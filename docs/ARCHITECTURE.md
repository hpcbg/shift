# SHIFT — Architecture

**SHIFT — Smart Heat Interoperability and Flexibility Technology**
A **synthetic pre-pilot simulator** for district-heating demand response.

> **Scope summary.** The simulator uses a 1R1C space-heating model,
> six synthetic buildings, synthetic environmental and tariff profiles, and a
> parallel deterministic baseline. The executable prototype provides reference
> equations and initial prototype behaviour for the modular implementation.

---

## 1. Purpose and scope

SHIFT turns district-heated buildings from passive consumers into controllable
providers of measurable thermal flexibility. It sits conceptually between the
**district-heating network operator** and individual heat substations.

The simulator verifies thermal balance, flexibility assessment, comfort,
rebound and KPI logic before integration with operational substations.

It implements the DESTO demand-response workflow, transferred from a single
domestic electric water heater to whole-building heat substations:

1. receive a flexibility signal from the district-heating network operator
   (price offer, peak-reduction request, or critical request);
2. assess available flexibility (in kW) from each controllable building;
3. allocate the portfolio request and decide **accept / partial / reject** per building;
4. advance (preheat), delay, or reduce heat consumption;
5. exploit building thermal inertia without breaching the comfort band;
6. execute control through (simulated) substation interfaces;
7. restore normal operation with staggered recovery to avoid a synchronised rebound peak;
8. log every signal, decision, command and outcome (auditable record).

**MVP scope (Phases 0–5):** scaffold, thermal core, flexibility & control,
events + KPIs + audit, API, dashboard. **Deferred (Phase 6):** the separate
long-term economics module. The MVP contains **no** NPV, IRR, payback,
avoided-peak-generation valuation, long-term cost-per-event, or long-term CO₂
financial valuation. It **does** compute basic cost/energy KPIs (baseline vs
controlled thermal-energy cost, customer savings, renewable thermal energy and
share, shifted energy, peak reduction, rebound) — all in `shift_sim/kpis.py`.

Out of scope for the simulator: real FIWARE/NGSI-LD brokers, real IoT hardware,
real weather/tariff feeds, DHW/legionella hygiene modelling, and live substation
writes. Clean seams are left for these.

---

## 2. Design principles

- **Independent project.** SHIFT reuses HARVEST *patterns and idioms*, not its
  domain code. No tractors, batteries, chargers, routes, fields, PTO, MARL or
  HARVEST branding cross the boundary.
- **Dependency-light and demo-first.** Runs with `python server.py` and a
  browser: no build step, no external services, no CDN. Mandatory deps are only
  `pyyaml` and `pytest`.
- **Transparent thermal model.** A lumped 1R1C model supports control and KPI
  evaluation using synthetic representative parameters.
- **Baseline as an exact counterfactual.** Every KPI is the difference between a
  parallel deterministic baseline with identical initial conditions and the
  SHIFT-controlled run. Forecast-accuracy metrics are added when operational data
  and learned baselines are available.
- **Rebound is a first-class constraint,** measured and reported for every event.
- **Comfort is a hard band** (`comfort_minimum_c` … `comfort_maximum_c`),
  enforced by the controller and never traded for peak reduction.
- **Everything is logged** and timestamped — the challenge's regulator-ready
  evidence.
- **Deterministic and stateless engine.** One-shot simulations; no server-side
  session, real-time clock or WebSocket in the MVP.
- **Centralised assumptions.** All synthetic assumptions live in configuration,
  never scattered through source.

---

## 3. System context (C4 level 1)

```
   ┌───────────────────────────────┐   flexibility signal        ┌──────────────────────────┐
   │ District-heating network       │  (PRICE_OFFER /             │                          │
   │ operator        │   PEAK_REDUCTION_REQUEST /  │        SHIFT             │
   │                                │   CRITICAL_REQUEST)         │   pre-pilot simulator    │
   │ — issues signals               │ ──────────────────────────►│                          │
   │ — authorises events            │                            │  — assess (kW) & allocate│
   │                                │ ◄──────────────────────────│  — accept/partial/reject │
   └───────────────────────────────┘   accepted reduction +      │  — control (preheat/     │
                                        heuristic confidence +    │    reduce / stagger)     │
                                        audit log                 │  — simulate 1R1C physics │
   ┌──────────────┐  outdoor T, renewable share, heat tariff      │  — KPIs (per building &  │
   │ Environment  │ ─────────────────────────────────────────────►│    portfolio)           │
   │ feeds (sim)  │                                               │  — audit everything      │
   └──────────────┘                                               └───────────┬──────────────┘
                                                                              │ setpoint / heat commands
                                                          ┌───────────────────▼──────────────┐
                                                          │ 6 synthetic heat-substation /      │
                                                          │ building thermal twins (1R1C,      │
                                                          │ comfort band, space heating only)  │
                                                          └────────────────────────────────────┘
```

