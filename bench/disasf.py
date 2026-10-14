"""Disassemble MilesMorales.exe code from the file on disk (game closed is fine).

    python3 bench/disasf.py <rva hex> [bytes]
"""
import sys

import capstone
import pefile

EXE = "/home/zaid/Games/Marvel’s Spider-Man - Miles Morales/MilesMorales.exe"
rva = int(sys.argv[1], 16)
n = int(sys.argv[2], 0) if len(sys.argv) > 2 else 256
pe = pefile.PE(EXE, fast_load=True)
code = pe.get_data(rva, n)
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
for i in md.disasm(code, 0x140000000 + rva):
    print(f"{i.address - 0x140000000:8x}  {i.bytes.hex():24s} {i.mnemonic:8s} {i.op_str}")
