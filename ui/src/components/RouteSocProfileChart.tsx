"use client";

import React, { useState } from "react";

interface RoutePoint {
  distance_km: number;
  elevation_m: number;
  soc: number;
  lat: number;
  lon: number;
}

interface StopInfo {
  station_id: string;
  station_name: string;
  operator: string;
  max_kw: number;
  arrival_soc: number;
  departure_soc: number;
  charge_time_min: number;
  detour_distance_m: number;
}

interface RouteSocProfileChartProps {
  profile: RoutePoint[];
  stops: StopInfo[];
  reserveSoc: number;
  hoveredDistanceKm?: number | null;
  onHoverDistance?: (distanceKm: number | null) => void;
}

export const RouteSocProfileChart: React.FC<RouteSocProfileChartProps> = ({
  profile,
  stops,
  reserveSoc,
  hoveredDistanceKm,
  onHoverDistance,
}) => {
  const [internalHoveredPoint, setInternalHoveredPoint] = useState<RoutePoint | null>(null);

  // Synchronized hovered point (either from internal mouse hover or external map hover)
  const hoveredPoint = React.useMemo(() => {
    if (internalHoveredPoint) return internalHoveredPoint;
    if (hoveredDistanceKm != null && profile.length > 0) {
      let closest = profile[0];
      let minDiff = Math.abs(profile[0].distance_km - hoveredDistanceKm);
      for (const p of profile) {
        const diff = Math.abs(p.distance_km - hoveredDistanceKm);
        if (diff < minDiff) {
          minDiff = diff;
          closest = p;
        }
      }
      return closest;
    }
    return null;
  }, [internalHoveredPoint, hoveredDistanceKm, profile]);

  if (!profile || profile.length < 2) {
    return (
      <div className="glass-panel rounded-2xl p-6 text-center text-slate-500 text-sm">
        No trajectory profile available for this plan.
      </div>
    );
  }

  // Chart Dimensions
  const width = 800;
  const height = 300;
  const padding = { top: 30, right: 50, bottom: 40, left: 55 };

  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  // Scales
  const maxDist = Math.max(...profile.map((p) => p.distance_km), 1.0);
  const minElev = Math.min(...profile.map((p) => p.elevation_m));
  const maxElev = Math.max(...profile.map((p) => p.elevation_m));
  const elevRange = Math.max(maxElev - minElev, 10.0);

  const getX = (distKm: number) => padding.left + (distKm / maxDist) * chartW;
  const getYElev = (elev: number) => padding.top + chartH - ((elev - minElev) / elevRange) * (chartH * 0.45);
  const getYSoc = (soc: number) => padding.top + (1.0 - soc) * chartH;

  // Elevation SVG Path (bottom shaded mountain)
  const elevPathPoints = profile.map((p) => `${getX(p.distance_km)},${getYElev(p.elevation_m)}`);
  const elevAreaPath = `M ${getX(0)},${padding.top + chartH} L ${elevPathPoints.join(" L ")} L ${getX(maxDist)},${padding.top + chartH} Z`;

  // SoC Line Path
  const socPathPoints = profile.map((p) => `${getX(p.distance_km)},${getYSoc(p.soc)}`);
  const socLinePath = `M ${socPathPoints.join(" L ")}`;

  // Reserve line Y
  const reserveY = getYSoc(reserveSoc);

  return (
    <div className="glass-panel rounded-2xl p-6 flex flex-col gap-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold text-white flex items-center gap-2">
            <svg className="w-5 h-5 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
            </svg>
            Corridor Elevation & Battery State of Charge (SoC) Profile
          </h3>
          <p className="text-xs text-slate-400">
            Physical step-by-step simulation with regenerative braking and capacity clamping at 100%
          </p>
        </div>

        {/* Legend */}
        <div className="flex flex-wrap items-center gap-4 text-xs">
          <div className="flex items-center space-x-1.5">
            <span className="w-3 h-0.5 bg-emerald-400 rounded-full" />
            <span className="text-slate-300">Battery SoC (%)</span>
          </div>
          <div className="flex items-center space-x-1.5">
            <span className="w-3 h-2 bg-slate-700/60 rounded border border-slate-600/40" />
            <span className="text-slate-300">Terrain Elevation (m)</span>
          </div>
          <div className="flex items-center space-x-1.5">
            <span className="w-3 h-0.5 border-t border-dashed border-rose-500" />
            <span className="text-rose-400 font-mono">Reserve ({Math.round(reserveSoc * 100)}%)</span>
          </div>
        </div>
      </div>

      {/* SVG Canvas */}
      <div className="relative w-full overflow-hidden rounded-xl bg-slate-950/60 border border-slate-800/80 p-2">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          onMouseLeave={() => {
            setInternalHoveredPoint(null);
            onHoverDistance?.(null);
          }}
        >
          <defs>
            {/* Elevation Gradient */}
            <linearGradient id="elevationGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#334155" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#0f172a" stopOpacity="0.05" />
            </linearGradient>

            {/* Battery SoC Glow */}
            <linearGradient id="socGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#10b981" />
              <stop offset="50%" stopColor="#06b6d4" />
              <stop offset="100%" stopColor="#10b981" />
            </linearGradient>

            <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="2" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          {/* Grid lines */}
          {[0.25, 0.5, 0.75, 1.0].map((level) => {
            const y = getYSoc(level);
            return (
              <g key={`grid-${level}`}>
                <line
                  x1={padding.left}
                  y1={y}
                  x2={width - padding.right}
                  y2={y}
                  stroke="#1e293b"
                  strokeDasharray="4 4"
                  strokeWidth="1"
                />
                <text
                  x={width - padding.right + 8}
                  y={y + 3}
                  fill="#64748b"
                  fontSize="10"
                  fontFamily="monospace"
                >
                  {Math.round(level * 100)}%
                </text>
              </g>
            );
          })}

          {/* Elevation Area Shading */}
          <path d={elevAreaPath} fill="url(#elevationGrad)" stroke="#475569" strokeWidth="1" />

          {/* Safety Reserve Threshold Line */}
          <line
            x1={padding.left}
            y1={reserveY}
            x2={width - padding.right}
            y2={reserveY}
            stroke="#f43f5e"
            strokeDasharray="5 3"
            strokeWidth="1.5"
          />

          {/* Continuous Battery SoC Curve */}
          <path
            d={socLinePath}
            fill="none"
            stroke="url(#socGrad)"
            strokeWidth="2.5"
            filter="url(#glow)"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Charging Stops Vertical Indicators */}
          {stops.map((stop, sIdx) => {
            // Find nearest profile point by station id or distance
            const pt = profile.find((p) => p.distance_km > 0.1) || profile[Math.floor(profile.length / 2)];
            const x = getX(pt.distance_km);

            return (
              <g key={`stop-marker-${sIdx}`} className="cursor-pointer">
                <line
                  x1={x}
                  y1={padding.top}
                  x2={x}
                  y2={padding.top + chartH}
                  stroke="#f59e0b"
                  strokeWidth="1.5"
                  strokeDasharray="3 3"
                />
                {/* Pin Circle */}
                <circle cx={x} cy={getYSoc(stop.departure_soc)} r="5" fill="#f59e0b" stroke="#090d16" strokeWidth="2" />
                <circle cx={x} cy={getYSoc(stop.arrival_soc)} r="4" fill="#ef4444" stroke="#090d16" strokeWidth="1.5" />

                <text
                  x={x}
                  y={padding.top - 8}
                  fill="#fbbf24"
                  fontSize="10"
                  fontWeight="bold"
                  textAnchor="middle"
                  fontFamily="sans-serif"
                >
                  Stop #{sIdx + 1}
                </text>
              </g>
            );
          })}

          {/* Interactive Invisible Overlay for Hover */}
          {profile.map((p, i) => (
            <rect
              key={`hover-col-${i}`}
              x={getX(p.distance_km) - (chartW / profile.length) / 2}
              y={padding.top}
              width={chartW / profile.length}
              height={chartH}
              onMouseEnter={() => {
                setInternalHoveredPoint(p);
                onHoverDistance?.(p.distance_km);
              }}
            />
          ))}

          {/* Hover Crosshair */}
          {hoveredPoint && (
            <g>
              <line
                x1={getX(hoveredPoint.distance_km)}
                y1={padding.top}
                x2={getX(hoveredPoint.distance_km)}
                y2={padding.top + chartH}
                stroke="#38bdf8"
                strokeWidth="1"
              />
              <circle
                cx={getX(hoveredPoint.distance_km)}
                cy={getYSoc(hoveredPoint.soc)}
                r="4.5"
                fill="#38bdf8"
                stroke="#090d16"
                strokeWidth="2"
              />
            </g>
          )}

          {/* X-Axis (Distance) */}
          <line
            x1={padding.left}
            y1={padding.top + chartH}
            x2={width - padding.right}
            y2={padding.top + chartH}
            stroke="#334155"
            strokeWidth="1"
          />
          {[0, 30, 60, 90, 120, Math.round(maxDist)].map((km) => (
            <text
              key={`x-axis-${km}`}
              x={getX(km)}
              y={padding.top + chartH + 18}
              fill="#94a3b8"
              fontSize="10"
              textAnchor="middle"
              fontFamily="monospace"
            >
              {km} km
            </text>
          ))}
          <text
            x={padding.left + chartW / 2}
            y={height - 5}
            fill="#64748b"
            fontSize="11"
            textAnchor="middle"
          >
            Highway Corridor Distance (km)
          </text>
        </svg>

        {/* Floating Tooltip */}
        {hoveredPoint && (
          <div
            className="absolute top-3 left-16 glass-panel rounded-lg px-3 py-1.5 text-xs font-mono border border-slate-700/80 pointer-events-none shadow-xl flex items-center space-x-3"
          >
            <span className="text-slate-300">KM: <strong className="text-white">{hoveredPoint.distance_km.toFixed(1)}</strong></span>
            <span className="text-emerald-400">SoC: <strong>{Math.round(hoveredPoint.soc * 100)}%</strong></span>
            <span className="text-slate-400">Elev: <strong>{Math.round(hoveredPoint.elevation_m)}m</strong></span>
          </div>
        )}
      </div>
    </div>
  );
};