In the pilot these seams become NGSI-LD signals, weather/tariff APIs and
FIWARE/SAREF substation adapters. In the simulator they are synthetic profiles
and in-memory objects.

---

## 4. Container view (C4 level 2)

| Container | Technology | Responsibility |
|-----------|-----------|----------------|
| **Simulation engine** `shift_sim/` | Python 3.12 package, **pure Python** (stdlib only) | 1R1C physics, flexibility assessment & allocation, control strategies, events, KPI + audit computation. No I/O, no framework — importable and unit-testable. |
| **HTTP server** `server.py` | Python stdlib `http.server` | Serves dashboard, exposes JSON endpoints (`/simulate`, `/flexibility/assess`, `/config`, `/health`), applies UI overrides, marshals results. No web framework. |
| **Dashboard** `web/dashboard.html` + vendored `chart.umd.js` (Chart.js v4.4.1, MIT) | One self-contained HTML file + one vendored JS file | Operator console, **schematic building map (offline SVG/CSS)**, result charts, per-building & portfolio KPI cards, flexibility-decision panel, event/audit timeline. No build tooling, no online map tiles. |

Long-term economics (`economics/`) is **deferred to Phase 6** and is *not* part
of the MVP.

Rationale for stdlib `http.server`: HARVEST demonstrates that a single-user,
local, zero-dependency server provides a low-friction one-command demo. FastAPI
is a future upgrade path for multi-user or streaming operation.

---

## 5. Component view — the simulation engine

```
shift_sim/
├── config.py       load_yaml + deep-merge of config.local.yaml (HARVEST idiom); unit-annotated fields
├── profiles.py     outdoor temperature, renewable share, heat tariff (EUR/MWh) — time → value
├── building.py     Building: 1R1C twin + full attribute set + control status
├── substation.py   substation technical limits (max heat power, fault state)
├── events.py       dynamic events (PRICE_OFFER, PEAK_REDUCTION_REQUEST, CRITICAL_REQUEST,
│                   WINDOW_OPEN, DOOR_OPEN, SUBSTATION_FAULT, RESTORE; optional cold-snap/capacity)
├── flexibility.py  assess available kW, allocate portfolio request, accept/partial/reject, kW→°C heuristic
├── controller.py   strategies: preheat, reduction trajectory, staggered recovery
├── scenario.py     ScenarioDef + typed SimulationConfig dataclasses (baseline vs shift)
├── simulator.py    Simulator: deterministic one-shot clock loop, StepMetrics collection
├── kpis.py         per-building and portfolio KPIs (incl. all basic cost/energy metrics)
├── audit.py        timestamped signal/decision/command/outcome log
└── __main__.py     CLI batch runner (headless: run scenario, print/export KPIs)
```

**Dependency direction** (no cycles): `profiles`, `substation`, `building` are
leaf domain; `events`, `flexibility`, `controller` depend on them; `simulator`
orchestrates; `kpis` and `audit` consume simulator output; `scenario`/`config`
feed everything; `__main__` and `server.py` are the entry points.

### 5.1 Data flow through one deterministic simulation

```
config.yaml (+ config.local.yaml)  ──load+merge──►  SimulationConfig
        │
        ├── ScenarioDef(baseline)         ┌──────────── same engine, same config ───────────┐
        └── ScenarioDef(shift)            ▼                                                   ▼
   Simulator.run("baseline")                              Simulator.run("shift")
     for t in clock (dt=2 min, horizon=1 day):              (as baseline, plus:)
        env = profiles(t)  # T_out, renewable, price          when a PEAK/CRITICAL request first
        events.apply(t)    # window/door/fault physical        activates:
        S_eff = scheduled_setpoint(building, t)                  envelope = flexibility.assess(...)   [kW]
        Q = building.control(S_eff, T_out)  # clamp[0,Pmax]      allocate portfolio → committed_i
        building.step(Q, dt); record StepMetrics                 decision accept/partial/reject → audit
                                                                during PRICE_OFFER → preheat (≤ comfort_max)
                                                                during event → reduce via kW→°C heuristic
                                                                after event → staggered recovery
        │                                                                       │
        └──────────────────────────► kpis.compute(baseline, shift) ◄───────────┘
                                             │
                                             ▼
     JSON { per_building_timeseries, aggregated_demand, per_building_kpis,
            portfolio_kpis, envelopes, decisions, audit_log, map_state }
                                             │
                                             ▼
                 server → dashboard (map + charts + KPI cards + decision + audit timeline)
```

