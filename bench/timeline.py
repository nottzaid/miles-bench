"""Print a samples.tsv recording as a timeline of per-interval rates (bench/sample.sh output)."""
import csv, sys

rows = list(csv.DictReader(open(sys.argv[1]), delimiter='\t'))
num = lambda r, k: float(r[k]) if r[k] else float('nan')
t0 = num(rows[0], 't')
print(f"{'t(s)':>6} {'rss':>5} {'swap':>5} {'anon':>5} {'pin':>5} {'vram':>5} {'zram':>5} "
      f"{'game MB/s':>9} {'sda MB/s':>8} {'majflt/s':>8} {'gpu%':>4}")
for a, b in zip(rows, rows[1:]):
    dt = num(b, 't') - num(a, 't') or 1
    print(f"{num(b,'t')-t0:6.0f} {b['rss']:>5} {b['swap']:>5} {b['anon_rss']:>5} {b['nvidiactl_rss']:>5} "
          f"{b['game_vram']:>5} {b['zram_used']:>5} "
          f"{(num(b,'game_read')-num(a,'game_read'))/dt:9.1f} {(num(b,'sda_read')-num(a,'sda_read'))/dt:8.1f} "
          f"{(num(b,'majflt')-num(a,'majflt'))/dt:8.0f} {b['gpu_util']:>4}")
