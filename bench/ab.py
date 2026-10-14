"""Same-scene A/B of the spin patch: alternate spin_block on/off in the running game and measure
each window.

    python3 bench/ab.py <capture-dir> [--secs 10] [--rounds 2] [--label menu]

Per window: process CPU (all threads, % of one core), Render Thread CPU, fps and frame-time
percentiles from frametrace.tsv, mean GPU utilisation from nvidia-smi. Results are appended to
<capture-dir>/ab.tsv.
"""
import argparse
import os
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import enginectl  # noqa: E402

HZ = os.sysconf("SC_CLK_TCK")


def thread_ticks(pid):
    out = {}
    for tid in os.listdir(f"/proc/{pid}/task"):
        try:
            with open(f"/proc/{pid}/task/{tid}/stat") as f:
                stat = f.read()
            with open(f"/proc/{pid}/task/{tid}/comm") as f:
                comm = f.read().strip()
        except OSError:
            continue
        fields = stat[stat.rindex(")") + 2:].split()
        out[tid] = (comm, int(fields[11]) + int(fields[12]))
    return out


def last_frame_t(path):
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 4096))
        lines = [l for l in f.read().decode(errors="ignore").splitlines() if l.startswith("F\t")]
    return float(lines[-1].split("\t")[1]) if lines else 0.0


def frames_between(path, ta, tb):
    t = []
    with open(path) as f:
        for line in f:
            if line.startswith("F\t"):
                x = float(line.split("\t")[1])
                if ta < x <= tb:
                    t.append(x)
    return t


def gpu_util():
    out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() else None


def window(pid, ctl, ft, mode, secs):
    with open(f"/proc/{pid}/mem", "r+b") as mem:
        mem.seek(ctl + 16)
        mem.write(mode.to_bytes(4, "little"))
    time.sleep(2)  # settle
    time.sleep(1.1)  # frametrace flushes once a second
    ta = last_frame_t(ft)
    c0, k0, w0 = thread_ticks(pid), time.monotonic(), enginectl.read(pid, ctl)
    gpu = []
    end = k0 + secs
    while time.monotonic() < end:
        g = gpu_util()
        if g is not None:
            gpu.append(g)
        time.sleep(0.5)
    c1, k1, w1 = thread_ticks(pid), time.monotonic(), enginectl.read(pid, ctl)
    time.sleep(1.1)
    tb = last_frame_t(ft) - 1100  # drop the frames presented after the window closed
    tb = max(tb, ta)
    dt = k1 - k0
    total = sum(c1[t][1] - c0[t][1] for t in c1 if t in c0) / HZ / dt * 100
    render = sum(c1[t][1] - c0[t][1] for t in c1 if t in c0 and c1[t][0] == "Render Thread") / HZ / dt * 100
    busiest = sorted(((c1[t][1] - c0[t][1]) / HZ / dt * 100, c1[t][0]) for t in c1 if t in c0)[-6:][::-1]
    fr = frames_between(ft, ta, tb)
    iv = [b - a for a, b in zip(fr, fr[1:])]
    fps = len(iv) / ((fr[-1] - fr[0]) / 1000) if len(iv) > 1 else 0
    q = (lambda p: sorted(iv)[min(len(iv) - 1, int(p * len(iv)))]) if iv else (lambda p: 0)
    return {
        "mode": "block" if mode else "spin",
        "cpu_total": total, "cpu_render": render,
        "fps": fps, "p50": q(0.5), "p95": q(0.95), "p99": q(0.99), "max": max(iv) if iv else 0,
        "gpu": statistics.mean(gpu) if gpu else 0,
        "waits_s": (w1[3] - w0[3]) / dt, "blocked_pct": (w1[4] - w0[4]) / 1e7 / dt,
        "spin_pct": (w1[6] - w0[6]) / 1e7 / dt,
        "busiest": ", ".join(f"{n} {p:.0f}%" for p, n in busiest),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cap")
    ap.add_argument("--secs", type=float, default=10)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    pid = enginectl.game_pid()
    ctl = enginectl.find_ctl(pid)
    ft = os.path.join(a.cap, "frametrace.tsv")
    out = os.path.join(a.cap, "ab.tsv")
    cols = ["label", "mode", "cpu_total", "cpu_render", "fps", "p50", "p95", "p99", "max", "gpu",
            "waits_s", "blocked_pct", "spin_pct", "busiest"]
    new = not os.path.exists(out)
    with open(out, "a") as f:
        if new:
            f.write("\t".join(cols) + "\n")
        for r in range(a.rounds):
            for mode in (0, 1):
                w = window(pid, ctl, ft, mode, a.secs)
                w["label"] = a.label
                row = [w[c] if isinstance(w[c], str) else f"{w[c]:.1f}" for c in cols]
                f.write("\t".join(row) + "\n")
                f.flush()
                print(f"{a.label:8s} {w['mode']:5s} cpu {w['cpu_total']:5.0f}%  render {w['cpu_render']:4.0f}%"
                      f"  fps {w['fps']:5.1f}  ft p50 {w['p50']:5.1f} p95 {w['p95']:5.1f} p99 {w['p99']:5.1f}"
                      f" max {w['max']:6.1f}  gpu {w['gpu']:3.0f}%  blocked {w['blocked_pct']:3.0f}%"
                      f" spin {w['spin_pct']:3.0f}%\n         {w['busiest']}", flush=True)
    # leave the patch on
    with open(f"/proc/{pid}/mem", "r+b") as mem:
        mem.seek(ctl + 16)
        mem.write((1).to_bytes(4, "little"))
