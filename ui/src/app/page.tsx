"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import { TopBar } from "@/components/TopBar";
import { Sidebar } from "@/components/Sidebar";
import type { AppTab, LocationWaypoint, MobileSheetState, TripParams, VehicleOption } from "@/features/trip/model/types";
import { BackendErrorModal } from "@/components/BackendErrorModal";
import { RouteProgressModal, JobProgressInfo } from "@/components/RouteProgressModal";
import { RouteAlternativesModal } from "@/components/RouteAlternativesModal";
import { TripPlan, ChargingStopInfo, VehicleOptionItem, RouteAlternativeCandidate, RouteAlternativeSummary } from "@/types/plan";
import { API_BASE_URL } from "@/config/api";
import {
  buildCorridor,
  fetchRouteBuildJob,
  fetchVehicles,
  refreshCorridorStations,
  requestTripPlan,
} from "@/features/trip/api";

// Dynamically import Leaflet Map to avoid SSR window errors in Next.js
const RouteMap = dynamic(
  () => import("@/components/RouteMap").then((mod) => mod.RouteMap),
  {
    ssr: false,
    loading: () => (
      <div className="w-full h-full bg-slate-950 flex flex-col items-center justify-center text-slate-400 gap-3">
        <div className="w-8 h-8 rounded-full border-2 border-emerald-400 border-t-transparent animate-spin" />
        <span className="text-xs font-mono">Initializing OpenStreetMap Canvas...</span>
      </div>
    ),
  }
);

