import { defineConfig } from "vite";

// In development the viewer runs on Vite and everything else comes from the Spikecast
// server (`uv run spikecast serve`) on port 8000.
const server = "http://localhost:8000";

export default defineConfig({
  build: {
    rollupOptions: { input: { main: "index.html", explain: "explain.html", film: "film.html" } },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": server,
      "/sessions": server,
      "/data": server,
      // The trailing slash matters: without it this would also catch /film.html.
      "/film/": server,
      "/ws": { target: server, ws: true },
    },
  },
});