Baseline and SHIFT are the **same engine, same config, different `ScenarioDef`**.
Physical events (window/door/fault) apply to **both** runs; only the control
response (preheat / reduce / stagger) differs. This guarantees an apples-to-apples
counterfactual.

---

## 6. Domain model — Building

`Building` carries the full attribute set (static config + runtime state). All
values are **synthetic**.

**Identity & geometry**

| Attribute | Unit / type | Notes |
|-----------|-------------|-------|
| `id`, `name` | str | synthetic (e.g. "Residential North") |
| `building_type` | `residential`\|`office`\|`school`\|`municipal` | |
| `map_x`, `map_y` | 0–100 schematic | synthetic dashboard coordinates (no geographic meaning) |
| `floor_area_m2` | m² | synthetic |
| `represented_units` | count | dwellings / tenant units |
| `represented_occupants` | count | |

**Thermal parameters**

| Attribute | Unit | Symbol |
|-----------|------|--------|
| `thermal_capacity_kwh_per_c` | kWh/°C | C |
| `heat_loss_coefficient_kw_per_c` | kW/°C | UA |
| `maximum_heat_power_kw` | kW | Pmax (substation limit) |
| `non_controllable_heat_kw` (optional) | kW | uncurtailable base heat |

**Comfort, occupancy, participation**

| Attribute | Unit / type | Notes |
|-----------|-------------|-------|
| `initial_indoor_temperature_c`, `current_indoor_temperature_c` | °C | state |
| `scheduled_setpoint` | °C | default target |
| `comfort_minimum_c`, `comfort_maximum_c` | °C | hard comfort band |
| occupancy / setpoint schedule | list of `{start_h,end_h,setpoint_c}` | drives daytime/night setbacks |
| `controllable_share` | 0–1 | fraction of heat that is shiftable |
| `flexibility_participation` | bool | false → never curtailed |
| `window_state`, `door_state` | bool | raise losses when open |

**Runtime accumulators / derived**

`current_heat_input` (kW), `current_heat_loss` (kW),
`cumulative_thermal_energy` (kWh), `cumulative_renewable_thermal_energy` (kWh),
`cumulative_cost` (EUR), `available_flexibility` (kW), `committed_flexibility`
(kW), `delivered_flexibility` (kW), `thermal_state_of_charge`
(kWh = `C·(T − comfort_minimum)`), `control_status`.

**`control_status` values:** `normal`, `preheating`, `reducing`, `recovering`,
`comfort_constrained`, `non_participating`, `window_open`, `door_open`, `fault`.

> **No hygiene floor.** Indoor **air** temperature is never treated as a DHW
> hygiene temperature. The MVP models space heating only, bounded by the comfort
> band, substation limits and optional `non_controllable_heat_kw`. The MVP does
> **not** curtail any explicitly non-controllable or protected thermal load.
> DHW tank-temperature and legionella constraints are a documented **future
> extension** with their own separate model.

---

## 7. Thermal model and units

Single-node lumped-capacitance (1R1C) space-heating model. These are
**reference equations**, independently verified as described in
IMPLEMENTATION_PLAN §13 and parameterised with synthetic representative values.

**State equation (heat balance):**

```
C · dT/dt = Q − UA_eff · (T − T_out)
```

**Controller (proportional + loss feed-forward), per building per step:**

```
Q = UA_eff · (S_eff − T_out) + Kp · (S_eff − T)
Q ← clamp(Q, non_controllable_heat_kw, Pmax_eff)     # Pmax_eff = 0 during fault
```

At steady state the feed-forward term makes `T = S_eff` exactly (no offset), so a
setpoint change maps cleanly to a temperature change — the basis of the kW→°C
control heuristic.

**Integration** (explicit Euler; `dt = 2 min` → stable):

```
T(t+dt) = T(t) + (Q − UA_eff·(T − T_out)) / C · dt
```

**Open window / door / fault** modify the physics for **both** scenarios:
`UA_eff = UA · opening_multiplier` while a WINDOW_OPEN/DOOR_OPEN event is active;
`Pmax_eff = 0` while a SUBSTATION_FAULT is active.

