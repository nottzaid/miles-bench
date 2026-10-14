#!/usr/bin/env bash
# Every 2 s, append one row of the game's memory and I/O to $1 (TSV, MiB unless noted):
#   rss, swap, anon_rss, nvidiactl_rss (driver-pinned system RAM), game_vram, total_vram, zram_used,
#   then cumulative counters: game_read (MiB the game actually read from storage), majflt (major
#   faults, swap-ins included), sda_read (MiB read from the game's disk), and gpu_util (%).
#
# Kept cheap, because it runs next to a CPU-bound game (bench runs and play.sh sessions): rss, swap
# and anon come from /proc/<pid>/status (counters, no page-table walk); nvidiactl_rss needs smaps
# (a walk of every page table under the game's mmap lock), so it is refreshed every 30 s only; the
# GPU numbers come from two long-running nvidia-smi loops (NVML set up once) instead of two
# nvidia-smi processes per sample. The old version cost ~9% of a core in the driven fight
# (perf sched, v13-S9-sched).
set -u
out=${1:?usage: sample.sh <out.tsv>}
printf 't\trss\tswap\tanon_rss\tnvidiactl_rss\tgame_vram\ttotal_vram\tzram_used\tgame_read\tmajflt\tsda_read\tgpu_util\n' > "$out"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/sample.XXXXXX")
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits -lms 2000 >> "$tmp/gpu" 2>/dev/null &
gpu_loop=$!
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits -lms 2000 >> "$tmp/apps" 2>/dev/null &
apps_loop=$!
trap 'kill $gpu_loop $apps_loop 2>/dev/null; rm -rf "$tmp"' EXIT
trap 'exit 0' TERM INT

pid= nvctl= n=0
while :; do
    if [[ -z $pid || ! -d /proc/$pid ]]; then
        pid=$(pgrep -x MilesMorales.ex | head -1)
        nvctl=
    fi
    if [[ -n $pid && -r /proc/$pid/status ]]; then
        read -r rss swap anon < <(awk '
            /^VmRSS:/ { r = $2 } /^VmSwap:/ { s = $2 } /^RssAnon:/ { a = $2 }
            END { printf "%d %d %d\n", r/1024, s/1024, a/1024 }' "/proc/$pid/status")
        if (( n % 15 == 0 )) || [[ -z $nvctl ]]; then
            nvctl=$(awk '/^[0-9a-f]+-[0-9a-f]+ / { nv = ($6 ~ /nvidiactl/); next } nv && /^Rss:/ { s += $2 }
                END { printf "%d", s/1024 }' "/proc/$pid/smaps" 2>/dev/null)
        fi
        n=$((n + 1))
        gvram=$(tail -n 20 "$tmp/apps" 2>/dev/null | awk -F', ' -v p="$pid" '$1 == p { v = $2 } END { print v }')
        read -r tvram gpu < <(tail -n 1 "$tmp/gpu" 2>/dev/null | tr -d ',')
        zram=$(awk 'NR == 1 { printf "%d", $3 / 1048576 }' /sys/block/zram0/mm_stat 2>/dev/null)
        gread=$(awk '/^read_bytes:/ { printf "%d", $2 / 1048576 }' "/proc/$pid/io" 2>/dev/null)
        majflt=$(sed 's/.*) //' "/proc/$pid/stat" 2>/dev/null | awk '{ print $10 }')
        sda=$(awk '{ printf "%d", $3 * 512 / 1048576 }' /sys/block/sda/stat)
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date +%s)" "$rss" "$swap" "$anon" "$nvctl" \
            "${gvram:-}" "${tvram:-}" "${zram:-}" "${gread:-}" "${majflt:-}" "$sda" "${gpu:-}" >> "$out"
    fi
    # Keep the loop files small (the loops append with O_APPEND, so truncating in place is safe).
    if (( n % 300 == 299 )); then
        tail -n 50 "$tmp/apps" > "$tmp/apps.t" 2>/dev/null && cat "$tmp/apps.t" > "$tmp/apps"
        tail -n 5 "$tmp/gpu" > "$tmp/gpu.t" 2>/dev/null && cat "$tmp/gpu.t" > "$tmp/gpu"
    fi
    sleep 2
done
