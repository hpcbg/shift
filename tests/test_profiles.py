"""
Tests for the config-driven hourly outdoor-temperature profile and its
sinusoidal fallback.
"""

import copy
import math

import pytest

from shift_sim.config import load_config
from shift_sim.profiles import Profiles
from shift_sim.simulator import run_simulation


def _profiles():
    return Profiles(load_config())


# ── exact configured values ───────────────────────────────────────────────────
def test_exact_values_at_configured_hours():
    p = _profiles()
    assert p.outdoor_temp_c(0.0) == pytest.approx(-5.0)
    assert p.outdoor_temp_c(5.0) == pytest.approx(-6.9)
    assert p.outdoor_temp_c(15.0) == pytest.approx(-2.1)
    assert p.outdoor_temp_c(24.0) == pytest.approx(-5.0)


# ── linear interpolation ──────────────────────────────────────────────────────
def test_linear_interpolation_half_hours():
    p = _profiles()
    # 00:00 -5.0 -> 01:00 -5.4  => 00:30 = -5.2
    assert p.outdoor_temp_c(0.5) == pytest.approx(-5.2)
    # 14:00 -2.4 -> 15:00 -2.1   => 14:30 = -2.25
    assert p.outdoor_temp_c(14.5) == pytest.approx(-2.25)
    # 05:00 -6.9 -> 06:00 -7.1   => 05:30 = -7.0
    assert p.outdoor_temp_c(5.5) == pytest.approx(-7.0)


def test_interpolation_at_two_minute_steps_is_between_neighbours():
    p = _profiles()
    # between hour 10 (-5.5) and hour 11 (-4.7), values must stay within [-5.5, -4.7]
    lo, hi = -5.5, -4.7
    for k in range(0, 31):
        t = 10.0 + k * (2 / 60.0)
        v = p.outdoor_temp_c(t)
        assert lo - 1e-9 <= v <= hi + 1e-9


# ── bounds ────────────────────────────────────────────────────────────────────
def test_bounds_derived_correctly():
    p = _profiles()
    lo, hi = p.outdoor_temp_bounds()
    assert lo == pytest.approx(-7.1)
    assert hi == pytest.approx(-2.1)


# ── validation of invalid profiles ────────────────────────────────────────────
def _cfg_with_points(points):
    cfg = load_config()
    cfg["weather"] = {"profile_name": "test", "hourly_temperature_c": points}
    return cfg


def test_unordered_hours_rejected():
    with pytest.raises(ValueError):
        _profiles_from(_cfg_with_points([
            {"hour": 0, "value": -3.0}, {"hour": 5, "value": -5.0},
            {"hour": 3, "value": -4.0}, {"hour": 24, "value": -3.0}]))


def test_duplicate_hours_rejected():
    with pytest.raises(ValueError):
        _profiles_from(_cfg_with_points([
            {"hour": 0, "value": -3.0}, {"hour": 5, "value": -5.0},
            {"hour": 5, "value": -4.0}, {"hour": 24, "value": -3.0}]))


def test_non_finite_value_rejected():
    with pytest.raises(ValueError):
        _profiles_from(_cfg_with_points([
            {"hour": 0, "value": -3.0}, {"hour": 12, "value": float("nan")},
            {"hour": 24, "value": -3.0}]))


def test_missing_coverage_rejected():
    # does not start at 0
    with pytest.raises(ValueError):
        _profiles_from(_cfg_with_points([
            {"hour": 2, "value": -3.0}, {"hour": 24, "value": -3.0}]))
    # does not reach 24
    with pytest.raises(ValueError):
        _profiles_from(_cfg_with_points([
            {"hour": 0, "value": -3.0}, {"hour": 20, "value": -3.0}]))


def _profiles_from(cfg):
    return Profiles(cfg)


# ── sinusoidal fallback still supported ───────────────────────────────────────
def test_sinusoidal_fallback_when_hourly_absent():
    cfg = load_config()
    cfg["weather"] = {"coldest_c": -12.0, "coldest_hour": 5.0, "daily_swing_c": 8.0}
    p = Profiles(cfg)
    # minimum at coldest_hour == coldest_c
    assert p.outdoor_temp_c(5.0) == pytest.approx(-12.0, abs=1e-6)
    # warmest 12 h later == coldest_c + swing
    assert p.outdoor_temp_c(17.0) == pytest.approx(-4.0, abs=1e-6)
    assert p.outdoor_temp_bounds() == pytest.approx((-12.0, -4.0))


# ── whole-simulation properties ───────────────────────────────────────────────
def test_all_outdoor_values_finite_and_deterministic():
    cfg = load_config()
    a = run_simulation(copy.deepcopy(cfg))
    b = run_simulation(copy.deepcopy(cfg))
    assert a["shift"]["t_out"] == b["shift"]["t_out"]            # deterministic
    assert all(math.isfinite(v) for v in a["shift"]["t_out"])    # finite
    assert a["portfolio_kpis"] == b["portfolio_kpis"]
