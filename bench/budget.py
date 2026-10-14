"""Read or change the engine's named memory budgets in a running MilesMorales.exe.

The table is a {entries*, count} pair at RVA 0x84aecf0 (v1.1116.0.0); each 24-byte entry is
{char *name, u32 name_len, u32 crc, u64 bytes}. Found via D3DBufferManager::InitBuffer's lookup
of "ManagedBuffer" (fn 0x2132e50).

    python3 bench/budget.py                      # list
    python3 bench/budget.py TextureAllocMedium=1100   # set, in MiB
"""
import struct, subprocess, sys

TABLE_RVA = 0x84aecf0
pid = int(subprocess.check_output(['pgrep', '-x', 'MilesMorales.ex']).split()[0])
base = next(int(l.split('-')[0], 16) for l in open(f'/proc/{pid}/maps') if 'MilesMorales.exe' in l)
mem = open(f'/proc/{pid}/mem', 'r+b', buffering=0)

def rd(addr, n):
    mem.seek(addr); return mem.read(n)

ptr, count = struct.unpack('<QI', rd(base + TABLE_RVA, 12))
entries = {}
for i in range(count):
    name_ptr, name_len, crc, val = struct.unpack('<QIIQ', rd(ptr + 24 * i, 24))
    name = rd(name_ptr, name_len).decode()
    entries[name] = (ptr + 24 * i + 16, val)

for arg in sys.argv[1:]:
    name, mib = arg.split('=')
    addr, old = entries[name]
    new = int(float(mib) * 2**20)
    mem.seek(addr); mem.write(struct.pack('<Q', new))
    print(f"{name}: {old / 2**20:.0f} -> {new / 2**20:.0f} MiB")
    entries[name] = (addr, new)

if len(sys.argv) == 1:
    for name, (addr, val) in entries.items():
        print(f"{name:24s} {val / 2**20:8.0f} MiB")
