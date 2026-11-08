# Entry point of Rome2TestRunner.exe (PyInstaller, tools\build_exe.ps1): opens the desktop window.
# Without a console (windowed exe) two switches write to a file instead:
#   Rome2TestRunner.exe --selftest out.json       bundled files found?, game/Steam/config status
#   Rome2TestRunner.exe --testrun out.log <mods> <campaign label> <faction> <turns>   one run, no window
import json
import os
import sys


def selftest(out):
    from rome2bridge.config import FROZEN, ROOT, USER_DIR, load_config
    from rome2bridge.core import Bridge
    from rome2bridge.testrun import MOD_SETS, Runner, load_factions
    r = {"frozen": FROZEN, "root": ROOT, "user_dir": USER_DIR, "files": {}}
    for p in ("tools\\post_key.ps1", "tools\\post_click.ps1", "tools\\game_shot.ps1", "tools\\crashsig.py",
              "scripts\\faction_report.lua", "scripts\\progress_stats.lua", "pack\\build\\@rome2_bridge.pack",
              "extras\\build\\@@0_PAW_legio_invicta.pack", "rome2bridge\\maps\\map_data.json"):
        r["files"][p] = os.path.isfile(os.path.join(ROOT, p))
    try:
        cfg = load_config(); r["config"] = cfg.as_dict()
        b = Bridge(cfg); r["status"] = b.status()
        run = Runner(b, log=lambda s: None)
        r["mod_sets"] = {m: {"missing": run.check_mod_set(m), "faction_list": bool(load_factions(m))} for m in MOD_SETS}
    except Exception as e:
        r["error"] = repr(e)
    # the Progress window on the latest run (if any): opens, loads the turns and a picture, closes
    try:
        import tkinter as tk
        from rome2bridge.progress import ProgressWindow
        from rome2bridge.testrun import latest_run
        root = tk.Tk(); root.withdraw()
        last = latest_run(Runner(log=lambda s: None).results_dir)
        w = ProgressWindow(root, last)
        for _ in range(20):
            root.update(); __import__("time").sleep(0.1)
        r["progress_window"] = {"run": last, "turns": list(w.lst.get(0, "end")), "rows": len(w.tree.get_children()),
                                "picture": bool(w.photo), "head": w.lb_head.cget("text")}
        root.destroy()
    except Exception as e:
        r["progress_window"] = {"error": repr(e)}
    json.dump(r, open(out, "w", encoding="utf-8"), indent=1)


def testrun(out, mods, campaign, faction, turns):
    from rome2bridge.testrun import Runner, load_factions
    f = open(out, "a", encoding="utf-8")
    log = lambda s: (f.write(str(s) + "\n"), f.flush())
    data = load_factions(mods)
    t = [(btn, c["label"], g, fk) for btn, c in data.items() if c["label"] == campaign
         for g, gd in c["groups"].items() for fk in gd["factions"] if fk == faction]
    log("targets: %s" % t)
    res = Runner(log=log).run(mods, t, int(turns))
    log(json.dumps(res, indent=1))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
    elif len(sys.argv) > 6 and sys.argv[1] == "--testrun":
        testrun(*sys.argv[2:7])
    else:
        from rome2bridge.gui import main
        main()
