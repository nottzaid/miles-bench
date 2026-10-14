"""Which of the game's swapped-out pages zram could not compress ("huge": stored at full size), by
memory region.

    printf '%s\n' "$SUDO_PW" | sudo -S -p '' python3 bench/zramhuge.py [pid] [top N]

Runs as root: the kernel hides swap slot numbers in /proc/<pid>/pagemap from everyone else (every
swapped page reads as slot 0, which made an unprivileged run report 0 MiB incompressible). Reads
the game's pagemap (swapped pages carry their swap slot), the zram slot flags from
/sys/kernel/debug/zram/zram0/block_state (CONFIG_ZRAM_MEMORY_TRACKING) and /proc/swaps for the swap
device order. Prints per mapping: size, resident,
swapped, swapped incompressible.
"""
import collections
import os
import random
import struct
import zlib
import subprocess
import sys

if os.geteuid() != 0:
    sys.exit("zramhuge.py needs root (pagemap shows swap slots to root only)")
pid = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
top = int(sys.argv[2]) if len(sys.argv) > 2 else 25
if pid is None:
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open(f"/proc/{p}/comm").read().strip() == "MilesMorales.ex":
                    pid = int(p)
            except OSError:
                pass
swaps = [l.split()[0] for l in open("/proc/swaps").read().splitlines()[1:]]
zram_type = next(i for i, s in enumerate(swaps) if "zram0" in s)

flags = {}
proc = subprocess.Popen(["cat", "/sys/kernel/debug/zram/zram0/block_state"], stdout=subprocess.PIPE, text=True)
huge = set()
same = set()
for line in proc.stdout:
    f = line.split()
    if len(f) == 3:
        if "h" in f[2]:
            huge.add(int(f[0]))
        if "s" in f[2]:
            same.add(int(f[0]))
proc.wait()

rows = []
tot = collections.Counter()
samples = collections.defaultdict(list)  # mapping lo -> sampled incompressible page addresses
seen = collections.Counter()
random.seed(1)
pm = open(f"/proc/{pid}/pagemap", "rb", buffering=0)
for line in open(f"/proc/{pid}/maps"):
    f = line.split(None, 5)
    lo, hi = (int(x, 16) for x in f[0].split("-"))
    if "r" not in f[1] and "w" not in f[1]:
        continue
    name = f[5].strip() if len(f) > 5 else ""
    c = collections.Counter()
    page = lo >> 12
    end = hi >> 12
    while page < end:
        n = min(end - page, 65536)
        pm.seek(page * 8)
        data = pm.read(n * 8)
        for i, (e,) in enumerate(struct.iter_unpack("<Q", data)):
            if e >> 63:
                c["resident"] += 1
            elif (e >> 62) & 1:
                c["swapped"] += 1
                if (e & 0x1f) == zram_type:
                    slot = (e >> 5) & ((1 << 50) - 1)
                    if slot in huge:
                        c["huge"] += 1
                        seen[lo] += 1
                        if len(samples[lo]) < 8:
                            samples[lo].append((page + i) << 12)
                        elif random.random() < 8 / seen[lo]:
                            samples[lo][random.randrange(8)] = (page + i) << 12
                    elif slot in same:
                        c["same"] += 1
        page += n
    tot.update(c)
    if c["swapped"] or c["resident"] > 256:
        rows.append((c["huge"], c["swapped"], c["resident"], lo, hi, f[1], name))

mib = lambda p: p * 4096 / 1048576
print(f"pid {pid}: resident {mib(tot['resident']):.0f} MiB, swapped {mib(tot['swapped']):.0f} MiB, of it incompressible "
      f"{mib(tot['huge']):.0f} MiB, same-filled {mib(tot['same']):.0f} MiB (zram huge slots system-wide {mib(len(huge)):.0f} MiB)")
print(f"{'mapping':>34s} {'size':>7s} {'resid':>7s} {'swapped':>7s} {'huge':>7s}  name")
for h, s, r, lo, hi, perm, name in sorted(rows, reverse=True)[:top]:
    print(f"{lo:#16x}-{hi:#16x} {mib((hi - lo) >> 12):7.0f} {mib(r):7.0f} {mib(s):7.0f} {mib(h):7.0f}  {perm} {name[-50:]}")

# What the incompressible pages hold: 8 of them from each of the top regions (reading swaps them in).
mem = open(f"/proc/{pid}/mem", "rb", buffering=0)
for h, s_, r, lo, hi, perm, name in sorted(rows, reverse=True)[:6]:
    if not h:
        continue
    print(f"\nsampled incompressible pages of {lo:#x} ({mib((hi - lo) >> 12):.0f} MiB):")
    for a in sorted(samples[lo]):
        try:
            mem.seek(a)
            b = mem.read(4096)
        except OSError:
            continue
        print(f"  {a:#x} zlib {len(zlib.compress(b, 1)) / 4096:4.2f} zeros {b.count(0) / 4096:4.2f}  {b[:24].hex(' ')}")
