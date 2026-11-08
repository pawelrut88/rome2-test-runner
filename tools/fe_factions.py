# Read the playable factions of every campaign from the game's own New Campaign screen (main menu), through the bridge.
# Needs the game running in the main menu with @rome2_bridge.pack (python -m rome2bridge start --menu).
#   python tools\fe_factions.py out.json
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rome2bridge import Bridge  # noqa: E402

b = Bridge()


def L(code, t=20):
    return b.lua(code, t)


def kids(id, all=False):
    return L("return B.children(%s, nil, %s)" % (json.dumps(id), "true" if all else "false")) or []


def text(id):
    return L("local c = B.find(%s); return c and B.info(c).text or ''" % json.dumps(id))


t0 = time.time()
while True:  # main menu tick
    hb = b.heartbeat() or {}
    if hb.get("screen") == "menu" and (hb.get("tick") or 0) > 0 and hb.get("age_s", 99) < 5:
        break
    if time.time() - t0 > 300:
        sys.exit("no main-menu heartbeat")
    time.sleep(2)

buttons = []
for cont in ("main_container", "dlc_container"):
    for k in kids(cont, all=True):
        if k.startswith("button_") and not k.endswith("_unowned") and k not in ("button_load_campaign",):
            buttons.append(k)
out = {}
for btn in buttons:
    label = L("local c = B.find(%s); local s = c and B.U(c:Find('string')); return s and s:GetStateText() or ''" % json.dumps(btn))
    print(btn, "|", label, flush=True)
    b.click(btn, force=True)
    time.sleep(4)
    groups = kids("faction_group_button_group")
    camp = {"label": label, "groups": {}}
    for g in groups:
        b.click(g)
        time.sleep(1.5)
        camp["groups"][g] = {"name": text("dy_faction/group_name"), "factions": kids("faction_button_group")}
        print("  ", g, camp["groups"][g], flush=True)
    out[btn] = camp
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("written", sys.argv[1])
