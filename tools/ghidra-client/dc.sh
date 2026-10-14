#!/usr/bin/env bash
# Decompile functions by RVA through GhidraMCP: tools/ghidra-client/dc.sh <rva> [<rva>...]
# Saves analysis/decomp/<rva>.c and prints it.
cd "$(dirname "$0")/../.."
for a in "$@"; do
    a=${a#0x}
    timeout 600 uv run -q --with mcp python tools/ghidra-client/gq.py decompile_function_by_address \
        address=$(printf '0x%x' $((0x140000000 + 0x$a))) 2>&1 |
        python3 -c 'import json,sys; t=sys.stdin.read()
try:
    d=json.loads(t); print("// " + d["function"]["name"] + " @ " + d["function"]["address"]); print(d["code"])
except Exception: print(t)' > analysis/decomp/$a.c
    cat analysis/decomp/$a.c
done
