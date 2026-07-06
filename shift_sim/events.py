"""
Dynamic event model.

Supported (required) event types:
  PRICE_OFFER, PEAK_REDUCTION_REQUEST, CRITICAL_REQUEST,
  WINDOW_OPEN, DOOR_OPEN, SUBSTATION_FAULT, RESTORE
Optional: COLD_SNAP, NETWORK_CAPACITY_CHANGE.

Every event has a start hour and (except RESTORE) a duration, so ``active(hour)``
is well defined. Times in config are "HH:MM" strings (or numeric hours).

All event firings are timestamped and surfaced to the audit/event timeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import parse_clock

REQUIRED_TYPES = {
    "PRICE_OFFER", "PEAK_REDUCTION_REQUEST", "CRITICAL_REQUEST",
    "WINDOW_OPEN", "DOOR_OPEN", "SUBSTATION_FAULT", "RESTORE",
}
OPTIONAL_TYPES = {"COLD_SNAP", "NETWORK_CAPACITY_CHANGE"}
KNOWN_TYPES = REQUIRED_TYPES | OPTIONAL_TYPES

# event types that carry a portfolio/building flexibility request
REQUEST_TYPES = {"PEAK_REDUCTION_REQUEST", "CRITICAL_REQUEST"}


@dataclass
class Event:
    type: str
    raw: Dict[str, Any]
    start_h: float
    end_h: float
    received_h: float
    building_id: Optional[str] = None
    # convenience typed fields (populated where relevant)
    price_eur_per_mwh: Optional[float] = None
    renewable_share_override: Optional[float] = None
    heat_loss_multiplier: Optional[float] = None
    requested_reduction_kw: Optional[float] = None
    requested_reduction_percent: Optional[float] = None
    maximum_rebound_ratio: Optional[float] = None
    incentive_eur_per_mwh: float = 0.0
    priority: Optional[str] = None
    target: str = "portfolio"

    def active(self, hour: float) -> bool:
        return self.start_h <= hour < self.end_h

    @property
    def duration_h(self) -> float:
        return self.end_h - self.start_h


def _duration_hours(d: Dict[str, Any]) -> float:
    if "duration_minutes" in d and d["duration_minutes"] is not None:
        return float(d["duration_minutes"]) / 60.0
    if "duration_hours" in d and d["duration_hours"] is not None:
        return float(d["duration_hours"])
    return 0.0


def build_events(config: Dict[str, Any]) -> List[Event]:
    """Parse the config ``events`` list into typed, time-resolved Event objects."""
    events: List[Event] = []
    for d in config.get("events", []) or []:
        etype = str(d["type"]).upper()
        if etype not in KNOWN_TYPES:
            raise ValueError(f"Unknown event type: {etype}")

        start_h = parse_clock(d["start_time"]) if "start_time" in d else 0.0
        dur = _duration_hours(d)
        end_h = start_h + dur if dur > 0 else start_h
        received_h = parse_clock(d["received_time"]) if d.get("received_time") is not None else start_h

        ev = Event(
            type=etype,
            raw=d,
            start_h=start_h,
            end_h=end_h,
            received_h=received_h,
            building_id=d.get("building_id"),
            price_eur_per_mwh=(float(d["price_eur_per_mwh"]) if d.get("price_eur_per_mwh") is not None else None),
            renewable_share_override=(float(d["renewable_share_override"]) if d.get("renewable_share_override") is not None else None),
            heat_loss_multiplier=(float(d["heat_loss_multiplier"]) if d.get("heat_loss_multiplier") is not None else None),
            requested_reduction_kw=(float(d["requested_reduction_kw"]) if d.get("requested_reduction_kw") is not None else None),
            requested_reduction_percent=(float(d["requested_reduction_percent"]) if d.get("requested_reduction_percent") is not None else None),
            maximum_rebound_ratio=(float(d["maximum_rebound_ratio"]) if d.get("maximum_rebound_ratio") is not None else None),
            incentive_eur_per_mwh=float(d.get("customer_incentive_eur_per_mwh", 0.0) or 0.0),
            priority=d.get("priority"),
            target=str(d.get("target", "portfolio")),
        )
        events.append(ev)
    events.sort(key=lambda e: (e.start_h, e.type))
    return events


class EventManager:
    """Query helper over the parsed events for a single simulation."""

    def __init__(self, events: List[Event]) -> None:
        self.events = events

    # --- environment overrides -------------------------------------------------
    def active_price_offer(self, hour: float) -> Optional[Event]:
        for e in self.events:
            if e.type == "PRICE_OFFER" and e.active(hour):
                return e
        return None

    def active_cold_snap_delta(self, hour: float) -> float:
        delta = 0.0
        for e in self.events:
            if e.type == "COLD_SNAP" and e.active(hour):
                delta += float(e.raw.get("delta_c", 0.0))
        return delta

    # --- per-building physical modifiers --------------------------------------
    def opening_multiplier(self, building_id: str, hour: float, default_mult: float,
                           window_states: Dict[str, bool], door_states: Dict[str, bool]) -> float:
        """UA multiplier from any active window/door event (or manual override state)."""
        mult = 1.0
        opened = False
        for e in self.events:
            if e.type in ("WINDOW_OPEN", "DOOR_OPEN") and e.building_id == building_id and e.active(hour):
                mult *= (e.heat_loss_multiplier or default_mult)
                opened = True
        # manual dashboard toggles (whole-day) if provided
        if not opened and window_states.get(building_id):
            mult *= default_mult
        if not opened and door_states.get(building_id):
            mult *= default_mult
        return mult

    def window_open(self, building_id: str, hour: float, manual: Dict[str, bool]) -> bool:
        if manual.get(building_id):
            return True
        return any(e.type == "WINDOW_OPEN" and e.building_id == building_id and e.active(hour)
                   for e in self.events)

    def door_open(self, building_id: str, hour: float, manual: Dict[str, bool]) -> bool:
        if manual.get(building_id):
            return True
        return any(e.type == "DOOR_OPEN" and e.building_id == building_id and e.active(hour)
                   for e in self.events)

    def in_fault(self, building_id: str, hour: float) -> bool:
        return any(e.type == "SUBSTATION_FAULT" and e.building_id == building_id and e.active(hour)
                   for e in self.events)

    # --- flexibility requests --------------------------------------------------
    def active_request(self, hour: float) -> Optional[Event]:
        """The active peak/critical request, if any (critical takes precedence)."""
        best = None
        for e in self.events:
            if e.type in REQUEST_TYPES and e.active(hour):
                if best is None or (e.type == "CRITICAL_REQUEST" and best.type != "CRITICAL_REQUEST"):
                    best = e
        return best

    def requests(self) -> List[Event]:
        return [e for e in self.events if e.type in REQUEST_TYPES]

    def price_offers(self) -> List[Event]:
        return [e for e in self.events if e.type == "PRICE_OFFER"]
