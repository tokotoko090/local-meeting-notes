import { useEffect, useMemo, useRef, useState } from "react";
import type { AudioDevice, AudioLevel, BackendEvent, Capabilities, PromptResult, GpuStatusResult, SettingsResult, UpdateCheckResult } from "./vite-env";

type RecordingState = "starting" | "idle" | "recording" | "processing" | "complete" | "error";

const API_BASE = window.location.port === "5173" ? "http://127.0.0.1:8765" : window.location.origin;
const silentLevel: AudioLevel = { rms_dbfs: -60, peak_dbfs: -60, clipping: false, active: false, updated_at: 0 };
const mojibakeDeviceNameReplacements: Record<string, string> = {
  "\ufffdT\ufffdE\ufffd\ufffd\ufffdh \ufffd}\ufffdb\ufffdp\ufffd[": "サウンド マッパー",
  "\ufffd}\ufffdC\ufffdN": "マイク",
  "\ufffdw\ufffdb\ufffdh\ufffdZ\ufffdb\ufffdg": "ヘッドセット",
  "\ufffdw\ufffdb\ufffdh\ufffdz\ufffd\ufffd": "ヘッドホン",
  "\ufffdX\ufffds\ufffd[\ufffdJ\ufffd[": "スピーカー",
  "\ufffdC\ufffd\ufffd\ufffdt\ufffdH\ufffd\ufffd": "イヤフォン",
  "\ufffdC\ufffd\ufffd\ufffd^\ufffdt\ufffdF\ufffd[\ufffdX": "インターフェース",
  "\ufffdf\ufffdo\ufffdC\ufffdX": "デバイス"
};

