from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import site
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
SERVER_VERSION = "0.1.5"
EVENTS: "queue.Queue[dict[str, Any]]" = queue.Queue()
EVENT_HISTORY: list[dict[str, Any]] = []
EVENT_LOCK = threading.Lock()
NEXT_EVENT_ID = 0
RECORDER: subprocess.Popen[str] | None = None
TRANSCRIBER: subprocess.Popen[str] | None = None
LATEST_OUTPUT_DIR: str | None = None
LOG_PATH = ROOT / "server.log"


class UserFacingValueError(ValueError):
    pass


def log(message: str) -> None:
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def backend_args(*args: str) -> list[str]:
    return [PYTHON, str(ROOT / "backend" / "meeting_notes.py"), *args]


def backend_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    cuda_paths = []
    for site_path in site.getsitepackages():
        nvidia_root = Path(site_path) / "nvidia"
        for relative in ("cublas/bin", "cudnn/bin", "cuda_nvrtc/bin"):
            candidate = nvidia_root / relative
            if candidate.exists():
                cuda_paths.append(str(candidate))
    if cuda_paths:
        env["PATH"] = os.pathsep.join([*cuda_paths, env.get("PATH", "")])
    return env


def emit(payload: dict[str, Any]) -> None:
    global LATEST_OUTPUT_DIR, NEXT_EVENT_ID
    if payload.get("output_dir"):
        LATEST_OUTPUT_DIR = str(payload["output_dir"])
    with EVENT_LOCK:
        NEXT_EVENT_ID += 1
        event = {"id": NEXT_EVENT_ID, **payload}
        EVENT_HISTORY.append(event)
        del EVENT_HISTORY[:-200]
    EVENTS.put(event)


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def run_device_list() -> dict[str, Any]:
    result = subprocess.run(
        backend_args("list-devices", "--json"),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        env=backend_env(),
    )
    payload: dict[str, Any] = {"devices": []}
    if result.returncode == 0 and result.stdout.strip():
        payload = json.loads(result.stdout)
    return {
        "ok": result.returncode == 0,
        "output": result.stdout.strip(),
        "devices": payload.get("devices", []),
        "error": result.stderr.strip(),
    }


