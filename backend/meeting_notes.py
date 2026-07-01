from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import site
from typing import Any

APP_VERSION = "0.2.8"
IS_FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
DEFAULT_APP_DATA_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LocalMeetingNotes"
GPU_RUNTIME_ROOT = Path(os.environ.get("LOCAL_MEETING_NOTES_GPU_RUNTIME", str(DEFAULT_APP_DATA_ROOT / "gpu-runtime")))
SAMPLE_RATE = 48_000
CHANNELS = 2
FRAMES_PER_BUFFER = 2048
CUDA_DISABLED = False


def configure_standard_streams() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

MOJIBAKE_REPLACEMENTS = {
    "�T�E���h �}�b�p�[": "サウンド マッパー",
    "�}�C�N": "マイク",
    "�w�b�h�Z�b�g": "ヘッドセット",
    "�w�b�h�z��": "ヘッドホン",
    "�X�s�[�J�[": "スピーカー",
    "�C���t�H��": "イヤフォン",
    "�C���^�t�F�[�X": "インターフェース",
    "�f�o�C�X": "デバイス",
}


class UserFacingError(RuntimeError):
    pass


_CUDA_DLL_HANDLES: list[Any] = []


def configure_cuda_dll_paths() -> list[str]:
    paths: list[str] = []
    nvidia_roots = [
        *(Path(site_path) / "nvidia" for site_path in site.getsitepackages()),
        GPU_RUNTIME_ROOT / "nvidia",
        RESOURCE_ROOT / "nvidia",
        Path(sys.executable).resolve().parent / "nvidia",
    ]
    for nvidia_root in nvidia_roots:
        for relative in ("cublas/bin", "cudnn/bin", "cuda_nvrtc/bin"):
            candidate = nvidia_root / relative
            if candidate.exists() and str(candidate) not in paths:
                paths.append(str(candidate))

    if not paths:
        return []

    current_path = os.environ.get("PATH", "")
    existing = {part.lower() for part in current_path.split(os.pathsep) if part}
    missing = [path for path in paths if path.lower() not in existing]
    if missing:
        os.environ["PATH"] = os.pathsep.join([*missing, current_path])

    if hasattr(os, "add_dll_directory"):
        for path in paths:
            try:
                _CUDA_DLL_HANDLES.append(os.add_dll_directory(path))
            except OSError:
                pass
    return paths


def classify_cuda_error(error: Exception) -> tuple[str, str]:
    detail = str(error)
    lowered = detail.lower()
    if "cublas64_12.dll" in lowered or "cudnn" in lowered or "nvrtc" in lowered:
        return (
            "gpu_runtime_missing",
            "GPU(CUDA)対応コンポーネントが未導入です。CPUで続行します。画面上部のGPU(CUDA)セットアップから、このアプリ専用に追加インストールできます。",
        )
    if "cuda driver" in lowered or "driver" in lowered or "cuda_error_no_device" in lowered:
        return ("gpu_driver_missing", "NVIDIAドライバーが古い、または見つかりません。CPUで続行します。")
    if "no cuda" in lowered or "device not found" in lowered or "cuda failed" in lowered:
        return ("gpu_not_found", "NVIDIA GPUが見つかりません。CPUで実行します。")
    return ("gpu_initialization_failed", f"GPU初期化に失敗しました。CPUで続行します。詳細: {detail}")


def configure_binary_paths() -> None:
    candidates = [
        RESOURCE_ROOT / "vendor",
        RESOURCE_ROOT / "ffmpeg",
        Path(sys.executable).resolve().parent / "vendor",
    ]
    existing = {part.lower() for part in os.environ.get("PATH", "").split(os.pathsep) if part}
    additions = [str(path) for path in candidates if path.exists() and str(path).lower() not in existing]
    if additions:
        os.environ["PATH"] = os.pathsep.join([*additions, os.environ.get("PATH", "")])


