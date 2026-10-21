"use client";

import React from "react";
import { CheckCircle2, Loader2, AlertCircle, X } from "lucide-react";

export interface JobProgressInfo {
  jobId: string;
  status: "pending" | "running" | "completed" | "failed";
  progressStep: string;
  percent: number;
  errorMessage?: string | null;
  originLabel?: string;
  destLabel?: string;
}

interface RouteProgressModalProps {
  job: JobProgressInfo;
  onClose?: () => void;
  onRetry?: () => void;
}

const PIPELINE_STEPS = [
  { id: "osrm", label: "Querying OSRM driving route with road geometry", minPct: 10 },
  { id: "stations", label: "Ingesting corridor charging stations (OCM & Overpass)", minPct: 35 },
  { id: "elevation", label: "Sampling and smoothing route elevation profile", minPct: 60 },
  { id: "amenities", label: "Populating station amenities and comfort scores", minPct: 80 },
  { id: "graph", label: "Assembling road network graph and caching snapshot", minPct: 95 },
];

export const RouteProgressModal: React.FC<RouteProgressModalProps> = ({
  job,
  onClose,
  onRetry,
}) => {
  const isFailed = job.status === "failed";
  const isCompleted = job.status === "completed";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4 select-none animate-in fade-in duration-200">
      <div className="w-full max-w-md bg-white rounded-2xl border border-gray-200 shadow-xl overflow-hidden text-gray-900">
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
          <div>
            <div className="text-xs uppercase font-semibold text-gray-500 tracking-wider">
              Corridor Route Pipeline
            </div>
            <h3 className="text-sm font-bold text-gray-900">
              {isCompleted
                ? "Corridor Ready"
                : isFailed
                ? "Route Build Error"
                : "Building Road-Following Route"}
            </h3>
          </div>
          {onClose && (isCompleted || isFailed) && (
            <button
              onClick={onClose}
              className="p-1 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 cursor-pointer"
            >
              <X size={16} />
            </button>
          )}
        </div>

        {/* Origin & Destination Waypoints */}
        <div className="px-5 py-3 bg-gray-50 border-b border-gray-100 text-xs flex items-center justify-between text-gray-600">
          <div className="truncate max-w-[170px]">
            <span className="font-semibold text-gray-800">From:</span>{" "}
            {job.originLabel || "Origin"}
          </div>
          <span className="text-gray-400">→</span>
          <div className="truncate max-w-[170px] text-right">
            <span className="font-semibold text-gray-800">To:</span>{" "}
            {job.destLabel || "Destination"}
          </div>
        </div>

        {/* Content Body */}
        <div className="p-5 space-y-4">
          {/* Progress Bar */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs font-medium">
              <span className="text-gray-600">{job.progressStep || "Working..."}</span>
              <span className="font-mono font-bold text-green-700">{job.percent}%</span>
            </div>
            <div className="w-full h-2 rounded-full bg-gray-100 overflow-hidden">
              <div
                className={`h-full transition-all duration-300 rounded-full ${
                  isFailed ? "bg-red-500" : "bg-green-600"
                }`}
                style={{ width: `${Math.min(100, Math.max(5, job.percent))}%` }}
              />
            </div>
          </div>

          {/* Pipeline Stages Checklist */}
          <div className="space-y-2 pt-1">
            {PIPELINE_STEPS.map((step) => {
              const stepDone = job.percent >= step.minPct || isCompleted;
              const stepActive =
                !stepDone && !isFailed && job.percent >= step.minPct - 25;

              return (
                <div
                  key={step.id}
                  className="flex items-center gap-2.5 text-xs text-gray-700"
                >
                  {stepDone ? (
                    <CheckCircle2 size={16} className="text-green-600 shrink-0" />
                  ) : stepActive ? (
                    <Loader2 size={16} className="text-green-600 shrink-0 animate-spin" />
                  ) : (
                    <div className="w-4 h-4 rounded-full border border-gray-300 shrink-0 flex items-center justify-center text-[10px] text-gray-400">
                      •
                    </div>
                  )}
                  <span
                    className={
                      stepDone
                        ? "text-gray-900 font-medium"
                        : stepActive
                        ? "text-green-800 font-semibold"
                        : "text-gray-400"
                    }
                  >
                    {step.label}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Failure Alert */}
          {isFailed && (
            <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-800 space-y-2">
              <div className="flex items-center gap-2 font-semibold">
                <AlertCircle size={15} className="text-red-600 shrink-0" />
                <span>Pipeline encountered an error</span>
              </div>
              <div className="font-mono text-[11px] text-red-700 break-words">
                {job.errorMessage || "Unknown build error."}
              </div>
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="mt-2 w-full py-1.5 px-3 rounded-lg bg-red-600 hover:bg-red-700 text-white font-medium text-xs cursor-pointer"
                >
                  Retry Pipeline
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
