"""Where the game's major faults (swap-ins, file page-ins) happen during a launch and load.

    SUDO_PW=... python3 bench/faultprof.py <out dir> [seconds, default 300]

Waits for the game process, then records every major fault of it (sudo perf record -e
major-faults -d, kernel+user call chains) for <seconds>, snapshots /proc/<pid>/maps at the end and
prints faults by thread, by kind (inside a read() into the faulting page vs. user code vs. other
kernel paths), by mapping and by user function (PE .pdata). perf script output is streamed.
HITCH_REUSE=1 re-analyzes saved data.
"""
import bisect
import collections
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import missprof  # noqa: E402

out = sys.argv[1]
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 300
os.makedirs(out, exist_ok=True)
data = os.path.join(out, "faults.data")
pw = os.environ.get("SUDO_PW", "")
reuse = bool(os.environ.get("HITCH_REUSE"))


def game_pid():
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open(f"/proc/{p}/comm").read().strip() == "MilesMorales.ex":
                    return int(p)
            except OSError:
                pass
    return None


if not reuse:
    pid = None
    while pid is None:
        pid = game_pid()
        if pid is None:
            time.sleep(0.2)
    open(os.path.join(out, "pid"), "w").write(str(pid))
    rec = subprocess.Popen(["sudo", "-S", "-p", "", "perf", "record", "-q", "-e", "major-faults", "-c", "1", "-d",
                            "--call-graph", "fp", "-p", str(pid), "-o", data, "--", "sleep", str(secs)],
                           stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    rec.stdin.write((pw + "\n").encode())
    rec.stdin.close()
    t_end = time.time() + secs
    maps = None
    while time.time() < t_end and os.path.exists(f"/proc/{pid}"):
        try:
            maps = open(f"/proc/{pid}/maps").read()
            comm = {}
            for t in os.listdir(f"/proc/{pid}/task"):
                try:
                    comm[t] = open(f"/proc/{pid}/task/{t}/comm").read().strip()
                except OSError:
                    pass
            with open(os.path.join(out, "threads.tsv"), "a") as f:
                f.writelines(f"{t}\t{c}\n" for t, c in comm.items())
        except OSError:
            pass
        time.sleep(5)
    if maps:
        open(os.path.join(out, "maps.txt"), "w").write(maps)
        missprof.modules(out) if os.path.exists(f"/proc/{pid}") else None
    rec.wait()
    subprocess.run(["sudo", "-S", "-p", "", "chown", f"{os.getuid()}", data], input=(pw + "\n").encode(),
                   stderr=subprocess.DEVNULL)

names = {}
if os.path.exists(os.path.join(out, "threads.tsv")):
    for line in open(os.path.join(out, "threads.tsv")):
        t, c = line.rstrip("\n").split("\t", 1)
        names[int(t)] = re.sub(r"\d+$", "#", c)

maps = []
for line in open(os.path.join(out, "maps.txt")):
    f = line.split(None, 5)
    lo, hi = (int(x, 16) for x in f[0].split("-"))
    maps.append((lo, hi, f[5].strip() if len(f) > 5 else "[anon]"))
maps.sort()
map_lo = [m[0] for m in maps]
mods = []
if os.path.exists(os.path.join(out, "modules.tsv")):
    for line in open(os.path.join(out, "modules.tsv")):
        f = line.rstrip("\n").split("\t")
        if len(f) == 3:
            mods.append((int(f[0], 16), int(f[1], 16), f[2]))
mods.sort()
mod_lo = [m[0] for m in mods]
pdata = {}


def region(addr):
    i = bisect.bisect_right(map_lo, addr) - 1
    if i >= 0 and maps[i][0] <= addr < maps[i][1]:
        lo, hi, path = maps[i]
        return path.rsplit("/", 1)[-1] if path != "[anon]" else f"anon {lo:#x} ({(hi - lo) >> 20} MiB)"
    return "?"


def ufunc(ip):
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
    return None


by_thread = collections.Counter()
by_kind = collections.Counter()
by_region = collections.Counter()
by_func = collections.Counter()
by_kfunc = collections.Counter()
read_by_func = collections.Counter()
total = 0
proc = subprocess.Popen(["perf", "script", "-i", data, "-F", "tid,addr,ip,sym,dso", "--max-stack", "24"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
head = re.compile(r"^\s*(\d+)\s+([0-9a-f]+)\b")
frame = re.compile(r"^\s+([0-9a-f]+)\s+(.*?)\s+\((.*)\)\s*$")
ev = None


def flush(ev):
    global total
    tid, addr, stack = ev
    total += 1
    by_thread[names.get(tid, str(tid))] += 1
    by_region[region(addr)] += 1
    ksyms = [s for _, s, d in stack if "kernel" in d or d.startswith("[")]
    user = [ip for ip, s, d in stack if not ("kernel" in d or d.startswith("["))]
    uf = next((f for f in (ufunc(ip) for ip in user) if f), None)
    if any(re.search(r"ksys_read|vfs_read|filemap_read|copy_page_to_iter|_copy_to_iter|_copy_to_user|pread", s) for s in ksyms):
        kind = "kernel: read() copying into the page"
        read_by_func[uf or "?"] += 1
    elif ksyms and any(re.search(r"entry_SYSCALL|do_syscall", s) for s in ksyms):
        kind = "kernel: other syscall (" + next((s for s in ksyms if s.startswith(("__x64_sys", "ksys_", "do_sys"))), "?") + ")"
    elif user:
        kind = "user code"
    else:
        kind = "kernel: other"
    by_kind[kind] += 1
    by_func[uf or "?"] += 1


for line in proc.stdout:
    m = head.match(line)
    if m:
        if ev:
            flush(ev)
        ev = (int(m.group(1)), int(m.group(2), 16), [])
        continue
    m = frame.match(line)
    if m and ev:
        ev[2].append((int(m.group(1), 16), m.group(2), m.group(3)))
if ev:
    flush(ev)

print(f"{total} major faults")
for title, c, n in (("by kind", by_kind, 8), ("by thread", by_thread, 10), ("by mapping", by_region, 12),
                    ("by user function (first PE frame)", by_func, 15),
                    ("read() faults by calling user function", read_by_func, 10)):
    print(f"\n{title}:")
    for k, v in c.most_common(n):
        print(f"  {v:8d} {100 * v / max(1, total):5.1f}%  {k}")
