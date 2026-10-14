"""Hitch attribution: what the game's threads were doing during the slowest render-thread frames.

    python3 bench/hitch.py <out dir> [seconds, default 30] [threads, default "main,Render Thread"]

Frame boundaries come from polling the render thread's state word (as bench/statepoll.py; 1 =
waiting for the game thread). At the same time, with CLOCK_MONOTONIC timestamps:
  - perf record cycles:u on the chosen threads (where they run), no root;
  - sudo perf record sched:sched_switch with kernel+user call chains for those threads (where and
    why they sleep: futex, page fault / swap-in, disk read, ...).
"main" means the thread whose tid is the process id. The sudo password is read from $SUDO_PW and
passed on stdin only. For each frame slower than 2x the median it prints, per thread, the on-CPU
functions and the longest sleeps with their kernel and first user frames.
"""
import bisect
import collections
import itertools
import os
import re
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import enginectl  # noqa: E402
import missprof  # noqa: E402

out = sys.argv[1]
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 30
names = (sys.argv[3] if len(sys.argv) > 3 else "main,Render Thread").split(",")
os.makedirs(out, exist_ok=True)

pid = enginectl.game_pid()
comm = {}
for t in os.listdir(f"/proc/{pid}/task"):
    try:
        comm[int(t)] = open(f"/proc/{pid}/task/{t}/comm").read().strip()
    except OSError:
        pass
watch = {}
for n in names:
    for tid, c in comm.items():
        if (n == "main" and tid == pid) or c == n:
            watch[tid] = f"{'main' if n == 'main' else c}/{tid}"
if not watch:
    sys.exit("no matching threads")
missprof.modules(out)
base = None
for line in open(f"/proc/{pid}/maps"):
    if "MilesMorales.exe" in line and " 00000000 " in line:
        base = int(line.split("-")[0], 16)
        break
state_addr = base + 0x83cd138

cpu_data, sw_data = os.path.join(out, "cpu.data"), os.path.join(out, "sched.data")
reuse = bool(os.environ.get("HITCH_REUSE"))
rec = subprocess.Popen(["true"] if reuse else ["perf", "record", "-q", "-k", "CLOCK_MONOTONIC", "-e", "cycles:u", "-F", "4000",
                        "-t", ",".join(map(str, watch)), "-o", cpu_data, "--", "sleep", str(secs + 1)],
                       stderr=subprocess.DEVNULL)
