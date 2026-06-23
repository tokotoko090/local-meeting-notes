const { spawn } = require("node:child_process");
const { execFile } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const port = 5173;
const apiPort = 8765;
const requiredApiVersion = "0.1.5";
const viteBin = path.join(root, "node_modules", ".bin", process.platform === "win32" ? "vite.cmd" : "vite");

function waitFor(url, retries = 80) {
  return new Promise((resolve, reject) => {
    const tick = () => {
      const request = http.get(url, (response) => {
        response.resume();
        resolve();
      });
      request.on("error", () => {
        if (retries <= 0) {
          reject(new Error(`${url} did not start.`));
          return;
        }
        retries -= 1;
        setTimeout(tick, 250);
      });
    };
    tick();
  });
}

function readJson(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => {
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });
    request.on("error", reject);
    request.setTimeout(1500, () => {
      request.destroy(new Error(`${url} timed out`));
    });
  });
}

function execFileText(command, args) {
  return new Promise((resolve) => {
    execFile(command, args, { windowsHide: true }, (_error, stdout) => {
      resolve(stdout || "");
    });
  });
}

async function killPortListeners(targetPort) {
  if (process.platform !== "win32") return;
  const output = await execFileText("netstat.exe", ["-ano"]);
  const pids = new Set();
  for (const line of output.split(/\r?\n/)) {
    if (!line.includes(`:${targetPort}`) || !line.includes("LISTENING")) continue;
    const parts = line.trim().split(/\s+/);
    const pid = parts[parts.length - 1];
    if (/^\d+$/.test(pid) && pid !== "0") pids.add(pid);
  }
  for (const pid of pids) {
    await execFileText("taskkill.exe", ["/PID", pid, "/F"]);
  }
}

async function ensureFreshApiPort() {
  try {
    const health = await readJson(`http://127.0.0.1:${apiPort}/api/health`);
    if (health.server_version === requiredApiVersion) return;
  } catch {
    // No compatible server is running.
  }
  await killPortListeners(apiPort);
}

const commonEnv = {
  ...process.env,
  PYTHONUTF8: "1",
  PYTHONIOENCODING: "utf-8",
  BROWSER: "none"
};

let api;
let vite;
const keepAlive = setInterval(() => {}, 60 * 60 * 1000);

function stopAll() {
  clearInterval(keepAlive);
  if (api && !api.killed) api.kill();
  if (vite && !vite.killed) vite.kill();
}

process.on("SIGINT", () => {
  stopAll();
  process.exit(0);
});
process.on("SIGTERM", () => {
  stopAll();
  process.exit(0);
});

Promise.all([
  ensureFreshApiPort().then(() => {
    api = spawn("python", ["backend/server.py"], {
      cwd: root,
      stdio: "inherit",
      env: commonEnv
    });
    return waitFor(`http://127.0.0.1:${apiPort}/api/health`);
  }),
  Promise.resolve().then(() => {
    vite = spawn(viteBin, ["--host", "127.0.0.1", "--port", String(port)], {
      cwd: root,
      stdio: "inherit",
      env: commonEnv,
      shell: process.platform === "win32"
    });
    return waitFor(`http://127.0.0.1:${port}`);
  })
])
  .then(() => {
    const url = `http://127.0.0.1:${port}`;
    console.log(`Local Meeting Notes is ready: ${url}`);
    if (process.platform === "win32") {
      spawn("cmd.exe", ["/c", "start", "", url], { detached: true, stdio: "ignore" }).unref();
    }
  })
  .catch((error) => {
    console.error(error);
    stopAll();
    process.exit(1);
  });
