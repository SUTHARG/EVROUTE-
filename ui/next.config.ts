import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // React Leaflet removes its map instance in an effect cleanup. Next's
  // development Strict Mode replay leaves that same container uninitialized,
  // which breaks TileLayer mounting and can reset the visible route.
  reactStrictMode: false,
};

export default nextConfig;
