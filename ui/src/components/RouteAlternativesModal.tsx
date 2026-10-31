"use client";

import React from "react";
import { AlertTriangle, CheckCircle2, Clock3, Map, Route, Zap } from "lucide-react";
import type { RouteAlternativeCandidate } from "@/types/plan";
import { formatDuration } from "../utils/format";

interface RouteAlternativesModalProps {
  routes: RouteAlternativeCandidate[];
  onSelect: (route: RouteAlternativeCandidate) => void;
  onClose: () => void;
}

export const RouteAlternativesModal: React.FC<RouteAlternativesModalProps> = ({
  routes,
  onSelect,
  onClose,
}) => {
  const hasFeasibleRoute = routes.some((route) => route.plan?.feasible);

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="route-alternatives-title"
        className="w-full max-w-3xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
      >
        <header className="border-b border-slate-100 px-6 py-5">
          <div className="flex items-start gap-3">
            <div className="rounded-xl bg-emerald-50 p-2 text-emerald-700">
              <Route size={21} />
            </div>
            <div>
              <h2 id="route-alternatives-title" className="text-lg font-bold text-slate-900">
                Compare route options
              </h2>
              <p className="mt-1 text-sm text-slate-600">
                Each route was checked with your selected EV and charge settings. Choose a route marked EV-feasible.
              </p>
            </div>
          </div>
        </header>

        <div className="grid gap-3 p-5 md:grid-cols-2">
          {routes.map((route) => {
            const feasible = Boolean(route.plan?.feasible);
            const stops = route.plan?.stops.length ?? 0;
            const totalTime = route.plan?.total_time_min;

            return (
              <article
                key={route.snapshot_id}
                className={`rounded-xl border p-4 ${
                  feasible ? "border-emerald-200 bg-emerald-50/50" : "border-amber-200 bg-amber-50/50"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 className="font-bold text-slate-900">Route {route.route_number}</h3>
                  <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                    feasible ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-900"
                  }`}>
                    {feasible ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
                    {feasible ? "EV-feasible" : "Not feasible"}
                  </span>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-lg bg-white/80 p-3">
                    <div className="flex items-center gap-1.5 text-xs text-slate-500"><Map size={13} /> Road distance</div>
                    <div className="mt-1 font-semibold text-slate-900">{route.distance_km.toLocaleString()} km</div>
                  </div>
                  <div className="rounded-lg bg-white/80 p-3">
                    <div className="flex items-center gap-1.5 text-xs text-slate-500"><Clock3 size={13} /> Drive time</div>
                    <div className="mt-1 font-semibold text-slate-900">{formatDuration(route.driving_time_min)}</div>
                  </div>
                  <div className="rounded-lg bg-white/80 p-3">
                    <div className="flex items-center gap-1.5 text-xs text-slate-500"><Zap size={13} /> Corridor stations</div>
                    <div className="mt-1 font-semibold text-slate-900">{route.station_count}</div>
                  </div>
                  <div className="rounded-lg bg-white/80 p-3">
                    <div className="flex items-center gap-1.5 text-xs text-slate-500"><Route size={13} /> Charge stops</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {route.plan ? stops : "Could not plan"}
                      {totalTime != null && <span className="ml-1 font-normal text-slate-500">· {formatDuration(totalTime)} total</span>}
                    </div>
                  </div>
                </div>

                {!feasible && (route.plan?.infeasibility_reason || route.error_message) && (
                  <p className="mt-3 rounded-lg border border-amber-200 bg-white/80 p-3 text-xs leading-relaxed text-amber-900">
                    {route.plan?.infeasibility_reason || route.error_message}
                  </p>
                )}

                <button
                  type="button"
                  disabled={!feasible}
                  onClick={() => onSelect(route)}
                  className="mt-4 w-full rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  {feasible ? "Choose this route" : "Unavailable with current settings"}
                </button>
              </article>
            );
          })}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-6 py-4">
          <p className="text-xs text-slate-500">
            {hasFeasibleRoute
              ? "Selecting a route will show its map and charging-stop plan."
              : "No option is feasible with the current vehicle and battery settings. Try another EV or starting charge."}
          </p>
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            Close
          </button>
        </footer>
      </section>
    </div>
  );
};
