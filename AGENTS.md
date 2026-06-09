# greptile-game — project guide for Codex

This repo reskins the **Ikemen-GO** fighting engine with Greptile mascot art.
This file is auto-loaded by Codex on clone, so any teammate's Codex starts
with the right context. Read **`docs/asset-pipeline.md`** for the full PNG→SFF
how-to; this is the orientation.

## What this repo is

- A runnable build of Ikemen-GO (`extracted/`) plus our custom assets.
- A converter, `build_assets.py`, that packs the designer's PNG sprite sheets
  into the `.sff` files the engine loads.
- **This is NOT the engine source.** The engine source lives elsewhere
  (`Ikemen-GO`, read-only reference); never edit engine internals here.

## The one thing to know about assets

Ikemen loads sprites **only from `.sff` files, never loose PNGs**. To change any
character action wiring, edit the variant map in
`assets/characters/<variant>/action-map.json`, then run the packer. The default
active variant is `lizard`; `bug` is available explicitly.

```bash
# one-time: Homebrew Python blocks global pip, so use a venv
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python build_assets.py all             # default: lizard + stage
.venv/bin/python build_assets.py char lizard     # active lizard skin
.venv/bin/python build_assets.py char bug        # alternate bug skin
```

Outputs `extracted/chars/greptile/greptile.sff`, patches
`extracted/chars/greptile/greptile.air` so every action uses the selected
variant's sprite groups, and builds `extracted/stages/greptile_city.sff`. Full
details, including the lifebar art spec and how the KFM-repack trick works, are in
**`docs/asset-pipeline.md`**.

## Running the game (macOS ARM)

```bash
cd extracted
./I.K.E.M.E.N-Go.app/Contents/MacOS/Ikemen_GO_MacOSARM \
  -p1 greptile -p2 kfm -p1.ai 5 -p2.ai 5 \
  -s stages/greptile_city.def -rounds 99 -time -1 -nomusic
```

Renders at 1280×720. macOS blocks CLI `screencapture` (Screen Recording
permission) — watch live or use the engine's built-in screenshot.

## Key paths

| Path | What |
|------|------|
| `greptile-game-images/lizard/` | Complete lizard character source sheets (24x24 RGBA strips) |
| `greptile-game-images/bug/` | Complete bug character source sheets (24x24 RGBA strips) |
| `assets/characters/<variant>/action-map.json` | Sprite sheet → Ikemen action map |
| `build_assets.py` | PNG sheets → SFF v2 converter + AIR patcher |
| `extracted/` | Runnable game + packed assets |
| `extracted/data/select.def` | Registers the `greptile` char + `greptile_city` stage |
| `extracted/data/fight.def` / `fight.sff` | Lifebar / HUD definition + sprites |
| `docs/asset-pipeline.md` | Full asset pipeline + lifebar art spec |

## Conventions & constraints

- Character sprites are PNG32/RGBA (SFF format 12) — no palettes needed.
- `greptile.sff` keeps **all** KFM sprites and appends the active variant's
  frames; `greptile.air` should reference only that variant's groups for visual
  actions.
- License: base char is KFM (Elecbyte, **CC BY-NC** → non-commercial only);
  engine is MIT. Keep `extracted/LICENSES.txt`.
- Don't commit the `.venv/` or `__pycache__/`.
