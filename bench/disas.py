"""Disassemble engine code straight from the running game's memory (no disk reads, no Ghidra).

    python3 bench/disas.py <rva hex> [bytes, default 256]
"""
import os
import sys

import capstone

sys.path.insert(0, os.path.dirname(__file__))
import enginectl  # noqa: E402

rva = int(sys.argv[1], 16)
n = int(sys.argv[2], 0) if len(sys.argv) > 2 else 256
pid = enginectl.game_pid()
base = None
for line in open(f"/proc/{pid}/maps"):
    if line.rstrip().endswith("MilesMorales.exe"):
        base = int(line.split("-")[0], 16)
        break
base = 0x140000000 if base is None else base
with open(f"/proc/{pid}/mem", "rb", buffering=0) as m:
    m.seek(base + rva)
    code = m.read(n)
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
for i in md.disasm(code, 0x140000000 + rva):
    print(f"{i.address - 0x140000000:8x}  {i.mnemonic:8s} {i.op_str}")
