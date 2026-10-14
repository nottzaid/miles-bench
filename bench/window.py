"""Frame statistics for the next N seconds of a live frametrace.tsv, and how busy the rest of the
machine was meanwhile (the game shares one GPU, four cores and one HDD with the user's desktop).

    python3 bench/window.py <frametrace.tsv> <seconds>

The last line says "clean" or "DISTURBED (...)": other processes' GPU share, CPU used outside the
game, HDD reads by others, or the user having the game focused (their keys reach it). CPU is split
by process tree: the game (everything under the run's launcher, captures/<run>/run.pid, plus kernel
threads such as kswapd and zram that the game's memory use drives), the bench (this script's
parent, cfgrun.sh, and its loggers) and other (the user's own programs).
"""
import glob
import json
import os
import statistics
import subprocess
import sys
import time

path, secs = sys.argv[1], float(sys.argv[2])
GAME = ("MilesMorales.ex", "wineserver")
# Thresholds for a clean window. The idle desktop with a terminal streaming output shows 9-15% SM
# in pmon (Hyprland compositing) and ~4% other CPU (2026-10-12 calibration); a video, a second
# game or a build goes well past these.
MAX_OTHER_SM, MAX_OTHER_CPU, MAX_OTHER_DISK_MBS = 25, 15, 2


def frames():
    return [float(l.split("\t")[1]) for l in open(path) if l.startswith("F\t")]


def is_game(name):
    return name.startswith(GAME)


def game_pids():
    pids = []
    for p in glob.glob("/proc/[0-9]*/comm"):
        try:
            if is_game(open(p).read().strip()):
                pids.append(int(p.split("/")[2]))
        except OSError:
            pass
    return pids


def proc_ticks(pids):
    total = 0
    for pid in pids:
        try:
            f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
            total += int(f[11]) + int(f[12])
        except OSError:
            pass
    return total


def all_procs():
    """pid -> (comm, ppid, utime+stime, is kernel thread)"""
    out = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            raw = open(f"{d}/stat").read()
            comm = raw[raw.index("(") + 1:raw.rindex(")")]
            f = raw.rsplit(")", 1)[1].split()
            flags = int(f[6])
            out[int(d[6:])] = (comm, int(f[1]), int(f[11]) + int(f[12]), bool(flags & 0x00200000))
        except (OSError, ValueError):
            pass
    return out


def descendants(procs, root):
    kids = {}
    for pid, (_, ppid, _, _) in procs.items():
        kids.setdefault(ppid, []).append(pid)
    seen, todo = set(), [root]
    while todo:
        pid = todo.pop()
        if pid in seen:
            continue
        seen.add(pid)
        todo += kids.get(pid, [])
    return seen


def proc_read_bytes(pids):
    total = 0
    for pid in pids:
        try:
            total += int(next(l for l in open(f"/proc/{pid}/io") if l.startswith("read_bytes")).split()[1])
        except (OSError, StopIteration):
            pass
    return total


def cpu_ticks():
    f = [int(x) for x in open("/proc/stat").readline().split()[1:]]
    return sum(f) - f[3] - f[4], sum(f)  # busy, total (idle and iowait excluded from busy)


def sda_read_bytes():
    for line in open("/proc/diskstats"):
        f = line.split()
        if f[2] == "sda":
            return int(f[5]) * 512
    return 0


def game_focused():
    try:
        w = json.loads(subprocess.run(["hyprctl", "-j", "activewindow"], capture_output=True, text=True).stdout or "{}")
        return (w or {}).get("class", "").startswith("steam_app")
    except (OSError, ValueError):
        return False


time.sleep(1.2)
start = frames()[-1]
pids = game_pids()
busy0, total0 = cpu_ticks()
procs0 = all_procs()
disk0, gread0 = sda_read_bytes(), proc_read_bytes(pids)
# 1 sample/s: power (W), SM busy (%), PCIe rx/tx (MB/s, rx = into the GPU); pmon: SM % per process
n = str(int(secs))
# -s p: power, temperature; u: SM / memory-controller busy %; c: memory and graphics clock (MHz);
# t: PCIe rx/tx
dmon = subprocess.Popen(["nvidia-smi", "dmon", "-s", "puct", "-c", n], stdout=subprocess.PIPE, text=True)
pmon = subprocess.Popen(["nvidia-smi", "pmon", "-s", "u", "-c", n], stdout=subprocess.PIPE, text=True)
focused = 0
t_end = time.time() + secs
while time.time() < t_end:
    focused += game_focused()
    time.sleep(1)
dmon_out, pmon_out = dmon.communicate()[0], pmon.communicate()[0]
busy1, total1 = cpu_ticks()
procs1 = all_procs()
disk1, gread1 = sda_read_bytes(), proc_read_bytes(pids)
time.sleep(1.2)

