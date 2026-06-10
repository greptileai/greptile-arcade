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
  - sprite node: group,num,w,h(u16),axisX,axisY(i16),link(u16) fmt,coldepth(u8)
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

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent
ART = ROOT / "greptile-game-images"
CHARACTER_ASSETS = ROOT / "assets/characters"
DEFAULT_VARIANT = "lizard"
CHAR_AIR = ROOT / "extracted/chars/greptile/greptile.air"
CHAR_SFF = ROOT / "extracted/chars/greptile/greptile.sff"
FIGHT_SFF = ROOT / "extracted/data/fight.sff"
FIGHT_DEF = ROOT / "extracted/data/fight.def"
SYSTEM_DEF = ROOT / "extracted/data/ikemen1/system.def"
KOMODO_START_SFF = ROOT / "extracted/data/ikemen1/komodo_start.sff"
KOMODO_VS_SFF = ROOT / "extracted/data/ikemen1/komodo_vs.sff"
KOMODO_WINNER_SFF = ROOT / "extracted/data/ikemen1/komodo_winner.sff"
SIG = b"ElecbyteSpr\x00"
ROUND_HISTORY_GROUP = 9300
ROUND_HISTORY_ACTIONS = {9300, 9301, 9302}
WINNER_IDLE_ACTION = 9400
GENERATED_ACTIONS = ROUND_HISTORY_ACTIONS | {WINNER_IDLE_ACTION}
GLITTER_SPECS = [
    (1, "glitter-01.png", (45, 45)),
    (2, "glitter-02.png", (38, 38)),
    (3, "glitter-03.png", (30, 30)),
    (4, "glitter-04.png", (53, 53)),
    (5, "glitter-05.png", (53, 53)),
    (6, "glitter-06.png", (23, 23)),
    (7, "glitter-07.png", (23, 23)),
    (8, "glitter-08.png", (23, 23)),
    (9, "glitter-09.png", (38, 38)),
    (10, "glitter-10.png", (23, 23)),
    (11, "glitter-11.png", (38, 60)),
]
WINNER_BG_COLOR = (126, 147, 255, 255)
WINNER_GRID_ALPHA = 0.72
WINNER_TITLE_POS = (258, 196)
WINNER_RESTART_POS = (506, 398)
WINNER_POSE_LEFT_POS = (20, 228)
WINNER_POSE_RIGHT_EDGE_X = 1260
WINNER_POSE_CANVAS = (456, 456)
WINNER_POSE_BASELINE_Y = 418
WINNER_GLITTER_PREVIEW_POSITIONS = [
    (470, 40),
    (870, 405),
    (690, 92),
    (1165, 20),
    (1110, 565),
    (419, 490),
    (972, 70),
    (32, 212),
    (37, 470),
    (1202, 300),
    (42, 22),
]
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


