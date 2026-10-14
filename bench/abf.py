"""Same-session A/B of live engine features: alternate engine_ctl.features between two masks in the
running game and measure each window (fps and frame-time percentiles from frametrace.tsv).

    python3 bench/abf.py <capture-dir> --a 0 --b 5 [--secs 20] [--rounds 4] [--settle 3]

Feature bits (vkd3d_private.h): 1 = copies keep system-memory images instead of discarding them,
2 = same for every image, 4 = qasync (query answers read a frame later; needs the qasync patch),
8 = index cache bypassed (runs with VKD3D_BENCH_INDEX_CACHE=1), 16 = vertex decoder takes its original
loads (runs with VKD3D_ENGINE_PATCH=gdec), 32 = particle loop UAV barriers dropped (lossy experiment).
Windows run A B B A A B ... (ABBA order cancels slow drift). Appends to <capture-dir>/abf.tsv.
"""
import argparse
import os
import statistics
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import enginectl  # noqa: E402
from ab import frames_between, last_frame_t  # noqa: E402

FEATURES_OFFSET = struct.calcsize(enginectl.FMT)


def set_features(pid, ctl, mask):
    with open(f"/proc/{pid}/mem", "r+b") as mem:
        mem.seek(ctl + FEATURES_OFFSET)
        mem.write(mask.to_bytes(4, "little"))


def paging(pid):
    """System swap-ins and the game's major faults so far."""
    swin = next(int(line.split()[1]) for line in open("/proc/vmstat") if line.startswith("pswpin "))
    st = open(f"/proc/{pid}/stat").read()
    return swin, int(st[st.rindex(")") + 2:].split()[9])


def window(pid, ctl, ft, mask, secs, settle):
    set_features(pid, ctl, mask)
    time.sleep(settle + 1.1)
    ta = last_frame_t(ft)
    pa = paging(pid)
    time.sleep(secs)
    pb = paging(pid)
    time.sleep(1.1)
    tb = max(last_frame_t(ft) - 1100, ta)
    t = frames_between(ft, ta, tb)
    iv = sorted(b - a for a, b in zip(t, t[1:]))
    if len(iv) < 10:
        return None
    q = lambda p: iv[min(len(iv) - 1, int(p * len(iv)))]
    return dict(mask=mask, fps=len(iv) / ((t[-1] - t[0]) / 1000), p50=q(.5), p95=q(.95), p99=q(.99), n=len(iv),
                slow=sum(x > 40 for x in iv), worst=iv[-1], swin=pb[0] - pa[0], majflt=pb[1] - pa[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cap")
    ap.add_argument("--a", type=int, required=True)
    ap.add_argument("--b", type=int, required=True)
    ap.add_argument("--secs", type=float, default=20)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--settle", type=float, default=3)
    args = ap.parse_args()
    pid = enginectl.game_pid()
    ctl = enginectl.find_ctl(pid)
    ft = os.path.join(args.cap, "frametrace.tsv")
    order = []
    for r in range(args.rounds):
        order += [args.a, args.b] if r % 2 == 0 else [args.b, args.a]
    res = {args.a: [], args.b: []}
    with open(os.path.join(args.cap, "abf.tsv"), "a") as out:
        for mask in order:
            w = window(pid, ctl, ft, mask, args.secs, args.settle)
            if not w:
                print(f"features {mask}: too few frames")
                continue
            res[mask].append(w)
            line = (f"features {mask}: fps {w['fps']:.2f} p50 {w['p50']:.1f} p95 {w['p95']:.1f} p99 {w['p99']:.1f} ms "
                    f"({w['n']} frames, {w['slow']} over 40 ms, worst {w['worst']:.0f} ms; {w['swin']} swap-ins, "
                    f"{w['majflt']} game major faults)")
            print(line, flush=True)
            out.write(f"{time.time():.0f}\t{mask}\t{w['fps']:.3f}\t{w['p50']:.2f}\t{w['p95']:.2f}\t{w['p99']:.2f}\t{w['n']}\n")
    set_features(pid, ctl, args.a)
    for mask in (args.a, args.b):
        f = [w["fps"] for w in res[mask]]
        if f:
            print(f"features {mask}: mean fps {statistics.mean(f):.2f} (min {min(f):.2f} max {max(f):.2f}), "
                  f"p95 {statistics.mean(w['p95'] for w in res[mask]):.1f} ms, p99 {statistics.mean(w['p99'] for w in res[mask]):.1f} ms, "
                  f"{sum(w['slow'] for w in res[mask])} frames over 40 ms, {sum(w['swin'] for w in res[mask])} swap-ins, "
                  f"{sum(w['majflt'] for w in res[mask])} game major faults")
    fa = [w["fps"] for w in res[args.a]]
    fb = [w["fps"] for w in res[args.b]]
    if fa and fb:
        print(f"B vs A: {100 * (statistics.mean(fb) / statistics.mean(fa) - 1):+.1f}% fps")


if __name__ == "__main__":
    main()
