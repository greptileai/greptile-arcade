# Asset pipeline — turning PNGs into Ikemen `.sff` files

Ikemen-GO loads sprites **only** from `.sff` files, never from loose PNGs. The
designer hands us RGBA PNG sprite sheets; `build_assets.py` slices them, packs
them into SFF v2 as PNG32 sprites (format 12, RGBA -- no palette needed), and
patches the character `.air` animation file from a variant action map. The
default matchup is `greptile` (lizard art) vs `bug` (bug art).

## TL;DR

> **You only need this to rebuild assets.** Launching the game needs no Python at
> all — the engine is a native binary and the SFFs are already committed.

```bash
# one-time setup (Homebrew Python blocks global pip, so use a venv)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# build everything (lizard + bug characters, stage, HUD, screenpack screens)
.venv/bin/python build_assets.py all

# build one character
.venv/bin/python build_assets.py char lizard
.venv/bin/python build_assets.py char bug

# or just one part
.venv/bin/python build_assets.py char
.venv/bin/python build_assets.py air
.venv/bin/python build_assets.py stage
.venv/bin/python build_assets.py hud
.venv/bin/python build_assets.py start
.venv/bin/python build_assets.py vs
.venv/bin/python build_assets.py winner
.venv/bin/python build_assets.py screens
.venv/bin/python build_assets.py validate lizard
.venv/bin/python build_assets.py validate-air lizard
```

Output:
- `extracted/chars/greptile/greptile.sff` — KFM fallback sprites plus active skin sprites
- `extracted/chars/greptile/greptile.air` — sprite refs patched to active skin groups
- `extracted/chars/bug/bug.sff` — KFM fallback sprites plus bug skin sprites
- `extracted/chars/bug/bug.air` — sprite refs patched to bug groups
- `extracted/stages/greptile_city.sff` — city stage
- `extracted/data/fight.sff` — fight HUD sprites, including custom health bars
- `extracted/data/ikemen1/komodo_start.sff` — startup screen art
- `extracted/data/ikemen1/komodo_vs.sff` — VS/start prompt screen art
- `extracted/data/ikemen1/komodo_winner.sff` — post-match winner screen art

## Where things live

| Path | What |
|------|------|
| `greptile-game-images/lizard/` | Complete lizard character source sheets (24x24 RGBA strips) |
| `greptile-game-images/bug/` | Complete bug character source sheets (24x24 RGBA strips) |
| `assets/characters/lizard/action-map.json` | Lizard sheet → Ikemen action map (default) |
| `assets/characters/bug/action-map.json` | Bug sheet → Ikemen action map |
| `greptile-game-images/Screen.png` | Stage background |
| `greptile-game-images/ui/hud/` | Fight HUD source art |
| `greptile-game-images/ui/glitter/` | Shared screenpack glitter source art |
| `greptile-game-images/ui/start/` | Startup screen source art |
| `greptile-game-images/ui/vs/` | VS/start prompt screen source art |
| `greptile-game-images/ui/winner/` | Winner screen source art |
| `build_assets.py` | Converter and AIR patcher |
| `extracted/` | The runnable game + packed assets |
| `extracted/data/select.def` | Registers the `greptile` and `bug` chars plus `greptile_city` stage |

> Note: `~/dev/Ikemen-GO` (engine **source code**) is read-only reference only —
> we work in `~/dev/ikemen-release`. The SFF v2 format was learned from that
> repo's `src/image.go`.

## How the character build works

`build_character()` repacks KFM's `kfm.sff` into the target character SFF, byte-copying
**every** existing KFM sprite/palette and **appending** the selected complete
skin frame set as PNG32 sprites. Keeping KFM data in the SFF preserves fallback
data, but the target AIR file is patched so all 117 current action blocks
reference the selected skin groups or explicit blank `-1` frames.

The lizard and bug sheets are fixed 24x24 RGBA horizontal strips. The packer
preserves each full cell, including internal transparent offsets, and upscales
frames 4x to 96x96. Character maps can choose their axis mode; lizard uses
`content-bottom-center` so transparent padding below the feet does not make the
fighter float above the stage floor. Do not trim the cells; jump, knockdown,
dash, and hit motion is drawn inside the transparent cell.

The action maps are in `assets/characters/<variant>/action-map.json`. To change
which frames a game action uses, edit the variant map and rerun:

```bash
.venv/bin/python build_assets.py char lizard
.venv/bin/python build_assets.py char bug
```

## How the stage build works

`build_stage()` turns `greptile-game-images/Screen.png` into a stage SFF with the
background sprite axis centered (so the camera can pan without black edges).

## Running the game

```bash
cd extracted
./I.K.E.M.E.N-Go.app/Contents/MacOS/Ikemen_GO_MacOSARM \
  -p1 greptile -p2 bug -p1.ai 5 -p2.ai 5 \
  -s stages/greptile_city.def -rounds 2 -time -1 -nomusic
```

Renders at 1280×720. On macOS, CLI `screencapture` is blocked by Screen Recording
permission — watch live or use the engine's built-in screenshot.

## Updating Character Mapping

The lizard and bug sets are complete. The right edit surface is the action map,
not custom Python blocks:

1. Edit `assets/characters/<variant>/action-map.json`.
2. Run `.venv/bin/python build_assets.py validate <variant>` to validate sheets,
   frame references, group collisions, and action coverage.
3. Run `.venv/bin/python build_assets.py char <variant>`.
4. Verify in-game.

`char <variant>` also verifies that the patched AIR sprite refs use only the
selected variant's groups. To check that explicitly, run
`.venv/bin/python build_assets.py validate-air <variant>`.

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

Current source filenames:

| Source PNG | Packed sprite |
|------------|---------------|
| `health-empty.png` | `10,0` |
| `health-frame.png` | `11,0` |
| `health-trail.png` | `12,0` |
| `health-fill-green.png` | `13,0` |
| `health-fill-yellow.png` | `13,1` |
| `health-fill-red.png` | `13,2` |
| `health-fill-flash.png` | `13,3` |

Run `.venv/bin/python build_assets.py hud` to pack the health-bar PNGs into
`extracted/data/fight.sff`.

## License constraint

The base character is KFM (Elecbyte, CC BY-NC), so anything derived from it is
**non-commercial only**; the engine itself is MIT. Keep `extracted/LICENSES.txt`.
Fine for private / non-commercial use.
