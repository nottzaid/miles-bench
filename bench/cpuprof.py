"""Where one game thread spends its CPU time: cycle sampling of that thread, by module and function.

    python3 bench/cpuprof.py <out dir> ["Render Thread"] [seconds, default 10] [top N]

Records `perf record -e cycles:u` on every thread with that name (no root needed), writes the game's
PE module list (bench/missprof.py modules) and prints self time per module and per function (.pdata
bounds for PE modules, perf's symbols for native ones such as the NVIDIA driver).
"""
import collections
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
import enginectl  # noqa: E402
import missprof  # noqa: E402

out = sys.argv[1]
name = sys.argv[2] if len(sys.argv) > 2 else "Render Thread"
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 10
top = int(sys.argv[4]) if len(sys.argv) > 4 else 40
os.makedirs(out, exist_ok=True)

pid = enginectl.game_pid()
tids = [t for t in os.listdir(f"/proc/{pid}/task") if open(f"/proc/{pid}/task/{t}/comm").read().strip() == name]
if not tids:
    sys.exit(f"no thread named {name!r}")
missprof.modules(out)
data = os.path.join(out, "cpu.data")
subprocess.run(["perf", "record", "-q", "-e", "cycles:u", "-F", "2000", "-t", ",".join(tids), "-o", data,
                "--", "sleep", str(secs)], check=True, stderr=subprocess.DEVNULL)
txt = subprocess.run(["perf", "script", "-i", data, "-F", "ip,sym,dso"], capture_output=True, text=True).stdout

mods = []
for line in open(os.path.join(out, "modules.tsv")):
    f = line.rstrip("\n").split("\t")
    if len(f) == 3:
        mods.append((int(f[0], 16), int(f[1], 16), f[2]))
mods.sort()
pdata = {}
by_mod, by_func = collections.Counter(), collections.Counter()
total = 0
pat = re.compile(r"^\s*([0-9a-f]+)\s+(.*?)\s+\((.*)\)\s*$")
for line in txt.splitlines():
    m = pat.match(line)
    if not m:
        continue
    ip, sym, dso = int(m.group(1), 16), m.group(2), m.group(3)
    total += 1
    for lo, hi, path in mods:
        if lo <= ip < hi:
            mod = path.rsplit("/", 1)[-1]
            if path not in pdata:
                try:
                    pdata[path] = missprof.Pdata(path)
                except Exception:
                    pdata[path] = None
            fn = pdata[path].func(ip - lo) if pdata[path] else ip - lo
            by_mod[mod] += 1
            by_func[(mod, f"{fn:#x}")] += 1
            break
    else:
        mod = dso.rsplit("/", 1)[-1] if dso and dso != "[unknown]" else "[anon]"
        by_mod[mod] += 1
        by_func[(mod, sym if sym and sym != "[unknown]" else "?")] += 1
print(f"{name}: {total} samples ({len(tids)} thread(s), {secs:.0f} s)")
for k, n in by_mod.most_common(12):
    print(f"  {100 * n / total:5.1f}%  {k}")
print("functions:")
for (mod, fn), n in by_func.most_common(top):
    print(f"  {100 * n / total:5.1f}%  {mod} {fn}")
