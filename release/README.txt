Rome II Test Runner  -  version 0.7.2
=====================================

Starts Total War: Rome II by itself, plays a new campaign as the faction you pick for the number of turns you set,
and writes down what happened (screenshots, a faction report, saves, crash report). Made for testing mods: does the
campaign start, does the end turn get through, does the game crash.

Works with vanilla Rome II and with Divide et Impera (DeI). Consul Scriptum is not needed (it still works if you
use it). No Python, no install: one .exe.

MADE FOR VANILLA AND DeI. Mods that edit the startpos file (campaigns\<campaign>\startpos.esf) are not supported:
you can add them, but they may crash the game or the Test Runner.


WHAT YOU NEED
-------------
- Windows 10 or 11
- Total War: Rome II from Steam (current version), and Steam running
- For DeI, one of:
    the data folder version: _divide_et_impera_release_12_Part1.pack and _Part2.pack in the game's data folder
    the Steam version: the three DeI workshop items subscribed and downloaded (Part 1, Part 2, Part 3)
  The program finds DeI by itself. If both are installed you pick which one; never both together (the game
  crashes).


HOW TO USE
----------
1. Unzip anywhere and start Rome2TestRunner.exe. (Windows may warn about an unknown program: the exe is not
   signed. Click "More info" -> "Run anyway".)
2. Close Rome II if it is running. The runner starts and closes the game by itself.
3. Pick:
   Mods            Vanilla or DeI (DeI only shows when it is installed)
   Campaign        one campaign, or All campaigns
   Faction         one playable faction, All playable factions, or the first faction of each campaign
   Added mods      your own mods on top, see "ADD YOUR OWN MODS" below
   Turns           how many end turns per game
   Save            save the game every N turns (0 = no saves; 1 = every turn; 3 = every third turn)
   Legio Invicta   Off, 100 or 1000 times stronger: your faction's soldiers and ships, so it isn't wiped out. See
                   "GAME OVER AND LEGIO INVICTA" below.
4. Press "Start Test Run". Don't touch the game window while it runs (see USING THE PC DURING A RUN).
   Pause Test Run   the run waits after the current turn. The game stays open and dialogs are no longer
                    answered for you, so you can look around the map (don't end the turn yourself). The tools
                    (Faction report, Screenshot, Run Lua) work while paused. The button then says
                    "Continue Test Run": press it to go on.
   Stop Test Run    the run stops after the current turn (at once when paused), closes the game and puts
                    your files back.
   Quit game        (bottom right) closes Rome II, no save. During a run it does the same as Stop Test Run.
   Progress...      opens the Progress window (see PROGRESS WINDOW below).

During a run, dialogs are answered by themselves so the turn can go on: diplomacy offers declined, war declared on
you accepted, dilemmas get the first choice, battles are autoresolved, captives released, the intro is skipped.


USING THE PC DURING A RUN
-------------------------
You can use the PC for other things while a run goes. The program does not move your mouse or type on your
keyboard: it clicks the game's buttons from inside the game, sends the Esc that skips the intro straight to the
game window, and takes screenshots of the game window even when other windows are in front of it.
Don't:
- click, scroll or type in the game window, or press keys while it is the active window (Esc opens the game menu,
  Enter can end the turn). When a new game starts (All campaigns / All factions), the game window may come to the
  front: check where your typing goes.
- move, resize, minimize or maximize the game window (not tested: leave it as the program set it up).
- close the game from the game itself (its menu, Alt+F4) or from Task Manager. To end a run press Stop Test Run
  or Quit game (the same during a run): it closes the game and puts your files back.
- start Rome II or its launcher a second time.
- let the PC go to sleep or hibernate: the game stops with it. For long runs set Windows sleep to "Never"
  (Settings > System > Power). Locking the screen during a run has not been tested.
- change mods during a run: no Steam Workshop updates of the mods in use (Steam may update subscribed mods by
  itself), and don't add or remove .pack files in the game's data folder.
- edit user.script.txt or preferences.script.txt; the program puts them back at the end anyway.
Heavy programs (another game, video rendering) can make the turns slower.


GAME OVER AND LEGIO INVICTA
---------------------------
The test faction only ends turns: it doesn't recruit, move armies or build. In DeI a faction like that can be
wiped out (seen twice: Rome in the Grand Campaign, destroyed on turn 14 and on turn 19). The game then shows its
Defeat screen.
- The program notices the defeat at once, ends that game, and writes "<faction> was destroyed on turn N (game
  over)" in the log and in result.json, with defeat.png. A game over is not an error: the game counts as ok
  (no crash, no stuck turn), it just ends early. The run goes on with the next game, if any.