cols, rows = [], []
for line in dmon_out.splitlines():
    if line.startswith("# gpu"):
        cols = line[1:].split()
    elif line.strip() and not line.startswith("#") and cols:
        rows.append(dict(zip(cols, line.split())))
mean = lambda k: statistics.mean(float(r[k]) for r in rows if r.get(k, "-") not in ("-", "")) if rows else 0

# pmon prints one block per second; sum SM % of non-game processes per block.
other_sm, block, last_key = [], {}, None
for line in pmon_out.splitlines():
    if line.startswith("#") or not line.strip():
        continue
    f = line.split()
    sm = 0 if f[3] == "-" else int(f[3])
    name = " ".join(f[9:]) if len(f) > 9 else f[-1]
    if (f[1], name) in block:  # a pid seen again: next second
        other_sm.append(sum(v for k, v in block.items() if not is_game(k[1])))
        block = {}
    block[(f[1], name)] = sm
if block:
    other_sm.append(sum(v for k, v in block.items() if not is_game(k[1])))

# Shares of the whole machine (all cores), from clock ticks, per process tree.
try:
    launcher = int(open(os.path.join(os.path.dirname(os.path.abspath(path)), "run.pid")).read())
except (OSError, ValueError):
    launcher = None
game_tree = descendants(procs1, launcher) if launcher else set(pids)
game_tree |= set(pids)
bench_tree = descendants(procs1, os.getppid()) | {os.getpid()}
spent = {"game": 0, "bench": 0, "other": 0}
other_by = {}
for pid, (comm, _, ticks, kthread) in procs1.items():
    d = ticks - procs0.get(pid, (None, None, 0, None))[2] if pid in procs0 else ticks
    if d <= 0:
        continue
    group = "game" if pid in game_tree or kthread or is_game(comm) else "bench" if pid in bench_tree else "other"
    spent[group] += d
    if group == "other":
        other_by[comm] = other_by.get(comm, 0) + d
cpu_total = max(1, total1 - total0)
game_cpu, bench_cpu, other_cpu = (100 * spent[k] / cpu_total for k in ("game", "bench", "other"))
top_other = ", ".join(f"{c} {100 * t / cpu_total:.0f}%" for c, t in sorted(other_by.items(), key=lambda x: -x[1])[:3])
other_disk = max(0, (disk1 - disk0) - (gread1 - gread0)) / 1e6 / secs

util = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                      capture_output=True, text=True).stdout.strip()
limits = subprocess.run(["nvidia-smi", "--query-gpu=pstate,clocks.max.gr,clocks.max.mem,power.limit,"
                         "clocks_throttle_reasons.active", "--format=csv,noheader"],
                        capture_output=True, text=True).stdout.strip()
t = [x for x in frames() if start < x <= start + secs * 1000]
iv = sorted(b - a for a, b in zip(t, t[1:]))
q = lambda p: iv[min(len(iv) - 1, int(p * len(iv)))]
print(f"fps {len(iv) / ((t[-1] - t[0]) / 1000):.2f}  frametime p50 {q(.5):.1f} p95 {q(.95):.1f} p99 {q(.99):.1f} max {iv[-1]:.1f} ms"
      f"  frames {len(iv)}  power {mean('pwr'):.0f} W  pcie rx {mean('rxpci'):.0f} tx {mean('txpci'):.0f} MB/s  util-now {util}%")
print(f"gpu: sm busy {mean('sm'):.0f}%  vram controller busy {mean('mem'):.0f}%  clocks gr {mean('pclk'):.0f} mem {mean('mclk'):.0f} MHz"
      f"  temp {mean('gtemp'):.0f} C  (pstate, max gr, max mem, power limit, throttle: {limits})")
sm_mean = statistics.mean(other_sm) if other_sm else 0
print(f"machine: cpu game {game_cpu:.0f}% bench {bench_cpu:.0f}% other {other_cpu:.0f}% ({top_other})"
      f"  other gpu sm {sm_mean:.1f}% (max {max(other_sm, default=0)})"
      f"  other hdd reads {other_disk:.1f} MB/s  game focused {focused} s")
why = [w for w, bad in [
    (f"other GPU {sm_mean:.0f}%", sm_mean > MAX_OTHER_SM),
    (f"other CPU {other_cpu:.0f}%", other_cpu > MAX_OTHER_CPU),
    (f"other HDD {other_disk:.0f} MB/s", other_disk > MAX_OTHER_DISK_MBS),
    (f"game focused {focused} s", focused > 0),
] if bad]
print("window: " + (f"DISTURBED ({', '.join(why)})" if why else "clean"))
