"use client";

import React from "react";

interface BadgeHeaderProps {
  corridorName?: string;
  distanceKm?: number;
}

export const BadgeHeader: React.FC<BadgeHeaderProps> = ({
  corridorName = "Mumbai → Pune Synthetic Corridor",
  distanceKm = 150.0,
}) => {
  return (
    <header className="border-b border-slate-800/80 bg-slate-950/70 backdrop-blur-xl sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3.5 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        {/* Brand & Title */}
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 via-teal-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-emerald-500/20">
            <svg
              className="w-6 h-6 text-slate-950"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2.5}
                d="M13 10V3L4 14h7v7l9-11h-7z"
              />
            </svg>
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center">
                Route<span className="text-emerald-400">.ev</span>
              </h1>
              <span className="text-xs px-2 py-0.5 rounded-full font-mono bg-slate-800 text-slate-300 border border-slate-700">
                v1.0 Generic Corridor
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Physics-Informed EV Highway Trip Planner & Pareto Multi-Objective Engine
            </p>
          </div>
        </div>

        {/* Prominent Provenance & Reliability Badges */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Badge 1: Synthetic Data */}
          <div
            id="badge-synthetic"
            className="flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-950/70 text-amber-300 border border-amber-500/50 shadow-sm shadow-amber-500/10 cursor-help"
            title="Corridor road nodes, elevation profile, and corridor lengths are generated synthetically for generic benchmark evaluation."
          >
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <span>SYNTHETIC DATA</span>
          </div>

          {/* Badge 2: Unverified Data */}
          <div
            id="badge-unverified"
            className="flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-orange-950/70 text-orange-300 border border-orange-500/50 shadow-sm shadow-orange-500/10 cursor-help"
            title="Station catalog is an illustrative synthetic test fixture. Not live-verified by human review or direct API ping."
          >
            <svg className="w-3.5 h-3.5 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>UNVERIFIED DATA</span>
          </div>

          {/* Badge 3: Simulated Reliability */}
          <div
            id="badge-simulated-reliability"
            className="flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-950/70 text-indigo-300 border border-indigo-500/50 shadow-sm shadow-indigo-500/10 cursor-help"
            title="Operator base score + clamped Gaussian noise, seeded"
          >
            <svg className="w-3.5 h-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            <span>SIMULATED RELIABILITY</span>
          </div>

          {/* Active Corridor Pill */}
          <div className="hidden lg:flex items-center space-x-1.5 px-2.5 py-1 rounded-lg text-xs bg-slate-900 text-slate-300 border border-slate-800">
            <span className="text-slate-400">Corridor:</span>
            <span className="font-medium text-white">{corridorName}</span>
            <span className="text-emerald-400 font-mono">({distanceKm} km)</span>
          </div>
        </div>
      </div>
    </header>
  );
};
