import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Disable Next.js dev tools indicator in bottom-left
  devIndicators: false,
  // Proxy API calls to the Python backend during development
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
