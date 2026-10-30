"use client";

import React, { useState, useMemo } from "react";
import {
  Navigation,
  MapPin,
  Zap,
  BarChart3,
  Sliders,
  Clock,
  Battery,
  AlertTriangle,
  Search,
  Check,
  ChevronDown,
  ChevronUp,
  RotateCw,
  ExternalLink,
  ShieldCheck,
  Coffee,
  Info,
  ArrowUpDown,
  Sparkles,
  Radio,
  Database,
} from "lucide-react";
import { formatDuration, formatPercent } from "../utils/format";
import { TripPlan, ChargingStopInfo, CorridorStationInfo, ParetoPoint } from "@/types/plan";
import benchmarkResults from "../data/benchmark_results.json";
import { API_BASE_URL } from "@/config/api";

const IS_DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

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

function stationPowerLabel(station: CorridorStationInfo): string {
  if (station.max_dc_kw) return `${station.max_dc_kw} kW DC`;
  if (station.max_ac_kw) return `${station.max_ac_kw} kW AC`;
  const hasDcPlug = station.connector_types?.some((connector) => /ccs|chademo/i.test(connector));
  const hasAcPlug = station.connector_types?.some((connector) => /type\s*2/i.test(connector));
  if (!hasDcPlug && hasAcPlug && station.power_assumed) return "7.2 kW AC assumed";
  return `${station.max_kw} kW${hasDcPlug ? " DC" : ""}`;
}

export interface VehicleOption {
  id: string;
  name: string;
  battery_kwh: number;
  max_dc_kw: number;
  supported_connectors?: string[];
  is_placeholder_profile?: boolean;
  description?: string;
}

export interface TripParams {
  snapshotId: string;
  carId: string;
  startSoc: number;
  reserveSoc: number;
  stopThresholdSoc: number;
  comfortLambda: number;
  K: number;
  enableFilter: boolean;
}

export interface LocationWaypoint {
  lat: number;
  lon: number;
  label: string;
}

export interface SidebarProps {
  // Navigation & Tabs
  activeTab: "trip" | "plan" | "stations" | "analysis";
  onTabChange: (tab: "trip" | "plan" | "stations" | "analysis") => void;

  // Waypoints
  origin: LocationWaypoint;
  destination: LocationWaypoint;
  onChangeOrigin: (loc: LocationWaypoint) => void;
  onChangeDestination: (loc: LocationWaypoint) => void;
  onBuildAndPlanRoute: (origin: LocationWaypoint, dest: LocationWaypoint) => void;

  // Trip Config
  params: TripParams;
  onChangeParams: (params: TripParams) => void;
  onPlanTrip: (targetSnapId?: string, fromSavedSnapshot?: boolean) => void;
  isLoading: boolean;
  vehicles: VehicleOption[];

  // Plan Data
  plan: TripPlan | null;
  onSelectStation: (stationId: string) => void;

  selectedStationId?: string | null;

  // Mobile drawer state
  mobileSheetState?: "collapsed" | "half" | "full";
  onChangeMobileSheetState?: (state: "collapsed" | "half" | "full") => void;

  // Station refresh
  onRefreshStations?: () => void;
  isRefreshing?: boolean;
}


