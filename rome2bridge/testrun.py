"""Unattended test runs: mod set x campaign x faction x turns. Used by the desktop window (gui.py) and the CLI
(`python -m rome2bridge testrun ...`).

Every run (one call of Runner.run):
  - backs up user.script.txt and preferences.script.txt into the run folder (and checks them by hash at the end)
  - installs @rome2_bridge.pack into data\\ if it isn't there (removed again at the end)
  - writes the mod set into user.script.txt (our pack first; other, non-mod lines are kept)
  - sets the game windowed 1920x1080 (the window/click tools assume it)
  - per campaign/faction: new campaign from the main menu as that faction, skip the intro, faction report,
    N end turns with the "test" auto-answer rules (always on: without them a dialog stops the turn), screenshots,
    crash check; results in result.json
  - optional: save every N turns (the game's autosave, copied to its own named file in save_games, so no save is
    overwritten; not Quick Save), and a world map screenshot every N turns without fog of war
    (game:show_shroud(false), as Consul's /show_shroud does; the fog is turned back on after the screenshot)
  - the user's own save_games/auto_save.save is backed up and put back (the game and the save option rewrite it)
  - quits the game and puts both files back (after the game has quit: it rewrites preferences on exit)
"""
import hashlib
import json
import os
import re
import shutil
import time

from .config import ROOT, USER_DIR
from . import __version__
from .core import Bridge, BridgeError

HERE = os.path.dirname(os.path.abspath(__file__))
OUR_PACK = "@rome2_bridge.pack"
# option "Legio Invicta": the user's super soldiers mod, improved (extras\legio_invicta, tools\build_legio_invicta.ps1):
# every unit of the human faction 1000 times stronger, so a faction that only ends turns is not wiped out early
SS_PACK = "@@0_PAW_legio_invicta.pack"


def ss_times(super_soldiers):
    """super_soldiers True = 1000 times; a number = that many times (tools\\build_legio_invicta.ps1 -Times N)."""
    return 1000 if super_soldiers is True else int(super_soldiers or 0)


def ss_name(super_soldiers):
    n = ss_times(super_soldiers)
    return SS_PACK if n in (0, 1000) else "@@0_PAW_legio_invicta_x%d.pack" % n


def ss_is(pack):
    """a Legio Invicta pack of any strength (only one may be loaded: they hold the same tables)"""
    p = (pack or "").lower()
    return p == SS_PACK.lower() or (p.startswith("@@0_paw_legio_invicta_x") and p.endswith(".pack"))

# mod sets (user, 2026-11-08). Never both DeI sets in one run: the game crashes.
MOD_SETS = {
    "Vanilla": {"mods": [], "workshop": []},
    "DeI (data folder)": {"mods": ["_divide_et_impera_release_12_Part1.pack", "_divide_et_impera_release_12_Part2.pack"],
                          "workshop": []},
    # Steam workshop items 362473569 (Part 1), 1405475000 (Part 2), 1405479496 (Part 3), in this order
    "DeI (Steam)": {"mods": ["___divide_et_impera_010_part1.pack", "___divide_et_impera_010_part9.pack",
                             "___divide_et_impera_010_part10.pack"],
                    "workshop": ["362473569", "1405475000", "1405479496"]},
}
FACTION_FILES = {"Vanilla": "vanilla.json", "DeI (data folder)": "dei_data.json", "DeI (Steam)": "dei_steam.json"}
MOD_LINE = re.compile(r'^\s*mod\s+"?([^";]+?)"?\s*;', re.I)


CRASH_CODES = {"c0000005": "access violation (the game used memory that was not there)",
               "c00000fd": "stack overflow", "c0000409": "stack buffer overrun", "e06d7363": "C++ exception",
               "80000003": "breakpoint", "c0000017": "out of memory", "c000001d": "illegal instruction"}


def crash_words(sig):
    """'<date>  code c0000005  Empire.Retail.dll+0x798cd2  [...]' (tools\\crashsig.py) in words, raw line kept."""
    m = re.search(r"code ([0-9a-f]{8})\s+(\S+?)\+(0x[0-9a-f]+)", sig or "")
    if not m:
        return sig or "?"
    code, module, off = m.groups()
    return "%s, error code %s, in %s at %s" % (CRASH_CODES.get(code, "error").capitalize(), code, module, off)



# campaign keys of the vanilla menu buttons (from the faction prefixes, 2026-11-08)
VANILLA_KEYS = {"button_new_campaign_main_rome": "main_rome", "button_new_campaign_main_emperor": "main_emperor",
                "button_dlc_campaign_0": "main_3c", "button_dlc_campaign_1": "main_invasion",
                "button_dlc_campaign_2": "main_gaul", "button_dlc_campaign_3": "main_punic",
                "button_dlc_campaign_4": "main_greek"}


