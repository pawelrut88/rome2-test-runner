"""Talk to a running Rome II through the in-game bridge (lua_scripts/rome2_bridge.lua in the rome2-bridge pack).

File protocol, all in the game folder:
  rome2_bridge_cmd.lua    we write: first line "--id <n>", then Lua; the game runs it within ~1 s and deletes it
  rome2_bridge_out.json   game writes: {"id", "ok", "result"|"error"}
  rome2_bridge_alive.json game writes every tick: turn, human_turn, current faction, tick, ...
  rome2_bridge_click.txt  we write: auto-click rules "<context id> <button id>", one click per tick while shown
  rome2_bridge_log.txt    game appends its log
Windows only for now (process checks, posted keys/clicks and screenshots).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from .config import FROZEN, NO_WINDOW, load_config

# rules for unattended end-turn tests (rome2-bridge project, 2026-11-07): decline AI diplomacy offers and then press
# the end-diplomacy button, accept war declarations (only an OK button), decline an ally's call to war, take the first
# dilemma option, accept objective popups. The offer screen itself is button_set2: never accept there.
PRESETS = {
    "test": "\n".join([
        # battles: autoresolve (ids and order from the IA project's autoplay run, 2026-11-06)
        "battle_results button_dismiss",
        # captives after a won battle (Release / Enslave / Kill): the first choice, like dilemmas (a 20-turn Grand
        # Campaign run stalled on it after a sea battle, 2026-11-08)
        "popup_battle_results button_release",
        "autoresolve_panel button_balanced",
        "button_set_attack button_autoresolve",
        "diplomacy_dropdown button_cancel",
        "diplomacy_dropdown button_ok_war_declared",
        "button_set3 button_accept",
        "events decline_button",
        "dilemma1_window dilemma_button",
        "events button_accept",
    ]),
}


class BridgeError(RuntimeError):
    pass


# Calls that break the game's Lua state or stop the bridge timer for good (the game keeps running, the bridge is dead
# until a restart). Tested in game, vanilla main_rome, 2026-11-08/09 (NOTES.md). lua() refuses code that names them.
UNSAFE_LUA = {
    "SetImageColour": "(UIComponent) breaks the game's Lua state: every value read after it is wrong (a function) and "
                      "the bridge stops ticking. Tested with 3 and 4 numbers, 2026-11-09.",
    "scroll_camera(": "stops the bridge timer for good (scroll_camera_with_direction is harmless but does nothing).",
    "render_campaign_to_file": "stops the bridge timer for good and writes no file.",
}


def lua_str(s):
    """Lua string literal (or nil)."""
    return "nil" if s is None else json.dumps(str(s))


class Bridge:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        if not self.cfg.game_dir or not os.path.isdir(self.cfg.game_dir):
            raise BridgeError("Rome II folder not found (set game_dir in rome2bridge.json or ROME2_GAME_DIR)")
        g = self.cfg.game
        self.CMD, self.OUT, self.ALIVE = g("rome2_bridge_cmd.lua"), g("rome2_bridge_out.json"), g("rome2_bridge_alive.json")
        self.CLICK, self.LOG = g("rome2_bridge_click.txt"), g("rome2_bridge_log.txt")
        self.launched = 0.0
        self.launch_line = ""
        # command ids must differ across processes too (two CLI calls in the same second got the same id and the
        # second read the first one's answer, seen 2026-11-08): pid + counter
        self.seq = 0
        self.lock = threading.Lock()
        self._restore_thread = None

    # ---- processes ----------------------------------------------------------------------------------------------
    @staticmethod
    def _tasklist(image):
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % image, "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, creationflags=NO_WINDOW)
        return image.lower() in r.stdout.lower()

    def running(self):
        return self._tasklist(self.cfg.exe)

    def game_start_time(self):
        """Start time (epoch s) of the running game process, or None (a new process, e.g. the CLI, didn't launch it)."""
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "(Get-Process %s -ErrorAction Stop | Select-Object -First 1).StartTime.ToUniversalTime()"
                                ".Subtract([datetime]'1970-01-01').TotalSeconds" % self.cfg.process], capture_output=True, text=True, timeout=30,
                               creationflags=NO_WINDOW)
            return float(r.stdout.strip().replace(",", "."))
        except (ValueError, subprocess.SubprocessError):
            return None

    def steam_running(self):
        return self._tasklist("steam.exe")

    def kill(self):
        subprocess.run(["taskkill", "/F", "/IM", self.cfg.exe], capture_output=True, creationflags=NO_WINDOW)
        for _ in range(20):
            if not self.running():
                return
            time.sleep(0.5)

    def _ps(self, script, *args, timeout=60):
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            os.path.join(self.cfg.tools_dir, script), *map(str, args)],
                           capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
        out = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            raise BridgeError("%s failed: %s" % (script, out))
        return out

    # ---- state ----------------------------------------------------------------------------------------------------
    def heartbeat(self, tries=5):
        # The bridge rewrites this file every second: for a moment it can be missing (between its remove and rename)
        # or half-written (written in place while we had it open), so a failed read is tried again a few times before
        # it counts as "no heartbeat" (popsupply 2026-11-11: "bridge not alive (heartbeat None)" in a healthy game).
        for i in range(tries):
            try:
                with open(self.ALIVE, encoding="utf-8") as f:
                    hb = json.load(f)
                hb["age_s"] = round(time.time() - os.path.getmtime(self.ALIVE), 1)
                return hb
            except (OSError, ValueError):
                if i + 1 < tries:
                    time.sleep(0.05)
        return None

    def alive(self, max_age=10):
        hb = self.heartbeat()
        return bool(hb and hb["age_s"] <= max_age and (hb.get("tick") or 0) > 0)

    def new_crashes(self):
        d = self.cfg.crash_dir
        if not os.path.isdir(d):
            return []
        # only dumps since this game run: our launch, else the running game's start; unknown -> none (a "last hour"
        # guess listed old dumps and made game_status run the slow crash analysis, seen 2026-11-08)
        since = self.launched or self.game_start_time()
        if not since:
            return []
        return sorted(os.path.join(d, n) for n in os.listdir(d)
                      if n.lower().endswith(".mdmp") and os.path.getmtime(os.path.join(d, n)) > since)

    def crash_sig(self):
        if FROZEN:  # no python.exe next to the exe: run tools\crashsig.py in this process
            import contextlib, io, runpy
            buf, argv = io.StringIO(), sys.argv
            try:
                sys.argv = ["crashsig.py", self.cfg.crash_dir, "1"]
                with contextlib.redirect_stdout(buf):
                    runpy.run_path(os.path.join(self.cfg.tools_dir, "crashsig.py"), run_name="__main__")
            except Exception as e:
                buf.write("crashsig failed: %s" % e)
            finally:
                sys.argv = argv
            return buf.getvalue().strip()
        try:
            r = subprocess.run([sys.executable, os.path.join(self.cfg.tools_dir, "crashsig.py"), self.cfg.crash_dir, "1"],
                               capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
            return (r.stdout + r.stderr).strip()
        except Exception as e:
            return "crashsig failed: %s" % e

    def status(self):
        c = self.new_crashes()
        return {"running": self.running(), "steam": self.steam_running(), "heartbeat": self.heartbeat(),
                "launched": time.strftime("%H:%M:%S", time.localtime(self.launched)) if self.launched else None,
                "launch": self.launch_line, "new_crash_dumps": c, "registry_mod_version_ok": self.mod_version_ok()}

    # ---- user.script.txt (UTF-16 LE as the game/launcher writes it) ---------------------------------------------------
    def _read_us(self):
        if not os.path.exists(self.cfg.user_script):
            return "", "utf-16"  # a game never started on this PC has none yet (Attila, ToB: 2026-11-12)
        b = open(self.cfg.user_script, "rb").read()
        if b[:2] == b"\xff\xfe":
            return b.decode("utf-16"), "utf-16"
        return b.decode("utf-8-sig", errors="replace"), "utf-8"

    def _write_us(self, text, enc):
        os.makedirs(os.path.dirname(self.cfg.user_script), exist_ok=True)
        with open(self.cfg.user_script, "wb") as f:
            f.write(text.encode("utf-16") if enc == "utf-16" else text.encode("utf-8"))

    def strip_startup_lines(self):
        """Remove game_startup_mode lines from user.script.txt; everything else stays as it was."""
        if not os.path.exists(self.cfg.user_script):
            return "no user.script.txt"
        text, enc = self._read_us()
        lines = text.splitlines(keepends=True)
        keep = [l for l in lines if not l.strip().startswith("game_startup_mode")]
        if len(keep) == len(lines):
            return "no startup line"
        self._write_us("".join(keep).rstrip() + "\r\n", enc)
        return "removed %d startup line(s)" % (len(lines) - len(keep))

    def mods(self):
        text, _ = self._read_us()
        return [l.strip()[5:].strip().rstrip(";").strip().strip('"') for l in text.splitlines() if l.strip().startswith("mod ")]

    def set_pack_enabled(self, pack, enabled=True):
        """Add (as the first mod line) or remove `mod "<pack>";` in user.script.txt. Backs the file up first."""
        text, enc = self._read_us()
        shutil.copyfile(self.cfg.user_script, self.cfg.user_script + ".bak_rome2bridge")
        lines = [l for l in text.splitlines() if l.strip() != 'mod "%s";' % pack]
        if enabled:
            i = next((n for n, l in enumerate(lines) if l.strip().startswith("mod ")), None)
            if i is None:
                i = next((n + 1 for n, l in enumerate(lines) if l.strip().startswith("add_working_directory")), 0)
            lines.insert(i, 'mod "%s";' % pack)
        self._write_us("\r\n".join(lines).rstrip() + "\r\n", enc)
        return self.mods()

    # ---- pack ------------------------------------------------------------------------------------------------------
    def install_pack(self, src):
        dst = self.cfg.game("data", os.path.basename(src))
        shutil.copyfile(src, dst)
        return dst

    def uninstall_pack(self, name):
        p = self.cfg.game("data", name)
        if os.path.exists(p):
            os.remove(p)
            return "removed " + p
        return "not installed"

    # ---- start / stop -----------------------------------------------------------------------------------------------
    MOD_VERSION = 0x00020004  # registry last_game_version; without it the "out-of-date mods" dialog stops the launch

    def mod_version_ok(self):
        if not self.cfg.profile.get("reg"):
            return True  # Rome II only (Attila's / ToB's out-of-date mods dialog not seen yet)
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\The Creative Assembly" + "\\" + self.cfg.profile["reg"])
            v, _ = winreg.QueryValueEx(k, "last_game_version")
            winreg.CloseKey(k)
            return v == self.MOD_VERSION
        except OSError:
            return False

    def ensure_mod_version(self):
        """Set HKCU\\SOFTWARE\\The Creative Assembly\\Rome2 last_game_version before every launch (the game removes it
        again, and without it the out-of-date mods dialog stops the start). Checked by reading it back."""
        if not self.cfg.profile.get("reg"):
            return "no registry step for this game"
        if self.mod_version_ok():
            return "registry ok"
        try:
            import winreg
            k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\The Creative Assembly" + "\\" + self.cfg.profile["reg"])
            winreg.SetValueEx(k, "last_game_version", 0, winreg.REG_DWORD, self.MOD_VERSION)
            winreg.CloseKey(k)
        except OSError as e:
            raise BridgeError("could not set registry last_game_version: %s" % e)
        if not self.mod_version_ok():
            raise BridgeError("registry last_game_version did not stick")
        return "registry set"

    def start(self, campaign=None, save=None, check_steam=True, menu=False, windowed=True):
        """Kill the game and start it straight into a new campaign (the campaign's first faction) or a save, or
        (menu=True) into the main menu.

        Writes `game_startup_mode ...;` into user.script.txt, launches the game's exe, and removes the line again after
        cfg.startup_restore_s seconds (the game reads the file at startup only). Does not touch the mod list.
        windowed: launch windowed 1920x1080 (preferences.script.txt backed up first; quit() puts it back).
        """
        if not campaign and not save and not menu:
            raise BridgeError("give a campaign key or a save name (or menu=True)")
        if check_steam and not self.steam_running():
            raise BridgeError("Steam is not running: start Steam first (the game crashes while loading without it)")
        self.kill()
        for p in (self.CMD, self.OUT, self.ALIVE, self.cfg.game("rome2_bridge_running.txt")):
            if os.path.exists(p):
                os.remove(p)
        self.strip_startup_lines()
        if menu:
            line = "(main menu)"
        else:
            text, enc = self._read_us()
            line = ('game_startup_mode campaign_load "%s";' % save) if save else ("game_startup_mode campaign %s;" % campaign)
            self._write_us(text.rstrip() + "\r\n" + line + "\r\n", enc)
        self.ensure_mod_version()
        self.display = self.windowed_for_start() if windowed else "display settings as they are"
        self.launched = time.time(); self.launch_line = line
        subprocess.Popen([self.cfg.game(self.cfg.exe)], cwd=self.cfg.game_dir)

        def restore():
            time.sleep(self.cfg.startup_restore_s)
            self.strip_startup_lines()
        self._restore_thread = threading.Thread(target=restore, daemon=True)
        self._restore_thread.start()
        return line

    # ---- windowed 1920x1080 for start, the player's own display settings back on quit -------------------------------
    @property
    def prefs(self):
        return self.cfg.app("scripts", "preferences.script.txt")

    @property
    def prefs_backup(self):
        return self.prefs + ".rome2bridge_backup"

    def set_windowed(self):
        """Write windowed 1920x1080 into preferences.script.txt (fullscreen ignores posted clicks and can minimize).
        Returns True if the file changed. Every other line stays as it was."""
        if not os.path.exists(self.prefs):
            return False
        t0 = open(self.prefs, encoding="utf-8", errors="replace").read()
        t = t0
        for k, v in (("gfx_fullscreen", "false"), ("x_res", "1920"), ("y_res", "1080")):
            t, n = re.subn(r"(?m)^%s [^;\r\n]*;" % k, "%s %s;" % (k, v), t)
            if n == 0:
                t = t.rstrip("\r\n") + "\n%s %s;\n" % (k, v)
        if t == t0:
            return False
        open(self.prefs, "w", encoding="utf-8", newline="").write(t)
        return True

    def windowed_for_start(self):
        # back up the player's file once: a backup left by a start without quit is still the player's own file
        if not os.path.exists(self.prefs):
            # a game never closed normally on this PC has none (Attila 2026-11-12: the first launch was fullscreen):
            # write just these three lines; an EMPTY backup means "there was no file", so quit deletes it again
            if not os.path.isdir(os.path.dirname(self.prefs)):
                return "no scripts folder"
            if not os.path.exists(self.prefs_backup):
                open(self.prefs_backup, "wb").close()
            open(self.prefs, "w", encoding="utf-8", newline="").write(
                "gfx_fullscreen false;\nx_res 1920;\ny_res 1080;\n")
            return "windowed 1920x1080 (new preferences.script.txt, removed on quit)"
        if self.is_windowed():
            return "already windowed 1920x1080"
        if not os.path.exists(self.prefs_backup):
            shutil.copy2(self.prefs, self.prefs_backup)
        self.set_windowed()
        return "windowed 1920x1080 (your settings back on quit)"

    def restore_prefs(self):
        """Put the player's preferences.script.txt back (from start's backup), after the game has exited: the game
        rewrites the file when it closes."""
        if not os.path.exists(self.prefs_backup):
            return "preferences not changed"
        if os.path.exists(self.prefs) and not self.is_windowed():
            # not what start wrote: the player changed the display settings since, keep theirs
            os.remove(self.prefs_backup)
            return "preferences changed by the player since start: kept"
        if os.path.getsize(self.prefs_backup) == 0:
            # there was no file before start
            if os.path.exists(self.prefs):
                os.remove(self.prefs)
            os.remove(self.prefs_backup)
            return "preferences removed again (there was none before start)"
        os.replace(self.prefs_backup, self.prefs)
        return "preferences put back"

    def is_windowed(self):
        t = open(self.prefs, encoding="utf-8", errors="replace").read()
        return all(re.search(r"(?m)^%s;" % kv, t) for kv in ("gfx_fullscreen false", "x_res 1920", "y_res 1080"))

    def wait_restore(self):
        if self._restore_thread:
            self._restore_thread.join()

    def quit(self):
        self.kill()
        if self.running():
            return self.strip_startup_lines() + "; game still running, preferences not put back"
        return self.strip_startup_lines() + "; " + self.restore_prefs()

    def wait_bridge(self, timeout=300, min_ticks=1, screen=None, since=None):
        """Wait until the bridge ticks (heartbeat fresh and tick >= min_ticks) after the last start (or `since`), on
        `screen` ("menu" or "campaign") if given."""
        t0 = time.time()
        since = self.launched if since is None else since
        while time.time() - t0 < timeout:
            hb = self.heartbeat()
            if hb and hb["age_s"] < 5 and (hb.get("tick") or 0) >= min_ticks and \
                    os.path.getmtime(self.ALIVE) >= since and (screen is None or hb.get("screen", "campaign") == screen):
                return {"alive": True, "heartbeat": hb}
            if self.launched and not self.running():
                c = self.new_crashes()
                return {"alive": False, "running": False, "crashes": c}
            time.sleep(1)
        return {"alive": False, "running": self.running(), "waited_s": timeout, "heartbeat": self.heartbeat()}

    def _exit_cause(self, cid, since):
        """After the game exited during lua(cid): was the command running (rome2_bridge_running.txt names it while it
        runs), never read, or done? Plus any new crash dump."""
        running = self.cfg.game("rome2_bridge_running.txt")
        try:
            in_cmd = open(running, encoding="utf-8").read().strip() == cid
        except OSError:
            in_cmd = False
        if in_cmd:
            what = "it closed WHILE this command ran (the command may have crashed it, or the game was closed then)"
        elif os.path.exists(self.CMD):
            what = "the command was never read"
        else:
            what = "the command was read, but not running when the game closed"
        d = self.cfg.crash_dir
        dumps = sorted(os.path.join(d, n) for n in (os.listdir(d) if os.path.isdir(d) else [])
                       if n.lower().endswith(".mdmp") and os.path.getmtime(os.path.join(d, n)) > since - 5)
        return what + ("; crash dump: %s" % dumps[-1] if dumps else "; no crash dump")

    # ---- commands ---------------------------------------------------------------------------------------------------
    def lua(self, code, timeout=30):
        """Run Lua in the game's campaign state; returns the decoded `return` value. Raises BridgeError on failure."""
        for name, why in UNSAFE_LUA.items():
            if name in code:
                raise BridgeError("not sent: %s %s" % (name, why))
        if not self.running():
            raise BridgeError("game is not running")
        hb = self.heartbeat()
        if not hb or hb["age_s"] > 10:
            raise BridgeError("bridge not alive (heartbeat %s)" % (hb and ("%ss old" % hb["age_s"])))
        with self.lock:
            self.seq += 1
            cid = "%d_%d_%d" % (os.getpid(), int(time.time() * 1000) % 10000000, self.seq)
            tmp = self.CMD + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write("--id %s\n%s\n" % (cid, code))
            os.replace(tmp, self.CMD)
            t0 = time.time()
            while time.time() - t0 < timeout:
                time.sleep(0.25)
                try:
                    with open(self.OUT, encoding="utf-8", errors="replace") as f:
                        res = json.load(f)
                except (OSError, ValueError):
                    continue
                if str(res.get("id")) == cid:
                    if not res.get("ok"):
                        raise BridgeError("Lua error: %s" % res.get("error"))
                    return res.get("result")
                if not self.running():
                    raise BridgeError("game exited while waiting: %s" % self._exit_cause(cid, t0))
            # say what the bridge was doing, so a bug report shows whether the game's timer stopped or the command hung
            hb = self.heartbeat() or {}
            raise BridgeError("no answer in %ss (loading or AI turn? the command stays queued; heartbeat %ss old, "
                              "tick %s, command %s)" % (timeout, hb.get("age_s"), hb.get("tick"),
                                                        "not read yet" if os.path.exists(self.CMD) else "read"))

    def ui_tree(self, root=None, ctx=None, maxd=16, interactive=False, all=False, max=1500):
        opts = "{root=%s, ctx=%s, maxd=%d, interactive=%s, all=%s, max=%d}" % (
            lua_str(root), lua_str(ctx), int(maxd), str(bool(interactive)).lower(), str(bool(all)).lower(), int(max))
        return self.lua("return ROME2_BRIDGE.tree(%s)" % opts, 60)

    def ui_info(self, id, ctx=None):
        return self.lua("local c = ROME2_BRIDGE.find(%s, %s); if not c then return 'not found' end; return ROME2_BRIDGE.info(c)"
                        % (lua_str(id), lua_str(ctx)))

    def click(self, id, ctx=None, force=False):
        return self.lua("return ROME2_BRIDGE.click(%s, %s, %s)" % (lua_str(id), lua_str(ctx), str(bool(force)).lower()))

    def factions(self, name=None):
        return self.lua("return ROME2_BRIDGE.factions(%s)" % lua_str(name), 60)

    def panels(self):
        return self.lua("return ROME2_BRIDGE.panels()", 20)

    def auto_click(self, rules):
        """Set auto-click rules (text, one '<context id> <button id>' per line, or a preset name); empty clears."""
        rules = PRESETS.get((rules or "").strip(), rules or "").strip()
        if not rules:
            if os.path.exists(self.CLICK):
                os.remove(self.CLICK)
            return 0
        with open(self.CLICK, "w", encoding="utf-8", newline="\n") as f:
            f.write(rules + "\n")
        return len(rules.splitlines())

    def end_turn(self, wait=True, timeout=900, stall=90, send=True):
        """End the turn (the bridge retries every 15 s while a dialog blocks it) and wait for the next player turn.

        Returns {"ended": True, ...}, or {"stalled": True, "panels": [...]} when one faction's turn (or our pending
        end turn) takes longer than `stall` seconds (usually a dialog waiting for the player), or {"game_exited": True}.
        """
        hb0 = self.heartbeat()
        start_n = hb0["turn_starts"] if hb0 else 0
        if send:
            r = self.lua("return ROME2_BRIDGE.end_turn()")
            if str(r).startswith("not the player's turn"):
                return {"ended": False, "refused": r}
            if not wait:
                return {"sent": r}
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(2)
            if not self.running():
                return {"ended": False, "game_exited": True, "crashes": self.new_crashes()}
            hb = self.heartbeat()
            if hb and hb.get("defeated"):
                # game over: the player's faction was destroyed; the game shows its Defeat screen (scripts stop)
                return {"ended": False, "defeated": hb["defeated"], "seconds": round(time.time() - t0), "heartbeat": hb}
            if hb and hb["turn_starts"] > start_n and hb["human_turn"]:
                return {"ended": True, "seconds": round(time.time() - t0), "heartbeat": hb}
            if hb and hb["age_s"] > max(180, 2 * stall) and time.time() - t0 > max(180, 2 * stall):
                # the game is open but its scripts stopped (a full-screen panel such as the Defeat screen)
                return {"ended": False, "stalled": True, "no_heartbeat": True, "seconds": round(time.time() - t0),
                        "heartbeat": hb, "panels": "the game stopped running scripts (heartbeat %ss old)" % hb["age_s"]}
            if hb and (hb.get("current_for_s") or 0) > stall and time.time() - t0 > stall:
                try:
                    panels = self.panels()
                except BridgeError as e:
                    panels = str(e)
                return {"ended": False, "stalled": True, "seconds": round(time.time() - t0), "heartbeat": hb,
                        "panels": panels}
        return {"ended": False, "waited_s": timeout, "heartbeat": self.heartbeat()}

    def wait_turn(self, timeout=900, stall=90):
        hb0 = self.heartbeat()
        if hb0 and hb0["human_turn"] and not hb0["want_end"]:
            return {"ended": True, "already": True, "heartbeat": hb0}
        return self.end_turn(timeout=timeout, stall=stall, send=False)

    # ---- main menu: faction lists and starting as a chosen faction (2026-11-08) ------------------------------------
    # The bridge also runs in the front end (all_scripted.lua is loaded there too) and clicks the menu by id:
    # campaign button (button_new_campaign_<key> / button_dlc_campaign_<n>, force: its menu is hidden until hovered)
    # -> culture group (faction_group_button_group) -> faction (faction_button_group) -> button_start_campaign.
    def wait_shown(self, id, timeout=30):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if self.lua("return ROME2_BRIDGE.find_shown(%s) ~= nil" % lua_str(id)):
                    return True
            except BridgeError:
                pass
            time.sleep(1)
        return False

    def children(self, id, all=False):
        return self.lua("return ROME2_BRIDGE.children(%s, nil, %s)" % (lua_str(id), "true" if all else "false")) or []

    def menu_campaign_buttons(self):
        """[(button id, label)] of the New Campaign entries (not Load, not unowned DLC)."""
        out = []
        for cont in ("main_container", "dlc_container"):
            for k in self.children(cont, all=True):
                if k.startswith("button_") and not k.endswith("_unowned") and k != "button_load_campaign":
                    label = self.lua("local c = ROME2_BRIDGE.find(%s); local s = c and ROME2_BRIDGE.U(c:Find('string'));"
                                     " return s and s:GetStateText() or ''" % lua_str(k))
                    out.append((k, label))
        return out

    def menu_factions(self, log=print):
        """Playable factions of every campaign, read from the New Campaign screen (game in the main menu):
        {button: {"label", "groups": {group: {"name", "factions": [...]}}}}. A campaign without a faction choice
        (the prologue) has no groups."""
        out = {}
        for btn, label in self.menu_campaign_buttons():
            self.click(btn, force=True)
            time.sleep(4)
            camp = {"label": label, "groups": {}}
            for g in self.children("faction_group_button_group"):
                self.click(g)
                time.sleep(1.5)
                name = self.lua("local c = ROME2_BRIDGE.find('dy_faction/group_name'); return c and ROME2_BRIDGE.info(c).text or ''")
                camp["groups"][g] = {"name": name, "factions": self.children("faction_button_group")}
            log("%s (%s): %d groups" % (label, btn, len(camp["groups"])))
            out[btn] = camp
        return out

    def shown_ids(self, contains="", prefix=("rom_", "emp_", "gaul_", "pun_", "pel_", "inv_", "3c_", "pro_")):
        """Ids of shown UI components containing `contains` (with "" : faction-like keys by prefix). For error messages."""
        try:
            return self.lua(
                "local B = ROME2_BRIDGE; local out, seen = {}, {}; local want, pre = %s, {%s}"
                # no plain flag: string.find(s, x, 1, true) crashes Rome II at the main menu (SHARED_KNOWLEDGE.md);
                # `contains` is matched as a pattern, so pass only letters, digits and "_"
                " local function hit(id) if want ~= '' then return id:find(want) ~= nil end"
                " for _, p in ipairs(pre) do if id:sub(1, #p) == p then return true end end return false end"
                " local function walk(c, d) if d > 16 then return end local id = tostring(c:Id())"
                " if hit(id) and B.shown(c) and not seen[id] then seen[id] = true; out[#out + 1] = id end"
                " for i = 0, c:ChildCount() - 1 do pcall(walk, B.U(c:Find(i)), d + 1) end end"
                " pcall(walk, B.root(), 0) table.sort(out) return out"
                % (lua_str(contains), ", ".join(lua_str(p) for p in prefix)), 30) or []
        except BridgeError:
            return []

    def start_faction(self, button, group, faction, timeout=420, check_steam=True):
        """Start the game into the main menu, then a new campaign (`button`) as `faction` (in culture `group`).
        Waits for the bridge on the campaign map. Returns the wait result plus the human factions found there."""
        self.start(menu=True, check_steam=check_steam)
        r = self.wait_bridge(240, screen="menu")
        if not r.get("alive"):
            return dict(r, step="main menu")
        try:  # e.g. "v2.4.0  Build 1339.3427123" (for bug reports)
            self.menu_version = self.lua("local c = ROME2_BRIDGE.find('version_number'); return c and ROME2_BRIDGE.info(c).text or nil")
        except BridgeError:
            pass
        # the campaign button sits in a hidden (hover) menu: force. The rest: wait until shown (the New Campaign screen
        # takes longer right after launch than later, seen 2026-11-08), then click.
        res = self.click(button, force=True)
        if res != "clicked":
            return {"alive": False, "step": "click %s: %s" % (button, res)}
        for id in (group, faction, "button_start_campaign"):
            if id == faction and not self.wait_shown(id, 8):
                # one faction in the group (e.g. Caesar in Gaul): the faction row stays hidden and the group click has
                # already selected it (seen 2026-11-08). The human check on the map confirms it.
                if self.lua("local c = ROME2_BRIDGE.find(%s); local row = ROME2_BRIDGE.find('faction_button_group');"
                            " return c ~= nil and row ~= nil and not ROME2_BRIDGE.shown(row)" % lua_str(faction)):
                    continue
            if not self.wait_shown(id, 30):
                r = {"alive": False, "ok": False, "step": "%s not shown after 30 s" % id}
                if id in (group, faction):  # a wrong key is the usual cause (DeI's groups differ from vanilla's)
                    r["shown_here"] = self.shown_ids("_faction_group_" if id == group else "")
                    r["step"] += " (shown on this screen: %s)" % ", ".join(r["shown_here"] or ["none"])
                return r
            time.sleep(1)
            if id == "button_start_campaign":
                t_click = time.time()
            res = self.click(id)
            if res != "clicked":
                return {"alive": False, "step": "click %s: %s" % (id, res)}
        if res != "clicked":
            return {"alive": False, "step": "click button_start_campaign: %s" % res}
        for p in (self.CMD, self.OUT):  # a command left over from the menu would run on the map
            if os.path.exists(p):
                os.remove(p)
        r = self.wait_bridge(timeout, screen="campaign", since=t_click)
        if r.get("alive"):
            try:
                r["human"] = self.lua("local r = {} for _, f in ipairs(ROME2_BRIDGE.items(ROME2_BRIDGE.game():model():world()"
                                      ":faction_list())) do if f:is_human() then r[#r+1] = f:name() end end return r")
            except BridgeError as e:
                r["human"] = "error: %s" % e
        return r

    # ---- window: keys, clicks, screenshots (PowerShell helpers in tools\) -----------------------------------------
    def post_key(self, vk=0x1B, wait=1):
        return self._ps("post_key.ps1", "-Vk", vk, "-Wait", wait, "-Process", self.cfg.process,
                        "-Title", self.cfg.window_title or "*")

    def hover(self, id, ctx=None, wait=2.5):
        """Move the REAL mouse cursor over a UI component (its centre) and wait, so its tooltip shows for a screenshot.
        Brings the game window to the front. The game's UI coordinates are scaled to the window's client pixels
        (they differ, e.g. a 2182x1227 UI in a 1920x1080 window). Returns where the cursor went."""
        import ctypes
        from ctypes import wintypes as wt
        r = self.lua("local B = ROME2_BRIDGE; local c = B.find(%s, %s); if not c then return nil end; "
                     "local x, y = c:Position(); local w, h = c:Dimensions(); local rw, rh = B.root():Dimensions(); "
                     "return {x, y, w, h, rw, rh}" % (lua_str(id), lua_str(ctx)))
        if not r:
            raise BridgeError("component not found: %s" % id)
        x, y, w, h, rw, rh = r
        u32 = ctypes.windll.user32
        hwnd = self.game_hwnd()
        if not hwnd:
            raise BridgeError("game window not found")
        rc = wt.RECT()
        u32.GetClientRect(hwnd, ctypes.byref(rc))
        sx, sy = rc.right / float(rw or rc.right), rc.bottom / float(rh or rc.bottom)
        pt = wt.POINT(int((x + w / 2.0) * sx), int((y + h / 2.0) * sy))
        cx, cy = pt.x, pt.y
        u32.ClientToScreen(hwnd, ctypes.byref(pt))
        u32.SetForegroundWindow(hwnd)
        # first off the window (its title bar), so the game closes an open tooltip: hovering the same spot again kept
        # the old tooltip text after it changed (popsupply, 2026-11-09)
        off = wt.POINT(rc.right // 2, 0)
        u32.ClientToScreen(hwnd, ctypes.byref(off))
        u32.SetCursorPos(off.x, max(0, off.y - 10))
        time.sleep(0.5)
        u32.SetCursorPos(pt.x, pt.y)
        time.sleep(0.3)
        u32.SetCursorPos(pt.x + 1, pt.y)  # a second move: the game reacts to mouse movement, not position
        time.sleep(wait)
        return "hover %s: ui %d,%d %dx%d (ui %dx%d, client %dx%d) -> client %d,%d, screen %d,%d" % (
            id, x, y, w, h, rw, rh, rc.right, rc.bottom, cx, cy, pt.x, pt.y)

    def post_click(self, x, y, wait=1):
        return self._ps("post_click.ps1", "-X", int(x), "-Y", int(y), "-Wait", wait, "-Process", self.cfg.process,
                        "-Title", self.cfg.window_title or "*")

    def game_hwnd(self):
        """The game's main window: by title if the profile has one, else the largest visible top-level window of the
        game's process (Attila's and ToB's titles not checked yet). 0 if none."""
        import ctypes
        from ctypes import wintypes as wt
        u32 = ctypes.windll.user32
        if self.cfg.window_title:
            return u32.FindWindowW(None, self.cfg.window_title) or 0
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % self.cfg.exe, "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, creationflags=NO_WINDOW)
        pids = {int(l.split('","')[1]) for l in r.stdout.splitlines() if l.lower().startswith('"%s"' % self.cfg.exe.lower())}
        best = [0, 0]

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def cb(h, _):
            pid = wt.DWORD(); u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value in pids and u32.IsWindowVisible(h) and not u32.GetWindow(h, 4):  # GW_OWNER: top level only
                rc = wt.RECT(); u32.GetWindowRect(h, ctypes.byref(rc))
                area = max(1, (rc.right - rc.left) * (rc.bottom - rc.top))
                if area > best[1]:
                    best[0], best[1] = h, area
            return True
        if pids:
            u32.EnumWindows(cb, 0)
        return best[0] or 0

    def restore_window(self, wait=1.5):
        """If the game window is minimized, show it again at its last size WITHOUT activating it (no focus taken from
        the player's window). A minimized window screenshots as 160x28 (consul-work 2026-11-11: windowed, but
        minimized after start). Returns "restored", "not minimized" or "no window"."""
        import ctypes
        u32 = ctypes.windll.user32
        hwnd = self.game_hwnd()
        if not hwnd:
            return "no window"
        if not u32.IsIconic(hwnd):
            return "not minimized"
        u32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        time.sleep(wait)  # let the game draw again before a screenshot
        return "restored" if not u32.IsIconic(hwnd) else "still minimized"

    def screenshot(self, out, full=False, crop=None):
        """PNG of the game window: 968 px wide by default, the window's own size if full, or crop=(left, top, width,
        height) in window pixels (top-left corner of the window, title bar included, is 0,0) at full size.
        Returns e.g. "printwindow=True window 1936x1119 saved 968x559"."""
        self.restore_window()
        args = ["-Out", out]
        if crop:
            left, top, width, height = map(int, crop)
            args += ["-Left", left, "-Top", top, "-Width", width, "-Height", height]
        elif full:
            args.append("-Full")
        return self._ps("game_shot.ps1", *args, "-Process", self.cfg.process)

    def intro_shown(self):
        return bool(self.lua('return ROME2_BRIDGE.find_shown("cinematic_bars") ~= nil'))

    def _intro_shown_retry(self, tries=3):
        # once in ~30 test games (Grand Campaign, 2026-11-08) one call during the intro got no answer in 30 s;
        # the calls before it worked, so ask again before giving up
        for i in range(tries):
            try:
                return self.intro_shown()
            except BridgeError:
                if i == tries - 1 or not self.running():
                    raise
                time.sleep(5)

    def skip_intro(self,max_presses=10, delay=5):
        """While the campaign intro shows (cinematic_bars), wait `delay` s and press Esc; never presses Esc on the map
        (that would open the game menu). Returns the number of presses."""
        n = 0
        while n < max_presses and self._intro_shown_retry():
            time.sleep(delay)
            self.post_key(0x1B, 2)
            n += 1
        return n
