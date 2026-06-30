from __future__ import annotations

import json
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import webbrowser
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import site
from typing import Any
from urllib.parse import parse_qs, urlparse

IS_FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
ROOT = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parents[1]
WORK_ROOT = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LocalMeetingNotes"
    if IS_FROZEN
    else ROOT
)
PYTHON = sys.executable
SERVER_VERSION = "0.2.4"
APP_NAME = "Local Meeting Notes"
GITHUB_REPOSITORY = os.environ.get("LOCAL_MEETING_NOTES_REPOSITORY", "tokotoko090/local-meeting-notes")
RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
INSTALLER_ASSET_RE = re.compile(r"LocalMeetingNotesSetup-[0-9A-Za-z_.-]+\.exe$", re.IGNORECASE)
STATIC_ROOT = Path(os.environ.get("LOCAL_MEETING_NOTES_STATIC_ROOT", str(RESOURCE_ROOT / "dist")))
EVENTS: "queue.Queue[dict[str, Any]]" = queue.Queue()
EVENT_HISTORY: list[dict[str, Any]] = []
EVENT_LOCK = threading.Lock()
NEXT_EVENT_ID = 0
RECORDER: subprocess.Popen[str] | None = None
TRANSCRIBER: subprocess.Popen[str] | None = None
LATEST_OUTPUT_DIR: str | None = None
WORK_ROOT.mkdir(parents=True, exist_ok=True)
LOG_PATH = WORK_ROOT / "server.log"
SETTINGS_PATH = WORK_ROOT / "settings.json"
DOWNLOADED_INSTALLER: Path | None = None
GPU_RUNTIME_ROOT = WORK_ROOT / "gpu-runtime"
GPU_RUNTIME_PACKAGES = [
    ("nvidia-cublas-cu12", "12.9.2.10"),
    ("nvidia-cudnn-cu12", "9.23.2.1"),
    ("nvidia-cuda-nvrtc-cu12", "12.9.86"),
]


class UserFacingValueError(ValueError):
    pass


def configure_standard_streams() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def default_output_root() -> Path:
    return WORK_ROOT / "output"


