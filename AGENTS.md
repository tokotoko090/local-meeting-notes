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
- Windows packaged validation passed CPU/int8 and RTX 3080 CUDA/float16, real mic/loopback capture, stop, prompt save/copy and restart. See `docs/WINDOWS-VALIDATION.md`. UI regression counts are 93 + 13. The prompt saving-state test uses an explicit request gate because an 800 ms delay races hidden Electron frame acknowledgments on Windows.
