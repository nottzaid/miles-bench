"""Heavy vs light frames in a gputime.tsv: which segments make the difference.

    python3 bench/gpudiff.py <capture dir> [split ms, default: median busy]

Splits sampled frames by GPU busy time and prints, per segment label (as in gputime.py), the mean
ms per frame in each group and the difference, largest first.
"""
import collections
import statistics
import sys
sys.argv += [] 
cap = sys.argv[1]
sys.argv = [sys.argv[0], cap, "1e9", "0"]
exec(open(__file__.replace("gpudiff.py", "gputime.py")).read().split("per_frame = []")[0])

frame_busy = {}
frame_labels = collections.defaultdict(collections.Counter)
for fr in frames:
    keys = [k for k in cmds if k[0] == fr]
    busy = 0
    for k in keys:
        for s in segs[k]:
            busy += s[1]
            frame_labels[fr][(qname[cmds[k]["queue"]], label(s))] += s[1]
    frame_busy[fr] = busy / 1e6
split = float(sys.argv_split) if False else statistics.median(frame_busy.values())
heavy = [f for f, b in frame_busy.items() if b > split]
light = [f for f, b in frame_busy.items() if b <= split]
print(f"{len(frames)} frames, split at {split:.2f} ms: heavy {len(heavy)} (mean {statistics.mean(frame_busy[f] for f in heavy):.2f} ms), "
      f"light {len(light)} (mean {statistics.mean(frame_busy[f] for f in light):.2f} ms)")
labels = set()
for f in frames:
    labels |= set(frame_labels[f])
rows = []
for lab in labels:
    h = sum(frame_labels[f][lab] for f in heavy) / len(heavy) / 1e6
    l = sum(frame_labels[f][lab] for f in light) / len(light) / 1e6
    hc = sum(1 for f in heavy if lab in frame_labels[f]) / len(heavy)
    lc = sum(1 for f in light if lab in frame_labels[f]) / len(light)
    rows.append((h - l, h, l, hc, lc, lab))
rows.sort(reverse=True)
for d, h, l, hc, lc, (q, lab) in rows[:25]:
    print(f"  {d:+6.2f} ms  heavy {h:6.2f} (in {100*hc:3.0f}%)  light {l:6.2f} (in {100*lc:3.0f}%)  {q} {lab}")
