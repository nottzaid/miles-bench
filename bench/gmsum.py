"""Summary of a gaming-mode A/B series (bench/gmseries.sh): per run and per arm, the fight
metrics (fight.json) and the game's own VRAM accounting (game.log: Video Budget / Usage, demoted).

    python3 bench/gmsum.py <prefix>
"""
import glob
import json
import os
import re
import statistics
import sys

prefix = sys.argv[1]
bench = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cols = ["fps", "p50", "p99", "over40", "over100", "worst", "secs", "swapins", "majflt", "video_mib", "demoted_mib"]
line = re.compile(r"Video Budget: (\d+)MB Video Usage: (\d+)MB")
arms = {}
print(f"{'run':<12}" + "".join(f"{c:>13}" for c in cols + ["budget", "usage"]))
for cap in sorted(glob.glob(f"{bench}/captures/{prefix}-[AB]*")):
    run = os.path.basename(cap)
    try:
        fight = json.load(open(f"{cap}/fight.json"))
    except (OSError, ValueError):
        print(f"{run:<12} no fight.json")
        continue
    budget = usage = None
    try:
        rows = [tuple(map(int, m.groups())) for m in map(line.search, open(f"{cap}/game.log", errors="replace")) if m]
        if rows:
            budget = statistics.mean(r[0] for r in rows)
            usage = statistics.mean(r[1] for r in rows)
    except OSError:
        pass
    fight["budget"], fight["usage"] = budget, usage
    arm = run[len(prefix) + 1]
    arms.setdefault(arm, []).append(fight)
    print(f"{run:<12}" + "".join(f"{fight.get(c) if fight.get(c) is not None else float('nan'):>13.1f}" for c in cols + ["budget", "usage"]))
print()
for arm, runs in sorted(arms.items()):
    means = {c: statistics.mean(r[c] for r in runs if r.get(c) is not None) if any(r.get(c) is not None for r in runs) else float("nan")
             for c in cols + ["budget", "usage"]}
    print(f"{'mean ' + arm:<12}" + "".join(f"{means[c]:>13.1f}" for c in cols + ["budget", "usage"]))
if {"A", "B"} <= arms.keys():
    a = statistics.mean(r["fps"] for r in arms["A"])
    b = statistics.mean(r["fps"] for r in arms["B"])
    print(f"\nfps B vs A: {100 * (b - a) / a:+.1f}%  (A {min(r['fps'] for r in arms['A']):.2f}-{max(r['fps'] for r in arms['A']):.2f},"
          f" B {min(r['fps'] for r in arms['B']):.2f}-{max(r['fps'] for r in arms['B']):.2f})")
