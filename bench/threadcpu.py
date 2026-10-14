"""CPU time per frame for each game thread (utime + stime from /proc, frames from the frame trace).

    python3 bench/threadcpu.py <capture dir> [seconds, default 20]

In a GPU-bound scene fps hides CPU savings; this shows them: the render thread's ms per frame is
how fast the game could go if the GPU kept up. Threads with the same name are summed.
"""
import collections
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import enginectl  # noqa: E402
from ab import frames_between, last_frame_t  # noqa: E402

cap = sys.argv[1]
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 20
pid = enginectl.game_pid()
hz = os.sysconf("SC_CLK_TCK")


def snap():
    out = collections.Counter()
    for t in os.listdir(f"/proc/{pid}/task"):
        try:
            name = open(f"/proc/{pid}/task/{t}/comm").read().strip()
            f = open(f"/proc/{pid}/task/{t}/stat").read().rsplit(")", 1)[1].split()
        except OSError:
            continue
        out[name] += int(f[11]) + int(f[12])  # utime + stime (fields 14, 15)
    return out


ft = os.path.join(cap, "frametrace.tsv")
a, ta, wa = snap(), last_frame_t(ft), time.time()
time.sleep(secs)
b, tb, wb = snap(), last_frame_t(ft), time.time()
frames = max(1, len(frames_between(ft, ta, tb)) - 1)
wall = wb - wa
print(f"{frames} frames in {wall:.1f} s ({frames / wall:.2f} fps)")
total = 0
for name, v in sorted(b.items(), key=lambda kv: -(kv[1] - a.get(kv[0], 0))):
    d = (v - a.get(name, 0)) / hz
    total += d
    if d / wall >= 0.01:
        print(f"  {100 * d / wall:6.1f}% of a core  {1000 * d / frames:6.2f} ms/frame  {name}")
print(f"  {100 * total / wall:6.1f}% total     {1000 * total / frames:6.2f} ms/frame")
