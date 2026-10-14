"""What a memory region of the game holds: strings and byte statistics of sampled pages.

    python3 bench/regionpeek.py <region start, hex> [pages to sample, default 64] [resident|any]

Reads pages of the mapping that contains the address through /proc/<pid>/mem (reading a swapped
page swaps it in, so the default samples resident pages only), and prints the most common printable
strings (6+ chars), the share of zero bytes, a compressibility estimate (zlib level 1) and the
first bytes of a few pages.
"""
import collections
import os
import random
import re
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(__file__))
import enginectl  # noqa: E402

addr = int(sys.argv[1], 16)
want = int(sys.argv[2]) if len(sys.argv) > 2 else 64
which = sys.argv[3] if len(sys.argv) > 3 else "resident"
pid = enginectl.game_pid()
for line in open(f"/proc/{pid}/maps"):
    lo, hi = (int(x, 16) for x in line.split()[0].split("-"))
    if lo <= addr < hi:
        break
else:
    sys.exit("no mapping there")
pm = open(f"/proc/{pid}/pagemap", "rb", buffering=0)
pm.seek((lo >> 12) * 8)
ents = struct.unpack(f"<{(hi - lo) >> 12}Q", pm.read(((hi - lo) >> 12) * 8))
cands = [lo + (i << 12) for i, e in enumerate(ents) if (e >> 63) or (which == "any" and (e >> 62) & 1)]
random.seed(1)
pages = sorted(random.sample(cands, min(want, len(cands))))
mem = open(f"/proc/{pid}/mem", "rb", buffering=0)
strings = collections.Counter()
zeros = ratio = 0
shown = 0
print(f"{lo:#x}-{hi:#x} ({(hi - lo) >> 20} MiB): {len(cands)} candidate pages, sampling {len(pages)}")
for a in pages:
    mem.seek(a)
    b = mem.read(4096)
    zeros += b.count(0)
    ratio += len(zlib.compress(b, 1)) / 4096
    for s in re.findall(rb"[\x20-\x7e]{6,}", b):
        strings[s[:60]] += 1
    if shown < 6:
        print(f"  {a:#x}: {b[:32].hex(' ')}")
        shown += 1
n = max(1, len(pages))
print(f"zero bytes {zeros / (4096 * n):.0%}, zlib-1 size {ratio / n:.2f}")
for s, c in strings.most_common(25):
    print(f"  {c:4d}  {s.decode()}")
