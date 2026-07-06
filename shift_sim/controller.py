"""
Control strategies for the SHIFT scenario: preheat, reduce, staggered recovery.

The controller turns committed flexibility (kW, decided by ``flexibility.py``)
into an effective setpoint trajectory per building per step. The committed kW is
translated to a setpoint drop via the documented heuristic and is fixed at the
moment the request is assessed.

It returns an *action* status (normal / preheating / reducing / recovering /
non_participating). The simulator overlays physical states (fault, window, door,
comfort_constrained) with higher display precedence.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .building import (Building, STATUS_NORMAL, STATUS_PREHEATING,
                       STATUS_REDUCING, STATUS_RECOVERING, STATUS_NON_PARTICIPATING)


class Controller:
    def __init__(self, config: Dict[str, Any], buildings: List[Building]) -> None:
        s = config.get("strategy", {})
        self.preheat_enabled = bool(s.get("preheat", True))
        self.preheat_boost = float(s.get("preheat_boost_c", 0.0))
        self.stagger_enabled = bool(s.get("stagger_recovery", True))
        self.ramp_h = float(s.get("recovery_ramp_minutes", 0.0)) / 60.0

        stagger_list = s.get("stagger_minutes_by_index", []) or []
        self.stagger_offset_h: Dict[str, float] = {}
        for i, b in enumerate(buildings):
            mins = stagger_list[i] if i < len(stagger_list) else 0.0
            self.stagger_offset_h[b.id] = float(mins) / 60.0

        # populated by the simulator once a request is assessed:
        self.committed_drop: Dict[str, float] = {}
        self.event_start_h: float = -1.0
        self.event_end_h: float = -1.0

    def set_reduction(self, drops: Dict[str, float], start_h: float, end_h: float) -> None:
        self.committed_drop = dict(drops)
        self.event_start_h = start_h
        self.event_end_h = end_h

    def effective_setpoint(self, b: Building, hour: float, base_setpoint: float,
                           price_offer_active: bool, request_active: bool):
        """Return (s_eff, action_status) for the SHIFT scenario.

        The effective comfort floor is min(comfort_minimum_c, base_setpoint): a
        reduction may only lower the setpoint, never raise a night-setback
        building above its own schedule.
        """
        floor = min(b.comfort_minimum_c, base_setpoint)

        # Preheat during a price offer (participating buildings only), capped at comfort_max.
        if price_offer_active and self.preheat_enabled and b.flexibility_participation:
            s = min(b.comfort_maximum_c, base_setpoint + self.preheat_boost)
            return s, STATUS_PREHEATING

        drop = self.committed_drop.get(b.id, 0.0)

        # Non-participating building while a request is active.
        if request_active and not b.flexibility_participation:
            return base_setpoint, STATUS_NON_PARTICIPATING

        # Active reduction window.
        if request_active and drop > 0.0:
            return max(floor, base_setpoint - drop), STATUS_REDUCING

        # Staggered recovery after the event.
        if drop > 0.0 and self.event_end_h >= 0.0 and hour >= self.event_end_h:
            offset = self.stagger_offset_h.get(b.id, 0.0) if self.stagger_enabled else 0.0
            hold_end = self.event_end_h + offset
            ramp_end = hold_end + self.ramp_h
            if hour < hold_end:
                return max(floor, base_setpoint - drop), STATUS_RECOVERING
            if self.ramp_h > 0.0 and hour < ramp_end:
                frac = (hour - hold_end) / self.ramp_h            # 0..1
                return max(floor, base_setpoint - drop * (1.0 - frac)), STATUS_RECOVERING

        return base_setpoint, STATUS_NORMAL
