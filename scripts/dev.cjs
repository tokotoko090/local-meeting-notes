const { spawn } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const viteBin = path.join(root, "node_modules", ".bin", process.platform === "win32" ? "vite.cmd" : "vite");
const electronBin = require("electron");
const port = 5173;

const api = spawn("python", ["backend/server.py"], {
  cwd: root,
  stdio: "inherit",
  env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" }
});

const vite = spawn(viteBin, ["--host", "127.0.0.1", "--port", String(port)], {
  cwd: root,
  stdio: "inherit",
  env: { ...process.env, BROWSER: "none" },
  shell: process.platform === "win32"
});

function waitForServer(retries = 80) {
  return new Promise((resolve, reject) => {
    const tick = () => {
      const request = http.get(`http://127.0.0.1:${port}`, (response) => {
        response.resume();
        resolve();
      });
      request.on("error", () => {
        if (retries <= 0) {
          reject(new Error("Vite dev server did not start."));
          return;
        }
        retries -= 1;
        setTimeout(tick, 250);
      });
    };
    tick();
  });
}

waitForServer()
  .then(() => {
    const electron = spawn(electronBin, ["--disable-gpu", "--disable-software-rasterizer", "."], {
      cwd: root,
      stdio: "inherit",
      env: { ...process.env, VITE_DEV_SERVER_URL: `http://127.0.0.1:${port}` }
    });
    electron.on("error", (error) => {
      console.error("Electron failed to start:", error);
      api.kill();
      vite.kill();
      process.exit(1);
    });
    electron.on("exit", (code) => {
      console.error(`Electron exited with code ${code}`);
      if (code === 3221225477) {
        console.error(`Electron crashed before startup. Browser fallback is available at http://127.0.0.1:${port}`);
        return;
      }
      api.kill();
      vite.kill();
      process.exit(code ?? 0);
    });
  })
  .catch((error) => {
    console.error(error);
    api.kill();
    vite.kill();
    process.exit(1);
  });