**Units — used consistently across config, engine, API and dashboard:**

| Quantity | Unit |
|----------|------|
| temperature `T,T_out,S` | °C |
| thermal power `Q,Pmax` | kW |
| thermal energy `Σ Q·dt` | kWh |
| thermal capacity `C` | kWh/°C |
| heat-loss coefficient `UA` | kW/°C |
| controller gain `Kp` | kW/°C |
| time constant `τ = C/UA` | h |
| step `dt` | h (from `time_step_minutes`, default 2) |
| **price** | **EUR/MWh (thermal)** |

**Cost formula (single source of truth):**

```
cost_eur = energy_kwh * price_eur_per_mwh / 1000
```

EUR/kWh is never mixed with EUR/MWh anywhere. Every config price field is
documented as EUR/MWh next to its value.

**Extension seams (post-MVP):** 2R2C, explicit supply/return temperature and
mass-flow, per-zone models, and a **separate DHW hygiene/legionella model**.

---

## 8. Flexibility assessment & control (the DESTO decision transferred)

The operator request is expressed in **kW or percent**. The controller must
**not** interpret requested kW as a fixed setpoint drop. The sequence is:

1. **Assess** each building's available reduction (kW) from: current heating
   demand, comfort headroom (`scheduled_setpoint − comfort_minimum`), thermal
   capacity `C`, heat loss `UA_eff`, open windows/doors, `Pmax`,
   `controllable_share`, and `flexibility_participation`.
   Heuristic: `available_kw = controllable_share · (UA_eff·headroom + C·stored/duration)`,
   capped at current demand and `Pmax`; `0` if not participating or in fault.
   `thermal_state_of_charge = C·(T − comfort_minimum)`.
2. **Allocate** the portfolio request proportionally to available flexibility
   (percent requests are resolved against baseline aggregated demand at event start).
3. **Decide** per building: **accept** (can meet its fair share), **partial**
   (participates but comfort/window-limited below its share), **reject**
   (non-participating, fault, or zero available).
4. **Derive** a heat-input / setpoint trajectory from the committed kW using the
   documented heuristic `setpoint_drop ≈ committed_kW / UA_eff`, floored at
   `comfort_minimum`. This kW→°C mapping is an explicit control heuristic whose
   parameters are verified through simulation and later calibrated with
   operational data.
5. **Simulate** the resulting temperature response.

A **heuristic confidence** score (0–1) may accompany a decision for explanation
only; it is explicitly labelled a **simulator heuristic**, never calibrated
prediction confidence.

Control levers: **preheat** during a PRICE_OFFER window (store cheap, high-renewable
heat, capped at `comfort_maximum`), **reduce** during the event, **stagger
recovery** afterwards (per-building hold + ramp) to avoid a synchronised rebound.

---

## 9. Default scenario — six synthetic buildings

The default committed configuration contains **six synthetic buildings**.
Names, coordinates and parameters are representative and defined exclusively for
the simulator.

| # | Name | Type | Character | Role in acceptance scenario |
|---|------|------|-----------|-----------------------------|
| 1 | Residential North | residential | modern, well-insulated, high `C`, strong participation | preheats and accepts |
| 2 | Residential Old Town | residential | older, high `UA`, limited flexibility | small accept/partial |
| 3 | Residential Riverside | residential | medium insulation, **window-open event** | reduced flexibility → partial |
| 4 | Business Centre | office | daytime occupancy schedule, lower night setpoint | preheats, accepts |
| 5 | Administration Building | municipal | **flexibility participation disabled** | reject (non-participating) |
| 6 | Municipal School | school | daytime occupancy, **tight comfort band** | partial (comfort-constrained) |

---

## 10. KPI model (per building and portfolio)

All values computed from the simulation (both runs). Full formulas in
IMPLEMENTATION_PLAN §9.

**Per building:** baseline thermal energy, controlled thermal energy, baseline
cost, controlled cost, customer savings, renewable thermal energy consumed,
renewable share, available/committed/delivered flexibility, comfort deviation,
event response.

**Portfolio:** baseline & controlled peak demand, peak reduction (kW and %),
shifted thermal energy, rebound energy, rebound ratio, renewable
thermal-energy increase, baseline & controlled cost, total customer savings,
counts of accepted/partial/rejected requests, comfort violations, audit
completeness.

Baseline forecasting metrics such as NMAE are introduced when operational data
and learned baselines are available. The simulator evaluates KPI arithmetic
against its known parallel baseline.

