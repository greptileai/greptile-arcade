#!/usr/bin/env python3
"""
build_assets.py - pack Greptile game art into Ikemen-GO SFF v2 files.

The character build is manifest-driven for complete sprite sets:
  1. Repack KFM's sprite file into greptile.sff, preserving every existing
     KFM sprite/palette as fallback data.
  2. Append the selected variant's frames as PNG32 sprites in fixed groups from
     assets/characters/<variant>/action-map.json.
  3. Patch greptile.air in place, replacing sprite references action-by-action
     while preserving KFM timing, flags, and collision phases.

Ikemen loads sprites from .sff files, not loose PNGs.

The SFF v2 layout is taken from Ikemen-GO/src/image.go:
  header(512) | sprite nodes(28B each) | palette nodes(16B each) | LDATA blob
  - sprite node: group,num,w,h,axisX,axisY,link(u16) fmt,coldepth(u8)
                 dataOfs,dataLen(u32) palIdx,flags(u16); size==0 => linked
  - palette node: group,num,numcols,link(u16) ofs,size(u32); size==0 => linked
  - PNG sprite (fmt 12): payload = u32 length prefix + PNG bytes
"""
from __future__ import annotations

import codecs
import io
import json
import re
import struct
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
ART = ROOT / "greptile-game-images"
CHARACTER_ASSETS = ROOT / "assets/characters"
DEFAULT_VARIANT = "lizard"
CHAR_AIR = ROOT / "extracted/chars/greptile/greptile.air"
CHAR_SFF = ROOT / "extracted/chars/greptile/greptile.sff"
FIGHT_SFF = ROOT / "extracted/data/fight.sff"
SIG = b"ElecbyteSpr\x00"
ROUND_HISTORY_GROUP = 9300
ROUND_HISTORY_ACTIONS = {9300, 9301, 9302}
ROUND_HISTORY_AIR_BLOCK = f"""
; BEGIN KOMODO ROUND HISTORY HUD
[Begin Action 9300]
{ROUND_HISTORY_GROUP},0, 0,0, -1

[Begin Action 9301]
{ROUND_HISTORY_GROUP},1, 0,0, -1

[Begin Action 9302]
{ROUND_HISTORY_GROUP},2, 0,0, -1
; END KOMODO ROUND HISTORY HUD
"""
CHARACTER_TARGETS = {
    "greptile": {
        "dir": ROOT / "extracted/chars/greptile",
        "sff": ROOT / "extracted/chars/greptile/greptile.sff",
        "air": ROOT / "extracted/chars/greptile/greptile.air",
    },
    "bug": {
        "dir": ROOT / "extracted/chars/bug",
        "sff": ROOT / "extracted/chars/bug/bug.sff",
        "air": ROOT / "extracted/chars/bug/bug.air",
    },
}

ACTION_RE = re.compile(r"(?m)^\[Begin Action (\d+)\]")
SPRITE_LINE_RE = re.compile(
    r"^(\s*)(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)(.*)$"
)


def display_path(path):
    path = Path(path)
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


# ---------------------------------------------------------------- SFF reading
def read_sff_v2(path):
    """Parse an SFF v2 file into (sprites, palettes) with raw payloads."""
    data = Path(path).read_bytes()
    if data[:12] != SIG:
        raise ValueError(f"{path}: not an SFF file")
    ver = data[12:16]  # verlo3, verlo2, verlo1, verhi
    if ver[3] != 2:
        raise ValueError(f"{path}: expected SFF v2, got version byte {ver[3]}")

    first_spr_ofs, num_spr, first_pal_ofs, num_pal, lofs, _d, tofs = struct.unpack_from(
        "<7I", data, 36
    )

    sprites = []
    for i in range(num_spr):
        off = first_spr_ofs + i * 28
        grp, num, w, h, ax, ay, link = struct.unpack_from("<7H", data, off)
        fmt, coldepth = data[off + 14], data[off + 15]
        dofs, dlen = struct.unpack_from("<2I", data, off + 16)
        palidx, flags = struct.unpack_from("<2H", data, off + 24)
        if dlen == 0:
            payload = b""
        else:
            base = tofs if (flags & 1) else lofs
            payload = data[base + dofs : base + dofs + dlen]
        sprites.append(
            dict(
                group=grp,
                number=num,
                w=w,
                h=h,
                ax=ax,
                ay=ay,
                link=link,
                fmt=fmt,
                coldepth=coldepth,
                palidx=palidx,
                payload=payload,
            )
        )

    palettes = []
    for i in range(num_pal):
        off = first_pal_ofs + i * 16
        grp, num, ncol, link = struct.unpack_from("<4H", data, off)
        pofs, psize = struct.unpack_from("<2I", data, off + 8)
        payload = b"" if psize == 0 else data[lofs + pofs : lofs + pofs + psize]
        palettes.append(
            dict(group=grp, number=num, ncol=ncol, link=link, payload=payload)
        )
    return sprites, palettes


