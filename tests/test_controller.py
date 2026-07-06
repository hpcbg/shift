from shift_sim.building import (Building, STATUS_PREHEATING, STATUS_REDUCING,
                                STATUS_RECOVERING, STATUS_NON_PARTICIPATING, STATUS_NORMAL)
from shift_sim.controller import Controller

CFG = {
    "strategy": {
        "preheat": True, "preheat_boost_c": 1.5, "stagger_recovery": True,
        "stagger_minutes_by_index": [0, 30], "recovery_ramp_minutes": 30,
    }
}

BASE = dict(
    id="b", name="B", building_type="residential", map_x=0, map_y=0,
    floor_area_m2=1000, represented_units=10, represented_occupants=20,
    thermal_capacity_kwh_per_c=8.0, heat_loss_coefficient_kw_per_c=1.0,
    maximum_heat_power_kw=60.0, non_controllable_heat_kw=1.0,
    initial_indoor_temperature_c=22.0, scheduled_setpoint=21.0,
    comfort_minimum_c=20.0, comfort_maximum_c=23.0, setpoint_schedule=[],
    controllable_share=0.6, flexibility_participation=True,
)


def make(**over):
    d = dict(BASE); d.update(over)
    return Building.from_config(d)


def test_preheat_capped_at_comfort_max():
    b = make(comfort_maximum_c=22.0)
    c = Controller(CFG, [b])
    s, status = c.effective_setpoint(b, 15.0, base_setpoint=21.0,
                                     price_offer_active=True, request_active=False)
    assert status == STATUS_PREHEATING
    assert s == 22.0   # 21 + 1.5 boost, capped at comfort_max 22.0


def test_non_participating_status_during_request():
    b = make(flexibility_participation=False)
    c = Controller(CFG, [b])
    s, status = c.effective_setpoint(b, 18.5, 21.0, price_offer_active=False, request_active=True)
    assert status == STATUS_NON_PARTICIPATING
    assert s == 21.0


def test_reduction_lowers_setpoint_by_drop():
    b = make()
    c = Controller(CFG, [b])
    c.set_reduction({"b": 0.8}, start_h=18.0, end_h=20.0)
    s, status = c.effective_setpoint(b, 18.5, 21.0, price_offer_active=False, request_active=True)
    assert status == STATUS_REDUCING
    assert abs(s - 20.2) < 1e-9


def test_reduction_floored_at_comfort_minimum():
    b = make(comfort_minimum_c=20.5)
    c = Controller(CFG, [b])
    c.set_reduction({"b": 5.0}, start_h=18.0, end_h=20.0)  # huge drop
    s, _ = c.effective_setpoint(b, 18.5, 21.0, price_offer_active=False, request_active=True)
    assert s == 20.5


def test_recovery_holds_then_ramps():
    b0 = make(id="b0")
    b1 = make(id="b1")
    c = Controller(CFG, [b0, b1])           # b1 has 30-min stagger hold
    c.set_reduction({"b0": 1.0, "b1": 1.0}, start_h=18.0, end_h=20.0)
    # b0 (0-min hold, 30-min ramp): at 20.25 h it is mid-ramp, above full reduction
    s0, st0 = c.effective_setpoint(b0, 20.25, 21.0, False, False)
    assert st0 == STATUS_RECOVERING
    assert 20.0 < s0 < 21.0
    # b1 (30-min hold): still fully reduced at 20.25 h
    s1, st1 = c.effective_setpoint(b1, 20.25, 21.0, False, False)
    assert st1 == STATUS_RECOVERING
    assert abs(s1 - 20.0) < 1e-9
    # well after ramp, both back to normal schedule
    s0b, st0b = c.effective_setpoint(b0, 22.0, 21.0, False, False)
    assert st0b == STATUS_NORMAL and s0b == 21.0