def stream_process_output(process: subprocess.Popen[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        try:
            emit(json.loads(line))
        except json.JSONDecodeError:
            emit({"event": "log", "message": line.strip()})
    code = process.wait()
    emit({"event": "process_closed" if code == 0 else "error", "code": code, "output_dir": LATEST_OUTPUT_DIR})


def stream_process_error(process: subprocess.Popen[str]) -> None:
    assert process.stderr is not None
    for line in process.stderr:
        emit({"event": "log", "message": line.strip()})


def start_backend_process(args: list[str]) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        backend_args(*args),
        cwd=ROOT,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=backend_env(),
    )
    threading.Thread(target=stream_process_output, args=(process,), daemon=True).start()
    threading.Thread(target=stream_process_error, args=(process,), daemon=True).start()
    return process


def any_process_running() -> bool:
    return bool((RECORDER and RECORDER.poll() is None) or (TRANSCRIBER and TRANSCRIBER.poll() is None))


def start_recording(
    model: str,
    transcribe_device: str,
    mic_device_index: int | None = None,
    system_device_index: int | None = None,
) -> dict[str, Any]:
    global RECORDER
    if any_process_running():
        return {"ok": False, "error": "Another recording or transcription process is already running."}

    args = ["record", "--model", model, "--transcribe-device", transcribe_device]
    if mic_device_index is not None:
        args.extend(["--mic-device-index", str(mic_device_index)])
    if system_device_index is not None:
        args.extend(["--system-device-index", str(system_device_index)])

    RECORDER = start_backend_process(args)
    return {"ok": True}


def stop_recording() -> dict[str, Any]:
    if not RECORDER or RECORDER.poll() is not None or RECORDER.stdin is None:
        return {"ok": False, "error": "Recording is not running."}
    RECORDER.stdin.write("stop\n")
    RECORDER.stdin.flush()
    return {"ok": True}


def resolve_output_dir(output_dir: str) -> Path:
    if not output_dir.strip():
        raise UserFacingValueError("Output folder is required.")
    path = Path(output_dir)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.exists() or not path.is_dir():
        raise UserFacingValueError(f"Output folder does not exist: {path}")
    if not (path / "mic.wav").exists() and not (path / "system.wav").exists():
        raise UserFacingValueError("The selected output folder must contain mic.wav or system.wav.")
    return path


def start_transcription(output_dir: str, model: str, transcribe_device: str) -> dict[str, Any]:
    global TRANSCRIBER, LATEST_OUTPUT_DIR
    if any_process_running():
        return {"ok": False, "error": "Another recording or transcription process is already running."}
    try:
        path = resolve_output_dir(output_dir)
    except UserFacingValueError as exc:
        return {"ok": False, "error": str(exc)}

    LATEST_OUTPUT_DIR = str(path)
    emit({"event": "transcription_queued", "output_dir": str(path), "model": model, "transcribe_device": transcribe_device})
    TRANSCRIBER = start_backend_process(["generate", str(path), "--transcribe", "--model", model, "--transcribe-device", transcribe_device])
    return {"ok": True, "output_dir": str(path)}


def copy_prompt(output_dir: str | None = None) -> dict[str, Any]:
    target_dir = output_dir or LATEST_OUTPUT_DIR
    if not target_dir:
        return {"ok": False, "error": "No output folder is available yet."}
    prompt_path = Path(target_dir) / "chatgpt_prompt.md"
    if not prompt_path.exists():
        return {"ok": False, "error": "chatgpt_prompt.md has not been generated yet."}
    text = prompt_path.read_text(encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"], input=text, text=True, check=False)
    return {"ok": True}


def open_output(output_dir: str | None = None) -> dict[str, Any]:
    target_dir = output_dir or LATEST_OUTPUT_DIR
    if not target_dir:
        return {"ok": False, "error": "No output folder is available yet."}
    subprocess.Popen(["explorer", target_dir])
    return {"ok": True}


def pick_output_dir() -> dict[str, Any]:
    env = os.environ.copy()
    output_root = ROOT / "output"
    env["LOCAL_MEETING_NOTES_OUTPUT_ROOT"] = str(output_root.resolve() if output_root.exists() else ROOT.resolve())
    script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Select an existing Local Meeting Notes output folder'
$dialog.ShowNewFolderButton = $false
if (Test-Path -LiteralPath $env:LOCAL_MEETING_NOTES_OUTPUT_ROOT) {
  $dialog.SelectedPath = (Resolve-Path -LiteralPath $env:LOCAL_MEETING_NOTES_OUTPUT_ROOT).Path
}
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  Write-Output $dialog.SelectedPath
  exit 0
}
exit 3
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-Command", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return {"ok": True, "output_dir": result.stdout.strip().splitlines()[-1]}
    if result.returncode == 3:
        return {"ok": False, "canceled": True}
    return {"ok": False, "error": result.stderr.strip() or "Could not open the folder picker."}


class Handler(BaseHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "server_version": SERVER_VERSION})
            return
        if parsed.path == "/api/devices":
            self.send_json(run_device_list())
            return
        if parsed.path == "/api/events":
            query = parse_qs(parsed.query)
            since = int(query.get("since", ["0"])[0] or "0")
            with EVENT_LOCK:
                events = [event for event in EVENT_HISTORY if int(event.get("id", 0)) > since]
            self.send_json({"ok": True, "events": events})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        body = read_json_body(self)
        if self.path == "/api/recording/start":
            mic_index = body.get("micDeviceIndex")
            system_index = body.get("systemDeviceIndex")
            self.send_json(
                start_recording(
                    str(body.get("model") or "small"),
                    str(body.get("transcribeDevice") or "cpu"),
                    int(mic_index) if mic_index not in (None, "") else None,
                    int(system_index) if system_index not in (None, "") else None,
                )
            )
            return
        if self.path == "/api/recording/stop":
            self.send_json(stop_recording())
            return
        if self.path == "/api/transcribe-existing":
            self.send_json(
                start_transcription(
                    str(body.get("outputDir") or ""),
                    str(body.get("model") or "small"),
                    str(body.get("transcribeDevice") or "cpu"),
                )
            )
            return
        if self.path == "/api/prompt/copy":
            self.send_json(copy_prompt(str(body.get("outputDir") or "") or None))
            return
        if self.path == "/api/output/open":
            self.send_json(open_output(str(body.get("outputDir") or "") or None))
            return
        if self.path == "/api/output/pick-directory":
            self.send_json(pick_output_dir())
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def main() -> int:
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
        log("Local Meeting Notes API: http://127.0.0.1:8765")
        print("Local Meeting Notes API: http://127.0.0.1:8765", flush=True)
        server.serve_forever()
    except Exception as exc:  # noqa: BLE001
        log(f"server failed: {exc}")
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