# ---------------------------------------------------------------- SFF writing
def write_sff_v2(path, sprites, palettes):
    """Write sprites/palettes to an SFF v2 file using a single LDATA blob."""
    n_spr, n_pal = len(sprites), len(palettes)
    first_spr_ofs = 512
    first_pal_ofs = first_spr_ofs + n_spr * 28
    lofs = first_pal_ofs + n_pal * 16

    ldata = bytearray()

    def stash(payload):
        ofs = len(ldata)
        ldata.extend(payload)
        return ofs

    spr_nodes = bytearray()
    for s in sprites:
        if s["payload"]:
            dofs, dlen = stash(s["payload"]), len(s["payload"])
        else:
            dofs, dlen = 0, 0
        spr_nodes += struct.pack(
            "<7H", s["group"], s["number"], s["w"], s["h"], s["ax"], s["ay"], s["link"]
        )
        spr_nodes += bytes((s["fmt"], s["coldepth"]))
        spr_nodes += struct.pack("<2I", dofs, dlen)
        spr_nodes += struct.pack("<2H", s["palidx"], 0)

    pal_nodes = bytearray()
    for p in palettes:
        if p["payload"]:
            pofs, psize = stash(p["payload"]), len(p["payload"])
        else:
            pofs, psize = 0, 0
        pal_nodes += struct.pack("<4H", p["group"], p["number"], p["ncol"], p["link"])
        pal_nodes += struct.pack("<2I", pofs, psize)

    tofs = lofs
    header = bytearray(512)
    header[0:12] = SIG
    header[12:16] = bytes((0, 0, 0, 2))
    struct.pack_into(
        "<7I", header, 36, first_spr_ofs, n_spr, first_pal_ofs, n_pal, lofs, 0, tofs
    )
    Path(path).write_bytes(bytes(header) + bytes(spr_nodes) + bytes(pal_nodes) + bytes(ldata))


# ---------------------------------------------------------------- config
def action_map_path(variant):
    return CHARACTER_ASSETS / variant / "action-map.json"


def load_action_map(variant=DEFAULT_VARIANT):
    path = action_map_path(variant)
    if not path.exists():
        raise FileNotFoundError(f"missing action map for variant '{variant}': {path}")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["_variant"] = variant
    cfg["_map_path"] = path
    cfg["_source_dir_abs"] = ROOT / cfg["source_dir"]
    return cfg


def character_target(cfg):
    character = cfg.get("character", "greptile")
    if character not in CHARACTER_TARGETS:
        raise ValueError(f"unknown character target for {cfg['_map_path']}: {character}")
    target = CHARACTER_TARGETS[character]
    if not target["dir"].exists():
        raise FileNotFoundError(f"missing character directory: {display_path(target['dir'])}")
    return target


def read_air_actions(path=CHAR_AIR):
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")
    return {int(m.group(1)) for m in ACTION_RE.finditer(text)}


def all_skin_sprite_groups():
    groups = set()
    for path in CHARACTER_ASSETS.glob("*/action-map.json"):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        groups.update(int(spec["group"]) for spec in cfg.get("sprites", {}).values())
    return groups


