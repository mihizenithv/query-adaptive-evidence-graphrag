import { existsSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import http from "node:http";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const webDir = path.join(root, "web");
const python = process.platform === "win32" ? "python.exe" : "python3";
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const children = [];

function run(command, args, cwd = root) {
  const result = spawnSync(command, args, { cwd, stdio: "inherit", shell: false });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function portResponds(port, requestPath) {
  return new Promise((resolve) => {
    const request = http.get({ hostname: "127.0.0.1", port, path: requestPath, timeout: 700 }, (response) => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 500);
    });
    request.on("error", () => resolve(false));
    request.on("timeout", () => { request.destroy(); resolve(false); });
  });
}

function pythonDependenciesAvailable() {
  const check = spawnSync(python, ["-c", "import fastapi, uvicorn, pypdf, docx"], { cwd: root, stdio: "ignore", shell: false });
  return check.status === 0;
}

function start(command, args, cwd, env) {
  const useWindowsCommandShell = process.platform === "win32" && command.toLowerCase().endsWith(".cmd");
  const child = spawn(command, args, { cwd, env: { ...process.env, ...env }, stdio: "inherit", shell: useWindowsCommandShell });
  children.push(child);
  child.on("exit", (code) => {
    if (code && code !== 0) process.exitCode = code;
  });
  return child;
}

if (!existsSync(path.join(webDir, "node_modules", "next"))) {
  console.log("Installing frontend dependencies…");
  run(npm, ["install", "--prefix", webDir]);
}

if (!pythonDependenciesAvailable()) {
  console.log("Installing backend dependencies…");
  run(python, ["-m", "pip", "install", "-r", path.join(root, "requirements.txt")]);
}

const apiAlreadyRunning = await portResponds(8001, "/api/health");
const webAlreadyRunning = await portResponds(3000, "/");

if (apiAlreadyRunning) {
  console.log("API already running at http://127.0.0.1:8001");
} else {
  start(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001"], root);
}

if (webAlreadyRunning) {
  console.log("Web app already running at http://127.0.0.1:3000");
} else {
  start(npm, ["run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3000"], webDir, { NEXT_PUBLIC_API_URL: "http://127.0.0.1:8001" });
}

console.log("\nQuery-Adaptive Evidence GraphRAG");
console.log("Open http://127.0.0.1:3000");
console.log("Press Ctrl+C to stop services started by this command.\n");

function shutdown() {
  for (const child of children) child.kill();
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

if (children.length === 0) {
  await new Promise(() => {});
}
