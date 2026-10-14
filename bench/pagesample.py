"""What a region of the game's memory holds: samples pages and reports how well they compress and
what they start with.

    python3 bench/pagesample.py <pid> <lo hex> <hi hex> [pages, default 64] [only: swapped|resident|any]

Reads through /proc/<pid>/mem (a swapped page is swapped back in by the read, so keep samples
small). Per page: zlib-1 ratio, byte entropy, zero fraction, first 32 bytes.
"""
import collections
import math
import random
import struct
import sys
import zlib

pid, lo, hi = int(sys.argv[1]), int(sys.argv[2], 16), int(sys.argv[3], 16)
n = int(sys.argv[4]) if len(sys.argv) > 4 else 64
only = sys.argv[5] if len(sys.argv) > 5 else "swapped"
pm = open(f"/proc/{pid}/pagemap", "rb", buffering=0)
mem = open(f"/proc/{pid}/mem", "rb", buffering=0)
pages = []
first, last = lo >> 12, hi >> 12
step = 4096
for page in range(first, last, step):
    cnt = min(step, last - page)
    pm.seek(page * 8)
    for i, (e,) in enumerate(struct.iter_unpack("<Q", pm.read(cnt * 8))):
        if (only == "swapped" and (e >> 62) == 1) or (only == "resident" and e >> 63) or (only == "any" and e >> 62):
            pages.append(page + i)
random.seed(1)
pick = sorted(random.sample(pages, min(n, len(pages))))
ratios = []
kinds = collections.Counter()
for p in pick:
    mem.seek(p << 12)
    b = mem.read(4096)
    r = len(zlib.compress(b, 1)) / 4096
    cnt = collections.Counter(b)
    ent = -sum(c / 4096 * math.log2(c / 4096) for c in cnt.values())
    z = b.count(0) / 4096
    ratios.append(r)
    kind = "incompressible" if r > 0.9 else "compressible" if r < 0.6 else "mixed"
    kinds[kind] += 1
    print(f"{p << 12:#x} zlib {r:4.2f} entropy {ent:4.2f} zeros {z:4.2f}  {b[:32].hex(' ')}")
print(f"{len(pages)} {only} pages in range, {len(pick)} sampled; zlib ratio median {sorted(ratios)[len(ratios) // 2]:.2f}; {dict(kinds)}")
