"""Progress window: one run's turns with the world-map (or campaign) screenshot and a faction table.

Reads a run folder written by testrun.Runner:
  <run>\\<campaign>__<faction>\\turn<N>.png        campaign map after each turn
  <run>\\<campaign>__<faction>\\turn<N>_map.png    world map without fog (Map screenshot turns, and turn 1)
  <run>\\<campaign>__<faction>\\turn<N>_stats.json faction stats (every turn since 2026-11-08 late; before that
                                                   turn 1, the Map screenshot turns and the last turn)
"Drawn map" (mapdraw.py) is drawn from the stats' region owners on the game's own strategic map (read from the
game's files), so it shows the whole map for every faction.
Nothing else is needed (no PIL: Tk 8.6 reads PNG itself; images are shrunk with subsample)."""
import json
import os
import re
import subprocess
import tkinter as tk
from tkinter import filedialog, ttk

COLS = (("faction", "Faction", 120, "w"), ("regions", "Regions", 66, "e"), ("armies", "Armies", 60, "e"),
        ("navies", "Navies", 56, "e"), ("units", "Units", 66, "e"), ("treasury", "Treasury", 96, "e"),
        ("food", "Food", 58, "e"), ("shortage", "Shortage", 62, "center"))
NUM = ("regions", "armies", "navies", "units", "treasury", "food")


def pretty(key):
    """rom_arverni -> Arverni, pun_carthage -> Carthage (the key is shown when a row is selected)."""
    parts = key.split("_")
    if len(parts) > 1 and len(parts[0]) <= 4:
        parts = parts[1:]
    return " ".join(p.capitalize() for p in parts if p)


def games(run_dir):
    """Game folders of a run that have something to show."""
    try:
        out = []
        for n in sorted(os.listdir(run_dir)):
            p = os.path.join(run_dir, n)
            if os.path.isdir(p) and any(re.match(r"turn\d+(_map|_stats)?\.(png|json)$", f) for f in os.listdir(p)):
                out.append(n)
        return out
    except OSError:
        return []


def turns(game_dir):
    """{turn: {"shot", "map", "stats"}} (paths, or None)."""
    t = {}
    try:
        names = os.listdir(game_dir)
    except OSError:
        return t
    for f in names:
        m = re.match(r"turn(\d+)(_map|_stats)?\.(png|json)$", f)
        if m:
            kind = {"": "shot", "_map": "map", "_stats": "stats"}[m.group(2) or ""]
            t.setdefault(int(m.group(1)), {"shot": None, "map": None, "stats": None})[kind] = os.path.join(game_dir, f)
    return t


