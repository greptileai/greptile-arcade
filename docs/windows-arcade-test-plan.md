# Windows Arcade Readiness Test Plan

This checklist verifies the Greptile/Komodo Kombat Ikemen-GO game package on a
Windows laptop before final cabinet testing.

The repo contains the game data and macOS runtime under `extracted/`, but it
does not contain the Windows runtime. On Windows, use the official Ikemen-GO
Windows build and overlay this repo's game data onto it.

## Goals

- Prove the game launches on Windows using `Ikemen_GO.exe`.
- Prove the shipped `greptile` vs `bug` matchup loads with the Greptile city
  stage, HUD, title screen, VS flow, and winner flow.
- Prove the keyboard controls match the arcade cabinet handoff.
- Catch fullscreen, audio, input rollover, and packaging problems before the
  final cabinet test.

## Required Files

- Official Ikemen-GO Windows ZIP:
  - Download `Ikemen_GO-dev-windows.zip` from:
    <https://github.com/ikemen-engine/Ikemen-GO/releases>
- This repo:
  - <https://github.com/greptileai/greptile-game>
  - Test the PR/branch intended for the cabinet build, currently:
    `codex/production-cabinet-readiness`

Do not download these for Windows testing:

- `Ikemen_GO-dev-android.zip`
- `Ikemen_GO-dev-linux.zip`
- `Ikemen_GO-dev-macos.zip`
- `src_ffmpeg.tar.gz`
- `Source code (zip)`
- `Source code (tar.gz)`

## Windows Folder Layout

Use a clean local folder outside `Program Files`, OneDrive, Dropbox, iCloud, or
any synced desktop folder.

Recommended layout:

```text
C:\Games\KomodoKombat
C:\Games\greptile-game
```

`C:\Games\KomodoKombat` is the runnable Windows package.

`C:\Games\greptile-game` is the source repo.

## Prepare The Windows Runtime

1. Download `Ikemen_GO-dev-windows.zip`.
2. Extract it into:

```text
C:\Games\KomodoKombat
```

3. Confirm this file exists:

```text
C:\Games\KomodoKombat\Ikemen_GO.exe
```

4. Do not extract over an older Ikemen folder. If you need to retry, delete
   `C:\Games\KomodoKombat` and start from a fresh unzip.

## Get The Game Repo Onto Windows

Option A: clone with Git.

```bat
cd C:\Games
git clone https://github.com/greptileai/greptile-game.git
cd greptile-game
git checkout codex/production-cabinet-readiness
```

Option B: copy the repo folder from another machine.

If copying manually, make sure the copied repo includes:

```text
extracted\chars
extracted\data
extracted\external
extracted\font
extracted\sound
extracted\stages
extracted\video
extracted\save
```

## Overlay Game Data Onto The Windows Runtime

Open PowerShell and run:

```powershell
$repo = "C:\Games\greptile-game"
$game = "C:\Games\KomodoKombat"

robocopy "$repo\extracted\chars" "$game\chars" /MIR
robocopy "$repo\extracted\data" "$game\data" /MIR
robocopy "$repo\extracted\external" "$game\external" /MIR
robocopy "$repo\extracted\font" "$game\font" /MIR
robocopy "$repo\extracted\sound" "$game\sound" /MIR
robocopy "$repo\extracted\stages" "$game\stages" /MIR
robocopy "$repo\extracted\video" "$game\video" /MIR
robocopy "$repo\extracted\save" "$game\save" /MIR

Copy-Item "$repo\extracted\LICENSES.txt" "$game\LICENSES.txt" -Force
```

Robocopy may return exit code `1` when files copy successfully. That is normal.
Treat exit codes `0` and `1` as success.

Do not copy macOS-only runtime files into the Windows package:

```text
I.K.E.M.E.N-Go.app
Ikemen_GO.command
```

## Sanity Check The Copied Package

Confirm these paths exist:

```text
C:\Games\KomodoKombat\Ikemen_GO.exe
C:\Games\KomodoKombat\chars\greptile\greptile.def
C:\Games\KomodoKombat\chars\greptile\greptile.sff
C:\Games\KomodoKombat\chars\bug\bug.def
C:\Games\KomodoKombat\chars\bug\bug.sff
C:\Games\KomodoKombat\stages\greptile_city.def
C:\Games\KomodoKombat\stages\greptile_city.sff
C:\Games\KomodoKombat\data\ikemen1\system.def
C:\Games\KomodoKombat\data\fight.def
C:\Games\KomodoKombat\save\config.ini
```

Also confirm `save\config.ini` contains the cabinet settings:

```ini
Players           = 2
EscOpensMenu      = 0
Fullscreen              = 1
GameWidth               = 1280
GameHeight              = 720
AllowDebugMode      = 0
AllowDebugKeys      = 0
```

## Command-Line Smoke Test

Open Command Prompt:

```bat
cd C:\Games\KomodoKombat
Ikemen_GO.exe -windowed -nosound -p1 greptile -p2 bug -p1.ai 5 -p2.ai 5 -s stages/greptile_city.def -rounds 1 -time 10 -log smoke.log
```

Pass criteria:

- A game window opens.
- Greptile/lizard loads as player 1.
- Bug loads as player 2.
- The Greptile city stage loads.
- One round completes.
- The process exits by itself.
- `C:\Games\KomodoKombat\smoke.log` exists.

Fail criteria:

- Windows blocks or quarantines `Ikemen_GO.exe`.
- The game opens to the wrong screenpack.
- Either character is missing or appears as KFM/fallback art.
- Stage is missing or black.
- The app crashes, hangs, or exits before a round completes.

## Fullscreen Cabinet Flow Test

Run the game normally:

```bat
cd C:\Games\KomodoKombat
Ikemen_GO.exe
```

Pass criteria:

- The game starts fullscreen.
- The title screen shows the custom Komodo Kombat art.
- The title screen has a single `Play` option.
- No arcade/options/training/watch/debug menu is visible.
- Pressing P1 Start (`1`) starts a match.
- After relaunching, pressing P2 Start (`2`) also starts a match.
- The match is always `greptile` versus `bug` on `greptile_city`.

If fullscreen fails, retry with the command-line smoke test in windowed mode to
separate a rendering/fullscreen issue from a data-loading issue.

## Cabinet Handoff Key Map

The arcade handoff image maps buttons as keyboard input.

Player 1:

| Cabinet control | Expected key |
| --- | --- |
| Credit side button | `5` |
| Start | `1` |
| Utility blue | `Enter` |
| Utility red | `Esc` |
| Up | `Up Arrow` |
| Down | `Down Arrow` |
| Left | `Left Arrow` |
| Right | `Right Arrow` |
| Top left attack | `Z` |
| Top middle attack | `X` |
| Top right attack | `C` |
| Bottom left attack | `V` |
| Bottom middle attack | `B` |
| Bottom right attack | `Space` |

Player 2:

| Cabinet control | Expected key |
| --- | --- |
| Credit side button | `6` |
| Start | `2` |
| Utility green | `Tab` |
| Utility yellow | `P` |
| Up | `R` |
| Down | `F` |
| Left | `D` |
| Right | `G` |
| Top left attack | `A` |
| Top middle attack | `S` |
| Top right attack | `Q` |
| Bottom left attack | `W` |
| Bottom middle attack | `I` |
| Bottom right attack | `K` |

## Notepad Input Test

Before launching the game, open Notepad and press every physical control.

Pass criteria:

- Every cabinet button emits the expected key above.
- No button emits multiple unexpected keys.
- Holding a direction does not spam unrelated keys.
- Both players can press controls at the same time without one side dropping.

Special note: arrow keys, `Enter`, `Esc`, `Tab`, and `Space` will not all display
as visible text in Notepad. Use cursor movement, focus changes, or a keyboard
tester website/app if needed to confirm those keys.

## In-Game Control Test

Start a match and test every control.

Player 1:

- `Up`, `Down`, `Left`, `Right` move the lizard.
- `Z`, `X`, `C`, `V`, `B`, and `Space` each trigger visible actions.
- `1` starts from the title screen.