---

## 11. Dashboard (one-shot, deterministic)

- **Left console:** conditions, operator events, strategy (preheat/stagger), and
  per-building participation / window / door / setpoint controls.
- **Schematic building map** (offline SVG/CSS, no map tiles): all six buildings at
  their `map_x,map_y`, showing name, type, indoor temperature, heat demand,
  flexibility and status, with distinct visuals for `normal`, `preheating`,
  `reducing`, `recovering`, `comfort warning`, `window open`, `door open`,
  `non-participating`, `fault`. Selecting a building updates the detail panel and
  temperature chart.
- **Charts:** context (outdoor T + renewable share), indoor temperature (baseline
  vs SHIFT per building, comfort band), aggregated demand (baseline vs SHIFT,
  shaved/rebound shading).
- **KPI cards:** per-building and portfolio.
- **Flexibility-decision panel** and **event/audit timeline.**

**Execution model:** configure → *Run simulation* → `POST /simulate` → receive
complete baseline + SHIFT time series → render. Manual controls modify the next
request and rerun. No real-time clock, WebSocket, or persistent server state; the
engine is stateless and deterministic.

---

## 12. Reuse map — HARVEST → SHIFT

### 12.1 Reused *patterns* (re-implemented, not imported)

| HARVEST asset | Pattern reused | Why |
|---------------|----------------|-----|
| `load_yaml` + `load_yaml_with_local` deep-merge | `config.py` | layered config + machine-local overrides. |
| stdlib `http.server` handler (`/simulate`, `/config`, `/health`, CORS, JSON) | `server.py` | zero-dependency one-command demo. |
| `ScenarioDef` + multi-scenario compare | `scenario.py`, `simulator.py` | baseline-vs-intervention core. |
| `StepMetrics` + `summarize()` | `StepMetrics`, `kpis.py` | per-step metering → KPI roll-up. |
| `TariffModel` time-of-use lookup | `profiles.py` (heat tariff, EUR/MWh) | time-of-use pricing. |
| PV hourly-shape profile | outdoor-temp & renewable-share profiles | same "normalised time-shape" idea. |
| Dynamic events (`_load_events`/`_apply_event`) | `events.py` | typed events injected mid-run. |
| Static dashboard + vendored `chart.umd.js` + canvas | `web/dashboard.html` | no-build visual demo. |
| `tests/` with unit + endpoint integration | `tests/` | same testing discipline. |

### 12.2 Explicitly **NOT** reused (HARVEST-specific)

Tractor/vehicle models, battery electrochemistry/SoC/swap, chargers & charging
strategies, V2L, routes/field geometry/`(x,y)` transit, task scheduling/PTO,
agricultural consumers, MARL, `farmview`, PV NN predictor, HARVEST names/branding,
**and the entire `roi/` financial stack** (NPV/IRR/payback) — deferred to Phase 6,
excluded from the MVP. The SHIFT engine shares **zero** domain code with HARVEST.

---

## 13. Cross-cutting concerns & future seams

- **Interoperability (pilot):** `profiles.py` and `substation.py` are the seams
  where synthetic feeds become FIWARE/NGSI-LD (Orion-LD) + SAREF adapters.
- **Auditability:** `audit.py` records serialise directly to a future pilot store.
- **Staged rollout (shadow → supervised → live):** the simulator *is* shadow mode.
- **Manual override:** modelled as a `RESTORE` event.
- **Framework upgrade path:** stdlib server → FastAPI when multi-user/streaming needed.

---

## 14. Key architectural assumptions (flag for review)

1. **1R1C single-zone, space heating only** — adequate for pre-pilot logic/KPI
   verification; 2R2C and DHW hygiene deferred.
2. **Synthetic environment** (sinusoidal outdoor temperature, Gaussian renewable
   share, time-of-use EUR/MWh tariff). Real feeds are a pilot integration.
3. **Baseline = exact deterministic counterfactual.** Forecast uncertainty
   metrics such as NMAE are introduced with operational data and learned
   baselines.
4. **Operator requests use kW/percent; control acts in °C** through the documented
   heuristic `drop ≈ committed_kW / UA_eff`.
5. **Thermal parameters are synthetic and representative.**
6. **Single-user local deployment** retains the latest run in memory.
7. **Heuristic confidence** is an explanatory simulator score.

See `docs/IMPLEMENTATION_PLAN.md` for build sequence, schemas, testing and exact
run commands.
