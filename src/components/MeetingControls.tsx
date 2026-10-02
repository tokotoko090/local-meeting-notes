import { Cpu, FolderOpen, Mic, Volume2 } from "lucide-react";
import { LevelMeter } from "./LevelMeter";
import type { MeetingApp } from "../useMeetingApp";

export function ModelPicker({ app, id = "model" }: { app: MeetingApp; id?: string }) {
  const option = app.capabilities?.models.find(item => item.id === app.model);
  const description = option?.label.replace(new RegExp(`^${app.model}\\s*[—–-]?\\s*`), "");
  return <div className="model-block">
    <div className="field-heading"><label htmlFor={id}>文字起こしモデル</label>{app.capabilities?.platform === "darwin" && <span className="chip"><Cpu size={12} />Apple Siliconで処理</span>}</div>
    <select id={id} value={app.model} onChange={event => app.setModel(event.target.value)} disabled={app.busy || !app.capabilities} aria-describedby={`${id}-hint`}>
      {!app.capabilities && <option value="">読み込み中…</option>}
      {app.capabilities?.models.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}
    </select>
    <p className="field-hint" id={`${id}-hint`}>{description || "モデルを選択してください。"}<span>初回はモデルのダウンロードが必要です。取得後はオフラインで使えます。</span></p>

  </div>;
}

export function AudioSources({ app }: { app: MeetingApp }) {
  const metering = app.capabilities?.platform === "win32" && app.capabilities.audio_monitor;
  return <><div className="source-grid">
    <div className="source-card"><div className="source-title"><Mic size={18} /><label htmlFor="mic-device">マイク</label><span className="source-tag">自分の声</span></div><select id="mic-device" title={app.micDevices.find(device => device.index === app.selectedMicDeviceIndex)?.name || "自動"} value={app.selectedMicDeviceIndex} onChange={event => app.setSelectedMicDeviceIndex(event.target.value === "" ? "" : Number(event.target.value))} disabled={app.busy}><option value="">自動</option>{app.micDevices.map(device => <option key={device.index} value={device.index}>{device.name}</option>)}</select><span className="source-file">mic.wav</span>{metering && <LevelMeter label="マイク" level={app.audioLevels.mic} />}</div>
    <div className="source-card"><div className="source-title"><Volume2 size={18} /><label htmlFor="system-device">{app.capabilities?.platform === "darwin" ? "Macの再生音" : "PCの再生音"}</label><span className="source-tag">相手の声</span></div><select id="system-device" title={app.systemDevices.find(device => device.index === app.selectedSystemDeviceIndex)?.name || "自動"} value={app.selectedSystemDeviceIndex} onChange={event => app.setSelectedSystemDeviceIndex(event.target.value === "" ? "" : Number(event.target.value))} disabled={app.busy}><option value="">自動</option>{app.systemDevices.map(device => <option key={device.index} value={device.index}>{device.name}</option>)}</select><span className="source-file">system.wav</span>{metering && <LevelMeter label="PC音声" level={app.audioLevels.system} />}</div>
  </div>{metering && <div className="monitor-actions"><button onClick={app.toggleAudioMonitor} disabled={app.busy || app.monitorBusy || !app.devicesLoaded || !app.micDevices.length}>{app.monitoring ? "入力テストを停止" : "入力テスト"}</button></div>}</>;
}

export function OutputLocation({ app, compact = false }: { app: MeetingApp; compact?: boolean }) {
  return <div className={`output-location ${compact ? "compact" : ""}`}><FolderOpen size={18} /><div><span className="eyebrow">録音の保存先</span><p title={app.outputRootDir || app.defaultOutputRootDir}>{app.outputRootDir || app.defaultOutputRootDir || "保存先を読み込み中…"}</p></div><button className="text-button" onClick={app.pickRecordingOutputRoot} disabled={app.busy}>変更</button></div>;
}
