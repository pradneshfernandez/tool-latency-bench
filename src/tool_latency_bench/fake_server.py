"""Fake OpenAI-compatible streaming server for dry runs, no API key needed.

Simulated latency grows with the request size, so tools visibly add delay:
first chunk after BASE_S + PER_KTOKEN_S per 1000 input tokens (rough chars/4),
times log-normal noise. With tools (and tool_choice not "none"), it calls the first tool
60% of the time. Some text answers start with a <think> block in `content`, and a small
share of requests get a 429, to exercise those paths in the runner.
"""

import json
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_S = 0.15
PER_KTOKEN_S = 0.04
NOISE_SIGMA = 0.15
TOKEN_GAP_S = 0.01
RATE_LIMIT_SHARE = 0.03
THINK_SHARE = 0.1


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def write_event(self, data: str):
        raw = f"data: {data}\n\n".encode()
        self.wfile.write(f"{len(raw):x}\r\n".encode() + raw + b"\r\n")
        self.wfile.flush()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        if random.random() < RATE_LIMIT_SHARE:
            msg = b'{"error":{"message":"rate limited"}}'
            self.send_response(429)
            self.send_header("Retry-After", "1")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        body = json.loads(raw)
        prompt_tokens = len(raw) // 4
        tools = body.get("tools") or []

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        base = {"id": "fake", "object": "chat.completion.chunk", "model": body["model"]}

        def send(delta, finish=None):
            self.write_event(json.dumps(
                {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}))

        time.sleep((BASE_S + PER_KTOKEN_S * prompt_tokens / 1000)
                   * random.lognormvariate(0, NOISE_SIGMA))
        send({"role": "assistant", "content": ""})
        if tools and body.get("tool_choice") != "none" and random.random() < 0.6:
            fn = tools[0]["function"]["name"]
            send({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                  "function": {"name": fn, "arguments": ""}}]})
            for part in ['{"', 'x":', ' "', 'y"}']:
                time.sleep(TOKEN_GAP_S)
                send({"tool_calls": [{"index": 0, "function": {"arguments": part}}]})
            send({}, "tool_calls")
        else:
            words = ["Sure", ",", " I", " can", " help", "."]
            if random.random() < THINK_SHARE:
                words = ["<think>", "The user", " asks.", "</think>", "\n"] + words
            for word in words:
                send({"content": word})
                time.sleep(TOKEN_GAP_S)
            send({}, "stop")
        self.write_event(json.dumps({**base, "choices": [], "usage": {
            "prompt_tokens": prompt_tokens, "completion_tokens": 6,
            "total_tokens": prompt_tokens + 6, "prompt_tokens_details": {"cached_tokens": 0}}}))
        self.write_event("[DONE]")
        self.wfile.write(b"0\r\n\r\n")


def start() -> str:
    """Start the server on a free local port in a background thread; returns its base_url."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/v1"
