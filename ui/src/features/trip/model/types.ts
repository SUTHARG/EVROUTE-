/** Shared state and input types for the trip-planning feature. */

export type AppTab = "trip" | "plan" | "stations" | "analysis";
export type MobileSheetState = "collapsed" | "half" | "full";

export interface VehicleOption {
  id: string;
  name: string;
  battery_kwh: number;
  max_dc_kw: number;
  supported_connectors?: string[];
  is_placeholder_profile?: boolean;
  description?: string;
}

export interface TripParams {
  snapshotId: string;
  carId: string;
  startSoc: number;
  reserveSoc: number;
  stopThresholdSoc: number;
  comfortLambda: number;
  K: number;
  enableFilter: boolean;
}

export interface LocationWaypoint {
  lat: number;
  lon: number;
  label: string;
}
