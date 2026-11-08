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

APP_ID = "214950"
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


def find_game_dir():
    """Rome II install folder from Steam's libraryfolders.vdf (the library that lists app 214950)."""
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
            if re.search(r'"%s"' % APP_ID, m.group(3)):
                libs.insert(0, path)
            else:
                libs.append(path)
    except OSError:
        pass
    for lib in libs:
        acf = os.path.join(lib, "steamapps", "appmanifest_%s.acf" % APP_ID)
        name = "Total War Rome II"
        try:
            m = re.search(r'"installdir"\s+"([^"]+)"', open(acf, encoding="utf-8", errors="replace").read())
            if m:
                name = m.group(1)
        except OSError:
            pass
        d = os.path.join(lib, "steamapps", "common", name)
        if os.path.exists(os.path.join(d, "Rome2.exe")):
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
    def __init__(self, game_dir=None, app_dir=None, tools_dir=None, window_title="Total War: ROME 2",
                 startup_restore_s=30, source=None):
        self.game_dir = game_dir
        self.app_dir = app_dir
        self.tools_dir = tools_dir or os.path.join(ROOT, "tools")
        self.window_title = window_title
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

    def as_dict(self):
        return {"game_dir": self.game_dir, "app_dir": self.app_dir, "tools_dir": self.tools_dir,
                "window_title": self.window_title, "startup_restore_s": self.startup_restore_s, "source": self.source}


def load_config(path=None):
    data, src = {}, {}
    path = path or config_file()
    if path:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    cfg = Config(window_title=data.get("window_title", "Total War: ROME 2"),
                 startup_restore_s=int(data.get("startup_restore_s", 30)), tools_dir=data.get("tools_dir"))
    for key, env, auto in (("game_dir", "ROME2_GAME_DIR", find_game_dir),
                           ("app_dir", "ROME2_APP_DIR",
                            lambda: os.path.join(os.environ.get("APPDATA", ""), "The Creative Assembly", "Rome2"))):
        if data.get(key):
            setattr(cfg, key, data[key]); src[key] = "config " + path
        elif os.environ.get(env):
            setattr(cfg, key, os.environ[env]); src[key] = "env " + env
        else:
            setattr(cfg, key, auto()); src[key] = "autodetect"
    cfg.source = src
    return cfg
