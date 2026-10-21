"use client";

import React from "react";
import { Zap, ShieldAlert, Sparkles, Database, PanelLeftClose, PanelLeftOpen, Radio, ShieldCheck } from "lucide-react";
import { API_BASE_URL } from "@/config/api";

export interface TopBarProps {
  hasPlan?: boolean;
  synthetic?: boolean;
  dataProvenance?: string;
  isLiveBuild?: boolean;
  corridorName?: string;
  isSidebarOpen: boolean;
  onToggleSidebar: () => void;
  apiOnline: boolean | null;
}

export const TopBar: React.FC<TopBarProps> = ({
  hasPlan = false,
  synthetic = false,
  dataProvenance = "open_data_providers",
  isLiveBuild = false,
  corridorName = "Mumbai → Pune Express Corridor (150 km)",
  isSidebarOpen,
  onToggleSidebar,
  apiOnline,
}) => {
  return (
    <header className="h-12 w-full bg-white border-b border-gray-200 flex items-center justify-between px-3 z-30 shrink-0 select-none">
      {/* Left: Brand & Sidebar Toggle */}
      <div className="flex items-center gap-2.5 min-w-0 flex-1">
        <button
          onClick={onToggleSidebar}
          aria-label={isSidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
          className="p-1.5 rounded-lg text-gray-500 hover:text-gray-900 hover:bg-gray-100 transition-colors flex items-center justify-center cursor-pointer"
        >
          {isSidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
        </button>

        <div className="flex items-center gap-2 shrink-0">
          <div className="w-7 h-7 rounded-lg bg-green-50 border border-green-200 flex items-center justify-center text-green-600">
            <Zap size={16} />
          </div>
          <span className="font-bold text-sm tracking-tight text-gray-900 font-mono">Route.ev</span>
        </div>

        {/* Corridor Label with clean spacing */}
        <div className="hidden md:flex items-center gap-2 pl-3 border-l border-gray-200 text-xs text-gray-600 font-mono min-w-0 overflow-hidden">
          <span className="text-gray-400 shrink-0">•</span>
          <span className="font-medium text-gray-700 truncate" title={corridorName}>{corridorName}</span>
        </div>
      </div>

      {/* One concise data-status label and backend health indicator */}
      <div className="flex items-center gap-2 flex-nowrap shrink-0">
        {hasPlan && (synthetic ? (
          <div className="has-tooltip">
            <div className="flex items-center gap-1 px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700 text-[11px] font-medium cursor-help whitespace-nowrap">
              <Sparkles size={12} className="shrink-0 text-amber-600" />
              <span>Demo data</span>
            </div>
            <div className="tooltip">Corridor geometry & stations generated via synthetic physics model</div>
          </div>
        ) : dataProvenance === "verified" ? (
          <div className="has-tooltip">
            <div className="flex items-center gap-1 px-2 py-1 rounded-full bg-emerald-50 border border-emerald-300 text-emerald-800 text-[11px] font-medium cursor-help whitespace-nowrap">
              <ShieldCheck size={12} className="shrink-0 text-emerald-600" />
              <span>Verified stations</span>
            </div>
            <div className="tooltip">Station locations have been verified against a registry or checked dataset.</div>
          </div>
        ) : dataProvenance === "manual_unverified" ? (
          <div className="has-tooltip">
            <div className="flex items-center gap-1 px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-800 text-[11px] font-medium cursor-help whitespace-nowrap">
              <ShieldAlert size={12} className="shrink-0 text-amber-600" />
              <span>Unverified stations</span>
            </div>
            <div className="tooltip">Some station details have not been independently verified.</div>
          </div>
        ) : isLiveBuild ? (
          <div className="has-tooltip">
            <div className="flex items-center gap-1 px-2 py-1 rounded-full bg-emerald-50 border border-emerald-300 text-emerald-800 text-[11px] font-medium cursor-help whitespace-nowrap">
              <Radio size={12} className="shrink-0 text-emerald-600" />
              <span>Fresh station data</span>
            </div>
            <div className="tooltip">Station data was refreshed from live providers for this corridor.</div>
          </div>
        ) : (
          <div className="has-tooltip">
            <div className="flex items-center gap-1 px-2 py-1 rounded-full bg-slate-100 border border-slate-200 text-slate-700 text-[11px] font-medium cursor-help whitespace-nowrap">
              <Database size={12} className="shrink-0 text-slate-500" />
              <span>Saved route</span>
            </div>
            <div className="tooltip">Using the saved corridor and its station data.</div>
          </div>
        ))}

        {/* API Health Dot */}
        <div className="has-tooltip ml-1 pl-2 border-l border-gray-200 flex items-center gap-1.5 shrink-0">
          <div
            className={`w-2 h-2 rounded-full ${
              apiOnline === true
                ? "bg-green-600"
                : apiOnline === false
                ? "bg-red-600"
                : "bg-gray-400"
            }`}
          />
          <span className="text-xs text-gray-500 font-medium hidden lg:inline">
            {apiOnline === true ? "API Online" : apiOnline === false ? "API Offline" : "Connecting..."}
          </span>
          <div className="tooltip">
            {apiOnline === true
              ? `FastAPI server running at ${API_BASE_URL}`
              : "Backend server unreachable"}
          </div>
        </div>
      </div>
    </header>
  );
};
