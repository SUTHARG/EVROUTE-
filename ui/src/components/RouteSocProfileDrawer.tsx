"use client";

import React, { useState, useMemo, useRef } from "react";
import { ChevronUp, ChevronDown, Activity } from "lucide-react";
import { formatDistance, formatPercent } from "../utils/format";

export interface ProfilePoint {
  distance_km: number;
  elevation_m: number;
  soc: number;
  lat: number;
  lon: number;
  event?: "drive" | "regen" | "spur_in" | "charge" | "spur_out" | string;
}

export interface StopInfo {
  station_id: string;
  station_name: string;
  operator: string;
  max_kw: number;
  arrival_soc: number;
  departure_soc: number;
  charge_time_min: number;
  route_distance_km?: number;
  power_assumed?: boolean;
  connector_assumed?: boolean;
  amenity_known?: boolean;
  spur_estimated?: boolean;
}


interface RouteSocProfileDrawerProps {
  profile: ProfilePoint[];
  stops: StopInfo[];
  reserveSoc: number;
  hoveredDistanceKm?: number | null;
  onHoverDistance?: (distanceKm: number | null) => void;
  onSelectStation?: (stationId: string) => void;
  originLabel?: string;
  destinationLabel?: string;
}

export const RouteSocProfileDrawer: React.FC<RouteSocProfileDrawerProps> = ({
  profile,
  stops,
  reserveSoc,
  hoveredDistanceKm,
  onHoverDistance,
  onSelectStation,
  originLabel,
  destinationLabel,
}) => {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Downsample profile to at most ~200 points for smooth SVG rendering
  const sampledProfile = useMemo(() => {
    if (!profile || profile.length === 0) return [];
    if (profile.length <= 200) return profile;

    const step = (profile.length - 1) / 199;
    const sampled: ProfilePoint[] = [];
    for (let i = 0; i < 200; i++) {
      const idx = Math.min(profile.length - 1, Math.round(i * step));
      sampled.push(profile[idx]);
    }
    // Always include the exact last point
    if (sampled[sampled.length - 1] !== profile[profile.length - 1]) {
      sampled[sampled.length - 1] = profile[profile.length - 1];
    }
    return sampled;
  }, [profile]);

  const maxDist = useMemo(() => {
    if (!profile || profile.length === 0) return 150.0;
    return Math.max(...profile.map((p) => p.distance_km), 1.0);
  }, [profile]);

  // Compute SVG viewBox and coordinates
  const svgWidth = 800;
  const svgHeight = 120;
  const padding = { top: 16, right: 24, bottom: 24, left: 40 };
  const graphWidth = svgWidth - padding.left - padding.right;
  const graphHeight = svgHeight - padding.top - padding.bottom;

  const getX = (distKm: number) => padding.left + (distKm / maxDist) * graphWidth;
  const getY = (socFrac: number) => padding.top + (1.0 - Math.max(0, Math.min(1.0, socFrac))) * graphHeight;

  // Build single smooth line path and area path
  const { linePath, areaPath } = useMemo(() => {
    if (sampledProfile.length < 2) return { linePath: "", areaPath: "" };

    const pts = sampledProfile.map((p) => ({
      x: getX(p.distance_km),
      y: getY(p.soc),
    }));

    let dLine = `M ${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`;
    for (let i = 1; i < pts.length; i++) {
      dLine += ` L ${pts[i].x.toFixed(1)},${pts[i].y.toFixed(1)}`;
    }

    const bottomY = padding.top + graphHeight;
    const dArea = `${dLine} L ${pts[pts.length - 1].x.toFixed(1)},${bottomY} L ${pts[0].x.toFixed(1)},${bottomY} Z`;

    return { linePath: dLine, areaPath: dArea };
  }, [sampledProfile, maxDist, padding.left, padding.top, graphHeight, graphWidth]);

  // Reserve line Y coordinate
  const reserveY = getY(reserveSoc);

  // Active hovered point details
  const activeHoverPoint = useMemo(() => {
    if (hoveredDistanceKm == null || !profile || profile.length === 0) return null;
    let closest = profile[0];
    let minDiff = Math.abs(profile[0].distance_km - hoveredDistanceKm);
    for (const pt of profile) {
      const diff = Math.abs(pt.distance_km - hoveredDistanceKm);
      if (diff < minDiff) {
        minDiff = diff;
        closest = pt;
      }
    }
    return closest;
  }, [profile, hoveredDistanceKm]);

  // Handle SVG mouse movement
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!containerRef.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const clientX = e.clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, (clientX - (padding.left / svgWidth) * rect.width) / ((graphWidth / svgWidth) * rect.width)));
    const targetKm = ratio * maxDist;
    onHoverDistance?.(targetKm);
  };

  const handleMouseLeave = () => {
    onHoverDistance?.(null);
  };

  if (!profile || profile.length === 0) {
    return null;
  }

  return (
    <div className="absolute bottom-3 left-3 right-3 z-20 transition-all select-none pointer-events-auto">
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
        {/* Drawer Header / Toggle Bar */}
        <div
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="h-8 px-3 flex items-center justify-between border-b border-gray-200 cursor-pointer bg-gray-50 hover:bg-gray-100 transition-colors"
        >
          <div className="flex items-center gap-2 text-xs font-semibold text-gray-800">
            <Activity size={14} className="text-green-600 shrink-0" />
            <span>Battery SoC & Elevation Profile</span>
            <span className="text-xs text-gray-500 font-normal">({maxDist.toFixed(1)} km corridor)</span>
          </div>

          <div className="flex items-center gap-3">
            {activeHoverPoint && (
              <div className="hidden sm:flex items-center gap-3 text-xs font-mono">
                <span className="text-gray-600">
                  KM: <strong className="text-gray-900">{activeHoverPoint.distance_km.toFixed(1)}</strong>
                </span>
                <span className="text-green-600">
                  SoC: <strong>{formatPercent(activeHoverPoint.soc)}</strong>
                </span>
                <span className="text-gray-700">
                  Elev: <strong>{Math.round(activeHoverPoint.elevation_m)} m</strong>
                </span>
              </div>
            )}
            <button className="text-gray-500 hover:text-gray-900 cursor-pointer flex items-center">
              {isCollapsed ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
          </div>
        </div>

        {/* Collapsible Chart Body */}
        {!isCollapsed && (
          <div ref={containerRef} className="p-2 relative bg-white">
            <svg
              viewBox={`0 0 ${svgWidth} ${svgHeight}`}
              className="w-full h-[120px] overflow-visible cursor-crosshair bg-white"
              onMouseMove={handleMouseMove}
              onMouseLeave={handleMouseLeave}
            >
              <defs>
                {/* Light Theme Faint Green SoC Area Gradient */}
                <linearGradient id="socAreaGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#16A34A" stopOpacity="0.18" />
                  <stop offset="100%" stopColor="#16A34A" stopOpacity="0.02" />
                </linearGradient>
              </defs>

              {/* Light Gray Grid Lines (#E5E7EB) */}
              {[0.25, 0.5, 0.75, 1.0].map((frac) => {
                const y = getY(frac);
                return (
                  <g key={`grid-y-${frac}`}>
                    <line
                      x1={padding.left}
                      y1={y}
                      x2={svgWidth - padding.right}
                      y2={y}
                      stroke="#E5E7EB"
                      strokeWidth="1"
                      strokeDasharray="4 4"
                    />
                    <text
                      x={padding.left - 6}
                      y={y + 3}
                      fill="#6B7280"
                      fontSize="9"
                      fontFamily="monospace"
                      textAnchor="end"
                    >
                      {Math.round(frac * 100)}%
                    </text>
                  </g>
                );
              })}

              {/* Safety Reserve Floor (Dashed Red Line #DC2626) */}
              <line
                x1={padding.left}
                y1={reserveY}
                x2={svgWidth - padding.right}
                y2={reserveY}
                stroke="#DC2626"
                strokeWidth="1.5"
                strokeDasharray="5 3"
              />
              {/* Reserve Label Placed at LEFT End ABOVE the Dashed Line (No Overlap) */}
              <text
                x={padding.left + 4}
                y={reserveY - 6}
                fill="#DC2626"
                fontSize="10"
                fontFamily="monospace"
                fontWeight="bold"
                textAnchor="start"
              >
                Reserve: {formatPercent(reserveSoc)}
              </text>

              {/* Faint Green Area Fill */}
              {areaPath && <path d={areaPath} fill="url(#socAreaGradient)" />}

              {/* Smooth Green SoC Line (#16A34A) */}
              {linePath && (
                <path
                  d={linePath}
                  fill="none"
                  stroke="#16A34A"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              )}

              {/* Charging Stop Markers along distance axis */}
              {stops.map((stop, idx) => {
                const stopDistKm = stop.route_distance_km ?? 0;


                const x = getX(stopDistKm);
                const arrY = getY(stop.arrival_soc);
                const depY = getY(stop.departure_soc);

                return (
                  <g
                    key={`stop-marker-${stop.station_id}`}
                    className="cursor-pointer group"
                    onClick={() => onSelectStation?.(stop.station_id)}
                  >
                    {/* Vertical guideline */}
                    <line
                      x1={x}
                      y1={padding.top}
                      x2={x}
                      y2={padding.top + graphHeight}
                      stroke="#D97706"
                      strokeWidth="1.5"
                      strokeDasharray="3 3"
                    />

                    {/* Arrival point */}
                    <circle cx={x} cy={arrY} r="4" fill="#FFFFFF" stroke="#DC2626" strokeWidth="2" />

                    {/* Departure point */}
                    <circle cx={x} cy={depY} r="4.5" fill="#16A34A" stroke="#FFFFFF" strokeWidth="1.5" />

                    {/* Stop Label Pill */}
                    <rect
                      x={x - 22}
                      y={padding.top + 2}
                      width="44"
                      height="15"
                      rx="4"
                      fill="#FEF3C7"
                      stroke="#D97706"
                      strokeWidth="1"
                    />
                    <text
                      x={x}
                      y={padding.top + 13}
                      fill="#92400E"
                      fontSize="9"
                      fontFamily="monospace"
                      fontWeight="bold"
                      textAnchor="middle"
                    >
                      Stop {idx + 1}
                    </text>
                  </g>
                );
              })}

              {/* Active Hover Crosshair Guideline */}
              {activeHoverPoint && (
                <g>
                  <line
                    x1={getX(activeHoverPoint.distance_km)}
                    y1={padding.top}
                    x2={getX(activeHoverPoint.distance_km)}
                    y2={padding.top + graphHeight}
                    stroke="#2563EB"
                    strokeWidth="1.5"
                    strokeDasharray="2 2"
                  />
                  <circle
                    cx={getX(activeHoverPoint.distance_km)}
                    cy={getY(activeHoverPoint.soc)}
                    r="4.5"
                    fill="#2563EB"
                    stroke="#FFFFFF"
                    strokeWidth="2"
                  />
                </g>
              )}

              {/* Distance Axis Baseline & Mileage Milestones */}
              <line
                x1={padding.left}
                y1={padding.top + graphHeight}
                x2={svgWidth - padding.right}
                y2={padding.top + graphHeight}
                stroke="#E5E7EB"
                strokeWidth="1"
              />
              <text
                x={padding.left}
                y={padding.top + graphHeight + 14}
                fill="#4B5563"
                fontSize="10"
                fontFamily="monospace"
              >
                0 km ({originLabel ? originLabel.split(",")[0].trim() : "Origin"})
              </text>
              <text
                x={svgWidth - padding.right}
                y={padding.top + graphHeight + 14}
                fill="#4B5563"
                fontSize="10"
                fontFamily="monospace"
                textAnchor="end"
              >
                {Math.round(maxDist)} km ({destinationLabel ? destinationLabel.split(",")[0].trim() : "Destination"})
              </text>
            </svg>
          </div>
        )}
      </div>
    </div>
  );
};
