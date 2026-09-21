# Repository handoff

## Windows and encoding

- Use PowerShell 7, `npm.cmd` / `npx.cmd`, literal file paths and explicit UTF-8. Console mojibake is not evidence of corrupted files. Before edits inspect `git status --short`, exact targets with `rg -n`, then verify scoped diffs. Preserve unrelated changes and Japanese copy.
- Packaged GUI executables must be launched with `Start-Process -Wait -PassThru` when waiting for completion; direct PowerShell `&` can return early. Use `-WindowStyle Hidden` for background helpers.
- Never commit recordings, transcripts, user settings, models, `.validation/`, or build outputs. Use dedicated recording/data folders for real-device tests. Preserve existing files during installer verification.
- Update this file with reusable findings before completing work.

## Windows v0.3.0 correction

- Draft `3eac0985e40c40ffd7ad1fa392235794d43dc907` reproduced the reported `_MEI.../lib/ffmpeg/tools/ffmpeg/bin/ffmpeg.exe` failure: CI copied a Chocolatey shim instead of ffmpeg. `scripts/prepare_windows_ffmpeg.py` now verifies the published ZIP checksum, extracts the real executable and validates a relocated EXE with an actual WAV conversion before atomic replacement. NSIS installs sibling `vendor/ffmpeg.exe`; the spec excludes the vendor directory.
- Frozen `resolve_ffmpeg()` accepts a managed `components/ffmpeg/current.json` path contained within that component directory, then installed sibling vendor. It never selects PATH or `_MEIPASS` shims. Development may use PATH. Do not restore the old `Get-Command ffmpeg.exe` copy.
- Silent WASAPI reads need a stop waiter that calls `stream.stop_stream()`; otherwise recording stop can time out without finalizing WAV. The waiter finishes before resource close. Keep Mac recording separate.
- Windows clipboard stdin must explicitly decode UTF-8 and use `ReadToEnd`, with binary subprocess input to retain exact newlines. The old PowerShell `$input` pipeline corrupted Japanese. Real clipboard readback verified Japanese, emoji and trailing LF.
- Settings now expose and validate persisted model/device choices; capability defaults load before saved settings. Mac stays MLX-only with `large-v3-turbo` default. CPU fallback remains Windows-only.
- Read `docs/RELEASING.md` and `scripts/release*.py`. Never move existing v0.3.0 tag, publish the current draft, or mix this Windows build with old Mac artifacts. Both OS distributions must come from one verified SHA before publication.

## Verification on this host

- Python: `python -m unittest discover -s tests -v`; symlink escape test skips only Windows privilege error 1314, and native Mac helper tests require a Mac. No Windows security settings need changing.
- UI: fixture server on 8877 plus sequential Electron `scripts/verify-ui.cjs` / `scripts/verify-prompt-ui.cjs`; reports and screenshots live in ignored `build/`. A restricted shell produced Electron GPU exit `-1073741515`; normal desktop execution resolved it. Restricted System.Speech also reported no voices; normal desktop execution generated the test WAV.
- The root workspace was dirty on `master` at task start. The correction checkout is `.worktrees/windows-fix`, branch `codex/macos-support`; do not copy the old root source over this branch. Its pending work remains separate.
- v0.2.9 listens on 8765 even when `LOCAL_MEETING_NOTES_PORT` is set. Isolate its data with `LOCALAPPDATA`; new versions support `LOCAL_MEETING_NOTES_DATA_ROOT` and an alternate port.
- Windows packaged validation passed CPU/int8 and RTX 3080 CUDA/float16, real mic/loopback capture, stop, prompt save/copy and restart. See `docs/WINDOWS-VALIDATION.md`. UI regression counts are 94 + 13. The prompt saving-state test uses an explicit request gate because an 800 ms delay races hidden Electron frame acknowledgments on Windows.
- Windows CI temp paths may use `RUNNER~1` while `Path.resolve()` returns `runneradmin`. Compare resolved paths in ffmpeg tests; string comparisons against unresolved temp paths caused a false CI failure.

## Windows meters and turbo

- `backend/windows_transcription.py` owns Windows defaults (`large-v3-turbo` / `auto`), cache-first acquisition and per-job model reuse. Keep faster-whisper >= 1.2.1. A session is shared by mic/system and released after the job; download failures are not CUDA failures and must not trigger repeated downloads or a success event. Existing settings take priority over new defaults. Mac remains MLX-only.
- `record_device` measures the same int16 PCM written to WAV at about 10 Hz. Input test workers use `record-one --monitor-only --source mic|system` and create no audio files. Device enumeration/open must stay in the killable worker, not the HTTP server's process lock: audio drivers can hang. Stop sends stdin, then kills/reaps on timeout. A failed worker stops its sibling and exposes `audio-levels.error`.
- `audio_level` events update only latest server values, bypassing event history/logs. UI polling is 120 ms, stale cutoff 1.5 s, peak hold 350 ms, decay 4 dB/tick. Windows capability gates both display and API calls. Device/view changes, record/transcribe start, app exit, unmount and pagehide stop input testing; recording measurements continue from recording workers.
- Do not let generic model status events move the progress stage backwards from mic/system. Keep download/load detail visible independently. Shutdown must cancel a pending record/transcribe request waiting for monitor stop.
- Real-device turbo validation uses ignored `.validation/` and `HF_HUB_OFFLINE=1` after acquisition. GPU/CPU performance and accuracy comparisons were explicitly removed from scope; do not claim Mac-equivalent performance. Model weights and personal audio must never enter Git or Actions artifacts.
