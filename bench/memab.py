"""Is the game limited by DRAM bandwidth? Same-session windows with no extra load, a CPU-only load
(memhog spin) and a DRAM load taking the same CPU time (memhog mem), in rotating order.

    python3 bench/memab.py <capture-dir> [--duty 0.3] [--secs 20] [--rounds 3]

Needs build/memhog (gcc -O2 -o build/memhog bench/memhog.c) and the game in the bench scene
(cfgrun.sh with KEEP_GAME=1). Window start/end times go to <capture-dir>/memab.tsv so DRAM traffic
per window can be read from a bench/imc.py recording taken alongside.
"""
import argparse
import os
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from ab import frames_between, last_frame_t  # noqa: E402

HOG = os.path.join(os.path.dirname(__file__), "..", "build", "memhog")


def window(ft, mode, duty, secs, settle):
    hog = None
    if mode != "none":
        hog = subprocess.Popen([HOG, mode, str(duty), str(settle + secs + 4)], stdout=subprocess.PIPE, text=True)
    time.sleep(settle + 1.1)
    ta = last_frame_t(ft)
    t0 = time.time()
    time.sleep(secs)
    t1 = time.time()
    time.sleep(1.1)
    tb = max(last_frame_t(ft) - 1100, ta)
    rate = ""
    if hog:
        hog.terminate()
        rate = (hog.communicate()[0] or "").strip()
    t = frames_between(ft, ta, tb)
    iv = sorted(b - a for a, b in zip(t, t[1:]))
    if len(iv) < 10:
        return None
    q = lambda p: iv[min(len(iv) - 1, int(p * len(iv)))]
    return dict(mode=mode, fps=len(iv) / ((t[-1] - t[0]) / 1000), p50=q(.5), p95=q(.95), p99=q(.99),
                n=len(iv), t0=t0, t1=t1, rate=rate)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cap")
    ap.add_argument("--duty", type=float, default=0.3)
    ap.add_argument("--secs", type=float, default=20)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--settle", type=float, default=3)
    args = ap.parse_args()
    ft = os.path.join(args.cap, "frametrace.tsv")
    modes = ["none", "spin", "mem"]
    order = []
    for r in range(args.rounds):
        order += modes if r % 2 == 0 else modes[::-1]
    res = {m: [] for m in modes}
    with open(os.path.join(args.cap, "memab.tsv"), "a") as out:
        for mode in order:
            w = window(ft, mode, args.duty, args.secs, args.settle)
            if not w:
                print(f"{mode}: too few frames")
                continue
            res[mode].append(w)
            print(f"{mode:4s}: fps {w['fps']:.2f} p50 {w['p50']:.1f} p95 {w['p95']:.1f} p99 {w['p99']:.1f} ms "
                  f"({w['n']} frames) {w['rate']}", flush=True)
            out.write(f"{w['t0']:.1f}\t{w['t1']:.1f}\t{mode}\t{args.duty}\t{w['fps']:.3f}\t{w['p50']:.2f}\t"
                      f"{w['p95']:.2f}\t{w['p99']:.2f}\t{w['n']}\t{w['rate']}\n")
    for m in modes:
        f = [w["fps"] for w in res[m]]
        if f:
            print(f"{m:4s}: mean fps {statistics.mean(f):.2f} (min {min(f):.2f} max {max(f):.2f}), "
                  f"p99 {statistics.mean(w['p99'] for w in res[m]):.1f} ms")


if __name__ == "__main__":
    main()
