import { useEffect, useRef, useState } from "react";
import { Download, RefreshCcw, Upload, X } from "lucide-react";
import type { MeetingApp } from "../useMeetingApp";
import { useUnsavedPrompt } from "./useUnsavedPrompt";
import { OutputLocation } from "./MeetingControls";

function permissionLabel(value?: string) {
  if (value === "granted" || value === "authorized") return "許可済み";
  if (value === "denied") return "許可が必要です（システム設定）";
  if (value === "restricted") return "アクセスが制限されています";
  return "録音開始時に確認";
}

export function SettingsDialog({ app, onClose }: { app: MeetingApp; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [template, setTemplate] = useState(app.promptTemplate);
  const [savedTemplate, setSavedTemplate] = useState(app.promptTemplate);
  const [saving, setSaving] = useState(false);
  const [templateError, setTemplateError] = useState("");
  const [templateStatus, setTemplateStatus] = useState("");
  const [confirmClose, setConfirmClose] = useState(false);
  const savingRef = useRef(false);
  const initialized = useRef(app.settingsLoaded);
  const mounted = useRef(false);
  const dirty = template !== savedTemplate;
  useUnsavedPrompt(dirty, saving);
  useEffect(() => {
    if (!initialized.current && app.settingsLoaded) {
      setTemplate(app.promptTemplate); setSavedTemplate(app.promptTemplate); initialized.current = true;
    }
  }, [app.settingsLoaded, app.promptTemplate]);
  function requestClose() {
    if (savingRef.current) return;
    if (dirty) setConfirmClose(true); else onClose();
  }
  async function saveTemplate() {
    if (savingRef.current || app.busy || !app.settingsLoaded || !template.trim()) return;
    savingRef.current = true; setSaving(true); setTemplateError(""); setTemplateStatus("");
    const submitted = template;
    const result = await app.savePromptTemplate(submitted);
    if (!mounted.current) return;
    savingRef.current = false; setSaving(false);
    if (result.ok) { setSavedTemplate(result.prompt_template ?? submitted); setTemplate(result.prompt_template ?? submitted); setTemplateStatus("保存しました。次に開始する録音・文字起こしに適用されます。"); }
    else setTemplateError(result.error || "保存できませんでした。編集内容は保持されています。");
  }
  useEffect(() => {
    mounted.current = true;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    return () => { mounted.current = false; dialog?.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} className="settings-dialog" aria-labelledby="settings-title" onKeyDownCapture={event => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); requestClose(); } }} onCancel={event => { event.preventDefault(); requestClose(); }} onClick={event => { if (event.target === event.currentTarget) { const bounds = event.currentTarget.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) requestClose(); } }}>
    <div className="dialog-header"><div><h2 id="settings-title">設定</h2></div><button className="icon-button" aria-label="設定を閉じる" onClick={requestClose} disabled={saving} autoFocus><X size={20} /></button></div>
    <div className="dialog-body">
      {confirmClose && <div className="discard-confirmation" role="alert"><p>保存していないプロンプト設定の変更を破棄しますか？</p><div className="button-row"><button onClick={() => { setConfirmClose(false); ref.current?.querySelector<HTMLTextAreaElement>("textarea")?.focus(); }} autoFocus>編集に戻る</button><button onClick={onClose}>変更を破棄して閉じる</button></div></div>}
      <section className="settings-section prompt-settings"><h3>プロンプト設定</h3><p className="field-hint">議事録の作成指示を編集します。文字起こし全文は自動で末尾に追加されます。次に開始する録音・文字起こしに適用され、作成済みファイルは変更しません。</p><label className="field-label" htmlFor="prompt-template">議事録の作成指示</label><textarea id="prompt-template" value={template} onChange={event => { setTemplate(event.target.value); setTemplateStatus(""); }} disabled={app.busy || saving || !app.settingsLoaded} spellCheck={false} />
      <div className="button-row"><button onClick={() => { setTemplate(app.defaultPromptTemplate); setTemplateStatus("標準の内容に戻しました。保存すると適用されます。"); setTemplateError(""); }} disabled={app.busy || saving || !app.settingsLoaded}>標準に戻す</button><button className="primary" onClick={() => void saveTemplate()} disabled={app.busy || saving || !app.settingsLoaded || !template.trim()}>プロンプト設定を保存</button></div>{templateError && <p className="error-message" role="alert">{templateError}</p>}{templateStatus && <p className="save-feedback" role="status">{templateStatus}</p>}{app.busy && <p className="field-hint">録音・文字起こし中は変更できません。</p>}</section>
      <section className="settings-section"><div className="section-heading"><h3>音声デバイス</h3><button className="text-button" onClick={app.refreshDevices} disabled={app.busy}><RefreshCcw size={14} />再読み込み</button></div><div className="device-list">{app.devices.length ? app.devices.map(device => <div className="device-item" key={`${device.kind}-${device.index}`}><span className="device-kind">{device.kind === "mic" ? "マイク" : device.kind === "system" ? "再生音" : "その他"}</span><div><strong>{device.name}</strong><small>{device.channels}ch · {device.sample_rate.toLocaleString()} Hz</small></div></div>) : <p className="muted">{app.devicesLoaded ? "音声デバイスが見つかりません。接続とアクセス許可を確認し、再読み込みしてください。" : "音声デバイスを読み込んでいます。"}</p>}</div></section>
      {app.capabilities?.platform === "darwin" && <section className="settings-section"><div className="section-heading"><h3>macOSのアクセス許可</h3><button className="text-button" onClick={app.refreshCapabilities} disabled={app.busy}><RefreshCcw size={14} />再確認</button></div><div className="permission-row"><span>マイク</span><strong>{permissionLabel(app.capabilities.permissions?.microphone)}</strong></div><div className="permission-row"><span>システム音声</span><strong>{permissionLabel(app.capabilities.permissions?.system_audio)}</strong></div><p className="field-hint">共有画面が表示されたらディスプレイを選択してください。映像は保存されません。</p>{app.capabilities.permissions?.error && <p className="inline-notice">{app.capabilities.permissions.error}</p>}</section>}
      <section className="settings-section"><h3>保存先</h3><OutputLocation app={app} compact /></section>
      {app.capabilities && app.capabilities.platform !== "darwin" && <section className="settings-section"><div className="field windows-device"><label htmlFor="transcribe-device">処理デバイス</label><select id="transcribe-device" value={app.transcribeDevice} onChange={event => app.setTranscribeDevice(event.target.value)} disabled={app.busy}>{app.capabilities.transcribe_devices.map(device => <option key={device}>{device}</option>)}</select></div></section>}
      {app.capabilities?.cuda_setup && <section className="settings-section"><h3>GPU（CUDA）</h3><p>{app.gpuStatus?.label || "確認中"}</p><p className="field-hint">{app.gpuStatus?.error || app.gpuStatus?.message}</p><div className="button-row"><button onClick={app.refreshGpuStatus} disabled={app.busy || app.gpuBusy}><RefreshCcw size={16} />診断</button><button onClick={app.setupGpuRuntime} disabled={app.busy || app.gpuBusy || !["setup_available", "setup_failed"].includes(app.gpuStatus?.state || "")}><Download size={16} />セットアップ</button></div></section>}
      {app.capabilities?.updates && <section className="settings-section"><h3>アップデート</h3><p className="field-hint">{app.updateStatus || "新しいバージョンがあるか確認できます。"}</p>{app.updateInfo?.release_url && <a href={app.updateInfo.release_url} target="_blank" rel="noreferrer">リリース情報</a>}<div className="button-row"><button onClick={app.checkForUpdates} disabled={app.busy || app.updateBusy}><RefreshCcw size={16} />確認</button><button onClick={app.downloadUpdate} disabled={app.busy || app.updateBusy || !app.updateInfo?.update_available}><Download size={16} />ダウンロード</button><button onClick={app.installUpdate} disabled={app.busy || app.updateBusy || !app.downloadedInstaller}><Upload size={16} />インストール</button></div></section>}
      {app.notice && <p className="inline-notice" role="status">{app.notice}</p>}
      <p className="settings-footnote">音声と文字起こしは、このコンピュータ内で処理・保存されます。</p>
    </div>
  </dialog>;
}
