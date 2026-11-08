# Build rome2bridge\maps\map_data.json for the Progress window's drawn map (mapdraw.py): for every campaign map, the
# map picture and the region lookup picture inside the game's pack; every region's map and lookup colour; every
# faction's colour (vanilla, and DeI's changes). Only keys, colours and file paths: the pictures themselves are read
# from the user's own game files when a map is drawn.
# Needs RPFM's rpfm_cli.exe and its Rome II schema (developer tool; the program itself does not need RPFM).
#   python tools\build_map_data.py
# Env: RPFM_CLI, RPFM_SCHEMA, ROME2_GAME_DIR (defaults below).
import csv, glob, json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RPFM = os.environ.get("RPFM_CLI", r"F:\ROME2\ConsulScriptum\.deps\rpfm_cli\rpfm_cli.exe")
SCHEMA = os.environ.get("RPFM_SCHEMA", r"F:\ROME2\ConsulScriptum\.deps\rpfm_schema\schema_rom2.ron")
GAME = os.environ.get("ROME2_GAME_DIR", r"F:\Steam\steamapps\common\Total War Rome II")
DATA = os.path.join(GAME, "data")
BASE = "data_rome2.pack"  # the Emperor Edition pack: has every campaign map (data.pack has them too)
DEI = "_divide_et_impera_release_12_Part1.pack"


def rpfm(*args):
    r = subprocess.run([RPFM, "--game", "rome_2", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("rpfm_cli failed: %s" % (r.stderr or r.stdout)[-500:])
    return r.stdout


def tables(pack, paths, out):
    args = ["pack", "extract", "-p", os.path.join(DATA, pack), "--tables-as-tsv", SCHEMA]
    for p in paths:
        args += ["-f", "%s;%s" % (p, out)]
    rpfm(*args)


def rows(path):
    r = list(csv.reader(open(path, encoding="utf-8"), delimiter="\t"))
    head = r[0]
    return [dict(zip(head, x)) for x in r[2:] if x]


def main():
    tmp = tempfile.mkdtemp(prefix="r2b_mapdata_")
    try:
        listing = [l.strip().replace("\\", "/") for l in rpfm("pack", "list", "-p", os.path.join(DATA, BASE)).splitlines()]
        maps = {}
        for l in listing:
            m = re.match(r"^campaign_maps/([^/]+)/([^/]+)$", l)
            if not m or "minimap" in m.group(2):
                continue
            kind = "image" if m.group(2).endswith("_map.png") else "lookup" if m.group(2).endswith("_lookup.tga") else None
            if kind:
                maps.setdefault(m.group(1), {})[kind] = l
        maps = {k: v for k, v in maps.items() if "image" in v and "lookup" in v}
        tables(BASE, ["db/regions_tables/regions", "db/campaign_map_regions_tables/campaign_map_regions",
                      "db/factions_tables/factions"], os.path.join(tmp, "base"))
        on_map = {r["region"]: r["campaign_map"] for r in rows(glob.glob(os.path.join(tmp, "base", "**", "campaign_map_regions.tsv"), recursive=True)[0])}
        regions = {}
        for r in rows(glob.glob(os.path.join(tmp, "base", "**", "regions.tsv"), recursive=True)[0]):
            if r["key"] in on_map and on_map[r["key"]] in maps:
                regions[r["key"]] = [on_map[r["key"]], r["unnamed colour group_1"].upper()]
        def colours(path):
            return {r["key"]: [r["primary_colour_hex"].upper(), r["secondary_colour_hex"].upper()]
                    for r in rows(path) if r.get("primary_colour_hex")}
        vanilla = colours(glob.glob(os.path.join(tmp, "base", "**", "factions.tsv"), recursive=True)[0])
        dei = {}
        dei_tables = [l.strip().replace("\\", "/") for l in rpfm("pack", "list", "-p", os.path.join(DATA, DEI)).splitlines()
                      if l.strip().replace("\\", "/").startswith("db/factions_tables/")]
        if dei_tables:
            tables(DEI, dei_tables, os.path.join(tmp, "dei"))
            # same key in several tables of one pack: the table whose name sorts first wins, so apply it last
            for p in sorted(glob.glob(os.path.join(tmp, "dei", "**", "*.tsv"), recursive=True), reverse=True):
                dei.update(colours(p))
        dei = {k: v for k, v in dei.items() if vanilla.get(k) != v}
        out = {"source": "%s, %s (tools/build_map_data.py)" % (BASE, DEI), "maps": maps, "regions": regions,
               "colours": {"vanilla": vanilla, "dei": dei}}
        os.makedirs(os.path.join(ROOT, "rome2bridge", "maps"), exist_ok=True)
        p = os.path.join(ROOT, "rome2bridge", "maps", "map_data.json")
        json.dump(out, open(p, "w", encoding="utf-8"), indent=0, sort_keys=True)
        print("%s: %d maps, %d regions, %d faction colours (+%d DeI changes)" % (p, len(maps), len(regions), len(vanilla), len(dei)))
        for k, v in sorted(maps.items()):
            print("  %-16s %s | %s | %d regions" % (k, v["image"], v["lookup"], sum(1 for r in regions.values() if r[0] == k)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