def sprite_line_count_by_action(path=CHAR_AIR):
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")
    matches = list(ACTION_RE.finditer(text))
    counts = {}
    for i, match in enumerate(matches):
        action = int(match.group(1))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        counts[action] = sum(1 for line in body.splitlines() if SPRITE_LINE_RE.match(line))
    return counts


def validate_character_assets(cfg=None, air_path=CHAR_AIR):
    """Validate sheet geometry, group safety, frame references, and AIR coverage."""
    cfg = cfg or load_action_map()
    source_dir = cfg["_source_dir_abs"]
    variant = cfg["_variant"]
    frame_size = int(cfg["frame_size"])
    scale = int(cfg["scale"])
    axis_mode = cfg.get("axis", "bottom-center")
    if frame_size <= 0 or scale <= 0:
        raise ValueError("frame_size and scale must be positive")
    if axis_mode not in ("bottom-center", "content-bottom-center"):
        raise ValueError(f"unsupported axis mode: {axis_mode}")
    portrait_name = cfg.get("portrait")
    if portrait_name:
        portrait_path = source_dir / portrait_name
        if not portrait_path.exists():
            raise FileNotFoundError(
                f"{variant}: missing portrait image {display_path(portrait_path)}"
            )
        portrait = Image.open(portrait_path).convert("RGBA")
        if portrait.width <= 0 or portrait.height <= 0:
            raise ValueError(f"{display_path(portrait_path)}: empty portrait image")

    groups = []
    frame_counts = {}
    for name, spec in cfg["sprites"].items():
        group = int(spec["group"])
        groups.append(group)
        path = source_dir / spec["sheet"]
        if not path.exists():
            raise FileNotFoundError(f"{name}: missing sprite sheet {path}")
        img = Image.open(path).convert("RGBA")
        if img.height != frame_size:
            raise ValueError(f"{path}: expected height {frame_size}, got {img.height}")
        if img.width % frame_size:
            raise ValueError(f"{path}: width {img.width} is not a multiple of {frame_size}")
        frames = img.width // frame_size
        if frames <= 0:
            raise ValueError(f"{path}: no frames")
        frame_counts[name] = frames

    if len(groups) != len(set(groups)):
        raise ValueError(f"duplicate {variant} sprite group in action map")

    src_sprites, _ = read_sff_v2(ROOT / "extracted/chars/kfm/kfm.sff")
    max_base_group = max(s["group"] for s in src_sprites)
    min_variant_group = min(groups)
    if min_variant_group <= max_base_group:
        raise ValueError(
            f"{variant} group {min_variant_group} collides with base SFF max group "
            f"{max_base_group}"
        )

    actions = cfg["actions"]
    preserve_actions = {int(a) for a in cfg.get("preserve_actions", [])}
    air_actions = read_air_actions(air_path)
    overlap = sorted(a for a in preserve_actions if str(a) in actions)
    missing = sorted(
        a
        for a in air_actions
        if str(a) not in actions
        and a not in preserve_actions
        and a not in ROUND_HISTORY_ACTIONS
    )
    extra = sorted(int(a) for a in actions if int(a) not in air_actions)
    extra_preserved = sorted(a for a in preserve_actions if a not in air_actions)
    if overlap:
        raise ValueError(f"actions cannot be both mapped and preserved: {overlap}")
    if missing:
        raise ValueError(f"action map missing AIR actions: {missing}")
    if extra:
        raise ValueError(f"action map includes actions not present in AIR: {extra}")
    if extra_preserved:
        raise ValueError(f"preserve_actions includes actions not present in AIR: {extra_preserved}")

    for action, mapping in actions.items():
        sprite_name = mapping["sprite"]
        if sprite_name not in cfg["sprites"]:
            raise ValueError(f"action {action}: unknown sprite {sprite_name}")
        frames = mapping["frames"]
        if not frames:
            raise ValueError(f"action {action}: no frames")
        max_frame = frame_counts[sprite_name] - 1
        bad = [f for f in frames if not isinstance(f, int) or f < 0 or f > max_frame]
        if bad:
            raise ValueError(
                f"action {action}: invalid frame(s) {bad} for {sprite_name} 0..{max_frame}"
            )

    print(
        f"[validate] {variant} map: {len(cfg['sprites'])} sheets, "
        f"{sum(frame_counts.values())} frames, {len(actions)} mapped actions, "
        f"scale={scale}x"
    )
    return frame_counts


