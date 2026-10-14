"""Read or flip the engine patch control block (enginepatch.c) inside the running game.

    python3 bench/enginectl.py              # print counters
    python3 bench/enginectl.py spin=0       # original busy-wait at the patched sites
    python3 bench/enginectl.py spin=1       # blocking fence wait
    python3 bench/enginectl.py --watch 2    # counters every 2 s (deltas)

The block lives in d3d12core.dll's .data and starts with "MILESBENCH_CTL1\\0"; it's found by
scanning the DLL's writable pages through /proc/<pid>/mem.
"""
import argparse
import struct
import subprocess
import sys
import time

MAGIC = b"MILESBENCH_CTL1\0"
FMT = "<16sIIQQQQ"  # magic, spin_block, sites_patched, waits, blocked_ns, timeouts, spin_ns


def game_pid():
    out = subprocess.run(["pgrep", "-x", "MilesMorales.ex"], capture_output=True, text=True).stdout.split()
    if not out:
        sys.exit("game not running")
    return int(out[0])


def find_ctl(pid):
    # Wine copies sections that aren't page-aligned in the file into anonymous memory, so only
    # the header page carries the DLL's path. Take the image range from the header, then scan
    # every writable mapping inside it.
    with open(f"/proc/{pid}/maps") as f:
        maps = [line.split(None, 5) for line in f]  # the path field has spaces
    with open(f"/proc/{pid}/mem", "rb") as mem:
        base = next(int(p[0].split("-")[0], 16) for p in maps
                    if len(p) >= 6 and p[5].rstrip().endswith("d3d12core.dll") and int(p[2], 16) == 0)
        mem.seek(base + 0x3c)
        nt = base + struct.unpack("<I", mem.read(4))[0]
        mem.seek(nt + 0x18 + 0x38)  # OptionalHeader.SizeOfImage
        end = base + struct.unpack("<I", mem.read(4))[0]
        for p in maps:
            lo, hi = (int(x, 16) for x in p[0].split("-"))
            if hi <= base or lo >= end or "w" not in p[1]:
                continue
            mem.seek(lo)
            i = mem.read(hi - lo).find(MAGIC)
            if i >= 0:
                return lo + i
    sys.exit("control block not found (game not started with the bench d3d12core.dll?)")


def read(pid, addr):
    with open(f"/proc/{pid}/mem", "rb") as mem:
        mem.seek(addr)
        return struct.unpack(FMT, mem.read(struct.calcsize(FMT)))


def show(v, prev=None, dt=None):
    _, spin, sites, waits, blocked, timeouts, spin_ns = v
    line = f"spin_block={spin} sites={sites} waits={waits} blocked={blocked / 1e9:.2f}s timeouts={timeouts} spin={spin_ns / 1e9:.2f}s"
    if prev and dt:
        line += (f"  | per s: waits {(waits - prev[3]) / dt:.0f}, blocked {(blocked - prev[4]) / 1e7 / dt:.0f}%,"
                 f" spinning {(spin_ns - prev[6]) / 1e7 / dt:.0f}%")
    print(line, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("set", nargs="?")
    ap.add_argument("--watch", type=float)
    a = ap.parse_args()
    pid = game_pid()
    addr = find_ctl(pid)
    if a.set:
        key, val = a.set.split("=")
        assert key == "spin"
        with open(f"/proc/{pid}/mem", "r+b") as mem:
            mem.seek(addr + 16)
            mem.write(struct.pack("<I", int(val)))
    prev = read(pid, addr)
    show(prev)
    while a.watch:
        time.sleep(a.watch)
        cur = read(pid, addr)
        show(cur, prev, a.watch)
        prev = cur
