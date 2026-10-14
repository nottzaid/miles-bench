"""Gameplay measurement for bench/fightrun.sh.

    python3 bench/fightsum.py <capture dir> start              # JSON marker on stdout
    python3 bench/fightsum.py <capture dir> end <marker.json>  # summary since the marker

From the marker to now: frame rate and frame-time percentiles (frametrace.tsv), frames over 40 and
100 ms, the worst frame, system swap-ins and the game's major faults, plus the end state: GPU
memory vkd3d holds in system RAM (pinned; last "Memory heap #1" line), the game's own telemetry
(Video/Sys usage, Demoted) and light grid loss reports.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import enginectl  # noqa: E402
from ab import frames_between, last_frame_t  # noqa: E402

cap = sys.argv[1]
ft = os.path.join(cap, "frametrace.tsv")
pid = enginectl.game_pid()


def paging():
    swin = next(int(line.split()[1]) for line in open("/proc/vmstat") if line.startswith("pswpin "))
    st = open(f"/proc/{pid}/stat").read()
    return swin, int(st[st.rindex(")") + 2:].split()[9])


if sys.argv[2] == "start":
    swin, majflt = paging()
    print(json.dumps(dict(t=last_frame_t(ft), swin=swin, majflt=majflt, wall=time.time())))
    sys.exit()

m = json.load(open(sys.argv[3]))
swin, majflt = paging()
tb = last_frame_t(ft)
t = frames_between(ft, m["t"], tb)
iv = sorted(b - a for a, b in zip(t, t[1:]))
q = lambda p: iv[min(len(iv) - 1, int(p * len(iv)))]
secs = (t[-1] - t[0]) / 1000
row = dict(fps=len(iv) / secs, p50=q(.5), p95=q(.95), p99=q(.99), over40=sum(x > 40 for x in iv),
           over100=sum(x > 100 for x in iv), worst=iv[-1], secs=secs, swapins=swin - m["swin"],
           majflt=majflt - m["majflt"])
log = open(os.path.join(cap, "vkd3d.log"), errors="ignore").read()
heap1 = re.findall(r"Memory heap #1, size \d+ MiB, budget: \d+ MiB, usage: (\d+) MiB", log)
row["pinned_mib"] = int(heap1[-1]) if heap1 else None
row["lightgrid_loss"] = log.count("light grid: LOSS")
game_log = os.path.expanduser(os.path.join(os.path.dirname(__file__), "..", "prefix/pfx/drive_c/users/zaid/Documents",
                                           "Marvel's Spider-Man Miles Morales", "Marvel's Spider-Man Miles Morales.log"))
lines = open(game_log, errors="ignore").read().splitlines()
tele = [l for l in lines if "[Render] Working set" in l]
# Autosaves mean the fight moved on to a later phase (a different scene from the other launches).
row["saves"] = sum("[Save] Request save type" in l for l in lines)
if tele:
    for k, name in (("Video Usage", "video_mib"), ("Sys Usage", "sys_mib"), ("Demoted", "demoted_mib"),
                    ("Tex Usage", "tex_mib")):
        mm = re.search(k + r": (\d+)MB", tele[-1])
        row[name] = int(mm.group(1)) if mm else None
print(json.dumps(row))
print(f"{os.path.basename(cap)}: {row['fps']:.2f} fps over {secs:.0f} s, p50 {row['p50']:.1f} p95 {row['p95']:.1f} "
      f"p99 {row['p99']:.1f} ms, {row['over40']} frames >40 ms, {row['over100']} >100 ms, worst {row['worst']:.0f} ms; "
      f"{row['swapins']} swap-ins, {row['majflt']} game major faults; pinned {row['pinned_mib']} MiB, "
      f"game sys {row.get('sys_mib')} video {row.get('video_mib')} demoted {row.get('demoted_mib')} MiB; "
      f"light grid losses {row['lightgrid_loss']}; autosaves {row['saves']}", file=sys.stderr)