- To keep your faction alive for long runs, pick "Legio Invicta" 100 or 1000 times stronger. It loads a small mod
  that makes every unit of your faction (soldiers and ships) that many times stronger: +9900% (100 times) or
  +99900% (1000 times) to morale, attack, defence,
  shield, damage, armour, charge, accuracy, reload, ammo, ship health, ram damage, experience, general's aura and
  fatigue resistance, and +50% battle speed and range. It works through the game's difficulty table, so it needs
  no script and no Consul, and it only affects the human player's faction.
  The packs (@@0_PAW_legio_invicta.pack = 1000 times, @@0_PAW_legio_invicta_x100.pack = 100 times) are inside the
  program: the one you pick is copied into the game's data folder for the run and removed afterwards (if you have
  it in the data folder already, yours is used and left there). info.json says "super_soldiers": 100 or 1000.
  Only one of them may be loaded at a time: they change the same tables.
  Tested: DeI, Grand Campaign, Rome, 25 turns. Without Legio Invicta Rome was destroyed on turn 14; with it
  Rome kept all 5 regions to the end, and no faction even attacked it (the AI sees how strong it is).
  Also tested: DeI, Grand Campaign, Ebdani, 30 turns: without Legio Invicta Ebdani was destroyed on turn 24; with
  100 times and with 1000 times it kept its region to the end, no crash in either.
  Keep in mind: with Legio Invicta on, the campaign goes differently than without it. For testing whether a mod
  crashes or a turn gets stuck that doesn't matter.


ADD YOUR OWN MODS
-----------------
1. Put the mod's .pack in the game's data folder, or subscribe to it on the Steam Workshop.
2. Press "Add mods...". The list shows every mod pack found in the data folder and in the Steam Workshop folders.
   Pick one or more (Ctrl/Shift click) and press Add.
3. Order them with Up / Down. A mod higher up wins over the ones below it (and over DeI). "Remove" takes one out.
4. "Preview user.script.txt" shows the exact mod list the next run will use.
The added mods are remembered for the next time you open the program.

Mods marked STARTPOS (in red) edit the startpos file (campaigns\<campaign>\startpos.esf); the program finds them by
reading each pack's file list. They are NOT supported: the game or the run may crash, and the built-in campaign and
faction lists may not match them. You can still add them: the program warns you when you add one and again when
you press Start Test Run. If the game crashes with one loaded, the crash window says so: run again without it to check.

The program never edits your own user.script.txt (the mod list the game and the Steam launcher use for your
normal games). For a run it backs your file up, writes its own with: the Test Runner's pack, your added mods, DeI
(if picked), and two lines that skip the start movies; and puts your file back exactly as it was afterwards.


PROGRESS WINDOW
---------------
Shows how a game went, turn by turn: a map of who owns what next to a table of every faction. The faction numbers
and region owners are taken every turn, so you can check the map of every turn of the run: pick a turn on the left
(or Prev / Next, or the arrow keys) and see who owned what on that turn. This works during the run too.
- Press "Progress..." during a run (it updates by itself as turns come in) or afterwards (it opens the latest
  run). "Open run..." opens any earlier run folder; "Game" picks the campaign/faction when a run had several.
- Turns on the left ("stats" = faction numbers and region owners taken; "map" = a world map screenshot, runs made
  with 0.7.0). Prev / Next, or the arrow keys.
- Picture:
  "Drawn map" (the default): the game's own strategic map, read from your game files, with every region in its
  owner's colour (the faction colours of the game, DeI's with DeI: Carthage is white, as in the game). Every
  faction's armies are dots and its fleets squares, where they stood at the end of that turn. Your faction has a
  white outline and white-edged markers (black when your own colour is light, like Carthage's); click a faction in
  the table to outline it and its markers in yellow. It shows the whole map for every faction and campaign, every
  turn, and needs no screenshot. Runs made with 0.7.0 have no region owners: the window shows their screenshots
  instead. Runs made with 0.7.1 have no armies or fleets on the map.
  "World map (no fog)": the game's world map screenshot, in runs made with 0.7.0 (its "Map screenshot" option is
  gone: the world map opens around the camera, so for a faction far from the middle, like Ebdani, part of the
  map was cut off).
  "Campaign view": the screenshot after every turn.
