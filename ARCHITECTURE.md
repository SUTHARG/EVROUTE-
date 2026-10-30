# Route.ev Architecture

Route.ev is a modular monolith. The API and web UI run as separate processes, while
the route-planning domain remains a single deployable Python application.

## Backend module responsibilities

| Module | Responsibility |
| --- | --- |
| `core/` | EV domain models, energy and charging rules, road graph, filters, and route planning algorithms. |
| `ingest/` | External provider clients, geocoding, station normalization, route/elevation acquisition, and snapshot construction. |
| `api/` | HTTP schemas and endpoints. `snapshot_store.py` owns snapshot file loading and lookup; `main.py` composes the FastAPI application. |
| `analysis/` | Offline experiments and benchmark generation. |
| `tests/` | Unit, API, integration, and algorithm cross-checks. |

Dependency direction should be `api -> core` and `api -> ingest`; `ingest -> core`
is allowed when creating domain snapshots. Domain modules should not depend on
provider clients or FastAPI. Shared geographic primitives live in `core/geo.py`.

## Frontend module responsibilities

| Module | Responsibility |
| --- | --- |
| `src/app/` | Next.js route entry points and page composition. |
| `src/features/trip/model/` | Trip inputs, vehicle choices, waypoints, and feature-level state types. |
| `src/components/` | Reusable visual components such as the sidebar, map, progress modal, and profile drawer. |
| `src/utils/` | Shared formatting and presentation-independent helpers. |
| `src/types/` | API response types; these should ultimately be generated from the backend OpenAPI schema. |

Keep API calls and asynchronous workflows outside visual components as the next
frontend refactor step. Keep map-only code isolated from trip-form state.

## Data and planning rules

- Persist route geometry, edge length, travel time, elevation change, and station
  positions as vehicle-independent snapshot data.
- Treat edge energy as a vehicle-specific derived value. Legacy saved snapshots
  declare the vehicle used to generate their stored energy so planning can recompute
  it for another selected EV.
- Store explicit source and destination road-node IDs in newly built snapshots.
- Keep provider station order separate from corridor order; plan using each
  station's projected `route_distance_km`.
- Keep the current API paths and response schemas stable during module extraction.

## Incremental migration rule

Move one responsibility at a time, preserve existing import paths where external
code or tests rely on them, and keep each migration behavior-equivalent except for
explicit bug fixes recorded in the change summary.
