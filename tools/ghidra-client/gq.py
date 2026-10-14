"""Call GhidraMCP tools from the shell (the server runs headless with --transport streamable-http).

    uv run --with mcp python tools/ghidra-client/gq.py list
    uv run --with mcp python tools/ghidra-client/gq.py <tool> key=value ...
"""
import asyncio, json, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8081/mcp"

async def main():
    async with streamable_http_client(URL) as streams:
        r, w = streams[0], streams[1]
        async with ClientSession(r, w) as s:
            await s.initialize()
            if sys.argv[1] == "list":
                for t in (await s.list_tools()).tools:
                    props = list((getattr(t, "input_schema", None) or {}).get("properties", {}))
                    print(f"{t.name}({', '.join(props)}): {(t.description or '').splitlines()[0][:100]}")
                return
            args = {}
            for a in sys.argv[2:]:
                k, v = a.split("=", 1)
                try:
                    v = json.loads(v)
                except ValueError:
                    pass
                args[k] = v
            res = await s.call_tool(sys.argv[1], args)
            for c in res.content:
                print(getattr(c, "text", c))

asyncio.run(main())