- Table: Regions, Armies and Navies (forces led by a general; city garrisons don't count), Units (all units,
  garrisons too), Treasury, Food, Food shortage.
  (+n / -n) is the change since the previous turn with numbers. Your faction is blue, factions that are gone are
  grey, food shortage is red. Click a column to sort.
Faction names are shown from the game's faction keys (rom_arverni -> Arverni); click a row to see the key.


WHERE THE RESULTS GO
--------------------
Documents\rome2bridge_runs\<date>_<mods>\
  info.json            program, game and mod versions, the mod list used
  result.json          one line per game: ok or the error, turns done, time, crashes
  <campaign>__<faction>\
    turn1.png, turn2.png, ...     the campaign map after each turn
    turnN_stats.json              faction numbers and region owners for the Progress window (every turn)
    t1_report_*.txt               faction report at the start (factions, armies, garrisons, food, positions)
    bridge_log.txt                log of the game-side script
    stalled.png, stalled_ui.txt   only when a turn got stuck: what was on screen
    defeat.png                    only when your faction was destroyed: the Defeat screen

Saves go to the game's save folder (%APPDATA%\The Creative Assembly\Rome2\save_games) as
"TestRun <date> <faction> turn <n>.save". Load them from the game's Load menu with the same mods on.


WHAT IT CHANGES, AND PUTS BACK
------------------------------
For a run the program
- writes its own user.script.txt (the mod list; yours is backed up first),
- sets the game windowed 1920x1080 in preferences.script.txt,
- copies @rome2_bridge.pack (the game-side script) into the game's data folder, and with Legio Invicta on
  also @@0_PAW_legio_invicta.pack,
- sets the registry value the game needs to start with mods without the "out of date mods" question.
When the run ends (or you press Stop Test Run) it closes the game and puts user.script.txt, preferences.script.txt and
your save_games\auto_save.save back exactly as they were (checked by hash; the log says "hash ok"), and removes
the pack(s) again. A copy of both files is kept in the run folder.

Don't close the program during a run: press Stop Test Run and wait for "done" in the log.


THE GAME CRASHED TO DESKTOP (CTD)?
---------------------------------
When the game crashes during a run, a window opens and tells you:
- the campaign, the faction and when it happened (starting the campaign, or during which end turn),
- the mods that were loaded, in load order,
- the crash details from the game's crash file (error type and the game file that failed),
- a warning if an added mod edits the startpos file (the most likely cause then).
The same text is saved as crash.txt in the run folder and goes into "Make bug report". The run then goes on with
the next game, if any, and puts your files back at the end as usual. Rome II also crashes now and then on its
own: if it crashes again at the same place, press "Make bug report" and post the zip.


A TURN GOT STUCK / SOMETHING WENT WRONG?
---------------------------------------
Press "Make bug report". It zips the run folder's useful files (versions, mod list, results, logs, the stuck
screen and the list of what was on it). Post the zip with one line saying what you expected.
If a dialog the program does not know stops the turn, stalled_ui.txt names it, so it can be added.


TOOLS (for a game that is already running with the pack)
----------------------------------------------------------
Faction report, run a Lua file or a Lua line in the game (type it in the Lua box and press "Run Lua"; 'return x'
shows x in the log), screenshot, open the results folder, make a bug report. They also work while a run is
paused. "Run Lua" is not "Start Test Run": it only sends that Lua code to a game that is already running.


LIMITS
------
- Campaign map only. Battles are autoresolved, not fought.
- The test faction only ends turns (see GAME OVER AND LEGIO INVICTA).
- The Prologue has no faction choice.
- The campaign/faction lists are built in (Vanilla and DeI as of this version). New campaigns or factions from an
  added mod are not in them.


CREDITS
-------
- GooBad (bukowa) - Consul Scriptum (github.com/bukowa/ConsulScriptum), used with his permission: the Test Runner
  starts Consul the same way Consul's own all_scripted.lua does, finds the game and its UI the way Consul does, and
  turns the fog of war off with the same game call as Consul's /show_shroud. No Consul files are included.
- Creative Assembly - Total War: Rome II.
- Frodo45127 - RPFM, used to build the Test Runner's pack.
- The Divide et Impera team - DeI.
- Legio Invicta: my own super soldiers mod (PAW), improved with the stat list of the "Virtus" cheat I made for
  Consul Scriptum.


LICENSE
-------
GNU General Public License v3 (LICENSE.txt in this zip). Anyone may use, change and share it, with credit; changed
versions must stay under GPL v3 with their source code open. Source code: see the GitHub page.
