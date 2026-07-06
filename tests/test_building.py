"""
Independent verification of the 1R1C thermal model (docs/IMPLEMENTATION_PLAN.md
section 13). These tests confirm the reference equations directly, so the
golden-value acceptance test protects the corrected implementation.
"""

from shift_sim.building import Building

BASE = dict(
    id="b", name="B", building_type="residential", map_x=0, map_y=0,
    floor_area_m2=1000, represented_units=10, represented_occupants=20,
    thermal_capacity_kwh_per_c=6.0, heat_loss_coefficient_kw_per_c=1.0,
    maximum_heat_power_kw=50.0, non_controllable_heat_kw=1.0,
    initial_indoor_temperature_c=21.0, scheduled_setpoint=21.0,
    comfort_minimum_c=20.0, comfort_maximum_c=23.0, setpoint_schedule=[],
    controllable_share=0.8, flexibility_participation=True,
)


def make(**over):
    d = dict(BASE); d.update(over)
    return Building.from_config(d)


def run_to_steady(b, s_eff, t_out, kp=6.0, ua_mult=1.0, fault=False, steps=4000, dt_h=2/60):
    q = 0.0
    for _ in range(steps):
        q = b.step(s_eff, t_out, dt_h, kp, ua_mult, fault, 0.0, 0.0)
    return q


def test_steady_state_reaches_setpoint():
    b = make()
    run_to_steady(b, s_eff=21.0, t_out=-5.0)
    # feed-forward controller drives T -> S_eff exactly at steady state
    assert abs(b.current_indoor_temperature_c - 21.0) < 0.05


def test_steady_state_heat_equals_loss():
    b = make()
    q = run_to_steady(b, s_eff=21.0, t_out=-5.0)
    expected = b.heat_loss_coefficient_kw_per_c * (21.0 - (-5.0))  # UA*(T - T_out)
    assert abs(q - expected) < 0.1


def test_opening_doubles_steady_heat():
    # high Pmax so the steady-state relation is what is under test (not the clamp)
    b1 = make(maximum_heat_power_kw=500.0); q1 = run_to_steady(b1, 21.0, -5.0, ua_mult=1.0)
    b2 = make(maximum_heat_power_kw=500.0); q2 = run_to_steady(b2, 21.0, -5.0, ua_mult=2.0)
    assert abs(q2 - 2.0 * q1) < 0.2   # UA doubled -> steady heat doubles


def test_pmax_clamp():
    b = make(maximum_heat_power_kw=10.0)
    q = b.step(40.0, -20.0, 2 / 60, 6.0, 1.0, False, 0.0, 0.0)
    assert q <= 10.0 + 1e-9


def test_non_controllable_floor():
    b = make(non_controllable_heat_kw=2.5)
    # target far below current temperature -> controller wants Q<=0, floored to base heat
    q = b.step(5.0, 5.0, 2 / 60, 6.0, 1.0, False, 0.0, 0.0)
    assert abs(q - 2.5) < 1e-9


def test_fault_zero_heat():
    b = make()
    q = b.step(21.0, -10.0, 2 / 60, 6.0, 1.0, True, 0.0, 0.0)
    assert q == 0.0


def test_time_constant_and_cost_units():
    b = make(thermal_capacity_kwh_per_c=6.0, heat_loss_coefficient_kw_per_c=1.0)
    assert abs((b.thermal_capacity_kwh_per_c / b.heat_loss_coefficient_kw_per_c) - 6.0) < 1e-9
    # cost accounting uses EUR/MWh: 30 kW for 2 min at 100 EUR/MWh
    b.reset()
    b.step(21.0, -5.0, 2 / 60, 6.0, 1.0, False, renewable_share=0.5, price_eur_per_mwh=100.0)
    energy = b.cumulative_thermal_energy
    assert abs(b.cumulative_cost - energy * 100.0 / 1000.0) < 1e-9
    assert abs(b.cumulative_renewable_thermal_energy - energy * 0.5) < 1e-9


def test_schedule_lookup():
    b = make(setpoint_schedule=[{"start": "07:00", "end": "19:00", "setpoint_c": 21.0},
                                {"start": "19:00", "end": "24:00", "setpoint_c": 17.0},
                                {"start": "00:00", "end": "07:00", "setpoint_c": 17.0}])
    assert b.scheduled_setpoint_at(12.0) == 21.0
    assert b.scheduled_setpoint_at(22.0) == 17.0
    assert b.scheduled_setpoint_at(3.0) == 17.0
