"""Drawn world map for the Progress window: the game's own strategic map with every region tinted in its owner's
colour, the player's faction outlined in white and a picked faction in yellow. Needs no camera and no screenshot,
so the whole map shows for every faction and campaign.

Inputs:
- maps\\map_data.json (tools\\build_map_data.py): per campaign map the map picture and region lookup picture in the
  game's pack, every region's map and lookup colour, faction colours (vanilla, DeI changes);
- the user's game files: data\\data_rome2.pack (or data.pack), read here directly (Rome II packs are not compressed);
- a turn's stats (scripts\\progress_stats.lua): region_keys per faction.
No PIL: the lookup picture (TGA, 8-bit palette) is read here, the colour layer is written as a PNG here, and Tk 8.6
reads the map PNG and lays the layer over it (photo copy -compositingrule overlay)."""
import base64
import json
import os
import struct
import zlib
from hashlib import md5

HERE = os.path.dirname(os.path.abspath(__file__))
SCALE = 2  # draw at half the pictures' size (2032x1664 -> 1016x832)
_data = None
_cache = {}  # (pack, map key) -> loaded map


def data():
    global _data
    if _data is None:
        _data = json.load(open(os.path.join(HERE, "maps", "map_data.json"), encoding="utf-8"))
    return _data


def read_pack_file(pack, inner):
    """The bytes of one file in a Rome II .pack (PFH4/PFH5 index; data follows the index in index order)."""
    want = inner.replace("/", "\\").lower()
    with open(pack, "rb") as f:
        h = f.read(28)
        if len(h) < 28 or h[:3] != b"PFH":
            raise ValueError("not a pack file: %s" % pack)
        flags, _, pi_size, n_files, fi_size = struct.unpack_from("<5I", h, 4)
        ext = 20 if flags & 0x100 else 0
        f.read(ext)
        f.read(pi_size)
        idx = f.read(fi_size)
        offset = 28 + ext + pi_size + fi_size
        pos, stamp = 0, 4 if flags & 0x40 else 0
        for _ in range(n_files):
            size = struct.unpack_from("<I", idx, pos)[0]
            pos += 4 + stamp
            end = idx.index(b"\0", pos)
            name = idx[pos:end].decode("ascii", "replace").lower()
            pos = end + 1
            if name == want:
                f.seek(offset)
                return f.read(size)
            offset += size
    raise KeyError("%s not in %s" % (inner, os.path.basename(pack)))


def read_tga_indexed(b):
    """8-bit colour-mapped TGA (type 1, uncompressed) -> (width, height, rows top-down as bytes, palette [(r,g,b)])."""
    id_len, cmap_type, kind = b[0], b[1], b[2]
    first, length, entry_bits = struct.unpack_from("<HHB", b, 3)
    w, h, bpp, desc = struct.unpack_from("<HHBB", b, 12)
    if kind != 1 or cmap_type != 1 or bpp != 8:
        raise ValueError("lookup picture: only 8-bit colour-mapped TGA is read (type %d, %d bpp)" % (kind, bpp))
    pos = 18 + id_len
    step = entry_bits // 8
    pal = [(0, 0, 0)] * 256
    for i in range(length):
        e = b[pos + i * step: pos + i * step + 3]  # BGR(A)
        if first + i < 256:
            pal[first + i] = (e[2], e[1], e[0])
    pos += length * step
    rows = [b[pos + y * w: pos + (y + 1) * w] for y in range(h)]
    if not desc & 0x20:  # origin bottom-left
        rows.reverse()
    return w, h, rows, pal


