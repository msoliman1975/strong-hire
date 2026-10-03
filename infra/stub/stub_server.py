"""Placeholder for the STT and TTS services until P1 swaps in faster-whisper and Kokoro images.

Serves GET /health and returns 501 for the OpenAI-compatible audio routes.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NAME = os.environ.get("STUB_NAME", "stub")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "stub", "service": NAME})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        self._send(501, {"error": f"{NAME} is a stub until P1"})

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"{NAME} stub listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
