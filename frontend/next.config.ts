import type { NextConfig } from "next";

const api = process.env.API_INTERNAL_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/health", destination: `${api}/health` },
    ];
  },
  async redirects() {
    return [
      { source: "/app", destination: "/client", permanent: false },
      { source: "/app/:path*", destination: "/client/:path*", permanent: false },
    ];
  },
};

export default nextConfig;