def repo_asset_path(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def strip_inline_comment(line):
    return line.split(";", 1)[0].strip()


def parse_def_sections(path):
    sections = {}
    current = None
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = strip_inline_comment(raw)
        if not line:
            continue
        if line.startswith("[") and "]" in line:
            current = line[1 : line.index("]")].strip().lower()
            sections.setdefault(current, {})
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        sections[current][key.strip().lower()] = value.strip()
    return sections


def parse_num_pair(value, cast=float):
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        raise ValueError(f"expected two comma-separated values, got {value!r}")
    return cast(parts[0]), cast(parts[1])


def parse_int_quad(value):
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError(f"expected four comma-separated values, got {value!r}")
    return tuple(int(part) for part in parts)


def section_value(sections, section, key, default=None):
    return sections.get(section.lower(), {}).get(key.lower(), default)


def sff_sprite(path, group, number):
    sprites, _ = read_sff_v2(path)
    for sprite in sprites:
        if sprite["group"] == group and sprite["number"] == number:
            return sprite
    raise ValueError(f"{display_path(path)} is missing sprite {group},{number}")


def sff_sprite_image(path, group, number):
    sprite = sff_sprite(path, group, number)
    payload = sprite["payload"]
    if not payload:
        raise ValueError(f"{display_path(path)} sprite {group},{number} has no payload")
    png_len = struct.unpack_from("<I", payload, 0)[0]
    png = payload[4 : 4 + png_len]
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    if img.size != (sprite["w"], sprite["h"]):
        raise ValueError(
            f"{display_path(path)} sprite {group},{number}: header size "
            f"{sprite['w']}x{sprite['h']} does not match PNG {img.size}"
        )
    return sprite, img


def image_matches_source(img, source):
    source = source.convert("RGBA")
    return img.size == source.size and img.tobytes() == source.tobytes()


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
        grp, num, w, h, ax, ay, link = struct.unpack_from("<4H2hH", data, off)
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
            "<4H2hH", s["group"], s["number"], s["w"], s["h"], s["ax"], s["ay"], s["link"]
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


def validate_character_assets(cfg=None, air_path=None):
    """Validate sheet geometry, group safety, frame references, and AIR coverage."""
    cfg = cfg or load_action_map()
    air_path = Path(air_path) if air_path is not None else character_target(cfg)["air"]
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
    winner_pose = cfg.get("winner_pose")
    if winner_pose:
        winner_pose_path = repo_asset_path(winner_pose)
        if not winner_pose_path.exists():
            raise FileNotFoundError(
                f"{variant}: missing winner pose image {display_path(winner_pose_path)}"
            )
        winner = Image.open(winner_pose_path).convert("RGBA")
        if winner.width <= 0 or winner.height <= 0:
            raise ValueError(f"{display_path(winner_pose_path)}: empty winner pose image")

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
        and a not in GENERATED_ACTIONS
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

    patched = ensure_generated_air_actions("".join(chunks), cfg)
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


def winner_idle_air_frames(cfg):
    if cfg["_variant"] == "bug":
        return [(0, 13), (-3, 6), (-5, 6), (-3, 6), (0, 13)]
    return [(0, 12), (-4, 6), (-6, 6), (-4, 6), (0, 12)]


def generated_air_block(cfg):
    winner_frames = "\n".join(
        f"9000,3, 0,{y_offset}, {duration}"
        for y_offset, duration in winner_idle_air_frames(cfg)
    )
    return f"""
; BEGIN KOMODO GENERATED ACTIONS
[Begin Action 9300]
{ROUND_HISTORY_GROUP},0, 0,0, -1

[Begin Action 9301]
{ROUND_HISTORY_GROUP},1, 0,0, -1

[Begin Action 9302]
{ROUND_HISTORY_GROUP},2, 0,0, -1

[Begin Action {WINNER_IDLE_ACTION}]
LoopStart
{winner_frames}
; END KOMODO GENERATED ACTIONS
"""


def ensure_generated_air_actions(text, cfg):
    text = re.sub(
        r"\n?; BEGIN KOMODO (?:ROUND HISTORY HUD|GENERATED ACTIONS).*?; END KOMODO (?:ROUND HISTORY HUD|GENERATED ACTIONS)\s*",
        "\n",
        text,
        flags=re.S,
    )
    return text.rstrip() + "\n" + generated_air_block(cfg)


def validate_air_uses_variant_groups(cfg=None, path=None):
    cfg = cfg or load_action_map()
    path = Path(path) if path is not None else character_target(cfg)["air"]
    mapped_actions = {int(action) for action in cfg["actions"]}
    preserve_actions = {int(action) for action in cfg.get("preserve_actions", [])}
    variant_groups = {int(spec["group"]) for spec in cfg["sprites"].values()}
    variant = cfg["_variant"]
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")
    bad = []
    for match in ACTION_RE.finditer(text):
        action = int(match.group(1))
        next_match = ACTION_RE.search(text, match.end())
        body = text[match.end() : next_match.start() if next_match else len(text)]
        if action in ROUND_HISTORY_ACTIONS:
            allowed_groups = {ROUND_HISTORY_GROUP}
        elif action == WINNER_IDLE_ACTION:
            allowed_groups = {9000}
        elif action in mapped_actions or action in preserve_actions:
            allowed_groups = variant_groups
        else:
            allowed_groups = variant_groups
        for line in body.splitlines():
            sprite = SPRITE_LINE_RE.match(line)
            if not sprite:
                continue
            group = int(sprite.group(2))
            if group != -1 and group not in allowed_groups:
                bad.append((action, line.strip()))
    if bad:
        preview = ", ".join(f"{a}: {line}" for a, line in bad[:12])
        raise ValueError(f"AIR still references non-{variant}/HUD sprites: {preview}")
    print(
        f"[validate] AIR sprite refs use {variant} groups "
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


def alpha_bbox_area(bbox):
    if bbox is None:
        return 0
    return max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])


def intersect_bbox(a, b):
    return (
        max(a[0], b[0]),
        max(a[1], b[1]),
        min(a[2], b[2]),
        min(a[3], b[3]),
    )


