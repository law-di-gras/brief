import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = "http://localhost:8000";
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(["/matters", "/items", "/shares", "/p", "/config", "/auth"].map((p) => [p, api])),
  },
});
