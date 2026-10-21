import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Route.ev — Map-First EV Highway Trip Planner",
  description: "Physics-informed EV trip planner and Pareto trade-off optimization engine for highway corridors.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="h-full w-full overflow-hidden bg-white text-gray-900 font-sans">{children}</body>
    </html>
  );
}