function describeError(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export default function Home() {
  const [params, setParams] = useState<TripParams>({
    snapshotId: "",
    carId: "tata_nexon_ev_lr",
    startSoc: 0.80,
    reserveSoc: 0.10,
    stopThresholdSoc: 0.35,
    comfortLambda: 1.0,
    K: 30,
    enableFilter: true,
  });

  const [origin, setOrigin] = useState<LocationWaypoint>({
    lat: 0,
    lon: 0,
    label: "",
  });
  const [destination, setDestination] = useState<LocationWaypoint>({
    lat: 0,
    lon: 0,
    label: "",
  });
  const [jobInfo, setJobInfo] = useState<JobProgressInfo | null>(null);

  const [activeTab, setActiveTab] = useState<AppTab>("trip");
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [mobileSheetState, setMobileSheetState] = useState<MobileSheetState>("half");

  const [vehicles, setVehicles] = useState<VehicleOption[]>([]);
  const [plan, setPlan] = useState<TripPlan | null>(null);
  const [routeCandidates, setRouteCandidates] = useState<RouteAlternativeCandidate[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Cross-component interaction state
  const [focusedStationId, setFocusedStationId] = useState<string | null>(null);
  const [hoveredDistanceKm, setHoveredDistanceKm] = useState<number | null>(null);

  // Stable refs for tracking active requests and preventing races
  const hasLoadedRef = React.useRef(false);
  const isBuildingRouteRef = React.useRef(false);
  const activePlanReqIdRef = React.useRef(0);
  const pollCleanupRef = React.useRef<(() => void) | null>(null);

  // Unmount cleanup to stop any in-flight polling
  useEffect(() => {
    return () => {
      if (pollCleanupRef.current) {
        pollCleanupRef.current();
        pollCleanupRef.current = null;
      }
    };
  }, []);

  // 1. Fetch vehicles strictly from /cars
  const fetchCars = useCallback(async () => {
    try {
      const resp = await fetchVehicles();
      if (resp.ok) {
        const data: Record<string, VehicleOptionItem> = await resp.json();
        const carList: VehicleOption[] = Object.values(data).map((c) => ({
          id: c.id,
          name: c.name,
          battery_kwh: c.battery_kwh,
          max_dc_kw: c.max_dc_kw,
          supported_connectors: c.supported_connectors || ["CCS2"],
          is_placeholder_profile: c.is_placeholder_profile,
          description: c.description,
        }));
        setVehicles(carList);
        setApiOnline(true);
        setErrorMessage(null);
      } else {
        setApiOnline(true); // Server is reachable!
        let detail = "";
        try {
          const json = await resp.json();
          detail = json.detail || JSON.stringify(json);
        } catch {
          detail = await resp.text();
        }
        setErrorMessage(`Server Error (HTTP ${resp.status}): ${detail || "Failed to load vehicle catalog"}`);
      }
    } catch (err: unknown) {
      setApiOnline(false);
      setErrorMessage(
        `FastAPI backend is unreachable at ${API_BASE_URL}. Start the server using 'python -m uvicorn api.main:app' to load vehicles and plan routes. (${describeError(err, "Connection failed")})`
      );
    }
  }, []);

  // 2. Fetch plan strictly from /plan (Preserves selected corridor, prevents races)
  const fetchPlan = useCallback(async (targetSnapshotId?: string, fromSavedSnapshot: boolean = false) => {
    // If route building is actively in flight and this is an un-targeted call, ignore it to prevent race
    if (isBuildingRouteRef.current && !targetSnapshotId) {
      return;
    }

    const currentReqId = ++activePlanReqIdRef.current;
    setIsLoading(true);
    setErrorMessage(null);

    const snapshotToUse = targetSnapshotId || params.snapshotId;

    try {
      const resp = await requestTripPlan({
          snapshot_id: snapshotToUse,
          car_id: params.carId,
          start_soc: params.startSoc,
          reserve_soc: params.reserveSoc,
          stop_threshold_soc: params.stopThresholdSoc,
          comfort_weight_lambda: params.comfortLambda,
          K: params.K,
          enable_filter: params.enableFilter,
          from_saved_snapshot: fromSavedSnapshot,
      });

      // Discard stale responses if a newer request was dispatched
      if (activePlanReqIdRef.current !== currentReqId) {
        return;
      }

      if (resp.ok) {
        const data = await resp.json();
        setPlan(data);
        setApiOnline(true);
        setErrorMessage(null);
        setActiveTab("plan");
      } else {
        setApiOnline(true); // Server is reachable!
        let detail = "";
        try {
          const json = await resp.json();
          detail = json.detail || JSON.stringify(json);
        } catch {
          detail = await resp.text();
        }
        setErrorMessage(`Planning Error (HTTP ${resp.status}): ${detail || "Unable to compute trip plan"}`);
      }
    } catch (err: unknown) {
      if (activePlanReqIdRef.current !== currentReqId) {
        return;
      }
      setApiOnline(false);
      setPlan(null);
      setErrorMessage(
        `Backend Unreachable: Unable to connect to ${API_BASE_URL}. Ensure the FastAPI server is running via 'python -m uvicorn api.main:app'. (${describeError(err, "Failed to fetch")})`
      );
    } finally {
      if (activePlanReqIdRef.current === currentReqId) {
        setIsLoading(false);
      }
    }
  }, [params]);

  // 3. Lifecycle-safe asynchronous corridor route building and polling
  const handleBuildAndPlanRoute = useCallback(async (
    srcLoc: LocationWaypoint,
    dstLoc: LocationWaypoint,
    forceRefresh: boolean = true
  ) => {
    // Cancel any previous polling loop
    if (pollCleanupRef.current) {
      pollCleanupRef.current();
      pollCleanupRef.current = null;
    }

    isBuildingRouteRef.current = true;
    setIsLoading(true);
    setErrorMessage(null);
    setRouteCandidates(null);
    setPlan(null);
    ++activePlanReqIdRef.current;

    try {
      const buildResp = await buildCorridor({
          origin: { lat: srcLoc.lat, lon: srcLoc.lon, label: srcLoc.label },
          destination: { lat: dstLoc.lat, lon: dstLoc.lon, label: dstLoc.label },
          use_synthetic: false,
          force_refresh: forceRefresh,
          max_routes: 3,
      });

      if (!buildResp.ok) {
        setApiOnline(true);
        let errDetail = "";
        try {
          const json = await buildResp.json();
          errDetail = json.detail || JSON.stringify(json);
        } catch {
          errDetail = await buildResp.text();
        }
        isBuildingRouteRef.current = false;
        setIsLoading(false);
        setErrorMessage(`Failed to start route builder (HTTP ${buildResp.status}): ${errDetail}`);
        return;
      }

      setApiOnline(true);
      const initialJob = await buildResp.json();
      setJobInfo({
        jobId: initialJob.job_id,
        status: initialJob.status,
        progressStep: initialJob.progress_step || "Initializing corridor route pipeline...",
        percent: initialJob.percent || 5,
        originLabel: srcLoc.label,
        destLabel: dstLoc.label,
      });

      // Polling state controls
      let isCancelled = false;
      let timeoutHandle: ReturnType<typeof setTimeout> | null = null;
      let isPollInFlight = false;
      let consecutiveFailures = 0;
      const MAX_CONSECUTIVE_FAILURES = 5;
      const MAX_POLL_TIMEOUT_MS = 480000; // Compare up to three corridors and their station data.
      const startTime = Date.now();

      const cleanup = () => {
        isCancelled = true;
        if (timeoutHandle) {
          clearTimeout(timeoutHandle);
          timeoutHandle = null;
        }
      };
      const failJob = (message: string) => {
        cleanup();
        isBuildingRouteRef.current = false;
        setIsLoading(false);
        setJobInfo((current) => {
          if (!current || current.jobId !== initialJob.job_id) return current;
          return {
            jobId: current.jobId,
            status: "failed",
            progressStep: "Route build stopped",
            percent: current.percent,
            errorMessage: message,
            originLabel: current.originLabel,
            destLabel: current.destLabel,
          };
        });
      };
      pollCleanupRef.current = cleanup;

      const pollNext = async () => {
        if (isCancelled) return;

        // Check overall timeout
        if (Date.now() - startTime > MAX_POLL_TIMEOUT_MS) {
          failJob("The route builder did not finish within 8 minutes. A slow provider may be delaying the route comparison; retry when the provider is available.");
          return;
        }

        // Prevent overlapping polls
        if (isPollInFlight) return;
        isPollInFlight = true;

        try {
          const jobResp = await fetchRouteBuildJob(initialJob.job_id);
          if (isCancelled) return;

          if (jobResp.ok) {
            setApiOnline(true);
            consecutiveFailures = 0;
            const job = await jobResp.json();
            setJobInfo({
              jobId: job.job_id,
              status: job.status,
              progressStep: job.progress_step,
              percent: job.percent,
              errorMessage: job.error_message,
              originLabel: srcLoc.label,
              destLabel: dstLoc.label,
            });

            if (job.status === "completed") {
              cleanup();
              isBuildingRouteRef.current = false;
              const summaries: RouteAlternativeSummary[] = Array.isArray(job.route_options)
                ? job.route_options
                : [];
              if (summaries.length === 0 && job.snapshot_id) {
                summaries.push({
                  route_number: 1,
                  snapshot_id: job.snapshot_id,
                  distance_km: 0,
                  driving_time_min: 0,
                  station_count: 0,
                });
              }
              if (summaries.length === 0) {
                setJobInfo(null);
                setIsLoading(false);
                setErrorMessage("The route builder completed without returning a route option. Please retry.");
                return;
              }

              setJobInfo({
                jobId: job.job_id,
                status: "running",
                progressStep: "Checking EV range and charging feasibility for each route...",
                percent: 96,
                originLabel: srcLoc.label,
                destLabel: dstLoc.label,
              });
              const compareReqId = ++activePlanReqIdRef.current;
              const checkedRoutes = await Promise.all(summaries.map(async (route) => {
                try {
                  const planResp = await requestTripPlan({
                    snapshot_id: route.snapshot_id,
                    car_id: params.carId,
                    start_soc: params.startSoc,
                    reserve_soc: params.reserveSoc,
                    stop_threshold_soc: params.stopThresholdSoc,
                    comfort_weight_lambda: params.comfortLambda,
                    K: params.K,
                    enable_filter: params.enableFilter,
                    from_saved_snapshot: false,
                  });
                  if (!planResp.ok) {
                    const errorBody = await planResp.json().catch(() => ({}));
                    return {
                      ...route,
                      plan: null,
                      error_message: errorBody.detail || `Planning failed (HTTP ${planResp.status})`,
                    };
                  }
                  const routePlan: TripPlan = await planResp.json();
                  return { ...route, plan: routePlan };
                } catch (routeError: unknown) {
                  return {
                    ...route,
                    plan: null,
                    error_message: describeError(routeError, "Could not check this route."),
                  };
                }
              }));
              if (activePlanReqIdRef.current !== compareReqId) return;

              setJobInfo(null);
              setApiOnline(true);
              setIsLoading(false);
              const orderedRoutes = [...checkedRoutes].sort((a, b) => {
                const feasibilityOrder = Number(Boolean(b.plan?.feasible)) - Number(Boolean(a.plan?.feasible));
                if (feasibilityOrder !== 0) return feasibilityOrder;
                const aStationCount = a.plan?.corridor_stations?.length ?? a.station_count;
                const bStationCount = b.plan?.corridor_stations?.length ?? b.station_count;
                return bStationCount - aStationCount;
              });
              if (orderedRoutes.length > 1) {
                const previewRoute = orderedRoutes[0];
                setParams((prev) => ({ ...prev, snapshotId: previewRoute.snapshot_id }));
                setPlan(previewRoute.plan);
                setRouteCandidates(orderedRoutes);
                setActiveTab("plan");
              } else {
                const onlyRoute = orderedRoutes[0];
                setParams((prev) => ({ ...prev, snapshotId: onlyRoute.snapshot_id }));
                if (onlyRoute.plan) {
                  setPlan(onlyRoute.plan);
                  setActiveTab("plan");
                } else {
                  setErrorMessage(onlyRoute.error_message || "Could not plan this route.");
                }
              }
              return;
            } else if (job.status === "failed") {
              cleanup();
              isBuildingRouteRef.current = false;
              setIsLoading(false);
              return;
            }
          } else {
            setApiOnline(true);
            consecutiveFailures += 1;
            if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
              failJob(`Could not read route build status (HTTP ${jobResp.status}) after several attempts. Retry the route build.`);
              return;
            }
          }
        } catch (pollErr: unknown) {
          if (isCancelled) return;
          consecutiveFailures += 1;
          if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
            setApiOnline(false);
            failJob(`Lost connection to the route builder after several attempts. ${describeError(pollErr, "Check that the API server is running, then retry.")}`);
            return;
          }
        } finally {
          isPollInFlight = false;
          if (!isCancelled) {
            timeoutHandle = setTimeout(pollNext, 700);
          }
        }
      };

      // Start initial poll cycle
      timeoutHandle = setTimeout(pollNext, 700);
    } catch (err: unknown) {
      isBuildingRouteRef.current = false;
      setApiOnline(false);
      setIsLoading(false);
      setErrorMessage(`Route build failed to start: ${describeError(err, "Network error")}`);
    }
  }, [params]);

  // Manual refresh stations handler
  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefreshStations = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await refreshCorridorStations(params.snapshotId);
      await handleBuildAndPlanRoute(origin, destination);
    } catch (err: unknown) {
      console.error("Station refresh failed:", err);
    } finally {
      setIsRefreshing(false);
    }
  }, [params.snapshotId, handleBuildAndPlanRoute, origin, destination]);

  const handleChooseRoute = useCallback((candidate: RouteAlternativeCandidate) => {
    if (!candidate.plan?.feasible) return;
    setParams((prev) => ({ ...prev, snapshotId: candidate.snapshot_id }));
    setPlan(candidate.plan);
    setRouteCandidates(null);
    setErrorMessage(null);
    setActiveTab("plan");
  }, []);

  const handlePreviewRoute = useCallback((candidate: RouteAlternativeCandidate) => {
    if (!candidate.plan) return;
    setParams((prev) => ({ ...prev, snapshotId: candidate.snapshot_id }));
    setPlan(candidate.plan);
    setRouteCandidates(null);
    setErrorMessage(null);
    setActiveTab("plan");
  }, []);

  const handleCloseRouteChoices = useCallback(() => {
    const firstPlan = routeCandidates?.find((candidate) => candidate.plan)?.plan || null;
    if (firstPlan) {
      setParams((prev) => ({ ...prev, snapshotId: firstPlan.snapshot_id || prev.snapshotId }));
      setPlan(firstPlan);
      setActiveTab("plan");
    }
    setRouteCandidates(null);
  }, [routeCandidates]);

  // Initial load only fetches vehicle options. Route searches start only after an
  // explicit user action, so a page refresh never silently builds a default route.
  useEffect(() => {
    if (hasLoadedRef.current) return;
    hasLoadedRef.current = true;
    fetchCars();
  }, [fetchCars]);


  // Handle station selection across map and sidebar
  const handleSelectStation = useCallback((stId: string) => {
    setFocusedStationId(stId);
  }, []);

  const corridorTitle = useMemo(() => {
    const srcCity = plan?.source_name || origin.label.split(",")[0].trim() || "Origin";
    const dstCity = plan?.destination_name || destination.label.split(",")[0].trim() || "Destination";
    const profileDistance = plan?.route_soc_profile?.[plan.route_soc_profile.length - 1]?.distance_km;
    const routeDistance = Array.isArray(plan?.route_distance_km)
      ? plan.route_distance_km[plan.route_distance_km.length - 1]
      : plan?.route_distance_km;
    const distText = plan ? ` (${Math.round(profileDistance ?? routeDistance ?? 0)} km)` : "";
    return plan
      ? `${srcCity} → ${dstCity} Corridor${distText}`
      : "Search for a route";
  }, [origin.label, destination.label, plan]);

  const inputsDiffer = useMemo(() => {
    if (!plan || !plan.source_name || !plan.destination_name) return false;
    const inSrc = origin.label.split(",")[0].trim().toLowerCase();
    const inDst = destination.label.split(",")[0].trim().toLowerCase();
    const planSrc = plan.source_name.split(",")[0].trim().toLowerCase();
    const planDst = plan.destination_name.split(",")[0].trim().toLowerCase();
    return inSrc !== planSrc || inDst !== planDst;
  }, [origin.label, destination.label, plan]);

  return (
    <div className="app-shell flex flex-col overflow-hidden bg-white text-gray-900">
      {/* 48px Top Navigation Bar */}
      <TopBar
        hasPlan={Boolean(plan)}
        synthetic={plan ? Boolean(plan.synthetic) : false}
        dataProvenance={plan ? plan.data_provenance : "open_data_providers"}
        isLiveBuild={plan ? Boolean(plan.is_live_build) : false}
        corridorName={corridorTitle}
        isSidebarOpen={isSidebarOpen}
        onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        apiOnline={apiOnline}
      />

      {/* Main Single-Screen Application Body */}
      <div className="app-body flex flex-1 min-h-0 min-w-0 overflow-hidden relative">
        {/* Left Side Panel (Collapsible on desktop, bottom sheet on mobile) */}
        {isSidebarOpen && (
          <Sidebar
            activeTab={activeTab}
            onTabChange={setActiveTab}
            origin={origin}
            destination={destination}
            onChangeOrigin={setOrigin}
            onChangeDestination={setDestination}
            onBuildAndPlanRoute={handleBuildAndPlanRoute}
            params={params}
            onChangeParams={setParams}
            onPlanTrip={(snapId?: string, fromSavedSnapshot: boolean = false) => fetchPlan(snapId || params.snapshotId, fromSavedSnapshot)}
            isLoading={isLoading}
            vehicles={vehicles}
            plan={plan}
            onSelectStation={handleSelectStation}
            selectedStationId={focusedStationId}
            mobileSheetState={mobileSheetState}
            onChangeMobileSheetState={setMobileSheetState}
            onRefreshStations={handleRefreshStations}
            isRefreshing={isRefreshing}
          />

        )}

        {/* Map Pane with Bottom Data Sources & Attribution Strip */}
        <main className="flex-1 min-h-0 min-w-0 flex flex-col relative overflow-hidden bg-gray-50">
          {/* Inputs Changed Warning Banner */}
          {inputsDiffer && (
            <div className="inputs-changed-banner absolute top-3 left-1/2 -translate-x-1/2 z-[1000] bg-amber-500 text-white px-4 py-2 rounded-lg shadow-lg flex items-center gap-3 text-xs font-semibold">
              <span className="min-w-0 break-words">⚠️ Inputs changed ({origin.label.split(",")[0]} → {destination.label.split(",")[0]}) - plan is showing {plan?.source_name} → {plan?.destination_name}</span>
              <button
                onClick={() => handleBuildAndPlanRoute(origin, destination, true)}
                className="bg-white text-amber-900 px-2.5 py-1 rounded text-xs font-bold hover:bg-amber-50 cursor-pointer shadow-xs transition-colors shrink-0"
              >
                Plan trip (Live providers)
              </button>
            </div>
          )}

          {/* Map & Overlaid Elevation/SoC Drawer Area */}
          <div className="flex-1 min-h-0 min-w-0 relative w-full overflow-hidden">
            <RouteMap
              routePoints={plan ? plan.route_soc_profile : []}
              routeGeometry={plan?.route_geometry || []}
              chosenStops={
                plan && plan.stops
                  ? plan.stops.map((s: ChargingStopInfo) => ({
                      station_id: s.station_id,
                      station_name: s.station_name,
                      operator: s.operator,
                      lat: s.lat || 18.75,
                      lon: s.lon || 73.4,
                      arrival_soc: s.arrival_soc,
                      departure_soc: s.departure_soc,
                      charge_time_min: s.charge_time_min,
                      max_kw: s.max_kw,
                      charging_mode: s.charging_mode,
                      charging_power_kw: s.charging_power_kw,
                      reliability: s.reliability,
                      route_distance_km: s.route_distance_km,
                      power_assumed: s.power_assumed,
                      connector_assumed: s.connector_assumed,
                      spur_estimated: s.spur_estimated,
                      data_provider_name: s.data_provider_name,
                      data_provider_license: s.data_provider_license,
                    }))
                  : []
              }
              corridorStations={plan ? plan.corridor_stations || [] : []}
              focusedStationId={focusedStationId}
              hoveredDistanceKm={hoveredDistanceKm}
              onSelectStation={handleSelectStation}
              activeTab={activeTab}
              originLabel={plan?.source_name || origin.label}
              destinationLabel={plan?.destination_name || destination.label}
            />

          </div>

          {/* Compact map and station data attribution */}
          {plan?.corridor_stations.some((station) => station.source === "ocm" || station.source === "ocm_snapshot") && (
            <div className="w-full bg-white border-t border-gray-200 px-3 py-1 text-[10px] text-gray-500 flex items-center justify-end shrink-0 select-none">
              Station data: <a href="https://openchargemap.org" target="_blank" rel="noopener noreferrer" className="ml-1 hover:text-gray-800">Open Charge Map (CC BY 4.0)</a>
            </div>
          )}

          {/* Route Building Progress Modal */}
          {jobInfo && (
            <RouteProgressModal
              job={jobInfo}
              onClose={() => setJobInfo(null)}
              onRetry={() => handleBuildAndPlanRoute(origin, destination)}
            />
          )}

          {/* Backend Error Modal Overlay (Displayed if backend is unreachable) */}
          {errorMessage && (
            <BackendErrorModal
              errorMessage={errorMessage}
              onRetry={() => {
                void fetchCars();
                if (params.snapshotId) {
                  void fetchPlan(params.snapshotId);
                } else {
                  setErrorMessage(null);
                }
              }}
              onClose={() => setErrorMessage(null)}
              isLoading={isLoading}
            />
          )}
          {routeCandidates && routeCandidates.length > 1 && (
            <RouteAlternativesModal
              routes={routeCandidates}
              onSelect={handleChooseRoute}
              onPreview={handlePreviewRoute}
              onClose={handleCloseRouteChoices}
            />
          )}
        </main>
      </div>
    </div>
  );
}
