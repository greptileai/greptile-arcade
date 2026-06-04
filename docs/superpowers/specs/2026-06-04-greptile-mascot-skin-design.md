# Greptile Mascot Skin + City Stage — Design

**Date:** 2026-06-04
**Goal:** Proof-of-life test that the designer's sprite-sheet art works in the Ikemen-GO engine. Skin Kung Fu Man's idle + walk with the Greptile mascot, and add the pastel city as a playable stage.

## Source assets
- `greptile-game-images/Idle_Spritesheet.png` — 48×24, RGBA → **2 frames** @ 24×24 (idle)
- `greptile-game-images/Walking_Spritesheet.png` — 96×24, RGBA → **4 frames** @ 24×24 (walk cycle)
- `greptile-game-images/Screen.png` — 1920×1080, RGBA → stage background

## Key engine facts (verified)
- Ikemen-GO loads sprites only from `.sff` files, not loose PNGs.
- `kfm.sff` is **SFF v2** (signature byte 15 = 0x02), which supports truecolor RGBA sprites — no palette conversion needed.
- SFF v2 loader decodes **embedded PNG** sprites directly (`Ikemen-GO/src/image.go:1216–1251`, `png.Decode`). So we embed PNG bytes (format 12, RGBA); no RLE/LZ5 codec required.
- KFM animations: Action 0 = stand/idle (group 0), Action 20 = walk fwd, Action 21 = walk back (`kfm.air`).

## Approach (A + C)

### Tooling
`build_assets.py` (Python + Pillow):
- Slice sheets into individual frames, upscale **4×** nearest-neighbor (24→96px, crisp pixel art, visible scale).
- Minimal **SFF v2 writer** that embeds frames as PNG sprites (format 12).

### A — Character skin (clone, never clobber)
1. Copy `extracted/chars/kfm/` → `extracted/chars/greptile/`. KFM stays untouched.
2. Append mascot frames to a new `greptile.sff` under fresh groups: **idle = group 9000**, **walk = group 9001** (no collision with KFM sprites).
3. Rewrite ONLY Actions `0`, `20`, `21` in `greptile.air` to reference the mascot frames; axis at bottom-center (48,96) so it stands on the floor; loop walk in sheet order.
4. Point `greptile.def` at the new files; rename character.
5. All other animations untouched → character loads and fights cleanly, idles/walks as mascot, "turns back into KFM" for every other action.

### C — City stage
1. Build `extracted/stages/greptile_city.sff` with `Screen.png` as one sprite.
2. Write `extracted/stages/greptile_city.def` (BGdef referencing the sprite; `localcoord` set so 1920×1080 fills the screen).

### Seeing it
- Register `greptile` + stage in `select.def`; launch the `.app`; pick mascot on city stage in Training mode.

## Decisions
- Mascot scale: 4× (~96px). [approved]
- Walk order: sheet order, looping. [approved]

## Safety
KFM and all originals are copied, never overwritten. Rollback = delete `chars/greptile/` and the new stage files + revert `select.def`.

## Out of scope
- Full playable mascot character (all animations).
- Palette/indexed-color conversion (not needed for SFF v2 truecolor).
