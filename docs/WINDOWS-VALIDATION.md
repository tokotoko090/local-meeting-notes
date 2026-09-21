# Windows v0.3.0 correction validation — 2026-09-21

This is a Windows correction candidate, not approval to publish v0.3.0. The old tag and draft still belong to `3eac0985e40c40ffd7ad1fa392235794d43dc907`. The new Windows artifact's exact source commit and SHA-256 belong in its adjacent `windows-manifest.json`.

## Reproduction and correction

The installed draft, matching installer SHA-256 `7a0de09b333b7bd121691b23f8b961879788e0d979c287b070bfa1bb86608365`, recorded WAV files but failed transcription with `Cannot find file at '..\\lib\ffmpeg\tools\ffmpeg\bin\ffmpeg.exe'` below `_MEI...`. The build had copied a Chocolatey shim. The corrected installer deploys a checksum-verified standalone ffmpeg beside the application; the same captured WAVs completed CPU transcription after reinstalling.

## Current Windows meters / turbo candidate

- Python: 81 tests run, 79 passed, 2 environment-specific skips. Vite/TypeScript, Python compilation, PyInstaller and NSIS builds passed. Chromium UI: 94/94; prompt regression: 13/13. The two initial UI failures exposed progress moving backwards on model status; fixed and the complete suite rerun successfully.
- Installed `LocalMeetingNotesSetup-0.3.0.exe` SHA-256: `abeff2aa936926bdebacc9f87b8f4b2810335e65c93c1575cf061c3a864a5fcf`. The adjacent manifest records the final source commit. This is a separate correction candidate; the old tag/draft remain unchanged.
- A fresh isolated data directory exposed `large-v3-turbo` / `auto`. Both real Razer mic and INZONE loopback meters updated during input testing, and no output directory/audio files were created. Starting recording stopped the monitor workers and used recording PCM for both meters.
- Approximately 41 seconds of actual mic/loopback recording stopped and saved successfully. Packaged turbo used RTX 3080 CUDA/FP16 for both streams with no fallback. The mic contained ambient sound and no recognized speech; the loopback produced two speech segments. Both JSON outputs, transcript Markdown and prompt Markdown were created. Original error did not recur from the Japanese/space-containing installation and data paths.
- Packaged turbo CPU/INT8 transcribed both copies of a dedicated 40.9-second synthetic Japanese reference. Both streams contained recognized speech. `HF_HUB_OFFLINE=1` was set for packaged GPU and CPU checks: cached weights worked without network acquisition. One model-load status per two-track job confirmed session reuse. Initial model acquisition succeeded separately before these checks; download failure/status behavior is covered by unit tests.
- Performance/accuracy comparison was explicitly removed from scope by the user. No CPU/GPU benchmark comparison or Mac-equivalence claim is made.
- Switching tabs and browser reload stopped input testing. An invalid microphone index caused both workers to stop and returned an actionable error; restarting/stopping cleared it. Stale/silent/clipping behavior and Mac exclusion passed automated tests.
- Individual prompt save/copy matched the actual Windows clipboard exactly, including Japanese, emoji and trailing newline. The common template was changed in the UI and applied to a subsequent dedicated transcription. Restarting the normally installed EXE retained `small` / `cpu`, the common template, and the individual edited prompt.
- v0.2.9 was installed into the dedicated upgrade directory and overwritten directly with this candidate. All 12 legacy settings/recording files remained byte-identical. Normal-path installation also preserved all 289 existing user settings/recording files; no test audio was put into the user's recording directory.
- Previous CI failure was a test comparison of Windows short (`RUNNER~1`) and resolved long paths. Expected ffmpeg paths now use `resolve()` as the implementation does.

## Previous ffmpeg correction baseline

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

Mac cannot be validated on this Windows host. Rebuild the Mac artifact from the same final correction commit and repeat MLX/GPU/FP16 recording/transcription, settings persistence, prompt edit/save/copy and restart. Shared changes affect capability/default initialization, recording/transcription lifecycle, model status display, settings serialization and clipboard subprocess input. Confirm no meter or monitor API calls on Mac. Windows session/model acquisition is separate from MLX and does not switch Mac to CPU. The Mac default remains `large-v3-turbo` and MLX only.

No master merge, tag movement, draft asset replacement or official release publication was performed. Audio, transcripts, personal settings, model caches and build products remain outside Git.
