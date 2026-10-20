"""Pipecat / Pipecat Flows: send each pool tool through pipecat's real LLM services at a local
capture server and record the tool exactly as it appears in the request body.

Pool tools are rebuilt as FunctionSchema(name, description, properties, required), which is
lossless: their parameters have no other top-level keys. Pipecat Flows hands nodes' functions to
the LLM the same way (pipecat_flows/manager.py builds a plain FunctionSchema), so the Flows run
uses the same code with pipecat-ai 1.4.0, the version pipecat-flows pins.

usage: probe_pipecat.py <pool_source_dir> <out_jsonl> [pipecat_src]
"""

import asyncio
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if len(sys.argv) > 3:
    sys.path.insert(0, sys.argv[3])

from anthropic import AsyncAnthropic  # noqa: E402
from capture import CaptureServer, record  # noqa: E402
from google.genai.types import HttpOptions  # noqa: E402
from pipecat.adapters.schemas.function_schema import FunctionSchema  # noqa: E402
from pipecat.adapters.schemas.tools_schema import ToolsSchema  # noqa: E402
from pipecat.processors.aggregators.llm_context import LLMContext  # noqa: E402
from pipecat.services.anthropic.llm import AnthropicLLMService  # noqa: E402
from pipecat.services.google.llm import GoogleLLMService  # noqa: E402
from pipecat.services.openai.llm import OpenAILLMService  # noqa: E402
from pipecat.services.openai.responses.llm import OpenAIResponsesHttpLLMService  # noqa: E402

POOL, OUT = sys.argv[1], sys.argv[2]
cap = CaptureServer()

# the WebSocket OpenAIResponsesLLMService uses the same adapter as the HTTP one captured here
SERVICES = {
    "openai-chat": lambda: OpenAILLMService(api_key="x", base_url=cap.url + "/v1"),
    "openai-responses": lambda: OpenAIResponsesHttpLLMService(api_key="x", base_url=cap.url + "/v1"),
    "anthropic": lambda: AnthropicLLMService(
        api_key="x", client=AsyncAnthropic(api_key="x", base_url=cap.url, max_retries=0)),
    "gemini": lambda: GoogleLLMService(api_key="x", http_options=HttpOptions(base_url=cap.url)),
}


async def main():
    services = {k: f() for k, f in SERVICES.items()}
    with open(OUT, "w") as out:
        for path in sorted(glob.glob(os.path.join(POOL, "**/*.json"), recursive=True)):
            t = json.load(open(path))
            p = t["parameters"]
            assert set(p) == {"type", "properties", "required"}, path
            fs = FunctionSchema(name=t["name"], description=t["description"],
                                properties=p["properties"], required=p["required"])
            for provider, llm in services.items():
                ctx = LLMContext(messages=[{"role": "user", "content": "hi"}],
                                 tools=ToolsSchema(standard_tools=[fs]))
                try:
                    await llm._process_context(ctx)
                except Exception:
                    pass  # the capture server answers 400
                record(out, cap, os.path.relpath(path, os.path.dirname(POOL)), provider)


asyncio.run(main())
