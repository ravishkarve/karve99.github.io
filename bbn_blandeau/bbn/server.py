"""Local dashboard server: static files plus the JSON API (the dashboard can also run fully in
the browser through Pyodide)."""
from __future__ import annotations

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import webapi

ROOT = Path(__file__).resolve().parent.parent


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):                                        # noqa: N802
        if self.path.startswith("/api/ping"):
            data = b'{"server": "bbn"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def do_POST(self):                                       # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"[]")
        fn = {"/api/run": lambda b: webapi.run(b[0]),
              "/api/parse_table": lambda b: webapi.parse_table(b[0], b[1]),
              "/api/template": lambda b: webapi.template(b[0])}.get(self.path)
        out = fn(body) if fn else json.dumps({"ok": False, "error": "unknown endpoint"})
        data = out.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(port=8000, host="127.0.0.1"):
    httpd = ThreadingHTTPServer((host, port), partial(Handler, directory=str(ROOT)))
    print(f"dashboard at http://{host}:{port}/")
    httpd.serve_forever()
