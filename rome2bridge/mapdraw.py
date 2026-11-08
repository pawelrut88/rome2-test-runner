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
    """The faction's colour as the game has it (DeI's if DeI); a light one (it would vanish on the parchment) is
    swapped for its second colour or darkened; an unknown faction gets a steady colour made from its key."""
    cols = data()["colours"]
    pair = (dei and cols["dei"].get(faction)) or cols["vanilla"].get(faction)
    c = _rgb(pair[0]) if pair else None
    if c is None:
        d = md5(faction.encode()).digest()
        return (60 + d[0] % 160, 60 + d[1] % 160, 60 + d[2] % 160)
    lum = lambda x: 0.3 * x[0] + 0.59 * x[1] + 0.11 * x[2]
    if lum(c) > 185:
        c2 = _rgb(pair[1]) if len(pair) > 1 else None
        c = c2 if c2 and lum(c2) <= 185 else tuple(int(v * 0.55) for v in c)
    return c


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


def overlay_png(m, owners, human=(), selected=None, dei=False):
    """The colour layer for one turn: owners {region key: faction}. Returns PNG bytes (RGBA, the drawn size)."""
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
    for mask, col in ((hum, (255, 255, 255)), (sel, (255, 220, 0))):
        if not any(mask):
            continue
        e = _edges(idx.translate(bytes(mask)), w, n)
        if not e:
            continue
        p = e.find(1)
        while p >= 0:
            px[4 * p:4 * p + 4] = bytes((col[0], col[1], col[2], 255))
            p = e.find(1, p + 1)
    return png_rgba(w, h, px)


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