def resolve_ffmpeg() -> str | None:
    configure_binary_paths()
    candidates = [
        RESOURCE_ROOT / "vendor" / "ffmpeg.exe",
        RESOURCE_ROOT / "ffmpeg" / "ffmpeg.exe",
        Path(sys.executable).resolve().parent / "vendor" / "ffmpeg.exe",
        Path(sys.executable).resolve().parent / "ffmpeg.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    found = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
    return found


def normalize_device_name(name: str) -> str:
    normalized = " ".join(str(name or "Unknown").replace("\x00", "").split())
    for source, target in MOJIBAKE_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"�+", "", normalized)
    return normalized.strip() or "Unknown"


def backend_command_args(*args: str) -> list[str]:
    if IS_FROZEN:
        return [sys.executable, "--backend", *args]
    return [sys.executable, str(Path(__file__).resolve()), *args]


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    channels: int
    sample_rate: int
    is_loopback: bool
    is_input: bool


def device_from_info(info: dict[str, Any]) -> AudioDevice:
    max_input = int(info.get("maxInputChannels", 0))
    return AudioDevice(
        index=int(info.get("index", -1)),
        name=normalize_device_name(str(info.get("name", "Unknown"))),
        channels=max_input,
        sample_rate=int(info.get("defaultSampleRate", SAMPLE_RATE)),
        is_loopback=bool(info.get("isLoopbackDevice", False)),
        is_input=max_input > 0,
    )


def emit(event: str, **payload: Any) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def timestamp_dir(base: Path) -> Path:
    return base / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def import_audio() -> Any:
    try:
        import pyaudiowpatch as pyaudio
    except ImportError as exc:
        raise UserFacingError(
            "pyaudiowpatch is not installed. Run: python -m pip install -r backend\\requirements.txt"
        ) from exc
    return pyaudio


def read_devices() -> list[AudioDevice]:
    pyaudio = import_audio()
    pa = pyaudio.PyAudio()
    try:
        devices: list[AudioDevice] = []
        for index in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(index)
            devices.append(device_from_info(info))
        return devices
    finally:
        pa.terminate()


def choose_microphone(devices: list[AudioDevice], requested_index: int | None) -> AudioDevice:
    if requested_index is not None:
        for device in devices:
            if device.index == requested_index and device.is_input and not device.is_loopback:
                return device
        raise UserFacingError(f"Requested microphone device index {requested_index} is not a microphone input.")

    pyaudio = import_audio()
    pa = pyaudio.PyAudio()
    try:
        wasapi_device = device_from_info(pa.get_default_wasapi_device())
        if wasapi_device.is_input and not wasapi_device.is_loopback:
            return wasapi_device
    except Exception:
        pass
    try:
        default_device = device_from_info(pa.get_default_input_device_info())
        if default_device.is_input and not default_device.is_loopback:
            return default_device
    except Exception:
        pass
    finally:
        pa.terminate()

    for device in devices:
        if device.is_input and not device.is_loopback:
            return device
    raise UserFacingError("No microphone input device found. Enable a microphone and retry.")


def can_open_input_device(device: AudioDevice) -> bool:
    pyaudio = import_audio()
    pa = pyaudio.PyAudio()
    stream = None
    try:
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=max(1, device.channels),
            rate=device.sample_rate or SAMPLE_RATE,
            input=True,
            input_device_index=device.index,
            frames_per_buffer=FRAMES_PER_BUFFER,
        )
        return True
    except Exception:
        return False
    finally:
        if stream is not None:
            stream.close()
        pa.terminate()


