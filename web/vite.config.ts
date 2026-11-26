import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/sessions": { target: "http://localhost:8000", ws: true },
      "/nodes": "http://localhost:8000",
      "/routing": "http://localhost:8000",
      "/byok": "http://localhost:8000",
      "/experiments": "http://localhost:8000",
      "/questionnaire": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/export.csv": "http://localhost:8000",
    },
  },
  build: { outDir: "dist" },
});