def validate_victory_screen(system_def=SYSTEM_DEF):
    """Guard the post-match winner portrait against invisible/off-screen sprites."""
    sections = parse_def_sections(system_def)
    info = sections.get("info", {})
    victory = sections.get("victory screen", {})
    if not info:
        raise ValueError(f"{display_path(system_def)}: missing [Info] section")
    if not victory:
        raise ValueError(f"{display_path(system_def)}: missing [Victory Screen] section")

    motif_localcoord = parse_num_pair(info.get("localcoord", "1280,720"), int)
    p1_localcoord = parse_num_pair(victory.get("p1.localcoord", "0,0"), int)
    p1_offset = parse_num_pair(victory.get("p1.offset", "0,0"), float)
    p1_pos = parse_num_pair(victory.get("p1.pos", "0,0"), float)
    p1_scale = parse_num_pair(victory.get("p1.scale", "1,1"), float)
    p1_window = parse_int_quad(victory.get("p1.window", "0,0,1279,719"))

    spr = parse_num_pair(victory.get("p1.spr", "-1,0"), int)
    required = {
        "enabled": "1",
        "p1.anim": "-1",
        "p1.num": "1",
        "p1.layerno": "2",
        "p1.applypal": "0",
    }
    bad = [
        f"{key}={victory.get(key)} (expected {expected})"
        for key, expected in required.items()
        if victory.get(key) != expected
    ]
    if bad:
        raise ValueError("[Victory Screen] winner portrait misconfigured: " + "; ".join(bad))
    if spr != (9000, 3):
        raise ValueError(f"[Victory Screen] p1.spr must be 9000,3, got {spr}")
    if p1_localcoord != motif_localcoord:
        raise ValueError(
            "[Victory Screen] p1.localcoord must match motif localcoord "
            f"{motif_localcoord}, got {p1_localcoord}"
        )

    bg_layer_violations = []
    for section, values in sections.items():
        if not section.startswith("victorybg "):
            continue
        layer = int(values.get("layerno", "0"))
        if layer >= 2:
            bg_layer_violations.append(f"[{section}] layerno={layer}")
    if bg_layer_violations:
        raise ValueError(
            "VictoryBG layer 2+ can cover the winner portrait: "
            + ", ".join(bg_layer_violations)
        )

    screen_bbox = (0.0, 0.0, float(motif_localcoord[0]), float(motif_localcoord[1]))
    window_bbox = tuple(float(v) for v in p1_window)
    clip_bbox = intersect_bbox(screen_bbox, window_bbox)
    visible = []
    for name, target in CHARACTER_TARGETS.items():
        char_def = target["dir"] / f"{name}.def"
        char_sections = parse_def_sections(char_def)
        char_localcoord = parse_num_pair(
            section_value(char_sections, "Info", "localcoord", "320,240"),
            int,
        )
        engine_scale = motif_localcoord[0] / char_localcoord[0]
        effective_scale = (p1_scale[0] * engine_scale, p1_scale[1] * engine_scale)
        sprite, img = sff_sprite_image(target["sff"], 9000, 3)
        alpha_bbox = img.getchannel("A").getbbox()
        if alpha_bbox is None:
            raise ValueError(f"{display_path(target['sff'])} sprite 9000,3 is fully transparent")
        x = p1_pos[0] + p1_offset[0]
        y = p1_pos[1] + p1_offset[1]
        placed = (
            x + (alpha_bbox[0] - sprite["ax"]) * effective_scale[0],
            y + (alpha_bbox[1] - sprite["ay"]) * effective_scale[1],
            x + (alpha_bbox[2] - sprite["ax"]) * effective_scale[0],
            y + (alpha_bbox[3] - sprite["ay"]) * effective_scale[1],
        )
        clipped = intersect_bbox(placed, clip_bbox)
        total_area = alpha_bbox_area(placed)
        visible_area = alpha_bbox_area(clipped)
        visible_fraction = visible_area / total_area if total_area else 0
        if visible_fraction < 0.95:
            raise ValueError(
                f"{name} winner sprite would be clipped/off-screen: "
                f"placed={tuple(round(v, 1) for v in placed)}, "
                f"visible={visible_fraction:.1%}, effective_scale={effective_scale}"
            )
        if not (0.15 <= effective_scale[0] <= 2.0 and 0.15 <= effective_scale[1] <= 2.0):
            raise ValueError(
                f"{name} winner sprite effective scale looks unsafe: {effective_scale}"
            )
        visible.append(
            f"{name} 9000,3 visible {visible_fraction:.0%} "
            f"bbox={tuple(round(v) for v in placed)}"
        )
    print("[validate] victory screen winner portrait: " + "; ".join(visible))


