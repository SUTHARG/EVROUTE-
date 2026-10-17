"""Elevation analysis script comparing smoothing windows on the Mumbai-Pune corridor."""

import json
from pathlib import Path

import matplotlib.pyplot as plt

from ingest.elevation import smooth_elevation_profile


def run_elevation_study():
    snapshot_path = Path("data/snapshots/real_mumbai_pune.json")
    if not snapshot_path.exists():
        snapshot_path = Path("data/snapshots/synthetic_mumbai_pune_like.json")

    with open(snapshot_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    nodes = data["nodes"]
    # Extract elevation array
    elevs = [nodes[str(i)]["elevation_m"] for i in range(len(nodes))]

    start_elev = elevs[0]
    end_elev = elevs[-1]
    max_elev = max(elevs)

    windows = [3, 5, 7]
    smoothed_results = {}
    ascents = {}

    # Raw ascent
    raw_ascent = sum(max(0.0, elevs[i + 1] - elevs[i]) for i in range(len(elevs) - 1))
    ascents["raw"] = raw_ascent

    for w in windows:
        smoothed, _, ascent_after = smooth_elevation_profile(elevs, window_size=w)
        smoothed_results[w] = smoothed
        ascents[w] = ascent_after

    print("=" * 60)
    print("ELEVATION PROFILE ANALYSIS (Modeling Choice Study)")
    print("=" * 60)
    print(f"Start Elevation: {start_elev:.1f} m")
    print(f"End Elevation:   {end_elev:.1f} m")
    print(f"Peak Elevation:  {max_elev:.1f} m")
    print("-" * 60)
    print(f"Raw Cumulative Ascent:               {ascents['raw']:.1f} m")
    for w in windows:
        reduction = ascents['raw'] - ascents[w]
        pct = (reduction / ascents['raw']) * 100.0 if ascents['raw'] > 0 else 0.0
        print(f"Window size {w}: Ascent = {ascents[w]:.1f} m (diff = -{reduction:.1f} m, -{pct:.1f}%)")
    print("=" * 60)

    # Plot raw vs smoothed profiles
    plt.figure(figsize=(10, 5), dpi=150)
    indices = list(range(len(elevs)))
    plt.plot(indices, elevs, label=f"Raw Elevation (Ascent={ascents['raw']:.0f}m)", color="#94a3b8", alpha=0.7, linewidth=1.0)
    plt.plot(indices, smoothed_results[3], label=f"Smoothed (w=3, Ascent={ascents[3]:.0f}m) [Chosen]", color="#2563eb", linewidth=1.5)
    plt.plot(indices, smoothed_results[5], label=f"Smoothed (w=5, Ascent={ascents[5]:.0f}m)", color="#059669", linestyle="--", linewidth=1.2)
    plt.plot(indices, smoothed_results[7], label=f"Smoothed (w=7, Ascent={ascents[7]:.0f}m)", color="#dc2626", linestyle=":", linewidth=1.2)

    plt.title("Elevation Profile & Smoothing Modeling Choice: Mumbai -> Pune")
    plt.xlabel("Route Node Index")
    plt.ylabel("Elevation (m)")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()

    out_plot = Path("analysis/plots/elevation_smoothing.png")
    plt.savefig(out_plot)
    plt.close()
    print(f"[+] Saved elevation comparison plot to: {out_plot}")


if __name__ == "__main__":
    run_elevation_study()
