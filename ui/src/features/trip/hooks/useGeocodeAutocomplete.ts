"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL } from "@/config/api";

export interface GeocodeCandidate {
  label: string;
  lat: number;
  lon: number;
}

export function useGeocodeAutocomplete() {
  const [fromQuery, setFromQuery] = useState("");
  const [toQuery, setToQuery] = useState("");
  const [fromCandidates, setFromCandidates] = useState<GeocodeCandidate[]>([]);
  const [toCandidates, setToCandidates] = useState<GeocodeCandidate[]>([]);
  const [isSearchingFrom, setIsSearchingFrom] = useState(false);
  const [isSearchingTo, setIsSearchingTo] = useState(false);
  const [showFromDropdown, setShowFromDropdown] = useState(false);
  const [showToDropdown, setShowToDropdown] = useState(false);

  useEffect(() => {
    if (!showFromDropdown || !fromQuery.trim()) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setIsSearchingFrom(true);
      try {
        const query = encodeURIComponent(fromQuery.trim());
        const response = await fetch(`${API_BASE_URL}/geocode?q=${query}&limit=5`, {
          signal: controller.signal,
        });
        if (response.ok) {
          setFromCandidates((await response.json()) as GeocodeCandidate[]);
        }
      } catch (error: unknown) {
        if (!controller.signal.aborted) console.error("Origin geocode error:", error);
      } finally {
        if (!controller.signal.aborted) setIsSearchingFrom(false);
      }
    }, 500);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [fromQuery, showFromDropdown]);

  useEffect(() => {
    if (!showToDropdown || !toQuery.trim()) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setIsSearchingTo(true);
      try {
        const query = encodeURIComponent(toQuery.trim());
        const response = await fetch(`${API_BASE_URL}/geocode?q=${query}&limit=5`, {
          signal: controller.signal,
        });
        if (response.ok) {
          setToCandidates((await response.json()) as GeocodeCandidate[]);
        }
      } catch (error: unknown) {
        if (!controller.signal.aborted) console.error("Destination geocode error:", error);
      } finally {
        if (!controller.signal.aborted) setIsSearchingTo(false);
      }
    }, 500);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [toQuery, showToDropdown]);

  return {
    fromQuery,
    setFromQuery,
    toQuery,
    setToQuery,
    fromCandidates,
    setFromCandidates,
    toCandidates,
    setToCandidates,
    isSearchingFrom,
    isSearchingTo,
    showFromDropdown,
    setShowFromDropdown,
    showToDropdown,
    setShowToDropdown,
  };
}
