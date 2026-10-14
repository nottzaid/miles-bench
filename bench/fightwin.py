"""Gameplay metrics of fightrun.sh launches over the same stretch of the fight: from the start of
the fight to the game's Nth autosave (the start of a phase), so builds that play faster are not
measured over later, heavier phases.

    python3 bench/fightwin.py <n> <capture dir>...

Frames from frametrace.tsv (mapped to wall time through fight-start.json), the game's major faults
from samples.tsv (cumulative, every 2 s, interpolated), autosave times from game.log. One JSON line
per capture on stdout (also saved as <capture>/fightwin<n>.json), a readable line on stderr.
"""
import json
import os
import sys
import time

n = int(sys.argv[1])
for cap in sys.argv[2:]:
    m = json.load(open(os.path.join(cap, "fight-start.json")))
    day = time.strftime("%Y-%m-%d", time.localtime(m["wall"]))
    saves = []
    for line in open(os.path.join(cap, "game.log"), errors="ignore"):
        if "[Save] Request save type" in line:
            hh, mm, ss, ms = line[:12].split(":")
            saves.append(time.mktime(time.strptime(f"{day} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S")) + int(ms) / 1000)
    saves = [s for s in saves if s > m["wall"]]
    if len(saves) < n:
        print(f"{os.path.basename(cap)}: only {len(saves)} autosaves", file=sys.stderr)
        continue
    w0, w1 = m["wall"], saves[n - 1]
    ta, tb = m["t"], m["t"] + (w1 - w0) * 1000
    t = []
    for line in open(os.path.join(cap, "frametrace.tsv")):
        if line.startswith("F\t"):
            x = float(line.split("\t", 2)[1])
            if ta < x <= tb:
                t.append(x)
    iv = sorted(b - a for a, b in zip(t, t[1:]))
    q = lambda p: iv[min(len(iv) - 1, int(p * len(iv)))]
    samp = [l.split("\t") for l in open(os.path.join(cap, "samples.tsv")).read().splitlines()[1:]]
    samp = [(int(s[0]), int(s[9])) for s in samp if len(s) > 9 and s[9].isdigit()]

    def majflt_at(w):
        for (ta_, fa), (tb_, fb) in zip(samp, samp[1:]):
            if ta_ <= w <= tb_:
                return fa + (fb - fa) * (w - ta_) / max(1, tb_ - ta_)
        return None

    fa, fb = majflt_at(w0), majflt_at(w1)
    fj = os.path.join(cap, "fight.json")
    if (fa is None or fb is None) and os.path.exists(fj):
        # The run ended at this autosave (FIGHT_SAVES=n), past the last 2 s sample: fightsum.py read
        # the game's fault counter at the start and right after the save.
        whole = json.loads(open(fj).read().splitlines()[0])
        if abs(whole["secs"] - (w1 - w0)) < 3:
            fa, fb = 0, whole["majflt"]
    row = dict(run=os.path.basename(cap), saves=n, secs=w1 - w0, fps=len(iv) / ((t[-1] - t[0]) / 1000),
               p50=q(.5), p95=q(.95), p99=q(.99), over40=sum(x > 40 for x in iv), over100=sum(x > 100 for x in iv),
               worst=iv[-1], majflt=round(fb - fa) if fa is not None and fb is not None else None)
    print(json.dumps(row))
    with open(os.path.join(cap, f"fightwin{n}.json"), "w") as f:
        f.write(json.dumps(row) + "\n")
    print(f"{row['run']}: to autosave {n} in {row['secs']:.0f} s, {row['fps']:.2f} fps, p50 {row['p50']:.1f} p95 {row['p95']:.1f} "
          f"p99 {row['p99']:.1f} ms, {row['over40']} >40 ms, {row['over100']} >100 ms, worst {row['worst']:.0f} ms, "
          f"{row['majflt']} major faults", file=sys.stderr)
