# SHIFT - Implementation Plan

**SHIFT - Smart Heat Interoperability and Flexibility Technology**
Synthetic pre-pilot district-heating demand-response simulator (WP2 deliverable).

This plan is the build specification. It assumes [`ARCHITECTURE.md`](./ARCHITECTURE.md).

> **Scope summary.** The simulator uses a 1R1C space-heating model, six
> synthetic buildings, synthetic price and renewable-share profiles, and a
> parallel deterministic baseline for control and KPI evaluation. The external
> actor is represented generically as the **district-heating network operator**.

---

## 1. MVP scope (Phases 0–5)

Implement: scaffold; thermal core; flexibility & control; events, KPIs & audit;
API; dashboard.

**Deferred — Phase 6, not in MVP:** the separate long-term economics module.
The MVP contains **no** NPV, IRR, payback, avoided-peak-generation valuation,
long-term cost-per-event, or long-term CO₂ financial valuation.

The MVP **does** compute, in `shift_sim/kpis.py`: baseline thermal-energy cost;
SHIFT-controlled thermal-energy cost; customer savings under the simulated
tariff/incentive profile; renewable thermal energy consumed; renewable share;
shifted thermal energy; peak reduction; rebound.

---

## 2. Selected technology stack

| Layer | Choice | Note |
|-------|--------|------|
| Language | **Python 3.12** | |
| Physics core | **Pure Python, stdlib only** | no numpy/pandas unless a real need is demonstrated |
| Config | `pyyaml` | deep-merged local overrides |
| CSV export | **stdlib `csv`** | no pandas |
| Web server | **Python stdlib `http.server`** | no web framework |
| Frontend | single static `web/dashboard.html` + vendored `chart.umd.js` (Chart.js v4.4.1, MIT — licence header retained) | no build, no CDN, no map tiles |
| Tests | **pytest** | |

**Mandatory `requirements.txt`:**

```
pyyaml>=6.0
pytest>=7.0
```

No numpy, no pandas, no web framework. (numpy/pandas may be added later only if
implementation or testing demonstrates a real need.)

---

## 3. Reuse / non-reuse decisions

**Reuse as patterns** (re-implemented in district-heating terms): YAML deep-merge
config; stdlib server handler shape; `ScenarioDef` + multi-scenario compare;
`StepMetrics`/`summarize` roll-up; time-of-use tariff lookup (EUR/MWh); normalised
hourly-shape profiles (outdoor temp, renewable share); dynamic-event list; static
dashboard + vendored chart; `tests/` discipline.

**Do NOT reuse** (HARVEST-specific): tractors, batteries/SoC/swap, chargers &
charging strategies, V2L, routes/geometry/`(x,y)` transit, tasks/PTO,
agricultural consumers, MARL, `farmview`, PV NN predictor, all HARVEST
names/branding, **and the entire `roi/` NPV/IRR/payback stack** (Phase 6,
excluded from MVP). No HARVEST domain code is imported.

**Prototype status:** the HTML prototype provides executable reference equations
and initial prototype behaviour. Section 13 defines the independent verification
process used before establishing golden-value regression tests.

---

## 4. Proposed directory structure

```
shift/
├── README.md
├── requirements.txt              # pyyaml, pytest
├── config.yaml                   # committed default: full six-building scenario
├── config.local.yaml.example     # documented override template
├── server.py                     # stdlib HTTP server + JSON endpoints
├── shift_sim/
│   ├── __init__.py
│   ├── __main__.py               # CLI batch runner (headless)
│   ├── config.py                 # load_yaml + deep-merge; unit-annotated access
│   ├── profiles.py               # outdoor temp, renewable share, heat tariff (EUR/MWh)
│   ├── building.py               # 1R1C thermal twin, full attribute set, control status
│   ├── substation.py             # substation limits + fault state
│   ├── events.py                 # 7 required event types (+ optional)
│   ├── flexibility.py            # assess / allocate / decide / kW→°C heuristic
│   ├── controller.py             # preheat / reduce / staggered recovery
│   ├── scenario.py               # ScenarioDef + SimulationConfig
│   ├── simulator.py              # deterministic one-shot loop + StepMetrics
│   ├── kpis.py                   # per-building + portfolio KPIs (incl. cost/energy)
│   └── audit.py                  # timestamped signal/decision/command/outcome log
├── web/
│   ├── dashboard.html            # console + schematic map + charts + decision/audit
│   └── chart.umd.js              # vendored, offline (MIT header retained)
├── tests/
│   ├── test_building.py
│   ├── test_flexibility.py
│   ├── test_controller.py
│   ├── test_events.py
│   ├── test_kpis.py
│   ├── test_simulator.py
│   ├── test_config.py
│   ├── test_api.py
│   └── test_acceptance.py        # deterministic acceptance scenario
├── docs/
│   ├── ARCHITECTURE.md
│   └── IMPLEMENTATION_PLAN.md
├── prototype/                    # existing PoC (reference only, unchanged)
└── references/                   # existing challenge & domain docs (unchanged)
```

