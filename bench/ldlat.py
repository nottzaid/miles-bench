"""Where the game's CPU threads stall on memory: PEBS load-latency samples (loads > 30 cycles)
attributed to the memory region they read.

    pid=$(pgrep -x MilesMorales.ex); cp /proc/$pid/maps <cap>/maps.txt
    perf record -W -d -e cpu/mem-loads,ldlat=30/upp -c 500 -p $pid -o <cap>/ldlat.data -- sleep 8
    perf script -i <cap>/ldlat.data -F comm,ip,addr,weight,data_src > <cap>/ldlat.txt
    python3 bench/ldlat.py <cap>

Weight = load latency in cycles, so a region's share of the total weight is its share of the
sampled stall time. The 800 MiB nvidiactl mapping is the engine's geometry heap.
"""
import bisect
import collections
import re
import sys

cap = sys.argv[1]
maps = []
for line in open(f"{cap}/maps.txt"):
    p = line.split(None, 5)
    lo, hi = (int(x, 16) for x in p[0].split("-"))
    name = p[5].strip().rsplit("/", 1)[-1] if len(p) > 5 else "[anon]"
    maps.append((lo, hi, f"{name} {(hi - lo) >> 20}MiB"))
maps.sort()
los = [m[0] for m in maps]


def region(a):
    i = bisect.bisect_right(los, a) - 1
    return maps[i][2] if i >= 0 and a < maps[i][1] else "?"


pat = re.compile(r"\s*(.+?)\s+([0-9a-f]+)\s+[0-9a-f]+\s+\|OP LOAD\|LVL ([^|]+)\|.*\|BLK\s+\S+\s+(\d+)\s+([0-9a-f]+)\s*$")
w, n, th = collections.Counter(), collections.Counter(), collections.Counter()
tot = 0
for line in open(f"{cap}/ldlat.txt"):
    m = pat.match(line)
    if not m:
        continue
    comm, addr, wt = m.group(1), int(m.group(2), 16), int(m.group(4))
    r = region(addr)
    w[r] += wt
    n[r] += 1
    tot += wt
    if r.startswith("nvidiactl 800MiB"):
        th[comm] += wt
print(f"{sum(n.values())} sampled loads > 30 cycles, total weight {tot}")
for r, x in w.most_common(8):
    print(f"  {100 * x / tot:5.1f}% of stall weight  {n[r]:6d} samples  avg {x / n[r]:5.0f} cycles  {r}")
print("geometry heap stall by thread: " + ", ".join(f"{t} {100 * x / tot:.1f}%" for t, x in th.most_common(5)))
