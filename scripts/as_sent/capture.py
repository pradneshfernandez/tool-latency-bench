"""Local HTTP server that records request bodies and answers 400, so SDK clients build and send
their real request without reaching any provider."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class CaptureServer:
    def __init__(self):
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(n)
                try:
                    body = json.loads(raw)
                except Exception:
                    body = raw.decode("utf-8", "replace")
                outer.requests.append({"path": self.path, "body": body})
                msg = json.dumps({"error": {"message": "capture", "type": "invalid_request_error",
                                            "code": 400, "status": "INVALID_ARGUMENT"}}).encode()
                self.send_response(400)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def take(self):
        r, self.requests = self.requests, []
        return r


def record(out, cap, tool_id, provider):
    """Write the single tool sent in the last captured request; fail loudly if there wasn't one."""
    reqs = cap.take()
    if len(reqs) != 1:
        raise RuntimeError(f"{tool_id} {provider}: expected 1 request, captured {len(reqs)}")
    body = reqs[0]["body"]
    tools = body.get("tools") if isinstance(body, dict) else None
    if not tools or len(tools) != 1:
        raise RuntimeError(f"{tool_id} {provider}: no single tool in request body")
    out.write(json.dumps({"tool_id": tool_id, "provider": provider, "endpoint": reqs[0]["path"],
                          "payload": tools[0]}, ensure_ascii=False) + "\n")
