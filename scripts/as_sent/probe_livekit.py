"""LiveKit: rebuild every example tool as a real FunctionTool with the committed extractor (its
strict schema is derived from the Python signature, not from the pool JSON), send it through the
LiveKit plugins at a local capture server, and record the tool exactly as it appears in the request.

usage: probe_livekit.py <livekit_repo> <pool_source_dir> <out_jsonl>
"""

import asyncio
import glob
import json
import os
import sys

REPO, POOL, OUT = sys.argv[1:4]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "extract")]
for p in ("openai", "anthropic", "google"):
    sys.path.insert(0, os.path.join(REPO, f"livekit-plugins/livekit-plugins-{p}"))

import lt_extract_examples as ex  # noqa: E402
from capture import CaptureServer, record  # noqa: E402

# keep each tool object the extractor builds, in the order it emits their schemas
tools = []
_bind = ex.bind_if_method


def _recording_bind(fn, node):
    t = _bind(fn, node)
    tools.append(t)
    return t


ex.bind_if_method = _recording_bind
extracted = OUT + ".extract.jsonl"
ex.run("livekit", REPO, extracted)
records = [json.loads(line) for line in open(extracted)]
os.remove(extracted)
assert len(records) == len(tools), (len(records), len(tools))

# match to pool files by content, in order (identical tools in one file get _2, _3 suffixes)
pool = {}
for path in sorted(glob.glob(os.path.join(POOL, "**/*.json"), recursive=True)):
    t = json.load(open(path))
    key = json.dumps([t["file_path"], t["name"], t["description"], t["parameters"]], sort_keys=True)
    pool.setdefault(key, []).append(os.path.relpath(path, os.path.dirname(POOL)))

from google.genai import types as gtypes  # noqa: E402
from livekit.agents import APIConnectOptions  # noqa: E402
from livekit.agents.llm import ChatContext  # noqa: E402
from livekit.plugins import anthropic, google, openai  # noqa: E402

cap = CaptureServer()
NO_RETRY = APIConnectOptions(max_retry=0, timeout=10)
# plugin defaults otherwise; responses.LLM normally uses a WebSocket, same tool serialization
LLMS = {
    "openai-chat": lambda: openai.LLM(model="gpt-4.1", api_key="x", base_url=cap.url + "/v1"),
    "openai-responses": lambda: openai.responses.LLM(model="gpt-4.1", api_key="x", base_url=cap.url + "/v1",
                                                     use_websocket=False),
    "anthropic": lambda: anthropic.LLM(api_key="x", base_url=cap.url),
    "gemini": lambda: google.LLM(api_key="x", http_options=gtypes.HttpOptions(base_url=cap.url)),
}


async def main():
    llms = {k: f() for k, f in LLMS.items()}
    with open(OUT, "w") as out:
        for rec, tool in zip(records, tools):
            key = json.dumps([rec["file_path"], rec["name"], rec["description"], rec["parameters"]], sort_keys=True)
            if not pool.get(key):
                continue  # extracted but not in the pool (dropped as a duplicate)
            tool_id = pool[key].pop(0)
            for provider, lk in llms.items():
                ctx = ChatContext()
                ctx.add_message(role="user", content="hi")
                try:
                    async with lk.chat(chat_ctx=ctx, tools=[tool], conn_options=NO_RETRY) as stream:
                        async for _ in stream:
                            pass
                except Exception:
                    pass  # the capture server answers 400
                record(out, cap, tool_id, provider)
    left = [i for ids in pool.values() for i in ids]
    assert not left, f"pool tools not rebuilt: {left}"


asyncio.run(main())