def load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log(f"settings load failed: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(settings: dict[str, Any]) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def settings_payload() -> dict[str, Any]:
    settings = load_settings()
    output_root = str(settings.get("output_root") or "").strip()
    return {
        "ok": True,
        "output_root": output_root,
        "default_output_root": str(default_output_root()),
    }


def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    if "output_root" in payload:
        output_root = str(payload.get("output_root") or "").strip()
        if output_root:
            path = Path(output_root)
            if not path.is_absolute():
                path = WORK_ROOT / path
            settings["output_root"] = str(path.resolve())
        else:
            settings.pop("output_root", None)
    save_settings(settings)
    return settings_payload()


def log(message: str) -> None:
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def backend_args(*args: str) -> list[str]:
    if IS_FROZEN:
        return [PYTHON, "--backend", *args]
    return [PYTHON, str(ROOT / "backend" / "meeting_notes.py"), *args]


def backend_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["LOCAL_MEETING_NOTES_GPU_RUNTIME"] = str(GPU_RUNTIME_ROOT)
    cuda_paths = []
    nvidia_roots = [
        *(Path(site_path) / "nvidia" for site_path in site.getsitepackages()),
        GPU_RUNTIME_ROOT / "nvidia",
        RESOURCE_ROOT / "nvidia",
        Path(PYTHON).resolve().parent / "nvidia",
    ]
    for nvidia_root in nvidia_roots:
        for relative in ("cublas/bin", "cudnn/bin", "cuda_nvrtc/bin"):
            candidate = nvidia_root / relative
            if candidate.exists() and str(candidate) not in cuda_paths:
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
        cwd=WORK_ROOT,
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


def version_parts(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("vV")
    parts: list[int] = []
    for part in cleaned.split("."):
        match = re.match(r"(\d+)", part)
        parts.append(int(match.group(1)) if match else 0)
    return tuple(parts)


def is_newer_version(candidate: str, current: str) -> bool:
    left = version_parts(candidate)
    right = version_parts(current)
    length = max(len(left), len(right), 3)
    return left + (0,) * (length - len(left)) > right + (0,) * (length - len(right))


def read_url_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"LocalMeetingNotes/{SERVER_VERSION}",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def latest_release_info() -> dict[str, Any]:
    release = read_url_json(RELEASE_API_URL)
    tag_name = str(release.get("tag_name") or "")
    version = tag_name.lstrip("vV")
    selected_asset: dict[str, Any] | None = None
    for asset in release.get("assets", []):
        name = str(asset.get("name") or "")
        if INSTALLER_ASSET_RE.match(name):
            selected_asset = asset
            break
    return {
        "tag_name": tag_name,
        "version": version,
        "release_url": release.get("html_url"),
        "asset": selected_asset,
    }


def check_update() -> dict[str, Any]:
    try:
        info = latest_release_info()
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"Could not check GitHub Releases: HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not check GitHub Releases: {exc}"}

    asset = info.get("asset")
    latest_version = str(info.get("version") or "")
    available = bool(latest_version and is_newer_version(latest_version, SERVER_VERSION) and asset)
    return {
        "ok": True,
        "current_version": SERVER_VERSION,
        "latest_version": latest_version,
        "update_available": available,
        "release_url": info.get("release_url"),
        "asset_name": asset.get("name") if asset else None,
        "asset_size": asset.get("size") if asset else None,
    }


def download_update() -> dict[str, Any]:
    global DOWNLOADED_INSTALLER
    if any_process_running():
        return {"ok": False, "error": "Finish the current recording or transcription before updating."}
    try:
        info = latest_release_info()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not check GitHub Releases: {exc}"}

    asset = info.get("asset")
    latest_version = str(info.get("version") or "")
    if not asset or not latest_version or not is_newer_version(latest_version, SERVER_VERSION):
        return {"ok": False, "error": "No newer installer is available."}

    url = str(asset.get("browser_download_url") or "")
    name = str(asset.get("name") or f"LocalMeetingNotesSetup-{latest_version}.exe")
    if not url:
        return {"ok": False, "error": "The latest release does not include a downloadable installer."}

    target_dir = Path(tempfile.gettempdir()) / "LocalMeetingNotesUpdates"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": f"LocalMeetingNotes/{SERVER_VERSION}"}), timeout=60) as response:
            with target.open("wb") as handle:
                shutil.copyfileobj(response, handle)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not download installer: {exc}"}

    DOWNLOADED_INSTALLER = target
    return {"ok": True, "installer_path": str(target), "latest_version": latest_version}


def install_update() -> dict[str, Any]:
    if any_process_running():
        return {"ok": False, "error": "Finish the current recording or transcription before updating."}
    if not DOWNLOADED_INSTALLER or not DOWNLOADED_INSTALLER.exists():
        return {"ok": False, "error": "Download the update before installing it."}
    try:
        subprocess.Popen([str(DOWNLOADED_INSTALLER)], cwd=str(DOWNLOADED_INSTALLER.parent))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not start installer: {exc}"}
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return {"ok": True}


def shutdown_app() -> dict[str, Any]:
    if any_process_running():
        return {"ok": False, "error": "録音または文字起こしが終わってから終了してください。"}
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return {"ok": True}


def gpu_runtime_paths() -> list[Path]:
    return [
        GPU_RUNTIME_ROOT / "nvidia" / "cublas" / "bin",
        GPU_RUNTIME_ROOT / "nvidia" / "cudnn" / "bin",
        GPU_RUNTIME_ROOT / "nvidia" / "cuda_nvrtc" / "bin",
    ]


def gpu_runtime_files() -> dict[str, bool]:
    return {
        "cublas64_12.dll": (GPU_RUNTIME_ROOT / "nvidia" / "cublas" / "bin" / "cublas64_12.dll").exists(),
        "cudnn64_9.dll": (GPU_RUNTIME_ROOT / "nvidia" / "cudnn" / "bin" / "cudnn64_9.dll").exists(),
        "nvrtc64_120_0.dll": (GPU_RUNTIME_ROOT / "nvidia" / "cuda_nvrtc" / "bin" / "nvrtc64_120_0.dll").exists(),
    }


def nvidia_smi_status() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            text=True,
            capture_output=True,
            timeout=6,
            check=False,
        )
    except FileNotFoundError:
        return {"available": False, "reason": "driver_missing", "message": "NVIDIAドライバーが見つかりません。CPUで実行します。"}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": "probe_failed", "message": f"GPU診断に失敗しました: {exc}"}
    if result.returncode != 0:
        return {
            "available": False,
            "reason": "driver_unavailable",
            "message": "NVIDIA GPUまたはドライバーを確認できません。CPUで実行します。",
            "detail": (result.stderr or result.stdout).strip(),
        }
    gpus = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {"available": bool(gpus), "gpus": gpus, "message": "NVIDIA GPUを検出しました。" if gpus else "NVIDIA GPUが見つかりません。CPUで実行します。"}


