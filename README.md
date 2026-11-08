# Rome II Test Runner (rome2-bridge)

A tool for testing **Total War: Rome II** mods. It starts the game by itself, begins a new campaign as the faction
you pick, plays the number of turns you set, and writes down what happened: screenshots, world maps without fog of
war, faction numbers per turn, saves, and a crash report when the game crashes to desktop.

Works with **vanilla Rome II** and **Divide et Impera (DeI)**, with or without Consul Scriptum. No Python needed:
one `.exe`.

> **Download:** see [Releases](../../releases). Unzip, start `Rome2TestRunner.exe`, read `README.txt`.

## What it does

- **Test runs:** one campaign or all of them, one faction or all playable ones, N end turns each. Dialogs are
  answered by themselves (diplomacy declined, war accepted, dilemma option 1, battles autoresolved, captives
  released, intro skipped).
- **Pause / Continue / Stop** a run; the game stays open while paused.
- **Save every N turns** (copied from the autosave to its own file, never Quick Save).
- **World map screenshot without fog of war every N turns** (the fog comes back right after).
- **Progress window:** each turn's world map next to a table of every faction (regions, armies, navies, units,
  treasury, food), with the change since the previous turn. Updates live during a run.
- **Game over:** if your faction is wiped out (it only ends turns, so in DeI it can be), the run notices it at once,
  notes "destroyed on turn N" and goes on with the next game.
- **Legio Invicta:** an option that makes your faction's soldiers and ships 1000 times stronger, so it survives
  long runs. A small mod (no script, no Consul) built in, copied into the game for the run and removed after.
- **Crash report:** when the game crashes, a window tells you where (campaign, faction, which end turn), which mods
  were loaded, and the crash details from the game's crash file.
- **Add your own mods** on top of vanilla or DeI. Mods that edit the startpos file are marked and warned about.
- **Your files are safe:** each run writes its own `user.script.txt`; yours, `preferences.script.txt` and your
  autosave are backed up first and put back afterwards (checked by hash).
- **Bug report:** one zip with what a bug report needs.

## Using the PC during a run

You can. The runner never moves your mouse or types on your keyboard: it clicks the game's buttons from inside the
game, posts the intro's Esc straight to the game window, and screenshots the game window even when it is covered.
Don't click or type in the game window, don't move, resize or minimize it, don't close the game from its own menu or
Task Manager (press Stop Test Run or Quit game: they close the game and put your files back), don't let the PC sleep, and don't change or update mods while a run goes. When a new game starts, the game
window may come to the front, so check where your typing goes. Details in `README.txt`.

## How it works

- `pack/` builds `@rome2_bridge.pack`, a small mod the runner copies into the game's `data` folder for a run (and
  removes afterwards). Its `lua_scripts/all_scripted.lua` is CA's vanilla file plus a short tail that starts
  Consul Scriptum (if installed) and then the bridge.
- `bridge/rome2_bridge.lua` runs inside the game: it answers Lua commands from a file, reads the UI, clicks buttons,
  and writes a heartbeat. It only reads the game and clicks, like a player.
- `rome2bridge/` is the Python side: the library (`core.py`), the test runner (`testrun.py`), the desktop window
  (`gui.py`, `progress.py`), and a command line (`python -m rome2bridge --help`).
- `bridge/rome2_mcp.py` is an MCP server (no dependencies) so any MCP client can control the game.
- `scripts/faction_report.lua` and `scripts/progress_stats.lua` are read-only faction reports.
- `extras/legio_invicta/` is the Legio Invicta mod as text tables (TSV); `tools\build_legio_invicta.ps1` builds
  `@@0_PAW_legio_invicta.pack` from them.

## Command line (from source)

Needs Python 3 on Windows (tested with 3.14; no extra packages) and Rome II from Steam.

```
python -m rome2bridge status
python -m rome2bridge gui
python -m rome2bridge testrun --help
python -m rome2bridge lua "return B.factions()"
```

The game and settings folders are found by themselves (Steam's library list). If not, set `ROME2_GAME_DIR` /
`ROME2_APP_DIR`, or copy `rome2bridge.example.json` to `rome2bridge.json`.

## Building

- The pack: `tools\build_pack.ps1` (needs [RPFM](https://github.com/Frodo45127/rpfm)'s `rpfm_cli.exe`; set
  `RPFM_CLI` and `ROME2_GAME_DIR` if they are not found).
- Legio Invicta: `tools\build_legio_invicta.ps1` (RPFM plus its Rome II schema `schema_rom2.ron`; set
  `RPFM_SCHEMA` if it is not found).
- The exe: `tools\build_exe.ps1` (makes a private venv with PyInstaller in `build\venv`).

## Credits

- **GooBad** ([bukowa](https://github.com/bukowa)) - [Consul Scriptum](https://github.com/bukowa/ConsulScriptum),
  used here with his permission. The parts of this tool that follow Consul: starting Consul from
  `all_scripted.lua` the same way Consul's own file does, the game-interface lookups of `consul._game()`, the Lua-registry search for `UIComponent`, and the fog of
  war switch (`show_shroud`, as Consul's `/show_shroud`). No Consul files are included.
- **Creative Assembly** - Total War: Rome II; the pack contains the game's vanilla `all_scripted.lua`.
- **Frodo45127** - RPFM, used to build the pack.
- **The Divide et Impera team** - DeI, supported as a base.
- **Legio Invicta** - my own super soldiers mod (PAW), improved with the stat list of the "Virtus" cheat I made
  for Consul Scriptum.

## License

[GNU General Public License v3](LICENSE), like Consul Scriptum. Anyone may use, change and share this tool, with
credit; changed versions must stay under GPL v3 with their source code open.
