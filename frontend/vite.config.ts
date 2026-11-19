import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

// POS_API / POS_WEB_PORT let a second copy run side by side (e.g. for testing); defaults are the normal ports.
const API = process.env.POS_API || "http://127.0.0.1:8100";
const WEB_PORT = Number(process.env.POS_WEB_PORT || 5180);
// POS_LAN=1 ("Phones on" in the server controller): serve on the shop network over https, so phones and
// tablets can use their cameras to scan. The API itself stays on 127.0.0.1; phones reach it only through
// the /api proxy below (never the database admin site, which isn't proxied).
const LAN = process.env.POS_LAN === "1";

export default defineConfig({
  plugins: [react(), ...(LAN ? [basicSsl({ name: "pos-system-lan" })] : [])],
  server: {
    port: WEB_PORT,
    strictPort: true,
    host: LAN ? "0.0.0.0" : "127.0.0.1",
    proxy: {
      "/api": {
        target: API,
        changeOrigin: true, // the API only accepts its own host names
        xfwd: true, // pass the phone's address on (X-Forwarded-For) for logs
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
      "/media": { target: API, changeOrigin: true },
    },
  },
});