def action_sprite_refs(def_text, action):
    matches = list(ACTION_RE.finditer(def_text))
    for i, match in enumerate(matches):
        if int(match.group(1)) != action:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(def_text)
        body = def_text[match.end() : end]
        refs = []
        for line in body.splitlines():
            sprite = SPRITE_LINE_RE.match(strip_inline_comment(line))
            if sprite:
                refs.append((int(sprite.group(2)), int(sprite.group(3))))
        return refs
    raise ValueError(f"missing [Begin Action {action}] in fight.def")


def validate_result_banners(fight_def=FIGHT_DEF, fight_sff=FIGHT_SFF):
    """Ensure round-end text cannot route a lizard win to the bug banner."""
    sections = parse_def_sections(fight_def)
    round_section = sections.get("round", {})
    if not round_section:
        raise ValueError(f"{display_path(fight_def)}: missing [Round] section")

    ai_keys = sorted(
        key
        for key in round_section
        if re.match(r"ai\.(?:win|lose)\d*\.", key)
    )
    if ai_keys:
        raise ValueError(
            "AI-specific win banners bypass side-specific lizard/bug art: "
            + ", ".join(ai_keys[:12])
        )

    for suffix in ("", "2", "3", "4"):
        p1_key = f"p1.win{suffix}.bg1.anim"
        p2_key = f"p2.win{suffix}.bg1.anim"
        if round_section.get(p1_key) != "582":
            raise ValueError(f"{p1_key} must use lizard action 582")
        if round_section.get(p2_key) != "583":
            raise ValueError(f"{p2_key} must use bug action 583")

    text = Path(fight_def).read_text(encoding="utf-8-sig")
    expected_refs = {582: {(530, 1)}, 583: {(530, 2)}}
    for action, expected in expected_refs.items():
        refs = {ref for ref in action_sprite_refs(text, action) if ref[0] != -1}
        if refs != expected:
            raise ValueError(
                f"action {action} must reference only {sorted(expected)}, got {sorted(refs)}"
            )

    packed_expectations = [
        (530, 1, "result-lizard-wins.png", (707, 102), (353, 51)),
        (530, 2, "result-bug-wins.png", (646, 102), (323, 51)),
    ]
    for group, number, filename, size, axis in packed_expectations:
        sprite, img = sff_sprite_image(fight_sff, group, number)
        if img.size != size or (sprite["ax"], sprite["ay"]) != axis:
            raise ValueError(
                f"{display_path(fight_sff)} sprite {group},{number}: "
                f"expected size={size} axis={axis}, got size={img.size} "
                f"axis={(sprite['ax'], sprite['ay'])}"
            )
        source = load_hud_png(filename, size)
        if not image_matches_source(img, source):
            raise ValueError(
                f"{display_path(fight_sff)} sprite {group},{number} does not match {filename}"
            )
    print("[validate] result banners: P1 uses lizard art, P2 uses bug art, AI overrides disabled")


def validate_screenpack():
    validate_victory_screen()
    validate_result_banners()


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


def load_winner_pose(cfg):
    sprite_spec = cfg.get("winner_pose_sprite")
    if sprite_spec:
        frame_size = int(cfg["frame_size"])
        sheet_path = cfg["_source_dir_abs"] / sprite_spec["sheet"]
        if not sheet_path.exists():
            raise FileNotFoundError(f"missing winner pose sheet: {display_path(sheet_path)}")
        sheet = Image.open(sheet_path).convert("RGBA")
        frame = int(sprite_spec.get("frame", 0))
        if frame < 0 or (frame + 1) * frame_size > sheet.width:
            raise ValueError(f"{display_path(sheet_path)}: invalid winner pose frame {frame}")
        img = sheet.crop((frame * frame_size, 0, (frame + 1) * frame_size, frame_size))
        scale = int(sprite_spec.get("scale", cfg.get("scale", 4)))
        if scale <= 0:
            raise ValueError(f"winner pose scale must be positive, got {scale}")
        return orient_winner_pose(
            normalize_winner_pose(
                img.resize((frame_size * scale, frame_size * scale), Image.NEAREST)
            ),
            cfg,
        )

    winner_pose = cfg.get("winner_pose")
    if winner_pose:
        return orient_winner_pose(
            normalize_winner_pose(Image.open(repo_asset_path(winner_pose)).convert("RGBA")),
            cfg,
        )

    img = load_character_portrait(cfg)
    return orient_winner_pose(normalize_winner_pose(fit_image_contain(img, WINNER_POSE_CANVAS)), cfg)


