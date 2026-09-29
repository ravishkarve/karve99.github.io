"""Minimal local web server: serves the dashboard and answers API calls.

    bbnoise serve --port 8000     ->  http://localhost:8000/

The dashboard uses this server when it is available (fast native NumPy) and
falls back to running the package in the browser with Pyodide otherwise
(e.g. on GitHub Pages).
"""
from __future__ import annotations

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .webapi import API

WEB_ROOT = Path(__file__).resolve().parent.parent


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter
        pass

    def do_GET(self):
        if self.path.startswith("/api/ping"):
            return self._send(json.dumps({"ok": True, "server": "bbnoise"}))
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_error(404)
            return
        fn = self.path[len("/api/"):].split("?")[0]
        if fn not in API:
            self.send_error(404, f"unknown API function {fn}")
            return
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode() if n else "[]"
        args = json.loads(body or "[]")
        if not isinstance(args, list):
            args = [args]
        args = [a if isinstance(a, str) else json.dumps(a) for a in args]
        self._send(API[fn](*args))

    def _send(self, text):
        data = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(port=8000, host="127.0.0.1", root=None):
    handler = partial(Handler, directory=str(root or WEB_ROOT))
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"bbnoise dashboard on http://{host}:{port}/  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
