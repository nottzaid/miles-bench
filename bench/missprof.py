"""Which CPU code makes the DRAM traffic: L3-miss sampling across the whole machine, attributed to
thread, module and (for PE modules) function via .pdata.

    python3 bench/missprof.py modules <out dir>      # game's PE modules -> <out>/modules.tsv
    sudo perf record -a -e offcore_response.all_requests.l3_miss.any_response -c 20000 \
        -o <out>/l3.data -- sleep 20
    sudo perf script -i <out>/l3.data -F comm,pid,tid,ip,sym,dso > <out>/l3.txt
    python3 bench/missprof.py report <out dir> [seconds] [top N]

Each sample stands for 20000 L3 misses (64 B each, so ~1.2 MiB of DRAM traffic). Streaming stores
to write-combined memory (upload heaps) are not L3 misses and are not counted here; the IMC
counters (bench/imc.py) see them.
"""
import bisect
import collections
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
PERIOD = 20000


def modules(out):
    import enginectl
    pid = enginectl.game_pid()
    with open(f"/proc/{pid}/maps") as f:
        maps = [line.split(None, 5) for line in f]
    rows = []
    with open(f"/proc/{pid}/mem", "rb") as mem:
        for p in maps:
            if len(p) < 6 or int(p[2], 16) != 0:
                continue
            path = p[5].rstrip()
            if not path.lower().endswith((".exe", ".dll")):
                continue
            base = int(p[0].split("-")[0], 16)
            try:
                mem.seek(base)
                hdr = mem.read(0x400)
            except OSError:
                continue
            if hdr[:2] != b"MZ":
                continue
            nt = struct.unpack_from("<I", hdr, 0x3c)[0]
            size = struct.unpack_from("<I", hdr, nt + 0x18 + 0x38)[0]
            rows.append((base, base + size, path))
    with open(os.path.join(out, "modules.tsv"), "w") as f:
        f.write(f"pid\t{pid}\n")
        for lo, hi, path in sorted(set(rows)):
            f.write(f"{lo:x}\t{hi:x}\t{path}\n")
    print(f"{len(rows)} PE modules of pid {pid}")


class Pdata:
    def __init__(self, path):
        import pefile
        pe = pefile.PE(path, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXCEPTION"]])
        self.starts = sorted({e.struct.BeginAddress for e in getattr(pe, "DIRECTORY_ENTRY_EXCEPTION", [])})

    def func(self, rva):
        i = bisect.bisect_right(self.starts, rva) - 1
        return self.starts[i] if i >= 0 else rva


def report(out, secs, top):
    pid = None
    mods = []
    for line in open(os.path.join(out, "modules.tsv")):
        f = line.rstrip("\n").split("\t")
        if f[0] == "pid":
            pid = int(f[1])
        else:
            mods.append((int(f[0], 16), int(f[1], 16), f[2]))
    los = [m[0] for m in mods]
    pdata = {}
    by_thread = collections.Counter()
    by_proc = collections.Counter()
    by_mod = collections.Counter()
    by_func = collections.Counter()
    total = 0
    pat = re.compile(r"^\s*(.+?)\s+(\d+)/(\d+)\s+([0-9a-f]+)\s+(.*?)\s+\((.*)\)\s*$")
    for line in open(os.path.join(out, "l3.txt"), errors="replace"):
        m = pat.match(line)
        if not m:
            continue
        comm, p, tid, ip, sym, dso = m.group(1), int(m.group(2)), m.group(3), int(m.group(4), 16), m.group(5), m.group(6)
        total += 1
        game = p == pid
        by_proc["game" if game else comm] += 1
        if not game:
            continue
        by_thread[comm] += 1
        i = bisect.bisect_right(los, ip) - 1
        if i >= 0 and ip < mods[i][1]:
            lo, hi, path = mods[i]
            name = path.rsplit("/", 1)[-1]
            by_mod[name] += 1
            if path not in pdata:
                try:
                    pdata[path] = Pdata(path.replace("Z:", "").replace("\\", "/") if not os.path.exists(path) else path)
                except Exception:
                    pdata[path] = None
            fs = pdata[path].func(ip - lo) if pdata[path] else ip - lo
            by_func[(name, fs)] += 1
        else:
            key = dso.rsplit("/", 1)[-1] if dso and dso != "[unknown]" else "[anon/jit]"
            by_mod[key] += 1
            by_func[(key, sym if sym and sym != "[unknown]" else "?")] += 1
    gib = lambda n: n * PERIOD * 64 / 2**30 / secs
    print(f"{total} samples over {secs:.0f} s = {gib(total):.2f} GiB/s of L3-miss traffic (reads + RFOs)")
    print("\nby process:")
    for k, n in by_proc.most_common(12):
        print(f"   {gib(n):6.2f} GiB/s  {100 * n / total:5.1f}%  {k}")
    g = by_proc["game"] or 1
    print("\ngame threads:")
    for k, n in by_thread.most_common(15):
        print(f"   {gib(n):6.2f} GiB/s  {100 * n / g:5.1f}%  {k}")
    print("\ngame modules:")
    for k, n in by_mod.most_common(15):
        print(f"   {gib(n):6.2f} GiB/s  {100 * n / g:5.1f}%  {k}")
    print("\ngame functions:")
    for (mod, f), n in by_func.most_common(top):
        fn = f"{f:#x}" if isinstance(f, int) else f
        print(f"   {gib(n):6.2f} GiB/s  {100 * n / g:5.1f}%  {mod} {fn}")


if __name__ == "__main__":
    if sys.argv[1] == "modules":
        modules(sys.argv[2])
    else:
        report(sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 20, int(sys.argv[4]) if len(sys.argv) > 4 else 40)
