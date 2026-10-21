"use client";

import React from "react";
import { AlertCircle, RotateCw, Terminal } from "lucide-react";

interface BackendErrorModalProps {
  errorMessage: string;
  onRetry: () => void;
  onClose?: () => void;
  isLoading: boolean;
}

export const BackendErrorModal: React.FC<BackendErrorModalProps> = ({
  errorMessage,
  onRetry,
  onClose,
  isLoading,
}) => {
  const isConnectionError =
    errorMessage.toLowerCase().includes("unreachable") ||
    errorMessage.toLowerCase().includes("unable to connect") ||
    errorMessage.toLowerCase().includes("connection refused") ||
    errorMessage.toLowerCase().includes("failed to fetch");

  return (
    <div className="absolute inset-0 bg-gray-900/40 backdrop-blur-xs z-50 flex items-center justify-center p-4">
      <div className="max-w-md w-full p-6 rounded-2xl border border-red-300 bg-white shadow-xl flex flex-col gap-4 text-center">
        <div className="w-12 h-12 rounded-full bg-red-50 border border-red-200 flex items-center justify-center mx-auto text-red-600">
          <AlertCircle size={24} />
        </div>

        <div>
          <h3 className="text-base font-bold text-gray-900">
            {isConnectionError ? "Backend Connection Error" : "API / Planning Error"}
          </h3>
          <p className="text-xs text-red-700 mt-2 leading-relaxed text-left bg-red-50 p-3 rounded-xl border border-red-200 font-mono break-words">
            {errorMessage}
          </p>
        </div>

        {isConnectionError && (
          <div className="text-left text-xs text-gray-600 space-y-1.5 bg-gray-50 p-3 rounded-xl border border-gray-200">
            <div className="flex items-center gap-1.5 text-gray-800 font-semibold">
              <Terminal size={14} className="text-green-600" />
              <span>How to start backend server:</span>
            </div>
            <div className="font-mono text-xs text-gray-900 bg-white border border-gray-200 px-2 py-1 rounded">
              python -m uvicorn api.main:app --port 8000
            </div>
            <div className="text-[11px] text-gray-500">
              Client-side silent fallback is disabled. Route planning requires the live FastAPI engine.
            </div>
          </div>
        )}

        <div className="flex gap-2 mt-1">
          {onClose && (
            <button
              onClick={onClose}
              className="flex-1 py-2.5 px-4 rounded-xl text-xs font-semibold bg-gray-100 hover:bg-gray-200 text-gray-700 transition-colors cursor-pointer"
            >
              Dismiss
            </button>
          )}
          <button
            onClick={onRetry}
            disabled={isLoading}
            className="flex-1 py-2.5 px-4 rounded-xl text-xs font-semibold bg-green-600 hover:bg-green-700 text-white transition-colors flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60 shadow-xs"
          >
            {isLoading ? <RotateCw size={14} className="animate-spin" /> : <RotateCw size={14} />}
            <span>Retry</span>
          </button>
        </div>
      </div>
    </div>
  );
};
