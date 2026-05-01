#!/usr/bin/env python3
"""
Phase 2 PoC: 静的ファイルサーバー + ARI REST プロキシ

ブラウザから /ari/* へのリクエストを Asterisk へ転送する。
CORS ヘッダーを付与するため、ブラウザの Same-Origin 制限を回避できる。
WebSocket 接続はブラウザから Asterisk に直接張る。

Usage:
  python serve.py
  Open http://localhost:8765/
"""

import http.server
import urllib.request
import urllib.error
import base64
import os
import sys

# ---- 設定 (serve.py は固定、ブラウザ側の設定と合わせること) ----
ASTERISK_HOST = "192.168.11.31"
ASTERISK_PORT = 8088
ARI_USER      = "confbridge_poc"
ARI_PASS      = "confbridge_poc_pass"
SERVE_PORT    = 8765
# ---------------------------------------------------------------

BASIC_AUTH = base64.b64encode(f"{ARI_USER}:{ARI_PASS}".encode()).decode()


class Handler(http.server.SimpleHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/ari/"):
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/ari/"):
            self._proxy("POST")
        else:
            self.send_error(405)

    def do_DELETE(self):
        if self.path.startswith("/ari/"):
            self._proxy("DELETE")
        else:
            self.send_error(405)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _proxy(self, method):
        url = f"http://{ASTERISK_HOST}:{ASTERISK_PORT}{self.path}"
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length > 0 else None

        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", f"Basic {BASIC_AUTH}")
        if body and "Content-Type" in self.headers:
            req.add_header("Content-Type", self.headers["Content-Type"])

        try:
            with urllib.request.urlopen(req) as r:
                data = r.read()
                self.send_response(r.status)
                self._cors()
                ct = r.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def log_message(self, fmt, *args):
        if self.path.startswith("/ari/"):
            print(f"[proxy] {self.command} {self.path}")
        else:
            super().log_message(fmt, *args)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    port = int(sys.argv[1]) if len(sys.argv) > 1 else SERVE_PORT
    server = http.server.ThreadingHTTPServer(("", port), Handler)
    print(f"[serve] Listening on http://localhost:{port}/")
    print(f"[serve] Open  http://localhost:{port}/index.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] Stopped.")
