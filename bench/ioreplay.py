"""Replay the game's streaming reads (from an strace of the NxStorage Command thread) against the
disk with a cold page cache, under different I/O strategies, and time them.

    python3 bench/ioreplay.py build/nxstorage.strace build/fdmap.tsv [--modes serial,qd8,...]
        [--remap old_path=new_path ...] [--repeat 2]

Modes:
  serial     one pread at a time in the game's order (what Wine does today: the game's ReadFile
             calls are synchronous on one thread)
  qdN        the same reads with N in flight (N threads taking requests in order), so the
             block layer and the disk's NCQ can reorder seeks
  coalesceG  serial, but a read that starts within G KiB after the previous one on the same file
             is merged into one larger read (gap bytes are read and thrown away)

The page cache is dropped with posix_fadvise(DONTNEED) on every file before each run (works
without root for pages nobody has mapped); --flush reads 512 MiB of another file first so the
drive's onboard cache doesn't serve the replay either.
"""
import argparse
import os
import queue
import re
import threading
import time


def load(strace_path, fdmap_path):
    fdpath = {}
    for line in open(fdmap_path):
        fd, path = line.rstrip("\n").split("\t", 1)
        fdpath[int(fd)] = path
    reads = []
    for line in open(strace_path):
        m = re.search(r"pread64\((\d+), .*?, (\d+), (\d+)\) = (\d+)", line)
        if m and int(m.group(1)) in fdpath:
            reads.append((fdpath[int(m.group(1))], int(m.group(3)), int(m.group(4))))
    return reads


def drop_cache(paths, flush_path=None, flush_offset=0):
    """Evict the files from the page cache, then push the disk's own cache out by reading
    512 MiB of unrelated data (evicted again afterwards)."""
    if flush_path:
        fd = os.open(flush_path, os.O_RDONLY)
        for i in range(512):
            os.pread(fd, 1 << 20, flush_offset + i * (1 << 20))
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        os.close(fd)
    for p in paths:
        fd = os.open(p, os.O_RDONLY)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        os.close(fd)


def coalesce(reads, gap):
    out = []
    for path, off, size in reads:
        if out and out[-1][0] == path and 0 <= off - (out[-1][1] + out[-1][2]) <= gap:
            p, o, s = out[-1]
            out[-1] = (p, o, max(s, off + size - o))
        else:
            out.append((path, off, size))
    return out


def run(reads, fds, depth):
    if depth == 1:
        for path, off, size in reads:
            os.pread(fds[path], size, off)
        return
    q = queue.Queue()
    for r in reads:
        q.put(r)

    def worker():
        while True:
            try:
                path, off, size = q.get_nowait()
            except queue.Empty:
                return
            os.pread(fds[path], size, off)

    threads = [threading.Thread(target=worker) for _ in range(depth)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("strace")
    ap.add_argument("fdmap")
    ap.add_argument("--modes", default="serial,qd4,qd8,qd32,coalesce256,coalesce1024")
    ap.add_argument("--remap", action="append", default=[])
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--flush", help="file used to push the disk cache out between runs")
    a = ap.parse_args()
    reads = load(a.strace, a.fdmap)
    for spec in a.remap:
        old, new = spec.split("=", 1)
        reads = [(new if p == old else p, o, s) for p, o, s in reads]
    paths = sorted({r[0] for r in reads})
    fds = {p: os.open(p, os.O_RDONLY) for p in paths}
    mib = sum(r[2] for r in reads) / 2**20
    print(f"{len(reads)} reads, {mib:.0f} MiB, {len(paths)} files")
    for rep in range(a.repeat):
        for mode in a.modes.split(","):
            todo, depth = reads, 1
            if mode.startswith("qd"):
                depth = int(mode[2:])
            elif mode.startswith("coalesce"):
                todo = coalesce(reads, int(mode[8:]) * 1024)
            drop_cache(paths, a.flush, (rep * 7 + len(mode)) % 4 * (600 << 20))
            time.sleep(1)
            t = time.monotonic()
            run(todo, fds, depth)
            dt = time.monotonic() - t
            read_mib = sum(r[2] for r in todo) / 2**20
            print(f"  {mode:13s} {dt:6.2f} s  {mib / dt:6.1f} MiB/s useful  ({len(todo)} requests, {read_mib:.0f} MiB read)",
                  flush=True)