def choose_loopback(devices: list[AudioDevice], requested_index: int | None) -> AudioDevice:
    if requested_index is not None:
        for device in devices:
            if device.index == requested_index and device.is_loopback:
                if not can_open_input_device(device):
                    raise UserFacingError(f"Requested system device index {requested_index} could not be opened.")
                return device
        raise UserFacingError(f"Requested system device index {requested_index} is not a WASAPI loopback device.")

    candidates: list[AudioDevice] = []
    pyaudio = import_audio()
    pa = pyaudio.PyAudio()
    try:
        candidates.append(device_from_info(pa.get_default_wasapi_loopback()))
    except Exception:
        pass
    finally:
        pa.terminate()

    for device in devices:
        if device.is_loopback and device.is_input:
            if all(candidate.index != device.index for candidate in candidates):
                candidates.append(device)
    for device in devices:
        if device.is_loopback:
            if all(candidate.index != device.index for candidate in candidates):
                candidates.append(device)
    for device in candidates:
        if can_open_input_device(device):
            return device
    raise UserFacingError("No WASAPI loopback device found. Confirm a playback device is active, then retry.")


def write_log(output_dir: Path, message: str) -> None:
    with (output_dir / "app.log").open("a", encoding="utf-8") as log:
        log.write(f"{now_iso()} {message}\n")


def create_wave(path: Path, channels: int, sample_rate: int) -> wave.Wave_write:
    wav = wave.open(str(path), "wb")
    wav.setnchannels(channels)
    wav.setsampwidth(2)
    wav.setframerate(sample_rate)
    return wav


def record_device(
    *,
    stop_event: threading.Event,
    error_queue: queue.Queue[str],
    output_dir: Path,
    file_name: str,
    device: AudioDevice,
) -> None:
    pyaudio = import_audio()
    pa = pyaudio.PyAudio()
    channels = max(1, device.channels)
    sample_rate = device.sample_rate or SAMPLE_RATE
    wav = create_wave(output_dir / file_name, channels, sample_rate)
    stream = None
    try:
        write_log(output_dir, f"opening {file_name} on device {device.index}: {device.name}")
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=sample_rate,
            input=True,
            input_device_index=device.index,
            frames_per_buffer=FRAMES_PER_BUFFER,
        )
        write_log(output_dir, f"started {file_name} on device {device.index}: {device.name}")
        while not stop_event.is_set():
            data = stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)
            wav.writeframes(data)
    except Exception as exc:  # noqa: BLE001
        error_queue.put(f"{file_name}: {exc}")
    finally:
        if stream is not None:
            if stream.is_active():
                stream.stop_stream()
            stream.close()
        wav.close()
        pa.terminate()
        write_log(output_dir, f"stopped {file_name}")


