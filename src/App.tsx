import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowRight, ChevronDown, FileAudio, FolderOpen, LockKeyhole, Mic, Power, Settings2 } from "lucide-react";
import appIcon from "../native/macos/AppIcon-preview.png";
import { eventLabel, eventMessage, useMeetingApp } from "./useMeetingApp";
import { AudioSources, ModelPicker, OutputLocation } from "./components/MeetingControls";
import { ActiveSession, SessionResult } from "./components/SessionStatus";
import { PromptEditor } from "./components/PromptEditor";
import { SettingsDialog } from "./components/SettingsDialog";

type Tab = "record" | "existing";

export default function App() {
  const app = useMeetingApp();
  const [tab, setTab] = useState<Tab>("record");
  const [sessionTab, setSessionTab] = useState<Tab>("record");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [promptTarget, setPromptTarget] = useState<string | null>(null);
  const [existingPrompt, setExistingPrompt] = useState<{ path: string; status: "loading" | "ready" | "missing"; error?: string } | null>(null);
  useEffect(() => {
    let canceled = false;
    const path = app.existingOutputDir.trim();
    if (!path || app.busy) { setExistingPrompt(null); return; }
    setExistingPrompt({ path, status: "loading" });
    const timer = window.setTimeout(() => {
      void app.readPrompt(path).then(result => {
        if (!canceled) setExistingPrompt({ path, status: result.ok && typeof result.text === "string" ? "ready" : "missing", error: result.error });
      });
    }, 300);
    return () => { canceled = true; window.clearTimeout(timer); };
  }, [app.existingOutputDir, app.busy]);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const active = app.busy;
  function onTabKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? 1 : 1 - index;
    setTab(next === 0 ? "record" : "existing");
    tabRefs.current[next]?.focus();
  }
  function recover() { app.setExistingOutputDir(app.outputDir); setTab("existing"); }
  function nextRecording() { app.newRecording(); setTab("record"); }
  return <main className="app-shell">
    <header className="app-header"><div className="brand"><img src={appIcon} alt="" width="44" height="44" /><div><h1>Local Meeting Notes</h1></div></div><div className="header-actions"><span className={`status-badge state-${app.state}`} role="status"><span className="status-dot" />{app.statusLabel}</span><button className="icon-button" aria-label="設定" onClick={() => setSettingsOpen(true)}><Settings2 size={19} /></button><button className="quit-button" aria-label="保存して終了" onClick={app.shutdownApp} disabled={app.closing}><Power size={15} /><span>保存して終了</span></button></div></header>
    <div className="workspace">

      {app.connectionError && <div role="status" className="inline-notice connection-notice">{app.connectionError}</div>}
      <section className="workspace-card">
        <div className="tab-bar" role="tablist" aria-label="作業の選択">{([{ id: "record", label: "新しく録音", Icon: Mic }, { id: "existing", label: "保存済み音声", Icon: FileAudio }] as const).map(({ id, label, Icon }, index) => <button key={id} ref={node => { tabRefs.current[index] = node; }} id={`tab-${id}`} role="tab" aria-selected={tab === id} aria-controls={`panel-${id}`} tabIndex={tab === id ? 0 : -1} onClick={() => setTab(id)} onKeyDown={event => onTabKey(event, index)}><Icon size={16} />{label}</button>)}</div>
        <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} tabIndex={0}>
          {active ? <ActiveSession app={app} /> : app.state === "complete" && tab === sessionTab ? <SessionResult app={app} onNew={nextRecording} onEdit={() => setPromptTarget(app.outputDir)} /> : <div className="setup-content">
            <div className="setup-heading"><h3>{tab === "record" ? "録音の準備" : "保存済みの音声を文字起こし"}</h3><p>{tab === "record" ? "自分の声と相手の声を、2つの音声で残します。" : "このアプリで保存した録音フォルダを選択してください。"}</p></div>
            {tab === "record" ? <AudioSources app={app} /> : <div className="existing-picker"><div className="folder-symbol"><FolderOpen size={25} /></div><div><label htmlFor="existing-output">録音フォルダ</label><input id="existing-output" value={app.existingOutputDir} onChange={event => app.setExistingOutputDir(event.target.value)} placeholder="mic.wav・system.wav を含むフォルダ" title={app.existingOutputDir} /></div><button onClick={app.pickExistingOutputFolder}><FolderOpen size={16} />フォルダを選択</button></div>}
            {tab === "existing" && <div className="existing-prompt-actions"><button onClick={() => setPromptTarget(app.existingOutputDir.trim())} disabled={app.busy || existingPrompt?.path !== app.existingOutputDir.trim() || existingPrompt?.status !== "ready"}>保存済みプロンプトを編集</button>{existingPrompt?.status === "loading" && <span className="field-hint">プロンプトを確認中…</span>}{existingPrompt?.status === "missing" && <span className="field-hint">{existingPrompt.error || "このフォルダに編集できるプロンプトはありません。"}</span>}</div>}
            {tab === "record" && app.devicesLoaded && !app.micDevices.length && <p className="inline-notice">マイクが見つかりません。接続を確認し、設定から音声デバイスを再読み込みしてください。</p>}
            <ModelPicker app={app} />
            {tab === "record" ? <OutputLocation app={app} /> : <p className="overwrite-note">元の音声は残ります。文字起こしとプロンプトは、手動編集した内容も含めて新しい結果で上書きします。</p>}
            {app.state === "error" && <div className="error-message" role="alert"><strong>処理を完了できませんでした</strong><p>{app.error}</p>{app.canRecover && app.outputDir && <button onClick={recover} className="text-button">保存した音声でやり直す<ArrowRight size={14} /></button>}</div>}
            {tab === "record" && app.capabilities?.platform === "darwin" && <p className="capture-note">Macで再生される音全体を録音します。初回の共有画面ではディスプレイを選択してください。映像は保存しません。</p>}

            <div className="primary-area"><button className="primary main-action" onClick={() => { setSessionTab(tab); void (tab === "record" ? app.startRecording() : app.transcribeExisting()); }} disabled={!app.capabilities || !!app.connectionError || (tab === "record" && (!app.devicesLoaded || !app.micDevices.length)) || (tab === "existing" && !app.existingOutputDir.trim())}>{tab === "record" ? <Mic size={18} /> : <FileAudio size={18} />}{tab === "record" ? "録音を開始" : "文字起こしを開始"}<ArrowRight size={17} /></button><p>{tab === "record" ? "録音前に、参加者の同意を確認してください。" : "選択したモデルで文字起こしを再作成します。"}</p></div>
          </div>}
        </div>
      </section>
      {app.notice && !settingsOpen && <p className="inline-notice" role="status">{app.notice}</p>}
      <footer className="workspace-footer"><span><LockKeyhole size={12} />音声はこのコンピュータ内に保存されます</span><details className="activity-details"><summary>処理の詳細<ChevronDown size={13} /></summary><div className="activity-panel"><h3>処理ログ</h3>{app.events.length ? <ol>{app.events.map((event, index) => <li key={`${event.id ?? index}-${event.event}`}><span>{eventLabel(event.event)}</span><p>{eventMessage(event)}</p></li>)}</ol> : <p className="muted">録音や文字起こしを始めると、ここに進行状況が表示されます。</p>}</div></details></footer>
    </div>
    {promptTarget && <PromptEditor app={app} outputDir={promptTarget} onClose={() => setPromptTarget(null)} />}
    {settingsOpen && !promptTarget && <SettingsDialog app={app} onClose={() => setSettingsOpen(false)} />}
  </main>;
}
