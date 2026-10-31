# Route.ev — Physics-Informed Algorithmic EV Highway Trip Planner

**Route.ev** is a multi-objective electric vehicle (EV) itinerary optimization engine designed for long-distance highway corridors (such as Mumbai $\to$ Pune). It formulates and solves the joint routing, charger selection, and battery dwell scheduling problem via an exact 2-layer state-space dynamic program, balancing total travel time against traveler dwell discomfort across a Pareto frontier.

---

## 1. Setup Instructions

### Prerequisites
- **Python**: 3.11, 3.12, or 3.13
- **Node.js**: v20+ or v24+ with `npm` (v10+)
- **Git**

### Backend Setup
Clone the repository and set up a Python virtual environment:

```bash
git clone https://github.com/your-username/route-ev.git
cd route-ev

# Create and activate virtual environment
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install core runtime dependencies
pip install -r requirements.txt

# Or install for development and testing:
pip install -r requirements-dev.txt
# Alternatively, editable install via pyproject.toml:
pip install -e ".[dev]"
```

### Frontend Setup
Install frontend dependencies cleanly via `npm ci`:

```bash
cd ui
npm ci
# Configure API URL if not using default http://127.0.0.1:8000
# (Set NEXT_PUBLIC_API_BASE_URL in ui/.env)
cd ..
```

---

## 2. How to Run API + UI

### Step 1: Start the FastAPI Backend Server
Run the FastAPI backend on port 8000:

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

- API Base URL: `http://127.0.0.1:8000` (Configurable via `NEXT_PUBLIC_API_BASE_URL`)
- Interactive API Docs (Swagger UI): `http://127.0.0.1:8000/docs`
- Health Check: `http://127.0.0.1:8000/health`
- Preset Vehicles: `http://127.0.0.1:8000/cars`

### Step 2: Start the Next.js Frontend
In a separate terminal, launch the Next.js production or dev server:

```bash
cd ui
npm run dev
```

Open your browser at `http://localhost:3000`. By default, the frontend connects to `http://127.0.0.1:8000` unless overridden by `NEXT_PUBLIC_API_BASE_URL`.

To build the production web bundle:
```bash
cd ui
npm run build
npm start
```

---

## 3. Data Provenance Policy

Route.ev enforces strict data classification to prevent silent data invention and ensure full academic and engineering integrity:

| Tier | Identifier | Description | UI Badge |
|---|---|---|---|
| **Verified** | `verified` | Stations whose coordinates, operator, connector types, and power ratings have been authenticated against official operator registries or verified URLs with an inspection date. | None (Verified) |
| **Manual Unverified** | `manual_unverified` | Station data entered manually or sourced from illustrative lists without cryptographic or primary URL verification. | `[UNVERIFIED DATA]` (Orange Badge) |
| **Synthetic** | `synthetic` | Topography, road nodes, elevation profiles, or station catalogs programmatically generated for generic corridor benchmarking. | `[SYNTHETIC DATA]` (Amber Badge) |

- **Zero-Tolerance Rule**: Metadata flags like `synthetic: false` can never be hard-coded. Provenance is computed directly from station catalogs and snapshot metadata.
- **Reliability Simulation**: Reliability figures are always flagged with `[Simulated Reliability]` across all API responses and UI cards.

---

## 4. Architectural Assumptions & Limitations

1. **Simulated Reliability**:
   Station operational reliability scores are generated synthetically using an operator baseline score plus clamped Gaussian noise with a deterministic seed (`core/models.py`). They do not reflect live real-time IoT hardware telemetry.
2. **Two Candidate Paths per Station Pair**:
   For each pair of charging stations $(u, v)$ in the reduced graph, exactly two candidate physical paths are evaluated:
   - **Fastest Path**: Dijkstra search minimizing road travel time.
   - **Min-Energy Path**: Bellman-Ford / Johnson search minimizing net energy (incorporating downhill regenerative braking).
   Alternative intermediate paths on the road graph are pruned.
