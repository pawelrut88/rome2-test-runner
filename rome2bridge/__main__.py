"""Command line:  python -m rome2bridge <command> [options]      (python -m rome2bridge -h for the list)

Prints JSON (or plain text for text results). Exit code 1 on an error.
"""
import argparse
import json
import sys

from . import Bridge, BridgeError, PRESETS, load_config


def out(v):
    if isinstance(v, str):
        print(v)
    else:
        print(json.dumps(v, indent=1, ensure_ascii=False))


def main(argv=None):
    # game text (names, Lua results) can hold characters the Windows console code page (cp1252) can't print:
    # print UTF-8 instead of crashing with UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="python -m rome2bridge", description="Control and read a running Total War: Rome II.")
    p.add_argument("--config", help="config file (default: $ROME2BRIDGE_CONFIG, rome2bridge.json, %%APPDATA%%\\rome2bridge)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("config", help="show the paths in use and where they came from")
    sub.add_parser("status", help="game running?, Steam running?, bridge heartbeat, crash dumps since launch")
    s = sub.add_parser("start", help="start the game straight into a new campaign or a save (Steam must run)")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--campaign", help="campaign key, e.g. main_rome (the campaign's first faction is played)")
    g.add_argument("--save", help="save file name as in save_games")
    g.add_argument("--menu", action="store_true", help="start into the main menu (no startup line)")
    s.add_argument("--no-wait", action="store_true", help="return right after launching")
    s.add_argument("--timeout", type=float, default=300)
    s.add_argument("--skip-intro", action="store_true", help="press Esc while the campaign intro shows")
    s.add_argument("--no-steam-check", action="store_true")
    w = sub.add_parser("wait", help="wait until the bridge ticks"); w.add_argument("--timeout", type=float, default=300)
    sub.add_parser("quit", help="kill the game and remove any startup line from user.script.txt")
    l = sub.add_parser("lua", help="run Lua in the game; 'return x' prints x")
    l.add_argument("code", nargs="?", help="Lua code (or use -f)"); l.add_argument("-f", "--file")
    l.add_argument("--timeout", type=float, default=30)
    t = sub.add_parser("tree", help="UI tree of shown components")
    t.add_argument("--root"); t.add_argument("--ctx"); t.add_argument("--maxd", type=int, default=16)
    t.add_argument("--interactive", action="store_true"); t.add_argument("--all", action="store_true")
    t.add_argument("--max", type=int, default=1500)
    i = sub.add_parser("info", help="one UI component"); i.add_argument("id"); i.add_argument("--ctx")
    c = sub.add_parser("click", help="click a UI component by id"); c.add_argument("id"); c.add_argument("--ctx")
    c.add_argument("--force", action="store_true")
    f = sub.add_parser("factions", help="factions with land, or one"); f.add_argument("name", nargs="?")
    sub.add_parser("panels", help="shown top-level panels and their buttons")
    a = sub.add_parser("autoclick", help="set auto-click rules: a preset name (%s), rules text, or --clear" % ", ".join(PRESETS))
    a.add_argument("rules", nargs="?"); a.add_argument("--clear", action="store_true")
    e = sub.add_parser("end-turn", help="end the turn and wait for the next player turn")
    e.add_argument("--no-wait", action="store_true"); e.add_argument("--timeout", type=float, default=900)
    e.add_argument("--stall", type=float, default=90, help="report the screen if one faction's turn takes longer")
    wt = sub.add_parser("wait-turn", help="wait for the next player turn without ending the turn")
    wt.add_argument("--timeout", type=float, default=900); wt.add_argument("--stall", type=float, default=90)
    sh = sub.add_parser("screenshot", help="PNG of the game window (968 px wide unless --full or --crop)")
    sh.add_argument("out"); sh.add_argument("--full", action="store_true", help="the window's own size")
    sh.add_argument("--crop", type=int, nargs=4, metavar=("LEFT", "TOP", "WIDTH", "HEIGHT"),
                    help="a part of the window at full size, window pixels (title bar included)")
    k = sub.add_parser("key", help="post a key to the game window"); k.add_argument("vk", nargs="?", default="0x1B",
                                                                                   help="virtual key code, default Esc")
    pc = sub.add_parser("post-click", help="posted click at client pixel x y"); pc.add_argument("x", type=int); pc.add_argument("y", type=int)
    si = sub.add_parser("skip-intro", help="press Esc while the campaign intro shows")
    si.add_argument("--max", type=int, default=10); si.add_argument("--delay", type=float, default=5)
    sub.add_parser("gui", help="open the desktop window")
    tr = sub.add_parser("testrun", help="unattended test run: new campaign(s) as faction(s), N end turns each")
    tr.add_argument("--mods", default="Vanilla", help="Vanilla, \"DeI (data folder)\" or \"DeI (Steam)\"")
    tr.add_argument("--campaign", help="campaign label or menu button id (default: all)")
    tr.add_argument("--faction", help="faction key (default: all playable)")
    tr.add_argument("--turns", type=int, default=1); tr.add_argument("--save-every", type=int, default=0, help="save every N turns (0 = off)")
    tr.add_argument("--map-every", type=int, default=0, help="world map screenshot without fog every N turns (0 = off)")
    rf = sub.add_parser("read-factions", help="read the playable factions of every campaign from the main menu")
    rf.add_argument("--mods", default="Vanilla")
    sub.add_parser("mods", help="mod list in user.script.txt")
    for name, h in (("enable", "add a pack to the mod list (first line)"), ("disable", "remove a pack from the mod list")):
        x = sub.add_parser(name, help=h); x.add_argument("pack", nargs="?", default="@rome2_bridge.pack")
    ins = sub.add_parser("install", help="copy a pack into the game's data folder"); ins.add_argument("path")
    un = sub.add_parser("uninstall", help="delete a pack from the data folder"); un.add_argument("name", nargs="?", default="@rome2_bridge.pack")

    args = p.parse_args(argv)
    cfg = load_config(args.config)
    if args.cmd == "config":
        return out(cfg.as_dict())
    b = Bridge(cfg)
    cmd = args.cmd
    if cmd == "status":
        return out(b.status())
    if cmd == "start":
        line = b.start(campaign=args.campaign, save=args.save, check_steam=not args.no_steam_check, menu=args.menu)
        r = {"launched": line}
        if not args.no_wait and not args.menu:
            r.update(b.wait_bridge(args.timeout, min_ticks=1))
            if args.skip_intro and r.get("alive"):
                r["intro_esc"] = b.skip_intro()
        b.wait_restore()  # take the startup line out of user.script.txt before this process ends
        return out(r)
    if cmd == "wait":
        return out(b.wait_bridge(args.timeout))
    if cmd == "quit":
        return out(b.quit())
    if cmd == "lua":
        code = open(args.file, encoding="utf-8").read() if args.file else args.code
        if not code:
            raise BridgeError("give Lua code or -f file")
        return out(b.lua(code, args.timeout))
    if cmd == "tree":
        return out(b.ui_tree(args.root, args.ctx, args.maxd, args.interactive, args.all, args.max))
    if cmd == "info":
        return out(b.ui_info(args.id, args.ctx))
    if cmd == "click":
        return out(b.click(args.id, args.ctx, args.force))
    if cmd == "factions":
        return out(b.factions(args.name))
    if cmd == "panels":
        return out(b.panels())
    if cmd == "autoclick":
        n = b.auto_click("" if args.clear else (args.rules or ""))
        return out("auto-click rules: %d line(s)" % n if n else "auto-click rules cleared")
    if cmd == "end-turn":
        return out(b.end_turn(wait=not args.no_wait, timeout=args.timeout, stall=args.stall))
    if cmd == "wait-turn":
        return out(b.wait_turn(args.timeout, args.stall))
    if cmd == "screenshot":
        return out(b.screenshot(args.out, full=args.full, crop=args.crop))
    if cmd == "key":
        return out(b.post_key(int(args.vk, 0)))
    if cmd == "post-click":
        return out(b.post_click(args.x, args.y))
    if cmd == "skip-intro":
        return out({"esc_presses": b.skip_intro(args.max, args.delay)})
    if cmd == "gui":
        from .gui import main as gui_main
        return gui_main()
    if cmd in ("testrun", "read-factions"):
        from .testrun import Runner, load_factions
        r = Runner(b)
        if cmd == "read-factions":
            r.read_factions(args.mods); return 0
        data = load_factions(args.mods)
        if not data:
            raise BridgeError("no faction list for %s: run read-factions first" % args.mods)
        t = [(btn, c["label"], g, f) for btn, c in data.items() if c.get("groups")
             if not args.campaign or args.campaign in (btn, c["label"])
             for g, gd in c["groups"].items() for f in gd["factions"] if not args.faction or f == args.faction]
        if not t:
            raise BridgeError("nothing matches --campaign/--faction")
        return out(r.run(args.mods, t, args.turns, args.save_every, args.map_every))
    if cmd == "mods":
        return out(b.mods())
    if cmd == "enable":
        return out(b.set_pack_enabled(args.pack, True))
    if cmd == "disable":
        return out(b.set_pack_enabled(args.pack, False))
    if cmd == "install":
        return out(b.install_pack(args.path))
    if cmd == "uninstall":
        return out(b.uninstall_pack(args.name))


if __name__ == "__main__":
    try:
        main()
    except BridgeError as e:
        print("error: %s" % e, file=sys.stderr)
        sys.exit(1)
