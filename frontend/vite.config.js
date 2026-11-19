import { defineConfig, loadEnv } from "vite";

// Frontend dev server: http://localhost:5173. API calls (/api/...) are proxied to the FastAPI backend,
// so no CORS setup is needed in development. Point VITE_BACKEND_URL elsewhere if the API runs on another host/port.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_BACKEND_URL || "http://127.0.0.1:8000";
  const proxy = { "/api": { target: backend, changeOrigin: true } };
  return {
    server: { port: 5173, strictPort: true, proxy },
    preview: { port: 4173, strictPort: true, proxy },
    build: { outDir: "dist", emptyOutDir: true },
  };
});
