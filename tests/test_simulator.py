from shift_sim.config import load_config
from shift_sim.scenario import ScenarioDef
from shift_sim.simulator import Simulator, run_simulation


def test_deterministic():
    cfg = load_config()
    a = run_simulation(cfg)
    b = run_simulation(cfg)
    assert a["shift"]["aggregated_demand_kw"] == b["shift"]["aggregated_demand_kw"]
    assert a["portfolio_kpis"] == b["portfolio_kpis"]


def test_fault_zeroes_demand_in_both_scenarios():
    cfg = load_config()
    cfg["events"].append({
        "type": "SUBSTATION_FAULT", "building_id": "res_north",
        "start_time": "02:00", "duration_minutes": 60,
    })
    base = Simulator(cfg, ScenarioDef.baseline()).run()
    shift = Simulator(cfg, ScenarioDef.shift()).run(base.aggregated_demand_kw)
    # 02:30 -> step index
    dt_h = base.hours[1] - base.hours[0]
    i = int(round(2.5 / dt_h))
    assert base.per_building["res_north"]["q"][i] == 0.0
    assert shift.per_building["res_north"]["q"][i] == 0.0


def test_audit_completeness_all_events_logged():
    cfg = load_config()
    out = run_simulation(cfg)
    assert out["portfolio_kpis"]["audit_completeness_pct"] == 100.0
    # at least one signal, one decision and one command recorded
    cats = {a["category"] for a in out["audit"]}
    assert {"signal", "decision", "command"}.issubset(cats)


def test_physical_events_apply_to_baseline():
    # window at Riverside raises baseline losses vs no window
    cfg = load_config()
    base_with = Simulator(cfg, ScenarioDef.baseline()).run()

    cfg2 = load_config()
    cfg2["events"] = [e for e in cfg2["events"] if e["type"] != "WINDOW_OPEN"]
    base_without = Simulator(cfg2, ScenarioDef.baseline()).run()

    dt_h = base_with.hours[1] - base_with.hours[0]
    i = int(round(18.5 / dt_h))
    assert base_with.per_building["res_riverside"]["q"][i] > \
        base_without.per_building["res_riverside"]["q"][i]
