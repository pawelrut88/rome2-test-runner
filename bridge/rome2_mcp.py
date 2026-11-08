# MCP server (stdio, no dependencies) for the rome2-bridge: one front end on the rome2bridge library, usable by any
# MCP client. The game side is the @rome2_bridge.pack (lua_scripts/rome2_bridge.lua); see rome2bridge\core.py.
#   python rome2_mcp.py            (started by the MCP client, e.g. through .mcp.json)
#   python rome2_mcp.py --selftest (prints the tool list and the status, no MCP)
import base64, json, os, sys, tempfile, threading, time, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rome2bridge import Bridge, BridgeError, PRESETS  # noqa: E402

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rome2_mcp.log")
_bridge = None


def log(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + s + "\n")


def B():
    global _bridge
    if _bridge is None:
        _bridge = Bridge()
    return _bridge


def as_text(v):
    return v if isinstance(v, str) else json.dumps(v, indent=1, ensure_ascii=False)


def t_status(a):
    b = B(); r = b.status()
    if r["new_crash_dumps"]:
        r["crash"] = b.crash_sig()
    return as_text(r)


def t_start(a):
    b = B()
    line = b.start(campaign=a.get("campaign") or (None if a.get("save") else "main_rome"), save=a.get("save") or None)
    return ("launched with %s; user.script.txt goes back to normal in %d s. A new campaign plays its first faction. "
            "Loading takes ~1-3 min: then call wait_bridge." % (line, b.cfg.startup_restore_s))


def t_wait_bridge(a):
    r = B().wait_bridge(float(a.get("timeout", 300)))
    if r.get("crashes"):
        r["crash"] = B().crash_sig()
    return as_text(r)


def t_lua(a): return as_text(B().lua(a["code"], float(a.get("timeout", 30))))
def t_ui_tree(a): return as_text(B().ui_tree(a.get("root"), a.get("ctx"), int(a.get("maxd", 16)), bool(a.get("interactive")),
                                             bool(a.get("all")), int(a.get("max", 1500))))
def t_ui_info(a): return as_text(B().ui_info(a["id"], a.get("ctx")))
def t_click(a): return as_text(B().click(a["id"], a.get("ctx"), bool(a.get("force"))))
def t_factions(a): return as_text(B().factions(a.get("name")))
def t_panels(a): return as_text(B().panels())


def t_auto_click(a):
    n = B().auto_click(a.get("rules", ""))
    return "auto-click rules set (%d lines)" % n if n else "auto-click rules cleared"


def t_end_turn(a):
    r = B().end_turn(wait=a.get("wait", True), timeout=float(a.get("timeout", 900)), stall=float(a.get("stall", 90)))
    if r.get("stalled"):
        r["hint"] = "click the dialog's button (click/auto_click), then call wait_turn"
    if r.get("game_exited") and r.get("crashes"):
        r["crash"] = B().crash_sig()
    return as_text(r)


def t_wait_turn(a): return as_text(B().wait_turn(float(a.get("timeout", 900)), float(a.get("stall", 90))))


def t_screenshot(a):
    p = os.path.join(tempfile.gettempdir(), "rome2bridge_shot.png")
    msg = B().screenshot(p)
    return [{"type": "image", "data": base64.b64encode(open(p, "rb").read()).decode(), "mimeType": "image/png"},
            {"type": "text", "text": msg + " (968 px wide, scaled from the window)"}]


def t_post_click(a): return B().post_click(a["x"], a["y"], a.get("wait", 1)) or "clicked"
def t_key(a): return B().post_key(int(str(a.get("vk", "0x1B")), 0), a.get("wait", 1)) or "key sent"
def t_skip_intro(a): return as_text({"esc_presses": B().skip_intro(int(a.get("max", 10)), float(a.get("delay", 5)))})
def t_quit(a): return "game stopped; " + B().quit()


