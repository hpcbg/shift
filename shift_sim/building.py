"""
Building — a 1R1C space-heating thermal digital twin.

Physics (reference equations, independently verified in the test-suite — see
docs/IMPLEMENTATION_PLAN.md section 13; NOT calibrated to real buildings):

    Heat balance:  C * dT/dt = Q - UA_eff * (T - T_out)
    Controller:    Q = UA_eff*(S_eff - T_out) + Kp*(S_eff - T)
                   Q = clamp(Q, non_controllable_heat_kw, Pmax_eff)
    Integration:   T <- T + (Q - UA_eff*(T - T_out)) / C * dt      (explicit Euler)

At steady state the feed-forward term makes T == S_eff exactly.

Units: temperature deg C; power kW; energy kWh; C kWh/degC; UA kW/degC;
Kp kW/degC; dt hours; price EUR/MWh; cost_eur = energy_kwh * price / 1000.

The model is SPACE HEATING ONLY. Indoor air temperature is never treated as a
domestic-hot-water hygiene temperature; there is no hygiene floor. DHW/legionella
is a documented future extension.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .config import parse_clock

# control_status values
STATUS_NORMAL = "normal"
STATUS_PREHEATING = "preheating"
STATUS_REDUCING = "reducing"
STATUS_RECOVERING = "recovering"
STATUS_COMFORT = "comfort_constrained"
STATUS_NON_PARTICIPATING = "non_participating"
STATUS_WINDOW = "window_open"
STATUS_DOOR = "door_open"
STATUS_FAULT = "fault"


@dataclass
class Building:
    # ── identity & geometry (synthetic) ──────────────────────────────────────
    id: str
    name: str
    building_type: str                       # residential | office | school | municipal
    map_x: float
    map_y: float
    floor_area_m2: float
    represented_units: int
    represented_occupants: int

    # ── thermal parameters ───────────────────────────────────────────────────
    thermal_capacity_kwh_per_c: float        # C   [kWh/degC]
    heat_loss_coefficient_kw_per_c: float    # UA  [kW/degC]
    maximum_heat_power_kw: float             # Pmax [kW]
    non_controllable_heat_kw: float          # uncurtailable base heat [kW]

    # ── comfort / occupancy / participation ─────────────────────────────────
    initial_indoor_temperature_c: float
    scheduled_setpoint: float                # [deg C]
    comfort_minimum_c: float
    comfort_maximum_c: float
    setpoint_schedule: List[Dict[str, Any]]  # [{start_h,end_h,setpoint_c}]
    controllable_share: float                # 0..1
    flexibility_participation: bool

    # ── runtime state (reset by reset()) ─────────────────────────────────────
    current_indoor_temperature_c: float = 0.0
    window_state: bool = False
    door_state: bool = False
    current_heat_input: float = 0.0          # kW
    current_heat_loss: float = 0.0           # kW
    cumulative_thermal_energy: float = 0.0   # kWh
    cumulative_renewable_thermal_energy: float = 0.0  # kWh
    cumulative_cost: float = 0.0             # EUR
    available_flexibility: float = 0.0       # kW
    committed_flexibility: float = 0.0       # kW
    delivered_flexibility: float = 0.0       # kW (filled by KPI stage)
    thermal_state_of_charge: float = 0.0     # kWh  = C*(T - comfort_minimum)
    control_status: str = STATUS_NORMAL

    # parsed schedule cache
    _schedule: List[tuple] = field(default_factory=list, repr=False)

    # ── construction ─────────────────────────────────────────────────────────
    @classmethod
    def from_config(cls, d: Dict[str, Any]) -> "Building":
        b = cls(
            id=d["id"],
            name=d["name"],
            building_type=d["building_type"],
            map_x=float(d["map_x"]),
            map_y=float(d["map_y"]),
            floor_area_m2=float(d["floor_area_m2"]),
            represented_units=int(d["represented_units"]),
            represented_occupants=int(d["represented_occupants"]),
            thermal_capacity_kwh_per_c=float(d["thermal_capacity_kwh_per_c"]),
            heat_loss_coefficient_kw_per_c=float(d["heat_loss_coefficient_kw_per_c"]),
            maximum_heat_power_kw=float(d["maximum_heat_power_kw"]),
            non_controllable_heat_kw=float(d.get("non_controllable_heat_kw", 0.0)),
            initial_indoor_temperature_c=float(d["initial_indoor_temperature_c"]),
            scheduled_setpoint=float(d["scheduled_setpoint"]),
            comfort_minimum_c=float(d["comfort_minimum_c"]),
            comfort_maximum_c=float(d["comfort_maximum_c"]),
            setpoint_schedule=list(d.get("setpoint_schedule", []) or []),
            controllable_share=float(d["controllable_share"]),
            flexibility_participation=bool(d["flexibility_participation"]),
        )
        b._schedule = [
            (parse_clock(s["start"]), parse_clock(s["end"]), float(s["setpoint_c"]))
            for s in b.setpoint_schedule
        ]
        b.reset()
        return b

    def reset(self) -> None:
        """Restore initial conditions so a scenario can be run from scratch."""
        self.current_indoor_temperature_c = self.initial_indoor_temperature_c
        self.window_state = False
        self.door_state = False
        self.current_heat_input = 0.0
        self.current_heat_loss = 0.0
        self.cumulative_thermal_energy = 0.0
        self.cumulative_renewable_thermal_energy = 0.0
        self.cumulative_cost = 0.0
        self.available_flexibility = 0.0
        self.committed_flexibility = 0.0
        self.delivered_flexibility = 0.0
        self.thermal_state_of_charge = self._soc()
        self.control_status = STATUS_NORMAL

    # ── helpers ──────────────────────────────────────────────────────────────
    def scheduled_setpoint_at(self, hour: float) -> float:
        """Effective occupancy-driven setpoint at ``hour`` (defaults to the base)."""
        h = hour % 24.0
        for start, end, sp in self._schedule:
            if start <= end:
                if start <= h < end:
                    return sp
            else:
                if h >= start or h < end:
                    return sp
        return self.scheduled_setpoint

    def _soc(self) -> float:
        return self.thermal_capacity_kwh_per_c * (
            self.current_indoor_temperature_c - self.comfort_minimum_c
        )

    # ── physics ──────────────────────────────────────────────────────────────
    def step(self, s_eff: float, t_out: float, dt_h: float, kp: float,
             ua_multiplier: float, in_fault: bool,
             renewable_share: float, price_eur_per_mwh: float) -> float:
        """Advance the building one time step under target setpoint ``s_eff``.

        Returns the heat demand Q [kW] delivered this step. Updates temperature,
        cumulative energy/cost and the reported state fields.
        """
        ua_eff = self.heat_loss_coefficient_kw_per_c * ua_multiplier
        pmax_eff = 0.0 if in_fault else self.maximum_heat_power_kw
        t_in = self.current_indoor_temperature_c

        q = ua_eff * (s_eff - t_out) + kp * (s_eff - t_in)
        # clamp: never below the uncurtailable base heat, never above the cap.
        low = 0.0 if in_fault else min(self.non_controllable_heat_kw, pmax_eff)
        q = max(low, min(q, pmax_eff))

        loss = ua_eff * (t_in - t_out)
        self.current_indoor_temperature_c = t_in + (q - loss) / self.thermal_capacity_kwh_per_c * dt_h

        energy = q * dt_h
        self.current_heat_input = q
        self.current_heat_loss = loss
        self.cumulative_thermal_energy += energy
        self.cumulative_renewable_thermal_energy += energy * renewable_share
        self.cumulative_cost += energy * price_eur_per_mwh / 1000.0
        self.thermal_state_of_charge = self._soc()
        return q
