// Second copy of the web dev server for side-by-side testing: web on 5181, talking to an API on 8101.
// Normal use is `npm run dev` (web 5180 -> API 8100). Override with POS_API / POS_WEB_PORT if needed.
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const env = {
  ...process.env,
  POS_API: process.env.POS_API || "http://127.0.0.1:8101",
  POS_WEB_PORT: process.env.POS_WEB_PORT || "5181",
};
const vite = path.join(dir, "node_modules", "vite", "bin", "vite.js");
spawn(process.execPath, [vite], { cwd: dir, env, stdio: "inherit" }).on("exit", (code) => process.exit(code ?? 0));
