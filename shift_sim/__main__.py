"""
Headless CLI runner:

    python -m shift_sim                     # run default config, print KPI summary
    python -m shift_sim --config other.yaml
    python -m shift_sim --csv out.csv       # also export the demand time series

Deterministic; no external services.
"""

from __future__ import annotations

import argparse
import csv
import sys
from typing import Any, Dict

from .config import load_config
from .simulator import run_simulation


def _fmt(v: Any) -> str:
    return f"{v:,.2f}" if isinstance(v, float) else str(v)


def _print_summary(result: Dict[str, Any]) -> None:
    p = result["portfolio_kpis"]
    print("\n" + "=" * 64)
    print("SHIFT — synthetic pre-pilot simulation (space heating, 1R1C)")
    print("Synthetic assumptions only; not real Miesto Gijos data; not TRL 7.")
    print("=" * 64)

    print("\nPORTFOLIO KPIs")
    order = [
        ("baseline_peak_demand_kw", "Baseline peak demand", "kW"),
        ("controlled_peak_demand_kw", "Controlled peak demand", "kW"),
        ("peak_reduction_kw", "Peak reduction", "kW"),
        ("peak_reduction_pct", "Peak reduction", "%"),
        ("shifted_thermal_energy_kwh", "Shifted thermal energy", "kWh"),
        ("rebound_energy_kwh", "Rebound energy", "kWh"),
        ("rebound_ratio", "Rebound ratio", "x"),
        ("renewable_thermal_energy_increase_kwh", "Renewable thermal-energy increase", "kWh"),
        ("baseline_cost_eur", "Baseline cost", "EUR"),
        ("controlled_cost_eur", "Controlled cost", "EUR"),
        ("total_customer_savings_eur", "Total customer savings", "EUR"),
        ("requests_accepted", "Requests accepted", ""),
        ("requests_partial", "Requests partial", ""),
        ("requests_rejected", "Requests rejected", ""),
        ("comfort_violations", "Comfort violations", ""),
        ("audit_completeness_pct", "Audit completeness", "%"),
    ]
    for key, label, unit in order:
        print(f"  {label:<38} {_fmt(p[key]):>12} {unit}")

    print("\nPER-BUILDING")
    hdr = f"  {'Building':<24}{'decision':>9}{'avail':>8}{'commit':>8}{'deliv':>8}{'save EUR':>10}{'dev C':>7}"
    print(hdr)
    for b in result["per_building_kpis"]:
        print(f"  {b['name']:<24}{b['decision']:>9}"
              f"{b['available_flexibility_kw']:>8.1f}{b['committed_flexibility_kw']:>8.1f}"
              f"{b['delivered_flexibility_kw']:>8.1f}{b['customer_savings_eur']:>10.2f}"
              f"{b['comfort_deviation_c']:>7.2f}")
    print()


def _export_csv(result: Dict[str, Any], path: str) -> None:
    base = result["baseline"]
    shift = result["shift"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "hour", "t_out_c", "renewable_share",
                    "price_eur_per_mwh", "baseline_demand_kw", "shift_demand_kw"])
        for i, ts in enumerate(shift["timestamps"]):
            w.writerow([ts, shift["hours"][i], shift["t_out"][i],
                        shift["renewable_share"][i], shift["price_eur_per_mwh"][i],
                        base["aggregated_demand_kw"][i], shift["aggregated_demand_kw"][i]])
    print(f"Wrote demand time series to {path}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="shift_sim", description="SHIFT headless simulator")
    ap.add_argument("--config", default=None, help="path to a config.yaml")
    ap.add_argument("--csv", default=None, help="optional CSV export path")
    args = ap.parse_args(argv)

    config = load_config(args.config)
    result = run_simulation(config)
    _print_summary(result)
    if args.csv:
        _export_csv(result, args.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