def pack_files(path):
    """File paths inside a Rome II .pack (PFH4 header + file index; the files themselves are not read).
    Header: 'PFH4', flags, pack-index count + size, file count + index size, timestamp (28 bytes). Each file index
    entry: u32 size, u32 timestamp if flag 0x40, then the path (ASCII, NUL-terminated, '\\' separators)."""
    import struct
    with open(path, "rb") as f:
        h = f.read(28)
        if len(h) < 28 or h[:3] != b"PFH" or h[3:4] not in (b"4", b"5", b"3"):
            raise ValueError("not a Rome II pack file")
        flags, _, pi_size, n_files, fi_size = struct.unpack_from("<5I", h, 4)
        if flags & 0x100:  # extended header (not used by Rome II mods)
            f.read(20)
        f.read(pi_size)
        idx = f.read(fi_size)
    out, pos, stamp = [], 0, 8 if flags & 0x40 else 4
    for _ in range(n_files):
        pos += stamp
        end = idx.index(b"\0", pos)
        out.append(idx[pos:end].decode("ascii", "replace").replace("\\", "/"))
        pos = end + 1
    return out


def startpos_files(path):
    """The startpos files a pack contains (campaigns/<campaign>/startpos.esf): allowed, with a warning."""
    return [p for p in pack_files(path) if p.lower().endswith("startpos.esf")]


def pack_type(path):
    """Pack type from the header: 0 boot, 1 release, 2 patch, 3 mod, 4 movie (the game's own packs are not 3)."""
    import struct
    with open(path, "rb") as f:
        h = f.read(8)
    if len(h) < 8 or h[:3] != b"PFH":
        return None
    return struct.unpack_from("<I", h, 4)[0] & 0xF


# the user's added mods (window "Add mods..."): [{"pack": file name, "item": workshop item id or None}], top first
ADDED_FILE = os.path.join(USER_DIR, "added_mods.json")


def load_added():
    try:
        return [m for m in json.load(open(ADDED_FILE, encoding="utf-8")) if m.get("pack")]
    except (OSError, ValueError):
        return []


def save_added(mods):
    os.makedirs(os.path.dirname(ADDED_FILE), exist_ok=True)
    json.dump(mods, open(ADDED_FILE, "w", encoding="utf-8"), indent=1)


