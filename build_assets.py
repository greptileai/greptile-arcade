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
def slice_sheet(path, frame_w, frame_h, scale):
    """Return a list of PNG32 byte-blobs, one per frame, upscaled nearest-neighbor."""
    sheet = Image.open(path).convert("RGBA")
    n = sheet.width // frame_w
    frames = []
    for i in range(n):
        box = (i * frame_w, 0, (i + 1) * frame_w, frame_h)
        frame = sheet.crop(box)
        if scale != 1:
            frame = frame.resize((frame_w * scale, frame_h * scale), Image.NEAREST)
        buf = io.BytesIO()
        frame.save(buf, format="PNG")
        frames.append(buf.getvalue())
    return frames, frame_w * scale, frame_h * scale

def png_sprite(group, number, png_bytes, w, h, ax, ay):
    payload = struct.pack("<I", len(png_bytes)) + png_bytes   # 4-byte len prefix
    return dict(group=group, number=number, w=w, h=h, ax=ax, ay=ay,
                link=0, fmt=12, coldepth=32, palidx=0, payload=payload)

# ---------------------------------------------------------------- build steps
def build_character(scale=4):
    src = ROOT / "extracted/chars/kfm/kfm.sff"
    dst = ROOT / "extracted/chars/greptile/greptile.sff"
    sprites, palettes = read_sff_v2(src)
    n_kfm = len(sprites)
    used_groups = {s["group"] for s in sprites}
    idle_grp = max(used_groups) + 100         # safely past any KFM group
    walk_grp = idle_grp + 1

    idle_frames, iw, ih = slice_sheet(ART / "Idle_Spritesheet.png", 24, 24, scale)
    walk_frames, ww, wh = slice_sheet(ART / "Walking_Spritesheet.png", 24, 24, scale)
    ax, ay = iw // 2, ih                      # axis: bottom-center -> stands on floor

    for i, png in enumerate(idle_frames):
        sprites.append(png_sprite(idle_grp, i, png, iw, ih, ax, ay))
    for i, png in enumerate(walk_frames):
        sprites.append(png_sprite(walk_grp, i, png, ww, wh, ww // 2, wh))

    write_sff_v2(dst, sprites, palettes)
    print(f"[char] {dst.relative_to(ROOT)}: kept {n_kfm} KFM sprites + "
          f"{len(idle_frames)} idle + {len(walk_frames)} walk")
    print(f"[char] idle group={idle_grp} (0..{len(idle_frames)-1}), "
          f"walk group={walk_grp} (0..{len(walk_frames)-1}), "
          f"frame={iw}x{ih}, axis=({ax},{ay})")
    return idle_grp, walk_grp, len(idle_frames), len(walk_frames), iw, ih

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
