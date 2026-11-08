"""Rome II Test Runner: desktop window for the rome2-bridge (tkinter, comes with Python). Start it with:
    python -m rome2bridge gui
Test runs (mod set / campaign / faction / turns), tools (faction report, Lua), live status and a log.
"""
import json
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__
from .core import Bridge, BridgeError
from .progress import ProgressWindow
from .testrun import (ROOT, Runner, faction_label, latest_run, load_added, load_factions, make_bug_report,
                      save_added)

ALL_CAMPAIGNS = "All campaigns"
ALL_FACTIONS = "All playable factions"


class App:
    def __init__(self, root):
        self.root = root
        root.title("Rome II Test Runner")
        self.root.title("Rome II Test Runner %s" % __version__)
        root.minsize(800, 780)
        self.q = queue.Queue()
        try:
            self.b = Bridge()
        except BridgeError as e:
            messagebox.showerror("Rome II Test Runner", str(e)); root.destroy(); return
        self.runner = Runner(self.b, log=self.log)
        self.runner.on_crash = lambda text, folder: self.q.put(("crash", (text, folder, "Rome II crashed (CTD)")))
        self.busy = None  # name of the running job
        self.data = None

        # status bar
        top = ttk.Frame(root, padding=(10, 8, 10, 0)); top.pack(fill="x")
        self.st = {}
        for k in ("Steam", "Game", "Bridge", "Registry"):
            l = ttk.Label(top, text=k + ": ?", padding=(0, 0, 14, 0)); l.pack(side="left"); self.st[k] = l
        self.st_turn = ttk.Label(top, text=""); self.st_turn.pack(side="right")

        # test run
        tr = ttk.LabelFrame(root, text="Test run", padding=10); tr.pack(fill="x", padx=10, pady=8)
        self.v_mods = tk.StringVar(value="Vanilla")
        self.v_camp = tk.StringVar(); self.v_fac = tk.StringVar(); self.v_turns = tk.IntVar(value=1)
        self.v_save = tk.IntVar(value=0)
        # Mods: Vanilla, or DeI if installed (data folder and/or Steam workshop; never both in one run)
        self.dei = self.runner.dei_sets()
        self.v_dei = tk.StringVar(value="data folder" if "DeI (data folder)" in self.dei else "Steam")
        ttk.Label(tr, text="Mods").grid(row=0, column=0, sticky="w")
        rowm = ttk.Frame(tr); rowm.grid(row=0, column=1, columnspan=3, sticky="w", padx=6, pady=3)
        self.cb_mods = ttk.Combobox(rowm, textvariable=self.v_mods, values=["Vanilla"] + (["DeI"] if self.dei else []),
                                    state="readonly", width=12)
        self.cb_mods.pack(side="left")
        self.cb_mods.bind("<<ComboboxSelected>>", lambda e: (self.load_lists(), self.show_dei()))
        self.cb_dei = ttk.Combobox(rowm, textvariable=self.v_dei, state="readonly", width=12,
                                   values=[v for s, v in (("DeI (data folder)", "data folder"), ("DeI (Steam)", "Steam")) if s in self.dei])
        self.lb_dei = ttk.Label(rowm, text="")
        self.show_dei()
        ttk.Label(tr, text="Campaign").grid(row=1, column=0, sticky="w")
        self.cb_camp = ttk.Combobox(tr, textvariable=self.v_camp, state="readonly", width=40)
        self.cb_camp.grid(row=1, column=1, columnspan=2, sticky="w", padx=6, pady=3)
        self.cb_camp.bind("<<ComboboxSelected>>", lambda e: self.fill_factions())
        ttk.Label(tr, text="Faction").grid(row=2, column=0, sticky="w")
        self.cb_fac = ttk.Combobox(tr, textvariable=self.v_fac, state="readonly", width=40)
        self.cb_fac.grid(row=2, column=1, columnspan=2, sticky="w", padx=6, pady=3)
        # mods the user adds on top of Vanilla/DeI (saved between sessions; top of the list wins)
        ttk.Label(tr, text="Added\nmods").grid(row=3, column=0, sticky="nw", pady=3)
        rowa = ttk.Frame(tr); rowa.grid(row=3, column=1, columnspan=3, sticky="w", padx=6, pady=3)
        self.lst_added = tk.Listbox(rowa, height=4, width=46, exportselection=False)
        self.lst_added.pack(side="left")
        bta = ttk.Frame(rowa); bta.pack(side="left", padx=6, anchor="n")
        for i, (text, cmd) in enumerate((("Add mods...", self.add_mods), ("Remove", self.remove_mod), ("Up", lambda: self.move_mod(-1)),
                                         ("Down", lambda: self.move_mod(1)), ("Preview user.script.txt", self.preview_script))):
            ttk.Button(bta, text=text, command=cmd).grid(row=i // 2, column=i % 2, sticky="we", padx=2, pady=1)
        self.added = load_added()
        self.fill_added()
        ttk.Label(tr, text="Turns").grid(row=4, column=0, sticky="w")
        row = ttk.Frame(tr); row.grid(row=4, column=1, columnspan=3, sticky="w", padx=6, pady=3)
        ttk.Spinbox(row, from_=0, to=200, textvariable=self.v_turns, width=6).pack(side="left")
        ttk.Label(row, text="end turn(s) per game").pack(side="left", padx=4)
        ttk.Label(tr, text="Save").grid(row=5, column=0, sticky="w")
        rows = ttk.Frame(tr); rows.grid(row=5, column=1, columnspan=3, sticky="w", padx=6, pady=3)
        ttk.Label(rows, text="Save the game every").pack(side="left")
        ttk.Spinbox(rows, from_=0, to=200, textvariable=self.v_save, width=5).pack(side="left", padx=4)
        ttk.Label(rows, text="turn(s)  (0 = no saves; 1 = every turn, 3 = every third turn)").pack(side="left")
        # (no "Map screenshot" option since 2026-11-08 late: the Progress window draws the map of every turn from the
        # region owners; the world map screenshot was cut off for factions far from the middle. CLI: --map-every.)
        # Legio Invicta: the user's super soldiers mod (our pack folder extras), your faction's units 1000x stronger, so
        # a faction that only ends turns is not wiped out early (DeI GC Rome fell on turn 19 without it)
        self.v_legio = tk.BooleanVar(value=False)
        ttk.Label(tr, text="Legio Invicta").grid(row=6, column=0, sticky="w")
        ttk.Checkbutton(tr, variable=self.v_legio, text="your faction's soldiers and ships 1000 times stronger, so it "
                        "isn't wiped out (the test faction only ends turns)").grid(row=6, column=1, columnspan=3, sticky="w", padx=6, pady=3)
        ttk.Label(tr, text="Made for vanilla Rome II and DeI. Mods that edit the startpos file (startpos.esf) are not "
                           "supported and may crash. Runs use their own user.script.txt; yours is put back after.", foreground="#b23b3b").grid(row=7, column=0, columnspan=4, sticky="w", pady=(4, 0))
        row2 = ttk.Frame(tr); row2.grid(row=8, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.bt_start = ttk.Button(row2, text="Start Test Run", command=self.start_run); self.bt_start.pack(side="left")
        # "Pause Test Run" <-> "Continue Test Run": the run waits between turns, the game stays open for the user to look at
        self.bt_pause = ttk.Button(row2, text="Pause Test Run", command=self.pause_or_continue, width=18, state="disabled")
        self.bt_pause.pack(side="left", padx=(6, 0))
        # "Stop Test Run": stops after the current turn, closes the game, puts the files back
        self.bt_stop = ttk.Button(row2, text="Stop Test Run", command=self.stop_run, width=16, state="disabled")
        self.bt_stop.pack(side="left", padx=6)
        self.lb_plan = ttk.Label(row2, text=""); self.lb_plan.pack(side="left", padx=10)
        # Progress window: drawn map + faction stats per turn of the current (or latest, or any) run
        ttk.Button(tr, text="Progress...", command=self.progress, width=14).grid(row=8, column=3, sticky="e", pady=(8, 0))

        # tools
        tl = ttk.LabelFrame(root, text="Tools (game already running)", padding=10); tl.pack(fill="x", padx=10)
        for text, cmd in (("Faction report", self.report), ("Run Lua file...", self.run_lua_file),
                          ("Screenshot", self.screenshot), ("Open results folder", self.open_results), ("Make bug report", self.bug_report)):
            ttk.Button(tl, text=text, command=cmd).pack(side="left", padx=(0, 6))

        # Lua
        lf = ttk.LabelFrame(root, text="Lua (runs in the game; 'return x' shows x)", padding=10); lf.pack(fill="x", padx=10, pady=8)
        self.lua_box = tk.Text(lf, height=3, font=("Consolas", 10)); self.lua_box.pack(fill="x")
        self.lua_box.insert("1.0", "return B.factions()")
        ttk.Button(lf, text="Run Lua", command=self.run_lua).pack(anchor="e", pady=(6, 0))

        # bottom bar (packed before the log so the log takes the rest of the height)
        bottom = ttk.Frame(root); bottom.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        self.bt_quit = ttk.Button(bottom, text="Quit game", command=self.quit_game, width=14)
        self.bt_quit.pack(side="right")
        ttk.Label(bottom, text="closes Rome II (no save)").pack(side="right", padx=6)

        # log
        lg = ttk.LabelFrame(root, text="Log", padding=10); lg.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.logw = ScrolledText(lg, height=12, font=("Consolas", 9), state="disabled"); self.logw.pack(fill="both", expand=True)

        self.load_lists()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        # the exe has no console: an error in a button's code goes to the log instead of nowhere
        root.report_callback_exception = lambda typ, val, tb: self.log(
            "error in the window: %s" % "".join(__import__("traceback").format_exception(typ, val, tb))[-1500:])
        self.root.after(200, self.pump)
        threading.Thread(target=self.status_loop, daemon=True).start()

    def on_close(self):
        # a run puts user.script.txt and preferences.script.txt back when it ends: don't cut it off
        if self.busy == "test run":
            messagebox.showwarning("Rome II Test Runner", "A %s is in progress. Press 'Stop Test Run' and wait for "
                                   "'done' in the log (your files are put back then), then close." % self.busy)
            return
        self.root.destroy()

    # ---- log / status ------------------------------------------------------------------------------------------------
    def log(self, s):
        self.q.put(("log", time.strftime("%H:%M:%S ") + str(s)))

    def pump(self):
        try:
            while True:
                kind, v = self.q.get_nowait()
                if kind == "log":
                    self.logw.configure(state="normal"); self.logw.insert("end", v + "\n"); self.logw.see("end")
                    self.logw.configure(state="disabled")
                elif kind == "status":
                    for k, (txt, ok) in v["items"].items():
                        self.st[k].configure(text="%s: %s" % (k, txt), foreground=("#2e7d32" if ok else "#b23b3b" if ok is False else ""))
                    self.st_turn.configure(text=v["turn"])
                elif kind == "lists":
                    self.load_lists()
                elif kind == "crash":
                    self.show_crash(*v)
                elif kind == "done":
                    self.busy = None; self.bt_start.configure(state="normal")
                    self.bt_pause.configure(text="Pause Test Run", state="disabled")
                    self.bt_stop.configure(text="Stop Test Run", state="disabled"); self.bt_quit.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(200, self.pump)

    def show_crash(self, text, folder, title="Rome II crashed (CTD)"):
        """Window for a crash to desktop, or the crash check's result (the run goes on)."""
        w = tk.Toplevel(self.root); w.title(title); w.geometry("760x640")
        txt = ScrolledText(w, font=("Segoe UI", 10), wrap="word"); txt.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        txt.insert("1.0", text); txt.configure(state="disabled")
        bar = ttk.Frame(w, padding=10); bar.pack(fill="x")
        ttk.Button(bar, text="Open folder", command=lambda: subprocess.Popen(["explorer", folder])).pack(side="left")
        ttk.Button(bar, text="Copy text", command=lambda: (w.clipboard_clear(), w.clipboard_append(text))).pack(side="left", padx=6)
        ttk.Button(bar, text="OK", command=w.destroy).pack(side="right")
        w.lift(); w.focus_force()

    def status_loop(self):
        while True:
            try:
                steam, game = self.b.steam_running(), self.b.running()
                hb = self.b.heartbeat() or {}
                fresh = game and hb.get("age_s", 99) < 6 and (hb.get("tick") or 0) > 0
                bridge = ("%s" % hb.get("screen", "campaign")) if fresh else "not running"
                turn = ""
                if fresh and hb.get("screen", "campaign") == "campaign":
                    turn = "Turn %s · %s · %s" % (hb.get("turn"), hb.get("current"), "your turn" if hb.get("human_turn") else "AI turn")
                if self.busy:
                    turn = (turn + "   [" + self.busy + "]").strip()
                reg = self.b.mod_version_ok()
                self.q.put(("status", {"items": {"Steam": ("running" if steam else "not running", steam),
                                                 "Game": ("running" if game else "not running", game if game else None),
                                                 "Bridge": (bridge, True if fresh else (False if game else None)),
                                                 "Registry": ("set" if reg else "set at launch", None)},
                                       "turn": turn}))
            except Exception as e:
                self.log("status error: %s" % e)
            time.sleep(2)

    # ---- lists -------------------------------------------------------------------------------------------------------
    def load_lists(self):
        self.data = load_factions(self.v_mods.get())
        if not self.data:
            self.cb_camp.configure(values=[]); self.cb_fac.configure(values=[]); self.v_camp.set(""); self.v_fac.set("")
            self.lb_plan.configure(text="No campaign/faction list for %s in this version." % self.v_mods.get())
            return
        self.camps = [(btn, c["label"]) for btn, c in self.data.items() if c.get("groups")]
        self.cb_camp.configure(values=[ALL_CAMPAIGNS] + [l for _, l in self.camps])
        if self.v_camp.get() not in self.cb_camp["values"]:
            self.v_camp.set(self.camps[0][1] if self.camps else "")
        self.fill_factions()

    def fill_factions(self):
        sel = self.v_camp.get()
        if sel == ALL_CAMPAIGNS:
            self.cb_fac.configure(values=[ALL_FACTIONS, "First faction of each campaign"]); self.v_fac.set(ALL_FACTIONS)
        else:
            btn = self.button_of(sel)
            self.facs = []
            for g, gd in self.data[btn]["groups"].items():
                for f in gd["factions"]:
                    self.facs.append((g, f, faction_label(g, f, self.data[btn]["groups"])))
            self.cb_fac.configure(values=[ALL_FACTIONS] + [l for _, _, l in self.facs])
            if self.v_fac.get() not in self.cb_fac["values"]:
                self.v_fac.set(self.facs[0][2] if self.facs else "")
        self.lb_plan.configure(text="%d game(s) to start" % len(self.targets()))

    def button_of(self, label):
        return next(b for b, l in self.camps if l == label)

    def targets(self):
        if not self.data:
            return []
        out = []
        camps = self.camps if self.v_camp.get() == ALL_CAMPAIGNS else [(self.button_of(self.v_camp.get()), self.v_camp.get())]
        for btn, label in camps:
            facs = [(g, f) for g, gd in self.data[btn]["groups"].items() for f in gd["factions"]]
            fsel = self.v_fac.get()
            if fsel == "First faction of each campaign":
                facs = facs[:1]
            elif fsel != ALL_FACTIONS:
                facs = [(g, f) for g, f, l in self.facs if l == fsel]
            out += [(btn, label, g, f) for g, f in facs]
        return out

    # ---- jobs --------------------------------------------------------------------------------------------------------
    def job(self, name, fn):
        # while a run is paused the tools (faction report, Lua, screenshot) may be used on the paused game
        side = self.busy == "test run" and self.runner.paused and name != "quit"
        if self.busy and not side:
            messagebox.showinfo("Rome II Test Runner", "Busy: " + self.busy +
                                (" (press Pause Test Run first to use the tools)" if self.busy == "test run" else "")); return
        if not side:
            self.busy = name; self.bt_start.configure(state="disabled")
            # Quit game stays on during a test run (it then does Stop Test Run); off during the other jobs
            self.bt_quit.configure(state="normal" if name == "test run" else "disabled")
            if name == "test run":
                self.bt_pause.configure(text="Pause Test Run", state="normal"); self.bt_stop.configure(text="Stop Test Run", state="normal")

        def work():
            try:
                fn()
            except BridgeError as e:
                self.log("error: %s" % e)
            except Exception as e:
                self.log("unexpected error: %r" % e)
            finally:
                if not side:
                    self.q.put(("done", None))
        threading.Thread(target=work, daemon=True).start()

    def start_run(self):
        t = self.targets()
        if not t:
            messagebox.showinfo("Rome II Test Runner", "Nothing to run: pick a campaign and a faction."); return
        mods, turns = self.mod_set(), int(self.v_turns.get())
        save_every, map_every = max(0, int(self.v_save.get() or 0)), 0  # map: drawn in Progress
        added = list(self.added)
        bad = self.runner.added_problems(added)
        if bad:
            messagebox.showwarning("Rome II Test Runner", "Fix the added mods first (Remove):\n\n" + "\n".join(bad)); return
        extra = ("\nAdded mods: " + ", ".join(m["pack"] for m in added)) if added else ""
        legio = bool(self.v_legio.get())
        if legio:
            extra += "\nLegio Invicta: on (your faction's soldiers 1000 times stronger)"
        sp = self.runner.startpos_mods(added)
        if sp:
            extra += ("\n\nWARNING: %s edit%s the startpos file. Not supported: the game or the run may crash."
                      % (", ".join(sp), "s" if len(sp) == 1 else ""))
        if not messagebox.askokcancel("Start Test Run", "%s: %d game(s), %d turn(s) each.%s\n\nThe game will be closed and "
                                      "restarted. user.script.txt and preferences.script.txt are backed up and put back "
                                      "afterwards.%s" % (mods, len(t), turns, extra,
                                      "\n\nSaves every %d turn(s) go to save_games as 'TestRun ...'." % save_every if save_every else "")):
            return
        self.runner.stop_flag = False
        self.job("test run", lambda: self.runner.run(mods, t, turns, save_every, map_every, added, super_soldiers=legio))

    # ---- mods ------------------------------------------------------------------------------------------------------
    def show_dei(self):
        """DeI picked: which version (only a choice when both are installed)."""
        self.cb_dei.pack_forget(); self.lb_dei.pack_forget()
        if self.v_mods.get() != "DeI":
            if not self.dei:
                self.lb_dei.configure(text="DeI not found (data folder or Steam workshop)"); self.lb_dei.pack(side="left", padx=8)
            return
        if len(self.dei) > 1:
            self.cb_dei.pack(side="left", padx=6)
            self.lb_dei.configure(text="both DeI versions found: pick one")
        else:
            self.lb_dei.configure(text="found: " + self.dei[0])
        self.lb_dei.pack(side="left", padx=8)

    def mod_set(self):
        if self.v_mods.get() != "DeI":
            return "Vanilla"
        return "DeI (data folder)" if (self.v_dei.get() == "data folder" and "DeI (data folder)" in self.dei) or \
            "DeI (Steam)" not in self.dei else "DeI (Steam)"

    def fill_added(self):
        self.lst_added.delete(0, "end")
        sp = set(self.runner.startpos_mods(self.added)) if self.added else set()
        for m in self.added:
            self.lst_added.insert("end", m["pack"] + ("   (Steam workshop)" if m.get("item") else "") +
                                  ("   STARTPOS - may crash" if m["pack"] in sp else ""))
            if m["pack"] in sp:
                self.lst_added.itemconfigure("end", foreground="#b23b3b")
        if not self.added:
            self.lst_added.insert("end", "(none: press Add mods... to add your own mods)")

    def save_added_list(self):
        save_added(self.added); self.fill_added()

    def add_mods(self):
        """List the mod packs on this PC (data folder + Steam workshop), pick one or more to add."""
        if self.busy == "test run":
            messagebox.showinfo("Rome II Test Runner", "Wait until the run has ended."); return
        avail = self.runner.available_mods()
        have = {(m["pack"], m.get("item")) for m in self.added}
        avail = [m for m in avail if (m["pack"], m["item"]) not in have]
        w = tk.Toplevel(self.root); w.title("Add mods"); w.geometry("640x460"); w.transient(self.root)
        ttk.Label(w, text="Mod packs found in the data folder and the Steam workshop. Pick one or more (Ctrl/Shift "
                          "click) and press Add.\nMods marked STARTPOS edit the startpos file: they are not supported "
                          "and may crash the game or the run.",
                  padding=10).pack(anchor="w")
        lb = tk.Listbox(w, selectmode="extended", font=("Consolas", 9))
        lb.pack(fill="both", expand=True, padx=10)
        for m in avail:
            lb.insert("end", "%-50s %s%s" % (m["pack"], "Steam workshop " + m["item"] if m["item"] else "data folder",
                                            "   STARTPOS - may crash" if m["startpos"] else ""))
            if m["startpos"]:
                lb.itemconfigure("end", foreground="#b23b3b")

        def ok():
            picked = [avail[i] for i in lb.curselection()]
            bad = [m["pack"] for m in picked if m["startpos"]]
            if bad and not messagebox.askyesno(
                    "Add mods", "These mods edit the startpos file (campaigns\\<campaign>\\startpos.esf):\n\n" +
                    "\n".join(bad) + "\n\nStartpos mods are not supported. They may crash the game or the Test "
                    "Runner, and the campaign and faction lists may not match them.\n\nAdd them anyway?", icon="warning",
                    parent=w):
                picked = [m for m in picked if not m["startpos"]]
            for m in picked:
                self.added.append({"pack": m["pack"], "item": m["item"]})
                self.log("added mod " + m["pack"] + ("  (STARTPOS: may crash)" if m["startpos"] else ""))
            self.save_added_list(); w.destroy()
        bar = ttk.Frame(w, padding=10); bar.pack(fill="x")
        ttk.Button(bar, text="Add", command=ok).pack(side="right")
        ttk.Button(bar, text="Cancel", command=w.destroy).pack(side="right", padx=6)
        if not avail:
            lb.insert("end", "(no other mod packs found)")

    def remove_mod(self):
        sel = self.lst_added.curselection()
        if sel and self.added and self.busy != "test run":
            self.log("removed mod " + self.added.pop(sel[0])["pack"]); self.save_added_list()

    def move_mod(self, d):
        sel = self.lst_added.curselection()
        if not sel or not self.added or self.busy == "test run":
            return
        i, j = sel[0], sel[0] + d
        if 0 <= j < len(self.added):
            self.added[i], self.added[j] = self.added[j], self.added[i]
            self.save_added_list(); self.lst_added.selection_set(j)

    def preview_script(self):
        try:
            text = "\n".join(self.runner.user_script_lines(self.mod_set(), self.added))
        except BridgeError as e:
            text = str(e)
        w = tk.Toplevel(self.root); w.title("user.script.txt for the next run"); w.geometry("640x300"); w.transient(self.root)
        ttk.Label(w, text="The run writes this user.script.txt (yours is backed up and put back after the run). "
                          "A mod line higher up wins over the lines below it.", padding=10, wraplength=600).pack(anchor="w")
        t = tk.Text(w, font=("Consolas", 10), height=10); t.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        t.insert("1.0", text); t.configure(state="disabled")

    def stop_run(self):
        if self.busy != "test run":
            return
        if self.runner.stop_flag:
            messagebox.showinfo("Rome II Test Runner", "Already stopping: wait for 'done' in the log."); return
        if messagebox.askokcancel("Stop Test Run", "Stop the run%s?\n\nThe game is then closed and your files are put back."
                                  % ("" if self.runner.paused else " after the current turn")):
            self.runner.stop_flag = True
            self.bt_stop.configure(text="Stopping...", state="disabled"); self.bt_pause.configure(state="disabled"); self.bt_quit.configure(state="disabled")
            self.log("stop requested: the run stops %s" % ("now" if self.runner.paused else "after the current turn"))

    def pause_or_continue(self):
        """Pause Test Run: the run waits after the current turn (game open, dialogs not answered); Continue Test Run goes on."""
        if self.busy != "test run" or self.runner.stop_flag:
            return
        if not self.runner.pause_flag:
            self.runner.pause_flag = True
            self.bt_pause.configure(text="Continue Test Run")
            if not self.runner.paused:
                self.log("pause requested: the run pauses after the current turn")
        else:
            self.runner.pause_flag = False
            self.bt_pause.configure(text="Pause Test Run")

    def report(self):
        def go():
            code = open(os.path.join(ROOT, "scripts", "faction_report.lua"), encoding="utf-8").read()
            self.log(self.b.lua(code, 120))
        self.job("faction report", go)

    def run_lua_file(self):
        p = filedialog.askopenfilename(filetypes=[("Lua", "*.lua"), ("All", "*.*")])
        if p:
            self.job("Lua file", lambda: self.log(json.dumps(self.b.lua(open(p, encoding="utf-8").read(), 120), ensure_ascii=False)))

    def run_lua(self):
        code = self.lua_box.get("1.0", "end").strip()
        if code:
            self.job("Lua", lambda: self.log(json.dumps(self.b.lua(code, 60), ensure_ascii=False)[:4000]))

    def screenshot(self):
        os.makedirs(self.runner.results_dir, exist_ok=True)
        p = os.path.join(self.runner.results_dir, "shot_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
        self.job("screenshot", lambda: self.log("%s -> %s" % (self.b.screenshot(p), p)))

    def open_results(self):
        os.makedirs(self.runner.results_dir, exist_ok=True)
        subprocess.Popen(["explorer", self.runner.results_dir])

    def bug_report(self):
        run = latest_run(self.runner.results_dir)
        run = filedialog.askdirectory(title="Run folder for the bug report", initialdir=run or self.runner.results_dir)
        if not run:
            return
        if not os.path.isfile(os.path.join(run, "result.json")):
            messagebox.showinfo("Rome II Test Runner", "That folder is not a test run (no result.json)."); return
        z = make_bug_report(run)
        self.log("bug report: " + z)
        subprocess.Popen(["explorer", "/select,", z])
        messagebox.showinfo("Rome II Test Runner", "Bug report saved:\n%s\n\nAttach this zip to your post and say in one line "
                            "what you expected." % z)

    def progress(self):
        """The Progress window for the run going now, or the latest run (another one can be opened from it)."""
        run = getattr(self.runner, "run_dir", None) if self.busy == "test run" else None
        run = run or latest_run(self.runner.results_dir)
        if not run:
            messagebox.showinfo("Progress", "No test run yet. Start one: faction numbers and region owners are taken "
                                "every turn, and the window draws the map of who owns what.")
            return
        ProgressWindow(self.root, run, self.runner.results_dir, live=lambda: self.busy == "test run")

    def quit_game(self):
        if self.busy == "test run":
            # during a run, Quit game is the same as Stop Test Run: the run closes the game and puts the files back
            return self.stop_run()
        if messagebox.askokcancel("Quit game", "Close Rome II now (no save)?"):
            self.job("quit", lambda: self.log("game stopped; " + self.b.quit()))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
