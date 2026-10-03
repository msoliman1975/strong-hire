"""Voice agent placeholder. P1 replaces this with the LiveKit Agents worker.

Until then it serves GET /health on VOICE_HEALTH_PORT (default 8081) so the compose stack and
its healthchecks work.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        ok = self.path == "/health"
        body = json.dumps({"status": "stub", "service": "voice"} if ok else {"error": "not found"})
        self.send_response(200 if ok else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    port = int(os.environ.get("VOICE_HEALTH_PORT", "8081"))
    print(f"voice agent stub listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), _Health).serve_forever()


if __name__ == "__main__":
    main()