def png_rgba(w, h, px):
    """RGBA bytes -> PNG file bytes (filter 0, fast zlib)."""
    stride = w * 4
    raw = b"".join(b"\0" + bytes(px[y * stride:(y + 1) * stride]) for y in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


def game_pack(game_dir):
    for n in ("data_rome2.pack", "data.pack"):
        p = os.path.join(game_dir, "data", n)
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("data_rome2.pack / data.pack not found in %s\\data" % game_dir)


def map_for(region_keys):
    """The campaign map most of these regions belong to (None if none is known)."""
    regs = data()["regions"]
    count = {}
    for k in region_keys:
        if k in regs:
            count[regs[k][0]] = count.get(regs[k][0], 0) + 1
    return max(count, key=count.get) if count else None


def load_map(game_dir, key):
    """{"key", "png": map picture bytes, "w", "h" (drawn size), "idx": lookup indices (drawn size, top-down),
    "region_of": {palette index: region key}}; cached."""
    pack = game_pack(game_dir)
    ck = (pack, key)
    if ck in _cache:
        return _cache[ck]
    m = data()["maps"][key]
    png = read_pack_file(pack, m["image"])
    w, h, rows, pal = read_tga_indexed(read_pack_file(pack, m["lookup"]))
    rows = [r[::SCALE] for r in rows[::SCALE]]
    by_colour = {}
    for i, c in enumerate(pal):
        by_colour.setdefault("%02X%02X%02X" % c, i)
    region_of = {}
    for reg, (mk, col) in data()["regions"].items():
        if mk == key and col in by_colour:
            region_of[by_colour[col]] = reg
    out = {"key": key, "png": png, "w": len(rows[0]), "h": len(rows), "idx": b"".join(rows), "region_of": region_of,
           "full": (w, h)}
    _cache[ck] = out
    return out


def _rgb(hexs):
    try:
        return tuple(int(hexs[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, TypeError, IndexError):
        return None


def faction_colour(faction, dei=False):
    """The faction's colour as the game draws it on its own map (primary colour, DeI's if DeI). Light colours stay
    light (Carthage is cream-white in the game, user 2026-11-09). An unknown faction gets a steady colour made from
    its key."""
    cols = data()["colours"]
    pair = (dei and cols["dei"].get(faction)) or cols["vanilla"].get(faction)
    c = _rgb(pair[0]) if pair else None
    if c is None:
        d = md5(faction.encode()).digest()
        return (60 + d[0] % 160, 60 + d[1] % 160, 60 + d[2] % 160)
    return c


def is_light(c):
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2] > 185


def human_edge(factions, dei=False):
    """the outline colour of the player's faction: white, or near-black when its own colour is light"""
    return (20, 20, 20) if any(is_light(faction_colour(f, dei)) for f in factions) else (255, 255, 255)


def _edges(mask, w, n):
    """Border pixels of a 0/1 byte mask (3 px wide: the edge and its neighbours), as a 0/1 byte string."""
    a = int.from_bytes(mask, "big")
    if not a:
        return None
    full = (1 << (8 * n)) - 1
    inner = a & ((a << 8) & full) & (a >> 8) & ((a << (8 * w)) & full) & (a >> (8 * w))
    e = a & ~inner
    e = e | ((e << 8) & full) | (e >> 8) | ((e << (8 * w)) & full) | (e >> (8 * w))
    return e.to_bytes(n, "big")


def overlay_png(m, owners, human=(), selected=None, dei=False, forces=None, calib=None):
    """The colour layer for one turn: owners {region key: faction}; forces (forces_from_stats) are drawn when there
    is a calibration (calibrate). Returns PNG bytes (RGBA, the drawn size)."""
    w, h, idx = m["w"], m["h"], m["idx"]
    n = w * h
    tr = [bytearray(256) for _ in range(4)]
    hum, sel = bytearray(256), bytearray(256)
    for i, reg in m["region_of"].items():
        f = owners.get(reg)
        if not f:
            continue
        r, g, b = faction_colour(f, dei)
        tr[0][i], tr[1][i], tr[2][i], tr[3][i] = r, g, b, 140
        if f in human:
            hum[i] = 1
        if f == selected:
            sel[i] = 1
    px = bytearray(4 * n)
    for c in range(4):
        px[c::4] = idx.translate(bytes(tr[c]))
    for mask, col in ((hum, human_edge(human, dei)), (sel, (255, 220, 0))):
        if not any(mask):
            continue
        e = _edges(idx.translate(bytes(mask)), w, n)
        if not e:
            continue
        p = e.find(1)
        while p >= 0:
            px[4 * p:4 * p + 4] = bytes((col[0], col[1], col[2], 255))
            p = e.find(1, p + 1)
    if forces and calib:
        draw_forces(m, px, forces, calib, human, selected, dei)
    return png_rgba(w, h, px)


def regions_at_from_file(path):
    """The city positions ({region: [x, y]}) a stats file has (runs from 2026-11-09 on), or None."""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    r = d.get("regions_at") if isinstance(d, dict) else None
    return r if isinstance(r, dict) and r else None


def _centroids(m):
    """{palette index: (x, y)} middle of each region on the drawn-size lookup picture."""
    if "centroids" in m:
        return m["centroids"]
    w, h, idx = m["w"], m["h"], m["idx"]
    sx, sy, n = [0.0] * 256, [0.0] * 256, [0] * 256
    for y in range(h):
        row = idx[y * w:(y + 1) * w]
        x0 = 0
        while x0 < w:
            v = row[x0]
            x1 = x0 + 1
            while x1 < w and row[x1] == v:
                x1 += 1
            k = x1 - x0
            sx[v] += (x0 + x1 - 1) * k / 2.0; sy[v] += y * k; n[v] += k
            x0 = x1
    m["centroids"] = {i: (sx[i] / n[i], sy[i] / n[i]) for i in m["region_of"] if n[i]}
    return m["centroids"]


def calibrate(m, regions_at):
    """Game (logical) position -> drawn-map pixel for this map: px = ax*x + bx, py = ay*y + by.
    regions_at: {region: [x, y]} city positions from the stats. A straight-line fit of the cities to the middles of
    their regions, then a small search that puts as many cities as possible inside their own region (checked
    2026-11-08 on 4 maps: 185/186 GC DeI, 171/173 GC vanilla, 52/52 Gaul with the fit alone).
    Returns (ax, bx, ay, by, cities inside, cities) or None."""
    if not regions_at:
        return None
    key = ("calib", m["key"])
    if key in m:
        return m[key]
    inv = {r: i for i, r in m["region_of"].items()}
    c = _centroids(m)
    pts = []
    for r, xy in regions_at.items():
        i = inv.get(r)
        try:
            x, y = float(xy[0]), float(xy[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if i is not None and i in c:
            pts.append((x, y, i))
    if len(pts) < 4:
        return None

    def fit(a, b):
        k = len(a); ma, mb = sum(a) / k, sum(b) / k
        d = sum((x - ma) ** 2 for x in a)
        s = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / d if d else 1.0
        return s, mb - s * ma
    ax, bx = fit([p[0] for p in pts], [c[p[2]][0] for p in pts])
    ay, by = fit([p[1] for p in pts], [c[p[2]][1] for p in pts])
    w, h, idx = m["w"], m["h"], m["idx"]

    def score(ax, bx, ay, by):
        s = 0
        for x, y, i in pts:
            X, Y = int(ax * x + bx), int(ay * y + by)
            if 0 <= X < w and 0 <= Y < h and idx[Y * w + X] == i:
                s += 1
        return s
    best = (score(ax, bx, ay, by), ax, bx, ay, by)
    # refine: scale steps of 1%, then offsets of 2 px, x and y apart (they don't depend on each other much)
    for _ in range(3):
        _, ax, bx, ay, by = best
        for sx in (0.97, 0.98, 0.99, 1.0, 1.01, 1.02, 1.03):
            for dx in range(-12, 13, 2):
                nax = ax * sx
                nbx = bx + dx + (1 - sx) * ax * (sum(p[0] for p in pts) / len(pts))  # keep the middle in place
                s = score(nax, nbx, ay, by)
                if s > best[0]:
                    best = (s, nax, nbx, ay, by)
        _, ax, bx, ay, by = best
        for sy in (0.97, 0.98, 0.99, 1.0, 1.01, 1.02, 1.03):
            for dy in range(-12, 13, 2):
                nay = ay * sy
                nby = by + dy + (1 - sy) * ay * (sum(p[1] for p in pts) / len(pts))
                s = score(ax, bx, nay, nby)
                if s > best[0]:
                    best = (s, ax, bx, nay, nby)
    s, ax, bx, ay, by = best
    m[key] = (ax, bx, ay, by, s, len(pts))
    return m[key]


def forces_from_stats(stats):
    """[(faction, x, y, units, navy)] from the stats rows' forces_at (runs from 2026-11-09 on), or []."""
    out = []
    for name, f in (stats or {}).items():
        at = f.get("forces_at") or []
        if isinstance(at, dict):
            at = list(at.values())
        for a in at:
            if isinstance(a, dict):
                a = [a.get(k) for k in sorted(a, key=lambda k: int(k) if str(k).isdigit() else 0)]
            try:
                out.append((name, float(a[0]), float(a[1]), int(a[2] or 0), bool(a[3]) if len(a) > 3 else False))
            except (TypeError, ValueError, IndexError):
                pass
    return out


def _marker(px, w, h, cx, cy, r, fill, edge, square):
    """A filled circle (army) or square (fleet) with an edge, written into the RGBA buffer."""
    r2o, r2i = (r + 1.5) ** 2, (r - 0.5) ** 2
    for y in range(int(cy - r - 2), int(cy + r + 3)):
        if not 0 <= y < h:
            continue
        for x in range(int(cx - r - 2), int(cx + r + 3)):
            if not 0 <= x < w:
                continue
            if square:
                d = max(abs(x - cx), abs(y - cy))
                inner, outer = d <= r - 0.5, d <= r + 1.5
            else:
                d2 = (x - cx) ** 2 + (y - cy) ** 2
                inner, outer = d2 <= r2i, d2 <= r2o
            if outer:
                col = fill if inner else edge
                px[4 * (y * w + x):4 * (y * w + x) + 4] = bytes((col[0], col[1], col[2], 255))


def draw_forces(m, px, forces, calib, human=(), selected=None, dei=False):
    """Armies (circles) and fleets (squares) in their owner's colour; yours bigger with a white edge, the picked
    faction's with a yellow edge, the rest dark."""
    ax, bx, ay, by = calib[:4]
    w, h = m["w"], m["h"]
    # yours and the picked faction's last, so they are drawn on top
    order = sorted(forces, key=lambda f: (f[0] in human, f[0] == selected))
    for fac, x, y, n, navy in order:
        cx, cy = ax * x + bx, ay * y + by
        mine, sel = fac in human, fac == selected
        r = 5 if mine else 4 if sel else 3
        edge = human_edge((fac,), dei) if mine else (255, 220, 0) if sel else (25, 25, 25)
        _marker(px, w, h, cx, cy, r, faction_colour(fac, dei), edge, navy)


def owners_from_stats(stats):
    """{faction: stats row} (progress.load_stats) -> ({region: faction}, [human factions]), or (None, ...) when the
    stats have no region keys (runs made before 2026-11-08 late)."""
    owners, human, any_keys = {}, [], False
    for name, f in (stats or {}).items():
        keys = f.get("region_keys")
        if isinstance(keys, dict):  # a Lua list may come back as {"1": ...}
            keys = list(keys.values())
        if keys:
            any_keys = True
            for k in keys:
                owners[k] = name
        if f.get("human"):
            human.append(name)
    return (owners if any_keys else None), human


def tk_picture(master, m, overlay):
    """Tk PhotoImage of the map (drawn size) with the colour layer laid over it."""
    import tkinter as tk
    base = tk.PhotoImage(master=master, data=base64.b64encode(m["png"]).decode())
    if SCALE > 1:
        base = base.subsample(SCALE)
    lay = tk.PhotoImage(master=master, data=base64.b64encode(overlay).decode())
    out = tk.PhotoImage(master=master, width=m["w"], height=m["h"])
    out.tk.call(out, "copy", base)
    out.tk.call(out, "copy", lay, "-compositingrule", "overlay")
    return out
