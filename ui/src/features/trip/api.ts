import { API_BASE_URL } from "@/config/api";

export interface TripPlanRequest {
  snapshot_id: string;
  car_id: string;
  start_soc: number;
  reserve_soc: number;
  stop_threshold_soc: number;
  comfort_weight_lambda: number;
  K: number;
  enable_filter: boolean;
  from_saved_snapshot: boolean;
}

export interface RouteBuildRequest {
  origin: { lat: number; lon: number; label: string };
  destination: { lat: number; lon: number; label: string };
  use_synthetic: boolean;
  force_refresh: boolean;
  max_routes: number;
}

const endpoint = (path: string) => `${API_BASE_URL}${path}`;

export function fetchVehicles(): Promise<Response> {
  return fetch(endpoint("/cars"));
}

export function requestTripPlan(payload: TripPlanRequest): Promise<Response> {
  return fetch(endpoint("/plan"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function buildCorridor(payload: RouteBuildRequest): Promise<Response> {
  return fetch(endpoint("/routes/build"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function fetchRouteBuildJob(jobId: string): Promise<Response> {
  return fetch(endpoint(`/jobs/${encodeURIComponent(jobId)}`));
}

export function refreshCorridorStations(snapshotId: string): Promise<Response> {
  return fetch(endpoint("/stations/refresh"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ snapshot_id: snapshotId }),
  });
}