`config/district_heating_demo.yaml` (named-scenario file) is optional and only added if
the loader supports named scenarios cleanly; the MVP ships the full scenario in
the committed `config.yaml`.

---

## 5. Domain model (implementation shapes)

`Building` (static config + mutable runtime; `reset()` re-initialises state):

```python
@dataclass
class Building:
    # identity & geometry (synthetic)
    id: str; name: str
    building_type: str            # residential | office | school | municipal
    map_x: float; map_y: float    # 0–100 schematic, no geographic meaning
    floor_area_m2: float
    represented_units: int
    represented_occupants: int
    # thermal
    thermal_capacity_kwh_per_c: float     # C   [kWh/°C]
    heat_loss_coefficient_kw_per_c: float # UA  [kW/°C]
    maximum_heat_power_kw: float          # Pmax [kW]
    non_controllable_heat_kw: float = 0.0 # optional uncurtailable base heat [kW]
    # comfort / occupancy / participation
    initial_indoor_temperature_c: float
    scheduled_setpoint: float             # [°C] default target
    comfort_minimum_c: float; comfort_maximum_c: float   # hard band [°C]
    setpoint_schedule: list               # [{start_h,end_h,setpoint_c}] occupancy-driven
    controllable_share: float             # 0–1
    flexibility_participation: bool
    # runtime state
    current_indoor_temperature_c: float
    window_state: bool = False; door_state: bool = False
    current_heat_input: float = 0.0; current_heat_loss: float = 0.0
    cumulative_thermal_energy: float = 0.0
    cumulative_renewable_thermal_energy: float = 0.0
    cumulative_cost: float = 0.0
    available_flexibility: float = 0.0
    committed_flexibility: float = 0.0
    delivered_flexibility: float = 0.0
    thermal_state_of_charge: float = 0.0  # C·(T − comfort_minimum) [kWh]
    control_status: str = "normal"
```

`control_status` ∈ {normal, preheating, reducing, recovering, comfort_constrained,
non_participating, window_open, door_open, fault}.

No `hygiene_floor` field. Indoor air temperature is never a DHW hygiene
temperature (see §6).

---

## 6. Thermal equations, units, and the comfort/hygiene decision

(Full derivation in ARCHITECTURE §7 — coding contract here.)

```
Heat balance:  C · dT/dt = Q − UA_eff·(T − T_out)
Controller:    Q = UA_eff·(S_eff − T_out) + Kp·(S_eff − T)
               Q = clamp(Q, non_controllable_heat_kw, Pmax_eff)   # Pmax_eff=0 in fault
Integration:   T ← T + (Q − UA_eff·(T − T_out)) / C · dt          # explicit Euler
Opening:       UA_eff = UA · opening_multiplier   (window/door event active)
τ = C / UA
```

**Units:** temp °C · power kW · energy kWh · capacity kWh/°C · UA kW/°C · Kp
kW/°C · dt h · **price EUR/MWh thermal**. Defaults `dt = 2 min`, `Kp = 6 kW/°C`.

**Cost (single source of truth):** `cost_eur = energy_kwh * price_eur_per_mwh / 1000`.
Every config price field is annotated `EUR/MWh`.

**Comfort/hygiene:** the MVP models **space heating only**, bounded by
`comfort_minimum_c` … `comfort_maximum_c`, substation limits, and optional
`non_controllable_heat_kw`. There is **no** room-temperature hygiene floor and
the MVP does not curtail any explicitly non-controllable load. DHW tank
temperature and legionella constraints are a documented future extension with a
separate model.

---

## 7. Simulation lifecycle (deterministic, one-shot)

