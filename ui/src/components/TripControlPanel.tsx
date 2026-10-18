"use client";

import React from "react";

export interface TripParams {
  carId: string;
  startSoc: number; // 0.0 to 1.0
  reserveSoc: number; // 0.0 to 1.0
  stopThresholdSoc: number; // 0.0 to 1.0
  comfortLambda: number; // 0.0 to 3.0
  K: number; // 10 to 50
  enableFilter: boolean;
}

export interface VehicleOption {
  id: string;
  name: string;
  battery_kwh: number;
  max_dc_kw: number;
  is_placeholder_profile?: boolean;
  description?: string;
}

interface TripControlPanelProps {
  params: TripParams;
  onChange: (newParams: TripParams) => void;
  onPlanTrip: () => void;
  isLoading: boolean;
  vehicles: VehicleOption[];
}

export const TripControlPanel: React.FC<TripControlPanelProps> = ({
  params,
  onChange,
  onPlanTrip,
  isLoading,
  vehicles,
}) => {
  const update = (patch: Partial<TripParams>) => {
    onChange({ ...params, ...patch });
  };

  return (
    <div className="glass-panel rounded-2xl p-6 flex flex-col gap-6">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-4">
        <div>
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <svg className="w-5 h-5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
            </svg>
            Trip & Physics Parameters
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Targeting synthetic corridor snapshot <span className="font-mono text-emerald-300">synthetic_mumbai_pune_v1</span>
          </p>
        </div>

        <button
          id="btn-plan-trip"
          onClick={onPlanTrip}
          disabled={isLoading}
          className={`flex items-center space-x-2 px-5 py-2.5 rounded-xl font-semibold text-sm transition-all duration-200 shadow-lg ${
            isLoading
              ? "bg-emerald-950 text-emerald-400 border border-emerald-800 cursor-not-allowed opacity-75"
              : "bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 shadow-emerald-500/25 active:scale-95"
          }`}
        >
          {isLoading ? (
            <>
              <svg className="animate-spin w-4 h-4 text-emerald-300" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              <span>Optimizing Itinerary...</span>
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
              <span>Calculate Itinerary</span>
            </>
          )}
        </button>
      </div>

      {/* Vehicle Grid loaded strictly from /cars */}
      <div>
        <label className="text-xs font-medium uppercase tracking-wider text-slate-400 block mb-2.5">
          Select Vehicle Model (Loaded from /cars)
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {vehicles.map((v) => {
            const isSelected = params.carId === v.id;
            return (
              <div
                key={v.id}
                id={`vehicle-card-${v.id}`}
                onClick={() => update({ carId: v.id })}
                className={`p-3.5 rounded-xl cursor-pointer border transition-all duration-150 ${
                  isSelected
                    ? "bg-emerald-950/40 border-emerald-500/80 shadow-md shadow-emerald-500/10 ring-1 ring-emerald-500/50"
                    : "bg-slate-900/50 border-slate-800/80 hover:bg-slate-800/50 hover:border-slate-700"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-white">{v.name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                    {v.battery_kwh} kWh
                  </span>
                </div>
                <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400">
                  <span>Max DC: {v.max_dc_kw} kW</span>
                  {v.is_placeholder_profile && (
                    <span className="text-[10px] text-amber-400 font-mono px-1 rounded bg-amber-950/60 border border-amber-600/40">
                      [Placeholder]
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Sliders Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
        {/* Start SoC */}
        <div className="bg-slate-900/40 border border-slate-800/70 rounded-xl p-3.5">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="font-medium text-slate-300">Initial Battery SoC</span>
            <span className="font-mono font-bold text-emerald-400 text-sm">
              {Math.round(params.startSoc * 100)}%
            </span>
          </div>
          <input
            id="slider-start-soc"
            type="range"
            min="0.20"
            max="1.00"
            step="0.05"
            value={params.startSoc}
            onChange={(e) => update({ startSoc: parseFloat(e.target.value) })}
            className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-emerald-500"
          />
          <span className="text-[10px] text-slate-500 mt-1 block">Departure charge from Mumbai</span>
        </div>

        {/* Safety Reserve SoC */}
        <div className="bg-slate-900/40 border border-slate-800/70 rounded-xl p-3.5">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="font-medium text-slate-300">Safety Reserve Floor</span>
            <span className="font-mono font-bold text-rose-400 text-sm">
              {Math.round(params.reserveSoc * 100)}%
            </span>
          </div>
          <input
            id="slider-reserve-soc"
            type="range"
            min="0.05"
            max="0.25"
            step="0.01"
            value={params.reserveSoc}
            onChange={(e) => update({ reserveSoc: parseFloat(e.target.value) })}
            className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-rose-500"
          />
          <span className="text-[10px] text-slate-500 mt-1 block">Strict hard lower battery limit</span>
        </div>

        {/* Comfort Weight Lambda */}
        <div className="bg-slate-900/40 border border-slate-800/70 rounded-xl p-3.5">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="font-medium text-slate-300">Comfort Weight (λ)</span>
            <span className="font-mono font-bold text-cyan-400 text-sm">
              {params.comfortLambda.toFixed(1)}
            </span>
          </div>
          <input
            id="slider-comfort-lambda"
            type="range"
            min="0.0"
            max="3.0"
            step="0.25"
            value={params.comfortLambda}
            onChange={(e) => update({ comfortLambda: parseFloat(e.target.value) })}
            className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-cyan-500"
          />
          <span className="text-[10px] text-slate-500 mt-1 block">
            {params.comfortLambda === 0
              ? "0.0: Pure Travel Time minimization"
              : params.comfortLambda < 1.5
              ? "Balanced Time vs Lounge Amenities"
              : "High Comfort: Prefers Premium plazas"}
          </span>
        </div>

        {/* Resolution K & Greedy Filter */}
        <div className="bg-slate-900/40 border border-slate-800/70 rounded-xl p-3.5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs mb-2">
              <span className="font-medium text-slate-300">Discretization (K)</span>
              <span className="font-mono font-bold text-violet-400 text-sm">{params.K}</span>
            </div>
            <input
              id="slider-k-resolution"
              type="range"
              min="10"
              max="50"
              step="5"
              value={params.K}
              onChange={(e) => update({ K: parseInt(e.target.value) })}
              className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-violet-500"
            />
          </div>

          <div className="flex items-center justify-between mt-3 pt-2 border-t border-slate-800/80">
            <span className="text-xs text-slate-400">Greedy Filter:</span>
            <button
              id="toggle-greedy-filter"
              type="button"
              onClick={() => update({ enableFilter: !params.enableFilter })}
              className={`px-2.5 py-0.5 rounded-full text-xs font-semibold transition-colors ${
                params.enableFilter
                  ? "bg-emerald-950 text-emerald-300 border border-emerald-500/50"
                  : "bg-slate-800 text-slate-400 border border-slate-700"
              }`}
            >
              {params.enableFilter ? "Enabled (Fast)" : "Disabled (All)"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
