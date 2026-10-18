"use client";

import React, { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, Polyline, Marker, Popup, useMap, CircleMarker } from "react-leaflet";
import L from "leaflet";

export interface MapStation {
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
}

export interface MapRoutePoint {
  distance_km: number;
  elevation_m: number;
  soc: number;
  lat: number;
  lon: number;
}

export interface MapChosenStop {
  station_id: string;
  station_name: string;
  operator: string;
  lat: number;
  lon: number;
  arrival_soc: number;
  departure_soc: number;
  charge_time_min: number;
  max_kw: number;
  reliability: number;
}

interface RouteMapProps {
  routePoints: MapRoutePoint[];
  chosenStops: MapChosenStop[];
  corridorStations: MapStation[];
  focusedStationId?: string | null;
  hoveredDistanceKm?: number | null;
  onHoverDistance?: (distanceKm: number | null) => void;
  onSelectStation?: (stationId: string) => void;
}

// Map Controller for smoothly panning and focusing on selected stops
function MapFocusController({
  focusedStationId,
  stations,
}: {
  focusedStationId?: string | null;
  stations: Array<{ id: string; lat: number; lon: number }>;
}) {
  const map = useMap();

  useEffect(() => {
    if (!focusedStationId) return;
    const target = stations.find((s) => s.id === focusedStationId);
    if (target && target.lat && target.lon) {
      map.flyTo([target.lat, target.lon], 13, {
        duration: 1.2,
        easeLinearity: 0.25,
      });
    }
  }, [focusedStationId, stations, map]);

  return null;
}

// Auto-fitter to fit route bounds on initial load
function AutoFitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    map.invalidateSize();
    if (points.length > 1) {
      map.fitBounds(L.latLngBounds(points), { padding: [40, 40] });
    }
  }, [points, map]);
  return null;
}

// Create custom SVG markers
const createFilledStopIcon = (label: string) =>
  L.divIcon({
    className: "custom-leaflet-marker",
    html: `
      <div style="
        position: relative;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        background: #f59e0b;
        color: #0f172a;
        border: 2.5px solid #ffffff;
        border-radius: 50%;
        box-shadow: 0 0 16px rgba(245, 158, 11, 0.7);
        cursor: pointer;
      ">
        <svg style="width: 16px; height: 16px;" viewBox="0 0 24 24" fill="currentColor">
          <path d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        <span style="
          position: absolute;
          bottom: -18px;
          background: #0f172a;
          color: #f59e0b;
          border: 1px solid #f59e0b;
          font-size: 10px;
          font-weight: 700;
          padding: 1px 5px;
          border-radius: 4px;
          white-space: nowrap;
        ">${label}</span>
      </div>
    `,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
    popupAnchor: [0, -18],
  });

const createHollowStationIcon = () =>
  L.divIcon({
    className: "custom-leaflet-marker",
    html: `
      <div style="
        width: 18px;
        height: 18px;
        background: rgba(15, 23, 42, 0.85);
        border: 2px solid #38bdf8;
        border-radius: 50%;
        box-shadow: 0 0 8px rgba(56, 189, 248, 0.4);
        cursor: pointer;
      "></div>
    `,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -12],
  });

const createTerminalIcon = (isOrigin: boolean, name: string) =>
  L.divIcon({
    className: "custom-leaflet-marker",
    html: `
      <div style="
        display: flex;
        flex-direction: column;
        align-items: center;
      ">
        <div style="
          width: 14px;
          height: 14px;
          background: ${isOrigin ? "#10b981" : "#06b6d4"};
          border: 2.5px solid #ffffff;
          border-radius: 50%;
          box-shadow: 0 0 12px ${isOrigin ? "rgba(16, 185, 129, 0.8)" : "rgba(6, 182, 212, 0.8)"};
        "></div>
        <div style="
          margin-top: 4px;
          background: rgba(15, 23, 42, 0.95);
          color: #f8fafc;
          border: 1px solid rgba(255, 255, 255, 0.2);
          font-size: 10px;
          font-weight: 700;
          padding: 2px 6px;
          border-radius: 6px;
          white-space: nowrap;
        ">${name}</div>
      </div>
    `,
    iconSize: [60, 36],
    iconAnchor: [30, 7],
    popupAnchor: [0, -10],
  });

