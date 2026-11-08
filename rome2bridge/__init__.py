"""rome2bridge: control and read a running Total War: Rome II from Python.

    from rome2bridge import Bridge
    b = Bridge()                      # finds the game through Steam, or rome2bridge.json / ROME2_GAME_DIR
    b.start(campaign="main_rome")     # Steam must be running
    b.wait_bridge()
    b.auto_click("test")              # answer dialogs for unattended end turns
    print(b.factions("rom_rome"))
    print(b.end_turn())
    print(b.lua("return B.turn()"))

Needs the rome2-bridge pack (@rome2_bridge.pack) in the game's data folder and in the mod list.
"""
from .config import Config, load_config, find_game_dir
from .core import Bridge, BridgeError, PRESETS, lua_str

__all__ = ["Bridge", "BridgeError", "Config", "load_config", "find_game_dir", "PRESETS", "lua_str"]
__version__ = "0.7.1"
