export interface StationAvailability {
  available: number;
  total: number;
  out_of_service: number;
  last_updated?: string | null;
}

export interface ChargingStopInfo {
  station_id: string;
  station_name: string;
  operator: string;
  lat: number;
  lon: number;
  arrival_soc: number;
  departure_soc: number;
  charge_time_min: number;
  energy_charged_kwh?: number;
  max_kw: number;
  max_ac_kw?: number | null;
  max_dc_kw?: number | null;
  charging_mode?: "ac" | "dc" | string;
  charging_power_kw?: number;
  charger_count?: number;
  connector_types?: string[];
  availability?: StationAvailability | null;
  reliability: number;
  route_distance_km?: number;
  distance_from_origin_km?: number;
  power_assumed?: boolean;
  connector_assumed?: boolean;
  connector_unknown?: boolean;
  amenity_known?: boolean;
  spur_estimated?: boolean;
  source?: string;
  source_url?: string | null;
  fetched_at?: string | null;
  verified?: boolean;
  data_provider_name?: string | null;
  data_provider_license?: string | null;
}

export interface RouteProfilePoint {
  distance_km: number;
  elevation_m: number;
  soc: number;
  lat: number;
  lon: number;
  event?: "drive" | "regen" | "spur_in" | "charge" | "spur_out" | string;
}

export interface CorridorStationInfo {
  id: string;
  name: string;
  lat: number;
  lon: number;
  operator: string;
  max_kw: number;
  max_ac_kw?: number | null;
  max_dc_kw?: number | null;
  charger_count?: number;
  connector_types?: string[];
  availability?: StationAvailability | null;
  amenity_score?: number;
  amenities?: Record<string, number>;
  amenity_known?: boolean;
  reliability: number;
  is_reliability_simulated?: boolean;
  source?: string;
  source_url?: string | null;
  fetched_at?: string | null;
  verified?: boolean;
  connector_unknown?: boolean;
  power_assumed?: boolean;
  connector_assumed?: boolean;
  spur_estimated?: boolean;
  route_distance_km?: number;
  data_provider_name?: string | null;
  data_provider_license?: string | null;
}

export interface ParetoPoint {
  lambda_val: number;
  total_time_min: number;
  total_discomfort_min: number;
  stops_count: number;
  is_supported: boolean;
}

export interface TripPlan {
  feasible: boolean;
  total_time_min: number;
  driving_time_min: number;
  charging_time_min: number;
  total_energy_kwh: number;
  arrival_soc_dest: number;
  stops: ChargingStopInfo[];
  route_soc_profile: RouteProfilePoint[];
  route_geometry?: [number, number][];
  route_distance_km?: number | number[];
  corridor_stations: CorridorStationInfo[];
  pareto_frontier?: ParetoPoint[];
  infeasibility_reason?: string;
  source_name?: string;
  destination_name?: string;
  snapshot_id?: string;
  sources_used?: string[];
  is_demo_mode?: boolean;
  elevation_available?: boolean;
  synthetic?: boolean;
  is_reliability_simulated?: boolean;
  data_provenance?: string;
  is_live_build?: boolean;
  states_expanded?: number;
  edges_relaxed?: number;
  build_time_ms?: number;
  search_time_ms?: number;
  api_calls?: Record<string, number>;
  corridor_metadata?: {
    total_length_km: number;
    station_count: number;
    unverified_illustrative: boolean;
  };
}


export interface VehicleOptionItem {
  id: string;
  name: string;
  battery_kwh: number;
  max_dc_kw: number;
  consumption_kwh_per_km?: number;
  real_range_km?: number;
  supported_connectors?: string[];
  is_placeholder_profile?: boolean;
  description?: string;
}