def normalize_winner_pose(img):
    """Put each mascot winner pose on a shared canvas so the victory offset works for all chars."""
    img = img.convert("RGBA")
    if img.width > WINNER_POSE_CANVAS[0] or img.height > WINNER_POSE_CANVAS[1]:
        img = fit_image_contain(img, WINNER_POSE_CANVAS)
    bbox = img.getchannel("A").getbbox()
    canvas = Image.new("RGBA", WINNER_POSE_CANVAS, (0, 0, 0, 0))
    if bbox is None:
        return canvas
    y = max(0, min(WINNER_POSE_CANVAS[1] - img.height, WINNER_POSE_BASELINE_Y - bbox[3]))
    canvas.alpha_composite(img, (0, y))
    return canvas


def orient_winner_pose(img, cfg):
    """Mirror the winner pose when a right-side variant should face inward."""
    side = cfg.get("winner_pose_side", "left")
    mirror = bool(cfg.get("winner_pose_mirror", side == "right"))
    if mirror:
        img = ImageOps.mirror(img)
    return img


def winner_pose_axis(cfg, img):
    """Shift a normal-sized winner sprite to the requested side via SFF axis metadata."""
    side = cfg.get("winner_pose_side", "left")
    if side == "right":
        return WINNER_POSE_LEFT_POS[0] - (WINNER_POSE_RIGHT_EDGE_X - img.width), 0
    return 0, 0


def character_portrait_sprites(cfg):
    img = load_character_portrait(cfg)
    small = fit_image_contain(img, (25, 25))
    hud = fit_image_contain(img, (100, 100))
    large = fit_image_contain(img, (120, 140))
    winner = load_winner_pose(cfg)
    winner_ax, winner_ay = winner_pose_axis(cfg, winner)
    return [
        image_sprite(9000, 0, small, 0, 0),
        image_sprite(9000, 1, large, 0, 0),
        image_sprite(9000, 2, hud, 0, 0),
        image_sprite(9000, 3, winner, winner_ax, winner_ay),
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


def load_ui_png(section, name, expected_size=None):
    path = ART / "ui" / section / name
    if not path.exists():
        raise FileNotFoundError(f"missing UI source art: {display_path(path)}")
    img = Image.open(path).convert("RGBA")
    if expected_size is not None and img.size != expected_size:
        raise ValueError(f"{display_path(path)}: expected {expected_size}, got {img.size}")
    return img


def apply_alpha(img, factor):
    if factor == 1:
        return img
    out = img.copy()
    out.putalpha(out.getchannel("A").point(lambda value: round(value * factor)))
    return out


def load_glitter_png(number, filename, expected_size):
    img = load_ui_png("glitter", filename, expected_size)
    if img.mode != "RGBA":
        raise ValueError(f"{filename}: expected RGBA glitter image")
    return img


def glitter_sprites(group):
    return [
        image_sprite(group, 19 + number, load_glitter_png(number, filename, size), 0, 0)
        for number, filename, size in GLITTER_SPECS
    ]


def load_winner_city_floor():
    img = load_ui_png("winner", "city-floor.png", (1280, 700))
    canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    canvas.alpha_composite(img, (0, 0))
    tail_height = 40
    tail = img.crop((0, img.height - tail_height, img.width, img.height))
    tail = tail.resize((img.width, 720 - img.height + tail_height), Image.NEAREST)
    canvas.alpha_composite(tail, (0, img.height - tail_height))
    return canvas


def build_start_screen(dst=KOMODO_START_SFF):
    """Pack the Komodo startup screen into a dedicated screenpack SFF."""
    city = Image.open(ART / "Screen.png").convert("RGBA")
    city = city.resize((1280, 720), Image.NEAREST)
    specs = [
        (1000, 0, city),
        (1000, 1, load_ui_png("start", "title.png", (671, 319))),
        (1000, 2, load_ui_png("start", "dino.png", (281, 279))),
        (1000, 3, load_ui_png("start", "bug.png", (329, 274))),
        (1000, 4, load_ui_png("start", "play-button.png", (420, 95))),
    ]
    sprites = [image_sprite(group, number, img, 0, 0) for group, number, img in specs]
    sprites.extend(glitter_sprites(1000))
    write_sff_v2(dst, sprites, [])
    print(f"[start] {display_path(dst)}: packed {len(sprites)} startup screen sprites")


def build_vs_screen(dst=KOMODO_VS_SFF):
    """Pack the Komodo VS screen into a dedicated screenpack SFF."""
    specs = [
        (1100, 0, load_ui_png("vs", "city-packed.png", (1280, 720))),
        (1100, 1, load_ui_png("vs", "dino-portrait.png", (390, 388))),
        (1100, 2, load_ui_png("vs", "bug-portrait.png", (390, 388))),
        (1100, 3, load_ui_png("vs", "vs-text.png", (203, 130))),
        (1100, 4, load_ui_png("vs", "start-button.png", (271, 96))),
    ]
    sprites = [image_sprite(group, number, img, 0, 0) for group, number, img in specs]
    sprites.extend(glitter_sprites(1100))
    write_sff_v2(dst, sprites, [])
    print(f"[vs] {display_path(dst)}: packed {len(sprites)} VS screen sprites")


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
        (530, 1, "result-lizard-wins.png", (707, 102), 353, 51),
        (530, 2, "result-bug-wins.png", (646, 102), 323, 51),
    ]
    for group, number, filename, size, ax, ay in replacements:
        img = load_hud_png(filename, size)
        replace_sprite(sprites, image_sprite(group, number, img, ax, ay))
    write_sff_v2(dst, sprites, palettes)
    print(f"[hud] {display_path(dst)}: packed {len(replacements)} HUD sprites")


