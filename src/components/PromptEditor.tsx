import { useEffect, useRef, useState } from "react";
import { Copy, Save, X } from "lucide-react";
import { useUnsavedPrompt } from "./useUnsavedPrompt";
import type { MeetingApp } from "../useMeetingApp";

export function PromptEditor({ app, outputDir, onClose }: { app: MeetingApp; outputDir: string; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [text, setText] = useState("");
  const [savedText, setSavedText] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [confirmClose, setConfirmClose] = useState(false);
  const dirty = text !== savedText;
  useUnsavedPrompt(dirty, saving);
  const savingRef = useRef(false);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    dialog?.showModal();
    let canceled = false;
    void app.readPrompt(outputDir).then(result => {
      if (canceled) return;
      if (result.ok && typeof result.text === "string") { setText(result.text); setSavedText(result.text); setLoaded(true); }
      else setError(result.error || "プロンプトを読み込めませんでした。");
      setLoading(false);
    });
    return () => { mounted.current = false; canceled = true; dialog?.close(); previous?.focus(); };
  }, [outputDir]);
  function requestClose() {
    if (savingRef.current) return;
    if (dirty) setConfirmClose(true); else onClose();
  }
  async function save(copy: boolean) {
    if (savingRef.current || app.busy || !loaded) return;
    savingRef.current = true; setSaving(true); setError(""); setStatus("");
    const submitted = text;
    const result = await app.savePrompt(outputDir, submitted, copy);
    if (!mounted.current) return;
    savingRef.current = false; setSaving(false);
    if (result.saved) setSavedText(submitted);
    if (!result.ok || !result.saved) {
      setError(result.saved ? `保存は完了しましたが、コピーできませんでした。${result.error || "もう一度お試しください。"}` : result.error || "保存できませんでした。編集内容は保持されています。");
      return;
    }
    setSavedText(submitted);
    setStatus(copy ? "保存してコピーしました。" : "保存しました。");
  }
  return <dialog ref={dialogRef} className="settings-dialog prompt-dialog" aria-labelledby="prompt-editor-title" onKeyDownCapture={event => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); requestClose(); } }} onCancel={event => { event.preventDefault(); requestClose(); }} onClick={event => { if (event.target === event.currentTarget) { const bounds = event.currentTarget.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) requestClose(); } }}>
    <div className="dialog-header"><h2 id="prompt-editor-title">プロンプトを編集</h2><button className="icon-button" aria-label="プロンプト編集を閉じる" onClick={requestClose} disabled={saving} autoFocus><X size={20} /></button></div>
    <div className="prompt-editor-body"><p className="field-hint">この録音の chatgpt_prompt.md を編集します。文字起こしは再実行しません。</p><p className="prompt-path">{outputDir}</p><label className="field-label" htmlFor="prompt-text">プロンプト全文（Markdown）</label><textarea id="prompt-text" value={text} onChange={event => { setText(event.target.value); setStatus(""); }} disabled={!loaded || saving || app.busy} spellCheck={false} placeholder={loading ? "読み込み中…" : ""} />
      {error && <p className="error-message" role="alert">{error}</p>}{status && <p className="save-feedback" role="status">{status}</p>}
      {confirmClose ? <div className="discard-confirmation" role="alert"><p>保存していない変更を破棄しますか？</p><div className="button-row"><button onClick={() => { setConfirmClose(false); dialogRef.current?.querySelector<HTMLTextAreaElement>("textarea")?.focus(); }} autoFocus>編集に戻る</button><button onClick={onClose}>変更を破棄して閉じる</button></div></div> : <div className="editor-actions"><button onClick={requestClose} disabled={saving}>キャンセル</button><div><button onClick={() => void save(false)} disabled={!loaded || saving || app.busy}><Save size={15} />保存</button><button className="primary" onClick={() => void save(true)} disabled={!loaded || saving || app.busy}><Copy size={15} />保存してコピー</button></div></div>}
    </div>
  </dialog>;
}
