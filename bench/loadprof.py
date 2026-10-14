"""What a game launch and save load wait on, second by second.

    python3 bench/loadprof.py <out dir> [seconds, default 330] [disk, default sda]

Start it right before bench/cfgrun.sh. Every second it records the game disk's busy time and
reads (/proc/diskstats), swap-ins/outs and major faults (/proc/vmstat), the game's read_bytes and
the CPU time of each of its threads (grouped by thread name). Writes <out>/loadprof.tsv and
<out>/threads.tsv and prints a per-phase summary; phases come from <out>/../cfgrun log lines if
given with LOADPROF_LOG=<cfgrun output file>.
"""
import collections
import os
import re
import sys
import time

out = sys.argv[1]
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 330
disk = sys.argv[3] if len(sys.argv) > 3 else "sda"
os.makedirs(out, exist_ok=True)
hz = os.sysconf("SC_CLK_TCK")


def diskstats():
    for line in open("/proc/diskstats"):
        f = line.split()
        if f[2] == disk:
            # reads completed, sectors read, ms reading, writes completed, sectors written, io_ticks ms
            return int(f[3]), int(f[5]), int(f[6]), int(f[7]), int(f[9]), int(f[12])
    return 0, 0, 0, 0, 0, 0


def vmstat():
    v = {}
    for line in open("/proc/vmstat"):
        k, n = line.split()
        if k in ("pswpin", "pswpout", "pgmajfault", "pgpgin"):
            v[k] = int(n)
    return v


def game_pid():
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open(f"/proc/{p}/comm").read().strip() == "MilesMorales.ex":
                    return int(p)
            except OSError:
                pass
    return None


def threads(pid):
    cpu = collections.Counter()
    try:
        for t in os.listdir(f"/proc/{pid}/task"):
            try:
                st = open(f"/proc/{pid}/task/{t}/stat").read()
                name = st[st.index("(") + 1:st.rindex(")")]
                f = st[st.rindex(")") + 2:].split()
                name = re.sub(r"\d+$", "#", name)
                cpu[name] += (int(f[11]) + int(f[12])) / hz
            except (OSError, ValueError):
                pass
    except OSError:
        pass
    return cpu


def read_bytes(pid):
    try:
        for line in open(f"/proc/{pid}/io"):
            if line.startswith("read_bytes:"):
                return int(line.split()[1])
    except OSError:
        pass
    return 0


rows = []
trows = []
t0 = time.time()
prev = None
pid = None
nxt = t0
while time.time() - t0 < secs:
    now = time.time()
    if pid is None or not os.path.exists(f"/proc/{pid}"):
        pid = game_pid()
    d = diskstats()
    v = vmstat()
    cpu = threads(pid) if pid else collections.Counter()
    rb = read_bytes(pid) if pid else 0
    cur = (now, d, v, cpu, rb)
    if prev:
        pt, pd, pv, pcpu, prb = prev
        dt = now - pt
        rows.append((now, (d[5] - pd[5]) / (10 * dt), (d[1] - pd[1]) * 512 / 1048576 / dt, (d[0] - pd[0]) / dt,
                     (d[4] - pd[4]) * 512 / 1048576 / dt,
                     (v["pswpin"] - pv["pswpin"]) / dt, (v["pswpout"] - pv["pswpout"]) / dt,
                     (v["pgmajfault"] - pv["pgmajfault"]) / dt, max(0, rb - prb) / 1048576 / dt,
                     sum(max(0, cpu[k] - pcpu.get(k, 0)) for k in cpu) / dt))
        for k in cpu:
            dd = cpu[k] - pcpu.get(k, 0)
            if dd > 0.005:
                trows.append((now, k, dd / dt))
    prev = cur
    nxt += 1
    time.sleep(max(0, nxt - time.time()))

with open(os.path.join(out, "loadprof.tsv"), "w") as f:
    f.write("t\tdisk_busy_pct\tdisk_read_mbs\tdisk_reads_s\tdisk_write_mbs\tswapin_s\tswapout_s\tmajflt_s\tgame_read_mbs\tgame_cpu\n")
    for r in rows:
        f.write("\t".join(f"{x:.3f}" if isinstance(x, float) else str(x) for x in r) + "\n")
with open(os.path.join(out, "threads.tsv"), "w") as f:
    f.write("t\tthread\tcpu\n")
    for r in trows:
        f.write(f"{r[0]:.3f}\t{r[1]}\t{r[2]:.3f}\n")

# Phases from the cfgrun log ("HH:MM:SS launcher: Play", "menu: Continue", "scene settled").
marks = []
logf = os.environ.get("LOADPROF_LOG")
if logf and os.path.exists(logf):
    day = time.strftime("%Y-%m-%d", time.localtime(t0))
    for line in open(logf):
        m = re.match(r"^(\d\d:\d\d:\d\d) (.*)$", line)
        if m:
            ts = time.mktime(time.strptime(f"{day} {m.group(1)}", "%Y-%m-%d %H:%M:%S"))
            marks.append((ts, m.group(2)[:40]))
edges = [rows[0][0] - 1] + [m[0] for m in marks] + [rows[-1][0] + 1]
names = ["start"] + [m[1] for m in marks]
print(f"{'phase (from)':42s} {'s':>5} {'busy%':>6} {'rdMB/s':>7} {'rd/s':>6} {'wrMB/s':>7} {'swin/s':>7} {'swout/s':>7} {'cpu':>5}")
for i in range(len(edges) - 1):
    sel = [r for r in rows if edges[i] <= r[0] < edges[i + 1]]
    if not sel:
        continue
    n = len(sel)
    avg = [sum(r[k] for r in sel) / n for k in range(1, 10)]
    print(f"{names[i]:42s} {n:5d} {avg[0]:6.1f} {avg[1]:7.1f} {avg[2]:6.1f} {avg[3]:7.2f} {avg[4]:7.0f} {avg[5]:7.0f} {avg[8]:5.2f}")
    tc = collections.Counter()
    for r in trows:
        if edges[i] <= r[0] < edges[i + 1]:
            tc[r[1]] += r[2]
    print("    threads (avg cores): " + ", ".join(f"{k} {v / n:.2f}" for k, v in tc.most_common(8)))