3. **Corridor Graph Approximation**:
   Highway infrastructure is modeled as a primary arterial corridor graph with perpendicular spur detours to charging stations, rather than an unconstrained 2D road mesh.
4. **Environmental & External Loads**:
   The current physical consumption model focuses on rolling resistance ($C_{rr}$), aerodynamic drag ($C_d \cdot A$), drivetrain/motor efficiency ($\eta_{\text{drive}}$), and regenerative recovery ($\eta_{\text{regen}}$). It does not dynamically model live traffic jams, ambient temperature swings (battery thermal degradation), headwind variations, or cabin air conditioning (HVAC) electrical loads.

---

## 5. Algorithmic Complexity & Analysis Directory

The `analysis/` directory contains mathematical proofs, empirical studies, and benchmarking suites:

- **[`analysis/np_hardness.md`](analysis/np_hardness.md)**:
  Formal mathematical proof of NP-hardness for the comfort-budgeted EV routing problem via Karp reduction from 0/1 Knapsack. Proves that the minimum feasible recharge at each station is exactly $\Delta E = 9.0$ kWh and proves that recharging more only increases journey time and weakly/strictly increases dwell discomfort (since dwell $\ge 20$ min and the dwell window penalty is non-decreasing on $[20, \infty)$). Also details the $\mathcal{O}((|E_c|K + |V_c|K^2) D_{\max})$ pseudo-polynomial dynamic program.
- **[`analysis/complexity.md`](analysis/complexity.md)**:
  Comprehensive asymptotic complexity derivations for the 2-layer state graph Dijkstra search ($\mathcal{O}((|E_c|K + |V_c|K^2)\log(|V_c|K))$), explaining why the finite battery horizon bounds $|E_c| = \mathcal{O}(|V_c|)$ on corridor topologies.
- **[`analysis/benchmarks.py`](analysis/benchmarks.py)**:
  Full benchmarking suite executing 5 algorithmic studies:
  1. Search time and graph-build time scaling vs $|V_c|$.
  2. Search time scaling vs SoC resolution $K$.
  3. Exponential Brute-Force vs Polynomial DP comparison.
  4. $K$-convergence of plan cost $J(K)$ on nested power-of-two grids ($K \in [25, 400]$).
  5. Contracted Charger Graph DP vs Uncontracted Full Road Graph DP (asserting equal optimal cost $J$, measuring $|E_c|$ vs $|V_c|$, and reporting build time separately).
- **[`analysis/elevation_study.py`](analysis/elevation_study.py)**:
  Investigation of elevation noise and moving average / Savitzky-Golay smoothing on net climb energy and plan feasibility.
- **[`analysis/filter_price_study.py`](analysis/filter_price_study.py)**:
  Quantitative evaluation of the greedy range-preserving charger filter speedup vs optimality gap.
- **[`analysis/heuristic_dwell_study.py`](analysis/heuristic_dwell_study.py)**:
  Comparison between the 5-point heuristic dwell target set and the exact exhaustive discrete departure level enumeration.
- **[`analysis/plots/`](analysis/plots/)**:
  Saved high-resolution visualization charts generated from empirical benchmark runs.

---

## 6. Test Suite & Code Quality

Execute the comprehensive test suite (unit tests, property-based Hypothesis tests, parser tests, and Bellman-Ford/Johnson graph tests):

```bash
# Run pytest with verbose reporting
pytest -v

# Run linter
ruff check .

# Verify clean frontend build
cd ui && npm ci && npm run build
```

---

## 7. Demo Build & Enabling Advanced Features

