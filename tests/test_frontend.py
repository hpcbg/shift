"""
Frontend tests.

Two layers:
  * static checks on web/dashboard.html (no stale prototype labels, fixed-height
    chart wrappers, disabled animation/resize loops, comfort-band Y range,
    numeric sanitiser);
  * API-contract checks on the data that feeds the charts (finite numbers,
    correct field names, six buildings) via the server helper.
"""

import math
import re
from pathlib import Path

import server

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "dashboard.html").read_text(encoding="utf-8")


# ── static HTML checks ────────────────────────────────────────────────────────

def test_no_old_prototype_labels():
    for stale in ("Flex 1", "Flex 2", "Flex 3"):
        assert stale not in HTML


def test_canvases_have_no_height_attribute():
    # height must come from the fixed-height CSS wrapper, never a canvas attribute
    assert not re.search(r"<canvas[^>]*\bheight\s*=", HTML)


def test_fixed_height_chart_wrappers_present():
    assert ".chart-canvas" in HTML
    for cls in ("cc-ctx", "cc-dem", "cc-tin"):
        assert cls in HTML
    # each wrapper pins a height
    assert re.search(r"\.cc-ctx\{height:\d+px", HTML)
    assert re.search(r"\.cc-dem\{height:\d+px", HTML)
    assert re.search(r"\.cc-tin\{height:\d+px", HTML)


def test_animation_and_resize_settings():
    assert "maintainAspectRatio:false" in HTML
    assert "animation:false" in HTML
    assert "resizeDelay:100" in HTML


def test_scrubber_uses_update_none_and_no_timers():
    assert 'update("none")' in HTML
    for banned in ("setInterval", "requestAnimationFrame", "ResizeObserver"):
        assert banned not in HTML


def test_numeric_sanitiser_and_comfort_band_range():
    # sanitiser maps non-finite values to null
    assert "Number.isFinite" in HTML and "function num(" in HTML
    # Y range derived from the selected building's comfort band
    assert "ymin:cmin-1" in HTML and "ymax:cmax+1" in HTML


# ── API-contract checks (data feeding the charts) ─────────────────────────────

def _finite_list(xs):
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in xs)


def test_api_six_buildings_and_names_available():
    out = server.build_response({})
    cfg = server.base_config()
    cfg_ids = [b["id"] for b in cfg["buildings"]]
    cfg_names = {b["name"] for b in cfg["buildings"]}

    assert set(out["shift"]["per_building"].keys()) == set(cfg_ids)
    assert {m["name"] for m in out["map_state"]} == cfg_names
    assert len(out["map_state"]) == 6
    # the six real names, never the prototype ones
    assert "Residential North" in cfg_names
    assert not (cfg_names & {"Flex 1", "Flex 2", "Flex 3"})


def test_api_temperature_and_setpoint_series_finite():
    out = server.build_response({})
    for scen in ("baseline", "shift"):
        for bid, series in out[scen]["per_building"].items():
            assert _finite_list(series["tin"]), f"{scen}/{bid} tin non-finite"
            assert _finite_list(series["q"]), f"{scen}/{bid} q non-finite"
            assert _finite_list(series["setpoint"]), f"{scen}/{bid} setpoint non-finite"
    assert _finite_list(out["shift"]["t_out"])
    assert _finite_list(out["shift"]["renewable_share"])
    assert _finite_list(out["shift"]["aggregated_demand_kw"])


def test_comfort_band_gives_finite_axis_range():
    cfg = server.base_config()
    for b in cfg["buildings"]:
        ymin = b["comfort_minimum_c"] - 1
        ymax = b["comfort_maximum_c"] + 1
        assert math.isfinite(ymin) and math.isfinite(ymax) and ymax > ymin