# ---------------------------------------------------------------- sheet slicing
def frame_axis(cell, frame_size, scale, axis_mode):
    ax = frame_size * scale // 2
    if axis_mode == "content-bottom-center":
        bbox = cell.getbbox()
        ay = (bbox[3] if bbox else frame_size) * scale
    else:
        ay = frame_size * scale
    return ax, ay


def slice_fixed_sheet(path, frame_size, scale, axis_mode):
    """Return full, untrimmed square cells as PNG32 blobs with per-frame axes."""
    sheet = Image.open(path).convert("RGBA")
    if sheet.height != frame_size or sheet.width % frame_size:
        raise ValueError(f"{path}: expected {frame_size}px-high horizontal strip")
    n = sheet.width // frame_size
    out_size = frame_size * scale
    frames = []
    for i in range(n):
        cell = sheet.crop((i * frame_size, 0, (i + 1) * frame_size, frame_size))
        ax, ay = frame_axis(cell, frame_size, scale, axis_mode)
        if scale != 1:
            cell = cell.resize((out_size, out_size), Image.NEAREST)
        buf = io.BytesIO()
        cell.save(buf, format="PNG")
        frames.append((buf.getvalue(), ax, ay))
    return frames, out_size, out_size


def png_sprite(group, number, png_bytes, w, h, ax, ay):
    payload = struct.pack("<I", len(png_bytes)) + png_bytes
    return dict(
        group=group,
        number=number,
        w=w,
        h=h,
        ax=ax,
        ay=ay,
        link=0,
        fmt=12,
        coldepth=32,
        palidx=0,
        payload=payload,
    )


# ---------------------------------------------------------------- AIR patching
def patch_air_for_variant(cfg=None, path=None):
    cfg = cfg or load_action_map()
    path = Path(path) if path is not None else character_target(cfg)["air"]
    validate_character_assets(cfg, path)

    raw = Path(path).read_bytes()
    had_bom = raw.startswith(codecs.BOM_UTF8)
    text = raw.decode("utf-8-sig")
    matches = list(ACTION_RE.finditer(text))
    chunks = []
    cursor = 0

    for i, match in enumerate(matches):
        action = int(match.group(1))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunks.append(text[cursor:start])
        chunks.append(patch_air_block(text[start:end], action, cfg))
        cursor = end
    chunks.append(text[cursor:])

    patched = ensure_round_history_air_actions("".join(chunks))
    out = patched.encode("utf-8")
    if had_bom:
        out = codecs.BOM_UTF8 + out
    Path(path).write_bytes(out)
    print(f"[air] patched {display_path(path)} from {cfg['_map_path'].relative_to(ROOT)}")


def patch_air_block(block, action, cfg):
    mapping = cfg["actions"].get(str(action))
    if mapping is None:
        return block
    sprite_spec = cfg["sprites"][mapping["sprite"]]
    group = int(sprite_spec["group"])
    frames = list(mapping["frames"])
    preserve_blank = bool(cfg.get("preserve_blank_sprite_lines", True))
    replaced = 0
    out_lines = []

    for line in block.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        newline = line[len(body) :]
        match = SPRITE_LINE_RE.match(body)
        if not match:
            out_lines.append(line)
            continue
        old_group = int(match.group(2))
        if old_group == -1 and preserve_blank:
            out_lines.append(line)
            continue
        frame = frames[replaced % len(frames)]
        replaced += 1
        indent = match.group(1)
        x_offset = match.group(4)
        y_offset = match.group(5)
        duration = match.group(6)
        flags = match.group(7)
        out_lines.append(f"{indent}{group},{frame}, {x_offset},{y_offset}, {duration}{flags}{newline}")
    return "".join(out_lines)