1. Load `config.yaml`, deep-merge `config.local.yaml` → `SimulationConfig`.
2. Build six buildings, profiles, event list; build `ScenarioDef`s.
3. For **each** scenario, `Simulator.run()`:
   - reset buildings to initial conditions;
   - loop `t = start … end` step `dt`:
     - `env = profiles(t)` (with PRICE_OFFER price/renewable overrides);
     - apply physical events (window/door/fault) to both scenarios;
     - baseline → `S_eff = scheduled_setpoint(t)`;
     - shift → at the first active step of a PEAK/CRITICAL request:
       `assess → allocate → decide`, log to audit; then `S_eff` from preheat/
       reduce/recover strategy;
     - `Q = building.control(S_eff, T_out)`; `building.step(...)`;
     - record `StepMetrics`.
4. `kpis.compute(baseline_metrics, shift_metrics)` → per-building + portfolio.
5. Emit JSON / CSV / stdout.

Horizon default 1 day; multi-day is a later loop reusing the engine. The engine
is seed-free and deterministic.

---

## 8. Baseline-versus-SHIFT design

Same engine, same config, two `ScenarioDef`s. Baseline follows scheduled
setpoints with all flexibility levers disabled and requests ignored. Physical
events (window/door/fault) apply to **both**. Delivered flexibility =
`baseline − shift` at each step (positive = shaved during event, negative =
rebound after). The baseline is an **exact counterfactual**. Forecasting accuracy
metrics are introduced later when operational data and learned baselines are
available.

---

## 9. KPI model (all computed from the simulation)

Cost uses `energy_kwh * price_eur_per_mwh / 1000`. Event window = the
PEAK_REDUCTION/CRITICAL window(s); rebound window = `[event_end, event_end + 2h]`.

**Per building:**

| KPI | Definition |
|-----|-----------|
| baseline thermal energy | `Σ Q_base·dt` (day), kWh |
| controlled thermal energy | `Σ Q_shift·dt`, kWh |
| baseline cost | `Σ Q_base·dt·price/1000`, EUR |
| controlled cost | `Σ Q_shift·dt·price/1000`, EUR |
| customer savings | baseline cost − controlled cost, EUR |
| renewable thermal energy consumed | `Σ Q_shift·dt·renewable_share`, kWh |
| renewable share | renewable energy / controlled energy, % |
| available flexibility | assessed kW at event start |
| committed flexibility | allocated kW |
| delivered flexibility | mean `max(0, D_base − D_shift)` over event, kW |
| comfort deviation | `max(0, comfort_minimum − T_shift)` over event, °C |
| event response | delivered/committed ratio + responded flag |

**Portfolio:** baseline & controlled peak demand (kW); peak reduction (kW, %);
shifted thermal energy (kWh); rebound energy (kWh); rebound ratio; renewable
thermal-energy increase (shift − base, kWh); baseline & controlled cost; total
customer savings; counts accepted / partial / rejected; comfort violations
(buildings with deviation > 0.1 °C); audit completeness (%).

---

## 10. Event model

`events.py`, config-driven list; every firing timestamped and shown in the
audit/event timeline. **Required types:**

| Type | Key fields |
|------|-----------|
| `PRICE_OFFER` | received_time, start_time, duration, price_eur_per_mwh, [customer_incentive], [renewable_share_override], target ids/portfolio |
| `PEAK_REDUCTION_REQUEST` | received_time, start_time, duration, requested_reduction_kw \| requested_reduction_percent, target, maximum_rebound_ratio, [incentive] |
| `CRITICAL_REQUEST` | received_time, start (immediate/scheduled), duration, requested_reduction_kw, priority, target |
| `WINDOW_OPEN` | building_id, start_time, duration, heat_loss_multiplier |
| `DOOR_OPEN` | building_id, start_time, duration, heat_loss_multiplier |
| `SUBSTATION_FAULT` | building_id, start_time, duration \| restore event |
| `RESTORE` | affected building/portfolio, reason |

**Optional:** cold-snap, network-capacity change.

---

## 11. Flexibility request & control sequence

Operator request is kW or percent. The controller does **not** treat requested kW
as a fixed setpoint drop. Sequence: (1) assess available reduction per building;
(2) account for current demand, comfort headroom, `C`, `UA_eff`, open
windows/doors, `Pmax`, `controllable_share`, participation; (3) allocate the
portfolio request; (4) decide accept/partial/reject; (5) derive a heat-input /
setpoint trajectory (`drop ≈ committed_kW / UA_eff`, floored at
`comfort_minimum`); (6) simulate the response. The kW→°C mapping is a
**documented control heuristic** whose parameters are verified through simulation
and later calibrated with operational data.

