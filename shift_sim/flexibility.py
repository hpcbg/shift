"""
Flexibility assessment, portfolio allocation and the accept / partial / reject
decision.

The operator request is expressed in kW (or percent). It is NOT interpreted as a
fixed setpoint drop. The sequence is:

  1. assess each building's available reduction (kW);
  2. allocate the portfolio request across participating buildings;
  3. decide accept / partial / reject per building;
  4. derive a setpoint trajectory from committed kW (documented heuristic).

kW -> deg C heuristic (step 4):  setpoint_drop ~= committed_kw / UA_eff,
floored so the target stays at or above comfort_minimum_c. This is an explicit
modelling heuristic, NOT a physical identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .building import Building

# decisions
ACCEPT = "accept"
PARTIAL = "partial"
REJECT = "reject"


@dataclass
class Envelope:
    building_id: str
    available_kw: float
    committed_kw: float
    fair_target_kw: float
    expected_delta_t_c: float
    thermal_state_of_charge_kwh: float
    confidence: float          # heuristic simulator score (0..1), NOT calibrated
    decision: str
    reason: str


def assess_available_kw(b: Building, setpoint: float, t_out: float,
                        ua_multiplier: float, duration_h: float) -> float:
    """Available heat-power reduction (kW) a building can safely offer.

    Heuristic combining a steady-state term (reduced losses at a lower indoor
    temperature) and a stored-energy term (thermal inertia / preheat), scaled by
    the controllable share. Zero if the building does not participate.

        available = share * ( UA_eff * headroom  +  C * stored / duration )

    capped by the current nominal heat demand and Pmax.
    """
    if not b.flexibility_participation or b.controllable_share <= 0.0:
        return 0.0

    ua_base = b.heat_loss_coefficient_kw_per_c
    ua_eff = ua_base * ua_multiplier
    headroom = max(0.0, setpoint - b.comfort_minimum_c)                     # deg C
    stored = max(0.0, b.current_indoor_temperature_c - b.comfort_minimum_c)  # deg C above floor
    dur = max(0.25, duration_h)

    # Steady term uses the BASE UA so that an open window (higher ua_eff) never
    # inflates the offered flexibility; the opening only tightens the cap below.
    steady = ua_base * headroom
    inertia = b.thermal_capacity_kwh_per_c * stored / dur
    available = b.controllable_share * (steady + inertia)

    # cannot reduce more than the building is currently drawing (with any opening),
    # nor exceed Pmax.
    nominal = max(0.0, ua_eff * (setpoint - t_out))
    available = min(available, nominal, b.maximum_heat_power_kw)
    return max(0.0, available)


def setpoint_drop_for(committed_kw: float, b: Building, setpoint: float,
                      ua_multiplier: float = 1.0) -> float:
    """kW -> deg C heuristic. Returns a setpoint drop capped by comfort headroom."""
    ua_eff = b.heat_loss_coefficient_kw_per_c * ua_multiplier
    if ua_eff <= 1e-9 or committed_kw <= 0.0:
        return 0.0
    drop = committed_kw / ua_eff
    max_drop = max(0.0, setpoint - b.comfort_minimum_c)
    return min(drop, max_drop)


def allocate(buildings: List[Building], requested_kw: float,
             availables: Dict[str, float], setpoints: Dict[str, float]) -> Dict[str, Envelope]:
    """Allocate ``requested_kw`` across buildings proportionally to availability.

    Per-building decision:
      * reject  — not participating / in fault / zero available;
      * accept  — participates and available >= its fair (capacity-weighted) share;
      * partial — participates but comfort/window-limited below its fair share.
    """
    participating = [b for b in buildings if availables.get(b.id, 0.0) > 1e-9]
    total_available = sum(availables.get(b.id, 0.0) for b in participating)

    # capacity weight = share of controllable substation power among participants
    total_cap = sum(b.maximum_heat_power_kw * b.controllable_share for b in participating) or 1.0

    # proportional scaling: if the portfolio can over-deliver, scale everyone down.
    if total_available <= requested_kw or total_available <= 0.0:
        scale = 1.0
    else:
        scale = requested_kw / total_available

    envelopes: Dict[str, Envelope] = {}
    for b in buildings:
        avail = availables.get(b.id, 0.0)
        setpoint = setpoints.get(b.id, b.scheduled_setpoint)
        fair = requested_kw * (b.maximum_heat_power_kw * b.controllable_share) / total_cap

        if avail <= 1e-9:
            if not b.flexibility_participation:
                reason = "flexibility participation disabled"
            elif b.controllable_share <= 0.0:
                reason = "no controllable share"
            else:
                reason = "no usable flexibility (comfort/fault/opening)"
            envelopes[b.id] = Envelope(
                building_id=b.id, available_kw=0.0, committed_kw=0.0,
                fair_target_kw=round(fair, 3), expected_delta_t_c=0.0,
                thermal_state_of_charge_kwh=round(b.thermal_state_of_charge, 3),
                confidence=0.0, decision=REJECT, reason=reason,
            )
            continue

        committed = avail * scale
        if avail + 1e-6 >= fair:
            decision, reason = ACCEPT, "offer meets requested share"
        else:
            decision, reason = PARTIAL, "comfort/opening-limited below requested share"

        # confidence heuristic (0..1): backed by stored energy + headroom.
        # Explicitly a simulator score, not calibrated prediction confidence.
        headroom = max(1e-6, setpoint - b.comfort_minimum_c)
        soc_ratio = min(1.0, max(0.0, b.thermal_state_of_charge /
                                 (b.thermal_capacity_kwh_per_c * headroom + 1e-6)))
        confidence = round(0.5 * min(1.0, avail / max(committed, 1e-6)) + 0.5 * soc_ratio, 3)

        drop = setpoint_drop_for(committed, b, setpoint)
        envelopes[b.id] = Envelope(
            building_id=b.id, available_kw=round(avail, 3), committed_kw=round(committed, 3),
            fair_target_kw=round(fair, 3), expected_delta_t_c=round(drop, 3),
            thermal_state_of_charge_kwh=round(b.thermal_state_of_charge, 3),
            confidence=confidence, decision=decision, reason=reason,
        )
    return envelopes