def ensure_round_history_air_actions(text):
    text = re.sub(
        r"\n?; BEGIN KOMODO ROUND HISTORY HUD.*?; END KOMODO ROUND HISTORY HUD\s*",
        "\n",
        text,
        flags=re.S,
    )
    return text.rstrip() + "\n" + ROUND_HISTORY_AIR_BLOCK


def validate_air_uses_variant_groups(cfg=None, path=None):
    cfg = cfg or load_action_map()
    path = Path(path) if path is not None else character_target(cfg)["air"]
    mapped_actions = {int(action) for action in cfg["actions"]}
    preserve_actions = {int(action) for action in cfg.get("preserve_actions", [])}
    variant_groups = {int(spec["group"]) for spec in cfg["sprites"].values()}
    skin_groups = all_skin_sprite_groups()
    variant = cfg["_variant"]
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")
    bad = []
    preserved_bad = []
    for match in ACTION_RE.finditer(text):
        action = int(match.group(1))
        next_match = ACTION_RE.search(text, match.end())
        body = text[match.end() : next_match.start() if next_match else len(text)]
        if action not in mapped_actions and action not in preserve_actions:
            continue
        for line in body.splitlines():
            sprite = SPRITE_LINE_RE.match(line)
            if not sprite:
                continue
            group = int(sprite.group(2))
            if action in mapped_actions and group != -1 and group not in variant_groups:
                bad.append((action, line.strip()))
            if action in preserve_actions and group in skin_groups:
                preserved_bad.append((action, line.strip()))
    if bad:
        preview = ", ".join(f"{a}: {line}" for a, line in bad[:12])
        raise ValueError(f"AIR still references non-{variant} sprites: {preview}")
    if preserved_bad:
        preview = ", ".join(f"{a}: {line}" for a, line in preserved_bad[:12])
        raise ValueError(f"AIR preserved actions still reference skin sprites: {preview}")
    print(
        f"[validate] AIR mapped sprite refs use {variant} groups "
        f"{min(variant_groups)}..{max(variant_groups)}"
    )


def validate_sff_contains_variant_groups(cfg=None, path=None):
    cfg = cfg or load_action_map()
    path = Path(path) if path is not None else character_target(cfg)["sff"]
    variant_groups = {int(spec["group"]) for spec in cfg["sprites"].values()}
    variant = cfg["_variant"]
    sprites, _ = read_sff_v2(path)
    packed_groups = {int(sprite["group"]) for sprite in sprites}
    missing = sorted(variant_groups - packed_groups)
    if missing:
        preview = ", ".join(str(group) for group in missing[:12])
        raise ValueError(
            f"{display_path(path)} is missing {variant} sprite group(s): "
            f"{preview}; run build_assets.py char {variant} first"
        )
    print(
        f"[validate] SFF contains {variant} groups "
        f"{min(variant_groups)}..{max(variant_groups)}"
    )


def image_sprite(group, number, img, ax=0, ay=0):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return png_sprite(group, number, buf.getvalue(), img.width, img.height, ax, ay)

# ---------------------------------------------------------------- build steps
def replace_sprite(sprites, replacement):
    key = (replacement["group"], replacement["number"])
    for i, sprite in enumerate(sprites):
        if (sprite["group"], sprite["number"]) == key:
            sprites[i] = replacement
            return
    sprites.append(replacement)