---

## 12. API design (stdlib server, JSON, CORS)

| Method | Path | Body/query | Returns |
|--------|------|-----------|---------|
| GET | `/`, `/dashboard.html` | — | dashboard HTML |
| GET | `/chart.js` | — | vendored Chart.js |
| GET | `/config` | — | merged config JSON |
| GET | `/health` | — | `{status, config}` |
| POST | `/simulate` | `{overrides}` | `{per_building_timeseries, aggregated, per_building_kpis, portfolio_kpis, envelopes, decisions, audit, map_state}` |
| POST | `/flexibility/assess` | `{overrides}` | `{envelopes, decisions}` (assessment only) |

`overrides` mirror dashboard controls (participation, window/door, setpoint,
event edits) and are deep-merged onto a copy of the base config. Errors: `400`
bad request, `500` with trace.

---

## 13. Prototype verification & regression testing

Before adding any golden-value regression test, independently verify the
prototype equations and calculations:

1. independently verify the thermal equation (steady state, energy balance, `τ`);
2. independently verify each KPI formula and its window;
3. confirm units (kW, kWh, kWh/°C, kW/°C, °C, EUR/MWh);
4. identify and correct any prototype issue (e.g. EUR/kWh vs EUR/MWh, comfort-floor
   handling under night setback);
5. document intentional differences from the prototype.

Golden-value tests then protect the verified Python implementation and its
documented behaviour.

---

## 14. Testing strategy (pytest)

| File | Asserts |
|------|---------|
| `test_building.py` | steady state `T=S_eff`; energy balance; `τ=C/UA`; Pmax clamp; opening raises loss; non-controllable floor honoured; Euler stability at 2 min. |
| `test_controller.py` | preheat only in PRICE_OFFER window & ≤ comfort_max; reduction from committed kW; staggered hold/ramp; baseline ignores requests. |
| `test_flexibility.py` | available shrinks with smaller headroom/higher loss; window reduces availability; non-participating/fault → 0 & reject; partial vs accept logic; kW→°C heuristic monotonic and comfort-floored. |
| `test_events.py` | all 7 required types parse and fire at correct times; each logged to audit. |
| `test_kpis.py` | per-building & portfolio arithmetic on hand-computed fixtures; cost uses /1000 (EUR/MWh); rebound=0 when no rebound; renewable increase sign. |
| `test_simulator.py` | deterministic; physical events affect both scenarios; audit completeness = 100 %. |
| `test_config.py` | deep-merge; local override wins; missing local tolerated; six buildings present. |
| `test_api.py` | `/health`, `/config`, `/simulate`, `/flexibility/assess` well-formed JSON; bad request → 400. |
| `test_acceptance.py` | the §16 acceptance scenario's principal numerical conditions. |

---

## 15. Phased implementation sequence (0–5)

| Phase | Deliverable | Gate |
|-------|-------------|------|
| **0 — Scaffold** | repo layout, `requirements.txt`, `config.yaml` (six buildings) + `.example`, package skeleton, README | `pip install`; `pytest` collects |
| **1 — Thermal core** | `config.py`, `profiles.py`, `substation.py`, `building.py`, `scenario.py`, baseline `simulator.py`; `test_building/config` | baseline day runs; steady-state & balance verified |
| **2 — Flexibility & control** | `flexibility.py`, `controller.py`, baseline-vs-shift; `test_flexibility/controller` | shift shows peak reduction, comfort respected |
| **3 — Events, KPIs, audit** | `events.py`, `kpis.py`, `audit.py`; `test_events/kpis/simulator` | per-building + portfolio KPIs; 100 % audit |
| **4 — API** | `server.py` endpoints + override merge; `test_api` | `/simulate` returns full JSON |
| **5 — Dashboard** | `web/dashboard.html` (map + charts + panels) + vendored chart; `test_acceptance` | one-command browser demo end-to-end |

Phase 6 (economics) is **deferred**.

---

## 16. Acceptance scenario (default config) + automated test

