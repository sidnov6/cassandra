import type { NextConfig } from "next";

// Static export so a single FastAPI process can serve the UI + /api on one origin/port
// (required for Hugging Face Spaces, and makes SSE work without a proxy). The app is fully
// client-rendered and talks to the API via NEXT_PUBLIC_BACKEND_URL (set to "" at build time
// for same-origin /api in the export).
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
