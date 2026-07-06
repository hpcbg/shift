"""
Simulator — deterministic, one-shot clock loop.

Baseline and SHIFT run the same engine over the same config. Physical events
(window/door/fault, cold snap) apply to both; only the control response
(preheat / reduce / stagger) differs. ``run_simulation`` runs the baseline first,
then the SHIFT scenario (using the baseline demand to resolve percent requests),
and finally computes KPIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional

from . import flexibility as flex
from .audit import AuditLog, SIGNAL, DECISION, COMMAND, OUTCOME
from .building import (Building, STATUS_NORMAL, STATUS_FAULT, STATUS_WINDOW,
                       STATUS_DOOR, STATUS_COMFORT, STATUS_REDUCING)
from .config import parse_datetime
from .controller import Controller
from .events import EventManager, build_events, Event
from .profiles import Profiles
from .scenario import ScenarioDef, SHIFT


@dataclass
class SimResult:
    scenario: str
    hours: List[float]
    timestamps: List[str]
    t_out: List[float]
    renewable_share: List[float]
    price_eur_per_mwh: List[float]
    aggregated_demand_kw: List[float]
    per_building: Dict[str, Dict[str, List]]   # id -> {tin, q, status, setpoint}
    buildings: List[Building]
    envelopes: Dict[str, Any] = field(default_factory=dict)
    audit: List[Dict[str, Any]] = field(default_factory=list)
    request_windows: List[Dict[str, float]] = field(default_factory=list)
    events_meta: List[Dict[str, Any]] = field(default_factory=list)


class Simulator:
    def __init__(self, config: Dict[str, Any], scenario: ScenarioDef) -> None:
        self.config = config
        self.scenario = scenario
        self.profiles = Profiles(config)

        self.buildings: List[Building] = [Building.from_config(b) for b in config["buildings"]]
        self.by_id = {b.id: b for b in self.buildings}

        self.events: List[Event] = build_events(config)
        self.em = EventManager(self.events)
        self.controller = Controller(config, self.buildings)

        sim = config["simulation"]
        self.start_dt = parse_datetime(sim["start_time"])
        self.horizon_h = float(sim.get("horizon_hours", 24))
        self.dt_min = float(sim.get("time_step_minutes", 2))
        self.dt_h = self.dt_min / 60.0
        self.kp = float(config.get("controller", {}).get("kp_kw_per_c", 6.0))
        self.default_opening = float(config.get("controller", {}).get("default_opening_multiplier", 1.9))

        # manual dashboard toggles (whole-day), from overrides
        self.manual_window: Dict[str, bool] = {}
        self.manual_door: Dict[str, bool] = {}

        self.audit = AuditLog()
        self._assessed = False

    # ── environment for a given hour, applying event overrides ────────────────
    def _env(self, hour: float):
        t_out = self.profiles.outdoor_temp_c(hour) + self.em.active_cold_snap_delta(hour)
        renewable = self.profiles.renewable_share(hour)
        price = self.profiles.price_eur_per_mwh(hour)
        offer = self.em.active_price_offer(hour)
        if offer is not None:
            if offer.price_eur_per_mwh is not None:
                price = offer.price_eur_per_mwh
            if offer.renewable_share_override is not None:
                renewable = offer.renewable_share_override
        return t_out, renewable, price

    def _log_signals(self) -> None:
        """Record one audit signal per configured event (ensures completeness)."""
        for e in self.events:
            ts = (self.start_dt + timedelta(hours=e.start_h)).strftime("%Y-%m-%d %H:%M")
            self.audit.add(
                timestamp=ts, hour=e.start_h, category=SIGNAL,
                actor="network operator" if e.type in ("PRICE_OFFER", "PEAK_REDUCTION_REQUEST",
                                                        "CRITICAL_REQUEST", "RESTORE") else "environment",
                message=f"{e.type} activated",
                building_id=e.building_id or "",
                values={k: v for k, v in e.raw.items() if k != "type"},
            )

    def _assess_request(self, req: Event, hour: float, t_out: float,
                        baseline_demand_at_start: float) -> None:
        """Assess, allocate and decide a flexibility request (SHIFT only)."""
        setpoints: Dict[str, float] = {}
        availables: Dict[str, float] = {}
        for b in self.buildings:
            sp = b.scheduled_setpoint_at(hour)
            setpoints[b.id] = sp
            mult = self.em.opening_multiplier(b.id, hour, self.default_opening,
                                              self.manual_window, self.manual_door)
            in_fault = self.em.in_fault(b.id, hour)
            if in_fault:
                availables[b.id] = 0.0
            else:
                availables[b.id] = flex.assess_available_kw(b, sp, t_out, mult, req.duration_h)

        # resolve the requested reduction (kW or percent of baseline demand at start)
        if req.requested_reduction_kw is not None:
            requested_kw = req.requested_reduction_kw
        elif req.requested_reduction_percent is not None:
            requested_kw = req.requested_reduction_percent / 100.0 * baseline_demand_at_start
        else:
            requested_kw = 0.0

        envelopes = flex.allocate(self.buildings, requested_kw, availables, setpoints)

        drops: Dict[str, float] = {}
        for b in self.buildings:
            env = envelopes[b.id]
            b.available_flexibility = env.available_kw
            b.committed_flexibility = env.committed_kw
            drops[b.id] = env.expected_delta_t_c
            ts = (self.start_dt + timedelta(hours=hour)).strftime("%Y-%m-%d %H:%M")
            self.audit.add(
                timestamp=ts, hour=hour, category=DECISION, actor="SHIFT controller",
                message=f"{env.decision.upper()} for {b.name}: {env.reason}",
                building_id=b.id,
                values={"available_kw": env.available_kw, "committed_kw": env.committed_kw,
                        "requested_share_kw": env.fair_target_kw,
                        "expected_delta_t_c": env.expected_delta_t_c,
                        "confidence_heuristic": env.confidence},
            )
            if env.committed_kw > 0:
                self.audit.add(
                    timestamp=ts, hour=hour, category=COMMAND, actor="SHIFT controller",
                    message=f"Reduce setpoint of {b.name} by ~{env.expected_delta_t_c:.2f} C",
                    building_id=b.id, values={"committed_kw": env.committed_kw},
                )
        self.controller.set_reduction(drops, req.start_h, req.end_h)
        self.envelopes = {bid: envelopes[bid] for bid in envelopes}
        self._assessed = True

    def _final_status(self, b: Building, action_status: str, base_setpoint: float,
                      window: bool, door: bool, in_fault: bool) -> str:
        if in_fault:
            return STATUS_FAULT
        # comfort floor only binds up to the current scheduled setpoint (setbacks
        # legitimately sit below comfort_minimum_c).
        floor = min(b.comfort_minimum_c, base_setpoint)
        if b.current_indoor_temperature_c < floor - 0.05:
            return STATUS_COMFORT
        if window:
            return STATUS_WINDOW
        if door:
            return STATUS_DOOR
        return action_status

    def run(self, baseline_demand: Optional[List[float]] = None) -> SimResult:
        for b in self.buildings:
            b.reset()
        self.audit = AuditLog()
        self._assessed = False
        self.envelopes = {}

        is_shift = self.scenario.apply_control
        if is_shift:
            self._log_signals()

        steps = int(round(self.horizon_h / self.dt_h))
        hours: List[float] = []
        timestamps: List[str] = []
        t_out_s: List[float] = []
        ren_s: List[float] = []
        price_s: List[float] = []
        agg: List[float] = []
        per: Dict[str, Dict[str, List]] = {b.id: {"tin": [], "q": [], "status": [], "setpoint": []}
                                           for b in self.buildings}

        # index of the event-start step, for baseline demand lookup
        req = self.em.requests()[0] if self.em.requests() else None

        for i in range(steps):
            hour = i * self.dt_h
            now = self.start_dt + timedelta(hours=hour)
            t_out, renewable, price = self._env(hour)

            # SHIFT: assess at the first step the request becomes active.
            if is_shift and req is not None and not self._assessed and req.active(hour):
                b_demand = 0.0
                if baseline_demand is not None and i < len(baseline_demand):
                    b_demand = baseline_demand[i]
                self._assess_request(req, hour, t_out, b_demand)

            price_offer_active = self.em.active_price_offer(hour) is not None
            request_active = req.active(hour) if req is not None else False

            total = 0.0
            for b in self.buildings:
                base_sp = b.scheduled_setpoint_at(hour)
                window = self.em.window_open(b.id, hour, self.manual_window)
                door = self.em.door_open(b.id, hour, self.manual_door)
                in_fault = self.em.in_fault(b.id, hour)
                mult = self.em.opening_multiplier(b.id, hour, self.default_opening,
                                                  self.manual_window, self.manual_door)

                if is_shift:
                    s_eff, action = self.controller.effective_setpoint(
                        b, hour, base_sp, price_offer_active, request_active)
                else:
                    s_eff, action = base_sp, STATUS_NORMAL

                q = b.step(s_eff, t_out, self.dt_h, self.kp, mult, in_fault,
                           renewable, price)
                b.control_status = self._final_status(b, action, base_sp, window, door, in_fault)
                b.window_state, b.door_state = window, door

                per[b.id]["tin"].append(round(b.current_indoor_temperature_c, 3))
                per[b.id]["q"].append(round(q, 3))
                per[b.id]["status"].append(b.control_status)
                per[b.id]["setpoint"].append(round(s_eff, 3))
                total += q

            hours.append(round(hour, 4))
            timestamps.append(now.strftime("%Y-%m-%d %H:%M"))
            t_out_s.append(round(t_out, 3))
            ren_s.append(round(renewable, 4))
            price_s.append(round(price, 3))
            agg.append(round(total, 3))

        # log restoration outcome (SHIFT)
        if is_shift and req is not None:
            ts = (self.start_dt + timedelta(hours=req.end_h)).strftime("%Y-%m-%d %H:%M")
            self.audit.add(timestamp=ts, hour=req.end_h, category=OUTCOME,
                           actor="SHIFT controller",
                           message="Event ended; staggered recovery to normal operation",
                           values={})

        request_windows = [{"start_h": e.start_h, "end_h": e.end_h, "type": e.type}
                           for e in self.em.requests()]
        events_meta = [{"type": e.type, "start_h": e.start_h, "end_h": e.end_h,
                        "building_id": e.building_id or "", "target": e.target}
                       for e in self.events]

        return SimResult(
            scenario=self.scenario.name, hours=hours, timestamps=timestamps,
            t_out=t_out_s, renewable_share=ren_s, price_eur_per_mwh=price_s,
            aggregated_demand_kw=agg, per_building=per, buildings=self.buildings,
            envelopes={bid: vars(env) for bid, env in self.envelopes.items()},
            audit=self.audit.to_list(), request_windows=request_windows,
            events_meta=events_meta,
        )


def run_simulation(config: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run baseline + SHIFT and compute KPIs. Returns a JSON-safe dict.

    ``overrides`` may carry manual dashboard toggles under keys
    ``manual_window`` / ``manual_door`` (dict of building_id -> bool).
    """
    from .kpis import compute_kpis  # local import to avoid a cycle

    overrides = overrides or {}

    base_sim = Simulator(config, ScenarioDef.baseline())
    base_res = base_sim.run()

    shift_sim = Simulator(config, ScenarioDef.shift())
    shift_sim.manual_window = dict(overrides.get("manual_window", {}) or {})
    shift_sim.manual_door = dict(overrides.get("manual_door", {}) or {})
    shift_res = shift_sim.run(baseline_demand=base_res.aggregated_demand_kw)

    kpis = compute_kpis(config, base_res, shift_res)

    return {
        "baseline": _result_to_dict(base_res),
        "shift": _result_to_dict(shift_res),
        "per_building_kpis": kpis["per_building"],
        "portfolio_kpis": kpis["portfolio"],
        "envelopes": shift_res.envelopes,
        "audit": shift_res.audit,
        "map_state": _map_state(shift_res),
        "request_windows": shift_res.request_windows,
        "events": shift_res.events_meta,
    }


def _result_to_dict(r: SimResult) -> Dict[str, Any]:
    return {
        "scenario": r.scenario,
        "hours": r.hours,
        "timestamps": r.timestamps,
        "t_out": r.t_out,
        "renewable_share": r.renewable_share,
        "price_eur_per_mwh": r.price_eur_per_mwh,
        "aggregated_demand_kw": r.aggregated_demand_kw,
        "per_building": r.per_building,
    }


def _map_state(r: SimResult) -> List[Dict[str, Any]]:
    """Final per-building snapshot for the schematic map."""
    out = []
    for b in r.buildings:
        out.append({
            "id": b.id, "name": b.name, "building_type": b.building_type,
            "map_x": b.map_x, "map_y": b.map_y,
            "indoor_temperature_c": round(b.current_indoor_temperature_c, 2),
            "heat_demand_kw": round(b.current_heat_input, 2),
            "available_flexibility_kw": round(b.available_flexibility, 2),
            "committed_flexibility_kw": round(b.committed_flexibility, 2),
            "delivered_flexibility_kw": round(b.delivered_flexibility, 2),
            "control_status": b.control_status,
            "flexibility_participation": b.flexibility_participation,
        })
    return out
