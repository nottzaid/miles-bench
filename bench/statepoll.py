"""Render-thread state timeline from outside the game (no patch): polls the engine's render thread
state word (0x83cd138: 1 = waiting for the game thread's next frame, 2 = frame handed over,
3 = executing render commands, 4 = finalizing, 5 = after the GUI/present section) through
/proc/<pid>/mem.

    python3 bench/statepoll.py [seconds, default 10] [poll Hz, default 2000]

Prints, per render-thread frame, how long it waited for the game thread (state 1) and how long it
worked (2..5), plus averages.
"""
import os, re, statistics, sys, time

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 10
hz = float(sys.argv[2]) if len(sys.argv) > 2 else 2000
pid = int(os.popen("pgrep -x MilesMorales.ex").read().split()[0])
base = None
for line in open(f"/proc/{pid}/maps"):
    if "MilesMorales.exe" in line and " 00000000 " in line:
        base = int(line.split("-")[0], 16)
        break
addr = base + 0x83cd138
fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
period = 1 / hz
samples = []
t_end = time.perf_counter() + secs
nxt = time.perf_counter()
while True:
    now = time.perf_counter()
    if now > t_end:
        break
    v = int.from_bytes(os.pread(fd, 4, addr), "little")
    samples.append((now, v))
    nxt += period
    d = nxt - time.perf_counter()
    if d > 0:
        time.sleep(d)
# segment into runs of equal state
runs = []
for t, v in samples:
    if runs and runs[-1][0] == v:
        runs[-1][2] = t
    else:
        runs.append([v, t, t])
# a render frame: from the start of a state-1 run to the start of the next state-1 run
frames = []
i = 0
starts = [k for k, r in enumerate(runs) if r[0] == 1]
for a, b in zip(starts, starts[1:]):
    wait = runs[a + 1][1] - runs[a][1] if a + 1 < len(runs) else 0
    total = runs[b][1] - runs[a][1]
    frames.append((wait * 1000, (total - wait) * 1000, total * 1000))
achieved = len(samples) / secs
print(f"{len(samples)} samples ({achieved:.0f} Hz), {len(frames)} render-thread frames")
if frames:
    w = [f[0] for f in frames]; b = [f[1] for f in frames]; t = [f[2] for f in frames]
    print(f"waiting for game thread: mean {statistics.mean(w):.2f} ms, median {statistics.median(w):.2f}, p90 {sorted(w)[int(.9*len(w))]:.2f}")
    print(f"rendering (state 2-5):   mean {statistics.mean(b):.2f} ms, median {statistics.median(b):.2f}, p90 {sorted(b)[int(.9*len(b))]:.2f}")
    print(f"frame period:            mean {statistics.mean(t):.2f} ms")
    per_state = {}
    for v, t0, t1 in runs:
        per_state[v] = per_state.get(v, 0) + (t1 - t0)
    print("time share by state: " + ", ".join(f"{k}: {100 * v / secs:.0f}%" for k, v in sorted(per_state.items())))
