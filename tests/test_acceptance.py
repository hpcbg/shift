"""
Deterministic acceptance test for the default six-building scenario
(docs/IMPLEMENTATION_PLAN.md section 16). Asserts the principal numerical
conditions of the acceptance scenario.
"""

from shift_sim.config import load_config
from shift_sim.simulator import run_simulation


def test_acceptance_scenario():
    cfg = load_config()
    out = run_simulation(cfg)
    p = out["portfolio_kpis"]
    per = {b["id"]: b for b in out["per_building_kpis"]}

    # (10) reduced portfolio demand relative to baseline
    assert p["peak_reduction_kw"] > 0.0
    assert p["controlled_peak_demand_kw"] < p["baseline_peak_demand_kw"]

    # (8/9) a mix of accept / partial / reject decisions
    assert p["requests_accepted"] >= 1
    assert p["requests_partial"] >= 1
    assert p["requests_rejected"] >= 1

    # (6) Administration is non-participating -> reject
    assert per["admin_building"]["decision"] == "reject"

    # (5) Residential Riverside window-open -> reduced (partial) participation
    assert per["res_riverside"]["decision"] == "partial"

    # (7) Municipal School comfort-constrained -> partial (cannot fully accept)
    assert per["municipal_school"]["decision"] == "partial"

    # (11) no SHIFT-induced comfort violation
    assert p["comfort_violations"] == 0

    # (14) increased heat consumption during the higher-renewable period
    assert p["renewable_thermal_energy_increase_kwh"] > 0.0

    # (15) positive customer savings under the price/incentive scenario
    assert p["total_customer_savings_eur"] > 0.0

    # (13) rebound managed: ratio within the configured maximum
    assert 0.0 <= p["rebound_ratio"] <= cfg["kpi_targets"]["max_rebound_ratio"]

    # (16) complete audit records
    assert p["audit_completeness_pct"] == 100.0

    # provisional peak-reduction target
    assert p["peak_reduction_pct"] >= cfg["kpi_targets"]["peak_reduction_pct"]