def sha(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest().upper()
    except OSError:
        return None


def factions_file(mod_set):
    """Where a faction list read from the game is saved (user folder: survives updates of the program)."""
    return os.path.join(USER_DIR, "factions", FACTION_FILES[mod_set])


def load_factions(mod_set):
    """{button: {"label", "groups": {group: {"name", "factions"}}}} or None.
    The preset list shipped with the program (rome2bridge\\factions; read from the game's main menu with
    `python -m rome2bridge read-factions`); a list in the user folder only if the program has none."""
    if mod_set == "DeI":  # both DeI versions have the same campaigns and factions (read 2026-11-08)
        mod_set = "DeI (data folder)"
    for p in (os.path.join(HERE, "factions", FACTION_FILES[mod_set]), factions_file(mod_set)):
        try:
            return json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return None


def faction_label(group, faction, groups):
    g = groups.get(group, {})
    if faction.startswith(("rom_politics_", "emp_politics_")):  # Rome/Carthage: the choice is a family
        return "%s - %s" % (g.get("name", group), faction.split("_")[-1].capitalize())
    return faction


def expected_human(group, faction):
    """The faction key the map should report as human (a family choice plays the group's faction)."""
    if "_politics_" in faction:
        return group  # rom_rome / rom_carthage
    return faction


class Runner:
    def __init__(self, bridge=None, log=print, results_dir=None):
        self.b = bridge or Bridge()
        self.log = log
        self.results_dir = results_dir or os.path.join(os.path.expanduser("~"), "Documents", "rome2bridge_runs")
        self.stop_flag = False
        self.pause_flag = False  # set by "Pause Test Run": the run waits between turns until it is cleared
        self.paused = False      # True while the run is actually waiting

    # ---- files -----------------------------------------------------------------------------------------------------
    @property
    def prefs(self):
        return self.b.cfg.app("scripts", "preferences.script.txt")

    def check_mod_set(self, mod_set):
        if mod_set == "DeI":
            return [] if self.dei_sets() else ["DeI (neither the data folder packs nor the Steam workshop items)"]
        ms = MOD_SETS[mod_set]
        missing = []
        if ms["workshop"]:
            ws = self.workshop_dir()
            for item, pack in zip(ms["workshop"], ms["mods"]):
                if not (ws and os.path.isfile(os.path.join(ws, item, pack))):
                    missing.append("%s (workshop item %s)" % (pack, item))
        else:
            for pack in ms["mods"]:
                if not os.path.isfile(self.b.cfg.game("data", pack)):
                    missing.append(pack + " (data folder)")
        return missing

    def workshop_dir(self):
        # <library>\steamapps\common\Total War Rome II -> <library>\steamapps\workshop\content\214950
        d = os.path.join(os.path.dirname(os.path.dirname(self.b.cfg.game_dir)), "workshop", "content", "214950")
        return d if os.path.isdir(d) else None

    def dei_sets(self):
        """The DeI versions installed on this PC (each complete): data folder and/or Steam workshop."""
        return [s for s in ("DeI (data folder)", "DeI (Steam)") if not self.check_mod_set(s)]

    def resolve(self, mod_set):
        """"DeI" -> the installed DeI version (the data folder one if both are there); other names as they are."""
        if mod_set != "DeI":
            return mod_set
        found = self.dei_sets()
        if not found:
            raise BridgeError("DeI is not installed: neither %s in the data folder nor the Steam workshop items %s"
                              % (" + ".join(MOD_SETS["DeI (data folder)"]["mods"]), ", ".join(MOD_SETS["DeI (Steam)"]["workshop"])))
        return found[0]

    def available_mods(self):
        """Mod packs on this PC that can be added: type "mod" packs in data\\ and in the Steam workshop folders,
        without our pack and the DeI sets' packs. [{"pack", "item", "path", "startpos": [...]}]"""
        skip = {OUR_PACK.lower(), SS_PACK.lower()} | {p.lower() for ms in MOD_SETS.values() for p in ms["mods"]}
        skip |= {p.lower() for p in os.listdir(self.b.cfg.game("data")) if ss_is(p)}
        found = []
        dirs = [(self.b.cfg.game("data"), None)]
        ws = self.workshop_dir()
        if ws:
            dirs += [(os.path.join(ws, i), i) for i in sorted(os.listdir(ws)) if os.path.isdir(os.path.join(ws, i))]
        for d, item in dirs:
            try:
                names = sorted(os.listdir(d))
            except OSError:
                continue
            for n in names:
                p = os.path.join(d, n)
                if not n.lower().endswith(".pack") or n.lower() in skip:
                    continue
                try:
                    if pack_type(p) != 3:
                        continue
                    sp = startpos_files(p)
                except (OSError, ValueError):
                    continue
                found.append({"pack": n, "item": item, "path": p, "startpos": sp})
        return found

    def added_path(self, m):
        ws = self.workshop_dir()
        return os.path.join(ws, m["item"], m["pack"]) if m.get("item") and ws else self.b.cfg.game("data", m["pack"])

    def added_problems(self, added):
        """Added mods that are missing or can't be read."""
        out = []
        for m in added:
            p = self.added_path(m)
            if not os.path.isfile(p):
                out.append("%s not found (%s)" % (m["pack"], p))
                continue
            try:
                pack_files(p)
            except (OSError, ValueError) as e:
                out.append("%s: %s" % (m["pack"], e))
        return out

    def startpos_mods(self, added):
        """Added mods that edit the startpos file: allowed, but they may crash the game or the run."""
        out = []
        for m in added:
            try:
                if startpos_files(self.added_path(m)):
                    out.append(m["pack"])
            except (OSError, ValueError):
                pass
        return out

    def user_script_lines(self, mod_set, added=None):
        """The lines of the user.script.txt a run writes (our own file, nothing of the user's):
        workshop folders, our pack first (an earlier mod line wins), the added mods in their order, the set's packs,
        then two lines that skip the start movies."""
        ms = MOD_SETS[self.resolve(mod_set)]
        added = added or []
        ws = self.workshop_dir()
        lines = []
        for item in [m["item"] for m in added if m.get("item")] + ms["workshop"]:
            l = 'add_working_directory "%s";' % os.path.join(ws, item).replace("\\", "/")
            if l not in lines:
                lines.append(l)
        lines.append('mod "%s";' % OUR_PACK)
        lines += ['mod "%s";' % m["pack"] for m in added]
        lines += ['mod "%s";' % p for p in ms["mods"]]
        return lines + ["DISABLE_BINK true;", "show_frontend_movies false;"]

    def write_mod_set(self, mod_set, added=None):
        """Write our own user.script.txt for the run (UTF-16 LE with BOM, as the game writes it). The user's file
        was backed up by run() and is put back afterwards. Returns the mod/working-directory lines."""
        lines = self.user_script_lines(mod_set, added)
        self.b._write_us("\r\n".join(lines) + "\r\n", "utf-16")
        return [l for l in lines if l.startswith(("mod ", "add_working_directory"))]

    def set_windowed(self):
        self.b.set_windowed()

    # ---- one run -------------------------------------------------------------------------------------------------
    def run(self, mod_set, targets, turns=1, save_every=0, map_every=0, added=None, super_soldiers=False):
        """targets: [(button, campaign label, group, faction)]. mod_set: "Vanilla", "DeI" (the installed version) or a
        MOD_SETS name. added: the user's added mods ([{"pack", "item"}], top wins). super_soldiers: load SS_PACK (Legio Invicta) (copied
        into the data folder for the run, like our pack) above the added mods. Returns the results list (also in result.json)."""
        b = self.b
        added = added or []
        if b.cfg.game_key != "rome2":
            raise BridgeError("test runs are Rome II only (game here: %s)" % b.cfg.game_key)
        if not b.steam_running():
            raise BridgeError("Steam is not running: start Steam first")
        mod_set = self.resolve(mod_set)
        missing = self.check_mod_set(mod_set)
        if missing:
            raise BridgeError("%s: not found: %s" % (mod_set, ", ".join(missing)))
        ss_installed = False
        ss_pack = ss_name(super_soldiers)
        if super_soldiers:
            ss_src = os.path.join(ROOT, "extras", "build", ss_pack)
            if not os.path.isfile(b.cfg.game("data", ss_pack)):
                if not os.path.isfile(ss_src):
                    raise BridgeError("%s not found (build it: tools\\build_legio_invicta.ps1%s)"
                                      % (ss_src, "" if ss_pack == SS_PACK else " -Times %d" % ss_times(super_soldiers)))
                b.install_pack(ss_src); ss_installed = True
                self.log("installed " + ss_pack + " (Legio Invicta)")
            added = [{"pack": ss_pack, "item": None}] + [m for m in added if not ss_is(m.get("pack"))]
            self.log("Legio Invicta on: %s loaded first (your faction's soldiers %d times stronger)"
                     % (ss_pack, ss_times(super_soldiers)))
        bad = self.added_problems(added)
        if bad:
            raise BridgeError("added mods: " + "; ".join(bad))
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        run_dir = os.path.join(self.results_dir, "%s_%s" % (stamp, re.sub(r"[^\w]+", "_", mod_set).strip("_")))
        self.run_dir = run_dir  # the Progress window opens it during the run
        os.makedirs(run_dir, exist_ok=True)
        self.log("results: " + run_dir)
        b.kill()
        backups = {}
        for p in (b.cfg.user_script, self.prefs, self.autosave):
            if p == self.autosave and not os.path.isfile(p):
                continue
            dst = os.path.join(run_dir, os.path.basename(p) + ".bak")
            shutil.copy2(p, dst)
            backups[p] = (dst, sha(p))
        self.stamp = stamp
        installed_here = False
        pack_src = os.path.join(ROOT, "pack", "build", OUR_PACK)
        if not os.path.isfile(b.cfg.game("data", OUR_PACK)):
            if not os.path.isfile(pack_src):
                raise BridgeError("%s is not in data\\ and %s does not exist (build it: tools\\build_pack.ps1)" % (OUR_PACK, pack_src))
            b.install_pack(pack_src); installed_here = True
            self.log("installed " + OUR_PACK)
        results = []
        info = {"tool": "Rome II Test Runner", "tool_version": __version__, "game_exe_version": self.game_exe_version(),
                "mod_set": mod_set, "turns": turns, "save_every": save_every, "map_every": map_every,
                "started": stamp, "targets": len(targets), "super_soldiers": ss_times(super_soldiers)}
        info_path = os.path.join(run_dir, "info.json")
        try:
            info["mod_lines"] = self.write_mod_set(mod_set, added)
            info["added_mods"] = self.added_names = [m["pack"] for m in added]
            info["startpos_mods"] = self.startpos_added = self.startpos_mods(added)
            if self.startpos_added:
                self.log("warning: these added mods edit the startpos file and may crash the game or the run: " +
                         ", ".join(self.startpos_added))
            self.mod_set, self.mod_lines = mod_set, info["mod_lines"]
            self.log("mod list: " + " | ".join(info["mod_lines"]))
            json.dump(info, open(info_path, "w"), indent=1)
            self.set_windowed()
            for i, (button, label, group, faction) in enumerate(targets, 1):
                if i > 1:
                    self.wait_if_paused()
                if self.stop_flag:
                    self.log("stopped"); break
                r = self.run_one(run_dir, button, label, group, faction, turns, save_every, map_every, "%d/%d" % (i, len(targets)))
                results.append(r)
                if not info.get("bridge_version"):
                    info["bridge_version"] = (b.heartbeat() or {}).get("version")
                    info["game_menu_version"] = getattr(b, "menu_version", None)
                    json.dump(info, open(info_path, "w"), indent=1)
                json.dump({"mod_set": mod_set, "turns": turns, "results": results}, open(os.path.join(run_dir, "result.json"), "w"), indent=1)
        finally:
            b.kill()
            time.sleep(2)
            b.auto_click("")
            for p, (bak, h) in backups.items():
                shutil.copy2(bak, p)
                ok = sha(p) == h
                self.log("restored %s (%s)" % (os.path.basename(p), "hash ok" if ok else "HASH DIFFERS"))
            if installed_here:
                b.uninstall_pack(OUR_PACK); self.log("removed " + OUR_PACK)
            if ss_installed:
                b.uninstall_pack(ss_pack); self.log("removed " + ss_pack)
        n_ok = sum(1 for r in results if r.get("ok"))
        n_def = sum(1 for r in results if r.get("defeated"))
        self.log("done: %d of %d ok%s%s" % (n_ok, len(results), (" (%d ended early: faction destroyed)" % n_def) if n_def
                                             else "", " (stopped by you)" if self.stop_flag else ""))
        return results

    def wait_if_paused(self, r=None):
        """"Pause Test Run": wait here (between turns, or between games) until "Continue Test Run" or "Stop Test Run". The game stays
        open and dialogs are not answered by the runner meanwhile, so the user can look around (and use the tools)."""
        if not self.pause_flag or self.stop_flag:
            return
        b = self.b
        b.auto_click("")
        self.paused = True
        self.log("paused (the game is yours to look at; don't end the turn yourself). Press Continue Test Run or Stop Test Run.")
        try:
            k = 0
            while self.pause_flag and not self.stop_flag:
                k += 1
                if k % 3 == 0 and not b.running():  # tasklist: not every second
                    self.log("the game was closed during the pause: the run stops")
                    self.stop_flag = True
                    if r is not None:
                        r["closed_while_paused"] = True
                    break
                time.sleep(1)
        finally:
            self.paused = False
            self.pause_flag = False
        if not self.stop_flag:
            b.auto_click("test")
            self.log("continued")

    def run_one(self, run_dir, button, label, group, faction, turns, save_every, map_every, n, folder=None):
        b = self.b
        name = folder or "%s__%s" % (re.sub(r"[^\w]+", "_", label).strip("_"), faction)
        d = os.path.join(run_dir, name)
        os.makedirs(d, exist_ok=True)
        r = {"campaign": label, "button": button, "group": group, "faction": faction, "ok": False, "turns_done": 0,
             "folder": d}
        t0 = time.time()
        try:
            log_from = os.path.getsize(b.LOG)
        except OSError:
            log_from = 0
        self.log("[%s] %s / %s: starting" % (n, label, faction))
        r["stage"] = "while starting the campaign (main menu or loading screen)"
        try:
            w = b.start_faction(button, group, faction)
            if not w.get("alive"):
                r["error"] = "no bridge on the map (%s)" % (w.get("step") or w)
                r["crashes"] = b.new_crashes()
                self.capture_stuck(d)
                return r
            human = w.get("human")
            r["human"] = human
            want = expected_human(group, faction)
            if not (isinstance(human, list) and want in human):
                r["error"] = "playing %s, expected %s" % (human, want)
                self.log("  " + r["error"])
                return r
            r["stage"] = "on the campaign map at turn 1, before the first end turn"
            r["intro_esc"] = b.skip_intro()
            b.auto_click("test")
            try:
                rep = b.lua(open(os.path.join(ROOT, "scripts", "faction_report.lua"), encoding="utf-8").read(), 120)
                r["report"] = rep
                for f in os.listdir(b.cfg.game_dir):
                    if f.startswith("report_") and f.endswith(".txt"):
                        shutil.copy2(b.cfg.game(f), os.path.join(d, "t1_" + f))
            except (BridgeError, OSError) as e:
                r["report"] = "error: %s" % e
            self.shot(d, "turn1.png")
            # Progress window: faction stats (and the world map, if Map screenshot is on) at the start too
            if map_every:
                self.world_map(d, "turn1_map.png")
            self.stats(d, 1)
            for t in range(turns):
                self.wait_if_paused(r)
                if self.stop_flag:
                    r["stopped"] = ("game closed by the user while paused" if r.get("closed_while_paused") else
                                    "by the user") + " after %d turn(s)" % t
                    break
                r["stage"] = "during end turn %d of %d (game turn %s; the AI factions were playing)" % (
                    t + 1, turns, (b.heartbeat() or {}).get("turn", "?"))
                e = b.end_turn(timeout=900, stall=150)
                if e.get("defeated"):
                    # game over: not an error of the mod, a result of the game (the test faction only ends turns)
                    r["defeated"] = e["defeated"]
                    r["end_turn"] = e
                    r["result"] = "%s was destroyed on turn %s (game over) after %d end turn(s)" % (
                        faction, e["defeated"], t)
                    self.shot(d, "defeat.png")
                    self.log("  GAME OVER: " + r["result"])
                    break
                if not e.get("ended"):
                    r["error"] = "end turn %d: %s" % (t + 1, "game exited" if e.get("game_exited") else
                                                       "stalled (the game stopped answering)" if e.get("no_heartbeat") else
                                                       "stalled" if e.get("stalled") else "timeout")
                    r["end_turn"] = e
                    self.capture_stuck(d)
                    if e.get("game_exited"):
                        r["crashes"] = e.get("crashes")
                    self.log("  " + r["error"])
                    return r
                r["turns_done"] = t + 1
                self.log("  turn %d reached (%ss)" % (e["heartbeat"]["turn"], e.get("seconds")))
                self.shot(d, "turn%d.png" % (t + 2))
                gt = e["heartbeat"]["turn"]
                snap = map_every and (t + 1) % map_every == 0
                if snap:
                    self.world_map(d, "turn%d_map.png" % gt)
                # stats every turn (one read-only Lua call, ~1 s): the Progress window's numbers and drawn map
                self.stats(d, gt)
                if save_every and (t + 1) % save_every == 0:
                    sv = self.save(faction, e["heartbeat"]["turn"])
                    r.setdefault("saves", []).append(sv)
            # a defeat ends the game early but is no failure: no crash, no stuck turn
            r["ok"] = r["turns_done"] == turns or bool(r.get("defeated"))
        except BridgeError as e:
            r["error"] = str(e)
            self.log("  error: %s" % e)
        finally:
            r["seconds"] = round(time.time() - t0)
            r["crashes"] = r.get("crashes") or b.new_crashes()
            try:
                if r.get("closed_while_paused") and not r["crashes"]:
                    pass  # the user closed the game during a pause: not a crash
                elif r["crashes"] or not b.running():  # crash dump written, or the game closed by itself
                    self.report_crash(r, d)
            except Exception as ex:
                self.log("  crash report failed: %r" % ex)
            json.dump(r, open(os.path.join(d, "result.json"), "w"), indent=1)
            try:  # this game's part of the bridge log
                with open(b.LOG, "rb") as f:
                    f.seek(log_from); part = f.read()
                open(os.path.join(d, "bridge_log.txt"), "wb").write(part)
            except OSError:
                pass
        return r

    def report_crash(self, r, d):
        """The game crashed to desktop (CTD): crash.txt in the game's folder (same text as the window), the small
        .stack.txt files next to each crash dump copied there (the .mdmp itself is ~65 MB and stays where the game
        wrote it), r["crash"] filled in, and self.on_crash(text, folder) called (the desktop window shows it)."""
        b = self.b
        dumps = r.get("crashes") or []
        sig = b.crash_sig() if dumps else ""
        for dmp in dumps:
            base = os.path.splitext(dmp)[0]
            for extra in (base + ".stack.txt", base + "_hash.stack.txt"):
                if os.path.isfile(extra):
                    shutil.copy2(extra, os.path.join(d, os.path.basename(extra)))
        mod_set = getattr(self, "mod_set", "?")
        mods = [l for l in getattr(self, "mod_lines", []) if MOD_LINE.match(l)]
        L = ["Rome II crashed to desktop (CTD).", "",
             "Campaign: %s" % r.get("campaign"), "Faction:  %s" % r.get("faction"),
             "When:     %s" % r.get("stage", "?"), "",
             "Mods loaded (\"%s\"), in load order:" % mod_set] + ["  " + l for l in mods] + [""]
        if dumps:
            L += ["Crash details:", "  " + crash_words(sig), "Crash file: %s" % dumps[-1]]
        else:
            L += ["The game closed without writing a crash file."]
        L += ["", "What this means:",
              "The game itself stopped with an error. The Test Runner does not change the game: it starts it, answers "
              "dialogs and presses End Turn, like a player would. Its own small pack (@rome2_bridge.pack) only reads "
              "the game and clicks buttons, and it is loaded in every run."]
        sp, added = getattr(self, "startpos_added", []), getattr(self, "added_names", [])
        if sp:
            L += ["", "WARNING: these added mods edit the startpos file (campaigns\\<campaign>\\startpos.esf):"]
            L += ["  " + n for n in sp]
            L += ["Startpos mods are not supported and are the most likely cause of this crash. Run again without "
                  "them (Remove) to check: if it does not crash then, the mod is the cause, not the Test Runner."]
        elif added:
            L += ["", "This run had added mods: %s. Run again without them (Remove) to check whether one of them "
                  "causes the crash." % ", ".join(added)]
        else:
            L += ["", "This run used only the built-in mod set \"%s\"." % mod_set]
        L += ["Rome II sometimes crashes on its own: if it crashes again at the same place, press "
              "\"Make bug report\" and post the zip."]
        text = "\n".join(L)
        open(os.path.join(d, "crash.txt"), "w", encoding="utf-8").write(text + "\n")
        r["crash"] = {"stage": r.get("stage"), "signature": sig, "dumps": dumps, "mod_set": mod_set}
        self.log("  CRASH (CTD) %s; details in %s" % (r.get("stage"), os.path.join(d, "crash.txt")))
        cb = getattr(self, "on_crash", None)
        if cb:
            cb(text, d)

    @property
    def autosave(self):
        return self.b.cfg.app("save_games", "auto_save.save")

    def fog(self, on):
        """game:show_shroud(false/true): what Consul's /show_shroud calls (Consul not needed)."""
        try:
            self.b.lua("B.game():show_shroud(%s) return true" % ("true" if on else "false"), 30)
        except BridgeError as e:
            self.log("  fog of war: %s" % e)

    def world_map(self, d, name):
        """Fog of war off, open the world map (the map button by the minimap), screenshot, close the map, fog back on."""
        b = self.b
        self.fog(False)
        try:
            time.sleep(1)
            b.click("button_tactical_map"); time.sleep(3)
            self.shot(d, name)
            b.click("button_tactical_map"); time.sleep(1)
        except BridgeError as e:
            self.log("  world map: %s" % e)
        finally:
            self.fog(True)

    def stats(self, d, turn):
        """Faction stats for the Progress window: scripts\\progress_stats.lua -> <d>\\turn<turn>_stats.json
        ({turn, factions: [{name, human, treasury, regions, forces, armies, navies, units, food, food_shortage}]})."""
        try:
            code = open(os.path.join(ROOT, "scripts", "progress_stats.lua"), encoding="utf-8").read()
            data = self.b.lua(code, 60)
            if not isinstance(data, dict) or data.get("error"):
                raise BridgeError(str(data)[:200])
            data["turn_label"] = turn
            json.dump(data, open(os.path.join(d, "turn%d_stats.json" % turn), "w", encoding="utf-8"), indent=0)
        except (BridgeError, OSError) as e:
            self.log("  stats turn %s: %s" % (turn, e))

    def save(self, faction, turn):
        """Save the game under its own name: the game's autosave (game:autosave_at_next_opportunity(), works on every
        difficulty; not Quick Save) is written to auto_save.save, which is copied at once to
        save_games/TestRun <run> <faction> turn <n>.save. Returns that file name, or an error text."""
        b = self.b
        src = self.autosave
        before = os.path.getmtime(src) if os.path.isfile(src) else 0
        try:
            b.lua("B.game():autosave_at_next_opportunity() return true", 30)
        except BridgeError as e:
            self.log("  save: %s" % e); return "error: %s" % e
        t0, size = time.time(), -1
        while time.time() - t0 < 90:
            time.sleep(2)
            if os.path.isfile(src) and os.path.getmtime(src) > before:
                n = os.path.getsize(src)
                if n == size and n > 0:  # finished writing
                    name = "TestRun %s %s turn %s.save" % (getattr(self, "stamp", time.strftime("%Y-%m-%d_%H%M%S")), faction, turn)
                    shutil.copy2(src, os.path.join(os.path.dirname(src), name))
                    self.log("  saved: " + name)
                    return name
                size = n
        self.log("  save: the game wrote no save within 90 s")
        return "error: no save written"

    def capture_stuck(self, d):
        """What a bug report needs when a turn gets stuck: a screenshot and every shown component with id and text
        (the ids give a new auto-answer rule "<dialog id> <button id>")."""
        self.shot(d, "stalled.png")
        b = self.b
        try:
            if b.running() and b.alive():
                with open(os.path.join(d, "stalled_ui.txt"), "w", encoding="utf-8") as f:
                    f.write("# shown components on screen when the turn got stuck: id [I]=clickable | text\n")
                    f.write(str(b.ui_tree(max=4000)) + "\n\n# clickable only\n")
                    f.write(str(b.ui_tree(interactive=True, max=1500)) + "\n\n# panels\n")
                    f.write(json.dumps(b.panels(), indent=1))
        except Exception as e:
            self.log("  could not read the screen: %s" % e)

    def game_exe_version(self):
        try:
            import subprocess
            from .config import NO_WINDOW
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Item -LiteralPath $args[0]).VersionInfo.FileVersion",
                                self.b.cfg.game("Rome2.exe")], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
            return r.stdout.strip() or None
        except Exception:
            return None

    def shot(self, d, name):
        try:
            self.b.screenshot(os.path.join(d, name))
        except Exception as e:  # screenshots are a nice-to-have
            self.log("  screenshot failed: %s" % e)

    # ---- faction lists -------------------------------------------------------------------------------------------
    def read_factions(self, mod_set):
        """Start the game into the main menu with this mod set and read every campaign's playable factions; saves
        them to rome2bridge\\factions\\<mod set>.json. Files are backed up and restored as in run()."""
        b = self.b
        missing = self.check_mod_set(mod_set)
        if missing:
            raise BridgeError("%s: not found: %s" % (mod_set, ", ".join(missing)))
        if not b.steam_running():
            raise BridgeError("Steam is not running: start Steam first")
        b.kill()
        tmp = os.path.join(self.results_dir, "_factions_backup")
        os.makedirs(tmp, exist_ok=True)
        backups = {}
        for p in (b.cfg.user_script, self.prefs):
            dst = os.path.join(tmp, os.path.basename(p) + ".bak"); shutil.copy2(p, dst); backups[p] = (dst, sha(p))
        installed_here = False
        if not os.path.isfile(b.cfg.game("data", OUR_PACK)):
            b.install_pack(os.path.join(ROOT, "pack", "build", OUR_PACK)); installed_here = True
        try:
            self.write_mod_set(mod_set)
            self.set_windowed()
            b.start(menu=True, backup_save=False)  # the run backs up and restores auto_save.save itself
            w = b.wait_bridge(240, screen="menu")
            if not w.get("alive"):
                raise BridgeError("no bridge in the main menu: %s" % w)
            data = b.menu_factions(log=self.log)
            os.makedirs(os.path.dirname(factions_file(mod_set)), exist_ok=True)
            json.dump(data, open(factions_file(mod_set), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
            self.log("saved " + factions_file(mod_set))
            return data
        finally:
            b.kill(); time.sleep(2)
            for p, (bak, h) in backups.items():
                shutil.copy2(bak, p)
                self.log("restored %s (%s)" % (os.path.basename(p), "hash ok" if sha(p) == h else "HASH DIFFERS"))
            if installed_here:
                b.uninstall_pack(OUR_PACK)


def latest_run(results_dir):
    try:
        runs = [os.path.join(results_dir, n) for n in os.listdir(results_dir)
                if os.path.isfile(os.path.join(results_dir, n, "result.json"))]
    except OSError:
        return None
    return max(runs, key=os.path.getmtime) if runs else None


def make_bug_report(run_dir, out_dir=None):
    """Zip what a bug report needs from one run folder: info.json and result.json (versions, mod list, campaign,
    faction, turn, errors), the backed-up user.script.txt, and per game: result.json, stalled.png + stalled_ui.txt
    (the stuck dialog's ids and texts), bridge_log.txt and the last turn's screenshot. Not the faction reports."""
    import zipfile
    out_dir = out_dir or os.path.dirname(run_dir)
    z_path = os.path.join(out_dir, "bug_report_%s.zip" % os.path.basename(run_dir))
    with zipfile.ZipFile(z_path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in ("info.json", "result.json", "user.script.txt.bak"):
            p = os.path.join(run_dir, n)
            if os.path.isfile(p):
                z.write(p, n)
        for sub in sorted(os.listdir(run_dir)):
            d = os.path.join(run_dir, sub)
            if not os.path.isdir(d):
                continue
            files = os.listdir(d)
            turns = sorted((f for f in files if re.match(r"turn\d+\.png$", f)), key=lambda f: int(re.findall(r"\d+", f)[0]))
            keep = {"result.json", "stalled.png", "stalled_ui.txt", "bridge_log.txt", "crash.txt"} | set(turns[-1:])
            for f in files:
                if f in keep or f.endswith(".stack.txt"):
                    z.write(os.path.join(d, f), sub + "/" + f)
    return z_path
