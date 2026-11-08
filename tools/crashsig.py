# Crash signature from Rome 2 minidumps: exception code + faulting module + offset (stable across runs,
# unlike the stack hash). Compare a new loading-bar crash with earlier ones of known cause.
#   python crashsig.py <crash_report_dir> [n_latest]
import sys, os, struct, glob

def sig(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'MDMP'
    nstreams, rva = struct.unpack_from('<II', d, 8)
    streams = {}
    for i in range(nstreams):
        t, size, off = struct.unpack_from('<III', d, rva + 12 * i); streams[t] = (off, size)
    mods = []
    off, _ = streams[4]                                   # ModuleListStream
    n = struct.unpack_from('<I', d, off)[0]
    for i in range(n):
        m = off + 4 + 108 * i
        base, size = struct.unpack_from('<QI', d, m); name_rva = struct.unpack_from('<I', d, m + 20)[0]
        ln = struct.unpack_from('<I', d, name_rva)[0]
        mods.append((base, size, d[name_rva + 4:name_rva + 4 + ln].decode('utf-16le').split('\\')[-1]))
    off, _ = streams[6]                                   # ExceptionStream
    code, flags = struct.unpack_from('<II', d, off + 8)
    addr = struct.unpack_from('<Q', d, off + 8 + 16)[0]
    nparams = struct.unpack_from('<I', d, off + 8 + 24)[0]
    info = struct.unpack_from('<%dQ' % min(nparams, 2), d, off + 8 + 32) if nparams else ()
    for base, size, name in mods:
        if base <= addr < base + size: return code, name, addr - base, info
    return code, '?', addr, info

files = sorted(glob.glob(os.path.join(sys.argv[1], '*.mdmp')), key=os.path.getmtime)
for f in files[-int(sys.argv[2]) if len(sys.argv) > 2 else 0:]:
    try:
        code, mod, offv, info = sig(f)
        print('%s  code %08x  %s+0x%x  %s' % (os.path.basename(f)[1:20], code, mod, offv, ['0x%x' % x for x in info]))
    except Exception as e:
        print(os.path.basename(f), 'ERR', e)
