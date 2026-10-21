"""Pool frame times per setting from bench/livetoggle.sh segments.  segscore.py frametrace.tsv segfile"""
import sys, bisect
F=[float(l.split('\t')[1]) for l in open(sys.argv[1]) if l.startswith('F\t')]
segs=[l.split() for l in open(sys.argv[2])]
for cfg in ('A','B'):
    d=[]; dur=0; per=[]
    for c,a,b in segs:
        if c!=cfg: continue
        a=float(a); b=float(b)
        w=F[bisect.bisect_left(F,a):bisect.bisect_right(F,b)]
        dd=[y-x for x,y in zip(w,w[1:])]; d+=dd; dur+=(w[-1]-w[0])/1000
        per.append(len(dd)/((w[-1]-w[0])/1000))
    d.sort(); n=len(d)
    print(f"{cfg}: {len(per)} segs, {n/dur:.2f} fps (segments {' '.join(f'{x:.1f}' for x in per)}), p50 {d[n//2]:.1f} p95 {d[int(.95*n)]:.1f} p99 {d[int(.99*n)]:.1f}, >40 {sum(x>40 for x in d)/dur*60:.1f}/min, >50 {sum(x>50 for x in d)}")