### Demo Mode Overview
The Demo Build provides a streamlined, presentation-ready experience:
- **Live Station Data**: Sourced from Google Places API (New), Open Charge Map v3, local Open Charge Map snapshot (`data/ocm_snapshot/POI.json.gz`), and user-verified charging hubs (`data/stations/verified_stations.csv`), with 100m spatial deduplication and dual caching (24h static, 5m availability).
- **Default 250 km Flat-Road Range**: All vehicle presets are calibrated to deliver exactly 250 km on flat highway cruise with a full usable battery (`DEFAULT_RANGE_KM = 250`).
- **4-Wheeler Passenger EV Standard**: Enforces CCS2, Type 2 (AC), and CHAdeMO standards; excludes 2W/3W plugs; unlisted connectors appear as "connector unknown" and are excluded from routing.
- **Hiding Advanced Features**: In demo mode (`NEXT_PUBLIC_DEMO_MODE=true`), the technical **Analysis** tab, Pareto multi-objective trade-off chart, raw algorithm state-expansion statistics, benchmark speedup cards, and Advanced Settings accordion are hidden from the UI to keep the interface uncluttered.

### How to Enable Advanced Features & Full Developer Mode
To reveal the Analysis tab, Pareto frontier explorer, algorithm performance counters, and Advanced Settings:

1. Edit your `.env` file (or `ui/.env`):
   ```env
   # Set to false to reveal all advanced/research tools
   NEXT_PUBLIC_DEMO_MODE=false

   # Set to true to switch back to manufacturer-rated vehicle ranges
   USE_CAR_SPECIFIC_RANGE=true

   # Optional: use Mapbox Streets tiles instead of the default OpenStreetMap tiles
   # Create a public token in your Mapbox account and restrict it to your app's URL.
   NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN=
   ```
   Mapbox tiles are enabled when this token is set. If it is blank, the map uses OpenStreetMap.
2. Restart or rebuild the Next.js frontend:
   ```bash
   cd ui
   npm run build
   npm run dev
   ```

---

## 8. Open Charge Map Offline Snapshot Setup (No API Key Required)

If you do not have an `OCM_API_KEY`, Route.ev supports an offline snapshot provider using the official Open Charge Map public export dataset.