The default scenario must visibly demonstrate: (1) six synthetic buildings on a
cold winter day; (2) parallel baseline & SHIFT; (3) a high-renewable discounted
PRICE_OFFER ≈14:00–17:00; (4) suitable buildings preheating within comfort_max;
(5) Residential Riverside window-open with reduced flexibility; (6) Administration
non-participating; (7) Municipal School comfort-constrained → partial; (8) a
portfolio PEAK_REDUCTION_REQUEST ≈18:00–20:00; (9) per-building accept/partial/
reject; (10) reduced portfolio demand vs baseline; (11) no intentional comfort
violation; (12) staggered recovery; (13) no synchronised recovery peak above the
contemporaneous baseline where achievable; (14) increased heat consumption during
the higher-renewable period; (15) positive customer savings; (16) complete event
& decision audit records.

`tests/test_acceptance.py` asserts the principal numerical conditions
deterministically (peak reduction > 0; portfolio comfort violations = 0; total
savings > 0; rebound ratio ≤ configured max where achievable; ≥1 reject and ≥1
partial; audit completeness = 100 %).

---

## 17. Configuration files

Create committed `config.yaml` (full six-building scenario) and
`config.local.yaml.example`. **All synthetic assumptions are centralised in
config** (building properties, map coordinates, outdoor temperature, renewable
profile, price profile, setpoint & occupancy schedules, comfort bands,
participation, controllable share, opening multipliers, operator events,
preheating, recovery staggering) — never scattered in source. Every price field
is annotated `EUR/MWh`.

Config skeleton:

```yaml
project: {name: shift_prepilot, version: 0.1}
simulation: {start_time, end_time, time_step_minutes: 2, rebound_window_minutes: 120}
controller: {kp_kw_per_c: 6.0, default_opening_multiplier: 1.9}
weather: {coldest_c, coldest_hour, daily_swing_c}
renewable: {base_share, midday_peak_share, peak_hour, spread}
tariff:   {periods: [{start_h,end_h,price_eur_per_mwh}], default_price_eur_per_mwh}
strategy: {preheat: true, preheat_boost_c, stagger_recovery: true,
           stagger_minutes_by_index: [...], recovery_ramp_minutes}
buildings: [ {id,name,building_type,map_x,map_y,floor_area_m2,represented_units,
              represented_occupants,thermal_capacity_kwh_per_c,
              heat_loss_coefficient_kw_per_c,maximum_heat_power_kw,
              non_controllable_heat_kw,initial_indoor_temperature_c,
              scheduled_setpoint,comfort_minimum_c,comfort_maximum_c,
              setpoint_schedule,controllable_share,flexibility_participation}, ... x6 ]
events: [ {type: PRICE_OFFER, ...}, {type: PEAK_REDUCTION_REQUEST, ...},
          {type: WINDOW_OPEN, ...}, ... ]
kpi_targets: {peak_reduction_pct: 10, max_comfort_deviation_c: 1.0, max_rebound_ratio: 0.8}
```

Economic figures are out of scope for the MVP; any placeholder is labelled a
demonstration assumption.

---

## 18. Development environment & exact run commands

**Primary environment: Linux / Bash.**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python server.py            # → http://localhost:8765
python -m shift_sim         # headless: run scenario, print KPIs (optional --csv out.csv)
pytest -q
pytest tests/test_acceptance.py -q
```

**Secondary — Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python server.py
python -m shift_sim
pytest -q
```

(The Linux venv activation is `source .venv/bin/activate` — **not**
`.venv/Scripts/activate`.)

---

## 19. Delivery checklist (§18 of the brief)

Before reporting completion: run full `pytest`; run the CLI scenario; run the
HTTP server and verify main endpoints; confirm the dashboard is served; confirm
the standalone prototype is unchanged; and confirm the HARVEST reference
repository remains unchanged. Report files created, architecture implemented,
run commands, tests passed, scenario KPI results, assumptions, and known
limitations.

---

## 20. Assumptions requiring attention

1. 1R1C single-zone, space heating only (2R2C & DHW hygiene deferred).
2. Synthetic weather/renewable/tariff; real feeds are a pilot integration.
3. Baseline is an exact counterfactual; forecasting NMAE is introduced with
   operational data and learned baselines.
4. Operator requests use kW/percent; control acts in °C through a documented
   heuristic.
5. Thermal parameters are synthetic and representative.
6. The deployment model is single-user and local, with the latest run retained
   in memory.
7. Heuristic confidence is an explanatory simulator score.
8. Prices in EUR/MWh throughout; cost = `energy_kwh * price / 1000`.
