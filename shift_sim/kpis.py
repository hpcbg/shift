"""
KPI computation — per building and portfolio.

All values are computed from the simulation. Cost uses the single formula
    cost_eur = energy_kwh * price_eur_per_mwh / 1000
No forecast-accuracy (NMAE) or fabricated confidence is reported here: the
baseline is an exact simulated counterfactual.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .simulator import SimResult
from .flexibility import ACCEPT, PARTIAL, REJECT
from .audit import SIGNAL


def _dt_h(res: SimResult) -> float:
    if len(res.hours) >= 2:
        return res.hours[1] - res.hours[0]
    return res.hours[0] if res.hours else 0.0


def _idx(hour: float, dt_h: float, n: int) -> int:
    if dt_h <= 0:
        return 0
    return max(0, min(n - 1, int(round(hour / dt_h))))


def _energy(series: List[float], dt_h: float) -> float:
    return sum(series) * dt_h


def _cost(q: List[float], price: List[float], dt_h: float) -> float:
    return sum(qi * pi for qi, pi in zip(q, price)) * dt_h / 1000.0


def compute_kpis(config: Dict[str, Any], base: SimResult, shift: SimResult) -> Dict[str, Any]:
    dt_h = _dt_h(shift)
    n = len(shift.hours)
    targets = config.get("kpi_targets", {})
    comfort_tol = float(targets.get("max_comfort_deviation_c", 1.0))
    rebound_minutes = float(config["simulation"].get("rebound_window_minutes", 120))

    # ── event & rebound windows (first peak/critical request) ────────────────
    if shift.request_windows:
        ev_start = shift.request_windows[0]["start_h"]
        ev_end = shift.request_windows[0]["end_h"]
    else:
        ev_start, ev_end = 0.0, 0.0
    i0 = _idx(ev_start, dt_h, n)
    i1 = _idx(ev_end, dt_h, n)
    r1 = _idx(ev_end + rebound_minutes / 60.0, dt_h, n)

    envelopes = shift.envelopes

    # ── per-building KPIs ────────────────────────────────────────────────────
    per_building: List[Dict[str, Any]] = []
    for b in shift.buildings:
        qb = base.per_building[b.id]["q"]
        qs = shift.per_building[b.id]["q"]
        tin_s = shift.per_building[b.id]["tin"]
        tin_b = base.per_building[b.id]["tin"]

        base_energy = _energy(qb, dt_h)
        ctrl_energy = _energy(qs, dt_h)
        base_cost = _cost(qb, base.price_eur_per_mwh, dt_h)
        ctrl_cost = _cost(qs, shift.price_eur_per_mwh, dt_h)
        renew_energy = sum(qi * ri for qi, ri in zip(qs, shift.renewable_share)) * dt_h

        # delivered flexibility: mean positive reduction over the event window
        if i1 > i0:
            deltas = [max(0.0, qb[i] - qs[i]) for i in range(i0, i1)]
            delivered = sum(deltas) / len(deltas)
        else:
            delivered = 0.0
        b.delivered_flexibility = delivered

        # comfort deviation: worst SHIFT-INDUCED breach below the effective floor,
        # measured beyond the baseline. The floor is
        # min(comfort_minimum_c, scheduled_setpoint) (night setbacks legitimately
        # sit below comfort_minimum_c); setback-recovery transients present in the
        # baseline are not attributed to SHIFT.
        comfort_dev = 0.0
        for idx_h, t in enumerate(tin_s):
            floor = min(b.comfort_minimum_c, b.scheduled_setpoint_at(shift.hours[idx_h]))
            shift_breach = max(0.0, floor - t)
            base_breach = max(0.0, floor - tin_b[idx_h])
            comfort_dev = max(comfort_dev, shift_breach - base_breach)
        comfort_dev = max(0.0, comfort_dev)

        env = envelopes.get(b.id, {})
        committed = float(env.get("committed_kw", 0.0))
        available = float(env.get("available_kw", 0.0))
        decision = env.get("decision", REJECT)

        per_building.append({
            "id": b.id, "name": b.name, "building_type": b.building_type,
            "baseline_thermal_energy_kwh": round(base_energy, 2),
            "controlled_thermal_energy_kwh": round(ctrl_energy, 2),
            "baseline_cost_eur": round(base_cost, 2),
            "controlled_cost_eur": round(ctrl_cost, 2),
            "customer_savings_eur": round(base_cost - ctrl_cost, 2),
            "renewable_thermal_energy_kwh": round(renew_energy, 2),
            "renewable_share_pct": round(100.0 * renew_energy / ctrl_energy, 1) if ctrl_energy > 0 else 0.0,
            "available_flexibility_kw": round(available, 2),
            "committed_flexibility_kw": round(committed, 2),
            "delivered_flexibility_kw": round(delivered, 2),
            "comfort_deviation_c": round(comfort_dev, 3),
            "event_response_ratio": round(delivered / committed, 3) if committed > 0 else 0.0,
            "responded": committed > 0,
            "decision": decision,
        })

    # ── portfolio KPIs ───────────────────────────────────────────────────────
    db = base.aggregated_demand_kw
    ds = shift.aggregated_demand_kw

    base_peak = max(db[i0:i1], default=0.0)
    ctrl_peak = max(ds[i0:i1], default=0.0)
    peak_red_kw = base_peak - ctrl_peak
    peak_red_pct = 100.0 * peak_red_kw / base_peak if base_peak > 0 else 0.0

    shifted = sum(max(0.0, db[i] - ds[i]) for i in range(i0, i1)) * dt_h
    rebound = sum(max(0.0, ds[i] - db[i]) for i in range(i1, r1)) * dt_h
    rebound_ratio = rebound / shifted if shifted > 1e-9 else 0.0

    # renewable thermal energy over the whole day
    ren_base = sum(qi * ri for qi, ri in zip(db, base.renewable_share)) * dt_h
    ren_shift = sum(qi * ri for qi, ri in zip(ds, shift.renewable_share)) * dt_h

    base_cost_total = _cost(db, base.price_eur_per_mwh, dt_h)
    ctrl_cost_total = _cost(ds, shift.price_eur_per_mwh, dt_h)

    # rebound peak vs contemporaneous baseline peak (item 13)
    rebound_peak_shift = max(ds[i1:r1], default=0.0)
    rebound_peak_base = max(db[i1:r1], default=0.0)

    counts = {ACCEPT: 0, PARTIAL: 0, REJECT: 0}
    for env in envelopes.values():
        counts[env.get("decision", REJECT)] = counts.get(env.get("decision", REJECT), 0) + 1

    comfort_violations = sum(1 for pb in per_building if pb["comfort_deviation_c"] > comfort_tol)

    total_events = len(shift.events_meta)
    logged = sum(1 for a in shift.audit if a["category"] == SIGNAL)
    audit_completeness = round(100.0 * min(logged, total_events) / total_events, 1) if total_events else 100.0

    portfolio = {
        "baseline_peak_demand_kw": round(base_peak, 2),
        "controlled_peak_demand_kw": round(ctrl_peak, 2),
        "peak_reduction_kw": round(peak_red_kw, 2),
        "peak_reduction_pct": round(peak_red_pct, 1),
        "shifted_thermal_energy_kwh": round(shifted, 2),
        "rebound_energy_kwh": round(rebound, 2),
        "rebound_ratio": round(rebound_ratio, 3),
        "rebound_peak_shift_kw": round(rebound_peak_shift, 2),
        "rebound_peak_baseline_kw": round(rebound_peak_base, 2),
        "renewable_thermal_energy_baseline_kwh": round(ren_base, 2),
        "renewable_thermal_energy_controlled_kwh": round(ren_shift, 2),
        "renewable_thermal_energy_increase_kwh": round(ren_shift - ren_base, 2),
        "baseline_cost_eur": round(base_cost_total, 2),
        "controlled_cost_eur": round(ctrl_cost_total, 2),
        "total_customer_savings_eur": round(base_cost_total - ctrl_cost_total, 2),
        "requests_accepted": counts[ACCEPT],
        "requests_partial": counts[PARTIAL],
        "requests_rejected": counts[REJECT],
        "comfort_violations": comfort_violations,
        "audit_completeness_pct": audit_completeness,
    }

    return {"per_building": per_building, "portfolio": portfolio}
