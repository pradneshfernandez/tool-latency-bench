"""Assemble a request from the request-part files plus a tool set."""

import json
import uuid
from pathlib import Path

from tool_latency_bench.tools import ROOT

SHARED_PARTS_DIR = ROOT / "benchmarks" / "_shared" / "request_parts"
PART_FILES = ["system_prompt.txt", "history.json", "user_messages.json", "settings.json"]
# Only valid alongside a non-empty tools list, so they are dropped when there are no tools.
TOOL_ONLY_SETTINGS = ("tool_choice", "parallel_tool_calls")


def part_paths(benchmark_name: str) -> dict[str, Path]:
    """Each part comes from benchmarks/<name>/request_parts/ if present, else _shared."""
    own = ROOT / "benchmarks" / benchmark_name / "request_parts"
    return {f: (own / f if (own / f).exists() else SHARED_PARTS_DIR / f) for f in PART_FILES}


def load_parts(paths: dict[str, Path]) -> dict:
    return {
        "system_prompt": paths["system_prompt.txt"].read_text().strip(),
        "history": json.loads(paths["history.json"].read_text()),
        "user_messages": json.loads(paths["user_messages.json"].read_text()),
        "settings": json.loads(paths["settings.json"].read_text()),
    }


def new_nonce() -> str:
    return uuid.uuid4().hex


def build_body(parts: dict, model: str, user_text: str, tools: list, nonce: str) -> dict:
    messages = [{"role": "system", "content": f"[{nonce}]\n{parts['system_prompt']}"}]
    messages += parts["history"]
    messages.append({"role": "user", "content": user_text})
    body = {"model": model, "messages": messages}
    if tools:
        body["tools"] = tools
    for k, v in parts["settings"].items():
        if tools or k not in TOOL_ONLY_SETTINGS:
            body[k] = v
    return body
