import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI app serves index.html at "/" and mounts the build under "/static".
// So assets must be requested from "/static/...", and the build lands in app/static.
const API_PROXY_PATHS = [
  "/cv",
  "/jobs",
  "/ingest",
  "/match",
  "/preferences",
  "/applications",
  "/letters",
  "/targets",
  "/auth",
  "/health",
  "/ready",
];

export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "../app/static",
    emptyOutDir: true,
  },
  server: {
    proxy: Object.fromEntries(
      API_PROXY_PATHS.map((p) => [p, { target: "http://localhost:8000", changeOrigin: true }]),
    ),
  },
});
