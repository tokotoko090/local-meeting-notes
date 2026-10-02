import type { AudioLevel } from "../vite-env";

export function LevelMeter({ label, level }: { label: string; level: AudioLevel }) {
  const percent = (db: number) => Math.max(0, Math.min(100, (db + 60) / 60 * 100));
  return <div className={`level-meter ${level.clipping ? "is-clipping" : ""}`}>
    <div className="level-caption"><span>{label}</span><span>{level.clipping ? "クリッピング" : level.active ? `${Math.round(level.rms_dbfs)} dBFS` : "−∞ dBFS"}</span></div>
    <div className="level-track" role="meter" aria-label={`${label}の音量`} aria-valuemin={-60} aria-valuemax={0} aria-valuenow={level.active ? Math.max(-60, Math.min(0, level.rms_dbfs)) : -60}>
      <span className="level-fill" style={{ width: `${level.active ? percent(level.rms_dbfs) : 0}%` }} />
      {level.active && <span className="level-peak" style={{ left: `${percent(level.peak_dbfs)}%` }} />}
    </div>
  </div>;
}
