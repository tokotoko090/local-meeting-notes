# Windows v0.3.0 correction validation — 2026-09-21

This is a Windows correction candidate, not approval to publish v0.3.0. The old tag and draft still belong to `3eac0985e40c40ffd7ad1fa392235794d43dc907`. The new Windows artifact's exact source commit and SHA-256 belong in its adjacent `windows-manifest.json`.

## Reproduction and correction

The installed draft, matching installer SHA-256 `7a0de09b333b7bd121691b23f8b961879788e0d979c287b070bfa1bb86608365`, recorded WAV files but failed transcription with `Cannot find file at '..\\lib\ffmpeg\tools\ffmpeg\bin\ffmpeg.exe'` below `_MEI...`. The build had copied a Chocolatey shim. The corrected installer deploys a checksum-verified standalone ffmpeg beside the application; the same captured WAVs completed CPU transcription after reinstalling.

## Completed on Windows 11

- Python: 63 tests run, 61 passed, 2 environment-specific skips (native Mac helper unavailable; Windows symlink privilege unavailable). Compilation and `git diff --check` passed.
- Vite/TypeScript build, PyInstaller EXE and NSIS installer build passed.
- Chromium UI regression: 93/93. Prompt editor regression: 13/13. The prompt test now holds and explicitly releases the save request instead of racing a short wall-clock delay.
- Installer-based v0.2.9 → correction overwrite, with identical hashes for legacy settings and saved test audio. No uninstall used.
- Corrected EXE launched from an installation directory containing Japanese characters and spaces, using a separate data directory. Default installed application path was also updated and launched with isolated test data.
- Real Razer Seiren V3 Mini microphone plus INZONE H9/H7 WASAPI loopback recorded approximately 33 seconds. Stop, WAV finalization, CPU/base transcription, transcript Markdown and prompt Markdown completed. Mic/system outputs contained 1/3 segments. Test speech was generated locally; no audio was uploaded.
- Packaged CUDA/base transcription of copies of those WAVs completed on RTX 3080. Both transcript JSON files recorded `runtime_device: cuda`, `compute_type: float16`; no CPU fallback occurred.
- Common template changed in the UI and applied to subsequent recording. Individual prompt edited, saved and copied; actual Windows clipboard readback exactly matched Japanese, emoji and trailing newline.
- Saving and exiting, process restart and UI reload retained template, individual prompt, selected model (`small`) and processing device (`auto`). Existing recordings were not overwritten by these tests.
- All 289 original installed user's settings and recording files were byte-identical before and after normal-path installation (SHA-256 comparison). Local preservation evidence is kept outside Git under `.validation/`.
- Existing tests preventing stale updater installers after failed downloads still pass.

## Remaining cross-platform checks

Mac cannot be validated on this Windows host. Rebuild the Mac artifact from the same correction commit and repeat MLX/GPU/FP16 recording/transcription, settings persistence, prompt edit/save/copy and restart. Shared changes affect settings serialization/initialization and clipboard subprocess input; Windows ffmpeg and WASAPI changes do not switch Mac to CPU. The default remains `large-v3-turbo` and MLX only.

No master merge, tag movement, draft asset replacement or official release publication was performed. Audio, transcripts, personal settings, model caches and build products remain outside Git.
