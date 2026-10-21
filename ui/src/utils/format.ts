/**
 * Formatting utilities for Route.ev frontend.
 */

export function formatDuration(minutes: number): string {
  if (isNaN(minutes) || minutes <= 0) return "0 min";
  const totalMin = Math.round(minutes);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h === 0) return `${m} min`;
  if (m === 0) return `${h} h`;
  return `${h} h ${m} min`;
}

export function formatDistance(km: number): string {
  if (isNaN(km) || km < 0) return "0.0 km";
  return `${km.toFixed(1)} km`;
}

export function formatPercent(frac: number): string {
  if (isNaN(frac) || frac < 0) return "0%";
  return `${Math.round(frac * 100)}%`;
}
