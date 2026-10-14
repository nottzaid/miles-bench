"""The light grid page allocator's state in the running game, read from /proc/<pid>/mem.

    python3 bench/lgpages.py [seconds, default 0 = once] [interval, default 1]

LightGridManager's page bitmap (struct at exe+0x6a453a8: level0/1/2 pointers, count, used,
highest; level 2 holds one bit per 64 KiB page, MSB first, set = allocated). Prints pages in use,
the highest allocated page and the highest seen so far.
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import enginectl  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 0
step = float(sys.argv[2]) if len(sys.argv) > 2 else 1
pid = enginectl.game_pid()
mem = open(f"/proc/{pid}/mem", "rb", buffering=0)


def read(addr, n):
    mem.seek(addr)
    return mem.read(n)


# The exe's header page is the file mapping at offset 0 whose path ends in MilesMorales.exe.
with open(f"/proc/{pid}/maps") as f:
    base = next(int(p[0].split("-")[0], 16) for p in (line.split(None, 5) for line in f)
                if len(p) >= 6 and p[5].rstrip().endswith("MilesMorales.exe") and int(p[2], 16) == 0)
l0, l1, l2, count, used, highest = struct.unpack("<QQQiii", read(base + 0x6a453a8, 36))
words = (count + 63) // 64
top = -1
t0 = time.time()
while True:
    bits = struct.unpack(f">{words}Q", b"".join(read(l2 + 8 * w, 8)[::-1] for w in range(words)))
    used_now = sum(bin(b).count("1") for b in bits)
    hi = max((w * 64 + 63 - (b & -b).bit_length() + 1 for w, b in enumerate(bits) if b), default=-1)
    top = max(top, hi)
    _, _, _, count, used, highest = struct.unpack("<QQQiii", read(base + 0x6a453a8, 36))
    print(f"{time.strftime('%T')} pages {count + 1}: {used_now} allocated (engine count {used}), highest {hi} "
          f"(engine {highest}), highest seen {top}", flush=True)
    if time.time() - t0 >= secs:
        break
    time.sleep(step)
