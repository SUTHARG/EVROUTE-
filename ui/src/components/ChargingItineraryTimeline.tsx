"use client";

import React from "react";

interface StopRecord {
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
}

interface ChargingItineraryTimelineProps {
  stops: StopRecord[];
  selectedStopId?: string | null;
  onSelectStop?: (stationId: string) => void;
}

export const ChargingItineraryTimeline: React.FC<ChargingItineraryTimelineProps> = ({
  stops,
  selectedStopId,
  onSelectStop,
}) => {
  if (!stops || stops.length === 0) {
    return (
      <div className="glass-panel rounded-2xl p-6 text-center">
        <div className="w-12 h-12 rounded-full bg-emerald-950/60 text-emerald-400 mx-auto flex items-center justify-center mb-3 border border-emerald-500/30">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h3 className="text-base font-semibold text-white">Direct Non-Stop Journey</h3>
        <p className="text-xs text-slate-400 max-w-md mx-auto mt-1">
          Vehicle battery capacity and initial state of charge are sufficient to complete the entire corridor without recharging.
        </p>
      </div>
    );
  }

  return (
    <div className="glass-panel rounded-2xl p-6 flex flex-col gap-5">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div>
          <h3 className="text-base font-semibold text-white flex items-center gap-2">
            <svg className="w-5 h-5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Charging Itinerary ({stops.length} Stop{stops.length > 1 ? "s" : ""})
          </h3>
          <p className="text-xs text-slate-400">
            Selected via 2-layer dynamic programming optimizing travel time and dwell discomfort
          </p>
        </div>

        <span className="text-xs font-mono text-slate-400">
          Total Charge Duration:{" "}
          <strong className="text-amber-300">
            {Math.round(stops.reduce((acc, s) => acc + s.charge_time_min, 0))} min
          </strong>
        </span>
      </div>

      <div className="space-y-3.5">
        {stops.map((stop, index) => {
          const arrPct = Math.round(stop.arrival_soc * 100);
          const depPct = Math.round(stop.departure_soc * 100);
          const deltaPct = depPct - arrPct;

          const isSelected = selectedStopId === stop.station_id;

          return (
            <div
              key={stop.station_id || `stop-${index}`}
              id={`stop-card-${index}`}
              onClick={() => onSelectStop?.(stop.station_id)}
              className={`border rounded-xl p-4 transition-all duration-200 cursor-pointer ${
                isSelected
                  ? "bg-amber-950/30 border-amber-500 shadow-lg shadow-amber-500/10 ring-1 ring-amber-500/40"
                  : "bg-slate-900/60 border-slate-800/80 hover:border-amber-500/50 hover:bg-slate-900/80"
              }`}
            >
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-3">
                <div className="flex items-center space-x-3">
                  <span className="w-7 h-7 rounded-lg bg-amber-500/20 text-amber-400 font-bold font-mono text-xs flex items-center justify-center border border-amber-500/30">
                    #{index + 1}
                  </span>
                  <div>
                    <h4 className="text-sm font-bold text-white flex items-center gap-2">
                      <span>{stop.station_name}</span>
                      <span className="text-[10px] text-amber-400 font-normal font-sans">(Click to focus map)</span>
                    </h4>
                    <span className="text-xs text-slate-400 flex items-center gap-2">
                      <span>Operator: <strong className="text-slate-300">{stop.operator}</strong></span>
                      <span>•</span>
                      <span className="text-amber-400 font-semibold">{stop.max_kw} kW DC Fast</span>
                    </span>
                  </div>
                </div>

                {/* Simulated Reliability Badge */}
                <div className="flex items-center space-x-2">
                  <span
                    className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono bg-indigo-950/80 text-indigo-300 border border-indigo-500/40"
                    title="Operator base score + clamped Gaussian noise, seeded"
                  >
                    [Simulated] Reliability: {(stop.reliability * 100).toFixed(0)}%
                  </span>
                </div>
              </div>

              {/* Charge Details Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-slate-950/40 rounded-lg p-3 text-xs border border-slate-900">
                <div>
                  <span className="text-slate-500 block mb-0.5 text-[11px]">Battery Transition</span>
                  <div className="font-mono font-bold text-white flex items-center gap-1.5">
                    <span className="text-rose-400">{arrPct}%</span>
                    <span className="text-slate-500">→</span>
                    <span className="text-emerald-400">{depPct}%</span>
                    <span className="text-[10px] text-emerald-500 font-normal">(+{deltaPct}%)</span>
                  </div>
                </div>

                <div>
                  <span className="text-slate-500 block mb-0.5 text-[11px]">Charge Dwell</span>
                  <div className="font-mono font-bold text-amber-300">
                    {stop.charge_time_min.toFixed(1)} min
                  </div>
                </div>

                <div>
                  <span className="text-slate-500 block mb-0.5 text-[11px]">Amenity Comfort</span>
                  <div className="font-mono font-bold text-cyan-300">
                    {Math.round(stop.dwell_comfort_score * 100)}% rating
                  </div>
                </div>

                <div>
                  <span className="text-slate-500 block mb-0.5 text-[11px]">Spur Detour</span>
                  <div className="font-mono text-slate-300">
                    {stop.detour_distance_m > 0
                      ? `${(stop.detour_distance_m / 1000).toFixed(1)} km (${Math.round(stop.detour_time_s / 60)}m)`
                      : "Direct Expressway"}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
