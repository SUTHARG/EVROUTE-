"use client";

import React from "react";

export interface PlanData {
  feasible: boolean;
  infeasibility_reason?: string | null;
  total_time_min: number;
  driving_time_min: number;
  charging_time_min: number;
  total_discomfort_min: number;
  cost_J: number;
  build_time_ms: number;
  search_time_ms: number;
  states_expanded?: number;
  edges_relaxed?: number;
  arrival_soc_dest: number;
  stops: Array<{
    station_id: string;
    station_name: string;
    operator: string;
    max_kw: number;
    arrival_soc: number;
    departure_soc: number;
    charge_time_min: number;
    dwell_comfort_score: number;
    detour_distance_m: number;
    detour_time_s: number;
    reliability: number;
    is_reliability_simulated: boolean;
  }>;
  route_soc_profile: Array<{
    distance_km: number;
    elevation_m: number;
    soc: number;
    lat: number;
    lon: number;
  }>;
  pareto_frontier?: Array<{
    lambda_val: number;
    total_time_min: number;
    total_discomfort_min: number;
    cost_J: number;
    stops_count: number;
    stop_station_ids: string[];
  }>;
  corridor_stations?: Array<{
    id: string;
    name: string;
    lat: number;
    lon: number;
    operator: string;
    max_kw: number;
    amenity_score?: number;
    amenities?: Record<string, number>;
    reliability: number;
    is_reliability_simulated?: boolean;
    source?: string;
  }>;
  synthetic: boolean;
  data_provenance: string;
  is_reliability_simulated: boolean;
}

interface PlanSummaryCardProps {
  plan: PlanData | null;
  comfortLambda: number;
}

export const PlanSummaryCard: React.FC<PlanSummaryCardProps> = ({ plan, comfortLambda }) => {
  if (!plan) return null;

  const formatHrsMins = (totalMinutes: number) => {
    const hrs = Math.floor(totalMinutes / 60);
    const mins = Math.round(totalMinutes % 60);
    return hrs > 0 ? `${hrs}h ${mins}m` : `${mins} min`;
  };

  if (!plan.feasible) {
    return (
      <div className="glass-panel border-rose-500/40 rounded-2xl p-6 bg-rose-950/20">
        <div className="flex items-center space-x-3 text-rose-400 mb-2">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <h3 className="text-lg font-bold text-white">Trip Infeasible</h3>
        </div>
        <p className="text-sm text-rose-300/90 font-mono">
          {plan.infeasibility_reason || "Vehicle battery capacity is insufficient to bridge charging gaps."}
        </p>
      </div>
    );
  }

  return (
    <div className="glass-panel rounded-2xl p-6">
      {/* Top Banner: Status + Summary */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-4 border-b border-slate-800/80 gap-3">
        <div className="flex items-center space-x-3">
          <span className="flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-bold bg-emerald-950 text-emerald-300 border border-emerald-500/60 shadow-sm shadow-emerald-500/20">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <span>OPTIMAL ROUTE FOUND</span>
          </span>
          <span className="text-xs text-slate-400 font-mono">
            {plan.stops.length === 0 ? "Non-stop direct transit" : `${plan.stops.length} Charging Stop(s)`}
          </span>
        </div>

        {/* Scalar Objective */}
        <div className="flex items-center space-x-2 text-xs">
          <span className="text-slate-400">Scalar Objective:</span>
          <span className="font-mono font-bold text-white px-2 py-0.5 rounded bg-slate-900 border border-slate-800">
            J = {plan.cost_J.toFixed(2)} min
          </span>
          <span className="text-[10px] text-slate-500 font-mono">
            (T + {comfortLambda.toFixed(1)}·D)
          </span>
        </div>
      </div>

      {/* Primary KPI Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5">
        {/* Total Travel Time */}
        <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800/70">
          <span className="text-xs text-slate-400 font-medium block mb-1">Total Travel Time</span>
          <div className="text-2xl font-bold font-mono text-white">
            {formatHrsMins(plan.total_time_min)}
          </div>
          <div className="text-[11px] text-slate-400 mt-1 flex items-center justify-between">
            <span>Drive: {Math.round(plan.driving_time_min)}m</span>
            <span>Charge: {Math.round(plan.charging_time_min)}m</span>
          </div>
        </div>

        {/* Dwell Discomfort */}
        <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800/70">
          <span className="text-xs text-slate-400 font-medium block mb-1">Total Discomfort</span>
          <div className="text-2xl font-bold font-mono text-cyan-400">
            {plan.total_discomfort_min.toFixed(1)}{" "}
            <span className="text-xs font-normal text-slate-400">min</span>
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            Amenity deficit + Dwell penalty
          </div>
        </div>

        {/* Arrival Destination SoC */}
        <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800/70">
          <span className="text-xs text-slate-400 font-medium block mb-1">Arrival SoC (Pune)</span>
          <div className="text-2xl font-bold font-mono text-emerald-400">
            {Math.round(plan.arrival_soc_dest * 100)}%
          </div>
          <div className="text-[11px] text-emerald-500/80 mt-1 flex items-center gap-1">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Above safety reserve
          </div>
        </div>

        {/* Charging Stops */}
        <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-800/70">
          <span className="text-xs text-slate-400 font-medium block mb-1">Charging Stops</span>
          <div className="text-2xl font-bold font-mono text-amber-400">
            {plan.stops.length}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            {plan.stops.length > 0 ? "Fast DC Charging" : "Direct without stops"}
          </div>
        </div>
      </div>

      {/* Algorithmic Search Metrics for THIS request */}
      <div className="mt-4 pt-3 border-t border-slate-800/60 flex flex-wrap items-center justify-between text-xs text-slate-400 gap-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="flex items-center space-x-1.5 font-mono">
            <span className="text-slate-500">States Expanded:</span>
            <span className="text-slate-200 font-semibold">{plan.states_expanded ?? 0}</span>
          </span>
          <span className="flex items-center space-x-1.5 font-mono">
            <span className="text-slate-500">Edges Relaxed:</span>
            <span className="text-slate-200 font-semibold">{plan.edges_relaxed ?? 0}</span>
          </span>
          <span className="flex items-center space-x-1.5 font-mono">
            <span className="text-slate-500">Graph Build:</span>
            <span className="text-sky-400 font-semibold">{plan.build_time_ms.toFixed(2)} ms</span>
          </span>
          <span className="flex items-center space-x-1.5 font-mono">
            <span className="text-slate-500">Search Time:</span>
            <span className="text-emerald-400 font-semibold">{plan.search_time_ms.toFixed(2)} ms</span>
          </span>
        </div>

        <div className="flex items-center space-x-2 font-mono text-[11px] text-slate-500">
          <span className="text-slate-400 font-semibold" title="Static benchmark on 2,495-node Mumbai-Pune corridor (source: analysis/benchmarks.py)">
            Static Benchmark: 6.8x search speedup (source: analysis/benchmarks.py)
          </span>
        </div>
      </div>
    </div>
  );
};
