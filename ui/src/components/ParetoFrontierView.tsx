"use client";

import React from "react";

export interface ParetoPoint {
  lambda_val: number;
  total_time_min: number;
  total_discomfort_min: number;
  cost_J: number;
  stops_count: number;
  stop_station_ids: string[];
}

interface ParetoFrontierViewProps {
  points?: ParetoPoint[];
  currentLambda: number;
  onSelectLambda: (lambda: number) => void;
}

export const ParetoFrontierView: React.FC<ParetoFrontierViewProps> = ({
  points,
  currentLambda,
  onSelectLambda,
}) => {
  if (!points || points.length === 0) {
    return null;
  }

  // Deduplicate points with nearly identical time & discomfort
  const uniquePoints: ParetoPoint[] = [];
  for (const pt of points) {
    const isDup = uniquePoints.some(
      (u) =>
        Math.abs(u.total_time_min - pt.total_time_min) < 0.1 &&
        Math.abs(u.total_discomfort_min - pt.total_discomfort_min) < 0.1
    );
    if (!isDup) uniquePoints.push(pt);
  }

  // Sort by time ascending
  uniquePoints.sort((a, b) => a.total_time_min - b.total_time_min);

  // SVG dimensions
  const width = 600;
  const height = 220;
  const padding = { top: 25, right: 30, bottom: 35, left: 50 };

  const minTime = Math.min(...uniquePoints.map((p) => p.total_time_min));
  const maxTime = Math.max(...uniquePoints.map((p) => p.total_time_min));
  const timeRange = Math.max(maxTime - minTime, 1.0);

  const minDisc = Math.min(...uniquePoints.map((p) => p.total_discomfort_min));
  const maxDisc = Math.max(...uniquePoints.map((p) => p.total_discomfort_min));
  const discRange = Math.max(maxDisc - minDisc, 1.0);

  const getX = (timeMin: number) =>
    padding.left + ((timeMin - minTime) / timeRange) * (width - padding.left - padding.right);
  const getY = (discMin: number) =>
    height - padding.bottom - ((discMin - minDisc) / discRange) * (height - padding.top - padding.bottom);

  const pathD = uniquePoints.map((p, i) => `${i === 0 ? "M" : "L"} ${getX(p.total_time_min)} ${getY(p.total_discomfort_min)}`).join(" ");

  return (
    <div className="glass-panel rounded-2xl p-6 flex flex-col gap-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-slate-800/80 pb-3">
        <div>
          <h3 className="text-base font-semibold text-white flex items-center gap-2">
            <svg className="w-5 h-5 text-violet-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 8v8m-4-5v5m-4-2v2m-2 4h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            Multi-Objective Pareto Frontier (Time vs. Comfort Trade-Offs)
          </h3>
          <p className="text-xs text-slate-400">
            Convex hull of supported Pareto-optimal itineraries generated via polynomial λ-sweep
          </p>
        </div>

        <span className="text-xs font-mono px-2.5 py-1 rounded-full bg-violet-950/70 text-violet-300 border border-violet-500/40">
          {uniquePoints.length} Supported Non-Dominated Points
        </span>
      </div>

      {/* Interactive SVG Chart */}
      <div className="bg-slate-950/60 rounded-xl p-2 border border-slate-800/80">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto select-none">
          {/* Axis lines */}
          <line
            x1={padding.left}
            y1={height - padding.bottom}
            x2={width - padding.right}
            y2={height - padding.bottom}
            stroke="#334155"
            strokeWidth="1"
          />
          <line
            x1={padding.left}
            y1={padding.top}
            x2={padding.left}
            y2={height - padding.bottom}
            stroke="#334155"
            strokeWidth="1"
          />

          {/* Axis labels */}
          <text
            x={padding.left + (width - padding.left - padding.right) / 2}
            y={height - 6}
            fill="#94a3b8"
            fontSize="10"
            textAnchor="middle"
          >
            Total Journey Time (min)
          </text>
          <text
            x={15}
            y={padding.top + (height - padding.top - padding.bottom) / 2}
            fill="#94a3b8"
            fontSize="10"
            textAnchor="middle"
            transform={`rotate(-90 15 ${padding.top + (height - padding.top - padding.bottom) / 2})`}
          >
            Discomfort (min)
          </text>

          {/* Pareto Curve connecting supported points */}
          <path d={pathD} fill="none" stroke="#8b5cf6" strokeWidth="2" strokeDasharray="3 3" />

          {/* Pareto Points */}
          {uniquePoints.map((pt, idx) => {
            const cx = getX(pt.total_time_min);
            const cy = getY(pt.total_discomfort_min);
            const isSelected = Math.abs(currentLambda - pt.lambda_val) < 0.2;

            return (
              <g
                key={`pareto-pt-${idx}`}
                onClick={() => onSelectLambda(pt.lambda_val)}
                className="cursor-pointer group"
              >
                <circle
                  cx={cx}
                  cy={cy}
                  r={isSelected ? 6 : 4}
                  fill={isSelected ? "#a855f7" : "#0f172a"}
                  stroke={isSelected ? "#ffffff" : "#a855f7"}
                  strokeWidth={isSelected ? 2.5 : 1.5}
                  className="transition-all duration-150 group-hover:scale-125"
                />
                <title>
                  λ = {pt.lambda_val.toFixed(2)} | Time: {pt.total_time_min.toFixed(1)}m | Discomfort: {pt.total_discomfort_min.toFixed(1)}m | Stops: {pt.stops_count}
                </title>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Quick Select Table */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        {uniquePoints.slice(0, 4).map((pt, idx) => {
          const isSelected = Math.abs(currentLambda - pt.lambda_val) < 0.2;
          return (
            <button
              key={`pt-btn-${idx}`}
              onClick={() => onSelectLambda(pt.lambda_val)}
              className={`p-2 rounded-lg border text-left transition-all ${
                isSelected
                  ? "bg-violet-950/50 border-violet-500/80 text-white"
                  : "bg-slate-900/40 border-slate-800 text-slate-300 hover:bg-slate-800/40"
              }`}
            >
              <div className="flex items-center justify-between font-mono">
                <span className="text-[10px] text-violet-400">λ = {pt.lambda_val.toFixed(1)}</span>
                <span className="text-[10px] text-slate-500">{pt.stops_count} stop(s)</span>
              </div>
              <div className="mt-1 font-mono font-bold text-xs">
                {pt.total_time_min.toFixed(0)}m / {pt.total_discomfort_min.toFixed(0)}d
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};
