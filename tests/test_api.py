"""
API tests. Exercises the engine-facing helpers directly, plus one live HTTP
round-trip against a threaded stdlib server.
"""

import json
import threading
import time
import urllib.error
import urllib.request

import server


def _get(url, data=None, method="GET", retries=25):
    """Request with a short readiness retry loop (robust on Windows)."""
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(
                url, data=data, method=method,
                headers={"Content-Type": "application/json"} if data is not None else {})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError:
            raise
        except (ConnectionResetError, ConnectionRefusedError, OSError) as e:
            last = e
            time.sleep(0.1)
    raise last


def test_build_response_shape():
    out = server.build_response({})
    assert "portfolio_kpis" in out and "per_building_kpis" in out
    assert "baseline" in out and "shift" in out
    assert "audit" in out and "map_state" in out
    assert len(out["map_state"]) == 6


def test_participation_override_forces_reject():
    out = server.build_response({"participation": {"res_north": False}})
    env = out["envelopes"]["res_north"]
    assert env["decision"] == "reject"


def test_manual_window_override_applies():
    # opening a window all day at a building must not increase its offered flexibility
    base = server.build_response({})
    with_win = server.build_response({"manual_window": {"business_centre": True}})
    assert with_win["envelopes"]["business_centre"]["available_kw"] <= \
        base["envelopes"]["business_centre"]["available_kw"] + 1e-6


def test_assessment_endpoint_helper():
    out = server.build_assessment({})
    assert "envelopes" in out and "portfolio_kpis" in out


def _serve(httpd):
    httpd.serve_forever()


def test_live_http_endpoints():
    httpd = server.make_server(port=0)          # ephemeral port avoids collisions
    port = httpd.server_address[1]
    t = threading.Thread(target=_serve, args=(httpd,), daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    try:
        assert _get(base + "/health")["status"] == "ok"
        assert len(_get(base + "/config")["buildings"]) == 6
        sim = _get(base + "/simulate", data=b"{}", method="POST")
        assert sim["portfolio_kpis"]["peak_reduction_kw"] > 0.0
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_bad_request_returns_400():
    httpd = server.make_server(port=0)
    port = httpd.server_address[1]
    t = threading.Thread(target=_serve, args=(httpd,), daemon=True)
    t.start()
    try:
        _get(f"http://127.0.0.1:{port}/health")   # wait until ready
        try:
            _get(f"http://127.0.0.1:{port}/simulate", data=b"not-json", method="POST")
            assert False, "expected HTTP 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()
