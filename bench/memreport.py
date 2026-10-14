"""Summarise a memtrace.tsv (see src/vkd3d-proton/libs/vkd3d/memtrace.c for the format).

Replays every event up to --at (ms, default: end of trace) and prints what is live, split by
where the bytes physically are: VRAM, BAR (CPU-visible VRAM window), or SYS (GPU-visible system
RAM, i.e. the driver-pinned nvidiactl memory).

    python3 bench/memreport.py captures/<run>/memtrace.tsv [--at MS] [--top N]
"""
import argparse
import collections

HEAP_TYPES = {1: 'DEFAULT', 2: 'UPLOAD', 3: 'READBACK', 4: 'CUSTOM', 5: 'GPU_UPLOAD'}
DIMS = {1: 'buffer', 2: 'tex1d', 3: 'tex2d', 4: 'tex3d'}
FORMATS = {
    0: 'UNKNOWN', 2: 'RGBA32F', 9: 'RGBA16_TL', 10: 'RGBA16F', 16: 'RG32F', 19: 'R32G8X24_TL',
    20: 'D32S8', 24: 'RGB10A2', 26: 'R11G11B10F', 27: 'RGBA8_TL', 28: 'RGBA8', 29: 'RGBA8_SRGB',
    34: 'RG16F', 35: 'RG16', 39: 'R32_TL', 40: 'D32F', 41: 'R32F', 42: 'R32U', 44: 'R24G8_TL',
    45: 'D24S8', 49: 'RG8', 54: 'R16F', 56: 'R16', 61: 'R8', 70: 'BC1_TL', 71: 'BC1', 72: 'BC1_SRGB',
    76: 'BC3_TL', 77: 'BC3', 78: 'BC3_SRGB', 79: 'BC4_TL', 80: 'BC4', 82: 'BC5_TL', 83: 'BC5',
    84: 'BC5_SNORM', 87: 'BGRA8', 90: 'BGRA8_TL', 91: 'BGRA8_SRGB', 94: 'BC6H_TL', 95: 'BC6H_UF16',
    97: 'BC7_TL', 98: 'BC7', 99: 'BC7_SRGB',
}
MiB = 1 << 20


def mib(n):
    return f"{n / MiB:9.1f}"


def load(path, at):
    mem_types, heaps_info = {}, {}
    vk_live = {}
    heaps, resources, names = {}, {}, {}
    vk_failures = []
    end_t = 0.0
    for line in open(path, encoding='utf-8', errors='replace'):
        f = line.rstrip('\n').split('\t')
        tag = f[0]
        if tag == 'MH':
            heaps_info[int(f[1])] = (int(f[2]), int(f[3], 16))
            continue
        if tag == 'MT':
            mem_types[int(f[1])] = (int(f[2], 16), int(f[3]))
            continue
        if tag.startswith('#') or len(f) < 2:
            continue
        t = float(f[1])
        if at is not None and t > at:
            break
        end_t = t
        if tag == 'VA':
            vk_type, size, ok, budgeted, handle = int(f[2]), int(f[3]), f[4] == '1', f[5] == '1', f[6]
            if ok:
                vk_live[handle] = (vk_type, size, budgeted)
            else:
                vk_failures.append((t, vk_type, size))
        elif tag == 'VF':
            vk_live.pop(f[4], None)
        elif tag == 'HC':
            heaps[f[2]] = dict(t=t, size=int(f[3]), type=int(f[4]), cpu_page=int(f[5]), pool=int(f[6]),
                               flags=int(f[7], 16), vk_type=int(f[8]), sub=f[9] == '1',
                               exe_rva=f[10], callers=f[11] if len(f) > 11 else '')
            names.pop(f[2], None)
        elif tag == 'HD':
            heaps.pop(f[2], None)
            names.pop(f[2], None)
        elif tag == 'RC':
            resources[f[2]] = dict(t=t, kind=f[3], dim=int(f[4]), width=int(f[5]), height=int(f[6]),
                                   depth=int(f[7]), mips=int(f[8]), format=int(f[9]), flags=int(f[10], 16),
                                   heap_type=int(f[12]), heap=f[14], heap_offset=int(f[15]),
                                   req_size=int(f[16]), vk_type=int(f[17]), sub=f[18] == '1',
                                   exe_rva=f[19], callers=f[20] if len(f) > 20 else '')
            names.pop(f[2], None)
        elif tag == 'RD':
            resources.pop(f[2], None)
            names.pop(f[2], None)
        elif tag == 'N':
            names[f[2]] = f[3] if len(f) > 3 else ''
    return mem_types, heaps_info, vk_live, heaps, resources, names, vk_failures, end_t


def classify(mem_types, heaps_info, vk_type):
    props, heap = mem_types.get(vk_type, (0, -1))
    if not heaps_info.get(heap, (0, 0))[1] & 1:
        return 'SYS'
    return 'BAR' if props & 0x2 else 'VRAM'