Player 2:

- `R`, `F`, `D`, `G` move the bug.
- `A`, `S`, `Q`, `W`, `I`, and `K` each trigger visible actions.
- `2` starts from the title screen.

Non-combat controls:

- `Esc` must not expose a pause menu or exit path during normal play.
- `P` must not pause the game.
- `Tab` must not expose debug/options behavior.
- `Enter` must not expose a menu during normal play.
- `5` and `6` are credit buttons from the hardware handoff, but the current game
  flow is free-play. They should not be required to start a match.

## Simultaneous Input / Rollover Test

This is the most important Windows/cabinet-specific risk because the cabinet
encoder behaves like a keyboard.

Test these combinations in a live match:

```text
P1 Left + P1 attack while P2 Right + P2 attack
P1 Down + P1 attack while P2 Down + P2 attack
P1 holds one direction while mashing all six P1 attack buttons
P2 holds one direction while mashing all six P2 attack buttons
Both players press Start during a match
Both players press three attack buttons at once
Both players hold opposite horizontal directions at the same time
```

Pass criteria:

- No player loses directional input unexpectedly.
- No attack button becomes dead while another key is held.
- No stuck input remains after releasing the controls.
- No Windows/system shortcut is triggered.
- No menu/pause/exit/debug screen appears.

Fail criteria:

- Inputs are dropped when many buttons are held.
- P1 controls affect P2, or P2 controls affect P1.
- The game pauses, exits, opens a menu, or loses focus.
- The Windows taskbar, Start menu, sticky keys, or accessibility prompts appear.

## Audio And Display Test

Run a normal match on the laptop and then on the cabinet.

Pass criteria:

- Audio plays through the intended speakers.
- Audio does not crackle, disappear, or switch devices.
- Fullscreen stays active.
- No mouse cursor is visible over gameplay.
- The game is centered and fills the expected cabinet display area.
- HUD and winner screens are not clipped.
- Text is readable from normal arcade distance.

If the cabinet display is not 1280x720, record the actual display resolution and
whether the image is stretched, letterboxed, cropped, or off-center.

## Soak Test

Run an AI match for 30-60 minutes:

```bat
cd C:\Games\KomodoKombat
Ikemen_GO.exe -p1 greptile -p2 bug -p1.ai 5 -p2.ai 5 -s stages/greptile_city.def -rounds 2 -time -1
```

Watch for:

- Crashes
- Freezes
- Audio failure
- Frame drops
- Fullscreen loss
- Controls becoming unresponsive
- Match not returning cleanly to the title/winner flow

## Cabinet Test

After the Windows laptop passes, repeat the same tests on the actual cabinet.

Minimum cabinet pass:

- `Ikemen_GO.exe` launches from the cabinet frontend or final launch script.
- Game is fullscreen and correctly framed.
- P1 Start and P2 Start both launch from the `Play` screen.
- Both players can move and attack simultaneously.
- No control exposes an unwanted menu, pause, debug overlay, or exit path.
- A full match can be played by two people.
- A 30-minute AI or manual soak does not crash.

## What To Capture On Failure

Send back:

- Whether the failure happened on the Windows laptop or the cabinet.
- Exact step that failed.
- Exact key/button involved.
- Photo or video of the screen.
- `C:\Games\KomodoKombat\smoke.log`, if the command-line smoke test was run.
- Any new `.log` files in `C:\Games\KomodoKombat`.
- The Windows display resolution.
- Whether the game was launched by double-click, Command Prompt, or cabinet
  frontend.

## Known Current Behavior

- The production flow is currently free-play style: `Play` starts the fixed
  `greptile` versus `bug` match.
- The hardware credit keys `5` and `6` are recognized as cabinet buttons but are
  not required by the current game flow.
- The repo includes macOS runtime files, but Windows must use
  `Ikemen_GO.exe` from the official Windows ZIP.
- The base KFM assets are licensed CC BY-NC, so keep `LICENSES.txt` with the
  package.

