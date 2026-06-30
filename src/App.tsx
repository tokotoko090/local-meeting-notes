import { Cpu, Download, FolderOpen, Mic, Play, Power, RefreshCcw, Square, Upload, Volume2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { AudioDevice, BackendEvent, UpdateCheckResult } from "./vite-env";

type RecordingState = "idle" | "recording" | "processing" | "complete" | "error";

const modelOptions = ["base", "small", "medium"];
const transcribeDeviceOptions = ["cpu", "auto", "cuda"];
const API_BASE = "http://127.0.0.1:8765";

function formatElapsed(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function eventMessage(event: BackendEvent): string {
  return event.message || event.file || event.output_dir || event.model || event.transcribe_device || "";
}

function eventLabel(eventName: string): string {
  const labels: Record<string, string> = {
    complete: "完了",
    error: "エラー",
    log: "ログ",
    process_closed: "処理終了",
    prompt_generated: "プロンプト作成",
    record_one_complete: "録音保存",
    recording_started: "録音開始",
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

export default function App() {
  const [state, setState] = useState<RecordingState>("idle");
  const [model, setModel] = useState("base");
  const [transcribeDevice, setTranscribeDevice] = useState("cpu");
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [selectedMicDeviceIndex, setSelectedMicDeviceIndex] = useState<number | "">("");
  const [selectedSystemDeviceIndex, setSelectedSystemDeviceIndex] = useState<number | "">("");
  const [error, setError] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [existingOutputDir, setExistingOutputDir] = useState("");
  const [micDevice, setMicDevice] = useState("");
  const [systemDevice, setSystemDevice] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [events, setEvents] = useState<BackendEvent[]>([]);
  const [updateInfo, setUpdateInfo] = useState<UpdateCheckResult | null>(null);
  const [updateStatus, setUpdateStatus] = useState("");
  const [updateBusy, setUpdateBusy] = useState(false);
  const [downloadedInstaller, setDownloadedInstaller] = useState("");
  const startedAt = useRef<number | null>(null);
  const lastEventId = useRef(0);

  function handleBackendEvent(payload: BackendEvent) {
    setEvents((current) => [payload, ...current].slice(0, 14));

    if (payload.output_dir) {
      setOutputDir(payload.output_dir);
    }
    if (payload.event === "recording_started") {
      startedAt.current = Date.now();
      setElapsed(0);
      setError("");
      setState("recording");
      setMicDevice(payload.mic_device || "");
      setSystemDevice(payload.system_device || "");
    }
    if (payload.event === "recording_stopped" || payload.event === "transcription_started" || payload.event === "transcription_queued") {
      setState("processing");
    }
    if (payload.event === "warning") {
      setError(payload.message || "Warning");
    }
    if (payload.event === "complete") {
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
      setError("録音または処理がエラーで停止しました。");
    }
    if (payload.event === "error") {
      startedAt.current = null;
      setState("error");
      setError(payload.message || "処理に失敗しました。");
    }
  }

  async function apiCall(path: string, body?: unknown) {
    const response = await fetch(`${API_BASE}${path}`, {
      method: body ? "POST" : "GET",
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined
    });
    return response.json();
  }

  useEffect(() => {
    if (!window.meetingNotes) {
      const timer = window.setInterval(async () => {
        try {
          const response = await fetch(`${API_BASE}/api/events?since=${lastEventId.current}`);
          const data = await response.json();
          for (const payload of data.events || []) {
            if (typeof payload.id === "number") {
              lastEventId.current = Math.max(lastEventId.current, payload.id);
            }
            handleBackendEvent(payload);
          }
        } catch {
          setError("ローカルAPIが起動していません。画面を閉じて Local Meeting Notes を起動し直してください。");
        }
      }, 700);
      return () => window.clearInterval(timer);
    }
    return window.meetingNotes.onBackendEvent((payload) => {
      handleBackendEvent(payload);
    });
  }, []);

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
    if (state === "recording") return "録音中";
    if (state === "processing") return "処理中";
    if (state === "complete") return "完了";
    if (state === "error") return "エラー";
    return "待機中";
  }, [state]);

  async function refreshDevices() {
    const result = window.meetingNotes ? await window.meetingNotes.listDevices() : await apiCall("/api/devices");
    if (result.ok) {
      const nextDevices: AudioDevice[] = result.devices || [];
      setDevices(nextDevices);
      if (selectedMicDeviceIndex === "") {
        const firstMic = nextDevices.find((device) => device.kind === "mic" && device.sample_rate === 48000) || nextDevices.find((device) => device.kind === "mic");
        if (firstMic) setSelectedMicDeviceIndex(firstMic.index);
      }
      if (selectedSystemDeviceIndex === "") {
        const firstSystem =
          nextDevices.find((device) => device.kind === "system" && device.name.includes("Game")) ||
          nextDevices.find((device) => device.kind === "system") ||
          undefined;
        if (firstSystem) setSelectedSystemDeviceIndex(firstSystem.index);
      }
      setError("");
    } else {
      setError(result.error || "音声デバイスを読み込めませんでした。");
    }
  }

  async function startRecording() {
    const options = { model, transcribeDevice, micDeviceIndex: selectedMicDeviceIndex, systemDeviceIndex: selectedSystemDeviceIndex };
    const result = window.meetingNotes ? await window.meetingNotes.startRecording(options) : await apiCall("/api/recording/start", options);
    if (!result.ok) {
      setError(result.error || "録音を開始できませんでした。");
    }
  }

  async function stopRecording() {
    setState("processing");
    const result = window.meetingNotes ? await window.meetingNotes.stopRecording() : await apiCall("/api/recording/stop", {});
    if (!result.ok) {
      setError(result.error || "録音を停止できませんでした。");
      setState("error");
    }
  }

  async function openFolder() {
    const result = window.meetingNotes ? await window.meetingNotes.openOutputFolder(outputDir) : await apiCall("/api/output/open", { outputDir });
    if (!result.ok) {
      setError(result.error || "保存フォルダを開けませんでした。");
    }
  }

  async function transcribeExisting() {
    const target = existingOutputDir.trim();
    setError("");
    setState("processing");
    const options = { outputDir: target, model, transcribeDevice };
    const result = window.meetingNotes?.transcribeExisting ? await window.meetingNotes.transcribeExisting(options) : await apiCall("/api/transcribe-existing", options);
    if (!result.ok) {
      setError(result.error || "文字起こしを開始できませんでした。");
      setState("error");
      return;
    }
    if (result.output_dir) {
      setOutputDir(result.output_dir);
      setExistingOutputDir(result.output_dir);
    }
  }

  async function pickExistingOutputFolder() {
    setError("");
    const result = window.meetingNotes?.pickOutputFolder ? await window.meetingNotes.pickOutputFolder() : await apiCall("/api/output/pick-directory", {});
    if (result.ok && result.output_dir) {
      setExistingOutputDir(result.output_dir);
      return;
    }
    if (!result.canceled) {
      setError(result.error || "フォルダ選択を開けませんでした。");
    }
  }

  async function checkForUpdates() {
    setUpdateBusy(true);
    setUpdateStatus("更新を確認しています...");
    setError("");
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
    setError("");
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
    setError("");
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
    setError("");
    const result = await apiCall("/api/shutdown", {});
    if (!result.ok) {
      setError(result.error || "アプリを終了できませんでした。");
      return;
    }
    setState("complete");
    setError("アプリを終了しています。このタブを閉じてください。");
  }

  useEffect(() => {
    void refreshDevices();
  }, []);

  const micDevices = devices.filter((device) => device.kind === "mic");
  const systemDevices = devices.filter((device) => device.kind === "system");

  function deviceLabel(device: AudioDevice): string {
    return `[${device.index}] ${device.name} (${device.channels}ch, ${device.sample_rate}Hz)`;
  }

  return (
    <main className="app">
      <section className="topbar">
        <div>
          <h1>Local Meeting Notes</h1>
          <p>マイク音声とPC出力音声を別々に録音し、ローカルで文字起こしします。</p>
        </div>
        <div className={`status ${state}`}>
          <span>{statusLabel}</span>
          <strong>{formatElapsed(elapsed)}</strong>
        </div>
      </section>

      <section className="notice">
        録音前に参加者の同意を取ってください。ファイルはこのPC内の保存フォルダにだけ保存されます。
      </section>

      <section className="updateBar">
        <div>
          <h2>アップデート</h2>
          <p>{updateStatus || "GitHub Releasesに新しいインストーラーがあるか確認します。"}</p>
          {updateInfo?.release_url && (
            <a href={updateInfo.release_url} target="_blank" rel="noreferrer">
              Releaseを開く
            </a>
          )}
        </div>
        <div className="updateActions">
          <button className="secondary" type="button" onClick={checkForUpdates} disabled={updateBusy || state === "recording" || state === "processing"} title="更新を確認">
            <RefreshCcw size={18} />
            確認
          </button>
          <button
            className="secondary"
            type="button"
            onClick={downloadUpdate}
            disabled={updateBusy || !updateInfo?.update_available || state === "recording" || state === "processing"}
            title="更新インストーラーをダウンロード"
          >
            <Download size={18} />
            ダウンロード
          </button>
          <button
            className="primary"
            type="button"
            onClick={installUpdate}
            disabled={updateBusy || !downloadedInstaller || state === "recording" || state === "processing"}
            title="ダウンロードしたインストーラーを起動"
          >
            <Upload size={18} />
            インストール
          </button>
          <button className="danger" type="button" onClick={shutdownApp} disabled={state === "recording" || state === "processing"} title="アプリを終了">
            <Power size={18} />
            終了
          </button>
        </div>
      </section>

      <section className="controls">
        <div className="controlGroup">
          <label htmlFor="model">文字起こしモデル</label>
          <select id="model" value={model} onChange={(event) => setModel(event.target.value)} disabled={state === "recording" || state === "processing"}>
            {modelOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="controlGroup">
          <label htmlFor="transcribe-device">処理デバイス</label>
          <select
            id="transcribe-device"
            value={transcribeDevice}
            onChange={(event) => setTranscribeDevice(event.target.value)}
            disabled={state === "recording" || state === "processing"}
          >
            {transcribeDeviceOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="controlGroup wide">
          <label htmlFor="mic-device">マイク</label>
          <select
            id="mic-device"
            value={selectedMicDeviceIndex}
            onChange={(event) => setSelectedMicDeviceIndex(event.target.value === "" ? "" : Number(event.target.value))}
            disabled={state === "recording" || state === "processing"}
          >
            <option value="">自動</option>
            {micDevices.map((device) => (
              <option key={device.index} value={device.index}>
                {deviceLabel(device)}
              </option>
            ))}
          </select>
        </div>

        <div className="controlGroup wide">
          <label htmlFor="system-device">PC出力</label>
          <select
            id="system-device"
            value={selectedSystemDeviceIndex}
            onChange={(event) => setSelectedSystemDeviceIndex(event.target.value === "" ? "" : Number(event.target.value))}
            disabled={state === "recording" || state === "processing"}
          >
            <option value="">自動</option>
            {systemDevices.map((device) => (
              <option key={device.index} value={device.index}>
                {deviceLabel(device)}
              </option>
            ))}
          </select>
        </div>

        <button className="secondary" type="button" onClick={refreshDevices} disabled={state === "recording" || state === "processing"} title="デバイスを再読み込み">
          <RefreshCcw size={18} />
          デバイス
        </button>

        <button className="primary" type="button" onClick={startRecording} disabled={state === "recording" || state === "processing"} title="録音を開始">
          <Play size={18} />
          録音開始
        </button>

        <button className="danger" type="button" onClick={stopRecording} disabled={state !== "recording"} title="録音を停止">
          <Square size={18} />
          録音停止
        </button>
      </section>

      <section className="controls rerun">
        <div className="controlGroup grow">
          <label htmlFor="existing-output">既存の保存フォルダ</label>
          <div className="folderPicker">
            <input id="existing-output" value={existingOutputDir} placeholder="保存フォルダを選択" readOnly disabled={state === "recording" || state === "processing"} />
            <button className="secondary" type="button" onClick={pickExistingOutputFolder} disabled={state === "recording" || state === "processing"} title="保存フォルダを選択">
              <FolderOpen size={18} />
              参照
            </button>
          </div>
        </div>
        <button
          className="secondary"
          type="button"
          onClick={transcribeExisting}
          disabled={state === "recording" || state === "processing" || !existingOutputDir.trim()}
          title="既存の保存フォルダを文字起こし"
        >
          <Cpu size={18} />
          既存フォルダを文字起こし
        </button>
      </section>

      {error && <section className={state === "error" ? "error" : "warning"}>{error}</section>}

      <section className="grid">
        <div className="panel">
          <h2>保存ファイル</h2>
          <div className="source">
            <Mic size={18} />
            <div>
              <span>mic.wav</span>
              <strong>{micDevice || "未選択"}</strong>
            </div>
          </div>
          <div className="source">
            <Volume2 size={18} />
            <div>
              <span>system.wav</span>
              <strong>{systemDevice || "未選択"}</strong>
            </div>
          </div>
          <div className="pathBox">{outputDir || "録音開始後に保存フォルダが表示されます。"}</div>
          <div className="actions">
            <button type="button" onClick={openFolder} disabled={!outputDir} title="保存フォルダを開く">
              <FolderOpen size={18} />
              保存フォルダを開く
            </button>
          </div>
        </div>

        <div className="panel">
          <h2>デバイス</h2>
          <div className="deviceList">
            {devices.length === 0 ? (
              <p>デバイスボタンで利用可能な音声デバイスを再読み込みしてください。</p>
            ) : (
              devices.map((device) => (
                <div className={`deviceRow ${device.kind}`} key={device.index}>
                  <span>{deviceKindLabel(device.kind)}</span>
                  <strong>{deviceLabel(device)}</strong>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="events">
        <h2>進行状況</h2>
        <ol>
          {events.map((event, index) => (
            <li key={`${event.event}-${index}`}>
              <span>{eventLabel(event.event)}</span>
              <p>{eventMessage(event)}</p>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