def gpu_status() -> dict[str, Any]:
    files = gpu_runtime_files()
    runtime_ready = all(files.values())
    probe = nvidia_smi_status()
    if runtime_ready and probe.get("available"):
        state = "available"
        label = "GPU利用可能"
        message = "GPU(CUDA)対応コンポーネントは導入済みです。"
    elif probe.get("available"):
        state = "setup_available"
        label = "GPU(CUDA)セットアップ可能"
        message = "NVIDIA GPUを検出しました。GPU(CUDA)対応コンポーネントをこのアプリ専用に追加インストールできます。"
    else:
        state = "cpu"
        label = "CPUで実行中"
        message = str(probe.get("message") or "CPUで実行します。")
    return {
        "ok": True,
        "state": state,
        "label": label,
        "message": message,
        "runtime_ready": runtime_ready,
        "runtime_root": str(GPU_RUNTIME_ROOT),
        "runtime_files": files,
        "probe": probe,
    }


def select_wheel_url(package: str, version: str) -> tuple[str, str]:
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    data = read_url_json(url)
    candidates = []
    for file_info in data.get("urls", []):
        filename = str(file_info.get("filename") or "")
        if not filename.endswith(".whl"):
            continue
        if "win_amd64" in filename or "none-any" in filename or "py3-none" in filename:
            candidates.append((filename, str(file_info.get("url") or "")))
    if not candidates:
        raise UserFacingValueError(f"{package} {version} のWindows用wheelが見つかりませんでした。")
    candidates.sort(key=lambda item: ("win_amd64" not in item[0], item[0]))
    filename, wheel_url = candidates[0]
    if not wheel_url:
        raise UserFacingValueError(f"{package} {version} のダウンロードURLが見つかりませんでした。")
    return filename, wheel_url


def download_file(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": f"LocalMeetingNotes/{SERVER_VERSION}"})
    with urllib.request.urlopen(request, timeout=120) as response:
        with target.open("wb") as handle:
            shutil.copyfileobj(response, handle)


def extract_nvidia_dlls(wheel_path: Path) -> int:
    count = 0
    with zipfile.ZipFile(wheel_path) as archive:
        for member in archive.infolist():
            normalized = member.filename.replace("\\", "/")
            if member.is_dir() or not normalized.startswith("nvidia/") or "/bin/" not in normalized or not normalized.lower().endswith(".dll"):
                continue
            target = GPU_RUNTIME_ROOT / Path(*normalized.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            count += 1
    return count


def setup_gpu_runtime() -> dict[str, Any]:
    if any_process_running():
        return {"ok": False, "state": "setup_failed", "label": "GPU(CUDA)セットアップ失敗", "error": "録音または文字起こしが終わってからGPU(CUDA)セットアップを実行してください。"}
    temp_dir = WORK_ROOT / "gpu-runtime-downloads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    installed: list[dict[str, Any]] = []
    try:
        for package, version in GPU_RUNTIME_PACKAGES:
            filename, url = select_wheel_url(package, version)
            wheel_path = temp_dir / filename
            if not wheel_path.exists():
                download_file(url, wheel_path)
            installed.append({"package": package, "version": version, "dll_count": extract_nvidia_dlls(wheel_path)})
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "state": "setup_failed",
            "label": "GPU(CUDA)セットアップ失敗、CPUで続行",
            "error": f"GPU(CUDA)対応コンポーネントを追加インストールできませんでした: {exc}",
        }
    status = gpu_status()
    status.update({"installed": installed, "message": "GPU(CUDA)対応コンポーネントを追加インストールしました。"})
    return status


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
        cwd=WORK_ROOT,
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


def resolve_recording_root(output_root: str) -> Path:
    if not output_root.strip():
        saved_output_root = str(load_settings().get("output_root") or "").strip()
        if saved_output_root:
            return Path(saved_output_root).resolve()
        return default_output_root()
    path = Path(output_root)
    if not path.is_absolute():
        path = WORK_ROOT / path
    return path.resolve()


def start_recording(
    model: str,
    transcribe_device: str,
    mic_device_index: int | None = None,
    system_device_index: int | None = None,
    output_root: str = "",
) -> dict[str, Any]:
    global RECORDER
    if any_process_running():
        return {"ok": False, "error": "Another recording or transcription process is already running."}

    args = ["record", "--model", model, "--transcribe-device", transcribe_device]
    try:
        root = resolve_recording_root(output_root)
        root.mkdir(parents=True, exist_ok=True)
        if output_root.strip():
            update_settings({"output_root": str(root)})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"保存先フォルダを使えませんでした: {exc}"}
    args.extend(["--output-dir", str(root / datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))])
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
        path = WORK_ROOT / path
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


