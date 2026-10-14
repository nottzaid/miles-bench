"""DRAM traffic by source from the Haswell client memory controller (uncore_imc free-running counters).

Record (root; counters are read over MMIO, the game is not perturbed):
    date +%s.%N > <out>.start; sudo perf stat -a -x, -I 1000 -e uncore_imc/data_reads/,\
uncore_imc/data_writes/,uncore_imc/ia_requests/,uncore_imc/io_requests/,uncore_imc/gt_requests/ \
-- sleep <secs> 2> <out>.csv

    python3 bench/imc.py <out>.csv [capture dir]

data_reads/data_writes = all DRAM traffic; ia_requests = requests from the CPU cores, io_requests =
from PCIe devices (the GPU reading/writing system memory), gt_requests = integrated graphics (unused).
Each request is 64 B. With a capture dir, the 30 s measurement window (ending when window.txt was
written) is summarized; otherwise every 10th second is printed.
"""
import collections
import os
import statistics
import sys

csv = sys.argv[1]
start = float(open(csv.rsplit(".", 1)[0] + ".start").read())
rows = collections.defaultdict(dict)
for line in open(csv):
    f = line.strip().split(",")
    if len(f) < 4 or not f[0][:1].isdigit() or not f[1].replace(".", "").isdigit():
        continue
    rows[start + float(f[0])][f[3].split("/")[1]] = float(f[1]) / 1024  # MiB -> GiB per 1 s interval
keys = ["data_reads", "data_writes", "ia_requests", "io_requests"]


def show(label, ts):
    if not ts:
        print(f"{label}: no samples")
        return
    m = {k: statistics.mean(rows[t].get(k, 0) for t in ts) for k in keys}
    print(f"{label}: DRAM read {m['data_reads']:.2f} + write {m['data_writes']:.2f} = "
          f"{m['data_reads'] + m['data_writes']:.2f} GiB/s; CPU cores {m['ia_requests']:.2f}, "
          f"PCIe (GPU) {m['io_requests']:.2f} GiB/s  ({len(ts)} s)")


if len(sys.argv) > 2:
    end = os.path.getmtime(os.path.join(sys.argv[2], "window.txt"))
    show("window", [t for t in rows if end - 31 <= t <= end - 1])
else:
    for t in sorted(rows):
        if round(t - start) % 10 == 0:
            show(f"{t - start:5.0f} s", [t])