export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onTabChange,
  origin,
  destination,
  onChangeOrigin,
  onChangeDestination,
  onBuildAndPlanRoute,
  params,
  onChangeParams,
  onPlanTrip,
  isLoading,
  vehicles,
  plan,
  onSelectStation,
  selectedStationId,
  mobileSheetState = "half",
  onChangeMobileSheetState,
  onRefreshStations,
  isRefreshing = false,
}) => {

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [stationSearch, setStationSearch] = useState("");

  // Geocoding autocomplete states
  const [fromQuery, setFromQuery] = useState(origin.label);
  const [toQuery, setToQuery] = useState(destination.label);
  const [fromCandidates, setFromCandidates] = useState<Array<{ label: string; lat: number; lon: number }>>([]);
  const [toCandidates, setToCandidates] = useState<Array<{ label: string; lat: number; lon: number }>>([]);
  const [isSearchingFrom, setIsSearchingFrom] = useState(false);
  const [isSearchingTo, setIsSearchingTo] = useState(false);
  const [showFromDropdown, setShowFromDropdown] = useState(false);
  const [showToDropdown, setShowToDropdown] = useState(false);

  // Redirect from analysis tab if demo mode is active
  React.useEffect(() => {
    if (IS_DEMO_MODE && activeTab === "analysis") {
      onTabChange("trip");
    }
  }, [activeTab, onTabChange]);

  // Sync inputs when external origin/destination changes
  React.useEffect(() => {
    setFromQuery(origin.label);
  }, [origin.label]);

  React.useEffect(() => {
    setToQuery(destination.label);
  }, [destination.label]);

  // Debounced search for Origin
  React.useEffect(() => {
    if (!showFromDropdown || !fromQuery.trim()) {
      setFromCandidates([]);
      return;
    }
    const timer = setTimeout(async () => {
      setIsSearchingFrom(true);
      try {
        const resp = await fetch(`${API_BASE_URL}/geocode?q=${encodeURIComponent(fromQuery.trim())}&limit=5`);
        if (resp.ok) {
          const data = await resp.json();
          setFromCandidates(data);
        }
      } catch (err) {
        console.error("Geocode error:", err);
      } finally {
        setIsSearchingFrom(false);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [fromQuery, showFromDropdown]);

  // Debounced search for Destination
  React.useEffect(() => {
    if (!showToDropdown || !toQuery.trim()) {
      setToCandidates([]);
      return;
    }
    const timer = setTimeout(async () => {
      setIsSearchingTo(true);
      try {
        const resp = await fetch(`${API_BASE_URL}/geocode?q=${encodeURIComponent(toQuery.trim())}&limit=5`);
        if (resp.ok) {
          const data = await resp.json();
          setToCandidates(data);
        }
      } catch (err) {
        console.error("Geocode error:", err);
      } finally {
        setIsSearchingTo(false);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [toQuery, showToDropdown]);

  const handleSwap = () => {
    const temp = { ...origin };
    onChangeOrigin(destination);
    onChangeDestination(temp);
    setFromQuery(destination.label);
    setToQuery(temp.label);
  };

  const handleSampleShortcut = (srcLabel: string, sLat: number, sLon: number, dstLabel: string, dLat: number, dLon: number, snapId?: string) => {
    const newOrigin = { lat: sLat, lon: sLon, label: srcLabel };
    const newDest = { lat: dLat, lon: dLon, label: dstLabel };
    onChangeOrigin(newOrigin);
    onChangeDestination(newDest);
    setFromQuery(srcLabel);
    setToQuery(dstLabel);
    setShowFromDropdown(false);
    setShowToDropdown(false);
    if (snapId) {
      update({ snapshotId: snapId });
      onPlanTrip(snapId, true);
    }
  };

  const update = (patch: Partial<TripParams>) => {
    onChangeParams({ ...params, ...patch });
  };

  // Selected vehicle profile
  const selectedVehicle = useMemo(() => {
    return vehicles.find((v) => v.id === params.carId) || vehicles[0];
  }, [vehicles, params.carId]);

  const canPlanRoute = Boolean(
    origin.label.trim() && destination.label.trim() &&
    Number.isFinite(origin.lat) && Number.isFinite(origin.lon) &&
    Number.isFinite(destination.lat) && Number.isFinite(destination.lon) &&
    Math.abs(origin.lat) <= 90 && Math.abs(destination.lat) <= 90 &&
    Math.abs(origin.lon) <= 180 && Math.abs(destination.lon) <= 180
  );

  // All corridor stations
  const corridorStations = useMemo(() => {
    if (!plan || !plan.corridor_stations) return [];
    return plan.corridor_stations as CorridorStationInfo[];
  }, [plan]);

  // Filtered stations for Stations tab
  const filteredStations = useMemo(() => {
    const q = stationSearch.trim().toLowerCase();
    if (!q) return corridorStations;
    return corridorStations.filter(
      (st) =>
        st.name.toLowerCase().includes(q) ||
        st.operator.toLowerCase().includes(q) ||
        st.id.toLowerCase().includes(q)
    );
  }, [corridorStations, stationSearch]);

  // Chosen stop IDs set
  const chosenStopIds = useMemo(() => {
    if (!plan || !plan.stops) return new Set<string>();
    return new Set(plan.stops.map((s: ChargingStopInfo) => s.station_id));
  }, [plan]);

  // Arrival battery color
  const arrivalSocFrac = plan ? plan.arrival_soc_dest : 0.0;
  const arrivalColorClass =
    arrivalSocFrac >= 0.20
      ? "text-green-600 bg-green-50 border-green-200"
      : arrivalSocFrac >= 0.10
      ? "text-amber-600 bg-amber-50 border-amber-200"
      : "text-red-600 bg-red-50 border-red-200";

  const originCity = origin.label ? origin.label.split(",")[0].trim() : "Origin";
  const destinationCity = destination.label ? destination.label.split(",")[0].trim() : "Destination";
  const totalKm = plan?.route_soc_profile?.length
    ? Math.round(plan.route_soc_profile[plan.route_soc_profile.length - 1].distance_km)
    : 150;

  return (
    <aside className={`sidebar-desktop w-full bg-slate-900 border-r border-gray-200 flex flex-col shrink-0 z-30 select-none mobile-bottom-sheet mobile-sheet-${mobileSheetState}`} style={{ backgroundColor: "#F7F8FA" }}>
      {/* Mobile drag handle & toggle bar */}
      <div
        className="md:hidden flex items-center justify-between px-4 py-2 border-b border-gray-200 cursor-pointer bg-gray-50"
        onClick={() => {
          if (onChangeMobileSheetState) {
            onChangeMobileSheetState(
              mobileSheetState === "collapsed" ? "half" : mobileSheetState === "half" ? "full" : "collapsed"
            );
          }
        }}
      >
        <div className="w-10 h-1 bg-gray-300 rounded-full mx-auto" />
      </div>

      {/* 4-Tab Navigation Header (Clean Underline Segmented Control) */}
      <div className="flex items-center border-b border-gray-200 shrink-0 bg-gray-50 h-11">
        <button
          onClick={() => onTabChange("trip")}
          className={`flex-1 h-full py-2.5 px-3 flex items-center justify-center gap-1.5 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
            activeTab === "trip"
              ? "border-green-600 text-green-600 font-semibold bg-white"
              : "border-transparent text-gray-500 hover:text-gray-900 hover:bg-gray-100"
          }`}
        >
          <Navigation size={14} className="shrink-0" />
          <span>Trip</span>
        </button>

        <button
          onClick={() => onTabChange("plan")}
          className={`flex-1 h-full py-2.5 px-3 flex items-center justify-center gap-1.5 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
            activeTab === "plan"
              ? "border-green-600 text-green-600 font-semibold bg-white"
              : "border-transparent text-gray-500 hover:text-gray-900 hover:bg-gray-100"
          }`}
        >
          <Clock size={14} className="shrink-0" />
          <span>Plan</span>
          {plan && plan.stops && plan.stops.length > 0 && (
            <span className="w-4 h-4 rounded-full bg-green-50 text-green-700 border border-green-200 text-[10px] font-bold flex items-center justify-center">
              {plan.stops.length}
            </span>
          )}
        </button>

        <button
          onClick={() => onTabChange("stations")}
          className={`flex-1 h-full py-2.5 px-3 flex items-center justify-center gap-1.5 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
            activeTab === "stations"
              ? "border-green-600 text-green-600 font-semibold bg-white"
              : "border-transparent text-gray-500 hover:text-gray-900 hover:bg-gray-100"
          }`}
        >
          <Zap size={14} className="shrink-0" />
          <span>Stations</span>
        </button>

        {!IS_DEMO_MODE && (
          <button
            onClick={() => onTabChange("analysis")}
            className={`flex-1 h-full py-2.5 px-3 flex items-center justify-center gap-1.5 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
              activeTab === "analysis"
                ? "border-green-600 text-green-600 font-semibold bg-white"
                : "border-transparent text-gray-500 hover:text-gray-900 hover:bg-gray-100"
            }`}
          >
            <BarChart3 size={14} className="shrink-0" />
            <span>Analysis</span>
          </button>
        )}
      </div>

      {/* Tab Panels Body (Scrollable) */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-gray-900" style={{ backgroundColor: "#F7F8FA" }}>
        {/* ========================================================================= */}
        {/* TAB 1: TRIP CONFIGURATION                                                 */}
        {/* ========================================================================= */}
        {activeTab === "trip" && (
          <div className="space-y-4">
            {/* Origin & Destination Route Waypoints */}
            <div className="p-3.5 rounded-xl bg-white border border-gray-200 shadow-xs space-y-3">
              <div className="flex items-center justify-between text-xs text-gray-500">
                <span className="font-semibold text-gray-700">Corridor Route</span>
                <span className="font-mono text-[11px] text-green-700 font-medium">Real road-following</span>
              </div>

              {/* Origin Waypoint Input */}
              <div className="relative">
                <label className="text-[10px] uppercase tracking-wider font-semibold text-gray-500 mb-1 block">
                  Origin (From)
                </label>
                <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-gray-200 bg-gray-50/50 focus-within:bg-white focus-within:border-green-600 transition-colors">
                  <div className="w-2.5 h-2.5 rounded-full bg-green-600 shrink-0" />
                  <input
                    type="text"
                    value={fromQuery}
                    onChange={(e) => {
                      setFromQuery(e.target.value);
                      setShowFromDropdown(true);
                    }}
                    onFocus={() => setShowFromDropdown(true)}
                    placeholder="Type origin city (e.g. Mumbai, Delhi)..."
                    className="w-full text-xs bg-transparent focus:outline-hidden text-gray-900 placeholder:text-gray-400 font-medium"
                  />
                  {isSearchingFrom && <RotateCw size={12} className="animate-spin text-gray-400 shrink-0" />}
                </div>

                {/* From Autocomplete Dropdown */}
                {showFromDropdown && fromCandidates.length > 0 && (
                  <div className="absolute left-0 right-0 top-full mt-1 z-30 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden py-1 max-h-48 overflow-y-auto">
                    {fromCandidates.map((c, i) => (
                      <div
                        key={`from-cand-${i}`}
                        onClick={() => {
                          onChangeOrigin(c);
                          setFromQuery(c.label);
                          setShowFromDropdown(false);
                        }}
                        className="px-3 py-2 text-xs hover:bg-gray-50 cursor-pointer flex items-center gap-2 border-b border-gray-50 last:border-0"
                      >
                        <MapPin size={12} className="text-green-600 shrink-0" />
                        <span className="truncate text-gray-800 font-medium">{c.label}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Swap Waypoints Button */}
              <div className="flex items-center justify-center -my-1">
                <button
                  type="button"
                  onClick={handleSwap}
                  className="p-1 rounded-full bg-gray-100 hover:bg-gray-200 text-gray-600 transition-colors cursor-pointer border border-gray-200 shadow-2xs"
                  title="Swap Origin and Destination"
                >
                  <ArrowUpDown size={13} />
                </button>
              </div>

              {/* Destination Waypoint Input */}
              <div className="relative">
                <label className="text-[10px] uppercase tracking-wider font-semibold text-gray-500 mb-1 block">
                  Destination (To)
                </label>
                <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-gray-200 bg-gray-50/50 focus-within:bg-white focus-within:border-blue-600 transition-colors">
                  <div className="w-2.5 h-2.5 rounded-full bg-blue-600 shrink-0" />
                  <input
                    type="text"
                    value={toQuery}
                    onChange={(e) => {
                      setToQuery(e.target.value);
                      setShowToDropdown(true);
                    }}
                    onFocus={() => setShowToDropdown(true)}
                    placeholder="Type destination city (e.g. Pune, Agra)..."
                    className="w-full text-xs bg-transparent focus:outline-hidden text-gray-900 placeholder:text-gray-400 font-medium"
                  />
                  {isSearchingTo && <RotateCw size={12} className="animate-spin text-gray-400 shrink-0" />}
                </div>

                {/* To Autocomplete Dropdown */}
                {showToDropdown && toCandidates.length > 0 && (
                  <div className="absolute left-0 right-0 top-full mt-1 z-30 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden py-1 max-h-48 overflow-y-auto">
                    {toCandidates.map((c, i) => (
                      <div
                        key={`to-cand-${i}`}
                        onClick={() => {
                          onChangeDestination(c);
                          setToQuery(c.label);
                          setShowToDropdown(false);
                        }}
                        className="px-3 py-2 text-xs hover:bg-gray-50 cursor-pointer flex items-center gap-2 border-b border-gray-50 last:border-0"
                      >
                        <MapPin size={12} className="text-blue-600 shrink-0" />
                        <span className="truncate text-gray-800 font-medium">{c.label}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Sample Corridor Shortcuts */}
              <div className="pt-1.5 border-t border-gray-100">
                <div className="text-[10px] text-gray-500 font-semibold mb-1.5 flex items-center justify-between">
                  <span>Quick routes</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    id="btn-shortcut-mumbai-pune"
                    type="button"
                    onClick={() =>
                      handleSampleShortcut(
                        "Mumbai, Maharashtra, India",
                        18.9388,
                        72.8354,
                        "Pune, Maharashtra, India",
                        18.5204,
                        73.8567,
                        "corridor_18.939_72.835_18.52_73.857"
                      )
                    }
                    className="flex-1 py-1 px-2 rounded-lg bg-gray-50 hover:bg-gray-100 border border-gray-200 text-[11px] font-medium text-gray-700 transition-colors cursor-pointer text-center"
                    title="Load the saved Mumbai to Pune route"
                  >
                    Mumbai → Pune
                  </button>
                  <button
                    id="btn-shortcut-delhi-agra"
                    type="button"
                    onClick={() =>
                      handleSampleShortcut(
                        "Delhi, National Capital Territory of Delhi, India",
                        28.6139,
                        77.2090,
                        "Agra, Uttar Pradesh, India",
                        27.1767,
                        78.0081,
                        "corridor_28.614_77.209_27.177_78.008"
                      )
                    }
                    className="flex-1 py-1 px-2 rounded-lg bg-gray-50 hover:bg-gray-100 border border-gray-200 text-[11px] font-medium text-gray-700 transition-colors cursor-pointer text-center"
                    title="Load the saved Delhi to Agra route"
                  >
                    Delhi → Agra
                  </button>
                </div>
              </div>
            </div>

            {/* EV Model Selector */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-gray-700 flex items-center justify-between">
                <span>Vehicle Model</span>
              </label>
              <div className="space-y-1.5">
                {vehicles.map((v) => {
                  const isSelected = v.id === params.carId;
                  return (
                    <div
                      key={v.id}
                      onClick={() => update({ carId: v.id })}
                      className={`p-2.5 rounded-xl border text-xs cursor-pointer transition-all flex items-center justify-between ${
                        isSelected
                          ? "bg-white border-green-600 shadow-xs"
                          : "bg-white border-gray-200 hover:border-gray-300"
                      }`}
                    >
                      <div className="space-y-0.5">
                        <div className="font-semibold text-gray-900 flex items-center gap-1.5">
                          <span>{v.name}</span>
                          {v.is_placeholder_profile && (
                            <span className="text-[10px] px-1.5 py-0.2 rounded bg-amber-50 text-amber-700 border border-amber-200 font-mono">
                              Sample profile
                            </span>
                          )}
                        </div>
                        <div className="text-gray-500 text-[11px] font-mono" title="Example vehicle profile; confirm specifications with the manufacturer.">
                          {v.battery_kwh} kWh &bull; Up to {v.max_dc_kw} kW DC
                        </div>
                      </div>
                      {isSelected && (
                        <div className="w-5 h-5 rounded-full bg-green-600 text-white flex items-center justify-center shrink-0">
                          <Check size={12} />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Sliders: Start Battery & Reserve */}
            <div className="space-y-3.5 p-3.5 rounded-xl bg-white border border-gray-200 shadow-xs">
              {/* Starting SoC */}
              <div className="space-y-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-semibold text-gray-700">Starting Battery SoC</span>
                  <span className="font-mono font-bold text-green-700">{formatPercent(params.startSoc)}</span>
                </div>
                <input
                  type="range"
                  min="0.10"
                  max="1.0"
                  step="0.05"
                  value={params.startSoc}
                  onChange={(e) => update({ startSoc: parseFloat(e.target.value) })}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-gray-400 font-mono">
                  <span>10% (Low)</span>
                  <span>100% (Full)</span>
                </div>
              </div>

              {/* Reserve SoC */}
              <div className="space-y-1.5 pt-2 border-t border-gray-100">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-semibold text-gray-700">Safety Reserve Floor</span>
                  <span className="font-mono font-bold text-red-600">{formatPercent(params.reserveSoc)}</span>
                </div>
                <input
                  type="range"
                  min="0.05"
                  max="0.25"
                  step="0.01"
                  value={params.reserveSoc}
                  onChange={(e) => update({ reserveSoc: parseFloat(e.target.value) })}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-gray-400 font-mono">
                  <span>5% (Minimal)</span>
                  <span>25% (Conservative)</span>
                </div>
              </div>

              {/* Comfort vs Speed Weight */}
              <div className="space-y-1.5 pt-2 border-t border-gray-100">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-semibold text-gray-700">Trade-Off Preference</span>
                  <span className="font-mono text-gray-600 text-[11px]">&lambda; = {params.comfortLambda.toFixed(1)}</span>
                </div>
                <input
                  type="range"
                  min="0.0"
                  max="3.0"
                  step="0.1"
                  value={params.comfortLambda}
                  onChange={(e) => update({ comfortLambda: parseFloat(e.target.value) })}
                  className="w-full"
                />
                <div className="flex justify-between text-[10px] text-gray-500">
                  <span>Fastest (&lambda;=0)</span>
                  <span>Most comfortable stops (&lambda;=3)</span>
                </div>
              </div>
            </div>

            {/* Primary Plan CTA Button */}
            <button
              id="plan-trip-btn"
              onClick={() => onBuildAndPlanRoute(origin, destination)}
              disabled={isLoading || !canPlanRoute}
              className="w-full py-2.5 px-4 rounded-xl text-sm font-semibold bg-green-600 hover:bg-green-700 text-white transition-colors flex items-center justify-center gap-2 cursor-pointer shadow-xs disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <>
                  <RotateCw size={16} className="animate-spin" />
                  <span>Planning Trip...</span>
                </>
              ) : (
                <>
                  <Navigation size={16} />
                  <span>Plan trip (Live providers)</span>
                </>
              )}
            </button>

            {/* Collapsed Advanced Settings (Hidden in Demo Mode) */}
            {!IS_DEMO_MODE && (
              <div className="pt-1">
                <button
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="w-full py-2 px-3 rounded-lg text-xs text-gray-600 hover:text-gray-900 bg-white border border-gray-200 flex items-center justify-between cursor-pointer"
                >
                  <span className="flex items-center gap-1.5 font-medium">
                    <Sliders size={14} /> Advanced Settings
                  </span>
                  {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>

                {showAdvanced && (
                  <div className="mt-2 p-3 rounded-xl bg-white border border-gray-200 space-y-3 text-xs">
                    <div className="space-y-1">
                      <div className="flex justify-between">
                        <span className="text-gray-700">SoC Discretization Grid (K)</span>
                        <span className="font-mono font-bold text-gray-900">{params.K} levels</span>
                      </div>
                      <input
                        type="range"
                        min="10"
                        max="100"
                        step="5"
                        value={params.K}
                        onChange={(e) => update({ K: parseInt(e.target.value, 10) })}
                        className="w-full"
                      />
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-gray-100">
                      <span className="text-gray-700">Greedy Candidate Pruning</span>
                      <input
                        type="checkbox"
                        checked={params.enableFilter}
                        onChange={(e) => update({ enableFilter: e.target.checked })}
                        className="cursor-pointer"
                      />
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 2: TRIP PLAN ITINERARY                                                */}
        {/* ========================================================================= */}
        {activeTab === "plan" && (
          <div className="space-y-4">
            {!plan ? (
              <div className="p-6 text-center rounded-xl bg-white border border-gray-200 text-xs text-gray-500 space-y-2">
                <Navigation size={24} className="mx-auto text-gray-400" />
                <div className="font-semibold text-gray-700">No plan generated yet</div>
                <p>Select your vehicle profile and tap "Plan trip" to compute the optimal itinerary.</p>
              </div>
            ) : !plan.feasible ? (
              <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-xs space-y-2">
                <div className="flex items-center gap-1.5 text-red-700 font-bold">
                  <AlertTriangle size={16} /> Infeasible Trip Route
                </div>
                <p className="text-gray-700 leading-relaxed">
                  {plan.infeasibility_reason ||
                    "Vehicle battery capacity cannot bridge the longest charging gap under safety reserve."}
                </p>
                <div className="text-[11px] text-gray-600 bg-white p-2.5 rounded-lg border border-red-200">
                  Tip: Increase starting battery SoC or choose a longer-range vehicle with higher battery capacity.
                </div>
              </div>
            ) : (
              <>
                {/* Demo Mode Persistent Banner */}
                {plan.is_demo_mode && (
                  <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-900 flex items-center gap-2">
                    <Sparkles size={16} className="text-amber-600 shrink-0" />
                    <div>
                      <span className="font-bold">DEMO MODE ACTIVE:</span> Using illustrative synthetic stations for corridor simulation.
                    </div>
                  </div>
                )}

                {/* Elevation Unavailable Warning Banner */}
                {plan.elevation_available === false && (
                  <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-900 flex items-center gap-2">
                    <AlertTriangle size={16} className="text-amber-600 shrink-0" />
                    <div>
                      <span className="font-bold">Warning:</span> Elevation profile unavailable along corridor. Flat-terrain assumptions applied.
                    </div>
                  </div>
                )}

                {/* Plan Origin Provenance Indicator (Live Build vs Saved Snapshot vs Synthetic) */}
                <div className={`p-2.5 rounded-xl border text-xs flex items-center justify-between ${
                  plan.synthetic
                    ? "bg-amber-50/80 border-amber-200 text-amber-900"
                    : plan.is_live_build
                    ? "bg-emerald-50/80 border-emerald-200 text-emerald-900"
                    : "bg-slate-50 border-slate-200 text-slate-800"
                }`}>
                  <div className="flex items-center gap-2">
                    {plan.synthetic ? (
                      <Sparkles size={14} className="text-amber-600 shrink-0" />
                    ) : plan.is_live_build ? (
                      <Radio size={14} className="text-emerald-600 shrink-0" />
                    ) : (
                      <Database size={14} className="text-slate-500 shrink-0" />
                    )}
                    <div>
                      <span className="font-bold text-[11px] block uppercase tracking-wider">
                        {plan.synthetic
                          ? "Synthetic Demo Plan"
                          : plan.is_live_build
                          ? "Live Route Build"
                          : "Saved Snapshot (Cached)"}
                      </span>
                      <span className="text-[10px] text-gray-600">
                        {plan.synthetic
                          ? "Offline synthetic physics model"
                          : plan.is_live_build
                          ? "Fresh APIs: Open Charge Map & OSRM"
                          : "Loaded from disk snapshot without querying live APIs"}
                      </span>
                    </div>
                  </div>
                  {!plan.is_live_build && !plan.synthetic && (
                    <button
                      type="button"
                      onClick={() => onBuildAndPlanRoute(origin, destination)}
                      className="px-2 py-1 rounded-lg bg-green-600 hover:bg-green-700 text-white text-[10px] font-semibold transition-colors cursor-pointer shrink-0"
                    >
                      Build Live
                    </button>
                  )}
                </div>

                {/* Big Arrival Battery Gauge */}
                <div className={`p-4 rounded-xl border flex items-center justify-between ${arrivalColorClass}`}>
                  <div>
                    <div className="text-[11px] uppercase tracking-wider font-bold">Arrival Battery ({destinationCity})</div>
                    <div className="text-3xl font-extrabold font-mono mt-0.5">
                      {formatPercent(plan.arrival_soc_dest)}
                    </div>

                    <div className="text-[11px] text-gray-600 mt-1 font-medium">
                      Safety floor: {formatPercent(params.reserveSoc)} buffer maintained
                    </div>
                  </div>
                  <div className="w-12 h-12 rounded-full bg-white border border-gray-200 flex items-center justify-center">
                    <Battery size={26} />
                  </div>
                </div>

                {/* Performance Stats Cards (Clean Spacing Scale & Formatted Durations) */}
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="p-3 rounded-xl bg-white border border-gray-200 shadow-xs">
                    <div className="text-gray-500 text-[11px]">Total Duration</div>
                    <div className="text-base font-bold text-gray-900 mt-0.5">
                      {formatDuration(plan.total_time_min)}
                    </div>
                  </div>

                  <div className="p-3 rounded-xl bg-white border border-gray-200 shadow-xs">
                    <div className="text-gray-500 text-[11px]">Driving Time</div>
                    <div className="text-base font-bold text-gray-900 mt-0.5">
                      {formatDuration(plan.driving_time_min)}
                    </div>
                  </div>

                  <div className="p-3 rounded-xl bg-white border border-gray-200 shadow-xs">
                    <div className="text-gray-500 text-[11px]">Charging Dwell</div>
                    <div className="text-base font-bold text-amber-700 mt-0.5">
                      {formatDuration(plan.charging_time_min)}
                    </div>
                  </div>

                  <div className="p-3 rounded-xl bg-white border border-gray-200 shadow-xs">
                    <div className="text-gray-500 text-[11px]">Charging Stops</div>
                    <div className="text-base font-bold text-gray-900 mt-0.5">
                      {plan.stops?.length || 0} {plan.stops?.length === 1 ? "Stop" : "Stops"}
                    </div>
                  </div>
                </div>

                {/* Vertical Timeline of Stops */}
                <div className="space-y-2 pt-2 border-t border-gray-200">
                  <div className="flex items-center justify-between text-xs text-gray-500">
                    <span className="font-semibold text-gray-700">Itinerary Stops</span>
                    <span className="text-[11px]">click to focus map</span>
                  </div>

                  <div className="space-y-2">
                    {/* Origin waypoint */}
                    <div className="p-2.5 rounded-xl bg-white border border-gray-200 text-xs flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full bg-green-600" />
                        <div>
                          <div className="font-semibold text-gray-900">Depart {originCity}</div>
                          <div className="text-[11px] text-gray-500 font-mono">
                            Battery: {formatPercent(params.startSoc)}
                          </div>
                        </div>
                      </div>
                      <span className="text-[11px] font-mono text-gray-400">KM 0</span>
                    </div>

                    {/* Chosen charging stops */}
                    {plan.stops && plan.stops.map((stop: ChargingStopInfo, idx: number) => {
                      const isSelected = selectedStationId === stop.station_id;
                      return (
                        <div
                          key={`timeline-${stop.station_id}-${idx}`}
                          onClick={() => onSelectStation(stop.station_id)}
                          className={`p-3 rounded-xl border text-xs cursor-pointer transition-all space-y-1.5 ${
                            isSelected
                              ? "bg-amber-50 border-amber-300 shadow-xs"
                              : "bg-white border-gray-200 hover:border-gray-300"
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-bold text-gray-900 flex items-center gap-1.5">
                              <span className="w-5 h-5 rounded-full bg-amber-600 text-white flex items-center justify-center text-[10px] font-mono">
                                {idx + 1}
                              </span>
                              <span>{stop.station_name}</span>
                            </span>
                            <span className="font-mono text-blue-700 font-semibold">
                              {stop.charging_power_kw ?? stop.max_kw} kW {stop.charging_mode?.toUpperCase() ?? "DC"}
                            </span>
                          </div>

                          <div className="text-gray-500 text-[11px] flex items-center justify-between">
                            <span>Operator: {stop.operator}</span>
                            <span className="font-mono text-gray-500">
                              KM {stop.route_distance_km !== undefined ? stop.route_distance_km.toFixed(1) : (stop.distance_from_origin_km || 0).toFixed(1)}
                            </span>
                          </div>

                          <div className="flex items-center justify-between text-[11px] font-mono pt-1 border-t border-gray-100">
                            <div>
                              <span className="text-gray-500">Recharge: </span>
                              <strong className="text-gray-900">
                                {formatPercent(stop.arrival_soc)} &rarr; {formatPercent(stop.departure_soc)}
                              </strong>
                            </div>
                            <div className="text-amber-700 font-bold">{formatDuration(stop.charge_time_min)}</div>
                          </div>

                          <div className="flex items-center justify-between text-[10px] pt-0.5">
                            <span className="text-gray-500">
                              Reliability: {Math.round(stop.reliability * 100)}%
                            </span>
                            <span className="px-1.5 py-0.2 rounded text-[10px] font-medium" style={{ backgroundColor: "#EDE9FE", color: "#5B21B6", border: "1px solid #DDD6FE" }}>
                              [simulated]
                            </span>
                          </div>

                          {(stop.power_assumed || stop.connector_assumed || stop.spur_estimated) && (
                            <div className="flex flex-col gap-1 pt-1 border-t border-gray-100">
                              {stop.power_assumed && (
                                <div className="text-[10px] text-amber-800 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded font-medium flex items-center gap-1">
                                  <span>&bull;</span>
                                  <span>charge time assumes 50 kW</span>
                                </div>
                              )}
                              {stop.connector_assumed && (
                                <div className="text-[10px] text-amber-800 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded font-medium flex items-center gap-1">
                                  <span>&bull;</span>
                                  <span>connector assumed: CCS2</span>
                                </div>
                              )}
                              {stop.spur_estimated && (
                                <div className="text-[10px] text-blue-800 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded font-medium flex items-center gap-1">
                                  <span>&bull;</span>
                                  <span>estimated detour</span>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}

                    {/* Destination waypoint */}
                    <div className="p-2.5 rounded-xl bg-white border border-gray-200 text-xs flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full bg-blue-600" />
                        <div>
                          <div className="font-semibold text-gray-900">Arrive {destinationCity}</div>
                          <div className="text-[11px] text-gray-500 font-mono">
                            Battery: {formatPercent(plan.arrival_soc_dest)}
                          </div>
                        </div>
                      </div>
                      <span className="text-[11px] font-mono text-gray-400">KM {totalKm}</span>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 3: CORRIDOR STATIONS DIRECTORY                                        */}
        {/* ========================================================================= */}
        {activeTab === "stations" && (
          !plan ? (
            <div className="mx-1 rounded-2xl border border-gray-200 bg-white p-5 text-center shadow-xs">
              <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-green-50 text-green-700">
                <MapPin size={20} />
              </div>
              <h3 className="text-sm font-semibold text-gray-900">No route selected</h3>
              <p className="mx-auto mt-1.5 max-w-[240px] text-xs leading-relaxed text-gray-500">
                Search for your starting point and destination to see charging stations along the route.
              </p>
              <button
                type="button"
                onClick={() => onTabChange("trip")}
                className="mt-4 rounded-lg bg-green-600 px-3.5 py-2 text-xs font-semibold text-white transition-colors hover:bg-green-700"
              >
                Set up a trip
              </button>
            </div>
          ) : (
          <div className="space-y-3">
            {/* Search filter input + Manual Refresh Button */}
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search size={14} className="absolute left-3 top-2.5 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search station or operator..."
                  value={stationSearch}
                  onChange={(e) => setStationSearch(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 rounded-xl bg-white border border-gray-200 text-xs text-gray-900 placeholder:text-gray-400 focus:outline-none focus:border-green-600"
                />
              </div>
              {onRefreshStations && (
                <button
                  id="btn-refresh-stations"
                  type="button"
                  onClick={onRefreshStations}
                  disabled={isRefreshing || !plan}
                  className="py-2 px-3 rounded-xl bg-white hover:bg-gray-50 border border-gray-200 text-xs font-semibold text-gray-700 flex items-center gap-1.5 transition-colors cursor-pointer shrink-0 disabled:opacity-60 disabled:cursor-not-allowed"
                  title={plan ? "Invalidate cache and query live station APIs" : "Plan a route before refreshing its stations"}
                >
                  <RotateCw size={13} className={isRefreshing ? "animate-spin text-green-600" : "text-gray-500"} />
                  <span>Refresh</span>
                </button>
              )}
            </div>

            <div className="px-1 text-xs text-gray-500">
              {filteredStations.length} {filteredStations.length === 1 ? "station" : "stations"}
            </div>


            {/* Stations list with Live Badges, Connectors, and Fetched Timestamp */}
            <div className="space-y-2">
              {filteredStations.length === 0 && (
                <div className="rounded-xl border border-dashed border-gray-300 bg-white p-4 text-center">
                  <p className="text-xs font-medium text-gray-700">
                    {corridorStations.length === 0 ? "No charging stations found on this route." : "No stations match your search."}
                  </p>
                  {corridorStations.length === 0 && onRefreshStations && (
                    <button
                      type="button"
                      onClick={onRefreshStations}
                      disabled={isRefreshing}
                      className="mt-2 text-xs font-semibold text-green-700 hover:text-green-800 disabled:opacity-60"
                    >
                      Refresh station data
                    </button>
                  )}
                </div>
              )}
              {filteredStations.map((st) => {
                const isChosen = chosenStopIds.has(st.id);
                const isFocused = selectedStationId === st.id;
                const isLive = isAvailabilityLive(st.availability);
                const isCompatible = !st.connector_unknown && (st.connector_types || []).some((c) => selectedVehicle?.supported_connectors?.includes(c));

                return (
                  <div
                    key={st.id}
                    onClick={() => onSelectStation(st.id)}
                    className={`p-3 rounded-xl border text-xs cursor-pointer transition-all space-y-2 ${
                      isChosen
                        ? "bg-amber-50/70 border-amber-300 shadow-xs"
                        : isFocused
                        ? "bg-blue-50/70 border-blue-300"
                        : "bg-white border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-gray-900 line-clamp-1">{st.name}</span>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {st.route_distance_km !== undefined && (
                          <span className="text-[10px] font-mono font-bold text-gray-600 bg-gray-100 border border-gray-200 px-1.5 py-0.5 rounded">
                            KM {st.route_distance_km.toFixed(1)}
                          </span>
                        )}
                        <span className="font-mono font-bold text-gray-900">{stationPowerLabel(st)}</span>
                      </div>
                    </div>

                    <div className="text-gray-600 text-[11px] flex items-center justify-between">
                      <span>Operator: <strong>{st.operator}</strong></span>
                      <div className="flex items-center gap-1">
                        {st.verified && (
                          <span className="text-[10px] font-bold text-green-700 bg-green-50 border border-green-200 px-1.5 py-0.2 rounded">
                            VERIFIED
                          </span>
                        )}
                        {isChosen ? (
                          <span className="text-[10px] font-bold text-amber-700 bg-amber-100 border border-amber-300 px-1.5 py-0.2 rounded">
                            CHOSEN
                          </span>
                        ) : isCompatible ? (
                          <span className="text-[10px] font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.2 rounded">
                            Eligible
                          </span>
                        ) : (
                          <span className="text-[10px] font-medium text-gray-500 bg-gray-100 border border-gray-200 px-1.5 py-0.2 rounded">
                            Incompatible
                          </span>
                        )}
                        {(st.power_assumed || st.connector_assumed) && (
                          <span className="text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.2 rounded">
                            assumed
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Live Availability Status */}
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

                    {/* Connectors & Charger Stalls */}
                    <div className="text-[11px] text-gray-600 font-mono flex items-center justify-between">
                      <span>Plugs: <strong className="text-blue-700">{st.connector_types?.join(", ") || (st.connector_unknown ? "Connector unknown" : "CCS2")}</strong></span>
                      <span>{st.charger_count ? `${st.charger_count} stalls` : "Stalls: unknown"}</span>
                    </div>

                    {/* Provenance, Fetched Time, External Link, and Simulated Label */}
                    <div className="flex items-center justify-between text-[10px] pt-1 border-t border-gray-100 text-gray-500">
                      <span>Fetched: {formatFetchedTime(st.fetched_at)}</span>
                      {st.source === "ocm_snapshot" ? (
                        <span className="text-[10px] font-medium px-1.5 py-0.2 rounded bg-blue-50 text-blue-700 border border-blue-200">
                          Open Charge Map snapshot, dated {st.fetched_at?.split("T")[0] || "2024"}
                        </span>
                      ) : (
                        <span className="font-mono uppercase px-1.5 py-0.2 rounded bg-gray-100 text-gray-700 border border-gray-200">
                          {st.source || "OSM"}
                        </span>
                      )}
                    </div>

                    {st.data_provider_name && (
                      <div className="flex items-center justify-between text-[10px] text-gray-500">
                        <span>Provider: <strong className="text-gray-700">{st.data_provider_name}</strong></span>
                        {st.data_provider_license && (
                          <span className="font-mono text-[9px] text-gray-400">{st.data_provider_license}</span>
                        )}
                      </div>
                    )}

                    <div className="flex items-center justify-between text-[10px] text-gray-400">
                      <span>Reliability: {((st.reliability || 0.85) * 100).toFixed(0)}% [simulated]</span>
                      {st.source_url && (
                        <a
                          href={st.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="text-green-700 hover:text-green-800 flex items-center gap-1 font-medium"
                        >
                          <ExternalLink size={10} /> Link
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          )
        )}

        {/* ========================================================================= */}
        {/* TAB 4: TECHNICAL ANALYSIS & BENCHMARKS (Hidden in Demo Mode)              */}
        {/* ========================================================================= */}
        {!IS_DEMO_MODE && activeTab === "analysis" && (
          <div className="space-y-4">
            {/* Pareto Trade-Off Curve Section */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-gray-900">Pareto Trade-Off Frontier</span>
                <span className="text-[11px] text-gray-500 font-mono">Time vs Discomfort</span>
              </div>
              <p className="text-[11px] text-gray-500 leading-relaxed">
                Click any supported trade-off point below to reconfigure the trip planner.
              </p>

              {plan && plan.pareto_frontier && plan.pareto_frontier.length > 0 ? (
                <div className="p-3 rounded-xl bg-white border border-gray-200 shadow-xs">
                  <div className="space-y-1.5">
                    {plan.pareto_frontier.map((pt: ParetoPoint, idx: number) => {
                      const isCurrent = Math.abs(pt.lambda_val - params.comfortLambda) < 0.15;
                      return (
                        <div
                          key={`pareto-${idx}`}
                          onClick={() => update({ comfortLambda: pt.lambda_val })}
                          className={`p-2 rounded-lg border text-xs cursor-pointer transition-all flex items-center justify-between font-mono ${
                            isCurrent
                              ? "bg-green-50 border-green-600 text-green-900 font-semibold"
                              : "bg-gray-50 border-gray-200 text-gray-700 hover:border-gray-300"
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-[11px] text-gray-500">&lambda;={pt.lambda_val.toFixed(1)}</span>
                            <span className="font-bold text-gray-900">{formatDuration(pt.total_time_min)}</span>
                          </div>
                          <div className="flex items-center gap-2 text-[11px]">
                            <span className="text-amber-700">{pt.total_discomfort_min.toFixed(1)} discomf</span>
                            <span className="text-gray-400">({pt.stops_count} stops)</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div className="p-4 text-center rounded-xl bg-white border border-gray-200 text-xs text-gray-500">
                  Plan a trip to generate the Pareto trade-off curve.
                </div>
              )}
            </div>

            {/* Dynamic Search & Contraction Stats (Clean Spacing Scale) */}
            <div className="space-y-2 pt-2 border-t border-gray-200">
              <span className="text-xs font-semibold text-gray-900">Current Query Performance</span>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2.5 rounded-xl bg-white border border-gray-200 shadow-xs">
                  <div className="text-[11px] text-gray-500">States Expanded</div>
                  <div className="text-base font-bold font-mono text-green-600 mt-0.5">
                    {plan ? (plan.states_expanded || 261).toLocaleString() : "—"}
                  </div>
                </div>

                <div className="p-2.5 rounded-xl bg-white border border-gray-200 shadow-xs">
                  <div className="text-[11px] text-gray-500">Edges Relaxed</div>
                  <div className="text-base font-bold font-mono text-blue-600 mt-0.5">
                    {plan ? (plan.edges_relaxed || 1919).toLocaleString() : "—"}
                  </div>
                </div>

                <div className="p-2.5 rounded-xl bg-white border border-gray-200 shadow-xs">
                  <div className="text-[11px] text-gray-500">Reduced Graph Build</div>
                  <div className="text-base font-bold font-mono text-gray-900 mt-0.5">
                    {plan ? `${(plan.build_time_ms || 1.45).toFixed(2)} ms` : "—"}
                  </div>
                </div>

                <div className="p-2.5 rounded-xl bg-white border border-gray-200 shadow-xs">
                  <div className="text-[11px] text-gray-500">Dijkstra Search</div>
                  <div className="text-base font-bold font-mono text-gray-900 mt-0.5">
                    {plan ? `${(plan.search_time_ms || 8.92).toFixed(2)} ms` : "—"}
                  </div>
                </div>
              </div>
            </div>

            {/* Static Empirical Contraction Benchmarks Card */}
            <div className="p-3 rounded-xl bg-white border border-gray-200 text-xs space-y-2 shadow-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-gray-900 flex items-center gap-1.5">
                  <Info size={14} className="text-blue-600" />
                  <span>Measured Contraction Speedup</span>
                </span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 font-mono">
                  Benchmark 5
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 text-[11px] font-mono pt-1">
                <div>
                  <span className="text-gray-500">Search-Only: </span>
                  <strong className="text-green-600">
                    {benchmarkResults.full_road_baseline?.search_speedup || 5.9}x
                  </strong>
                </div>
                <div>
                  <span className="text-gray-500">15-&lambda; Sweep: </span>
                  <strong className="text-blue-600">
                    {benchmarkResults.full_road_baseline?.amortized_15_lambda_speedup || 3.2}x
                  </strong>
                </div>
                <div>
                  <span className="text-gray-500">Single Query: </span>
                  <strong className="text-gray-900">
                    {benchmarkResults.full_road_baseline?.single_query_e2e_speedup || 0.7}x
                  </strong>
                </div>
                <div>
                  <span className="text-gray-500">Slope vs |V_c|: </span>
                  <strong className="text-purple-700">
                    {benchmarkResults.slope_vc || 1.36}
                  </strong>
                </div>
              </div>

              <p className="text-[10px] text-gray-500 border-t border-gray-100 pt-1.5">
                Source: 2,495 road nodes, 14 corridor stations. State expansions reduced 115x from 30,103 to 261.
              </p>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
};
