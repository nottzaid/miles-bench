"""Which of the game's pages stay swapped out for a whole session and which keep cycling.

    python3 bench/coldpages.py <out dir> [seconds, default 180] [interval, default 10]

Snapshots /proc/<pid>/pagemap of every private writable mapping each <interval> seconds (the
present and swapped bits only, so no root needed) and reports per mapping:
  cold     swapped in every snapshot (never touched while measured): candidates for dead data
  churn    swapped in one snapshot and present in a later one, or the other way round: the pages
           memory pressure keeps evicting and the game keeps paging back in
  hot      present in every snapshot
Writes <out>/coldpages.txt. Run it while bench/fightdrive.sh drives the game.
"""
import collections
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import enginectl  # noqa: E402

out = sys.argv[1]
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 180
step = float(sys.argv[3]) if len(sys.argv) > 3 else 10
os.makedirs(out, exist_ok=True)
pid = enginectl.game_pid()

regions = []
for line in open(f"/proc/{pid}/maps"):
    f = line.split(None, 5)
    lo, hi = (int(x, 16) for x in f[0].split("-"))
    name = f[5].strip() if len(f) > 5 else ""
    if "w" in f[1] and "p" in f[1] and (not name or name.startswith("[")) and hi - lo >= 1 << 20:
        regions.append((lo, hi, name))

pm = open(f"/proc/{pid}/pagemap", "rb", buffering=0)


def snapshot():
    """Per region: uint8 per page, 1 = present, 2 = swapped, 0 = neither."""
    res = []
    for lo, hi, _ in regions:
        pm.seek((lo >> 12) * 8)
        e = np.frombuffer(pm.read(((hi - lo) >> 12) * 8), dtype=np.uint64)
        st = ((e >> np.uint64(63)) & np.uint64(1)).astype(np.uint8) | (((e >> np.uint64(62)) & np.uint64(1)).astype(np.uint8) << 1)
        res.append(st)
    return res


first = snapshot()
ever_present = [s == 1 for s in first]
ever_swapped = [s == 2 for s in first]
always_swapped = [s == 2 for s in first]
always_present = [s == 1 for s in first]
n = 1
t0 = time.time()
while time.time() - t0 < secs:
    time.sleep(step)
    try:
        snap = snapshot()
    except OSError:
        break
    n += 1
    for i, s in enumerate(snap):
        ever_present[i] |= s == 1
        ever_swapped[i] |= s == 2
        always_swapped[i] &= s == 2
        always_present[i] &= s == 1

mib = lambda pages: pages * 4096 / 1048576
rows = []
tot = collections.Counter()
for i, (lo, hi, name) in enumerate(regions):
    c = dict(cold=int(always_swapped[i].sum()), hot=int(always_present[i].sum()),
             churn=int((ever_present[i] & ever_swapped[i]).sum()))
    tot.update(c)
    rows.append((c["cold"] + c["churn"], lo, hi, name, c))
with open(os.path.join(out, "coldpages.txt"), "w") as f:
    head = (f"pid {pid}, {n} snapshots over {time.time() - t0:.0f} s: cold (swapped throughout) {mib(tot['cold']):.0f} MiB, "
            f"churn (swapped and present at different times) {mib(tot['churn']):.0f} MiB, hot (present throughout) "
            f"{mib(tot['hot']):.0f} MiB")
    print(head)
    f.write(head + "\n")
    line = f"{'mapping':>34s} {'size':>6s} {'cold':>6s} {'churn':>6s} {'hot':>6s}  name"
    print(line)
    f.write(line + "\n")
    for _, lo, hi, name, c in sorted(rows, reverse=True)[:30]:
        line = (f"{lo:#16x}-{hi:#16x} {mib((hi - lo) >> 12):6.0f} {mib(c['cold']):6.0f} {mib(c['churn']):6.0f} "
                f"{mib(c['hot']):6.0f}  {name}")
        print(line)
        f.write(line + "\n")