def fit_image_contain(img, size):
    if hasattr(Image, "Resampling"):
        downsample = Image.Resampling.LANCZOS
        upsample = Image.Resampling.NEAREST
    else:
        downsample = Image.LANCZOS
        upsample = Image.NEAREST
    scale = min(size[0] / img.width, size[1] / img.height)
    resized_size = (
        max(1, round(img.width * scale)),
        max(1, round(img.height * scale)),
    )
    resample = downsample if scale < 1 else upsample
    resized = img.resize(resized_size, resample)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.alpha_composite(
        resized,
        ((size[0] - resized_size[0]) // 2, (size[1] - resized_size[1]) // 2),
    )
    return canvas


def load_character_portrait(cfg):
    portrait_name = cfg.get("portrait")
    if portrait_name:
        path = cfg["_source_dir_abs"] / portrait_name
        if not path.exists():
            raise FileNotFoundError(f"missing character portrait: {display_path(path)}")
        return Image.open(path).convert("RGBA")

    frame_size = int(cfg["frame_size"])
    idle_spec = cfg["sprites"].get("idle") or next(iter(cfg["sprites"].values()))
    sheet = Image.open(cfg["_source_dir_abs"] / idle_spec["sheet"]).convert("RGBA")
    return sheet.crop((0, 0, frame_size, frame_size))


def character_portrait_sprites(cfg):
    img = load_character_portrait(cfg)
    small = fit_image_contain(img, (25, 25))
    hud = fit_image_contain(img, (100, 100))
    large = fit_image_contain(img, (120, 140))
    return [
        image_sprite(9000, 0, small, 0, 0),
        image_sprite(9000, 1, large, 0, 0),
        image_sprite(9000, 2, hud, 0, 0),
    ]


def round_history_icon_sprites():
    colors = [
        (66, 58, 124, 190),   # empty
        (192, 255, 211, 255), # lizard
        (255, 253, 83, 255),  # bug
    ]
    outline = (126, 91, 225, 255)
    shadow = (36, 30, 78, 120)
    out = []
    for number, fill in enumerate(colors):
        img = Image.new("RGBA", (25, 8), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((2, 2, 22, 7), fill=shadow)
        draw.ellipse((1, 1, 23, 6), fill=fill, outline=outline)
        out.append(image_sprite(ROUND_HISTORY_GROUP, number, img, 12, 4))
    return out


def load_hud_png(name, expected_size):
    path = ART / "ui/hud" / name
    if not path.exists():
        raise FileNotFoundError(f"missing HUD source art: {display_path(path)}")
    img = Image.open(path).convert("RGBA")
    if img.size != expected_size:
        raise ValueError(f"{display_path(path)}: expected {expected_size}, got {img.size}")
    return img


def build_hud(dst=FIGHT_SFF):
    """Pack custom fight HUD art into fight.sff."""
    sprites, palettes = read_sff_v2(dst)
    replacements = [
        (10, 0, "health-empty.png", (435, 24), 435, 0),
        (11, 0, "health-frame.png", (439, 28), 439, 0),
        (12, 0, "health-trail.png", (435, 24), 435, 0),
        (13, 0, "health-fill-green.png", (435, 24), 435, 0),
        (13, 1, "health-fill-yellow.png", (435, 24), 435, 0),
        (13, 2, "health-fill-red.png", (435, 24), 435, 0),
        (13, 3, "health-fill-flash.png", (435, 24), 435, 0),
    ]
    for group, number, filename, size, ax, ay in replacements:
        img = load_hud_png(filename, size)
        replace_sprite(sprites, image_sprite(group, number, img, ax, ay))
    write_sff_v2(dst, sprites, palettes)
    print(f"[hud] {display_path(dst)}: packed {len(replacements)} health bar sprites")


def validate_air_variant_in_temp(cfg=None):
    cfg = cfg or load_action_map()
    variant = cfg["_variant"]
    target = character_target(cfg)
    with tempfile.TemporaryDirectory(prefix=f"greptile-{variant}-") as tmp:
        tmp = Path(tmp)
        tmp_sff = tmp / target["sff"].name
        tmp_air = tmp / target["air"].name
        tmp_air.write_bytes(target["air"].read_bytes())
        build_character(variant, dst=tmp_sff)
        validate_sff_contains_variant_groups(cfg, tmp_sff)
        patch_air_for_variant(cfg, tmp_air)
        validate_air_uses_variant_groups(cfg, tmp_air)


def build_character(variant=DEFAULT_VARIANT, dst=None):
    """Build a character SFF using the selected complete sprite set."""
    cfg = load_action_map(variant)
    target = character_target(cfg)
    dst = Path(dst) if dst is not None else target["sff"]
    frame_counts = validate_character_assets(cfg, target["air"])
    src = ROOT / "extracted/chars/kfm/kfm.sff"
    sprites, palettes = read_sff_v2(src)
    n_kfm = len(sprites)
    frame_size = int(cfg["frame_size"])
    scale = int(cfg["scale"])
    axis_mode = cfg.get("axis", "bottom-center")

    for sprite_name, spec in cfg["sprites"].items():
        group = int(spec["group"])
        path = cfg["_source_dir_abs"] / spec["sheet"]
        frames, w, h = slice_fixed_sheet(path, frame_size, scale, axis_mode)
        for i, (png, ax, ay) in enumerate(frames):
            sprites.append(png_sprite(group, i, png, w, h, ax, ay))
    for portrait in character_portrait_sprites(cfg):
        replace_sprite(sprites, portrait)
    for icon in round_history_icon_sprites():
        replace_sprite(sprites, icon)

    write_sff_v2(dst, sprites, palettes)
    added = sum(frame_counts.values())
    print(
        f"[char] {display_path(dst)}: kept {n_kfm} KFM sprites + "
        f"{added} {variant} frames across {len(cfg['sprites'])} groups; "
        f"frame={frame_size * scale}x{frame_size * scale}, axis={axis_mode}"
    )


def build_stage(scale=1.2):
    """Build the Greptile city stage SFF from Screen.png."""
    dst = ROOT / "extracted/stages/greptile_city.sff"
    img = Image.open(ART / "Screen.png").convert("RGBA")
    if scale != 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    ax, ay = img.width // 2, img.height // 2
    spr = png_sprite(0, 0, buf.getvalue(), img.width, img.height, ax, ay)
    write_sff_v2(dst, [spr], [])
    print(
        f"[stage] {dst.relative_to(ROOT)}: {img.width}x{img.height} background, "
        f"axis=({ax},{ay})"
    )


def command_variant(argv, index=2):
    return argv[index] if len(argv) > index else DEFAULT_VARIANT


def main(argv):
    what = argv[1] if len(argv) > 1 else "all"
    known_variants = {p.parent.name for p in CHARACTER_ASSETS.glob("*/action-map.json")}

    if what == "all":
        for variant in sorted(known_variants):
            build_character(variant)
            cfg = load_action_map(variant)
            patch_air_for_variant(cfg)
            validate_air_uses_variant_groups(cfg)
        build_stage()
        build_hud()
    elif what == "char":
        variant = command_variant(argv)
        build_character(variant)
        cfg = load_action_map(variant)
        patch_air_for_variant(cfg)
        validate_air_uses_variant_groups(cfg)
    elif what == "air":
        variant = command_variant(argv)
        cfg = load_action_map(variant)
        validate_sff_contains_variant_groups(cfg)
        patch_air_for_variant(cfg)
        validate_air_uses_variant_groups(cfg)
    elif what == "stage":
        build_stage()
    elif what in ("hud", "fight"):
        build_hud()
    elif what == "validate":
        variant = command_variant(argv)
        cfg = load_action_map(variant)
        validate_character_assets(cfg)
    elif what in ("validate-air", "air-validate"):
        variant = command_variant(argv)
        cfg = load_action_map(variant)
        validate_air_variant_in_temp(cfg)
    elif what in known_variants:
        variant = what
        build_character(variant)
        cfg = load_action_map(variant)
        patch_air_for_variant(cfg)
        validate_air_uses_variant_groups(cfg)
    else:
        variants = "|".join(sorted(known_variants))
        raise SystemExit(
            "usage: build_assets.py [all|char|air|stage|hud|fight|validate|validate-air] "
            f"[variant]  # variants: {variants}"
        )


if __name__ == "__main__":
    main(sys.argv)