export const RouteMap: React.FC<RouteMapProps> = ({
  routePoints,
  chosenStops,
  corridorStations,
  focusedStationId,
  hoveredDistanceKm,
  onHoverDistance,
  onSelectStation,
}) => {
  const chosenIds = useMemo(
    () => new Set(chosenStops.map((s) => s.station_id)),
    [chosenStops]
  );

  // Split route points into color-coded segments based on SoC
  const routeSegments = useMemo(() => {
    if (routePoints.length < 2) return [];

    const segments: Array<{
      positions: [number, number][];
      color: string;
      avgSoc: number;
    }> = [];

    for (let i = 0; i < routePoints.length - 1; i++) {
      const p1 = routePoints[i];
      const p2 = routePoints[i + 1];
      const avgSoc = (p1.soc + p2.soc) / 2.0;

      // Color scheme based on SoC:
      // >= 0.50: Emerald (healthy)
      // 0.25 - 0.49: Amber (moderate)
      // < 0.25: Rose (critical)
      let color = "#10b981"; // Emerald
      if (avgSoc < 0.25) {
        color = "#f43f5e"; // Rose
      } else if (avgSoc < 0.50) {
        color = "#f59e0b"; // Amber
      }

      segments.push({
        positions: [
          [p1.lat, p1.lon],
          [p2.lat, p2.lon],
        ],
        color,
        avgSoc,
      });
    }

    return segments;
  }, [routePoints]);

  const allLatLngs: [number, number][] = useMemo(
    () => routePoints.map((p) => [p.lat, p.lon]),
    [routePoints]
  );

  // Position of distance-aligned hover pointer
  const hoveredPoint = useMemo(() => {
    if (hoveredDistanceKm == null || routePoints.length === 0) return null;
    let closest = routePoints[0];
    let minDiff = Math.abs(routePoints[0].distance_km - hoveredDistanceKm);
    for (const p of routePoints) {
      const diff = Math.abs(p.distance_km - hoveredDistanceKm);
      if (diff < minDiff) {
        minDiff = diff;
        closest = p;
      }
    }
    return closest;
  }, [hoveredDistanceKm, routePoints]);

  const startPoint = routePoints[0];
  const endPoint = routePoints[routePoints.length - 1];

  const focusTargets = useMemo(() => {
    const list: Array<{ id: string; lat: number; lon: number }> = [];
    corridorStations.forEach((st) => list.push({ id: st.id, lat: st.lat, lon: st.lon }));
    chosenStops.forEach((st) => list.push({ id: st.station_id, lat: st.lat, lon: st.lon }));
    return list;
  }, [corridorStations, chosenStops]);

  return (
    <div className="glass-panel rounded-2xl overflow-hidden flex flex-col border border-slate-800/80">
      {/* Map Header */}
      <div className="p-4 bg-slate-900/80 border-b border-slate-800/80 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-950 border border-emerald-500/40 flex items-center justify-center text-emerald-400">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
            </svg>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              Interactive Corridor Map & Charging Infrastructure
            </h3>
            <p className="text-xs text-slate-400">
              Leaflet OSM with dynamic SoC-colored route polyline and live infrastructure status
            </p>
          </div>
        </div>

        {/* Legend */}
        <div className="flex flex-wrap items-center gap-3 text-[11px] font-mono text-slate-300">
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full bg-amber-400 border border-white shadow-sm" />
            <span>Chosen Stop ({chosenStops.length})</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full bg-slate-900 border-2 border-sky-400" />
            <span>Bypassed Station</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-4 h-1.5 rounded-full bg-emerald-400" />
            <span>SoC &ge; 50%</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-4 h-1.5 rounded-full bg-amber-400" />
            <span>25-50%</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-4 h-1.5 rounded-full bg-rose-500" />
            <span>&lt; 25%</span>
          </div>
        </div>
      </div>

      {/* Map Body */}
      <div className="relative w-full h-[460px] bg-slate-950">
        <MapContainer
          center={[18.75, 73.4]}
          zoom={9}
          scrollWheelZoom={true}
          className="w-full h-full dark-tiles"
          style={{ height: "460px", width: "100%", zIndex: 0 }}
        >
          {/* OSM Tile Layer with strict attribution */}
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            maxZoom={19}
          />

          <AutoFitBounds points={allLatLngs} />
          <MapFocusController focusedStationId={focusedStationId} stations={focusTargets} />

          {/* SoC Colored Route Polyline Segments */}
          {routeSegments.map((seg, idx) => (
            <Polyline
              key={`seg-${idx}`}
              positions={seg.positions}
              pathOptions={{
                color: seg.color,
                weight: 5,
                opacity: 0.9,
                lineCap: "round",
                lineJoin: "round",
              }}
              eventHandlers={{
                mouseover: () => {
                  if (routePoints[idx]) {
                    onHoverDistance?.(routePoints[idx].distance_km);
                  }
                },
                mouseout: () => {
                  onHoverDistance?.(null);
                },
              }}
            />
          ))}

          {/* Distance-aligned Hover Indicator Marker */}
          {hoveredPoint && (
            <CircleMarker
              center={[hoveredPoint.lat, hoveredPoint.lon]}
              radius={7}
              pathOptions={{
                color: "#ffffff",
                fillColor: "#06b6d4",
                fillOpacity: 1.0,
                weight: 2.5,
              }}
            >
              <Popup autoPan={false}>
                <div className="text-xs font-mono">
                  <div className="font-bold text-cyan-300">Route Milestone</div>
                  <div>Distance: {hoveredPoint.distance_km.toFixed(1)} km</div>
                  <div>Elevation: {Math.round(hoveredPoint.elevation_m)} m</div>
                  <div>SoC: {(hoveredPoint.soc * 100).toFixed(1)}%</div>
                </div>
              </Popup>
            </CircleMarker>
          )}

          {/* Origin Marker */}
          {startPoint && (
            <Marker
              position={[startPoint.lat, startPoint.lon]}
              icon={createTerminalIcon(true, "Origin (Mumbai)")}
            >
              <Popup>
                <div className="text-xs">
                  <strong className="text-emerald-400">Journey Origin: Mumbai</strong>
                  <div className="text-slate-300 mt-1">Starting point of corridor trip</div>
                </div>
              </Popup>
            </Marker>
          )}

          {/* Destination Marker */}
          {endPoint && (
            <Marker
              position={[endPoint.lat, endPoint.lon]}
              icon={createTerminalIcon(false, "Destination (Pune)")}
            >
              <Popup>
                <div className="text-xs">
                  <strong className="text-cyan-400">Destination: Pune</strong>
                  <div className="text-slate-300 mt-1">Arrival terminal milestone</div>
                </div>
              </Popup>
            </Marker>
          )}

          {/* Chosen Charging Stops (Filled Amber Pins) */}
          {chosenStops.map((stop, idx) => (
            <Marker
              key={`chosen-${stop.station_id}-${idx}`}
              position={[stop.lat, stop.lon]}
              icon={createFilledStopIcon(`Stop ${idx + 1}`)}
              eventHandlers={{
                click: () => onSelectStation?.(stop.station_id),
              }}
            >
              <Popup>
                <div className="text-xs flex flex-col gap-1.5 min-w-[220px]">
                  <div className="flex items-center justify-between pb-1 border-b border-slate-700">
                    <span className="font-bold text-amber-400">Chosen Stop #{idx + 1}</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-950 text-amber-300 border border-amber-600">
                      IN ITINERARY
                    </span>
                  </div>

                  <div className="font-semibold text-white">{stop.station_name}</div>
                  <div className="text-slate-400 text-[11px]">Operator: {stop.operator}</div>

                  <div className="grid grid-cols-2 gap-2 mt-1 py-1.5 px-2 rounded bg-slate-900 border border-slate-800 text-[11px] font-mono">
                    <div>
                      <span className="text-slate-400 block">Charger:</span>
                      <span className="font-bold text-white">{stop.max_kw} kW DC</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block">Dwell Time:</span>
                      <span className="font-bold text-emerald-400">{Math.round(stop.charge_time_min)} min</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block">Arrive SoC:</span>
                      <span className="font-bold text-rose-400">{(stop.arrival_soc * 100).toFixed(0)}%</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block">Depart SoC:</span>
                      <span className="font-bold text-emerald-400">{(stop.departure_soc * 100).toFixed(0)}%</span>
                    </div>
                  </div>

                  {/* Reliability Badge with exact text */}
                  <div className="mt-1 flex flex-col gap-1 text-[11px]">
                    <div className="flex items-center justify-between">
                      <span className="text-slate-300">Reliability:</span>
                      <span className="font-mono font-bold text-indigo-300">
                        {(stop.reliability * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="px-2 py-1 rounded bg-indigo-950/70 border border-indigo-500/50 text-[10px] text-indigo-300">
                      <span className="font-bold">[Simulated]</span> Operator base score + clamped Gaussian noise, seeded
                    </div>
                  </div>

                  {/* Provenance Badge */}
                  <div className="mt-1 flex items-center justify-between pt-1 border-t border-slate-800 text-[10px]">
                    <span className="text-slate-400">Data Source:</span>
                    <span className="px-1.5 py-0.5 rounded font-mono font-semibold bg-slate-800 text-slate-300">
                      SYNTHETIC / CORRIDOR
                    </span>
                  </div>
                </div>
              </Popup>
            </Marker>
          ))}

          {/* Bypassed Stations (Hollow Light-Blue Circles) */}
          {corridorStations
            .filter((st) => !chosenIds.has(st.id) && st.lat && st.lon)
            .map((st) => (
              <Marker
                key={`bypassed-${st.id}`}
                position={[st.lat, st.lon]}
                icon={createHollowStationIcon()}
                eventHandlers={{
                  click: () => onSelectStation?.(st.id),
                }}
              >
                <Popup>
                  <div className="text-xs flex flex-col gap-1.5 min-w-[210px]">
                    <div className="flex items-center justify-between pb-1 border-b border-slate-700">
                      <span className="font-bold text-slate-300">Available Infrastructure</span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-400 border border-slate-700">
                        BYPASSED
                      </span>
                    </div>

                    <div className="font-semibold text-white">{st.name}</div>
                    <div className="text-slate-400 text-[11px]">Operator: {st.operator}</div>

                    <div className="flex items-center justify-between py-1 px-2 rounded bg-slate-900 border border-slate-800 text-[11px] font-mono">
                      <span className="text-slate-400">Peak Power:</span>
                      <span className="font-bold text-sky-400">{st.max_kw} kW DC</span>
                    </div>

                    {/* Amenities */}
                    <div className="text-[11px] text-slate-300">
                      <span className="text-slate-400">Amenities: </span>
                      {st.amenities && Object.keys(st.amenities).length > 0 ? (
                        <span>
                          {Object.entries(st.amenities)
                            .map(([k, v]) => `${k} (${v})`)
                            .join(", ")}
                        </span>
                      ) : (
                        <span>Amenity score: {((st.amenity_score || 0) * 100).toFixed(0)}%</span>
                      )}
                    </div>

                    {/* Reliability with [Simulated] badge */}
                    <div className="mt-1 flex flex-col gap-1 text-[11px]">
                      <div className="flex items-center justify-between">
                        <span className="text-slate-300">Reliability:</span>
                        <span className="font-mono font-bold text-indigo-300">
                          {((st.reliability || 0.85) * 100).toFixed(0)}%
                        </span>
                      </div>
                      <div className="px-2 py-1 rounded bg-indigo-950/70 border border-indigo-500/50 text-[10px] text-indigo-300">
                        <span className="font-bold">[Simulated]</span> Operator base score + clamped Gaussian noise, seeded
                      </div>
                    </div>

                    {/* Provenance Badge */}
                    <div className="mt-1 flex items-center justify-between pt-1 border-t border-slate-800 text-[10px]">
                      <span className="text-slate-400">Provenance:</span>
                      <span className="px-1.5 py-0.5 rounded font-mono font-semibold bg-amber-950/80 text-amber-300 border border-amber-600/40">
                        {st.source?.toUpperCase() || "SYNTHETIC"}
                      </span>
                    </div>
                  </div>
                </Popup>
              </Marker>
            ))}
        </MapContainer>
      </div>

      {/* Map Footer Attribution & Info Bar */}
      <div className="px-4 py-2 bg-slate-950/90 border-t border-slate-800/80 flex flex-wrap items-center justify-between text-[11px] text-slate-500">
        <div>
          Map data &copy;{" "}
          <a
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-400 hover:text-white underline"
          >
            OpenStreetMap
          </a>{" "}
          contributors &bull; Carto style
        </div>
        <div className="flex items-center gap-2">
          <span>Click any timeline stop below to focus map view</span>
        </div>
      </div>
    </div>
  );
};