### File Details
- **File Name**: `POI.json.gz` (or uncompressed `POI.json`)
- **Source Repository**: [openchargemap/ocm-data on GitHub](https://github.com/openchargemap/ocm-data)
- **Note on File Size**: Check the asset file size directly on GitHub releases before downloading (repository archive size varies with upstream releases).

### Exact Steps for Manual Download
1. Visit the Open Charge Map data repository releases:
   - URL: `https://github.com/openchargemap/ocm-data`
2. Download the latest exported archive (`poi.json.gz` or `POI.json.gz`).
3. Place the downloaded file into the directory:
   ```bash
   data/ocm_snapshot/POI.json.gz
   ```
   *(This directory is ignored by Git in `.gitignore` to avoid committing large binary datasets).*
4. The backend `OCMSnapshotProvider` will automatically detect the file, filter to India charging stations (filtered strictly by ISO country code `"IN"`), index them spatially in memory, and provide charging coverage along your corridor without requiring any API keys.

---

## 9. Data Attributions & Licensing

- **OpenStreetMap**: Map data and road geometry &copy; [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), licensed under the Open Database License (ODbL).
- **Open Charge Map**: Charging station data courtesy of [Open Charge Map](https://openchargemap.org) and its contributors, licensed under the Creative Commons Attribution 4.0 International License ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)). Note that individual points of interest provided to Open Charge Map by external data providers specify their own originator data provider and license per station.
- **Open-Meteo**: Highway elevation profiles powered by the Open-Meteo Elevation API (CC BY 4.0).
- **OSRM**: Road network routing powered by Project-OSRM.

---

## 10. Project Structure and Module Reference

This section maps the repository files to their responsibilities. Start with `api/main.py` for HTTP behavior, `core/planner.py` for the route optimizer, `ingest/build_snapshot.py` for creating corridor data, and `ui/src/app/page.tsx` for the main web application flow.

### Repository-level files

| File | Purpose |
|---|---|
| `README.md` | Setup, run instructions, data provenance, architecture assumptions, analysis notes, and this module reference. |
| `ARCHITECTURE.md` | Module boundaries, dependency direction, data rules, and incremental migration guidance. |
| `pyproject.toml` | Python package metadata, runtime dependencies, optional dev dependencies, and pytest/Ruff configuration. |
| `requirements.txt` | Core Python runtime dependencies for the API and planner. |
| `requirements-dev.txt` | Additional test and lint dependencies. |
| `.env.example` | Backend environment-variable template. Copy to `.env` and provide local values; never commit real keys. |

### `api/` — FastAPI application

| File | Purpose |
|---|---|
| `api/main.py` | Creates the FastAPI app, runs startup loading, configures CORS, and implements health, vehicle, snapshot, geocoding, multi-route build, job-status, planning, Pareto, benchmark, and station-refresh endpoints. |
| `api/schemas.py` | Pydantic request and response models that define the HTTP contract, including summaries of built route alternatives. |
| `api/snapshot_store.py` | Loads saved corridor JSON files into the in-memory snapshot cache and resolves snapshot IDs for API handlers. |
| `api/__init__.py` | Marks `api` as a Python package. |

### `core/` — domain models and route-planning algorithms

| File | Purpose |
|---|---|
| `core/models.py` | Shared domain models for vehicles, stations, road nodes and edges, corridor snapshots, trips, charge stops, route profiles, Pareto points, and plans. Also defines preset vehicles. |
| `core/geo.py` | Geographic distance helpers shared by routing and ingestion code. |
| `core/road_graph.py` | Directed road-graph representation and graph operations over road nodes and edges. |
| `core/bellman_ford.py` | Bellman-Ford, Johnson reweighting, Dijkstra, negative-cycle detection, and path reconstruction. Supports regenerative edges with negative energy weights. |
| `core/charger_graph.py` | Contracts the road graph to charger candidates and precomputes fastest and minimum-energy transitions between them. |
| `core/energy.py` | Vehicle energy model: rolling and aerodynamic loads, elevation effects, regenerative recovery, SoC propagation, and battery-feasibility tables. |
| `core/charging.py` | CC-CV charging-time calculations, SoC inversion, charge-level options, and dwell-window target generation. |
| `core/comfort.py` | Calculates dwell discomfort and penalties for charging behavior relative to the preferred stop window. |
| `core/filters.py` | Scores and reduces candidate charging stations while restoring candidates when needed to preserve range/connectivity. |
| `core/planner.py` | Main optimization engine. Searches a layered charger/SoC state graph for travel-time and comfort trade-offs and constructs plan results. |
| `core/brute_force.py` | Independent exhaustive solver for small cases, used as a reference for validating the dynamic-programming planner. |
| `core/oracle.py` | Exhaustive multi-route oracle for small acyclic road topologies, including charger subsets and discrete charging decisions. |
| `core/config.py` | Loads and provides access to backend settings and provider keys without exposing secret values in API responses. |
| `core/__init__.py` | Marks `core` as a Python package. |

### `ingest/` — data collection and corridor construction

| File | Purpose |
|---|---|
| `ingest/build_snapshot.py` | End-to-end corridor builder: obtains route geometry, road nodes, elevation, and charging stations, then assembles a reusable snapshot. Also provides a CLI. |
| `ingest/route.py` | OSRM client for primary and alternative road routes plus spur detours, with configurable service URL and disk caching. |
| `ingest/elevation.py` | Samples elevation data, smooths noisy profiles, and calculates route ascent/descent inputs. |
| `ingest/geocode.py` | Nominatim geocoding and autocomplete search with throttling, disk cache, and offline fallbacks. |
| `ingest/station_providers.py` | Common station-provider interface and clients for verified CSV, Google Places, Open Charge Map, and Overpass. Normalizes connector data, merges records, and deduplicates nearby results. |
| `ingest/stations.py` | Station ingestion policies, provenance classification, curated/verified station loading, Overpass queries, reliability labels, and route-distance calculations. |
| `ingest/ocm_snapshot.py` | Reads a local Open Charge Map export, filters and indexes Indian charging points, normalizes records, and finds stations near a corridor. |
| `ingest/amenities.py` | Queries nearby amenities through Overpass and computes station amenity scores. |
| `ingest/cache.py` | Small disk-backed JSON cache used to reduce repeated external API requests. |
| `ingest/synthetic.py` | Generates synthetic corridor snapshots and random geometric graphs for demos, offline work, and algorithm experiments. |
| `ingest/topologies.py` | Builds small diamond and ladder corridor graphs for multi-route algorithm checks. |
| `ingest/__init__.py` | Marks `ingest` as a Python package. |

### `data/` — saved and curated input data

| Path | Purpose |
|---|---|
| `data/snapshots/*.json` | Saved corridor snapshots that the API can load and plan against. The committed synthetic snapshot is illustrative. |
| `data/stations/verified_stations.csv` | User-maintained station records. Verified rows need source URLs and inspection dates to receive verified provenance. |
| `data/ocm_snapshot/` | Optional location for the compressed Open Charge Map export. It is intentionally kept out of Git because the export can be large. |
| `data/cache/` | Local cache for provider, geocoding, and route requests; cache contents are generated during use. |

### `analysis/` — research, benchmarks, and generated results

| File or path | Purpose |
|---|---|
| `analysis/benchmarks.py` | Runs planner scaling, brute-force comparison, SoC-grid convergence, and reduced-versus-full graph benchmarks; can write result data and plots. |
| `analysis/benchmark_results.json` | Recorded benchmark output consumed by reports or the UI. |
| `analysis/elevation_study.py` | Studies elevation smoothing choices and their effect on energy and feasibility. |
| `analysis/filter_price_study.py` | Measures the speedup and optimality impact of greedy charger filtering. |
| `analysis/heuristic_dwell_study.py` | Compares heuristic dwell targets with exhaustive discrete departure-level enumeration. |
| `analysis/complexity.md` | Derives the asymptotic costs of the reduced charger-graph dynamic program. |
| `analysis/np_hardness.md` | Documents the reduction proving the comfort-budgeted problem is NP-hard. |
| `analysis/plots/` | Saved charts for benchmark runtime, grid convergence, brute-force comparison, and elevation smoothing. |

### `tests/` — automated checks and fixtures

| File | Main coverage |
|---|---|
| `tests/test_api.py` | FastAPI endpoint behavior and request/response handling. |
| `tests/test_audit_fixes.py` | Regression checks for previously identified correctness and audit issues. |
| `tests/test_bellman_ford.py` | Shortest paths, Johnson reweighting, and negative-weight road edges. |
| `tests/test_candidate_restoration_and_env.py` | Charger candidate restoration and configuration/environment behavior. |
| `tests/test_charging.py` | CC-CV charging times, SoC inversion, and charging options. |
| `tests/test_comfort.py` | Dwell-discomfort calculations and penalty behavior. |
| `tests/test_demo_mode.py` | Demo-mode configuration and feature visibility. |
| `tests/test_diamond_oracle.py` | Multi-route correctness against the exhaustive oracle on diamond graphs. |
| `tests/test_energy.py` | Energy use, regeneration, battery constraints, and vehicle-specific snapshot energy. |
| `tests/test_filters_and_charger_graph.py` | Candidate filtering, connectivity restoration, and reduced graph transitions. |
| `tests/test_geocode.py` | Geocoding query parsing, normalization, caching, and result behavior. |
| `tests/test_geometry.py` | Route geometry and geographic calculations. |
| `tests/test_knapsack_gadget.py` | Correctness of the NP-hardness reduction construction. |
| `tests/test_live_route_and_provenance.py` | Live route construction, source metadata, and provenance labels. |
| `tests/test_parsers.py` | Parsing and normalization of external provider payloads. |
| `tests/test_property_bf.py` | Property-based checks for shortest-path algorithms. |
| `tests/test_route_builder.py` | Corridor snapshot build pipeline and route-builder behavior. |
| `tests/test_stop_position.py` | Charger ordering and position along a route. |
| `tests/test_synthetic.py` | Synthetic graph and corridor generation. |
| `tests/fixtures/` | Small saved provider responses and route/station examples used by tests without live API calls. |

### `ui/` — Next.js and React frontend

| File or path | Purpose |
|---|---|
| `ui/src/app/page.tsx` | Main client page. Coordinates trip inputs, backend requests, route-build job polling, EV feasibility checks across route alternatives, the selected plan, errors, tabs, and map state. |
| `ui/src/app/layout.tsx` | Root Next.js layout and page metadata. |
| `ui/src/app/globals.css` | Global styles, Tailwind layers, and application-wide layout rules. |
| `ui/src/app/favicon.ico` | Browser tab icon. |
| `ui/src/components/TopBar.tsx` | Header with app status, corridor name, and sidebar controls. |
| `ui/src/components/Sidebar.tsx` | Trip input and settings panel, sample routes, vehicle selection, station/plan views, and analysis controls. |
| `ui/src/components/RouteMap.tsx` | Leaflet map, route lines, charging-station markers and details, focus behavior, and optional Mapbox Streets tiles. |
| `ui/src/components/RouteProgressModal.tsx` | Progress display for asynchronous corridor-building jobs. |
| `ui/src/components/BackendErrorModal.tsx` | API connection and planning error display with retry/dismiss actions. |
| `ui/src/components/RouteAlternativesModal.tsx` | Compares built road alternatives by distance, drive time, corridor-station count, charging stops, and EV feasibility; lets the user select a feasible route. |
| `ui/src/components/RouteSocProfileDrawer.tsx` | Elevation and battery SoC profile visualization for the planned route. |
| `ui/src/config/api.ts` | Resolves the API base URL from `NEXT_PUBLIC_API_BASE_URL` or its fallback. |
| `ui/src/features/trip/api.ts` | Typed frontend calls for vehicles, trip planning, route building, job polling, and station refresh. |
| `ui/src/features/trip/hooks/useGeocodeAutocomplete.ts` | Geocoding search state and API requests for origin/destination suggestions. |
| `ui/src/features/trip/model/types.ts` | Frontend types for trip settings, waypoints, vehicles, tabs, and mobile panel state. |
| `ui/src/types/plan.ts` | TypeScript shapes for plan, stop, route-profile, station, availability, and Pareto API data. |
| `ui/src/utils/format.ts` | Shared display formatting for durations, distances, and percentages. |
| `ui/src/utils/station.ts` | Shared station power, availability freshness, and fetched-time presentation helpers. |
| `ui/src/data/benchmark_results.json` | Benchmark data displayed in the analysis UI. |
| `ui/public/` | Static public assets, including the Next.js starter SVGs. |
| `ui/package.json` and `ui/package-lock.json` | Frontend scripts and pinned JavaScript dependency graph. |
| `ui/next.config.ts`, `ui/tsconfig.json`, `ui/eslint.config.mjs` | Next.js, TypeScript, and ESLint configuration. |
| `ui/.env.example` | Frontend environment template for API base URL, demo mode, and optional public Mapbox token. |
| `ui/AGENTS.md` | Local development guidance for work in the frontend directory. |

### Typical request flow

1. The browser loads vehicle presets from `GET /cars` and sends place searches to `GET /geocode`.
2. The user selects a saved route or submits origin and destination. For a new route, the UI calls `POST /routes/build` and polls `GET /jobs/{job_id}`.
3. The backend asks OSRM for up to three driving route candidates, collects route geometry, elevation, and station candidates for each through `ingest/`, then stores the corridor snapshots. OSRM may return fewer alternatives than requested.
4. The UI calls `POST /plan` for each snapshot using the selected EV settings. It presents the alternatives with feasibility, distance, drive time, and charging-stop information. EV-feasible routes can be chosen for navigation; routes without enough charging coverage can still be previewed on the map and are labeled as not EV-feasible.
5. `core/` builds candidate charger transitions, simulates energy and charging, and finds an itinerary balancing travel time and dwell discomfort. The API returns a plan for the map, stop list, and SoC/elevation profile.

