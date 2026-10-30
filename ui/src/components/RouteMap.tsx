"use client";

import React, { useEffect, useMemo, useRef } from "react";
import { MapContainer, TileLayer, Polyline, Marker, Popup, useMap, CircleMarker } from "react-leaflet";
import L from "leaflet";
import { Zap, Coffee, Battery, ShieldAlert, Sparkles, Database, ExternalLink } from "lucide-react";
import { formatDuration, formatPercent } from "../utils/format";

export interface MapStation {
  id: string;
  name: string;
  lat: number;
  lon: number;
  operator: string;
  max_kw: number;
  max_ac_kw?: number | null;
  max_dc_kw?: number | null;
  charger_count?: number;
  connector_types?: string[];
  availability?: {
    available: number;
    total: number;
    out_of_service: number;
    last_updated?: string | null;
  } | null;
  amenity_score?: number;
  amenities?: Record<string, number>;
  amenity_known?: boolean;
  reliability: number;
  is_reliability_simulated?: boolean;
  source?: string;
  source_url?: string | null;
  fetched_at?: string | null;
  verified?: boolean;
  connector_unknown?: boolean;
  power_assumed?: boolean;
  connector_assumed?: boolean;
  spur_estimated?: boolean;
  data_provider_name?: string | null;
  data_provider_license?: string | null;
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
  charging_mode?: string;
  charging_power_kw?: number;
  charger_count?: number;
  connector_types?: string[];
  availability?: {
    available: number;
    total: number;
    out_of_service: number;
    last_updated?: string | null;
  } | null;
  reliability: number;
  source?: string;
  source_url?: string | null;
  fetched_at?: string | null;
  verified?: boolean;
  connector_unknown?: boolean;
  route_distance_km?: number;
  distance_from_origin_km?: number;
  power_assumed?: boolean;
  connector_assumed?: boolean;
  amenity_known?: boolean;
  spur_estimated?: boolean;
  data_provider_name?: string | null;
  data_provider_license?: string | null;
}

function stationPowerLabel(station: MapStation): string {
  if (station.max_dc_kw) return `${station.max_dc_kw} kW DC`;
  if (station.max_ac_kw) return `${station.max_ac_kw} kW AC`;
  const hasDcPlug = station.connector_types?.some((connector) => /ccs|chademo/i.test(connector));
  const hasAcPlug = station.connector_types?.some((connector) => /type\s*2/i.test(connector));
  if (!hasDcPlug && hasAcPlug && station.power_assumed) return "7.2 kW AC assumed";
  return `${station.max_kw} kW${hasDcPlug ? " DC" : ""}`;
}

interface RouteMapProps {
  routePoints: MapRoutePoint[];
  routeGeometry?: [number, number][];
  chosenStops: MapChosenStop[];
  corridorStations: MapStation[];
  focusedStationId?: string | null;
  hoveredDistanceKm?: number | null;
  onHoverDistance?: (distanceKm: number | null) => void;
  onSelectStation?: (stationId: string) => void;
  activeTab?: string;
  originLabel?: string;
  destinationLabel?: string;
}

// Controller to smoothly pan and focus on selected stops
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
        duration: 0.8,
        easeLinearity: 0.25,
      });
    }
  }, [focusedStationId, stations, map]);

  return null;
}

// Auto-fitter to fit route bounds on load and invalidate size on tab/layout change
function AutoFitBounds({ points, activeTab }: { points: [number, number][]; activeTab?: string }) {
  const map = useMap();

  useEffect(() => {
    const handleResize = () => {
      map.invalidateSize();
    };

    map.invalidateSize();
    const t1 = setTimeout(() => {
      map.invalidateSize();
      if (points.length > 1) {
        map.fitBounds(L.latLngBounds(points), { padding: [50, 50] });
      }
    }, 100);

    const t2 = setTimeout(() => {
      map.invalidateSize();
    }, 400);

    window.addEventListener("resize", handleResize);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      window.removeEventListener("resize", handleResize);
    };
  }, [points, map, activeTab]);

  return null;
}