def load_stats(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fac = d.get("factions") or []
    if isinstance(fac, dict):  # an empty Lua table may come back as {}
        fac = list(fac.values())
    return {f["name"]: f for f in fac if isinstance(f, dict) and f.get("name")}


class ProgressWindow(tk.Toplevel):
    def __init__(self, master, run_dir, results_dir=None, live=lambda: False):
        super().__init__(master)
        self.title("Progress")
        self.geometry("1500x860")
        self.minsize(1000, 600)
        self.results_dir = results_dir or os.path.dirname(run_dir or "")
        self.live = live  # True while a test run is going: the window refreshes itself
        self.run_dir, self.game_dir, self.data, self.photo, self.cur = None, None, {}, None, None
        self.stats, self.order, self.rows = {}, [], []
        self.v_game, self.v_pic = tk.StringVar(), tk.StringVar(value="drawn")
        self.selected, self._drawn, self._drawn_text = None, {}, ""  # picked faction (yellow), drawn-map cache

        top = ttk.Frame(self, padding=(10, 8)); top.pack(fill="x")
        ttk.Button(top, text="Open run...", command=self.pick_run).pack(side="left")
        self.lb_run = ttk.Label(top, text=""); self.lb_run.pack(side="left", padx=8)
        ttk.Label(top, text="Game").pack(side="left", padx=(16, 4))
        self.cb_game = ttk.Combobox(top, textvariable=self.v_game, state="readonly", width=46)
        self.cb_game.pack(side="left")
        self.cb_game.bind("<<ComboboxSelected>>", lambda e: self.load_game())
        ttk.Label(top, text="Picture").pack(side="left", padx=(16, 4))
        for v, text in (("drawn", "Drawn map"), ("map", "World map (no fog)"), ("shot", "Campaign view")):
            ttk.Radiobutton(top, text=text, value=v, variable=self.v_pic, command=self.show_picture).pack(side="left")
        ttk.Button(top, text="Open folder", command=self.open_folder).pack(side="right")
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="right", padx=6)

        body = ttk.Frame(self, padding=(10, 0, 10, 4)); body.pack(fill="both", expand=True)
        left = ttk.Frame(body); left.pack(side="left", fill="y")
        ttk.Label(left, text="Turns").pack(anchor="w")
        self.lst = tk.Listbox(left, width=20, exportselection=False, font=("Consolas", 10))
        self.lst.pack(fill="y", expand=True)
        self.lst.bind("<<ListboxSelect>>", lambda e: self.show_turn())
        nav = ttk.Frame(left); nav.pack(fill="x", pady=(4, 0))
        ttk.Button(nav, text="< Prev", width=8, command=lambda: self.step(-1)).pack(side="left")
        ttk.Button(nav, text="Next >", width=8, command=lambda: self.step(1)).pack(side="right")

        pane = ttk.PanedWindow(body, orient="horizontal"); pane.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.pic = ttk.Label(pane, anchor="center", text="", background="#202020", foreground="#dddddd")
        pane.add(self.pic, weight=3)
        right = ttk.Frame(pane); pane.add(right, weight=2)
        self.after(300, lambda: pane.sashpos(0, int(pane.winfo_width() * 0.56)))  # picture ~56%, table the rest
        self.lb_head = ttk.Label(right, text="", font=("Segoe UI", 10, "bold")); self.lb_head.pack(anchor="w", pady=(0, 4))
        tf = ttk.Frame(right); tf.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tf, columns=[c[0] for c in COLS], show="headings")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview); self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        for key, text, w, anchor in COLS:
            self.tree.heading(key, text=text, command=lambda k=key: self.sort(k))
            self.tree.column(key, width=w, anchor=anchor, stretch=key == "faction")
        self.tree.tag_configure("human", background="#dbe9ff")
        self.tree.tag_configure("dead", foreground="#999999")
        self.tree.tag_configure("short", foreground="#b23b3b")
        self.tree.bind("<<TreeviewSelect>>", self.on_row)
        self.sort_key, self.sort_rev = "regions", True
        self.lb_note = ttk.Label(right, text="", wraplength=560, foreground="#555555"); self.lb_note.pack(anchor="w", pady=(4, 0))

        self.status = ttk.Label(self, text="", anchor="w", padding=(10, 2)); self.status.pack(fill="x", side="bottom")
        self.pic.bind("<Configure>", lambda e: self.after_idle(self.show_picture))
        self.bind("<Left>", lambda e: self.step(-1)); self.bind("<Right>", lambda e: self.step(1))
        self._pic_size = None
        if run_dir:
            self.load_run(run_dir)
        self.after(5000, self.tick)

    # ---- loading -----------------------------------------------------------------------------------------------
    def pick_run(self):
        p = filedialog.askdirectory(title="Run folder", initialdir=self.run_dir or self.results_dir, parent=self)
        if p:
            self.load_run(p)

    def load_run(self, run_dir):
        self.run_dir = run_dir
        self.lb_run.configure(text=os.path.basename(run_dir.rstrip("\\/")))
        gs = games(run_dir)
        self.cb_game["values"] = gs
        if not gs:
            self.v_game.set(""); self.game_dir = None; self.data = {}; self.stats = {}; self.fill_turns()
            self.status.configure(text="No turns in this run folder yet.")
            return
        if self.v_game.get() not in gs:
            self.v_game.set(gs[0])
        self.load_game()

    def load_game(self, keep=None):
        self.game_dir = os.path.join(self.run_dir, self.v_game.get())
        self.data = turns(self.game_dir)
        self.stats = {t: load_stats(v["stats"]) for t, v in self.data.items() if v["stats"]}
        self.fill_turns(keep)

    def fill_turns(self, keep=None):
        self.order = sorted(self.data)
        self.lst.delete(0, "end")
        for t in self.order:
            v = self.data[t]
            self.lst.insert("end", "Turn %-4d %s %s" % (t, "map" if v["map"] else "   ", "stats" if self.stats.get(t) else ""))
        if not self.order:
            self.show_turn(); return
        i = self.order.index(keep) if keep in self.order else len(self.order) - 1
        self.lst.selection_clear(0, "end"); self.lst.selection_set(i); self.lst.see(i)
        self.show_turn()

    def refresh(self):
        if self.run_dir:
            last = self.order[-1] if self.order else None
            keep = None if self.cur == last else self.cur  # at the latest turn: follow new turns
            gs = games(self.run_dir)
            self.cb_game["values"] = gs
            if self.v_game.get() in gs:
                self.load_game(keep)
            else:
                self.load_run(self.run_dir)

    def tick(self):
        try:
            if self.live():
                self.refresh()
            self.after(5000, self.tick)
        except tk.TclError:
            pass  # window closed

    def open_folder(self):
        if self.game_dir or self.run_dir:
            subprocess.Popen(["explorer", self.game_dir or self.run_dir])

    # ---- showing -----------------------------------------------------------------------------------------------
    def step(self, d):
        sel = self.lst.curselection()
        if sel and 0 <= sel[0] + d < self.lst.size():
            self.lst.selection_clear(0, "end"); self.lst.selection_set(sel[0] + d); self.lst.see(sel[0] + d)
            self.show_turn()

    def show_turn(self):
        sel = self.lst.curselection()
        self.cur = self.order[sel[0]] if sel and self.order else None
        self._pic_size = None
        self.show_picture()
        self.fill_table()

    def picture_path(self):
        v = self.data.get(self.cur) or {}
        first, second = ("shot", "map") if self.v_pic.get() == "shot" else ("map", "shot")
        return v.get(first) or v.get(second), bool(v.get(first))

    def is_dei(self):
        try:
            return str(json.load(open(os.path.join(self.run_dir, "info.json"), encoding="utf-8")).get("mod_set", "")).startswith("DeI")
        except (OSError, ValueError, TypeError):
            return False

    def drawn(self):
        """(Tk image, cache key, status text) of the drawn map for the current turn, or (None, None, why not)."""
        from . import mapdraw
        have = [t for t in sorted(self.stats) if self.stats[t] and t <= self.cur]
        if not have:
            return None, None, "no faction numbers for this turn yet"
        st = have[-1]
        owners, human = mapdraw.owners_from_stats(self.stats[st])
        if owners is None:
            return None, None, "this run's numbers have no region owners (runs from before the drawn map)"
        key = (self.game_dir, st, self.selected)
        if key in self._drawn:
            return self._drawn[key]
        try:
            from .config import load_config
            mk = mapdraw.map_for(owners)
            if not mk:
                return None, None, "these regions are on no known campaign map"
            m = mapdraw.load_map(load_config().game_dir, mk)
            img = mapdraw.tk_picture(self, m, mapdraw.overlay_png(m, owners, human, self.selected, self.is_dei()))
        except Exception as e:  # missing game files, unknown pack layout: say why, show a screenshot instead
            return None, None, "can't draw the map: %s" % e
        text = "Drawn map, turn %d%s: regions in their owner's colour, white = your faction%s. Map: %s" % (
            self.cur, "" if st == self.cur else " (owners from turn %d)" % st,
            ", yellow = " + pretty(self.selected) if self.selected else " (click a faction in the table to mark it yellow)", mk)
        if len(self._drawn) > 40:
            self._drawn.clear()
        self._drawn[key] = (img, key, text)
        return self._drawn[key]

    def fit(self, img, aw, ah):
        f = min(1.0, aw / img.width(), ah / img.height())  # fit, never enlarge
        z, s = max(((z, s) for s in range(1, 9) for z in range(1, s + 1) if z / s <= f), key=lambda p: p[0] / p[1])
        return img if (z, s) == (1, 1) else img.zoom(z).subsample(s) if z > 1 else img.subsample(s)

    def show_picture(self):
        aw, ah = max(self.pic.winfo_width(), 200), max(self.pic.winfo_height(), 150)
        why = ""
        if self.cur is not None and self.v_pic.get() == "drawn":
            img, key, text = self.drawn()
            if img is not None:
                if self._pic_size != (key, aw, ah):
                    self.photo = self.fit(img, aw, ah)
                    self.pic.configure(image=self.photo, text="")
                    self._pic_size = (key, aw, ah)
                self._drawn_text = text
                self.status.configure(text=text)
                return
            why = "   (drawn map: %s; showing a screenshot)" % text
        path, exact = self.picture_path() if self.cur is not None else (None, False)
        if not path:
            self.photo = None
            self.pic.configure(image="", text="No picture for this turn")
            self.status.configure(text=why.strip(" ()"))
            return
        if self._pic_size == (path, aw, ah):
            return
        try:
            self.photo = self.fit(tk.PhotoImage(file=path, master=self), aw, ah)
            self.pic.configure(image=self.photo, text="")
            self._pic_size = (path, aw, ah)
        except tk.TclError as e:
            self.photo = None
            self.pic.configure(image="", text="Can't show %s: %s" % (os.path.basename(path), e))
        self.status.configure(text="%s%s%s" % (path, "" if exact else "   (the other picture is not there for this turn)", why))

    def prev_stats(self, turn):
        earlier = [t for t in sorted(self.stats) if t < turn and self.stats[t]]
        return (earlier[-1], self.stats[earlier[-1]]) if earlier else (None, None)

    def fill_table(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = []
        # a turn without numbers shows the latest numbers before it (stats: turn 1, Map screenshot turns, last turn)
        have = [t for t in sorted(self.stats) if self.stats[t] and self.cur is not None and t <= self.cur]
        if not have:
            self.lb_head.configure(text="Turn %s" % self.cur if self.cur is not None else "")
            self.lb_note.configure(text="No faction numbers yet. They are taken every turn (runs made with 0.7.0: "
                                        "turn 1, the Map screenshot turns and the last turn).")
            return
        st = have[-1]
        cur = self.stats[st]
        pt, prev = self.prev_stats(st)
        seen = set()
        for t in have[:-1]:
            seen |= set(self.stats[t])
        rows = []
        for name, f in cur.items():
            alive = (f.get("regions") or 0) > 0 or (f.get("forces") or 0) > 0
            rows.append((name, f, prev.get(name) if prev else None, alive))
        for name in seen - set(cur):  # had regions or forces before, has none now
            rows.append((name, {"name": name}, prev.get(name) if prev else None, False))
        self.rows = rows
        alive_n = sum(1 for r in rows if r[3])
        human = [pretty(r[0]) for r in rows if r[1].get("human")]
        self.lb_head.configure(text="Turn %d%s  -  %d factions with land or forces%s" % (
            self.cur, "" if st == self.cur else "  (numbers from turn %d)" % st, alive_n,
            ("  -  you: " + ", ".join(human)) if human else ""))
        self.lb_note.configure(text=("(+n / -n) = change since turn %d. " % pt if pt else "First stats of this game. ") +
                               "Armies, Navies = forces led by a general (city garrisons don't count). Blue = your faction, grey = gone. "
                               "Click a column to sort.")
        self.draw_rows()

    def cell(self, f, p, key):
        v = f.get(key)
        if key == "shortage":
            return "yes" if f.get("food_shortage") else ("" if v is None and "food_shortage" not in f else "no")
        if v is None:
            return "-" if f.get("regions") is not None else ""
        try:
            v = int(round(float(v)))
        except (TypeError, ValueError):
            return str(v)
        if p is not None and p.get(key) is not None:
            try:
                dv = v - int(round(float(p.get(key))))
                if dv:
                    return "%d (%+d)" % (v, dv)
            except (TypeError, ValueError):
                pass
        return str(v)

    def draw_rows(self):
        self.tree.delete(*self.tree.get_children())
        k = self.sort_key

        def keyf(r):
            name, f, p, alive = r
            if k == "faction":
                return (0, pretty(name).lower())
            if k == "shortage":
                return (0, 1 if f.get("food_shortage") else 0)
            try:
                return (0 if alive else -1, float(f.get(k) or 0))
            except (TypeError, ValueError):
                return (0, 0)
        for name, f, p, alive in sorted(self.rows, key=keyf, reverse=self.sort_rev):
            tags = ("human",) if f.get("human") else ("dead",) if not alive else ("short",) if f.get("food_shortage") else ()
            vals = [pretty(name) + ("" if alive else "  (gone)")] + [self.cell(f, p, c[0]) for c in COLS[1:]]
            self.tree.insert("", "end", iid=name, values=vals, tags=tags)
        for key, text, w, anchor in COLS:
            self.tree.heading(key, text=text + (" v" if key == k and self.sort_rev else " ^" if key == k else ""))

    def sort(self, key):
        if not self.rows:
            return
        self.sort_rev = not self.sort_rev if key == self.sort_key else key != "faction"
        self.sort_key = key
        self.draw_rows()

    def on_row(self, e=None):
        sel = self.tree.selection()
        if sel:
            if self.v_pic.get() == "drawn" and sel[0] != self.selected:
                self.selected = sel[0]
                self._pic_size = None
                self.show_picture()
            self.status.configure(text="faction key: %s   %s" % (sel[0], self._drawn_text if self.v_pic.get() == "drawn" else ""))
