"""Rebuild the capture-derived tables in data/ from captures/ (the dashboard's launches, vram and
gaming_mode datasets).

    python3 bench/datasets.py            # writes data/launches.csv, data/vram.csv, data/gaming_mode.csv
    python3 bench/datasets.py --check    # compares with the files in data/ instead of writing

Which captures go in, and as which step, disk and arm, comes from data/runs.csv (the fight bench)
and data/gm_runs.csv (the gaming-mode series). Every launch is measured over the same stretch of
the fight: from its start to the game's 3rd autosave request (bench/fightwin.py, run here for a
capture that has no fightwin3.json yet). Per capture:
  fightwin3.json   fps, frame-time percentiles, slow frames, worst frame, window, game major faults
  fight.json       pinned RAM, demoted textures and whole-run swap-ins (state or counters read
                   once at the end of the run; fight.json's own fps covers a different window)
  samples.tsv      GPU busy and the video memory of every other process, over the window
  game.log         autosave requests, the engine's VRAM reports
"""
import csv
import io
import json
import os
import statistics
import subprocess
import sys
import time

bench = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data = os.path.join(bench, "data")
caps = os.path.join(bench, "captures")


def cap(run, name):
    return os.path.join(caps, run, name)


def window(run):
    path = cap(run, "fightwin3.json")
    if not os.path.exists(path):
        subprocess.run([sys.executable, os.path.join(bench, "bench", "fightwin.py"), "3", os.path.join(caps, run)],
                       check=True, stdout=subprocess.DEVNULL)
    return json.loads(open(path).read().splitlines()[0])


def samples(run, t0, t1):
    rows = csv.DictReader(open(cap(run, "samples.tsv")), delimiter="\t")
    return [r for r in rows if t0 <= float(r["t"]) <= t1]


def autosaves(run, start):
    day = time.strftime("%Y-%m-%d", time.localtime(start))
    out = []
    for line in open(cap(run, "game.log"), errors="ignore"):
        if "[Save] Request save type" in line:
            hh, mm, ss, ms = line[:12].split(":")
            out.append(time.mktime(time.strptime(f"{day} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S")) + int(ms) / 1000)
    return [s for s in out if s > start]


def vram_reports(run):
    """The engine's once-a-minute VRAM lines: (budget, usage, textures, demoted) in MiB."""
    out = []
    for line in open(cap(run, "game.log"), errors="ignore"):
        if "Video Budget:" in line:
            f = dict(p.split(": ") for p in line.split("> [Render] ", 1)[1].split("MB ") if ": " in p)
            out.append(tuple(int(f[k].rstrip("MB\n")) for k in ("Video Budget", "Video Usage", "Tex Usage", "Demoted")))
    return out


def common(run):
    """Metrics every table shares, over the start .. 3rd autosave request window."""
    w = window(run)
    start = json.load(open(cap(run, "fight-start.json")))
    t0, t1 = start["wall"], start["wall"] + w["secs"]
    s = samples(run, t0, t1)
    gpu = [float(r["gpu_util"]) for r in s if r.get("gpu_util")]
    desk = [float(r["total_vram"]) - float(r["game_vram"]) for r in s if r.get("total_vram") and r.get("game_vram")]
    return w, start, round(sum(gpu) / len(gpu), 1) if gpu else "", round(statistics.mean(desk))


def near_autosave(run, start, w):
    """Frames over 100 ms that ended between 1 s before and 4 s after the 1st or 2nd autosave request."""
    saves = autosaves(run, start["wall"])
    tb = start["t"] + (saves[2] - start["wall"]) * 1000
    t = [float(l.split("\t", 2)[1]) for l in open(cap(run, "frametrace.tsv")) if l.startswith("F\t")]
    t = [x for x in t if start["t"] < x <= tb]
    n = near = 0
    for a, b in zip(t, t[1:]):
        if b - a > 100:
            n += 1
            wall = start["wall"] + (b - start["t"]) / 1000
            near += any(-1 <= wall - s <= 4 for s in saves[:2])
    assert n == w["over100"], (run, n, w["over100"])
    return near


def launches():
    out = []
    for r in csv.DictReader(open(os.path.join(data, "runs.csv"))):
        run = r["run"]
        w, start, gpu, desk = common(run)
        fight = json.load(open(cap(run, "fight.json")))
        out.append(dict(
            run=run, step=r["step"], disk=r["disk"], fps=round(w["fps"], 2), p95_ms=round(w["p95"], 1),
            p99_ms=round(w["p99"], 1), frames_over_40ms=w["over40"], frames_over_100ms=w["over100"],
            worst_ms=round(w["worst"]), window_s=round(w["secs"]), over40_per_min=round(w["over40"] / w["secs"] * 60, 1),
            game_major_faults=w["majflt"] if w["majflt"] is not None else fight["majflt"],
            pinned_ram_mib=fight["pinned_mib"], gpu_busy_pct=gpu, desktop_vram_mib=desk,
            over100_near_autosave=near_autosave(run, start, w)))
    return out


def vram():
    label = {"S0": "Unpatched (S0)"}
    out = []
    for r in csv.DictReader(open(os.path.join(data, "runs.csv"))):
        if r["in_vram_table"] != "1":
            continue
        budget, usage, tex, demoted = vram_reports(r["run"])[-1]
        out.append(dict(run=r["run"], build=label.get(r["step"], r["step"]), video_budget_mib=budget,
                        video_usage_mib=usage, texture_usage_mib=tex, demoted_mib=demoted,
                        desktop_vram_mib=common(r["run"])[3]))
    return out


def gaming_mode():
    out = []
    for r in csv.DictReader(open(os.path.join(data, "gm_runs.csv"))):
        run = r["run"]
        w, start, gpu, desk = common(run)
        fight = json.load(open(cap(run, "fight.json")))
        rep = vram_reports(run)
        startup = next(int(l.split("VMEM Budget: ")[1].split()[0]) for l in open(cap(run, "game.log"), errors="ignore")
                       if "VMEM Budget: " in l)
        out.append(dict(
            series=r["series"], run=run, launch_order=r["launch_order"], arm=r["arm"], fps=round(w["fps"], 2),
            p99_ms=round(w["p99"], 1), frames_over_100ms=w["over100"], window_s=round(w["secs"]),
            game_major_faults=w["majflt"], swapins_whole_run=fight["swapins"], whole_run_s=round(fight["secs"]),
            swapins_per_s=round(fight["swapins"] / fight["secs"], 1),
            video_budget_mib=round(statistics.mean(x[0] for x in rep)), video_usage_mib=round(statistics.mean(x[1] for x in rep)),
            pinned_ram_mib=fight["pinned_mib"], demoted_mib=fight["demoted_mib"], startup_budget_mib=startup,
            desktop_vram_mib=desk))
    return out


def as_csv(rows):
    f = io.StringIO()
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return f.getvalue()


check = "--check" in sys.argv
bad = 0
for name, fn in (("launches", launches), ("vram", vram), ("gaming_mode", gaming_mode)):
    text = as_csv(fn())
    path = os.path.join(data, f"{name}.csv")
    if check:
        same = os.path.exists(path) and open(path).read() == text
        bad += not same
        print(f"{name}.csv: {'same' if same else 'DIFFERS'}")
    else:
        open(path, "w").write(text)
        print(f"wrote {path}")
sys.exit(1 if bad else 0)
