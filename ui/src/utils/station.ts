export interface StationPowerDetails {
  max_kw: number;
  max_ac_kw?: number | null;
  max_dc_kw?: number | null;
  connector_types?: string[];
  power_assumed?: boolean;
}

export function stationPowerLabel(station: StationPowerDetails): string {
  if (station.max_dc_kw) return `${station.max_dc_kw} kW DC`;
  if (station.max_ac_kw) return `${station.max_ac_kw} kW AC`;
  const hasDcPlug = station.connector_types?.some((connector) => /ccs|chademo/i.test(connector));
  const hasAcPlug = station.connector_types?.some((connector) => /type\s*2/i.test(connector));
  if (!hasDcPlug && hasAcPlug && station.power_assumed) return "7.2 kW AC assumed";
  return `${station.max_kw} kW${hasDcPlug ? " DC" : ""}`;
}

export function isAvailabilityLive(
  availability?: { last_updated?: string | null } | null,
): boolean {
  if (!availability) return false;
  if (!availability.last_updated) return true;
  const updatedAt = new Date(availability.last_updated).getTime();
  return Number.isFinite(updatedAt) && Date.now() - updatedAt < 3600 * 1000;
}

export function formatFetchedTime(isoString?: string | null): string {
  if (!isoString) return "Unavailable";
  const fetchedAt = new Date(isoString);
  if (!Number.isFinite(fetchedAt.getTime())) return isoString;
  return fetchedAt.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
