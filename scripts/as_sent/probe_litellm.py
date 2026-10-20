"""τ²-bench: tau2.utils.llm_utils passes [tool.openai_schema] unchanged to litellm.completion, so
send each pool tool through litellm (the version in tau2's uv.lock) at a local capture server.

usage: probe_litellm.py <pool_source_dir> <out_jsonl>
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capture import CaptureServer, record  # noqa: E402
import litellm  # noqa: E402

POOL, OUT = sys.argv[1], sys.argv[2]
cap = CaptureServer()

# provider -> (litellm model, api_base suffix, extra kwargs). tau2 routes gpt-5* models to the
# Responses API and adds allowed_openai_params for it (llm_utils._RESPONSES_BRIDGE_PARAMS).
ROUTES = {
    "openai-chat": ("openai/gpt-4.1", "/v1", {}),
    "openai-responses": ("openai/responses/gpt-5.2", "/v1", {"allowed_openai_params": ["tool_choice"]}),
    "anthropic": ("anthropic/claude-sonnet-4-5", "", {}),
    "gemini": ("gemini/gemini-2.5-flash", "", {}),
}

with open(OUT, "w") as out:
    for path in sorted(glob.glob(os.path.join(POOL, "**/*.json"), recursive=True)):
        t = json.load(open(path))
        schema = {"type": "function", "function": {k: t[k] for k in ("name", "description", "parameters")}}
        for provider, (model, suffix, extra) in ROUTES.items():
            try:
                litellm.completion(model=model, messages=[{"role": "user", "content": "hi"}],
                                   tools=[schema], tool_choice="auto", api_key="x",
                                   api_base=cap.url + suffix, num_retries=0, max_retries=0, **extra)
            except Exception:
                pass  # the capture server answers 400
            record(out, cap, os.path.relpath(path, os.path.dirname(POOL)), provider)