def name_group(name):
    """Collapse per-instance suffixes so similar resources group together."""
    out = []
    for ch in name:
        out.append('#' if ch.isdigit() else ch)
    s = ''.join(out)
    while '##' in s:
        s = s.replace('##', '#')
    return s[:70]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('trace')
    ap.add_argument('--at', type=float)
    ap.add_argument('--top', type=int, default=25)
    a = ap.parse_args()

    mem_types, heaps_info, vk_live, heaps, resources, names, vk_failures, end_t = load(a.trace, a.at)
    cls = lambda vt: classify(mem_types, heaps_info, vt)

    print(f"== state at t={end_t / 1000:.1f} s")
    print("\n-- Vulkan allocations (what physically exists)")
    by = collections.Counter(); cnt = collections.Counter()
    for vk_type, size, budgeted in vk_live.values():
        key = (cls(vk_type), vk_type, 'budgeted' if budgeted else 'internal')
        by[key] += size; cnt[key] += 1
    for key, size in sorted(by.items(), key=lambda kv: -kv[1]):
        print(f"{mib(size)} MiB  {cnt[key]:6d} allocs  {key[0]:4s} type {key[1]:2d} {key[2]}")
    tot = collections.Counter()
    for (c, _, _), size in by.items():
        tot[c] += size
    print('   totals: ' + '  '.join(f"{c} {size / MiB:.0f} MiB" for c, size in tot.most_common()))
    if vk_failures:
        print(f"   {len(vk_failures)} failed vkAllocateMemory calls, first at {vk_failures[0][0] / 1000:.1f} s: "
              + ', '.join(f"type {vt} {s / MiB:.0f} MiB" for _, vt, s in vk_failures[:6]))

    print("\n-- D3D12 heaps (game-created ID3D12Heap), by memory class / heap type")
    hb = collections.Counter(); hc = collections.Counter()
    for h in heaps.values():
        key = (cls(h['vk_type']), HEAP_TYPES.get(h['type'], h['type']), h['pool'], h['flags'])
        hb[key] += h['size']; hc[key] += 1
    for key, size in sorted(hb.items(), key=lambda kv: -kv[1]):
        print(f"{mib(size)} MiB  {hc[key]:6d} heaps  {key[0]:4s} {key[1]:8s} pool={key[2]} flags={key[3]:#x}")

    # Space actually used inside each heap by live placed resources.
    used = collections.Counter()
    for r in resources.values():
        if r['kind'] == 'placed' and r['heap'] in heaps:
            used[r['heap']] += r['req_size']
    total_heap = sum(h['size'] for h in heaps.values())
    total_used = sum(min(used[p], heaps[p]['size']) for p in heaps)
    if total_heap:
        print(f"   placed resources fill {total_used / MiB:.0f} of {total_heap / MiB:.0f} MiB of heap space "
              f"({100 * total_used / total_heap:.0f}%)")

    print("\n-- committed resources, by memory class / heap type / dimension")
    cb = collections.Counter(); cc = collections.Counter()
    for r in resources.values():
        if r['kind'] != 'committed':
            continue
        key = (cls(r['vk_type']), HEAP_TYPES.get(r['heap_type'], r['heap_type']), DIMS.get(r['dim'], r['dim']))
        cb[key] += r['req_size']; cc[key] += 1
    for key, size in sorted(cb.items(), key=lambda kv: -kv[1]):
        print(f"{mib(size)} MiB  {cc[key]:6d} res    {key[0]:4s} {key[1]:8s} {key[2]}")

    def owner_class(r):
        if r['kind'] == 'placed' and r['heap'] in heaps:
            return cls(heaps[r['heap']]['vk_type'])
        return cls(r['vk_type'])

    for title, keyf in (
        ("largest live allocations (heaps and committed resources)", None),
        ("by debug name (digits collapsed)", 'name'),
        ("by calling function in MilesMorales.exe (exe_rva)", 'rva'),
        ("by format (textures)", 'format'),
    ):
        print(f"\n-- {title}")
        if keyf is None:
            items = [(h['size'], cls(h['vk_type']), 'heap ' + HEAP_TYPES.get(h['type'], '?'), p, h['exe_rva'],
                      names.get(p, '')) for p, h in heaps.items()]
            items += [(r['req_size'], cls(r['vk_type']), f"{r['kind']} {DIMS.get(r['dim'])} "
                       f"{r['width']}x{r['height']}x{r['depth']} m{r['mips']} {FORMATS.get(r['format'], r['format'])}",
                       p, r['exe_rva'], names.get(p, '')) for p, r in resources.items() if r['kind'] == 'committed']
            for size, c, desc, p, rva, nm in sorted(items, key=lambda x: -x[0])[:a.top]:
                print(f"{mib(size)} MiB  {c:4s} {desc:52s} rva {rva:10s} {nm}")
            continue
        agg = collections.Counter(); n = collections.Counter(); where = collections.defaultdict(collections.Counter)
        for p, r in resources.items():
            if keyf == 'name':
                k = name_group(names.get(p, '(unnamed)'))
            elif keyf == 'rva':
                k = r['exe_rva'] + '  ' + r['callers'].split('<')[0]
            else:
                if r['dim'] == 1:
                    continue
                k = FORMATS.get(r['format'], str(r['format']))
            agg[k] += r['req_size']; n[k] += 1; where[k][owner_class(r)] += r['req_size']
        if keyf == 'rva':
            for p, h in heaps.items():
                k = h['exe_rva'] + '  ' + h['callers'].split('<')[0] + '  (heaps)'
                agg[k] += h['size']; n[k] += 1; where[k][cls(h['vk_type'])] += h['size']
        for k, size in agg.most_common(a.top):
            split = ' '.join(f"{c}:{v / MiB:.0f}" for c, v in where[k].most_common())
            print(f"{mib(size)} MiB  {n[k]:6d}  {k:60s} [{split}]")


if __name__ == '__main__':
    main()
