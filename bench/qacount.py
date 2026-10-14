"""Which resources the GPU's shaders actually touch, and where they live (VRAM or system memory).

    python3 bench/qacount.py <capture dir> [seconds at the end to use, default 30] [top N]

Needs a run with the descriptor-QA counting build (build/qa) and VKD3D_CONFIG=descriptor_qa_checks,
VKD3D_BENCH_QACOUNT=<capture>/qacount.tsv and MEMTRACE=1. Every descriptor-heap access a shader makes
(texture sample/load, bindless buffer load/store, ...) adds 1 to its resource's counter (helper
pixel lanes don't count). Root descriptors (root CBV/SRV/UAV by address), index/vertex buffer
fetches and render target writes are not descriptor accesses and are not counted.

Counters are per cookie slot (cookie & (slots - 1)); memtrace RK lines give each resource's cookie,
qacount CV lines map view cookies to their resource.
"""
import collections
import sys

cap = sys.argv[1]
window_s = float(sys.argv[2]) if len(sys.argv) > 2 else 30
top = int(sys.argv[3]) if len(sys.argv) > 3 else 40

SLOTS = 1 << 20
VRAM_TYPES = {7, 10}  # 7 VRAM, 10 BAR (VRAM, host-visible)

res = {}          # ptr -> dict
cookie_res = {}   # resource cookie -> ptr
names = {}        # object ptr -> name
heaps = {}        # heap ptr -> dict
mem_types = {}
for line in open(f"{cap}/memtrace.tsv", errors="replace"):
    f = line.rstrip("\n").split("\t")
    tag = f[0]
    if tag == "MT":
        mem_types[int(f[1])] = (int(f[2], 16), int(f[3]))
    elif tag == "RC":
        res[f[2]] = dict(t=float(f[1]), kind=f[3], dim=int(f[4]), width=int(f[5]), height=int(f[6]),
                         depth=int(f[7]), mips=int(f[8]), format=int(f[9]), flags=int(f[10], 16),
                         heap_type=int(f[12]), heap_flags=int(f[13], 16), heap=f[14], size=int(f[16]),
                         vk_type=int(f[17]), rva=f[19] if len(f) > 19 else "", alive=True)
    elif tag == "RK":
        cookie_res[int(f[3])] = f[2]
        if f[2] in res:
            res[f[2]]["cookie"] = int(f[3])
    elif tag == "RD":
        if f[2] in res:
            res[f[2]]["alive"] = False
    elif tag == "N":
        names[f[2]] = f[3]
    elif tag == "HC":
        heaps[f[2]] = dict(size=int(f[3]), type=int(f[4]), flags=int(f[7], 16), vk_type=int(f[8]))

# slot -> list of resource ptrs (resource cookies and view cookies)
slot_res = collections.defaultdict(set)
for c, p in cookie_res.items():
    slot_res[c & (SLOTS - 1)].add(p)
views = 0
snaps = []  # (t_ms, presents, {slot: count})
cur = None
for line in open(f"{cap}/qacount.tsv"):
    f = line.rstrip("\n").split("\t")
    if f[0] == "CV":
        r = cookie_res.get(int(f[2]))
        if r:
            slot_res[int(f[1]) & (SLOTS - 1)].add(r)
            views += 1
    elif f[0] == "QT":
        cur = (float(f[1]), int(f[2]), {})
        snaps.append(cur)
    elif f[0] == "QC" and cur:
        cur[2][int(f[1])] = int(f[2])

if len(snaps) < 2:
    sys.exit("not enough snapshots")
end_t = snaps[-1][0]
use = [s for s in snaps[1:] if s[0] > end_t - window_s * 1000]
first = snaps[snaps.index(use[0]) - 1]
frames = use[-1][1] - first[1]
secs = (use[-1][0] - first[0]) / 1000
total = collections.Counter()
for s in use:
    for slot, n in s[2].items():
        total[slot] += n
print(f"{len(use)} snapshots, {secs:.1f} s, {frames} presents ({frames / secs:.1f} fps under instrumentation); "
      f"{len(cookie_res)} resource cookies, {views} view cookies mapped")

per_res = collections.Counter()
unmapped = ambiguous = 0
for slot, n in total.items():
    cands = [p for p in slot_res.get(slot, ()) if res.get(p, {}).get("alive")] or list(slot_res.get(slot, ()))
    if not cands:
        unmapped += n
        continue
    if len(cands) > 1:
        ambiguous += n
    for p in cands:
        per_res[p] += n / len(cands)
allacc = sum(total.values())
print(f"accesses/frame {allacc / frames:,.0f}; unmapped {100 * unmapped / max(1, allacc):.1f}%, "
      f"shared slots {100 * ambiguous / max(1, allacc):.1f}%")


def where(r):
    t = r["vk_type"]
    return "VRAM" if t == 7 else "BAR" if t == 10 else f"sys{t}"


def label(p):
    r = res[p]
    n = names.get(p) or names.get(r["heap"]) or ""
    if r["dim"] == 1:
        shape = f"buffer {r['width'] / 2**20:.1f} MiB"
    else:
        shape = f"tex{r['dim'] - 1}d {r['width']}x{r['height']}" + (f"x{r['depth']}" if r["depth"] > 1 else "") + \
                f" fmt{r['format']} mips{r['mips']}"
    return f"{shape} {r['kind']} heap{r['heap_type']}/{r['heap_flags']:#x} rva {r['rva']} {n[:50]}"


groups = collections.Counter()
group_size = collections.Counter()
for p, n in per_res.items():
    groups[where(res[p])] += n
for p, r in res.items():
    if r["alive"]:
        group_size[where(r)] += r["size"]
print("\naccesses/frame by placement (live resource bytes there):")
for g, n in groups.most_common():
    print(f"   {g:6s} {n / frames:14,.0f}  {100 * n / allacc:5.1f}%   {group_size[g] / 2**20:8.0f} MiB")

print(f"\nhottest system-memory resources (accesses/frame, size):")
sysm = [(n, p) for p, n in per_res.items() if res[p]["vk_type"] not in VRAM_TYPES]
for n, p in sorted(sysm, reverse=True)[:top]:
    print(f"   {n / frames:12,.0f}  {res[p]['size'] / 2**20:7.1f} MiB  {where(res[p]):5s} {label(p)}")

print(f"\nlargest VRAM resources and how hot they are (accesses/frame per MiB):")
vram = [(r["size"], p) for p, r in res.items() if r["alive"] and r["vk_type"] in VRAM_TYPES]
for size, p in sorted(vram, reverse=True)[:top]:
    n = per_res.get(p, 0) / frames
    print(f"   {size / 2**20:7.1f} MiB  {n:12,.0f}  ({n / max(size / 2**20, 0.01):10,.0f}/MiB)  {where(res[p]):4s} {label(p)}")

cold = sum(r["size"] for p, r in res.items() if r["alive"] and r["vk_type"] in VRAM_TYPES and per_res.get(p, 0) == 0
           and not r["flags"] & 0x3)  # not render target / depth (those are written without descriptors)
print(f"\nVRAM in resources with zero descriptor accesses in the window (excluding RT/DS): {cold / 2**20:.0f} MiB")
