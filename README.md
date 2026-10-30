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

