import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Django API runs on :8000; the dev server proxies /api so the browser sees one origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.FORGE_API ?? "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