S = lambda **p: {"type": "object", "properties": p}
STR, NUM, BOOL = {"type": "string"}, {"type": "number"}, {"type": "boolean"}
TOOLS = [
    ("game_status", "Is Rome2 running, is Steam running; bridge heartbeat (turn, human_turn, current faction, tick); crash dumps since launch.", S(), t_status),
    ("start_game", "Kill the game and start it straight into a new campaign (its first faction) or a save, no menus. Steam must be running. Does not change the mod list (the rome2-bridge pack must be in it).",
     S(campaign={"type": "string", "description": "campaign key, e.g. main_rome, main_emperor, main_punic"},
       save={"type": "string", "description": "save name as in save_games; loads it instead"}), t_start),
    ("wait_bridge", "Wait until the bridge ticks after start_game (heartbeat fresh); reports crashes.", S(timeout=NUM), t_wait_bridge),
    ("lua", "Run Lua in the game's campaign state (global scope; helpers in ROME2_BRIDGE / B: B.game(), B.find(id,ctx), B.find_shown, B.click, B.tree, B.factions, B.items(list), B.turn()). 'return x' sends x back as JSON.",
     {"type": "object", "properties": {"code": STR, "timeout": NUM}, "required": ["code"]}, t_lua),
    ("ui_tree", "UI component tree (shown ones only unless all): 'id [I] | text' lines. interactive=true lists only clickable ids.",
     S(root=STR, ctx=STR, maxd=NUM, interactive=BOOL, all=BOOL, max=NUM), t_ui_tree),
    ("ui_info", "Details of one component: visible, shown (all parents visible), interactive, text, state, position, size.",
     {"type": "object", "properties": {"id": STR, "ctx": STR}, "required": ["id"]}, t_ui_info),
    ("click", "SimulateClick a UI component by id (first shown one), searched inside ctx if given. Only if shown, unless force.",
     {"type": "object", "properties": {"id": STR, "ctx": STR, "force": BOOL}, "required": ["id"]}, t_click),
    ("panels", "Shown top-level panels and their buttons (what is on screen).", S(), t_panels),
    ("end_turn", "End the turn (retried every 15 s while a dialog blocks it) and by default wait for the next player turn. Returns stalled + panels if a dialog waits; reports crashes.",
     S(wait=BOOL, timeout=NUM, stall=NUM), t_end_turn),
    ("wait_turn", "Wait for the next player turn without sending end turn (after clearing a stalled end_turn).", S(timeout=NUM, stall=NUM), t_wait_turn),
    ("factions", "Factions with land (or one by name): human, treasury, regions, forces, units, food.", S(name=STR), t_factions),
    ("auto_click", "Set auto-click rules, one per line '<context id> <button id>' ('-' = anywhere), one click per second while shown; or a preset name (%s: autoresolve battles, decline diplomacy offers, accept war declarations, decline an ally's call to war, dilemma option 1, accept objectives). Empty clears." % ", ".join(PRESETS),
     S(rules=STR), t_auto_click),
    ("skip_intro", "While the campaign intro shows, wait `delay` s and press Esc (never on the map).", S(max=NUM, delay=NUM), t_skip_intro),
    ("screenshot", "Screenshot of the game window.", S(), t_screenshot),
    ("post_click", "Fallback: posted mouse click at client pixel x,y (window 1920x1080).",
     {"type": "object", "properties": {"x": NUM, "y": NUM}, "required": ["x", "y"]}, t_post_click),
    ("key", "Post a key to the game window (virtual key code, default 0x1B = Esc).", S(vk=STR), t_key),
    ("quit_game", "Kill the game and remove any startup line from user.script.txt.", S(), t_quit),
]
BY_NAME = {t[0]: t for t in TOOLS}
send_lock = threading.Lock()


def send(msg):
    with send_lock:
        sys.stdout.buffer.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()


def handle(m):
    mid, meth = m.get("id"), m.get("method")
    if mid is None:
        return  # notification
    if meth == "initialize":
        pv = (m.get("params") or {}).get("protocolVersion", "2025-06-18")
        return send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": pv, "capabilities": {"tools": {}},
                     "serverInfo": {"name": "rome2", "version": "2"}}})
    if meth == "ping":
        return send({"jsonrpc": "2.0", "id": mid, "result": {}})
    if meth == "tools/list":
        return send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s, _ in TOOLS]}})
    if meth == "tools/call":
        p = m.get("params") or {}
        t = BY_NAME.get(p.get("name"))
        if not t:
            return send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}})
        try:
            r = t[3](p.get("arguments") or {})
            content = r if isinstance(r, list) else [{"type": "text", "text": str(r)[:60000]}]
            return send({"jsonrpc": "2.0", "id": mid, "result": {"content": content}})
        except Exception as e:
            if not isinstance(e, BridgeError):
                log("tool %s error: %s" % (p.get("name"), traceback.format_exc()))
            return send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "error: %s" % e}], "isError": True}})
    send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % meth}})


def main():
    if "--selftest" in sys.argv:
        print([t[0] for t in TOOLS]); print(t_status({})); return
    log("server start")
    calls = []
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except ValueError:
            continue
        # tool calls can block for minutes (end_turn): run each in a thread so pings still get answers
        if m.get("method") == "tools/call":
            th = threading.Thread(target=handle, args=(m,), daemon=True); th.start(); calls.append(th)
        else:
            handle(m)
    for th in calls:
        th.join(timeout=5)
    try:
        log("server stop: " + B().strip_startup_lines())
    except Exception as e:
        log("server stop: %s" % e)


if __name__ == "__main__":
    main()
