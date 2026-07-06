from shift_sim.events import build_events, EventManager, REQUIRED_TYPES

ALL_TYPES_CONFIG = {
    "events": [
        {"type": "PRICE_OFFER", "received_time": "13:30", "start_time": "14:00",
         "duration_minutes": 180, "price_eur_per_mwh": 30.0,
         "renewable_share_override": 0.8, "target": "portfolio"},
        {"type": "PEAK_REDUCTION_REQUEST", "received_time": "17:30", "start_time": "18:00",
         "duration_minutes": 120, "requested_reduction_kw": 40.0,
         "maximum_rebound_ratio": 0.8, "target": "portfolio"},
        {"type": "CRITICAL_REQUEST", "start_time": "20:00", "duration_minutes": 30,
         "requested_reduction_kw": 15.0, "priority": "high", "target": "portfolio"},
        {"type": "WINDOW_OPEN", "building_id": "b1", "start_time": "18:00",
         "duration_minutes": 90, "heat_loss_multiplier": 1.9},
        {"type": "DOOR_OPEN", "building_id": "b2", "start_time": "08:00",
         "duration_minutes": 30, "heat_loss_multiplier": 1.5},
        {"type": "SUBSTATION_FAULT", "building_id": "b3", "start_time": "09:00",
         "duration_minutes": 60},
        {"type": "RESTORE", "start_time": "10:00", "target": "portfolio",
         "reason": "manual override cleared"},
    ]
}


def test_all_required_types_parse():
    events = build_events(ALL_TYPES_CONFIG)
    seen = {e.type for e in events}
    assert REQUIRED_TYPES.issubset(seen)


def test_windows_and_fault_active_at_right_times():
    em = EventManager(build_events(ALL_TYPES_CONFIG))
    assert em.active_price_offer(15.0) is not None
    assert em.active_price_offer(20.0) is None
    assert em.window_open("b1", 18.5, {}) is True
    assert em.window_open("b1", 20.0, {}) is False
    assert em.in_fault("b3", 9.5) is True
    assert em.in_fault("b3", 11.0) is False


def test_opening_multiplier_and_requests():
    em = EventManager(build_events(ALL_TYPES_CONFIG))
    mult = em.opening_multiplier("b1", 18.5, 1.9, {}, {})
    assert mult == 1.9
    assert len(em.requests()) == 2
    # critical takes precedence when both overlap at 20:00
    assert em.active_request(20.1).type == "CRITICAL_REQUEST"


def test_unknown_type_raises():
    import pytest
    with pytest.raises(ValueError):
        build_events({"events": [{"type": "NONSENSE", "start_time": "10:00"}]})
