# Asset pipeline — turning PNGs into Ikemen `.sff` files

Ikemen-GO loads sprites **only** from `.sff` files, never from loose PNGs. The
designer hands us RGBA PNG sprite sheets; `build_assets.py` slices them, scales
them to the in-game size, and packs them into SFF v2 with each frame embedded as a PNG32 sprite
(format 12, RGBA — no palette needed). This doc is the human-readable how-to;
`build_assets.py`'s docstring documents the binary SFF v2 layout.

## TL;DR

> **You only need this to rebuild assets.** Launching the game needs no Python at
> all — the engine is a native binary and the SFFs are already committed.

```bash
# one-time setup (Homebrew Python blocks global pip, so use a venv)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# build everything (character + stage)
.venv/bin/python build_assets.py all
# or just one:
.venv/bin/python build_assets.py char
.venv/bin/python build_assets.py stage
```

Output:
- `extracted/chars/greptile/greptile.sff` — mascot character
- `extracted/stages/greptile_city.sff` — city stage

## Where things live

| Path | What |
|------|------|
| `greptile-game-images/` | Source art the designer exports (RGBA PNG sprite sheets + `Screen.png` stage bg) |
| `build_assets.py` | The converter (PNG sheets → SFF v2) |
| `extracted/` | The runnable game + packed assets |
| `extracted/data/select.def` | Registers the `greptile` char and `greptile_city` stage |

> Note: `~/dev/Ikemen-GO` (engine **source code**) is read-only reference only —
> we work in `~/dev/ikemen-release`. The SFF v2 format was learned from that
> repo's `src/image.go`.

## How the character build works

`build_character()` repacks KFM's `kfm.sff` into `greptile.sff`, byte-copying
**every** existing KFM sprite/palette and **appending** the mascot frames as
PNG32 sprites. Because KFM's own sprites survive untouched, the character still
fights as Kung Fu Man for every animation we haven't overridden. Currently
overridden:

| Animation | Anim # | Sprite group | Source sheet |
|-----------|--------|--------------|--------------|
| Idle | 0 | `9100` | `Idle_Spritesheet.png` |
| Walk | 20 / 21 | `9101` | `Walking_Spritesheet.png` |
| Dash / run forward | 100 | `9102` | `Dashing_spritesheet.png` |

The groups are **pinned** (9100/9101/9102) to match `greptile.air`, and the dash
sheet is **required** — the build fails fast if it's missing, since Action 100
always references group 9102.

**Sizing & anchoring:** sheets are square frames in a horizontal strip; the frame
size is auto-detected (= sheet height), so any resolution works (current art is
480×480 per frame). Frames are scaled nearest-neighbor to the original on-screen
mascot height (~56px, derived from the idle pose). The horizontal axis is the
frame center; the **vertical axis is set per frame to that frame's own foot
line**, so the mascot stays planted on the floor through the walk/dash bob
instead of sinking or floating.

## How the stage build works

`build_stage()` turns `greptile-game-images/Screen.png` into a stage SFF with the
background sprite axis centered (so the camera can pan without black edges).

## Running the game

```bash
cd extracted
./I.K.E.M.E.N-Go.app/Contents/MacOS/Ikemen_GO_MacOSARM \
  -p1 greptile -p2 kfm -p1.ai 5 -p2.ai 5 \
  -s stages/greptile_city.def -rounds 99 -time -1 -nomusic
```

Renders at 1280×720. On macOS, CLI `screencapture` is blocked by Screen Recording
permission — watch live or use the engine's built-in screenshot.

## Adding new sprite sheets

1. Designer exports an RGBA PNG sprite sheet — square frames in a horizontal
   strip (any resolution; current art is 480×480 per frame) — into
   `greptile-game-images/`.
2. Add a slicing + packing block in `build_assets.py` (mirror how idle/walk are
   handled), choosing a free sprite group/number and wiring it into the
   character's `.air` animation.
3. Re-run `.venv/bin/python build_assets.py char` and verify in-game.

## Lifebar / health-bar art spec

Health bars are defined in `extracted/data/fight.def` (`[Lifebar]` section) with
sprites packed in `extracted/data/fight.sff`. Motif resolution (localcoord) is
1280×720. All bar sprites are PNG32/RGBA (format 12) — same export as the mascot.

The bar is **4 stacked PNG layers**, each the same rectangle so they overlay
pixel-perfect:

| Group,Num | Layer | Size |
|-----------|-------|------|
| `10,0` | bg0 — empty bar / track | 435×24 |
| `12,0` | mid — damage trail (bright solid, lags on hit) | 435×24 |
| `13,0/1/2/3` | front — health fill, 4 states: >50%, 25–50%, <25%, flashing tip | 435×24 each |
| `11,0` | top — frame / border / gloss, drawn over everything | 439×28 |

Rules for the artist:
1. Draw each fill bar **full length** — the engine clips it left-to-right by
   life % (`range.x = 15,-460`); it does not scale or pre-cut.
2. Every layer is the same rectangle.
3. PNG RGBA transparent, designed at 1280×720 motif scale (or 2× to downscale).
4. Draw **plain rectangles** — the engine applies a 3px slant (`xshear=3`)
   automatically; don't bake the slant in. P1 bar axis is at the right edge; P2
   mirrors automatically.

Deliverables: `bar_empty`, `bar_fill_green/yellow/red`, `bar_trail` (435×24),
`bar_frame` (439×28). Pack into `fight.sff` at groups 10–13 via the same pipeline.

## License constraint

The base character is KFM (Elecbyte, CC BY-NC), so anything derived from it is
**non-commercial only**; the engine itself is MIT. Keep `extracted/LICENSES.txt`.
Fine for private / non-commercial use.
