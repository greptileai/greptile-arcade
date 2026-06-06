# greptile-game — project guide for Claude

This repo reskins the **Ikemen-GO** fighting engine with Greptile mascot art.
This file is auto-loaded by Claude Code on clone, so any teammate's Claude starts
with the right context. Read **`docs/asset-pipeline.md`** for the full PNG→SFF
how-to; this is the orientation.

## What this repo is

- A runnable build of Ikemen-GO (`extracted/`) plus our custom assets.
- A converter, `build_assets.py`, that packs the designer's PNG sprite sheets
  into the `.sff` files the engine loads.
- **This is NOT the engine source.** The engine source lives elsewhere
  (`Ikemen-GO`, read-only reference); never edit engine internals here.

## Launching needs no setup

The engine is a native binary and the greptile SFFs are committed, so **playing
the game requires no Python, no venv, no rebuild** — just clone and run (see
below). The venv is only for the *asset tooling*.

## Changing assets (only this part needs Python)

Ikemen loads sprites **only from `.sff` files, never loose PNGs**. To change any
art you edit/add a PNG in `greptile-game-images/`, then run the packer:

```bash
# one-time: Homebrew Python blocks global pip, so use a venv
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python build_assets.py all     # or: char | stage
```

The venv itself is git-ignored on purpose (it has platform-specific native
binaries and hardcoded paths); `requirements.txt` is the tracked, reproducible
source of truth. Outputs `extracted/chars/greptile/greptile.sff` and
`extracted/stages/greptile_city.sff`. Full details, including the lifebar art
spec and how the KFM-repack trick works, are in **`docs/asset-pipeline.md`**.

## Running the game (macOS ARM)

**Simulated fight (AI vs AI)** — greptile vs Kung Fu Man on the city stage. Both
`-pN.ai 5` flags are what make it a hands-off simulation; the whole runnable game
(engine binary + SFFs + defs) is committed, so this works straight from a clone:

```bash
cd extracted
./I.K.E.M.E.N-Go.app/Contents/MacOS/Ikemen_GO_MacOSARM \
  -p1 greptile -p2 kfm -p1.ai 5 -p2.ai 5 \
  -s stages/greptile_city.def -rounds 99 -time -1 -nomusic
```

To play it yourself instead, drop `-p1.ai 5` (P1 becomes keyboard/gamepad). The
`bundle_run.sh` next to the binary is an alternative launcher that resolves paths
and falls back to the x64 binary.

Renders at 1280×720. macOS blocks CLI `screencapture` (Screen Recording
permission) — watch live or use the engine's built-in screenshot.

## Key paths

| Path | What |
|------|------|
| `greptile-game-images/` | Source art the designer exports (RGBA PNG sheets, `Screen.png`) |
| `build_assets.py` | PNG sheets → SFF v2 converter |
| `extracted/` | Runnable game + packed assets |
| `extracted/data/select.def` | Registers the `greptile` char + `greptile_city` stage |
| `extracted/data/fight.def` / `fight.sff` | Lifebar / HUD definition + sprites |
| `docs/asset-pipeline.md` | Full asset pipeline + lifebar art spec |

## Arcade / 6-button controls

The target arcade cabinets have **6 attack buttons per player**. Ikemen-GO
exposes 8 attack buttons (`a b c x y z d w`); the extra two — `d` and `w` — are
**not used** and must stay unbound. `extracted/save/config.ini` has `d`/`w` set
to `Not used` for all players (keyboard + joystick); keep them that way.

The greptile character already uses only `x y z a b c` (light/medium/heavy punch
and kick) plus `s` (start/taunt), so **no moves depend on `d`/`w`** — dropping
them costs nothing. If you add moves, assign them to the six standard buttons
only. The arcade's own `config.ini` lives on the machine; ours is the reference.

## Conventions & constraints

- Mascot sprites are PNG32/RGBA (SFF format 12) — no palettes needed.
- `greptile.sff` keeps **all** KFM sprites and appends mascot frames, so the
  character still fights as Kung Fu Man for any animation we haven't reskinned.
- License: base char is KFM (Elecbyte, **CC BY-NC** → non-commercial only);
  engine is MIT. Keep `extracted/LICENSES.txt`.
- Don't commit the `.venv/` or `__pycache__/`.
