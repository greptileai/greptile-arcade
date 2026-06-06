#!/usr/bin/env python3
"""
build_assets.py — pack the Greptile mascot sprite sheets into Ikemen-GO SFF v2 files.

Two jobs:
  1. Repack KFM's sprite file into greptile.sff, byte-copying every existing
     sprite/palette and APPENDING the mascot frames as PNG32 sprites. Because
     KFM's own sprites survive untouched, the character still fights as Kung Fu
     Man for every animation we don't override (idle/walk).
  2. Build a stage SFF from the city background PNG.

The SFF v2 layout is taken from the engine source (Ikemen-GO/src/image.go):
  header(512) | sprite nodes(28B each) | palette nodes(16B each) | LDATA blob
  - sprite node: group,num,w,h,axisX,axisY,link(u16) fmt,coldepth(u8)
                 dataOfs,dataLen(u32) palIdx,flags(u16); size==0 => linked
  - palette node: group,num,numcols,link(u16) ofs,size(u32); size==0 => linked
  - PNG sprite (fmt 12): payload = u32 length prefix + PNG bytes (engine seeks +4)
"""
import struct, sys, io
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent
ART = ROOT / "greptile-game-images"
SIG = b"ElecbyteSpr\x00"

# ---------------------------------------------------------------- SFF reading
def read_sff_v2(path):
    """Parse an SFF v2 file into (sprites, palettes) with raw payloads attached."""
    data = Path(path).read_bytes()
    if data[:12] != SIG:
        raise ValueError(f"{path}: not an SFF file")
    ver = data[12:16]                      # verlo3,verlo2,verlo1,verhi
    if ver[3] != 2:
        raise ValueError(f"{path}: expected SFF v2, got version byte {ver[3]}")
    (first_spr_ofs, num_spr, first_pal_ofs, num_pal, lofs, _d, tofs) = struct.unpack_from(
        "<7I", data, 36)
    sprites = []
    for i in range(num_spr):
        off = first_spr_ofs + i * 28
        grp, num, w, h, ax, ay, link = struct.unpack_from("<7H", data, off)
        fmt, coldepth = data[off + 14], data[off + 15]
        dofs, dlen = struct.unpack_from("<2I", data, off + 16)
        palidx, flags = struct.unpack_from("<2H", data, off + 24)
        if dlen == 0:                      # linked sprite -> no payload
            payload = b""
        else:
            base = tofs if (flags & 1) else lofs
            payload = data[base + dofs: base + dofs + dlen]
        sprites.append(dict(group=grp, number=num, w=w, h=h, ax=ax, ay=ay,
                            link=link, fmt=fmt, coldepth=coldepth,
                            palidx=palidx, payload=payload))
    palettes = []
    for i in range(num_pal):
        off = first_pal_ofs + i * 16
        grp, num, ncol, link = struct.unpack_from("<4H", data, off)
        pofs, psize = struct.unpack_from("<2I", data, off + 16)
        payload = b"" if psize == 0 else data[lofs + pofs: lofs + pofs + psize]
        palettes.append(dict(group=grp, number=num, ncol=ncol, link=link,
                            payload=payload))
    return sprites, palettes

# ---------------------------------------------------------------- SFF writing
def write_sff_v2(path, sprites, palettes):
    """Write sprites/palettes to an SFF v2 file. All payloads go into one LDATA
    blob (flags=0). Linked nodes (empty payload + link) are preserved."""
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
            dofs, dlen = 0, 0              # linked
        spr_nodes += struct.pack("<7H", s["group"], s["number"], s["w"], s["h"],
                                 s["ax"], s["ay"], s["link"])
        spr_nodes += bytes((s["fmt"], s["coldepth"]))
        spr_nodes += struct.pack("<2I", dofs, dlen)
        spr_nodes += struct.pack("<2H", s["palidx"], 0)   # flags=0 -> LDATA

    pal_nodes = bytearray()
    for p in palettes:
        if p["payload"]:
            pofs, psize = stash(p["payload"]), len(p["payload"])
        else:
            pofs, psize = 0, 0            # linked
        pal_nodes += struct.pack("<4H", p["group"], p["number"], p["ncol"], p["link"])
        pal_nodes += struct.pack("<2I", pofs, psize)

    tofs = lofs                            # no TDATA used
    header = bytearray(512)
    header[0:12] = SIG
    header[12:16] = bytes((0, 0, 0, 2))    # v2.0.0.0
    struct.pack_into("<7I", header, 36, first_spr_ofs, n_spr, first_pal_ofs,
                     n_pal, lofs, 0, tofs)
    Path(path).write_bytes(bytes(header) + bytes(spr_nodes) + bytes(pal_nodes) + bytes(ldata))

