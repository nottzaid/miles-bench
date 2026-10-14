"""One line per bench run: fps and frame times of the measured window, how long the save load took
and how many major faults (swap-ins) the game had by then.

    python3 bench/runsum.py <run> [<run> ...]

load = last "menu: Continue" to "scene settled" in build/<run>.series.log (or <run>-cfgrun.log), less
the 21 s the scene has to stay up to count as settled. faults = the game's major faults (samples.tsv)
at that moment.
"""
import os
import re
import sys
import time

bench = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print(f"{'run':16s} {'fps':>6s} {'p99':>5s} {'load s':>6s} {'faults':>8s} {'zram MB':>7s}  dropdst")
for run in sys.argv[1:]:
    cap = os.path.join(bench, "captures", run)
    log = next((p for p in (os.path.join(bench, "build", f"{run}.series.log"), os.path.join(bench, "build", f"{run}-cfgrun.log"))
                if os.path.exists(p)), None)
    fps = p99 = "-"
    if os.path.exists(os.path.join(cap, "window.txt")):
        w = open(os.path.join(cap, "window.txt")).read()
        m = re.search(r"^fps ([\d.]+) .*? p99 ([\d.]+)", w, re.M)
        if m:
            fps, p99 = m.group(1), m.group(2)
    cont = settled = None
    if log:
        for line in open(log):
            m = re.match(r"^(\d\d:\d\d:\d\d) (.*)$", line)
            if m and m.group(2).startswith("menu: Continue"):
                cont = m.group(1)
            elif m and m.group(2).startswith("scene settled"):
                settled = m.group(1)
    load = faults = zram = "-"
    if cont and settled:
        day = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(os.path.join(cap, "samples.tsv"))))
        ts = lambda hms: time.mktime(time.strptime(f"{day} {hms}", "%Y-%m-%d %H:%M:%S"))
        t_set = ts(settled) - 21
        load = f"{t_set - ts(cont):.0f}"
        rows = [l.rstrip("\n").split("\t") for l in open(os.path.join(cap, "samples.tsv"))][1:]
        before = [r for r in rows if r[9] and float(r[0]) <= t_set]
        if before:
            faults = before[-1][9]
            zram = max(int(r[7]) for r in before if r[7])
    stats = ""
    vlog = os.path.join(cap, "vkd3d.log")
    if os.path.exists(vlog):
        for line in open(vlog, errors="replace"):
            if "dropdst:" in line:
                stats = line.split("dropdst:", 1)[1].strip()
    print(f"{run:16s} {fps:>6s} {p99:>5s} {load:>6s} {faults:>8s} {zram!s:>7s}  {stats[:200]}")
