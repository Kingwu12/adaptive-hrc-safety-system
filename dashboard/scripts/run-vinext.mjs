// Environment assignment works on Windows as well as POSIX shells.
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
const cli = fileURLToPath(new URL("../node_modules/vinext/dist/cli.js", import.meta.url));
const args = process.argv.slice(2);
const preload = process.platform === "win32" && args[0] === "start"
  ? ["--import", new URL("./windows-static-cache.mjs", import.meta.url).href]
  : [];
const child = spawn(process.execPath, [...preload, cli, ...args], {
  stdio: "inherit",
  env: { ...process.env, WRANGLER_LOG_PATH: ".wrangler/wrangler.log" },
});
child.on("error", error => { console.error(error.message); process.exitCode = 1; });
child.on("exit", (code) => { process.exitCode = code ?? 1; });
