# Local Meeting Notes

Windows-only MVP for recording local meeting audio into separate microphone and PC-output WAV files, transcribing both locally, and generating Markdown that can be pasted into ChatGPT Plus.

## Assumed Environment

- Windows 10 / 11
- Node.js 20+
- Python 3.11+
- ffmpeg available in `PATH`
- A working microphone
- A Windows playback device that exposes a WASAPI loopback device
- Optional NVIDIA GPU with a current driver for CUDA transcription

This app does not use the OpenAI API and does not send audio, transcripts, or generated notes to an external server.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd install
```

## Verify Audio Devices

List available microphone and loopback devices:

```powershell
.\.venv\Scripts\python.exe backend\meeting_notes.py list-devices
```

Record a 10 second Phase 1 smoke test:

```powershell
.\.venv\Scripts\python.exe backend\meeting_notes.py record --duration 10 --skip-transcribe
```

The command creates a timestamped folder under `output/` containing:

- `mic.wav`
- `system.wav`
- `metadata.json`
- `app.log`

If `system.wav` is silent or missing, confirm that audio is playing through the selected Windows output device and that a WASAPI loopback device is listed.

## Run The App

```powershell
npm.cmd run start:browser
```

Open:

```text
http://127.0.0.1:5173
```

The browser UI uses the local Python backend for microphone and WASAPI loopback recording. It does not use browser screen sharing or `getDisplayMedia`.

The UI shows consent guidance, recording state, elapsed time, saved file status, transcription progress, output path, and buttons for copying the ChatGPT prompt or opening the output folder.

Use the `Microphone` and `PC Output` selectors to choose explicit devices. `PC Output` lists Windows WASAPI loopback devices such as speakers, headsets, HDMI/DisplayPort audio, or virtual audio outputs. If a selected PC output device records silence or fails, choose the loopback device that matches the Windows output device currently playing meeting audio.

Use `Transcribe device` to choose `cpu`, `auto`, or `cuda`. CUDA uses `faster-whisper` through CTranslate2 and the NVIDIA runtime DLL packages from `backend/requirements.txt`.

To rerun transcription for an existing recording, click `Browse`, select an existing `output\...` folder, then click `Transcribe Existing Output`. Existing transcript JSON and Markdown files in that folder are overwritten.

## Output Layout

Each recording is saved under a timestamped directory:

```text
output/
  2026-06-23_14-30-00/
    mic.wav
    system.wav
    mic_transcript.json
    system_transcript.json
    transcript.md
    chatgpt_prompt.md
    metadata.json
    app.log
```

`metadata.json` includes:

- `recording_started_at`
- `recording_stopped_at`
- `duration_seconds`
- `mic_device_name`
- `system_device_name`
- `whisper_model`
- `app_version`

## Whisper Model

The default model is `small`. You can choose another model from the UI or CLI:

```powershell
.\.venv\Scripts\python.exe backend\meeting_notes.py record --model medium
```

The first transcription run may download the selected faster-whisper model. After that, transcription runs locally.

## Common Errors

- `pyaudiowpatch is not installed`: install backend requirements in the active Python environment.
- `No WASAPI loopback device found`: make sure a Windows playback device is active, then run `list-devices`.
- `No microphone input device found`: connect or enable a microphone in Windows sound settings.
- `ffmpeg not found`: install ffmpeg and confirm `ffmpeg -version` works in PowerShell.
- Bluetooth or external audio interfaces may expose device names differently. Use `list-devices` and pass explicit `--mic-device-index` or `--system-device-index` if automatic selection picks the wrong device.

## Privacy And Consent

Only record meetings when participants have agreed to recording. Audio and transcript files stay on the local machine unless you manually share them.