pw = os.environ.get("SUDO_PW")
sw = None
if pw and not reuse:
    # System-wide with a filter: a switch-in happens in the context of the task leaving the CPU.
    filt = " || ".join(f"prev_pid == {t} || next_pid == {t}" for t in watch)
    sw = subprocess.Popen(["sudo", "-S", "-p", "", "perf", "record", "-q", "-k", "CLOCK_MONOTONIC",
                           "-e", "sched:sched_switch", "--filter", filt, "--call-graph", "fp", "-a", "-o", sw_data,
                           "--", "sleep", str(secs + 1)], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    sw.stdin.write((pw + "\n").encode())
    sw.stdin.close()
time.sleep(0.5)

fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
samples = []
if os.environ.get("HITCH_REUSE"):
    secs = 0
t_end = time.monotonic() + secs
period = 1 / 4000
nxt = time.monotonic()
while True:
    now = time.monotonic()
    if now > t_end:
        break
    samples.append((now, int.from_bytes(os.pread(fd, 4, state_addr), "little")))
    nxt += period
    d = nxt - time.monotonic()
    if d > 0:
        time.sleep(d)
rec.wait()
states = os.path.join(out, "states.tsv")
if samples:
    with open(states, "w") as f:
        f.writelines(f"{t:.6f}\t{v}\n" for t, v in samples)
else:
    samples = [(float(a), int(b)) for a, b in (l.split() for l in open(states))]
    secs = samples[-1][0] - samples[0][0]
if sw:
    sw.wait()
time.sleep(0 if reuse else 0.5)

# Render-thread frames: start of a state-1 run to the start of the next one.
runs = []
for t, v in samples:
    if runs and runs[-1][0] == v:
        runs[-1][2] = t
    else:
        runs.append([v, t, t])
starts = [k for k, r in enumerate(runs) if r[0] == 1]
frames = []
for a, b in zip(starts, starts[1:]):
    wait = runs[a + 1][1] - runs[a][1]
    frames.append((runs[a][1], runs[b][1], wait))
periods = [f[1] - f[0] for f in frames]
med = statistics.median(periods)
print(f"{len(samples) / secs:.0f} Hz state polling, {len(frames)} frames, median {med * 1e3:.1f} ms, "
      f"p99 {sorted(periods)[int(.99 * len(periods))] * 1e3:.1f} ms")

# Symbolization: PE modules through .pdata, the rest through perf's symbols.
mods = []
for line in open(os.path.join(out, "modules.tsv")):
    f = line.rstrip("\n").split("\t")
    if len(f) == 3:
        mods.append((int(f[0], 16), int(f[1], 16), f[2]))
mods.sort()
mod_lo = [m[0] for m in mods]
pdata = {}


def sym(ip, s, dso):
    i = bisect.bisect_right(mod_lo, ip) - 1
    if i >= 0 and mods[i][0] <= ip < mods[i][1]:
        lo, _, path = mods[i]
        if path not in pdata:
            try:
                pdata[path] = missprof.Pdata(path)
            except Exception:
                pdata[path] = None
        fn = pdata[path].func(ip - lo) if pdata[path] else ip - lo
        return f"{path.rsplit('/', 1)[-1]}+{fn:#x}"
    if s and s != "[unknown]":
        return s.split("+")[0]
    return f"{dso.rsplit('/', 1)[-1] if dso else '?'}@{ip:#x}"


# perf script output is streamed: held whole, a 30 s trace is gigabytes of text (it once got the
# game OOM-killed).
cpu = collections.defaultdict(list)  # tid -> [(t, func)]
proc = subprocess.Popen(["perf", "script", "-i", cpu_data, "-F", "tid,time,ip,sym,dso"], stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, text=True)
pat = re.compile(r"^\s*(\d+)\s+([\d.]+):\s+([0-9a-f]+)\s+(.*?)\s+\((.*)\)\s*$")
for line in proc.stdout:
    m = pat.match(line)
    if m:
        cpu[int(m.group(1))].append((float(m.group(2)), sym(int(m.group(3), 16), m.group(4), m.group(5))))

# Sleeps: switch-out of a game thread (prev_pid) until its next switch-in (next_pid).
sleeps = collections.defaultdict(list)  # tid -> [(t_out, t_in, state, reason)]
if pw and os.path.exists(sw_data):
    proc = subprocess.Popen(["sudo", "-S", "-p", "", "perf", "script", "--max-stack", "10", "-i", sw_data,
                             "-F", "time,trace,ip,sym,dso"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True)
    proc.stdin.write(pw + "\n")
    proc.stdin.close()
    pending = {}
    ev = None
    for line in itertools.chain(proc.stdout, [""]):
        m = re.match(r"^\s*([\d.]+):\s+prev_comm=.*?prev_pid=(\d+).*?prev_state=(\S+) ==> next_comm=.*?next_pid=(\d+)", line)
        if m or not line.strip():
            if ev:
                t, prev, state, nxt_tid, stack = ev
                kern = [s for s in stack if s[2] == "kernel"]
                user = [s for s in stack if s[2] != "kernel"]
                ks = [s[1] for s in kern if not re.match(r"(__)?schedule|__traceiter|perf_|__perf|context_switch|__switch|preempt_schedule", s[1])]
                reason = " < ".join(ks[:3]) + (" | " + " < ".join(sym(u[0], u[1], u[2]) for u in user[:3]) if user else "")
                if prev in watch:
                    pending[prev] = (t, state, reason)
                if nxt_tid in pending:
                    t0, st, r = pending.pop(nxt_tid)
                    sleeps[nxt_tid].append((t0, t, st, r))
            ev = [float(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4)), []] if m else None
            continue
        m2 = re.match(r"^\s+([0-9a-f]+)\s+(.*?)\s+\((.*)\)\s*$", line)
        if m2 and ev:
            dso = m2.group(3)
            ev[4].append((int(m2.group(1), 16), m2.group(2), "kernel" if "kernel" in dso or dso.startswith("[") else dso))

slow = [f for f in frames if f[1] - f[0] > 2 * med]
print(f"{len(slow)} frames slower than {2 * med * 1e3:.1f} ms\n")
agg_cpu = collections.defaultdict(collections.Counter)
agg_sleep = collections.defaultdict(collections.Counter)
for t0, t1, wait in slow:
    print(f"frame at {t0:.3f}: {1e3 * (t1 - t0):.1f} ms, render thread waited {1e3 * wait:.1f} ms for the game thread")
    for tid, name in watch.items():
        c = collections.Counter(f for t, f in cpu[tid] if t0 <= t < t1)
        n = sum(c.values())
        sl = [(min(b, t1) - max(a, t0), st, r) for a, b, st, r in sleeps[tid] if b > t0 and a < t1]
        slept = sum(s[0] for s in sl)
        print(f"  {name:14s} on-CPU ~{n / 4:.1f} ms: " + ", ".join(f"{k} {v / 4:.1f}" for k, v in c.most_common(4)))
        for d, st, r in sorted(sl, reverse=True)[:3]:
            if d > 0.001:
                print(f"  {'':14s} slept {1e3 * d:5.1f} ms [{st}] {r[:160]}")
        for k, v in c.items():
            agg_cpu[name][k] += v
        for d, st, r in sl:
            agg_sleep[name][f"[{st}] {r[:140]}"] += d
print("\nover all slow frames:")
for name in watch.values():
    print(f"  {name}: on-CPU " + ", ".join(f"{k} {v / 4:.0f} ms" for k, v in agg_cpu[name].most_common(6)))
    for k, v in agg_sleep[name].most_common(6):
        print(f"      slept {1e3 * v:6.1f} ms  {k}")
