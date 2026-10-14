"""Where the GPU time of a frame goes, from a gputime.tsv (VKD3D_BENCH_GPUTIME, gputime.c).

    python3 bench/gputime.py <capture dir> [seconds at the end to use, default 30] [top N]

Per sampled frame and queue: the GPU's busy time (segments' union), idle gaps, and the time per
kind of segment. Then the heaviest segments, matched across frames by what they hold (render pass
size and draws, or dispatches and first pipeline), averaged over the sampled frames.

Timestamps are NVIDIA's global timer (ns since the epoch), so they line up with the frame trace.
"""
import collections
import statistics
import sys

cap = sys.argv[1]
window_s = float(sys.argv[2]) if len(sys.argv) > 2 else 30
top = int(sys.argv[3]) if len(sys.argv) > 3 else 30

cmds = {}   # (frame, seq) -> dict(queue, start)
segs = collections.defaultdict(list)  # (frame, seq) -> [(end, dur, kind, draws, disp, groups, copies, clears, binds, wh, pipe)]
for line in open(f"{cap}/gputime.tsv"):
    f = line.rstrip("\n").split("\t")
    if f[0] == "GS":
        cmds[(int(f[1]), int(f[3]))] = {"queue": f[2], "start": int(f[4])}
    elif f[0] == "GT":
        segs[(int(f[1]), int(f[3]))].append((int(f[4]), int(f[5]), f[6], int(f[7]), int(f[8]), int(f[9]),
                                             int(f[10]), int(f[11]), int(f[12]), f[13], f[14],
                                             f[15] if len(f) > 15 else "", f[16] if len(f) > 16 else ""))

last = max(c["start"] for c in cmds.values())
frames = sorted({fr for (fr, _), c in cmds.items() if c["start"] > last - window_s * 1e9})
queues = sorted({c["queue"] for c in cmds.values()})
qname = {q: f"q{i}" for i, q in enumerate(queues)}


def label(s):
    end, dur, kind, draws, disp, groups, copies, clears, binds, wh, pipe, shader, dims = s
    if kind == "e":
        return f"pass {wh} draws~{round(draws, -1) if draws > 20 else draws} binds~{round(binds, -1) if binds > 20 else binds}"
    parts = []
    if disp:
        parts.append(f"dispatch x{disp} " + (f"shader {shader} [{dims}]" if shader and shader != "0" * 16 else f"pipe {pipe[-6:]} (indirect)"))
    if copies:
        parts.append(f"copy x{copies}")
    if clears:
        parts.append(f"fill/clear x{clears}")
    if draws:
        parts.append(f"draws x{draws} in {wh}")
    return " + ".join(parts) or f"empty ({kind})"


per_frame = []
by_label = collections.defaultdict(list)
for fr in frames:
    keys = [k for k in cmds if k[0] == fr]
    out = {"frame": fr}
    for q in queues:
        ks = sorted((k for k in keys if cmds[k]["queue"] == q), key=lambda k: cmds[k]["start"])
        if not ks:
            continue
        intervals, cats = [], collections.Counter()
        prev_end = None
        idle = 0
        for k in ks:
            start = cmds[k]["start"]
            if prev_end is not None and start > prev_end:
                idle += start - prev_end
            for s in segs[k]:
                end, dur = s[0], s[1]
                intervals.append((end - dur, end))
                lab = label(s)
                cat = "render passes" if s[2] == "e" else ("compute" if s[4] else "copies/fills" if (s[6] or s[7]) else "draws outside pass" if s[3] else "empty (sync/barrier)")
                cats[cat] += dur
                by_label[(qname[q], lab)].append((fr, dur))
            if segs[k]:
                prev_end = max(prev_end or 0, segs[k][-1][0])
        span = max(e for _, e in intervals) - min(s for s, _ in intervals)
        out[q] = {"span": span, "work": sum(cats.values()), "idle_between_cmdbufs": idle, "cats": cats, "cmdbufs": len(ks)}
    per_frame.append(out)

n = len(per_frame)
print(f"{n} sampled frames in the last {window_s:.0f} s; queues: " + ", ".join(f"{qname[q]}={q}" for q in queues))
for q in queues:
    rows = [f[q] for f in per_frame if q in f]
    if not rows:
        continue
    ms = lambda v: v / 1e6
    print(f"\n{qname[q]}: in {len(rows)} frames; command buffers {statistics.mean(r['cmdbufs'] for r in rows):.1f}/frame;"
          f" span {ms(statistics.mean(r['span'] for r in rows)):.2f} ms, segment time {ms(statistics.mean(r['work'] for r in rows)):.2f} ms,"
          f" idle between command buffers {ms(statistics.mean(r['idle_between_cmdbufs'] for r in rows)):.2f} ms")
    cats = collections.Counter()
    for r in rows:
        cats.update(r["cats"])
    for c, v in cats.most_common():
        print(f"   {c:24s} {ms(v / len(rows)):6.2f} ms/frame")

print(f"\nheaviest segments (ms per sampled frame, averaged over {n} frames; count = occurrences per frame):")
agg = []
for (q, lab), v in by_label.items():
    agg.append((sum(d for _, d in v) / n / 1e6, len(v) / n, q, lab, statistics.median(d for _, d in v) / 1e3))
agg.sort(reverse=True)
tot = sum(a[0] for a in agg)
for ms_, cnt, q, lab, med in agg[:top]:
    print(f"  {ms_:6.2f} ms {100 * ms_ / tot:5.1f}%  x{cnt:5.1f}  median {med:7.1f} us  {q}  {lab}")
