from shift_sim.building import Building
from shift_sim import flexibility as flex
from shift_sim.flexibility import ACCEPT, PARTIAL, REJECT

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


def test_non_participating_zero_available():
    b = make(flexibility_participation=False)
    assert flex.assess_available_kw(b, 21.0, -5.0, 1.0, 2.0) == 0.0


def test_zero_controllable_share_zero_available():
    b = make(controllable_share=0.0)
    assert flex.assess_available_kw(b, 21.0, -5.0, 1.0, 2.0) == 0.0


def test_more_headroom_more_available():
    low = make(comfort_minimum_c=20.8)
    high = make(comfort_minimum_c=20.0)
    a_low = flex.assess_available_kw(low, 21.0, -5.0, 1.0, 2.0)
    a_high = flex.assess_available_kw(high, 21.0, -5.0, 1.0, 2.0)
    assert a_high > a_low


def test_opening_does_not_inflate_available():
    b = make()
    closed = flex.assess_available_kw(b, 21.0, -5.0, 1.0, 2.0)
    opened = flex.assess_available_kw(b, 21.0, -5.0, 1.9, 2.0)
    assert opened <= closed + 1e-9   # open window never increases offered flexibility


def test_setpoint_drop_capped_by_headroom_and_monotonic():
    b = make()
    d_small = flex.setpoint_drop_for(2.0, b, setpoint=21.0)
    d_big = flex.setpoint_drop_for(20.0, b, setpoint=21.0)
    assert d_big >= d_small
    assert d_big <= (21.0 - b.comfort_minimum_c) + 1e-9   # never below comfort floor


def test_allocate_small_request_all_accept():
    bs = [make(id="a"), make(id="b2"), make(id="c")]
    avail = {b.id: 10.0 for b in bs}
    sp = {b.id: 21.0 for b in bs}
    env = flex.allocate(bs, requested_kw=3.0, availables=avail, setpoints=sp)
    assert all(e.decision == ACCEPT for e in env.values())


def test_allocate_reject_when_unavailable():
    bs = [make(id="a"), make(id="b2", flexibility_participation=False)]
    avail = {"a": 10.0, "b2": 0.0}
    sp = {"a": 21.0, "b2": 21.0}
    env = flex.allocate(bs, requested_kw=5.0, availables=avail, setpoints=sp)
    assert env["b2"].decision == REJECT
    assert env["a"].decision == ACCEPT


def test_allocate_partial_when_below_fair_share():
    # 'small' has far less availability than its capacity-weighted share -> partial
    big = make(id="big", maximum_heat_power_kw=80.0)
    small = make(id="small", maximum_heat_power_kw=80.0)
    avail = {"big": 30.0, "small": 1.0}
    sp = {"big": 21.0, "small": 21.0}
    env = flex.allocate([big, small], requested_kw=40.0, availables=avail, setpoints=sp)
    assert env["small"].decision == PARTIAL