export function formatElapsed(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export function eventMessage(event: BackendEvent): string {
  return event.message || event.file || event.output_dir || event.model || event.transcribe_device || "";
}

function normalizeDisplayText(text: string): string {
  return text.replace(/\u0000/g, "").trim();
}

function normalizeDeviceName(name: string): string {
  let normalized = name.replace(/\u0000/g, "").replace(/\s+/g, " ").trim();
  for (const [source, target] of Object.entries(mojibakeDeviceNameReplacements)) {
    normalized = normalized.replaceAll(source, target);
  }
  return normalized.replace(/\ufffd+/g, "").trim() || "Unknown";
}

export function eventLabel(eventName: string): string {
  const labels: Record<string, string> = {
    complete: "完了",
    error: "エラー",
    log: "ログ",
    process_closed: "処理終了",
    prompt_generated: "プロンプト作成",
    record_one_complete: "録音保存",
    recording_started: "録音開始",
    recording_starting: "録音準備",
    recording_stopped: "録音停止",
    status: "状態",
    transcript_generated: "文字起こし作成",
    transcription_complete: "文字起こし完了",
    transcription_queued: "文字起こし待機",
    transcription_started: "文字起こし開始",
    transcribing: "文字起こし中",
    warning: "警告"
  };
  return labels[eventName] || eventName;
}

function deviceKindLabel(kind: AudioDevice["kind"]): string {
  if (kind === "mic") return "マイク";
  if (kind === "system") return "PC出力";
  return "その他";
}

export function useMeetingApp() {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const monitorSupported = useRef(false);
  monitorSupported.current = capabilities?.platform === "win32" && !!capabilities.audio_monitor;
  const [closing, setClosing] = useState(false);
  const closingRequested = useRef(false);
  const [promptReady, setPromptReady] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  const [state, commitState] = useState<RecordingState>("idle");
  const stateRef = useRef<RecordingState>("idle");
  function setState(next: RecordingState | ((current: RecordingState) => RecordingState)) {
    const value = typeof next === "function" ? next(stateRef.current) : next;
    stateRef.current = value;
    commitState(value);
  }
  const [model, setModel] = useState("");
  const [transcribeDevice, setTranscribeDevice] = useState("");
  const [monitoring, setMonitoring] = useState(false);
  const [monitorBusy, setMonitorBusy] = useState(false);
  const [audioLevels, setAudioLevels] = useState({ mic: silentLevel, system: silentLevel });
  const monitorRevision = useRef(0);
  const monitorWanted = useRef(false);
  const monitorQueue = useRef<Promise<unknown>>(Promise.resolve());
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [devicesLoaded, setDevicesLoaded] = useState(false);
  const [selectedMicDeviceIndex, setSelectedMicDeviceIndex] = useState<number | "">("");
  const [selectedSystemDeviceIndex, setSelectedSystemDeviceIndex] = useState<number | "">("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [stage, setStage] = useState("prepare");
  const [canRecover, setCanRecover] = useState(false);
  const [outputDir, setOutputDir] = useState("");
  const [outputRootDir, setOutputRootDir] = useState("");
  const [defaultOutputRootDir, setDefaultOutputRootDir] = useState("");
  const [promptTemplate, setPromptTemplate] = useState("");
  const [defaultPromptTemplate, setDefaultPromptTemplate] = useState("");
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [existingOutputDir, setExistingOutputDir] = useState("");
  const [micDevice, setMicDevice] = useState("");
  const [systemDevice, setSystemDevice] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [events, setEvents] = useState<BackendEvent[]>([]);
  const [updateInfo, setUpdateInfo] = useState<UpdateCheckResult | null>(null);
  const [updateStatus, setUpdateStatus] = useState("");
  const [updateBusy, setUpdateBusy] = useState(false);
  const [downloadedInstaller, setDownloadedInstaller] = useState("");
  const [gpuStatus, setGpuStatus] = useState<GpuStatusResult | null>(null);
  const [gpuBusy, setGpuBusy] = useState(false);
  const startedAt = useRef<number | null>(null);
  const lastEventId = useRef(0);
  const lifecycleRevision = useRef(0);
  const operationEpoch = useRef(0);

  function handleBackendEvent(payload: BackendEvent) {
    if (payload.event === "audio_level") return;
    if (["recording_starting", "recording_started", "recording_stopped", "transcription_queued", "transcription_started", "transcribing", "transcription_complete", "transcript_generated", "prompt_generated", "complete", "error", "process_closed"].includes(payload.event)) lifecycleRevision.current += 1;
    setEvents((current) => [payload, ...current].slice(0, 100));

    if (typeof payload.duration_seconds === "number") setElapsed(payload.duration_seconds);
    if (payload.event === "recording_stopped" || payload.event === "transcription_queued") setCanRecover(true);
    if (payload.output_dir) {
      setOutputDir(normalizeDisplayText(payload.output_dir));
    }
    if (payload.event === "recording_starting") { setState("starting"); setPromptReady(false); setCopyStatus(""); }
    if (payload.event === "prompt_generated") { setPromptReady(true); setStage("done"); }
    if (payload.event === "status" && payload.message?.includes("モデル")) {
      setNotice(payload.message);
      setStage(current => current === "prepare" || current === "model" ? "model" : current);
    }
    if (payload.event === "transcription_complete" || (payload.event === "transcribing" && payload.file === "system.wav")) setNotice(current => current.includes("モデル") ? "" : current);
    if (payload.event === "transcribing") setStage(payload.file === "system.wav" ? "system" : "mic");
    if (payload.event === "transcription_complete" || payload.event === "transcript_generated") setStage("files");
    if (payload.event === "recording_started") {
      startedAt.current = Date.now();
      setElapsed(0);
      setError("");
      setState("recording");
      setMicDevice(payload.mic_device ? normalizeDeviceName(payload.mic_device) : "");
      setSystemDevice(payload.system_device ? normalizeDeviceName(payload.system_device) : "");
    }
    if (payload.event === "recording_stopped" || payload.event === "transcription_started" || payload.event === "transcription_queued") {
      startedAt.current = null;
      setState("processing");
      setPromptReady(false);
      setCopyStatus("");
    }
    if (payload.event === "warning") {
      setNotice(payload.message || "処理からのお知らせがあります。");
    }
    if (payload.event === "complete" && stateRef.current !== "error") {
      startedAt.current = null;
      setState("complete");
    }
    if (payload.event === "process_closed" && payload.code === 0) {
      startedAt.current = null;
      setState((current) => (current === "processing" || current === "recording" ? "complete" : current));
    }
    if (payload.event === "process_closed" && payload.code !== 0) {
      startedAt.current = null;
      setState("error");
      setError((current) => current || "録音または処理がエラーで停止しました。モデルを小さくして再実行できます。");
    }
    if (payload.event === "error") {
      startedAt.current = null;
      setState("error");
      setError((current) => payload.message || current || "処理に失敗しました。");
    }
  }

  async function apiCall(path: string, body?: unknown) {
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        method: body ? "POST" : "GET",
        headers: body ? { "content-type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch {
      return { ok: false, error: "ローカル処理に接続できません。アプリを再起動してください。" };
    }
  }

  async function loadSettings() {
    try {
      const result: SettingsResult = await apiCall("/api/settings");
      if (result.ok) {
        if (result.model) setModel(result.model);
        if (result.transcribe_device) setTranscribeDevice(result.transcribe_device);
        setPromptTemplate(result.prompt_template ?? "");
        setDefaultPromptTemplate(result.default_prompt_template ?? "");
        setSettingsLoaded(true);
        setOutputRootDir(normalizeDisplayText(result.output_root || ""));
        setDefaultOutputRootDir(normalizeDisplayText(result.default_output_root || ""));
      }
    } catch {
      setDefaultOutputRootDir("");
    }
  }

  async function saveTranscriptionSetting(key: "model" | "transcribe_device", value: string) {
    if (!settingsLoaded) return;
    const result: SettingsResult = await apiCall("/api/settings", { [key]: value });
    if (!result.ok) {
      setNotice(result.error || "設定を保存できませんでした。");
      return;
    }
    if (key === "model") setModel(result.model ?? value);
    else setTranscribeDevice(result.transcribe_device ?? value);
  }

  function stopAudioMonitor() {
    monitorWanted.current = false;
    monitorRevision.current += 1;
    setMonitoring(false);
    setAudioLevels({ mic: silentLevel, system: silentLevel });
    if (!monitorSupported.current) return Promise.resolve({ ok: true });
    const task = monitorQueue.current.then(() => apiCall("/api/audio-monitor/stop", {}));
    monitorQueue.current = task;
    return task;
  }

  async function toggleAudioMonitor() {
    if (monitorWanted.current) { await stopAudioMonitor(); return; }
    if (!capabilities?.audio_monitor || capabilities.platform !== "win32" || monitorBusy || closingRequested.current || closing || ["starting", "recording", "processing"].includes(stateRef.current)) return;
    monitorWanted.current = true;
    const revision = ++monitorRevision.current;
    setMonitorBusy(true);
    const task = monitorQueue.current.then(() => revision === monitorRevision.current
      ? apiCall("/api/audio-monitor/start", { micDeviceIndex: selectedMicDeviceIndex, systemDeviceIndex: selectedSystemDeviceIndex })
      : { ok: false });
    monitorQueue.current = task;
    const result = await task;
    if (revision === monitorRevision.current) {
      setMonitoring(!!result.ok);
      monitorWanted.current = !!result.ok;
      if (!result.ok) { setNotice(result.error || "入力テストを開始できませんでした。"); await stopAudioMonitor(); }
    }
    setMonitorBusy(false);
  }

  useEffect(() => {
    if (!capabilities?.audio_monitor || capabilities.platform !== "win32" || closing || (!monitoring && state !== "recording")) {
      setAudioLevels({ mic: silentLevel, system: silentLevel });
      return;
    }
    let canceled = false;
    let fetching = false;
    let lastResponse = 0;
    let latest = { mic: silentLevel, system: silentLevel };
    const holds = { mic: 0, system: 0 };
    async function poll() {
      if (!fetching) {
        fetching = true;
        void apiCall("/api/audio-levels").then(result => {
          if (!canceled && result.ok && result.levels) {
            latest = result.levels; lastResponse = Date.now();
            if (monitoring && monitorWanted.current && result.monitoring === false) {
              monitorWanted.current = false;
              setMonitoring(false);
              setNotice(result.error || "入力テストが停止しました。音声デバイスを確認してください。");
            }
          }
        }).finally(() => { fetching = false; });
      }
      const now = Date.now();
      setAudioLevels(previous => Object.fromEntries((["mic", "system"] as const).map(source => {
        const value = latest[source];
        if (!value?.active || now - lastResponse > 1500 || now - value.updated_at * 1000 > 1500) return [source, silentLevel];
        const peak = Math.max(-60, Math.min(0, value.peak_dbfs));
        if (peak >= previous[source].peak_dbfs) holds[source] = now + 350;
        return [source, { ...value, peak_dbfs: Math.max(peak, previous[source].peak_dbfs - (now >= holds[source] ? 4 : 0)) }];
      })) as typeof previous);
    }
    void poll();
    const timer = window.setInterval(poll, 120);
    return () => { canceled = true; window.clearInterval(timer); };
  }, [capabilities, monitoring, state, closing]);

  useEffect(() => () => { if (monitorWanted.current) void stopAudioMonitor(); }, []);

  useEffect(() => {
    const onPageHide = () => {
      if (!monitorSupported.current || !monitorWanted.current) return;
      monitorWanted.current = false;
      monitorRevision.current += 1;
      void fetch(`${API_BASE}/api/audio-monitor/stop`, {
        method: "POST", headers: { "content-type": "application/json" }, body: "{}", keepalive: true
      }).catch(() => {});
    };
    window.addEventListener("pagehide", onPageHide);
    return () => window.removeEventListener("pagehide", onPageHide);
  }, []);

  async function savePromptTemplate(text: string): Promise<SettingsResult> {
    if (["starting", "recording", "processing"].includes(stateRef.current) || closing) return { ok: false, error: "録音・文字起こし中は変更できません。" };
    const result: SettingsResult = await apiCall("/api/settings", { prompt_template: text });
    if (result.ok) {
      setPromptTemplate(result.prompt_template ?? text);
      if (result.default_prompt_template !== undefined) setDefaultPromptTemplate(result.default_prompt_template);
    }
    return result;
  }

  async function readPrompt(outputDir: string): Promise<PromptResult> {
    return apiCall("/api/prompt/read", { outputDir });
  }

  async function savePrompt(outputDir: string, text: string, copy: boolean): Promise<PromptResult> {
    if (["starting", "recording", "processing"].includes(stateRef.current) || closing) return { ok: false, saved: false, error: "録音・文字起こし中は編集できません。" };
    const result: PromptResult = await apiCall("/api/prompt/save", { outputDir, text, copy });
    if (result.saved) setCopyStatus("");
    return result;
  }

  async function saveOutputRoot(outputRoot: string) {
    const result: SettingsResult = await apiCall("/api/settings", { output_root: outputRoot });
    if (result.ok) {
      setOutputRootDir(normalizeDisplayText(result.output_root || ""));
      setDefaultOutputRootDir(normalizeDisplayText(result.default_output_root || ""));
    } else { setNotice(result.error || "保存先を変更できませんでした。"); }
  }

  useEffect(() => {
    let canceled = false;
    let fetching = false;
    async function poll() {
      if (closing || fetching) return;
      fetching = true;
      try {
        const response = await fetch(`${API_BASE}/api/events?since=${lastEventId.current}`);
        if (!response.ok) throw new Error("Connection failed");
        const data = await response.json();
        if (canceled) return;
        setConnectionError("");
        for (const payload of data.events || []) {
          if (typeof payload.id === "number") {
            if (payload.id <= lastEventId.current) continue;
            lastEventId.current = payload.id;
          }
          handleBackendEvent(payload);
        }
      } catch {
        if (!canceled) setConnectionError("アプリとの接続を確認しています。録音・処理の状態は接続後に更新されます。");
      } finally { fetching = false; }
    }
    void poll();
    const timer = window.setInterval(poll, 700);
    return () => { canceled = true; window.clearInterval(timer); };
  }, [closing]);

  useEffect(() => {
    if (state !== "recording") {
      return;
    }
    const timer = window.setInterval(() => {
      if (startedAt.current) {
        setElapsed((Date.now() - startedAt.current) / 1000);
      }
    }, 250);
    return () => window.clearInterval(timer);
  }, [state]);

  const statusLabel = useMemo(() => {
    if (closing) return "保存して終了中";
    if (state === "starting") return "録音準備中";
    if (state === "recording") return "録音中";
    if (state === "processing") return "処理中";
    if (state === "complete") return "完了";
    if (state === "error") return "エラー";
    return "待機中";
  }, [state, closing]);

  async function refreshDevices() {
    if (monitorWanted.current) await stopAudioMonitor();
    const result = await apiCall("/api/devices");
    if (result.ok) {
      const nextDevices: AudioDevice[] = (result.devices || []).map((device: AudioDevice) => ({ ...device, name: normalizeDeviceName(device.name) }));
      setDevices(nextDevices);
      setDevicesLoaded(true);
      if (selectedMicDeviceIndex === "") {
        const firstMic = nextDevices.find((device) => device.kind === "mic" && device.is_default) || nextDevices.find((device) => device.kind === "mic" && device.sample_rate === 48000) || nextDevices.find((device) => device.kind === "mic");
        if (firstMic) setSelectedMicDeviceIndex(firstMic.index);
      }
      if (selectedSystemDeviceIndex === "") {
        const firstSystem =
          nextDevices.find((device) => device.kind === "system" && device.name.includes("Game")) ||
          nextDevices.find((device) => device.kind === "system") ||
          undefined;
        if (firstSystem) setSelectedSystemDeviceIndex(firstSystem.index);
      }
    } else {
      setDevicesLoaded(true);
      setNotice(result.error || "音声デバイスを読み込めませんでした。");
    }
  }

  async function startRecording() {
    if (!capabilities || !devicesLoaded || !devices.some(device => device.kind === "mic") || ["starting", "recording", "processing"].includes(stateRef.current) || closing) return;
    const epoch = ++operationEpoch.current;
    setState("starting");
    if (capabilities.audio_monitor) await stopAudioMonitor();
    if (epoch !== operationEpoch.current || closingRequested.current) { setState("idle"); return; }
    setCanRecover(false); setPromptReady(false); setCopyStatus(""); setOutputDir(""); setNotice(""); setElapsed(0); setStage("prepare");
    setError("");
    const options = { micDeviceId: devices.find(d => d.index === selectedMicDeviceIndex && d.kind === "mic")?.id, model, transcribeDevice, micDeviceIndex: selectedMicDeviceIndex, systemDeviceIndex: selectedSystemDeviceIndex, outputRoot: outputRootDir };
    const revision = lifecycleRevision.current;
    const result = await apiCall("/api/recording/start", options);
    if (operationEpoch.current !== epoch) return;
    if (!result.ok && lifecycleRevision.current === revision && stateRef.current === "starting") {
      setState("error");
      setError(result.error || "録音を開始できませんでした。");
    }
  }

  async function stopRecording() {
    if (stateRef.current !== "recording") return;
    setStage("prepare");
    setState("processing");
    const revision = lifecycleRevision.current;
    const result = await apiCall("/api/recording/stop", {});
    if (!result.ok) {
      if (lifecycleRevision.current === revision && (stateRef.current as RecordingState) === "processing") {
        setNotice(result.error || "録音を停止できませんでした。再度停止してください。");
        setState("recording");
      }
    }
  }

  async function openFolder() {
    const result = await apiCall("/api/output/open", { outputDir });
    if (!result.ok) {
      setNotice(result.error || "保存フォルダを開けませんでした。");
    }
  }

  async function copyPrompt() {
    const epoch = operationEpoch.current;
    const result = await apiCall("/api/prompt/copy", { outputDir });
    if (operationEpoch.current !== epoch) return;
    if (result.ok) setCopyStatus("コピーしました");
    else setNotice(result.error || "コピーできませんでした。");
  }

  async function transcribeExisting() {
    const target = existingOutputDir.trim();
    if (!capabilities || !target || ["starting", "recording", "processing"].includes(stateRef.current) || closing) return;
    const epoch = ++operationEpoch.current;
    setCanRecover(false); setPromptReady(false); setCopyStatus(""); setOutputDir(target); setNotice(""); setStage("prepare");
    setError("");
    setState("processing");
    const options = { outputDir: target, model, transcribeDevice };
    if (capabilities.audio_monitor) await stopAudioMonitor();
    if (epoch !== operationEpoch.current || closingRequested.current) { setState("idle"); return; }
    const revision = lifecycleRevision.current;
    const result = await apiCall("/api/transcribe-existing", options);
    if (operationEpoch.current !== epoch) return;
    if (!result.ok) {
      if (lifecycleRevision.current === revision && stateRef.current === "processing") {
        setError(result.error || "文字起こしを開始できませんでした。");
        setState("error");
      }
      return;
    }
    if (result.output_dir) {
      setCanRecover(true);
      setOutputDir(normalizeDisplayText(result.output_dir));
      setExistingOutputDir(normalizeDisplayText(result.output_dir));
    }
  }

  async function pickExistingOutputFolder() {
    setNotice("");
    const result = await apiCall("/api/output/pick-directory", {});
    if (result.ok && result.output_dir) {
      setExistingOutputDir(normalizeDisplayText(result.output_dir));
      return;
    }
    if (!result.canceled) {
      setNotice(result.error || "フォルダ選択を開けませんでした。");
    }
  }

  async function pickRecordingOutputRoot() {
    setNotice("");
    const result = await apiCall("/api/output/pick-recording-root", {});
    if (result.ok && result.output_dir) {
      await saveOutputRoot(result.output_dir);
      return;
    }
    if (!result.canceled) {
      setNotice(result.error || "保存先を選択できませんでした。");
    }
  }

  async function refreshGpuStatus() {
    try {
      const result: GpuStatusResult = await apiCall("/api/gpu/status");
      setGpuStatus(result);
    } catch {
      setGpuStatus({ ok: false, state: "cpu", label: "CPUで実行中", error: "GPU状態を確認できませんでした。" });
    }
  }

  async function setupGpuRuntime() {
    setGpuBusy(true);
    setGpuStatus({ ok: true, state: "setting_up", label: "GPU(CUDA)セットアップ中", message: "GPU(CUDA)対応コンポーネントを追加インストールしています。" });
    try {
      const result: GpuStatusResult = await apiCall("/api/gpu/setup", {});
      setGpuStatus(result);
      if (!result.ok) {
        setNotice(result.error || "GPU(CUDA)セットアップに失敗しました。CPUで続行できます。");
      } else {
        setNotice("");
      }
    } finally {
      setGpuBusy(false);
    }
  }

  async function checkForUpdates() {
    setUpdateBusy(true);
    setUpdateStatus("更新を確認しています...");
    setNotice("");
    setDownloadedInstaller("");
    try {
      const result: UpdateCheckResult = await apiCall("/api/update/check");
      setUpdateInfo(result);
      if (!result.ok) {
        setUpdateStatus(result.error || "更新を確認できませんでした。");
      } else if (result.update_available) {
        setUpdateStatus(`バージョン ${result.latest_version} が利用できます。`);
      } else {
        setUpdateStatus(`最新版です。現在のバージョン: ${result.current_version || "不明"}`);
      }
    } finally {
      setUpdateBusy(false);
    }
  }

  async function downloadUpdate() {
    setUpdateBusy(true);
    setUpdateStatus("インストーラーをダウンロードしています...");
    setNotice("");
    try {
      const result: UpdateCheckResult = await apiCall("/api/update/download", {});
      if (!result.ok) {
        setUpdateStatus(result.error || "更新をダウンロードできませんでした。");
        return;
      }
      setDownloadedInstaller(result.installer_path || "");
      setUpdateStatus(`バージョン ${result.latest_version || ""} をダウンロードしました。`);
    } finally {
      setUpdateBusy(false);
    }
  }

  async function installUpdate() {
    setUpdateBusy(true);
    setUpdateStatus("インストーラーを起動しています...");
    setNotice("");
    try {
      const result: UpdateCheckResult = await apiCall("/api/update/install", {});
      if (!result.ok) {
        setUpdateStatus(result.error || "インストーラーを起動できませんでした。");
        return;
      }
      setUpdateStatus("インストーラーを起動しました。アプリは終了します。");
    } finally {
      setUpdateBusy(false);
    }
  }

  async function shutdownApp() {
    if (closingRequested.current) return;
    closingRequested.current = true;
    operationEpoch.current += 1;
    setClosing(true);
    if (capabilities?.audio_monitor) await stopAudioMonitor();
    setNotice("");
    const result = await apiCall("/api/shutdown", {});
    if (!result.ok) {
      closingRequested.current = false;
      setClosing(false);
      setNotice(result.error || "アプリを終了できませんでした。");
      return;
    }
    setClosing(true);
    setNotice("録音を保存して終了します。文字起こし中の場合は処理の完了を待ちます。");
  }

  async function refreshCapabilities() {
    const result = await apiCall("/api/capabilities");
    if (!result.ok) {
      setNotice(result.error || "処理設定を取得できませんでした。アプリを再起動してください。");
      return;
    }
    setCapabilities(result);
    setModel((current) => result.models.some((option: { id: string }) => option.id === current) ? current : result.default_model);
    setTranscribeDevice((current) => result.platform === "darwin" ? "mlx" : result.transcribe_devices.includes(current) ? current : result.default_transcribe_device || "auto");
    if (result.cuda_setup) void refreshGpuStatus();
  }

  useEffect(() => {
    // Apply validated saved choices after capability defaults, regardless of request timing.
    void refreshCapabilities().then(loadSettings);
    void refreshDevices();
  }, []);

  useEffect(() => {
    const onClosing = () => { closingRequested.current = true; operationEpoch.current += 1; if (monitorWanted.current) void stopAudioMonitor(); setClosing(true); };
    window.addEventListener("meeting-app-closing", onClosing);
    return () => window.removeEventListener("meeting-app-closing", onClosing);
  }, []);

  function newRecording() {
    if (["starting", "recording", "processing"].includes(stateRef.current) || closing) return;
    operationEpoch.current += 1;
    setState("idle"); setError(""); setNotice(""); setPromptReady(false); setCopyStatus(""); setOutputDir(""); setElapsed(0); setCanRecover(false); setStage("prepare");
  }

  const micDevices = devices.filter((device) => device.kind === "mic");
  const systemDevices = devices.filter((device) => device.kind === "system");



  const busy = closing || state === "starting" || state === "recording" || state === "processing";
  return { capabilities, closing, promptReady, copyStatus, state, model, setModel: (value: string) => void saveTranscriptionSetting("model", value),
    transcribeDevice, setTranscribeDevice: (value: string) => void saveTranscriptionSetting("transcribe_device", value), devices, selectedMicDeviceIndex,
    setSelectedMicDeviceIndex: (value: number | "") => { if (monitorWanted.current) void stopAudioMonitor(); setSelectedMicDeviceIndex(value); },
    selectedSystemDeviceIndex, setSelectedSystemDeviceIndex: (value: number | "") => { if (monitorWanted.current) void stopAudioMonitor(); setSelectedSystemDeviceIndex(value); }, error, outputDir, outputRootDir,
    monitoring, monitorBusy, audioLevels, toggleAudioMonitor, stopAudioMonitor,
    defaultOutputRootDir, promptTemplate, defaultPromptTemplate, settingsLoaded, savePromptTemplate, readPrompt, savePrompt, existingOutputDir, setExistingOutputDir, micDevice, systemDevice, elapsed, events,
    updateInfo, updateStatus, updateBusy, downloadedInstaller, gpuStatus, gpuBusy, statusLabel, busy, devicesLoaded,
    micDevices, systemDevices, startRecording, stopRecording, transcribeExisting, openFolder, copyPrompt,
    pickExistingOutputFolder, pickRecordingOutputRoot, refreshDevices, refreshCapabilities, refreshGpuStatus,
    setupGpuRuntime, checkForUpdates, downloadUpdate, installUpdate, shutdownApp, notice, connectionError, stage, canRecover, newRecording,
  };
}

export type MeetingApp = ReturnType<typeof useMeetingApp>;
