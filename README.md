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

# Install core dependencies
pip install -r requirements.txt
```

### Frontend Setup
Install frontend dependencies cleanly via `npm ci`:

```bash
cd ui
npm ci
cd ..
```

---

## 2. How to Run API + UI

### Step 1: Start the FastAPI Backend Server
Run the FastAPI backend on port 8000:

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

- API Base URL: `http://127.0.0.1:8000`
- Interactive API Docs (Swagger UI): `http://127.0.0.1:8000/docs`
- Health Check: `http://127.0.0.1:8000/health`
- Preset Vehicles: `http://127.0.0.1:8000/cars`

### Step 2: Start the Next.js Frontend
In a separate terminal, launch the Next.js production or dev server:

```bash
cd ui
npm run dev
```

Open your browser at `http://localhost:3000`.

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
