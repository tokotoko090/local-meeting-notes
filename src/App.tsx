import { Clipboard, Cpu, FolderOpen, Mic, Play, RefreshCcw, Square, Volume2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { AudioDevice, BackendEvent } from "./vite-env";

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
      setError("The recording process stopped with an error.");
    }
    if (payload.event === "error") {
      startedAt.current = null;
      setState("error");
      setError(payload.message || "Processing failed.");
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
          setError("Local API is not running. Close this window and start Local Meeting Notes again.");
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
    if (state === "recording") return "Recording";
    if (state === "processing") return "Processing";
    if (state === "complete") return "Complete";
    if (state === "error") return "Error";
    return "Ready";
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
      setError(result.error || "Could not load audio devices.");
    }
  }

  async function startRecording() {
    const options = { model, transcribeDevice, micDeviceIndex: selectedMicDeviceIndex, systemDeviceIndex: selectedSystemDeviceIndex };
    const result = window.meetingNotes ? await window.meetingNotes.startRecording(options) : await apiCall("/api/recording/start", options);
    if (!result.ok) {
      setError(result.error || "Could not start recording.");
    }
  }

  async function stopRecording() {
    setState("processing");
    const result = window.meetingNotes ? await window.meetingNotes.stopRecording() : await apiCall("/api/recording/stop", {});
    if (!result.ok) {
      setError(result.error || "Could not stop recording.");
      setState("error");
    }
  }

  async function copyPrompt() {
    const result = window.meetingNotes ? await window.meetingNotes.copyPrompt(outputDir) : await apiCall("/api/prompt/copy", { outputDir });
    if (!result.ok) {
      setError(result.error || "Could not copy the prompt.");
    }
  }

  async function openFolder() {
    const result = window.meetingNotes ? await window.meetingNotes.openOutputFolder(outputDir) : await apiCall("/api/output/open", { outputDir });
    if (!result.ok) {
      setError(result.error || "Could not open the output folder.");
    }
  }

  async function transcribeExisting() {
    const target = existingOutputDir.trim();
    setError("");
    setState("processing");
    const options = { outputDir: target, model, transcribeDevice };
    const result = window.meetingNotes?.transcribeExisting ? await window.meetingNotes.transcribeExisting(options) : await apiCall("/api/transcribe-existing", options);
    if (!result.ok) {
      setError(result.error || "Could not start transcription.");
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
      setError(result.error || "Could not open the folder picker.");
    }
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
          <p>Record microphone and PC output separately, transcribe locally, and generate a ChatGPT-ready prompt.</p>
        </div>
        <div className={`status ${state}`}>
          <span>{statusLabel}</span>
          <strong>{formatElapsed(elapsed)}</strong>
        </div>
      </section>

      <section className="notice">
        Get consent before recording. Files are saved only on this PC under the output folder.
      </section>

      <section className="controls">
        <div className="controlGroup">
          <label htmlFor="model">Whisper model</label>
          <select id="model" value={model} onChange={(event) => setModel(event.target.value)} disabled={state === "recording" || state === "processing"}>
            {modelOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="controlGroup">
          <label htmlFor="transcribe-device">Transcribe device</label>
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
          <label htmlFor="mic-device">Microphone</label>
          <select
            id="mic-device"
            value={selectedMicDeviceIndex}
            onChange={(event) => setSelectedMicDeviceIndex(event.target.value === "" ? "" : Number(event.target.value))}
            disabled={state === "recording" || state === "processing"}
          >
            <option value="">Auto</option>
            {micDevices.map((device) => (
              <option key={device.index} value={device.index}>
                {deviceLabel(device)}
              </option>
            ))}
          </select>
        </div>

        <div className="controlGroup wide">
          <label htmlFor="system-device">PC Output</label>
          <select
            id="system-device"
            value={selectedSystemDeviceIndex}
            onChange={(event) => setSelectedSystemDeviceIndex(event.target.value === "" ? "" : Number(event.target.value))}
            disabled={state === "recording" || state === "processing"}
          >
            <option value="">Auto</option>
            {systemDevices.map((device) => (
              <option key={device.index} value={device.index}>
                {deviceLabel(device)}
              </option>
            ))}
          </select>
        </div>

        <button className="secondary" type="button" onClick={refreshDevices} disabled={state === "recording" || state === "processing"} title="Refresh devices">
          <RefreshCcw size={18} />
          Devices
        </button>

        <button className="primary" type="button" onClick={startRecording} disabled={state === "recording" || state === "processing"} title="Start recording">
          <Play size={18} />
          Start Recording
        </button>

        <button className="danger" type="button" onClick={stopRecording} disabled={state !== "recording"} title="Stop recording">
          <Square size={18} />
          Stop Recording
        </button>
      </section>

      <section className="controls rerun">
        <div className="controlGroup grow">
          <label htmlFor="existing-output">Existing output folder</label>
          <div className="folderPicker">
            <input id="existing-output" value={existingOutputDir} placeholder="Select an output folder" readOnly disabled={state === "recording" || state === "processing"} />
            <button className="secondary" type="button" onClick={pickExistingOutputFolder} disabled={state === "recording" || state === "processing"} title="Choose output folder">
              <FolderOpen size={18} />
              Browse
            </button>
          </div>
        </div>
        <button
          className="secondary"
          type="button"
          onClick={transcribeExisting}
          disabled={state === "recording" || state === "processing" || !existingOutputDir.trim()}
          title="Transcribe an existing output folder"
        >
          <Cpu size={18} />
          Transcribe Existing Output
        </button>
      </section>

      {error && <section className={state === "error" ? "error" : "warning"}>{error}</section>}

      <section className="grid">
        <div className="panel">
          <h2>Saved Files</h2>
          <div className="source">
            <Mic size={18} />
            <div>
              <span>mic.wav</span>
              <strong>{micDevice || "Not selected"}</strong>
            </div>
          </div>
          <div className="source">
            <Volume2 size={18} />
            <div>
              <span>system.wav</span>
              <strong>{systemDevice || "Not selected"}</strong>
            </div>
          </div>
          <div className="pathBox">{outputDir || "Output folder appears after recording starts."}</div>
          <div className="actions">
            <button type="button" onClick={copyPrompt} disabled={!outputDir || state === "recording" || state === "processing"} title="Copy ChatGPT prompt">
              <Clipboard size={18} />
              Copy Prompt
            </button>
            <button type="button" onClick={openFolder} disabled={!outputDir} title="Open output folder">
              <FolderOpen size={18} />
              Open Output
            </button>
          </div>
        </div>

        <div className="panel">
          <h2>Devices</h2>
          <div className="deviceList">
            {devices.length === 0 ? (
              <p>Use the Devices button to refresh available audio devices.</p>
            ) : (
              devices.map((device) => (
                <div className={`deviceRow ${device.kind}`} key={device.index}>
                  <span>{device.kind}</span>
                  <strong>{deviceLabel(device)}</strong>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="events">
        <h2>Progress</h2>
        <ol>
          {events.map((event, index) => (
            <li key={`${event.event}-${index}`}>
              <span>{event.event}</span>
              <p>{eventMessage(event)}</p>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
