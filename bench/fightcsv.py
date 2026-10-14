"""Gameplay rows for the dashboard: one CSV row per fightrun.sh launch.

    python3 bench/fightcsv.py out.csv "<series name>=<run prefix>" ...

A run's step and round come from its name: <prefix>-<step>-<round> (v8-gp-S7-2) or
<prefix>-<A|B><round> with A/B mapped by --ab "A=S6,B=S7". With --window=N the frame and fault
columns come from bench/fightwin.py's <run>/fightwin<N>.json (fight start to the Nth autosave, the
same stretch of the fight for every build); swap-ins (system-wide) are then left empty.
"""
import csv
import glob
import json
import os
import re
import sys

out = sys.argv[1]
ab = {}
specs = []
window = None
for a in sys.argv[2:]:
    if a.startswith("--window="):
        window = int(a[9:])
    elif a.startswith("--ab="):
        ab = dict(kv.split("=") for kv in a[5:].split(","))
    else:
        specs.append(a.split("=", 1))
cols = ["series", "run", "step", "round", "secs", "fps", "p50_ms", "p95_ms", "p99_ms", "frames_over_40", "frames_over_100",
        "worst_ms", "swapins", "game_major_faults", "pinned_mib", "game_sys_mib", "game_video_mib", "demoted_mib",
        "lightgrid_losses"]
rows = []
for series, prefix in specs:
    for path in sorted(glob.glob(f"captures/{prefix}*/fight.json")):
        run = os.path.basename(os.path.dirname(path))
        tail = run[len(prefix):].lstrip("-")
        m = re.match(r"(S\d+)-(\d+)$", tail) or re.match(r"([AB])(\d+)$", tail)
        if not m:
            continue
        step = ab.get(m.group(1), m.group(1))
        r = json.loads(open(path).read().splitlines()[0])
        if window:
            wp = os.path.join(os.path.dirname(path), f"fightwin{window}.json")
            if not os.path.exists(wp):
                print(f"{run}: no {os.path.basename(wp)}, skipped", file=sys.stderr)
                continue
            r.update(json.load(open(wp)))
            r["swapins"] = None
        rows.append(dict(series=series, run=run, step=step, round=m.group(2), secs=round(r["secs"], 1),
                         fps=round(r["fps"], 2), p50_ms=round(r["p50"], 1), p95_ms=round(r["p95"], 1),
                         p99_ms=round(r["p99"], 1), frames_over_40=r["over40"], frames_over_100=r["over100"],
                         worst_ms=round(r["worst"]), swapins=r["swapins"], game_major_faults=r["majflt"],
                         pinned_mib=r["pinned_mib"], game_sys_mib=r.get("sys_mib"), game_video_mib=r.get("video_mib"),
                         demoted_mib=r.get("demoted_mib"), lightgrid_losses=r["lightgrid_loss"]))
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
print(f"{len(rows)} rows -> {out}")