// Numbered Filled Stop Icon for Chosen Charging Stops (Amber #D97706 on Light Map)
function createFilledStopIcon(stopNumber: number, label: string) {
  return L.divIcon({
    className: "custom-stop-marker",
    html: `
      <div style="display: flex; flex-direction: column; align-items: center; transform: translate(-50%, -100%);">
        <div style="
          background-color: #D97706;
          color: #FFFFFF;
          font-weight: 700;
          font-family: ui-monospace, SFMono-Regular, monospace;
          font-size: 11px;
          width: 26px;
          height: 26px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          border: 2px solid #FFFFFF;
          box-shadow: 0 3px 8px rgba(0, 0, 0, 0.25);
        ">
          ${stopNumber}
        </div>
        <div style="
          margin-top: 2px;
          padding: 1px 6px;
          background: #FEF3C7;
          border: 1px solid #D97706;
          border-radius: 4px;
          color: #92400E;
          font-size: 10px;
          font-weight: 700;
          white-space: nowrap;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        ">
          Stop ${stopNumber}
        </div>
        <div style="width: 2px; height: 4px; background: #D97706;"></div>
      </div>
    `,
    iconSize: [26, 42],
    iconAnchor: [13, 42],
    popupAnchor: [0, -42],
  });
}

// Helper to test if live availability data is under 1 hour old
function isAvailabilityLive(avail?: { last_updated?: string | null } | null): boolean {
  if (!avail) return false;
  if (!avail.last_updated) return true;
  try {
    const updated = new Date(avail.last_updated).getTime();
    return Date.now() - updated < 3600 * 1000;
  } catch {
    return true;
  }
}

function formatFetchedTime(isoStr?: string | null): string {
  if (!isoStr) return "Unavailable";
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return isoStr;
  }
}

// Marker icon for station dot: Green = free, Amber = busy, Gray = unknown, Hollow Gray = incompatible/unknown connector
function createStationMarkerIcon(color: string, isHollow: boolean) {
  if (isHollow) {
    return L.divIcon({
      className: "custom-station-hollow",
      html: `
        <div style="
          width: 14px;
          height: 14px;
          border-radius: 50%;
          background-color: #FFFFFF;
          border: 2px solid #9CA3AF;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
        ">
          <div style="width: 4px; height: 4px; border-radius: 50%; background-color: #9CA3AF;"></div>
        </div>
      `,
      iconSize: [14, 14],
      iconAnchor: [7, 7],
      popupAnchor: [0, -7],
    });
  }

  return L.divIcon({
    className: "custom-station-dot",
    html: `
      <div style="
        width: 15px;
        height: 15px;
        border-radius: 50%;
        background-color: ${color};
        border: 2px solid #FFFFFF;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.25);
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
      ">
        <div style="width: 3px; height: 3px; border-radius: 50%; background-color: #FFFFFF;"></div>
      </div>
    `,
    iconSize: [15, 15],
    iconAnchor: [7.5, 7.5],
    popupAnchor: [0, -7.5],
  });
}

// Terminal Milestone Icon (Mumbai Origin / Pune Destination)
function createTerminalIcon(isStart: boolean, name: string) {
  const bg = isStart ? "#16A34A" : "#2563EB";
  return L.divIcon({
    className: "custom-terminal-marker",
    html: `
      <div style="display: flex; flex-direction: column; align-items: center; transform: translate(-50%, -100%);">
        <div style="
          background-color: ${bg};
          color: #FFFFFF;
          font-weight: 700;
          font-size: 10px;
          padding: 2px 7px;
          border-radius: 12px;
          border: 2px solid #FFFFFF;
          box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
          white-space: nowrap;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        ">
          ${name}
        </div>
        <div style="width: 2px; height: 5px; background: ${bg};"></div>
      </div>
    `,
    iconSize: [40, 26],
    iconAnchor: [20, 26],
    popupAnchor: [0, -26],
  });
}

// Battery SoC color mapping on light background
function getSocColor(soc: number): string {
  if (soc >= 0.50) return "#16A34A"; // >= 50% Green
  if (soc >= 0.25) return "#D97706"; // 25-50% Amber
  return "#DC2626";                  // < 25% Red
}