def build_winner_screen(dst=KOMODO_WINNER_SFF):
    """Pack the Komodo winner screen into a dedicated screenpack SFF."""
    specs = [
        (1200, 0, load_winner_city_floor(), 1),
        (1200, 1, load_ui_png("winner", "grid.png", (1278, 720)), WINNER_GRID_ALPHA),
        (1200, 2, load_ui_png("winner", "winner-text.png", (766, 148)), 1),
        (1200, 3, load_ui_png("winner", "restart-button.png", (271, 96)), 1),
    ]
    sprites = [
        image_sprite(group, number, apply_alpha(img, alpha), 0, 0)
        for group, number, img, alpha in specs
    ]
    sprites.extend(glitter_sprites(1200))
    sprites.append(image_sprite(1200, 98, winner_screen_preview("bug"), 0, 0))
    sprites.append(image_sprite(1200, 99, winner_screen_preview("lizard"), 0, 0))
    write_sff_v2(dst, sprites, [])
    print(f"[winner] {display_path(dst)}: packed {len(sprites)} winner screen sprites")


def winner_screen_preview(variant):
    preview = Image.new("RGBA", (1280, 720), WINNER_BG_COLOR)
    for img, pos, alpha in [
        (load_winner_city_floor(), (0, 0), 1),
        (load_ui_png("winner", "grid.png"), (0, 0), WINNER_GRID_ALPHA),
        (load_ui_png("winner", "winner-text.png"), WINNER_TITLE_POS, 1),
        (load_ui_png("winner", "restart-button.png"), WINNER_RESTART_POS, 1),
    ]:
        preview.alpha_composite(apply_alpha(img, alpha), pos)
    for (number, filename, size), pos in zip(GLITTER_SPECS, WINNER_GLITTER_PREVIEW_POSITIONS):
        preview.alpha_composite(apply_alpha(load_glitter_png(number, filename, size), 0.45), pos)
    preview_cfg = load_action_map(variant)
    preview_winner = load_winner_pose(preview_cfg)
    preview_ax, preview_ay = winner_pose_axis(preview_cfg, preview_winner)
    preview.alpha_composite(
        preview_winner,
        (WINNER_POSE_LEFT_POS[0] - preview_ax, WINNER_POSE_LEFT_POS[1] - preview_ay),
    )
    return preview


def build_screenpack_screens():
    build_start_screen()
    build_vs_screen()
    build_winner_screen()


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
        build_screenpack_screens()
        validate_screenpack()
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
        validate_result_banners()
    elif what == "start":
        build_start_screen()
    elif what == "vs":
        build_vs_screen()
    elif what == "winner":
        build_winner_screen()
        validate_victory_screen()
    elif what == "screens":
        build_screenpack_screens()
        validate_screenpack()
    elif what in ("validate-screenpack", "screenpack-validate"):
        validate_screenpack()
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
            "usage: build_assets.py [all|char|air|stage|hud|fight|start|vs|winner|screens|validate|validate-air|validate-screenpack] "
            f"[variant]  # variants: {variants}"
        )


if __name__ == "__main__":
    main(sys.argv)
