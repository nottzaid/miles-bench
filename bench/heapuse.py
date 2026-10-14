"""Per-heap occupancy from a memtrace.tsv: live placed bytes counted once (union of ranges) vs
summed (aliasing), grouped by the heap's creating call chain. Usage: heapuse.py trace.tsv"""
import collections, sys

heaps, res = {}, {}
for line in open(sys.argv[1], encoding='utf-8', errors='replace'):
    f = line.rstrip('\n').split('\t')
    if f[0] == 'HC':
        heaps[f[2]] = (int(f[3]), int(f[4]), int(f[6]), f[7], int(f[8]), f[11] if len(f) > 11 else '')
    elif f[0] == 'HD':
        heaps.pop(f[2], None)
    elif f[0] == 'RC' and f[3] == 'placed':
        res[f[2]] = (f[14], int(f[15]), int(f[16]), int(f[9]), int(f[5]), int(f[6]), int(f[4]))
    elif f[0] == 'RD':
        res.pop(f[2], None)

per_heap = collections.defaultdict(list)
for heap, off, size, fmt, w, h, dim in res.values():
    if heap in heaps:
        per_heap[heap].append((off, off + size, fmt, w, h, dim))

groups = collections.defaultdict(lambda: [0, 0, 0, 0, 0, collections.Counter()])
for p, (size, htype, pool, flags, vk, callers) in heaps.items():
    spans = sorted(per_heap[p])
    union, summed, cur_s, cur_e = 0, 0, None, None
    for s, e, *_ in spans:
        summed += e - s
        if cur_e is None or s > cur_e:
            if cur_e is not None: union += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None: union += cur_e - cur_s
    chain = '<'.join(x.split('!+')[1] for x in callers.split('<')[1:4])
    g = groups[(chain, htype, pool, flags, vk)]
    g[0] += 1; g[1] += size; g[2] += min(union, size); g[3] += summed; g[4] += len(spans)
    for s, e, fmt, w, h, dim in spans:
        g[5][(fmt, dim)] += e - s

M = 1 << 20
print(f"{'heaps':>5} {'size':>7} {'used':>7} {'summed':>7} {'res':>6}  type/pool/flags/vk  chain (below the heap-create wrapper)")
for (chain, ht, pool, fl, vk), g in sorted(groups.items(), key=lambda kv: -kv[1][1])[:20]:
    top = ', '.join(f"fmt{f}/{'buf' if d == 1 else 'tex'}:{b / M:.0f}" for (f, d), b in g[5].most_common(3))
    print(f"{g[0]:5d} {g[1] / M:7.0f} {g[2] / M:7.0f} {g[3] / M:7.0f} {g[4]:6d}  {ht}/{pool}/{fl}/vk{vk}  {chain}  [{top}]")
tot = [sum(g[i] for g in groups.values()) for i in range(4)]
print(f"\nall heaps: {tot[0]} heaps, {tot[1] / M:.0f} MiB reserved, {tot[2] / M:.0f} MiB actually covered by live "
      f"resources, {tot[3] / M:.0f} MiB if aliasing were not used")