export const RouteMap: React.FC<RouteMapProps> = ({
  routePoints,
  routeGeometry = [],
  chosenStops,
  corridorStations,
  focusedStationId,
  hoveredDistanceKm,
  onHoverDistance,
  onSelectStation,
  activeTab,
  originLabel,
  destinationLabel,
}) => {
  const chosenIds = useMemo(() => new Set(chosenStops.map((s) => s.station_id)), [chosenStops]);

  // Combined LatLngs for AutoFitBounds
  const allLatLngs = useMemo(() => {
    const list: [number, number][] = [];
    if (routePoints && routePoints.length > 0) {
      for (const p of routePoints) {
        if (p.lat && p.lon) list.push([p.lat, p.lon]);
      }
    } else if (routeGeometry.length > 0) {
      for (const [lat, lon] of routeGeometry) {
        if (Number.isFinite(lat) && Number.isFinite(lon)) list.push([lat, lon]);
      }
    } else if (corridorStations && corridorStations.length > 0) {
      for (const s of corridorStations) {
        if (s.lat && s.lon) list.push([s.lat, s.lon]);
      }
    }
    return list;
  }, [routePoints, routeGeometry, corridorStations]);

  // Focus targets list
  const focusTargets = useMemo(() => {
    return corridorStations.map((s) => ({ id: s.id, lat: s.lat, lon: s.lon }));
  }, [corridorStations]);

  // Partition route polyline into continuous SoC color segments
  const routeSegments = useMemo(() => {
    if (!routePoints || routePoints.length < 2) return [];

    const segments: Array<{ positions: [number, number][]; color: string }> = [];
    let curPositions: [number, number][] = [[routePoints[0].lat, routePoints[0].lon]];
    let curColor = getSocColor(routePoints[0].soc);

    for (let i = 1; i < routePoints.length; i++) {
      const pt = routePoints[i];
      const color = getSocColor(pt.soc);
      if (color === curColor) {
        curPositions.push([pt.lat, pt.lon]);
      } else {
        curPositions.push([pt.lat, pt.lon]);
        segments.push({ positions: curPositions, color: curColor });
        curPositions = [[pt.lat, pt.lon]];
        curColor = color;
      }
    }
    if (curPositions.length > 1) {
      segments.push({ positions: curPositions, color: curColor });
    }

    return segments;
  }, [routePoints]);

  // Distance-aligned hover point coordinates
  const hoveredPoint = useMemo(() => {
    if (hoveredDistanceKm == null || !routePoints || routePoints.length === 0) return null;
    let closest = routePoints[0];
    let minDiff = Math.abs(routePoints[0].distance_km - hoveredDistanceKm);
    for (const pt of routePoints) {
      const diff = Math.abs(pt.distance_km - hoveredDistanceKm);
      if (diff < minDiff) {
        minDiff = diff;
        closest = pt;
      }
    }
    return closest;
  }, [routePoints, hoveredDistanceKm]);

  const startPoint = routePoints?.[0] ?? (routeGeometry.length ? {
    lat: routeGeometry[0][0], lon: routeGeometry[0][1], distance_km: 0, elevation_m: 0, soc: 0,
  } : undefined);
  const endPoint = routePoints?.[routePoints.length - 1] ?? (routeGeometry.length ? {
    lat: routeGeometry[routeGeometry.length - 1][0], lon: routeGeometry[routeGeometry.length - 1][1],
    distance_km: 0, elevation_m: 0, soc: 0,
  } : undefined);

  // Unique signature for route geometry to ensure clean layer remounting
  const routeSignature = useMemo(() => {
    if (routePoints?.length) {
      const p0 = routePoints[0];
      const pN = routePoints[routePoints.length - 1];
      return `${routePoints.length}-${p0.lat.toFixed(3)}_${p0.lon.toFixed(3)}-${pN.lat.toFixed(3)}_${pN.lon.toFixed(3)}`;
    }
    if (routeGeometry.length) {
      const p0 = routeGeometry[0];
      const pN = routeGeometry[routeGeometry.length - 1];
      return `corridor-${routeGeometry.length}-${p0[0].toFixed(3)}_${p0[1].toFixed(3)}-${pN[0].toFixed(3)}_${pN[1].toFixed(3)}`;
    }
    return "empty";
  }, [routePoints, routeGeometry]);

  return (
    <div className="w-full h-full min-h-0 relative overflow-hidden bg-gray-50 select-none">
      <MapContainer
        center={[18.75, 73.4]}
        zoom={9}
        scrollWheelZoom={true}
        className="w-full h-full"
        style={{ height: "100%", width: "100%", position: "absolute", inset: 0, zIndex: 1 }}
      >
        {/* Clean Light Map Tiles (Standard OpenStreetMap) with Proper Attribution */}
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />

        <AutoFitBounds points={allLatLngs} activeTab={activeTab} />
        <MapFocusController focusedStationId={focusedStationId} stations={focusTargets} />

        {/* Dynamic SoC Colored Route Polyline: Unique key removes any leftover layers */}
        <React.Fragment key={`route-layer-group-${routeSignature}`}>
          {routeSegments.map((seg, idx) => (
            <Polyline
              key={`route-seg-${routeSignature}-${idx}`}
              positions={seg.positions}
              pathOptions={{
                color: seg.color,
                weight: 5,
                opacity: 0.95,
                lineCap: "round",
                lineJoin: "round",
              }}
            />
          ))}
          {routeSegments.length === 0 && routeGeometry.length >= 2 && (
            <Polyline
              key={`corridor-route-${routeSignature}`}
              positions={routeGeometry}
              pathOptions={{
                color: "#2563EB",
                weight: 5,
                opacity: 0.9,
                lineCap: "round",
                lineJoin: "round",
              }}
            />
          )}
        </React.Fragment>

        {/* Distance-aligned Crosshair Hover Marker */}
        {hoveredPoint && (
          <CircleMarker
            center={[hoveredPoint.lat, hoveredPoint.lon]}
            radius={8}
            pathOptions={{
              color: "#FFFFFF",
              fillColor: "#2563EB",
              fillOpacity: 1.0,
              weight: 2.5,
            }}
          >
            <Popup autoPan={false}>
              <div className="text-xs font-mono p-1">
                <div className="font-bold text-blue-600">Route Milestone</div>
                <div className="text-gray-700">Distance: {hoveredPoint.distance_km.toFixed(1)} km</div>
                <div className="text-gray-700">Elevation: {Math.round(hoveredPoint.elevation_m)} m</div>
                <div className="text-green-600 font-bold">Battery SoC: {formatPercent(hoveredPoint.soc)}</div>
              </div>
            </Popup>
          </CircleMarker>
        )}

        {/* Origin Marker */}
        {startPoint && (
          <Marker position={[startPoint.lat, startPoint.lon]} icon={createTerminalIcon(true, "Origin")}>
            <Popup>
              <div className="text-xs p-1">
                <div className="font-bold text-green-700">Journey Origin</div>
                <div className="font-medium text-gray-900 mt-0.5">{originLabel || "Starting waypoint"}</div>
                <div className="text-gray-500 text-[11px] mt-0.5">KM 0.0</div>
              </div>
            </Popup>
          </Marker>
        )}

        {/* Destination Marker */}
        {endPoint && (
          <Marker position={[endPoint.lat, endPoint.lon]} icon={createTerminalIcon(false, "Destination")}>
            <Popup>
              <div className="text-xs p-1">
                <div className="font-bold text-blue-700">Journey Destination</div>
                <div className="font-medium text-gray-900 mt-0.5">{destinationLabel || "Final destination"}</div>
                <div className="text-gray-500 text-[11px] mt-0.5">
                  {routePoints?.length
                    ? `Final corridor milestone (${endPoint.distance_km.toFixed(1)} km)`
                    : "Road corridor endpoint"}
                </div>
              </div>
            </Popup>
          </Marker>
        )}

        {/* Numbered Filled Markers for Chosen Stops */}
        {chosenStops.map((stop, idx) => (
          <Marker
            key={`chosen-${stop.station_id}`}
            position={[stop.lat, stop.lon]}
            icon={createFilledStopIcon(idx + 1, `Stop ${idx + 1}`)}
            eventHandlers={{
              click: () => onSelectStation?.(stop.station_id),
            }}
          >
            <Popup>
              <div className="text-xs flex flex-col gap-2 min-w-[220px] p-1 bg-white">
                <div className="flex items-center justify-between border-b border-gray-200 pb-1.5">
                  <span className="font-bold text-amber-700 flex items-center gap-1">
                    <Zap size={14} className="text-amber-600" /> Stop {idx + 1}
                  </span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-50 text-amber-700 border border-amber-200">
                    CHOSEN CHARGER
                  </span>
                </div>

                <div>
                  <div className="font-bold text-gray-900 text-sm">{stop.station_name}</div>
                  <div className="text-gray-600 text-xs mt-0.5">Operator: {stop.operator}</div>
                </div>

                <div className="grid grid-cols-2 gap-1.5 p-2 rounded-lg bg-gray-50 border border-gray-200 text-xs font-mono">
                  <div>
                    <span className="text-gray-500">Route Dist:</span>{" "}
                    <strong className="text-gray-900">
                      {(stop.route_distance_km !== undefined ? stop.route_distance_km : (stop.distance_from_origin_km || 0)).toFixed(1)} km
                    </strong>
                  </div>
                  <div>
                    <span className="text-gray-500">Power:</span>{" "}
                    <strong className="text-blue-700">
                      {stop.charging_power_kw ?? stop.max_kw} kW {stop.charging_mode?.toUpperCase() ?? "DC"}
                    </strong>
                  </div>
                  <div>
                    <span className="text-gray-500">Duration:</span>{" "}
                    <strong className="text-amber-700">{formatDuration(stop.charge_time_min)}</strong>
                  </div>
                  <div className="col-span-2 pt-1 border-t border-gray-200">
                    <span className="text-gray-500">Recharge:</span>{" "}
                    <strong className="text-green-700">
                      {formatPercent(stop.arrival_soc)} &rarr; {formatPercent(stop.departure_soc)}
                    </strong>
                  </div>
                </div>

                {/* Simulated Reliability Badge */}
                <div className="flex items-center justify-between text-xs pt-1 border-t border-gray-200">
                  <span className="text-gray-600">Reliability: {(stop.reliability * 100).toFixed(0)}%</span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium" style={{ backgroundColor: "#EDE9FE", color: "#5B21B6", border: "1px solid #DDD6FE" }}>
                    [Simulated]
                  </span>
                </div>

                {(stop.power_assumed || stop.connector_assumed || stop.spur_estimated) && (
                  <div className="flex flex-col gap-1 pt-1 border-t border-gray-100">
                    {stop.power_assumed && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
                        charge time assumes 50 kW
                      </span>
                    )}
                    {stop.connector_assumed && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
                        connector assumed: CCS2
                      </span>
                    )}
                    {stop.spur_estimated && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-200">
                        estimated detour
                      </span>
                    )}
                  </div>
                )}
              </div>
            </Popup>
          </Marker>
        ))}

        {/* Map Markers for Corridor Stations: Color-coded by Live Availability */}
        {corridorStations
          .filter((st) => !chosenIds.has(st.id) && st.lat && st.lon)
          .map((st) => {
            const isLive = isAvailabilityLive(st.availability);
            let markerIcon;

            if (st.connector_unknown) {
              markerIcon = createStationMarkerIcon("#9CA3AF", true); // Hollow gray (incompatible / unknown connector)
            } else if (isLive && st.availability) {
              if (st.availability.available > 0) {
                markerIcon = createStationMarkerIcon("#16A34A", false); // Green (chargers free)
              } else {
                markerIcon = createStationMarkerIcon("#D97706", false); // Amber (busy)
              }
            } else {
              markerIcon = createStationMarkerIcon("#6B7280", false); // Gray (availability unknown)
            }

            return (
              <Marker
                key={`station-${st.id}`}
                position={[st.lat, st.lon]}
                icon={markerIcon}
                eventHandlers={{
                  click: () => onSelectStation?.(st.id),
                }}
              >
                <Popup>
                  <div className="text-xs flex flex-col gap-2 min-w-[220px] p-1 bg-white">
                    <div className="flex items-center justify-between border-b border-gray-200 pb-1.5">
                      <span className="font-bold text-gray-900 line-clamp-1">{st.name}</span>
                      {st.verified && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-green-50 text-green-700 border border-green-200">
                          VERIFIED
                        </span>
                      )}
                    </div>

                    <div className="text-gray-600 text-xs">Operator: <strong className="text-gray-900">{st.operator}</strong></div>

                    {/* Live Availability Badge */}
                    <div className="flex items-center justify-between text-[11px] py-1 border-y border-gray-100">
                      <span className="text-gray-500">Live Status:</span>
                      {isLive && st.availability ? (
                        st.availability.available > 0 ? (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-green-50 text-green-700 border border-green-200">
                            Live &bull; {st.availability.available}/{st.availability.total} Free
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-50 text-amber-700 border border-amber-200">
                            Live &bull; Busy (0/{st.availability.total} Free)
                          </span>
                        )
                      ) : (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-500 border border-gray-200">
                          Availability unknown
                        </span>
                      )}
                    </div>

                    <div className="grid grid-cols-2 gap-1.5 p-2 rounded-lg bg-gray-50 border border-gray-200 text-xs font-mono">
                      <div>
                        <span className="text-gray-500">Power:</span>{" "}
                        <strong className="text-gray-900">{stationPowerLabel(st)}</strong>
                      </div>
                      <div>
                        <span className="text-gray-500">Stalls:</span>{" "}
                        <strong className="text-gray-900">{st.charger_count ? st.charger_count : "unknown"}</strong>
                      </div>
                      <div className="col-span-2 pt-1 border-t border-gray-200">
                        <span className="text-gray-500">Connectors:</span>{" "}
                        <strong className="text-blue-700">
                          {st.connector_types?.join(", ") || (st.connector_unknown ? "Connector unknown" : "CCS2")}
                        </strong>
                      </div>
                    </div>

                    {(st.power_assumed || st.connector_assumed) && (
                      <div className="flex flex-wrap gap-1 pt-1 border-t border-gray-100">
                        {st.power_assumed && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
                            assumed power (50 kW)
                          </span>
                        )}
                        {st.connector_assumed && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
                            assumed connector (CCS2)
                          </span>
                        )}
                      </div>
                    )}

                    {st.data_provider_name && (
                      <div className="text-[10px] text-gray-500 pt-1 border-t border-gray-100 flex items-center justify-between">
                        <span>Provider: <strong className="text-gray-700">{st.data_provider_name}</strong></span>
                        {st.data_provider_license && (
                          <span className="font-mono text-[9px] text-gray-500 bg-gray-50 px-1 py-0.2 rounded border border-gray-200">
                            {st.data_provider_license}
                          </span>
                        )}
                      </div>
                    )}

                    {/* Provenance & Fetched Time */}
                    <div className="flex items-center justify-between text-xs pt-1 border-t border-gray-200">
                      <span className="text-gray-400 text-[10px]">
                        Fetched: {formatFetchedTime(st.fetched_at)}
                      </span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-gray-100 border border-gray-200 text-gray-700 uppercase">
                        {st.source || "osm"}
                      </span>
                    </div>

                    {st.source_url && (
                      <a
                        href={st.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[11px] text-green-700 hover:text-green-800 flex items-center gap-1 font-medium pt-0.5"
                      >
                        <ExternalLink size={12} /> View on {st.source === "google_places" ? "Google Maps" : st.source === "ocm" ? "OpenChargeMap" : "Source"}
                      </a>
                    )}
                  </div>
                </Popup>
              </Marker>
            );
          })}
      </MapContainer>
    </div>
  );
};

export default RouteMap;
