"""Shared runner: builds requests, sends them one at a time, times them, writes the run folder."""

import csv
import json
import platform
import random
import shutil
import time
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import httpx
from loguru import logger

from tool_latency_bench.request import build_body, load_parts, new_nonce, part_paths
from tool_latency_bench.tools import ROOT, compact, load_tool, tool_tokens

FIELDS = ["block_id", "message_id", "condition", "tool_ids", "n_tools", "total_tool_tokens",
          "actionable_ms", "ttfat_ms", "outcome", "input_tokens", "cached_tokens", "error"]
WARMUPS = 3
MAX_TRIES = 6


def _empty_result(error=None) -> dict:
    return {"actionable_ms": None, "ttfat_ms": None, "outcome": None,
            "input_tokens": None, "cached_tokens": None, "error": error}


def send_once(client, url, headers, payload):
    """One streamed request; the clock starts just before sending.

    ttfat_ms: first delta carrying text content or a tool call (aiewf-eval's TTFAT).
    actionable_ms: first text token, or, if a tool call starts first, the moment that
    tool call is complete (finish_reason, or end of stream). The rest of the stream is
    still read to the end, outside the timing: it carries the usage chunk, and a stream
    closed early cannot go back to the connection pool, so the next request would pay
    for a new connection inside its timing.
    Returns (status, retry_after, result).
    """
    res = _empty_result()
    in_tool = False
    t0 = time.perf_counter()

    def ms():
        return (time.perf_counter() - t0) * 1000

    with client.stream("POST", url, content=payload, headers=headers) as r:
        if r.status_code != 200:
            body = r.read().decode(errors="replace")[:300]
            res["error"] = f"HTTP {r.status_code}: {body}"
            return r.status_code, r.headers.get("retry-after"), res
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                if res["actionable_ms"] is None and in_tool:
                    res["actionable_ms"], res["outcome"] = ms(), "tool"
                continue  # keep reading to the true end of the body
            chunk = json.loads(data)
            if chunk.get("error"):
                res["error"] = f"stream error: {json.dumps(chunk['error'])[:300]}"
                break
            if res["actionable_ms"] is None:
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if res["ttfat_ms"] is None and (delta.get("content") or delta.get("tool_calls")):
                        res["ttfat_ms"] = ms()
                    if delta.get("tool_calls"):
                        in_tool = True
                    elif delta.get("content") and not in_tool:
                        res["actionable_ms"], res["outcome"] = ms(), "text"
                    if in_tool and choice.get("finish_reason"):
                        res["actionable_ms"], res["outcome"] = ms(), "tool"
            usage = chunk.get("usage")
            if usage:
                res["input_tokens"] = usage.get("prompt_tokens")
                res["cached_tokens"] = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        if res["actionable_ms"] is None and in_tool and not res["error"]:
            res["actionable_ms"], res["outcome"] = ms(), "tool"
    if res["actionable_ms"] is None and not res["error"]:
        res["error"] = "stream ended with no text or tool call"
    return 200, None, res


def send(client, url, headers, body) -> dict:
    """Send with retries on 429. Never raises; failures go in the error field."""
    payload = compact(body).encode()
    for attempt in range(MAX_TRIES):
        try:
            status, retry_after, res = send_once(client, url, headers, payload)
        except Exception as e:
            return _empty_result(f"{type(e).__name__}: {e}"[:300])
        if status != 429:
            return res
        wait = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
        logger.warning(f"429, retry {attempt + 1}/{MAX_TRIES - 1} in {wait:.0f}s")
        time.sleep(wait)
    res["error"] = f"gave up after {MAX_TRIES} tries: {res['error']}"
    return res


def create_run_directory(benchmark_name: str, model: str, session: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    safe_model = model.replace("/", "_").replace(":", "_")
    run_dir = ROOT / "runs" / benchmark_name / f"{timestamp}_{safe_model}_{session}"
    run_dir.mkdir(parents=True)
    return run_dir


def run(cfg, model, service, base_url, api_key, session, blocks, pause, run_dir) -> dict:
    paths = part_paths(cfg.name)
    parts = load_parts(paths)
    (run_dir / "request_parts").mkdir()
    for name, src in paths.items():
        shutil.copy(src, run_dir / "request_parts" / name)

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    tokens = tool_tokens()
    seed = random.randrange(2**32)
    rng = random.Random(seed)
    msgs = parts["user_messages"]
    runtime = {
        "benchmark": cfg.name, "model": model, "service": service, "base_url": base_url,
        "session": session, "blocks": blocks, "pause_s": pause, "seed": seed,
        "started": datetime.now().astimezone().isoformat(timespec="seconds"),
        "request_parts": {k: str(v.relative_to(ROOT)) for k, v in paths.items()},
        "benchmark_info": cfg.info(),
        "versions": {"python": platform.python_version(),
                     **{p: version(p) for p in ("tool-latency-bench", "httpx", "tiktoken")}},
    }
    n_requests = n_errors = 0

    with httpx.Client(timeout=httpx.Timeout(60, connect=10)) as client, \
            open(run_dir / "results.csv", "w", newline="") as f:
        logger.info(f"warm-up: {WARMUPS} requests")
        for i in range(WARMUPS):
            res = send(client, url, headers,
                       build_body(parts, model, msgs[i % len(msgs)]["text"], [], new_nonce()))
            logger.debug(f"warm-up {i}: {res}")
            if res["error"]:
                logger.warning(f"warm-up error: {res['error']}")
            time.sleep(pause)

        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for b in range(blocks):
            msg = msgs[b % len(msgs)]
            sets = cfg.make_block(rng)
            order = rng.sample(cfg.conditions, len(cfg.conditions))
            line = []
            for cond in order:
                ids = sets[cond]
                body = build_body(parts, model, msg["text"], [load_tool(i) for i in ids], new_nonce())
                res = send(client, url, headers, body)
                n_requests += 1
                n_errors += bool(res["error"])
                row = {"block_id": b, "message_id": msg["id"], "condition": cond,
                       "tool_ids": ";".join(ids), "n_tools": len(ids),
                       "total_tool_tokens": sum(tokens[i] for i in ids), **res}
                w.writerow(row)
                f.flush()
                logger.debug(f"block {b} {cond}: {json.dumps({k: v for k, v in row.items() if k != 'tool_ids'})}")
                line.append(f"{cond}=" + ("ERR" if res["error"] else f"{res['actionable_ms']:.0f}"))
                if res["error"]:
                    logger.warning(f"block {b} {cond}: {res['error']}")
                time.sleep(pause)
            logger.info(f"block {b + 1}/{blocks} [{msg['id']}] " + " ".join(line))

    runtime.update(ended=datetime.now().astimezone().isoformat(timespec="seconds"),
                   n_requests=n_requests, n_errors=n_errors)
    (run_dir / "runtime.json").write_text(json.dumps(runtime, indent=1) + "\n")
    return runtime


def show_request(cfg, model: str) -> str:
    parts = load_parts(part_paths(cfg.name))
    sets = cfg.make_block(random.Random(0))
    cond = next(c for c in cfg.conditions if sets[c])
    ids = sets[cond]
    tokens = tool_tokens()
    body = build_body(parts, model, parts["user_messages"][0]["text"],
                      [load_tool(i) for i in ids], new_nonce())
    return (f"# {cfg.name}, condition {cond}: {len(ids)} tools, "
            f"{sum(tokens[i] for i in ids)} tool tokens (sample draw, seed 0)\n"
            + json.dumps(body, indent=2, ensure_ascii=False))
