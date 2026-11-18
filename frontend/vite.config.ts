import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// POS_API / POS_WEB_PORT let a second copy run side by side (e.g. for testing); defaults are the normal ports.
const API = process.env.POS_API || "http://127.0.0.1:8100";
const WEB_PORT = Number(process.env.POS_WEB_PORT || 5180);

export default defineConfig({
  plugins: [react()],
  server: {
    port: WEB_PORT,
    strictPort: true,
    proxy: {
      "/api": {
        target: API,
        // Backend down -> 503 (not Vite's default 500) so the POS switches to offline mode.
        configure: (proxy) => {
          proxy.on("error", (_err, _req, res) => {
            if ("writeHead" in res && !res.headersSent) {
              res.writeHead(503, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ detail: "API unreachable" }));
            }
          });
        },
      },
      // Product and category pictures uploaded through the back office.
      "/media": { target: API },
    },
  },
});