def pick_output_dir(existing_only: bool = True) -> dict[str, Any]:
    env = os.environ.copy()
    settings = load_settings()
    output_root = Path(str(settings.get("output_root") or default_output_root()))
    env["LOCAL_MEETING_NOTES_OUTPUT_ROOT"] = str(output_root.resolve() if output_root.exists() else WORK_ROOT.resolve())
    env["LOCAL_MEETING_NOTES_PICK_DESCRIPTION"] = (
        "Select an existing Local Meeting Notes output folder"
        if existing_only
        else "Select where new recordings should be saved"
    )
    env["LOCAL_MEETING_NOTES_SHOW_NEW_FOLDER"] = "0" if existing_only else "1"
    script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $env:LOCAL_MEETING_NOTES_PICK_DESCRIPTION
$dialog.ShowNewFolderButton = ($env:LOCAL_MEETING_NOTES_SHOW_NEW_FOLDER -eq '1')
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
        cwd=WORK_ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        selected = result.stdout.strip().splitlines()[-1]
        if not existing_only:
            update_settings({"output_root": selected})
        return {"ok": True, "output_dir": selected}
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

    def send_file(self, path: Path) -> None:
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "server_version": SERVER_VERSION})
            return
        if parsed.path == "/api/update/check":
            self.send_json(check_update())
            return
        if parsed.path == "/api/devices":
            self.send_json(run_device_list())
            return
        if parsed.path == "/api/gpu/status":
            self.send_json(gpu_status())
            return
        if parsed.path == "/api/settings":
            self.send_json(settings_payload())
            return
        if parsed.path == "/api/events":
            query = parse_qs(parsed.query)
            since = int(query.get("since", ["0"])[0] or "0")
            with EVENT_LOCK:
                events = [event for event in EVENT_HISTORY if int(event.get("id", 0)) > since]
            self.send_json({"ok": True, "events": events})
            return
        if STATIC_ROOT.exists():
            relative = parsed.path.lstrip("/") or "index.html"
            static_path = (STATIC_ROOT / relative).resolve()
            try:
                static_path.relative_to(STATIC_ROOT.resolve())
            except ValueError:
                self.send_response(403)
                self.end_headers()
                return
            if static_path.exists() and static_path.is_file():
                self.send_file(static_path)
                return
            index_path = STATIC_ROOT / "index.html"
            if index_path.exists():
                self.send_file(index_path)
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
                    str(body.get("outputRoot") or ""),
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
        if self.path == "/api/output/pick-recording-root":
            self.send_json(pick_output_dir(existing_only=False))
            return
        if self.path == "/api/settings":
            self.send_json(update_settings(body))
            return
        if self.path == "/api/gpu/setup":
            self.send_json(setup_gpu_runtime())
            return
        if self.path == "/api/update/download":
            self.send_json(download_update())
            return
        if self.path == "/api/update/install":
            self.send_json(install_update())
            return
        if self.path == "/api/shutdown":
            self.send_json(shutdown_app())
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def main() -> int:
    configure_standard_streams()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
        url = "http://127.0.0.1:8765"
        log(f"{APP_NAME}: {url}")
        print(f"{APP_NAME}: {url}", flush=True)
        open_browser_default = "1" if IS_FROZEN else "0"
        if os.environ.get("LOCAL_MEETING_NOTES_OPEN_BROWSER", open_browser_default) == "1":
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        server.serve_forever()
    except Exception as exc:  # noqa: BLE001
        log(f"server failed: {exc}")
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
