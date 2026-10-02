# Windows v1.0.0 validation — 2026-10-02

## Automated checks

- Python: 90 tests, 88 passed, 2 environment skips (native Mac helper and Windows symlink privileges).
- Vite/TypeScript build, Python compilation and git diff --check passed.
- Real Chromium UI fixtures: 94/94 checks. Prompt editing fixtures: 13/13 checks, run sequentially on port 8877.
- Updater tests cover same version, offline check, exact release/asset matching, partial download cleanup, missing digest, wrong size/hash, tampering after download, busy recording/transcription/monitor rejection, concurrent updates and Unicode launcher paths.
- Release tests preserve the default two-platform requirement, allow explicit Windows-only bundles, and verify artifact/platform/combined manifests before publication.

## Installed Windows 11 checks

Local NSIS installer was deployed to an isolated Japanese/space-containing path. Installer test shortcuts and uninstall registry values were backed up and restored. Actual installed EXE was tested with PATH limited to System32, without external Python/Node/FFmpeg resolution.

- Fresh installation: startup, bundled static UI, CPU capability, Unicode settings/prompt save, standalone FFmpeg WAV conversion, restart and shutdown passed.
- v0.2.9 executable extracted from its actual Release installer, and v0.3.0 corrected executable, were overwritten in the isolated installation by v1.0.0. Dedicated settings and recorded-file hashes remained identical. No uninstall was used. Legacy installer itself was not run, because it terminates all LocalMeetingNotes processes regardless of installation path.
- Real Razer microphone and INZONE loopback input testing updated levels and created no WAV. Updating during monitoring was refused. Recording/stop, including loopback silence after playback ended, finalized both WAVs.
- Packaged large-v3-turbo used CUDA/FP16 for both captured tracks with verified GPU components copied into the isolated data directory. When those components were initially absent, it notified and fell back to CPU/INT8 as designed.
- Packaged CPU/INT8 transcribed both tracks of an eight-second reference with HF_HUB_OFFLINE=1 and developer PATH removed. Both outputs contained recognized speech; transcript.md and chatgpt_prompt.md were generated.
- Real Windows clipboard readback exactly matched Japanese, emoji and trailing newline. Saved model/device, common prompt and edited meeting prompt survived restart.

Audio, transcripts, settings, model caches and local logs remain in ignored validation directories and are not uploaded. Per-artifact source SHA and SHA-256 are recorded in adjacent release manifests; CI artifacts must be installed and checked before publication.

## Limits

Separate-PC, Windows Sandbox and physical Windows 10 tests were not available. The user authorized publication with this limitation explicitly included in Release notes. Local PATH isolation does not prove operation on every Windows PC. Mac was not rebuilt or tested; no Mac artifact is included in this Windows-only Release. Installer is unsigned.

NPM audit reported six advisories in the existing development tool dependency tree. Node/Electron/Vite are not part of the Windows browser-plus-Python distribution; no broad dependency upgrade was mixed into this release change.
