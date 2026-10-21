"""winscore.py frametrace.tsv a b: fps and tails of the frames between frame-trace times a and b (ms).
Used by bench/owrun.sh for the open-world launches in data/s17_launches.csv."""
import sys, bisect
F = [float(l.split('\t')[1]) for l in open(sys.argv[1]) if l.startswith('F\t')]
a, b = float(sys.argv[2]), float(sys.argv[3])
w = F[bisect.bisect_left(F, a):bisect.bisect_right(F, b)]
d = sorted(y - x for x, y in zip(w, w[1:])); n = len(d); dur = (w[-1] - w[0]) / 1000
print(f"{n/dur:.2f} fps over {dur:.0f} s, p50 {d[n//2]:.1f} p95 {d[int(.95*n)]:.1f} p99 {d[int(.99*n)]:.1f} max {d[-1]:.0f}, "
      f">40 {sum(x>40 for x in d)/dur*60:.1f}/min, >50 {sum(x>50 for x in d)}")
