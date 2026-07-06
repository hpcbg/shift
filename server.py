"""
SHIFT local HTTP server.

Serves the dashboard and exposes JSON endpoints backed by the pure-Python
simulation engine. Standard library only; no web framework.

Usage:
    python server.py
Then open http://localhost:8765

Endpoints:
    GET  /               -> dashboard.html
    GET  /chart.js       -> vendored Chart.js
    GET  /config         -> merged configuration (JSON)
    GET  /health         -> {status, config}
    POST /simulate       -> full baseline + SHIFT result, KPIs, audit, map state
    POST /flexibility/assess -> envelopes + decisions only
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict

from shift_sim.config import load_config, deep_merge, DEFAULT_CONFIG
from shift_sim.simulator import run_simulation

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
DASHBOARD = WEB_DIR / "dashboard.html"
CHART_JS = WEB_DIR / "chart.umd.js"
PORT = 8765


# ── engine-facing helpers (testable without HTTP) ─────────────────────────────

def base_config() -> Dict[str, Any]:
    return load_config()


def build_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides from a request payload and run the full simulation."""
    cfg = base_config()
    overrides = payload.get("overrides") or {}
    if overrides:
        cfg = deep_merge(cfg, overrides)
    manual = {
        "manual_window": payload.get("manual_window", {}) or {},
        "manual_door": payload.get("manual_door", {}) or {},
    }
    # apply per-building participation overrides if supplied
    part = payload.get("participation") or {}
    if part:
        for b in cfg["buildings"]:
            if b["id"] in part:
                b["flexibility_participation"] = bool(part[b["id"]])
    return run_simulation(cfg, manual)


def build_assessment(payload: Dict[str, Any]) -> Dict[str, Any]:
    full = build_response(payload)
    return {"envelopes": full["envelopes"],
            "portfolio_kpis": full["portfolio_kpis"],
            "audit": [a for a in full["audit"] if a["category"] in ("signal", "decision")]}


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence default access log
        pass

    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, mime: str) -> None:
        if not path.exists():
            self._json({"error": f"{path.name} not found"}, 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/dashboard.html"):
            self._file(DASHBOARD, "text/html; charset=utf-8")
        elif path == "/chart.js":
            self._file(CHART_JS, "application/javascript; charset=utf-8")
        elif path == "/config":
            try:
                self._json(base_config())
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 500)
        elif path == "/health":
            self._json({"status": "ok", "config": str(DEFAULT_CONFIG)})
        else:
            self._json({"error": "not found"}, 404)

    def _read(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            payload = self._read()
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"bad request: {e}"}, 400)
            return

        try:
            if path == "/simulate":
                self._json(build_response(payload))
            elif path in ("/flexibility/assess", "/assess"):
                self._json(build_assessment(payload))
            else:
                self._json({"error": "unknown endpoint"}, 404)
        except Exception as e:  # noqa: BLE001
            import traceback
            self._json({"error": str(e), "trace": traceback.format_exc()}, 500)


def make_server(port: int = PORT) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    server = make_server(PORT)
    url = f"http://localhost:{PORT}"
    print(f"""
==================================================
  SHIFT  local simulation server
  URL   : {url}
  Config: {DEFAULT_CONFIG}
  Stop  : Ctrl+C
  (synthetic simulator - not real Miesto Gijos data)
==================================================
""")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
