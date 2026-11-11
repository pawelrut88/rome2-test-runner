"""Where things are: game folder, Rome II app data folder, tools. No hardcoded paths.

Order (first found wins), per setting:
  1. the config file: $ROME2BRIDGE_CONFIG, else rome2bridge.json next to the package (project root),
     else %APPDATA%\\rome2bridge\\rome2bridge.json
  2. environment: ROME2_GAME_DIR, ROME2_APP_DIR
  3. autodetect: the game from Steam's library folders (app 214950), app data from %APPDATA%
"""
import json
import os
import re
import sys

# The games the bridge knows. All three load lua_scripts/all_scripted.lua (the bridge pack's entry), as Consul's own
# packs do. Rome II is the tested one; Attila and Thrones of Britannia added 2026-11-12 for consul-work.
GAMES = {
    "rome2": {"app_id": "214950", "dir": "Total War Rome II", "exe": "Rome2.exe", "app": "Rome2",
              "title": "Total War: ROME 2", "rpfm": "rome_2", "reg": "Rome2", "campaign": "main_rome"},
    "attila": {"app_id": "325610", "dir": "Total War Attila", "exe": "Attila.exe", "app": "Attila",
               "title": "Total War: ATTILA", "rpfm": "attila", "reg": None, "campaign": "main_attila"},
    "tob": {"app_id": "712100", "dir": "Total War Saga Thrones of Britannia", "exe": "thrones.exe",
            "app": "ThronesofBritannia", "title": "A Total War Saga: Thrones of Britannia", "rpfm": "thrones_of_britannia",
            "reg": None, "campaign": "vik_attila"},
}
ALIASES = {"rome2": "rome2", "rome": "rome2", "rome_2": "rome2", "attila": "attila", "att": "attila",
           "tob": "tob", "thrones": "tob", "thrones_of_britannia": "tob"}
APP_ID = GAMES["rome2"]["app_id"]


def game_key(name):
    k = ALIASES.get(str(name or "rome2").lower())
    if not k:
        raise ValueError("unknown game %r (rome2, attila, tob)" % name)
    return k
HERE = os.path.dirname(os.path.abspath(__file__))
# inside rome2bridge.exe (PyInstaller) the bundled files (tools, scripts, pack, factions) are unpacked to sys._MEIPASS
FROZEN = bool(getattr(sys, "frozen", False))
ROOT = getattr(sys, "_MEIPASS", None) if FROZEN else os.path.dirname(HERE)
# where the program may write (faction lists read from the game; survives exe updates)
USER_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "rome2bridge")
# subprocess flag: no console window flashing up from a windowed exe
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _steam_path():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        p, _ = winreg.QueryValueEx(k, "SteamPath")
        winreg.CloseKey(k)
        return os.path.normpath(p)
    except Exception:
        return None


def find_game_dir(game="rome2"):
    """The game's install folder from Steam's libraryfolders.vdf (the library that lists its app id)."""
    prof = GAMES[game]
    app_id = prof["app_id"]
    steam = _steam_path()
    if not steam:
        return None
    libs = [steam]
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    try:
        text = open(vdf, encoding="utf-8", errors="replace").read()
        # each library block: "path" "<dir>" ... "apps" { "<appid>" "<size>" ... }
        for m in re.finditer(r'"path"\s+"([^"]+)"(.*?)"apps"\s*\{([^}]*)\}', text, re.S):
            path = m.group(1).replace("\\\\", "\\")
            if re.search(r'"%s"' % app_id, m.group(3)):
                libs.insert(0, path)
            else:
                libs.append(path)
    except OSError:
        pass
    for lib in libs:
        acf = os.path.join(lib, "steamapps", "appmanifest_%s.acf" % app_id)
        name = prof["dir"]
        try:
            m = re.search(r'"installdir"\s+"([^"]+)"', open(acf, encoding="utf-8", errors="replace").read())
            if m:
                name = m.group(1)
        except OSError:
            pass
        d = os.path.join(lib, "steamapps", "common", name)
        if os.path.exists(os.path.join(d, prof["exe"])):
            return d
    return None


def config_file():
    exe_dir = os.path.dirname(sys.executable) if FROZEN else None
    for p in (os.environ.get("ROME2BRIDGE_CONFIG"), exe_dir and os.path.join(exe_dir, "rome2bridge.json"),
              os.path.join(ROOT, "rome2bridge.json"),
              os.path.join(os.environ.get("APPDATA", ""), "rome2bridge", "rome2bridge.json")):
        if p and os.path.isfile(p):
            return p
    return None


class Config:
    def __init__(self, game_dir=None, app_dir=None, tools_dir=None, window_title=None,
                 startup_restore_s=30, source=None, game="rome2"):
        self.game_key = game_key(game)
        self.profile = GAMES[self.game_key]
        self.game_dir = game_dir
        self.app_dir = app_dir
        self.tools_dir = tools_dir or os.path.join(ROOT, "tools")
        # "" = any visible main window of the game's process (Attila's and ToB's titles not checked yet)
        self.window_title = self.profile["title"] if window_title is None else window_title
        self.startup_restore_s = startup_restore_s
        self.source = source or {}

    # derived paths
    def game(self, *p): return os.path.join(self.game_dir, *p)
    def app(self, *p): return os.path.join(self.app_dir, *p)
    @property
    def user_script(self): return self.app("scripts", "user.script.txt")
    @property
    def crash_dir(self): return self.app("crash_report")
    @property
    def save_dir(self): return self.app("save_games")

    @property
    def exe(self): return self.profile["exe"]
    @property
    def process(self): return os.path.splitext(self.profile["exe"])[0]

    def as_dict(self):
        return {"game": self.game_key, "game_dir": self.game_dir, "app_dir": self.app_dir, "tools_dir": self.tools_dir,
                "window_title": self.window_title, "startup_restore_s": self.startup_restore_s, "source": self.source}


def load_config(path=None):
    data, src = {}, {}
    path = path or config_file()
    if path:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    # which game: $ROME2BRIDGE_GAME (the CLI's --game sets it), else the config file's "game", else Rome II. The
    # folder settings (config file, ROME2_GAME_DIR / ROME2_APP_DIR) are Rome II's: for another game they are only
    # used when the config file names that game.
    game = game_key(os.environ.get("ROME2BRIDGE_GAME") or data.get("game") or "rome2")
    if game != game_key(data.get("game") or "rome2"):
        data = {k: v for k, v in data.items() if k not in ("game_dir", "app_dir", "window_title")}
    cfg = Config(window_title=data.get("window_title"), game=game,
                 startup_restore_s=int(data.get("startup_restore_s", 30)), tools_dir=data.get("tools_dir"))
    envs = ("ROME2_GAME_DIR", "ROME2_APP_DIR") if game == "rome2" else ("", "")
    for key, env, auto in (("game_dir", envs[0], lambda: find_game_dir(game)),
                           ("app_dir", envs[1],
                            lambda: os.path.join(os.environ.get("APPDATA", ""), "The Creative Assembly",
                                                 GAMES[game]["app"]))):
        if data.get(key):
            setattr(cfg, key, data[key]); src[key] = "config " + path
        elif env and os.environ.get(env):
            setattr(cfg, key, os.environ[env]); src[key] = "env " + env
        else:
            setattr(cfg, key, auto()); src[key] = "autodetect"
    cfg.source = src
    return cfg
