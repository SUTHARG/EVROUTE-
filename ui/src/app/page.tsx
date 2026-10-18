"use client";

import React, { useState, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import { BadgeHeader } from "@/components/BadgeHeader";
import { TripControlPanel, TripParams, VehicleOption } from "@/components/TripControlPanel";
import { PlanSummaryCard, PlanData } from "@/components/PlanSummaryCard";
import { RouteSocProfileChart } from "@/components/RouteSocProfileChart";
import { ChargingItineraryTimeline } from "@/components/ChargingItineraryTimeline";
import { ParetoFrontierView } from "@/components/ParetoFrontierView";

// Dynamically import Leaflet Map to avoid SSR window reference errors in Next.js App Router
const RouteMap = dynamic(
  () => import("@/components/RouteMap").then((mod) => mod.RouteMap),
  {
    ssr: false,
    loading: () => (
      <div className="glass-panel h-[460px] flex flex-col items-center justify-center text-slate-400 gap-3 border border-slate-800">
        <svg className="animate-spin w-8 h-8 text-emerald-400" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
        </svg>
        <span className="text-xs font-mono">Loading OpenStreetMap Canvas & Corridor Infrastructure...</span>
      </div>
    ),
  }
);

// Clearly labeled static snapshot demo data (frozen reference from synthetic_mumbai_pune_like.json)
const STATIC_SNAPSHOT_DEMO_PLAN: PlanData = {
  feasible: true,
  total_time_min: 138.12,
  driving_time_min: 112.50,
  charging_time_min: 25.62,
  total_discomfort_min: 9.61,
  cost_J: 147.73,
  build_time_ms: 1.45,
  search_time_ms: 8.92,
  states_expanded: 261,
  edges_relaxed: 1919,
  arrival_soc_dest: 0.28,
  synthetic: true,
  data_provenance: "synthetic",
  is_reliability_simulated: true,
  stops: [
    {
      station_id: "synth_stat_07",
      station_name: "Zeon Charging - Highway Stop 7",
      operator: "Zeon Charging",
      max_kw: 150.0,
      arrival_soc: 0.16,
      departure_soc: 0.72,
      charge_time_min: 25.62,
      dwell_comfort_score: 1.0,
      detour_distance_m: 600.0,
      detour_time_s: 70.0,
      reliability: 0.934,
      is_reliability_simulated: true,
    },
  ],
  corridor_stations: [
    {
      id: "synth_stat_02",
      name: "Tata Power - Panvel Bypass",
      operator: "Tata Power",
      max_kw: 60.0,
      lat: 18.91528,
      lon: 72.90716,
      amenity_score: 0.6,
      amenities: { cafe: 1, toilets: 1 },
      reliability: 0.88,
      is_reliability_simulated: true,
      source: "synthetic",
    },
    {
      id: "synth_stat_05",
      name: "Jio-bp Pulse - Khalapur Tollway",
      operator: "Jio-bp Pulse",
      max_kw: 120.0,
      lat: 18.7900,
      lon: 73.1800,
      amenity_score: 0.85,
      amenities: { restaurant: 2, toilets: 2, fuel: 1 },
      reliability: 0.92,
      is_reliability_simulated: true,
      source: "synthetic",
    },
    {
      id: "synth_stat_07",
      name: "Zeon Charging - Highway Stop 7",
      operator: "Zeon Charging",
      max_kw: 150.0,
      lat: 18.7500,
      lon: 73.4000,
      amenity_score: 1.0,
      amenities: { cafe: 2, restaurant: 1, toilets: 2 },
      reliability: 0.934,
      is_reliability_simulated: true,
      source: "synthetic",
    },
    {
      id: "synth_stat_09",
      name: "Statiq Fast Charger - Lonavala Ghat",
      operator: "Statiq",
      max_kw: 60.0,
      lat: 18.7100,
      lon: 73.5500,
      amenity_score: 0.7,
      amenities: { cafe: 1, fuel: 1 },
      reliability: 0.86,
      is_reliability_simulated: true,
      source: "synthetic",
    },
    {
      id: "synth_stat_12",
      name: "ChargeZone - Talegaon Plaza",
      operator: "ChargeZone",
      max_kw: 100.0,
      lat: 18.6500,
      lon: 73.6800,
      amenity_score: 0.75,
      amenities: { toilets: 1, restaurant: 1 },
      reliability: 0.89,
      is_reliability_simulated: true,
      source: "synthetic",
    },
  ],
  route_soc_profile: [
    { distance_km: 0.0, elevation_m: 14.39, soc: 0.45, lat: 18.9388, lon: 72.8354 },
    { distance_km: 15.2, elevation_m: 18.47, soc: 0.40, lat: 18.91528, lon: 72.90716 },
    { distance_km: 32.5, elevation_m: 24.10, soc: 0.33, lat: 18.8850, lon: 72.9980 },
    { distance_km: 52.0, elevation_m: 145.0, soc: 0.24, lat: 18.7900, lon: 73.1800 },
    { distance_km: 72.4, elevation_m: 580.0, soc: 0.16, lat: 18.7500, lon: 73.4000 },
    { distance_km: 72.5, elevation_m: 580.0, soc: 0.72, lat: 18.7501, lon: 73.4001 },
    { distance_km: 95.0, elevation_m: 610.0, soc: 0.61, lat: 18.7100, lon: 73.5500 },
    { distance_km: 118.0, elevation_m: 580.0, soc: 0.49, lat: 18.6500, lon: 73.6800 },
    { distance_km: 135.0, elevation_m: 560.0, soc: 0.38, lat: 18.5800, lon: 73.7800 },
    { distance_km: 150.0, elevation_m: 555.0, soc: 0.28, lat: 18.5204, lon: 73.8567 },
  ],
  pareto_frontier: [
    { lambda_val: 0.0, total_time_min: 132.5, total_discomfort_min: 16.4, cost_J: 132.5, stops_count: 1, stop_station_ids: ["synth_stat_02"] },
    { lambda_val: 0.5, total_time_min: 135.0, total_discomfort_min: 12.2, cost_J: 141.1, stops_count: 1, stop_station_ids: ["synth_stat_05"] },
    { lambda_val: 1.0, total_time_min: 138.1, total_discomfort_min: 9.61, cost_J: 147.7, stops_count: 1, stop_station_ids: ["synth_stat_07"] },
    { lambda_val: 2.5, total_time_min: 144.3, total_discomfort_min: 7.20, cost_J: 162.3, stops_count: 2, stop_station_ids: ["synth_stat_07", "synth_stat_09"] },
  ],
};

export default function Home() {
  const [params, setParams] = useState<TripParams>({
    carId: "tata_nexon_ev_lr",
    startSoc: 0.45,
    reserveSoc: 0.10,
    stopThresholdSoc: 0.35,
    comfortLambda: 1.0,
    K: 30,
    enableFilter: true,
  });

  const [vehicles, setVehicles] = useState<VehicleOption[]>([]);
  const [plan, setPlan] = useState<PlanData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isDemoSnapshotLoaded, setIsDemoSnapshotLoaded] = useState(false);

  // Cross-component interaction state
  const [focusedStationId, setFocusedStationId] = useState<string | null>(null);
  const [hoveredDistanceKm, setHoveredDistanceKm] = useState<number | null>(null);

  // 1. Fetch vehicle list strictly from /cars API
  const fetchCars = useCallback(async () => {
    try {
      const resp = await fetch("http://127.0.0.1:8000/cars");
      if (resp.ok) {
        const data = await resp.json();
        // data is { car_id: CarObject, ... }
        const carList: VehicleOption[] = Object.values(data).map((c: any) => ({
          id: c.id,
          name: c.name,
          battery_kwh: c.battery_kwh,
          max_dc_kw: c.max_dc_kw,
          is_placeholder_profile: c.is_placeholder_profile,
          description: c.description,
        }));
        setVehicles(carList);
        setApiOnline(true);
        setErrorMessage(null);
      } else {
        throw new Error(`GET /cars returned HTTP ${resp.status}`);
      }
    } catch {
      setApiOnline(false);
      setErrorMessage(
        "FastAPI backend is unreachable at http://127.0.0.1:8000. Start the backend with 'python -m uvicorn api.main:app' to load vehicles and plan routes."
      );
    }
  }, []);

  // 2. Fetch plan strictly from /plan API (NO silent fallback simulation)
  const fetchPlan = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    setIsDemoSnapshotLoaded(false);

    try {
      const resp = await fetch("http://127.0.0.1:8000/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          snapshot_id: "synthetic_mumbai_pune_v1",
          car_id: params.carId,
          start_soc: params.startSoc,
          reserve_soc: params.reserveSoc,
          stop_threshold_soc: params.stopThresholdSoc,
          comfort_weight_lambda: params.comfortLambda,
          K: params.K,
          enable_filter: params.enableFilter,
        }),
      });

      if (resp.ok) {
        const data = await resp.json();
        setPlan(data);
        setApiOnline(true);
        setErrorMessage(null);
      } else {
        const errText = await resp.text();
        throw new Error(`API returned HTTP ${resp.status}: ${errText}`);
      }
    } catch (err: any) {
      setApiOnline(false);
      setPlan(null);
      setErrorMessage(
        `Backend Unreachable: Unable to connect to http://127.0.0.1:8000. Ensure the FastAPI server is running via 'python -m uvicorn api.main:app'. (${err.message || "Network request failed"})`
      );
    } finally {
      setIsLoading(false);
    }
  }, [params]);

  // Load vehicles and initial plan on mount
  useEffect(() => {
    fetchCars();
    fetchPlan();
  }, [fetchCars, fetchPlan]);

  // Handler to load the clearly labeled static snapshot demo
  const handleLoadStaticDemo = () => {
    setPlan(STATIC_SNAPSHOT_DEMO_PLAN);
    setVehicles([
      {
        id: "tata_nexon_ev_lr",
        name: "Tata Nexon EV LR",
        battery_kwh: 40.5,
        max_dc_kw: 50.0,
      },
      {
        id: "mg_zs_ev",
        name: "MG ZS EV",
        battery_kwh: 50.3,
        max_dc_kw: 75.0,
      },
      {
        id: "hyundai_ioniq_5",
        name: "Hyundai Ioniq 5",
        battery_kwh: 72.6,
        max_dc_kw: 350.0,
        is_placeholder_profile: true,
      },
      {
        id: "tata_tiago_ev",
        name: "Tata Tiago EV (Placeholder)",
        battery_kwh: 24.0,
        max_dc_kw: 25.0,
        is_placeholder_profile: true,
      },
    ]);
    setIsDemoSnapshotLoaded(true);
    setErrorMessage(null);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Top Header with Mandatory Provenance Badges */}
      <BadgeHeader corridorName="Mumbai → Pune Synthetic Corridor" distanceKm={150.0} />

      {/* Main Container */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full space-y-6">
        {/* Backend Connectivity Status Bar */}
        <div className="flex flex-wrap items-center justify-between text-xs px-4 py-2.5 rounded-xl bg-slate-900/60 border border-slate-800 gap-3">
          <div className="flex items-center space-x-2.5">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                apiOnline === true
                  ? "bg-emerald-400 shadow-sm shadow-emerald-400/50"
                  : apiOnline === false
                  ? "bg-rose-500 shadow-sm shadow-rose-500/50"
                  : "bg-slate-500"
              }`}
            />
            <span className="text-slate-300 font-medium">
              {apiOnline === true ? (
                <span>Connected to Route.ev FastAPI Backend (<code className="text-emerald-400">http://127.0.0.1:8000</code>)</span>
              ) : (
                <span className="text-rose-400">Backend Server Offline</span>
              )}
            </span>
          </div>

          <div className="flex items-center gap-3 font-mono text-[11px] text-slate-400">
            {isDemoSnapshotLoaded && (
              <span className="px-2 py-0.5 rounded bg-amber-950/80 text-amber-300 border border-amber-500/50 font-bold">
                [STATIC SNAPSHOT DEMO - DATA FROZEN]
              </span>
            )}
            <span>Phase 11 Production Next.js UI</span>
          </div>
        </div>

        {/* Explicit Error State Banner (Requirement 3: No silent fallback simulation) */}
        {errorMessage && (
          <div className="glass-panel border-rose-500/50 bg-rose-950/20 rounded-2xl p-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-start space-x-3.5">
              <div className="w-8 h-8 rounded-lg bg-rose-900/50 border border-rose-500/40 text-rose-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Backend Connection Error</h3>
                <p className="text-xs text-rose-300/90 font-mono mt-1 leading-relaxed max-w-2xl">
                  {errorMessage}
                </p>
                <p className="text-[11px] text-slate-400 mt-2">
                  Client-side silent fallback is disabled. To evaluate the interface without running the backend server, you may load the clearly labeled static snapshot fixture below.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap sm:flex-col gap-2 flex-shrink-0">
              <button
                onClick={() => {
                  fetchCars();
                  fetchPlan();
                }}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-emerald-500 hover:bg-emerald-400 text-slate-950 transition-all active:scale-95 text-center shadow-md shadow-emerald-500/20"
              >
                Retry Backend Connection
              </button>
              <button
                onClick={handleLoadStaticDemo}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-all text-center"
              >
                Load Static Snapshot Demo
              </button>
            </div>
          </div>
        )}

        {/* Trip Controls (Vehicles loaded from /cars only) */}
        <TripControlPanel
          params={params}
          onChange={setParams}
          onPlanTrip={fetchPlan}
          isLoading={isLoading}
          vehicles={vehicles}
        />

        {/* Interactive Leaflet Map (Requirement 1) */}
        {plan && (
          <RouteMap
            routePoints={plan.route_soc_profile}
            chosenStops={plan.stops.map((s) => ({
              station_id: s.station_id,
              station_name: s.station_name,
              operator: s.operator,
              lat: (s as any).lat || (plan.route_soc_profile[Math.floor(plan.route_soc_profile.length / 2)]?.lat ?? 18.75),
              lon: (s as any).lon || (plan.route_soc_profile[Math.floor(plan.route_soc_profile.length / 2)]?.lon ?? 73.4),
              arrival_soc: s.arrival_soc,
              departure_soc: s.departure_soc,
              charge_time_min: s.charge_time_min,
              max_kw: s.max_kw,
              reliability: s.reliability,
            }))}
            corridorStations={plan.corridor_stations || []}
            focusedStationId={focusedStationId}
            hoveredDistanceKm={hoveredDistanceKm}
            onHoverDistance={setHoveredDistanceKm}
            onSelectStation={(stId) => setFocusedStationId(stId)}
          />
        )}

        {/* Plan Summary Card (Requirement 2: live expanded, relaxed, build_ms, search_ms) */}
        <PlanSummaryCard plan={plan} comfortLambda={params.comfortLambda} />

        {/* Elevation & SoC Profile Chart (Distance-aligned hover sync) */}
        {plan && (
          <RouteSocProfileChart
            profile={plan.route_soc_profile}
            stops={plan.stops}
            reserveSoc={params.reserveSoc}
            hoveredDistanceKm={hoveredDistanceKm}
            onHoverDistance={setHoveredDistanceKm}
          />
        )}

        {/* 2-Column Section: Itinerary (Click to focus map) + Pareto Frontier */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {plan && (
            <ChargingItineraryTimeline
              stops={plan.stops}
              selectedStopId={focusedStationId}
              onSelectStop={(stId) => setFocusedStationId(stId)}
            />
          )}

          {plan && (
            <ParetoFrontierView
              points={plan.pareto_frontier}
              currentLambda={params.comfortLambda}
              onSelectLambda={(l) => setParams((prev) => ({ ...prev, comfortLambda: l }))}
            />
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-900 bg-slate-950/80 py-4 mt-8">
        <div className="max-w-7xl mx-auto px-4 text-center text-xs text-slate-500 font-mono">
          Route.ev — Advanced Algorithmic EV Trip Planner & Multi-Objective Engine • Generic Corridor Architecture
        </div>
      </footer>
    </div>
  );
}
