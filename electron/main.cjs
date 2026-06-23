const { app, BrowserWindow, clipboard, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");

const root = path.resolve(__dirname, "..");
const logPath = path.join(root, "electron.log");
let mainWindow = null;
let recorder = null;
let transcriber = null;
let latestOutputDir = null;

function writeMainLog(message) {
  fs.appendFileSync(logPath, `${new Date().toISOString()} ${message}\n`, "utf8");
}

function pythonCommand() {
  const venvPython = path.join(root, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venvPython)) {
    return venvPython;
  }
  return "python";
}

function backendArgs(args) {
  return [path.join(root, "backend", "meeting_notes.py"), ...args];
}

function sendBackendEvent(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("backend:event", payload);
  }
}

function createWindow() {
  writeMainLog("createWindow");
  mainWindow = new BrowserWindow({
    width: 1040,
    height: 760,
    minWidth: 860,
    minHeight: 640,
    backgroundColor: "#f7f7f4",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    writeMainLog(`loadURL ${process.env.VITE_DEV_SERVER_URL}`);
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    writeMainLog("loadFile dist/index.html");
    mainWindow.loadFile(path.join(root, "dist", "index.html"));
  }
}

function spawnBackend(args) {
  return spawn(pythonCommand(), backendArgs(args), {
    cwd: root,
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
    env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" }
  });
}

function attachProcess(child, processName, onClose) {
  const stdout = readline.createInterface({ input: child.stdout });
  stdout.on("line", (line) => {
    try {
      const payload = JSON.parse(line);
      if (payload.output_dir) {
        latestOutputDir = payload.output_dir;
      }
      sendBackendEvent(payload);
    } catch {
      sendBackendEvent({ event: "log", message: line });
    }
  });

  child.stderr.on("data", (chunk) => {
    sendBackendEvent({ event: "log", message: chunk.toString("utf8") });
  });

  child.on("close", (code) => {
    sendBackendEvent({
      event: code === 0 ? "process_closed" : "error",
      code,
      output_dir: latestOutputDir,
      message: code === 0 ? "Complete." : `${processName} process failed.`
    });
    onClose();
  });
}

ipcMain.handle("devices:list", async () => {
  return new Promise((resolve) => {
    const child = spawnBackend(["list-devices", "--json"]);
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("close", (code) => {
      let devices = [];
      try {
        devices = JSON.parse(stdout).devices || [];
      } catch {
        devices = [];
      }
      resolve({ ok: code === 0, output: stdout.trim(), devices, error: stderr.trim() });
    });
  });
});

ipcMain.handle("recording:start", async (_event, options = {}) => {
  if (recorder || transcriber) {
    return { ok: false, error: "Another recording or transcription process is already running." };
  }

  const model = options.model || "small";
  const transcribeDevice = options.transcribeDevice || "cpu";
  const args = ["record", "--model", model, "--transcribe-device", transcribeDevice];
  if (options.micDeviceIndex !== undefined && options.micDeviceIndex !== "") {
    args.push("--mic-device-index", String(options.micDeviceIndex));
  }
  if (options.systemDeviceIndex !== undefined && options.systemDeviceIndex !== "") {
    args.push("--system-device-index", String(options.systemDeviceIndex));
  }
  recorder = spawnBackend(args);
  latestOutputDir = null;
  attachProcess(recorder, "Recording", () => {
    recorder = null;
  });

  return { ok: true };
});

ipcMain.handle("recording:stop", async () => {
  if (!recorder) {
    return { ok: false, error: "Recording is not running." };
  }
  recorder.stdin.write("stop\n");
  return { ok: true };
});

ipcMain.handle("transcribe:existing", async (_event, options = {}) => {
  if (recorder || transcriber) {
    return { ok: false, error: "Another recording or transcription process is already running." };
  }
  const outputDir = options.outputDir || latestOutputDir;
  if (!outputDir || !fs.existsSync(outputDir)) {
    return { ok: false, error: "Output folder does not exist." };
  }
  latestOutputDir = outputDir;
  const model = options.model || "small";
  const transcribeDevice = options.transcribeDevice || "cpu";
  sendBackendEvent({ event: "transcription_queued", output_dir: outputDir, model, transcribe_device: transcribeDevice });
  transcriber = spawnBackend(["generate", outputDir, "--transcribe", "--model", model, "--transcribe-device", transcribeDevice]);
  attachProcess(transcriber, "Transcription", () => {
    transcriber = null;
  });
  return { ok: true, output_dir: outputDir };
});

ipcMain.handle("output:pick-directory", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Select an existing Local Meeting Notes output folder",
    defaultPath: path.join(root, "output"),
    properties: ["openDirectory"]
  });
  if (result.canceled || result.filePaths.length === 0) {
    return { ok: false, canceled: true };
  }
  return { ok: true, output_dir: result.filePaths[0] };
});

ipcMain.handle("output:open", async (_event, outputDir) => {
  const target = outputDir || latestOutputDir;
  if (!target) {
    return { ok: false, error: "No output folder is available yet." };
  }
  const error = await shell.openPath(target);
  return { ok: !error, error };
});

ipcMain.handle("prompt:copy", async (_event, outputDir) => {
  const target = outputDir || latestOutputDir;
  if (!target) {
    return { ok: false, error: "No output folder is available yet." };
  }
  const promptPath = path.join(target, "chatgpt_prompt.md");
  if (!fs.existsSync(promptPath)) {
    return { ok: false, error: "chatgpt_prompt.md has not been generated yet." };
  }
  clipboard.writeText(fs.readFileSync(promptPath, "utf8"));
  return { ok: true };
});

app.whenReady().then(() => {
  writeMainLog("app ready");
  createWindow();
});

app.on("window-all-closed", () => {
  writeMainLog("window-all-closed");
  if (recorder) {
    recorder.kill();
  }
  if (transcriber) {
    transcriber.kill();
  }
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
