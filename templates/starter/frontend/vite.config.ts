import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
  server: {
    proxy: {
      // During local `vite dev`, forward API calls to the backend so the
      // frontend and backend can run as two dev processes on two ports.
      // In production this doesn't matter: Express serves this build's
      // static output directly, same origin.
      "/api": "http://localhost:3000",
    },
  },
});
