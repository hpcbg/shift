from shift_sim.config import load_config
from shift_sim.kpis import _cost
from shift_sim.simulator import Simulator, run_simulation
from shift_sim.scenario import ScenarioDef


def test_cost_uses_eur_per_mwh():
    # 30 kW for 2 minutes = 1.0 kWh; at 100 EUR/MWh -> 0.1 EUR
    dt_h = 2 / 60
    cost = _cost([30.0], [100.0], dt_h)
    assert abs(cost - (30.0 * dt_h * 100.0 / 1000.0)) < 1e-12
    assert abs(cost - 0.1) < 1e-9


def test_portfolio_and_building_kpis_present():
    cfg = load_config()
    out = run_simulation(cfg)
    p = out["portfolio_kpis"]
    for key in ("peak_reduction_kw", "peak_reduction_pct", "shifted_thermal_energy_kwh",
                "rebound_energy_kwh", "rebound_ratio", "renewable_thermal_energy_increase_kwh",
                "baseline_cost_eur", "controlled_cost_eur", "total_customer_savings_eur",
                "requests_accepted", "requests_partial", "requests_rejected",
                "comfort_violations", "audit_completeness_pct"):
        assert key in p
    assert len(out["per_building_kpis"]) == 6
    for b in out["per_building_kpis"]:
        for key in ("baseline_thermal_energy_kwh", "controlled_thermal_energy_kwh",
                    "customer_savings_eur", "renewable_thermal_energy_kwh",
                    "available_flexibility_kw", "committed_flexibility_kw",
                    "delivered_flexibility_kw", "comfort_deviation_c", "decision"):
            assert key in b


def test_rebound_zero_without_reduction():
    # remove the reduction request -> nothing shifted -> no rebound
    cfg = load_config()
    cfg["events"] = [e for e in cfg["events"] if e["type"] != "PEAK_REDUCTION_REQUEST"]
    out = run_simulation(cfg)
    assert out["portfolio_kpis"]["shifted_thermal_energy_kwh"] == 0.0
    assert out["portfolio_kpis"]["rebound_ratio"] == 0.0


def test_renewable_increase_positive_with_preheat():
    cfg = load_config()
    out = run_simulation(cfg)
    # preheating during the high-renewable price offer raises renewable consumption
    assert out["portfolio_kpis"]["renewable_thermal_energy_increase_kwh"] > 0.0