# ---------------------------------------------------------------- sheet slicing
def union_bbox(path):
    """Union of the non-transparent bounding boxes across all square frames of a
    sheet (frame size = sheet height), in frame-local coords (l, t, r, b)."""
    sheet = Image.open(path).convert("RGBA")
    fh = sheet.height
    ub = None
    for i in range(sheet.width // fh):
        bb = sheet.crop((i * fh, 0, (i + 1) * fh, fh)).getbbox()
        if bb:
            ub = bb if ub is None else (min(ub[0], bb[0]), min(ub[1], bb[1]),
                                        max(ub[2], bb[2]), max(ub[3], bb[3]))
    return ub

def slice_sheet(path, scale):
    """Slice a horizontal sheet of SQUARE frames (frame size = sheet height) and
    scale each by `scale`, nearest-neighbor to keep the pixel art crisp. The
    source frame size is auto-detected, so the high-res sheets (480x480 frames)
    and the original 24x24 sheets both pack correctly. Returns (frames, out_px)."""
    sheet = Image.open(path).convert("RGBA")
    fh = sheet.height
    n = sheet.width // fh
    out = round(fh * scale)
    frames = []
    for i in range(n):
        frame = sheet.crop((i * fh, 0, (i + 1) * fh, fh))
        if out != fh:
            frame = frame.resize((out, out), Image.NEAREST)
        buf = io.BytesIO()
        frame.save(buf, format="PNG")
        frames.append(buf.getvalue())
    return frames, out

def png_sprite(group, number, png_bytes, w, h, ax, ay):
    payload = struct.pack("<I", len(png_bytes)) + png_bytes   # 4-byte len prefix
    return dict(group=group, number=number, w=w, h=h, ax=ax, ay=ay,
                link=0, fmt=12, coldepth=32, palidx=0, payload=payload)

# ---------------------------------------------------------------- build steps
def build_character():
    src = ROOT / "extracted/chars/kfm/kfm.sff"
    dst = ROOT / "extracted/chars/greptile/greptile.sff"
    sprites, palettes = read_sff_v2(src)
    n_kfm = len(sprites)
    # greptile.air references the mascot sprites by fixed group numbers, so pin
    # them here rather than deriving from the source SFF — a future source SFF
    # with a higher max group would silently desync the packed groups from the
    # AIR (and the game would miss the idle/walk/dash sprites).
    idle_grp, walk_grp, dash_grp = 9100, 9101, 9102
    max_src_grp = max(s["group"] for s in sprites)
    if idle_grp <= max_src_grp:               # must sit above KFM's own groups
        raise ValueError(f"mascot group {idle_grp} collides with source SFF "
                         f"(max group {max_src_grp})")

    # The designer's sheets are high-res (480x480 frames) with the mascot drawn
    # inside transparent padding. Derive ONE scale + ground line from the idle
    # pose so the mascot renders at the ORIGINAL mascot's size (the first build
    # packed it ~56px tall) with its feet on the floor, then apply that same
    # transform to every sheet -> a constant size + baseline across idle/walk/dash.
    TARGET_CHAR_H = 56                         # in-game body height, px (matches original)
    idle_path = ART / "Idle_Spritesheet.png"
    ifh = Image.open(idle_path).height
    ul, ut, ur, ub = union_bbox(idle_path)    # idle content box (frame-local)
    scale = TARGET_CHAR_H / (ub - ut)         # idle content height -> target
    ax, ay = round(ifh / 2 * scale), round(ub * scale)   # bottom-center on foot line

    idle_frames, iout = slice_sheet(idle_path, scale)
    walk_frames, wout = slice_sheet(ART / "Walking_Spritesheet.png", scale)
    for i, png in enumerate(idle_frames):
        sprites.append(png_sprite(idle_grp, i, png, iout, iout, ax, ay))
    for i, png in enumerate(walk_frames):
        sprites.append(png_sprite(walk_grp, i, png, wout, wout, ax, ay))

    # Dash / forward-run (anim 100). Action 100 always references group 9102,
    # so fail fast if the required designer sheet is missing or misnamed.
    dash_sheet = ART / "Dashing_spritesheet.png"
    if not dash_sheet.exists():
        raise FileNotFoundError(f"required dash sheet missing: {dash_sheet}")
    dash_frames, dout = slice_sheet(dash_sheet, scale)
    for i, png in enumerate(dash_frames):
        sprites.append(png_sprite(dash_grp, i, png, dout, dout, ax, ay))
    n_dash = len(dash_frames)

    write_sff_v2(dst, sprites, palettes)
    print(f"[char] {dst.relative_to(ROOT)}: kept {n_kfm} KFM sprites + "
          f"{len(idle_frames)} idle + {len(walk_frames)} walk + {n_dash} dash")
    print(f"[char] groups idle={idle_grp} walk={walk_grp} dash={dash_grp}; "
          f"sprite {iout}x{iout} scale={scale:.3f} axis=({ax},{ay})")
    return idle_grp, walk_grp, len(idle_frames), len(walk_frames), iout, iout

def build_stage(scale=1.2):
    """Overfill the screen so camera panning never exposes an edge, and put the
    sprite axis at center so start=0 centers it (matching the engine's stage
    convention, e.g. stage0-720.sff: 3200px wide, axis at horizontal center)."""
    dst = ROOT / "extracted/stages/greptile_city.sff"
    img = Image.open(ART / "Screen.png").convert("RGBA")
    if scale != 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.NEAREST)
    buf = io.BytesIO(); img.save(buf, format="PNG")
    ax, ay = img.width // 2, img.height // 2          # centered axis
    spr = png_sprite(0, 0, buf.getvalue(), img.width, img.height, ax, ay)
    write_sff_v2(dst, [spr], [])
    print(f"[stage] {dst.relative_to(ROOT)}: {img.width}x{img.height} background, "
          f"axis=({ax},{ay})")
    return img.width, img.height

if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "char"):
        build_character()
    if what in ("all", "stage"):
        build_stage()
