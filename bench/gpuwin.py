"""GPU pass times per same-session window mode: which passes slow down under a load or a feature.

    python3 bench/gpuwin.py <capture dir> [memab.tsv|abf.tsv] [top N]

Needs a run with GPUTIME=1 (gputime.tsv) and window logs from bench/memab.py (t0 t1 mode ...) .
For each mode: busy time per sampled frame, then every segment (matched as in bench/gputime.py)
with its mean ms per sampled frame in each mode, sorted by the largest difference against the
first mode listed (memab: none).
"""
import collections
import statistics
import sys

cap = sys.argv[1]
wfile = sys.argv[2] if len(sys.argv) > 2 else "memab.tsv"
top = int(sys.argv[3]) if len(sys.argv) > 3 else 30

wins = []
for line in open(f"{cap}/{wfile}"):
    f = line.rstrip("\n").split("\t")
    wins.append((float(f[0]) * 1e9, float(f[1]) * 1e9, f[2]))
modes = list(dict.fromkeys(w[2] for w in wins))

cmds, segs = {}, collections.defaultdict(list)
for line in open(f"{cap}/gputime.tsv"):
    f = line.rstrip("\n").split("\t")
    if f[0] == "GS":
        cmds[(int(f[1]), int(f[3]))] = {"queue": f[2], "start": int(f[4])}
    elif f[0] == "GT":
        segs[(int(f[1]), int(f[3]))].append((int(f[4]), int(f[5]), f[6], int(f[7]), int(f[8]), int(f[9]),
                                             int(f[10]), int(f[11]), int(f[12]), f[13], f[14],
                                             f[15] if len(f) > 15 else "", f[16] if len(f) > 16 else ""))


def label(s):
    end, dur, kind, draws, disp, groups, copies, clears, binds, wh, pipe, shader, dims = s
    if kind == "e":
        return f"pass {wh} draws~{round(draws, -1) if draws > 20 else draws}"
    parts = []
    if disp:
        parts.append(f"dispatch {shader if shader and shader != '0' * 16 else 'pipe ' + pipe[-6:]} [{dims}]")
    if copies:
        parts.append("copy")
    if clears:
        parts.append("fill/clear")
    if draws:
        parts.append(f"draws in {wh}")
    return " + ".join(parts) or f"empty ({kind})"


frame_start = collections.defaultdict(lambda: float("inf"))
for (fr, _), c in cmds.items():
    frame_start[fr] = min(frame_start[fr], c["start"])
frame_mode = {}
for fr, t in frame_start.items():
    for t0, t1, m in wins:
        if t0 <= t <= t1:
            frame_mode[fr] = m
per = {m: collections.defaultdict(float) for m in modes}
busy = {m: [] for m in modes}
nfr = collections.Counter(frame_mode.values())
for (fr, seq), ss in segs.items():
    m = frame_mode.get(fr)
    if m is None:
        continue
    for s in ss:
        per[m][label(s)] += s[1]
for fr, m in frame_mode.items():
    iv = sorted((s[0] - s[1], s[0]) for k in cmds if k[0] == fr for s in segs[k])
    tot, cur = 0, None
    for a, b in iv:  # union of segment intervals = GPU busy
        if cur and a <= cur[1]:
            cur[1] = max(cur[1], b)
        else:
            if cur:
                tot += cur[1] - cur[0]
            cur = [a, b]
    if cur:
        tot += cur[1] - cur[0]
    busy[m].append(tot / 1e6)
for m in modes:
    if busy[m]:
        print(f"{m:6s}: {nfr[m]} sampled frames, GPU busy {statistics.mean(busy[m]):.2f} ms/frame "
              f"(median {statistics.median(busy[m]):.2f})")
base = modes[0]
labels = set().union(*(per[m] for m in modes))
rows = []
for lab in labels:
    v = {m: per[m][lab] / nfr[m] / 1e6 if nfr[m] else 0 for m in modes}
    rows.append((max(abs(v[m] - v[base]) for m in modes), lab, v))
rows.sort(reverse=True)
print("\n" + "".join(f"{m:>9s}" for m in modes) + "   ms per sampled frame, segment")
for _, lab, v in rows[:top]:
    print("".join(f"{v[m]:9.3f}" for m in modes) + f"   {lab}")
