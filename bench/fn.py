"""Disassemble the function containing an RVA in MilesMorales.exe, with string and call annotations.

Function bounds come from .pdata (x64 unwind table), so no full analysis pass is needed.

    python3 bench/fn.py <rva> [<rva>...] [--exe PATH] [--max N]
    python3 bench/fn.py --xref-string "Tex Budget"    # functions that reference a string
"""
import argparse
import bisect
import mmap
import struct

import capstone
import pefile

EXE = "/home/zaid/Games/Marvel’s Spider-Man - Miles Morales/MilesMorales.exe"


class Image:
    def __init__(self, path):
        self.f = open(path, 'rb')
        self.data = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        self.pe = pefile.PE(data=self.data, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.sections = [(s.VirtualAddress, s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData),
                          s.PointerToRawData, s.SizeOfRawData, s.Name.rstrip(b'\0').decode()) for s in self.pe.sections]
        pdata = next(s for s in self.sections if s[4] == '.pdata')
        raw = self.data[pdata[2]:pdata[2] + pdata[3]]
        raw = raw[:len(raw) // 12 * 12]
        entries = [e for e in struct.iter_unpack('<III', raw) if e[0]]
        self.fn_begin = [e[0] for e in entries]
        self.fn_end = [e[1] for e in entries]

    def section(self, rva):
        for start, end, raw, rawsize, name in self.sections:
            if start <= rva < end:
                return start, raw, rawsize, name
        return None

    def read(self, rva, n):
        s = self.section(rva)
        if not s:
            return b''
        off = s[1] + (rva - s[0])
        return self.data[off:off + n]

    def function(self, rva):
        i = bisect.bisect_right(self.fn_begin, rva) - 1
        # Chained unwind entries split one function into several ranges; walk back to the first.
        while i > 0 and self.fn_begin[i] == self.fn_end[i - 1]:
            i -= 1
        start = self.fn_begin[i]
        j = i
        while j + 1 < len(self.fn_begin) and self.fn_begin[j + 1] == self.fn_end[j]:
            j += 1
        return start, self.fn_end[j]

    def string_at(self, rva):
        s = self.section(rva)
        if not s or s[3] not in ('.rdata', '.data'):
            return None
        b = self.read(rva, 200)
        if len(b) > 3 and b[1] == 0 and b[3] == 0 and 32 <= b[0] < 127:  # UTF-16
            txt = b.decode('utf-16-le', 'ignore').split('\0')[0]
            return 'L"' + txt + '"' if len(txt) >= 3 and txt.isprintable() else None
        txt = b.split(b'\0')[0]
        if len(txt) >= 4 and all(32 <= c < 127 or c in (9, 10) for c in txt):
            return '"' + txt.decode().replace('\n', '\\n') + '"'
        return None


def disasm(img, rva, max_insns):
    start, end = img.function(rva)
    code = img.read(start, end - start)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    print(f"\n== function {start:#x}-{end:#x} ({end - start} bytes), contains {rva:#x}")
    for n, ins in enumerate(md.disasm(code, img.base + start)):
        if n >= max_insns:
            print("   ..."); break
        irva = ins.address - img.base
        note = ''
        for op in ins.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                target = ins.address + ins.size + op.mem.disp - img.base
                s = img.string_at(target)
                note = f"  ; {target:#x}" + (f" {s}" if s else f" [{(img.section(target) or (0, 0, 0, '?'))[3]}]")
            elif op.type == capstone.x86.X86_OP_IMM and ins.mnemonic in ('call', 'jmp') and img.base <= op.imm < img.base + 0x10000000:
                note = f"  ; -> {op.imm - img.base:#x}"
        mark = '>>' if irva <= rva < irva + ins.size or irva + ins.size == rva else '  '
        print(f"{mark} {irva:#09x}  {ins.mnemonic:6s} {ins.op_str}{note}")


def xref_string(img, needle):
    """Find functions whose RIP-relative operands point at a string containing needle."""
    targets = []
    for start, end, raw, rawsize, name in img.sections:
        if name not in ('.rdata', '.data'):
            continue
        blob = img.data[raw:raw + rawsize]
        for enc in (needle.encode(), needle.encode('utf-16-le')):
            i = blob.find(enc)
            while i != -1:
                # back up to the start of the string
                j = i
                step = 2 if enc != needle.encode() else 1
                while j - step >= 0 and blob[j - step] != 0:
                    j -= step
                targets.append(start + j)
                i = blob.find(enc, i + 1)
    targets = sorted(set(targets))
    for t in targets:
        print(f"string {t:#x}: {img.string_at(t)}")
    text = next(s for s in img.sections if s[4] == '.text')
    code = img.data[text[2]:text[2] + text[3]]
    # lea/mov reg,[rip+disp32]: scan for disp32 values that land on a target (cheap, no full disassembly)
    found = set()
    tset = set(targets)
    for k in range(len(code) - 7):
        if code[k] in (0x48, 0x4c) and code[k + 1] in (0x8d, 0x8b) and (code[k + 2] & 0xc7) == 0x05:
            disp = struct.unpack_from('<i', code, k + 3)[0]
            target = text[0] + k + 7 + disp
            if target in tset:
                found.add((img.function(text[0] + k)[0], text[0] + k, target))
    for fn, at, t in sorted(found):
        print(f"  ref at {at:#x} in function {fn:#x} -> {t:#x}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('rvas', nargs='*')
    ap.add_argument('--exe', default=EXE)
    ap.add_argument('--max', type=int, default=400)
    ap.add_argument('--xref-string')
    a = ap.parse_args()
    img = Image(a.exe)
    if a.xref_string:
        xref_string(img, a.xref_string)
    for r in a.rvas:
        disasm(img, int(r, 16), a.max)
