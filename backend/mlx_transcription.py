"""Apple Silicon transcription. Imports stay lazy for Windows and the HTTP server."""
from __future__ import annotations

import os
import platform
import wave
from pathlib import Path
from typing import Callable

DEFAULT_MODEL = "large-v3-turbo"
MODEL_OPTIONS = [
    {"id": "base", "label": "base — 軽量・速度優先"},
    {"id": "small", "label": "small — 速度と精度のバランス"},
    {"id": "medium", "label": "medium — 精度重視"},
    {"id": "large-v3", "label": "large-v3 — 高精度・処理負荷大"},
    {"id": "large-v3-turbo", "label": "large-v3-turbo — 高精度と速度の両立（標準）"},
]
MODEL_REPOS = {
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}
_MODEL_PATHS: dict[str, str] = {}


def audible_clips(samples) -> list[float]:
    """Skip near-digital silence, retaining absolute recording timestamps.

    A conservative -80 dB peak floor retains quiet speech; this is not a speech
    classifier. Group activity across gaps shorter than one second and retain
    200 ms around it so that word boundaries are not clipped.
    """
    import numpy as np
    if not samples.size:
        return []
    frame = 1600  # 100 ms at 16 kHz
    padded = np.pad(samples, (0, (-samples.size) % frame))
    active = np.flatnonzero(np.max(np.abs(padded.reshape(-1, frame)), axis=1) > 0.0001)
    if not active.size:
        return []
    groups = np.split(active, np.flatnonzero(np.diff(active) > 10) + 1)
    duration = samples.size / 16000
    return [boundary for group in groups for boundary in (
        round(max(0, int(group[0]) * .1 - .2), 3),
        round(min(duration, (int(group[-1]) + 1) * .1 + .2), 3),
    )]


def validate_model(name: str) -> str:
    if name not in MODEL_REPOS:
        raise ValueError(f"未対応の文字起こしモデルです: {name}")
    return name


def gpu_runtime():
    if platform.machine() != "arm64":
        raise RuntimeError("文字起こしにはApple SiliconのMacが必要です。")
    try:
        import mlx.core as mx
    except ImportError as exc:
        raise RuntimeError(f"MLXを読み込めません。Mac版アプリを再ビルドまたは再インストールしてください。詳細: {exc}") from exc
    if not mx.metal.is_available():
        raise RuntimeError("Apple SiliconのGPUを利用できません。アプリを再起動してください。CPUへの切り替えは行いません。")
    mx.set_default_device(mx.gpu)
    return mx


def model_path(name: str, status: Callable[[str], None] | None = None) -> str:
    validate_model(name)
    if name in _MODEL_PATHS:
        return _MODEL_PATHS[name]
    # Set before importing Hugging Face, whose constants are initialized on import.
    data_root = Path(os.environ.get("LOCAL_MEETING_NOTES_DATA_ROOT", str(Path.home() / "Library/Application Support/Local Meeting Notes")))
    os.environ.setdefault("HF_HOME", str(data_root / "models"))
    from huggingface_hub import snapshot_download
    options = dict(repo_id=MODEL_REPOS[name], allow_patterns=["config.json", "model.safetensors", "weights.safetensors", "weights.npz"])

    def complete(path: str) -> bool:
        root = Path(path)
        return (root / "config.json").is_file() and any((root / file).is_file() for file in ("model.safetensors", "weights.safetensors", "weights.npz"))

    try:
        cached = snapshot_download(**options, local_files_only=True)
        if complete(cached):
            _MODEL_PATHS[name] = cached
            return cached
    except OSError:
        pass
    if status:
        status(f"{name}のモデルを準備しています。初回はダウンロードに時間がかかります。")
    try:
        downloaded = snapshot_download(**options)
        if not complete(downloaded):
            raise RuntimeError("モデルファイルが不足しています。")
    except Exception as exc:
        raise RuntimeError(f"{name}のモデルを取得できませんでした。ネット接続と空き容量を確認して再実行してください。録音は保存されています。") from exc
    _MODEL_PATHS[name] = downloaded
    return downloaded


def transcribe(audio_path: Path, model_name: str, status: Callable[[str], None] | None = None) -> dict:
    validate_model(model_name)
    mx = gpu_runtime()
    import numpy as np

    # Use the app's already-converted WAV; MLX's path loader requires ffmpeg on PATH.
    with wave.open(str(audio_path), "rb") as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (16000, 1, 2):
            raise RuntimeError("文字起こし用音声を16kHz・モノラルPCM16へ変換できませんでした。")
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    result = {"language": "ja", "language_probability": None, "runtime_device": "mlx", "compute_type": "float16", "segments": []}
    clips = audible_clips(samples)
    if not clips:
        return result
    path = model_path(model_name, status)
    import mlx_whisper
    try:
        output = mlx_whisper.transcribe(
            samples, path_or_hf_repo=path, language="ja", task="transcribe",
            fp16=True, verbose=None, temperature=0.0,
            no_speech_threshold=0.6, logprob_threshold=-1.0,
            condition_on_previous_text=False,
            clip_timestamps=clips,
        )
        mx.synchronize()
    except Exception as exc:
        raise RuntimeError(f"Apple Siliconでの文字起こしに失敗しました。メモリ不足の場合は小さいモデルを選んで再実行してください。録音は保存されています。詳細: {exc}") from exc
    result["segments"] = [
        {"start": round(float(segment["start"]), 3), "end": round(float(segment["end"]), 3), "text": segment["text"].strip()}
        for segment in output["segments"] if segment["text"].strip()
    ]
    return result