def run_record_one(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    devices = read_devices()
    device = next((candidate for candidate in devices if candidate.index == args.device_index), None)
    if device is None:
        raise UserFacingError(f"Device index {args.device_index} was not found.")

    stop_event = threading.Event()
    errors: queue.Queue[str] = queue.Queue()

    def stdin_stop() -> None:
        for line in sys.stdin:
            if line.strip().lower() in {"stop", "quit", "exit"}:
                stop_event.set()
                return

    threading.Thread(target=stdin_stop, daemon=True).start()
    if args.duration is not None:
        threading.Timer(args.duration, stop_event.set).start()

    record_device(
        stop_event=stop_event,
        error_queue=errors,
        output_dir=output_dir,
        file_name=args.file_name,
        device=device,
    )
    if not errors.empty():
        raise UserFacingError(errors.get())
    emit("record_one_complete", file=args.file_name)
    return 0


def wait_for_stop(stop_event: threading.Event, duration: int | None) -> None:
    if duration is not None:
        stop_event.wait(duration)
        stop_event.set()
        return

    def handle_signal(signum: int, _frame: Any) -> None:
        emit("status", message=f"Received signal {signum}; stopping recording.")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    for line in sys.stdin:
        if line.strip().lower() in {"stop", "quit", "exit"}:
            stop_event.set()
            return


def assert_file_has_audio(path: Path) -> None:
    if not path.exists() or path.stat().st_size <= 44:
        raise UserFacingError(f"{path.name} was not recorded or is empty.")


def has_audio_frames(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 44


def run_record(args: argparse.Namespace) -> int:
    configure_binary_paths()
    if resolve_ffmpeg() is None:
        raise UserFacingError("ffmpeg was not found in PATH. Install ffmpeg before recording.")

    output_dir = Path(args.output_dir) if args.output_dir else timestamp_dir(Path("output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    write_log(output_dir, "record command started")

    devices = read_devices()
    mic_device = choose_microphone(devices, args.mic_device_index)
    system_device = choose_loopback(devices, args.system_device_index)
    started = now_iso()
    started_monotonic = time.monotonic()

    metadata: dict[str, Any] = {
        "recording_started_at": started,
        "recording_stopped_at": None,
        "duration_seconds": None,
        "mic_device_name": mic_device.name,
        "system_device_name": system_device.name,
        "whisper_model": args.model,
        "app_version": APP_VERSION,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    emit("recording_started", output_dir=str(output_dir.resolve()), mic_device=mic_device.name, system_device=system_device.name)

    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_specs = [
        ("mic.wav", mic_device.index),
        ("system.wav", system_device.index),
    ]
    children: list[tuple[str, subprocess.Popen[str]]] = []
    for file_name, device_index in child_specs:
        child_args = [
            *backend_command_args(
            "record-one",
            "--output-dir",
            str(output_dir),
            "--file-name",
            file_name,
            "--device-index",
            str(device_index),
            )
        ]
        child = subprocess.Popen(
            child_args,
            cwd=Path.cwd(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
        )
        children.append((file_name, child))

    if args.duration is not None:
        time.sleep(args.duration)
    else:
        wait_for_stop(threading.Event(), None)

    for _file_name, child in children:
        if child.stdin is not None and child.poll() is None:
            child.stdin.write("stop\n")
            child.stdin.flush()

    captured_errors: list[str] = []
    for file_name, child in children:
        try:
            stdout, stderr = child.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate(timeout=5)
            captured_errors.append(f"{file_name}: timed out while stopping")
        for line in stdout.splitlines():
            write_log(output_dir, f"{file_name} stdout {line}")
        for line in stderr.splitlines():
            write_log(output_dir, f"{file_name} stderr {line}")
        if child.returncode != 0:
            captured_errors.append(f"{file_name}: recorder exited with code {child.returncode}")

    stopped = now_iso()
    duration_seconds = round(time.monotonic() - started_monotonic, 2)
    metadata["recording_stopped_at"] = stopped
    metadata["duration_seconds"] = duration_seconds
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    mic_errors = [message for message in captured_errors if message.startswith("mic.wav:")]
    system_errors = [message for message in captured_errors if message.startswith("system.wav:")]
    for message in system_errors:
        write_log(output_dir, f"warning {message}")
        emit("warning", message=f"PC出力音声の録音で警告: {message}")
    if mic_errors:
        raise UserFacingError(mic_errors[0])

    assert_file_has_audio(output_dir / "mic.wav")
    if not has_audio_frames(output_dir / "system.wav"):
        write_log(output_dir, "system.wav contains no audio frames; continuing with an empty system transcript")
        emit("warning", message="system.wav に音声フレームがありません。PC側で音声が再生されているか確認してください。")
    emit("recording_stopped", duration_seconds=duration_seconds)

    if not args.skip_transcribe:
        transcribe_pair(output_dir, args.model, args.transcribe_device)
        generate_transcript(output_dir)
        generate_prompt(output_dir)
    emit("complete", output_dir=str(output_dir.resolve()))
    return 0


def transcribe_audio(audio_path: Path, model_name: str, transcribe_device: str = "cpu") -> dict[str, Any]:
    global CUDA_DISABLED
    if not has_audio_frames(audio_path):
        return {
            "source_file": audio_path.name,
            "language": "ja",
            "language_probability": 0,
            "segments": [],
        }
    configure_cuda_dll_paths()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise UserFacingError(
            "faster-whisper is not installed. Run: python -m pip install -r backend\\requirements.txt"
        ) from exc

    whisper_audio_path = prepare_audio_for_whisper(audio_path)
    last_error: Exception | None = None
    for device, compute_type in whisper_runtime_attempts(transcribe_device):
        try:
            model = WhisperModel(model_name, device=device, compute_type=compute_type)
            segments, info = model.transcribe(
                str(whisper_audio_path),
                language="ja",
                vad_filter=True,
                beam_size=1,
                best_of=1,
            )
            segment_items = [
                {"start": round(segment.start, 3), "end": round(segment.end, 3), "text": segment.text.strip()}
                for segment in segments
                if segment.text.strip()
            ]
            selected_runtime = (device, compute_type)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if device == "cuda":
                CUDA_DISABLED = True
                code, message = classify_cuda_error(exc)
                emit("warning", warning_code=code, message=message, detail=str(exc))
                continue
            raise
    else:
        raise last_error or UserFacingError("Could not run the Whisper model.")
    return {
        "source_file": audio_path.name,
        "language": info.language,
        "language_probability": info.language_probability,
        "runtime_device": selected_runtime[0] if selected_runtime else "unknown",
        "compute_type": selected_runtime[1] if selected_runtime else "unknown",
        "segments": segment_items,
    }


def whisper_runtime_attempts(transcribe_device: str) -> list[tuple[str, str]]:
    if CUDA_DISABLED:
        return [("cpu", "int8")]
    if transcribe_device == "cuda":
        return [("cuda", "float16"), ("cpu", "int8")]
    if transcribe_device == "auto":
        return [("cuda", "float16"), ("cpu", "int8")]
    return [("cpu", "int8")]


def prepare_audio_for_whisper(audio_path: Path) -> Path:
    ffmpeg = resolve_ffmpeg()
    prepared_path = audio_path.with_name(f"{audio_path.stem}_whisper.wav")
    if prepared_path.exists() and prepared_path.stat().st_mtime >= audio_path.stat().st_mtime:
        return prepared_path
    if ffmpeg is None:
        return audio_path

    with tempfile.TemporaryDirectory(prefix="local-meeting-notes-") as temp_dir:
        temp_root = Path(temp_dir)
        temp_input = temp_root / "input.wav"
        temp_output = temp_root / "output.wav"
        shutil.copyfile(audio_path, temp_input)
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(temp_input),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-sample_fmt",
            "s16",
            str(temp_output),
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            suffix = f": {detail}" if detail else ""
            raise UserFacingError(f"Whisper用の音声変換に失敗しました{suffix}")
        shutil.copyfile(temp_output, prepared_path)
    return prepared_path


def transcribe_pair(output_dir: Path, model_name: str, transcribe_device: str = "cpu") -> None:
    emit("transcription_started", model=model_name, transcribe_device=transcribe_device)
    for source, target in [("mic.wav", "mic_transcript.json"), ("system.wav", "system_transcript.json")]:
        emit("transcribing", file=source)
        try:
            result = transcribe_audio(output_dir / source, model_name, transcribe_device)
        except Exception as exc:  # noqa: BLE001
            write_log(output_dir, f"warning transcription failed for {source}: {exc}")
            emit("warning", message=f"Transcription failed for {source}: {exc}")
            result = {
                "source_file": source,
                "language": "ja",
                "language_probability": 0,
                "segments": [],
                "error": str(exc),
            }
        (output_dir / target).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    emit("transcription_complete")


def format_offset(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def load_segments(output_dir: Path) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for source, name in [("mic", "mic_transcript.json"), ("system", "system_transcript.json")]:
        path = output_dir / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for segment in data.get("segments", []):
            text = str(segment.get("text", "")).strip()
            if text:
                combined.append({"source": source, "start": float(segment.get("start", 0)), "text": text})
    return sorted(combined, key=lambda item: item["start"])


def generate_transcript(output_dir: Path) -> Path:
    lines = ["# 文字起こし", ""]
    for segment in load_segments(output_dir):
        lines.append(f"* [{format_offset(segment['start'])}] [{segment['source']}] {segment['text']}")
    lines.extend(
        [
            "",
            "## 元ファイル",
            "",
            "* mic.wav",
            "* system.wav",
            "* mic_transcript.json",
            "* system_transcript.json",
            "",
            "## メモ",
            "",
            "* [mic] は自分のマイク音声",
            "* [system] はPC出力音声",
            "",
        ]
    )
    path = output_dir / "transcript.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    emit("transcript_generated", file=str(path.resolve()))
    return path


def generate_prompt(output_dir: Path) -> Path:
    transcript_path = output_dir / "transcript.md"
    transcript = transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else ""
    prompt = f"""# 依頼

以下は会議の文字起こしです。mic は自分の発言、system はPCから聞こえた相手側や共有音声です。この文字起こしをもとに、議事録を作成してください。

# 出力形式

## 会議概要
*

## 決定事項
*

## 議論内容
*

## ToDo

| 担当 | 内容 | 期限 |
| -- | -- | -- |

## 保留事項
*

## 次回確認事項
*

## 重要発言
*

## 文字起こし全文

{transcript}
"""
    path = output_dir / "chatgpt_prompt.md"
    path.write_text(prompt, encoding="utf-8")
    emit("prompt_generated", file=str(path.resolve()))
    return path

def run_list_devices(_args: argparse.Namespace) -> int:
    devices = read_devices()
    if getattr(_args, "json", False):
        print(
            json.dumps(
                {
                    "devices": [
                        {
                            "index": device.index,
                            "name": device.name,
                            "channels": device.channels,
                            "sample_rate": device.sample_rate,
                            "is_loopback": device.is_loopback,
                            "is_input": device.is_input,
                            "kind": "system" if device.is_loopback else "mic" if device.is_input else "other",
                        }
                        for device in devices
                    ]
                },
                ensure_ascii=True,
            ),
            flush=True,
        )
        return 0
    for device in devices:
        flags = []
        if device.is_input and not device.is_loopback:
            flags.append("mic")
        if device.is_loopback:
            flags.append("loopback")
        print(f"[{device.index}] {'/'.join(flags) or 'other'} {device.name} ({device.channels}ch, {device.sample_rate}Hz)")
    return 0


def run_generate(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    if args.transcribe:
        transcribe_pair(output_dir, args.model, args.transcribe_device)
    generate_transcript(output_dir)
    generate_prompt(output_dir)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Meeting Notes backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_devices = subparsers.add_parser("list-devices")
    list_devices.add_argument("--json", action="store_true")
    list_devices.set_defaults(func=run_list_devices)

    record = subparsers.add_parser("record")
    record.add_argument("--duration", type=int, default=None, help="Stop automatically after this many seconds.")
    record.add_argument("--output-dir", default=None)
    record.add_argument("--mic-device-index", type=int, default=None)
    record.add_argument("--system-device-index", type=int, default=None)
    record.add_argument("--model", default="small")
    record.add_argument("--transcribe-device", choices=["cpu", "auto", "cuda"], default="cpu")
    record.add_argument("--skip-transcribe", action="store_true")
    record.set_defaults(func=run_record)

    record_one = subparsers.add_parser("record-one")
    record_one.add_argument("--output-dir", required=True)
    record_one.add_argument("--file-name", required=True)
    record_one.add_argument("--device-index", type=int, required=True)
    record_one.add_argument("--duration", type=int, default=None)
    record_one.set_defaults(func=run_record_one)

    generate = subparsers.add_parser("generate")
    generate.add_argument("output_dir")
    generate.add_argument("--model", default="small")
    generate.add_argument("--transcribe", action="store_true")
    generate.add_argument("--transcribe-device", choices=["cpu", "auto", "cuda"], default="cpu")
    generate.set_defaults(func=run_generate)
    return parser


def main() -> int:
    configure_standard_streams()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except UserFacingError as exc:
        emit("error", message=str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
