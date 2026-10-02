"""Lazy Windows model loading with reuse limited to one transcription job."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

DEFAULT_MODEL = "large-v3-turbo"
DEFAULT_DEVICE = "auto"
MODEL_NAMES = ("base", "small", "medium", "large-v3-turbo")


class ModelDownloadError(RuntimeError):
    """A model could not be acquired; changing GPU/CPU cannot fix this."""


class WindowsTranscriptionSession:
    """Share weights between mic/system, without retaining them across jobs."""

    def __init__(self) -> None:
        self._paths: dict[str, str] = {}
        self._models: dict[tuple[str, str, str], Any] = {}
        self._download_errors: dict[str, ModelDownloadError] = {}

    @staticmethod
    def _complete(path: str) -> bool:
        return all((Path(path) / name).is_file() for name in (
            "config.json", "model.bin", "tokenizer.json",
        ))

    def get_model(self, model_name: str, device: str, compute_type: str,
                  status: Callable[[str], None] | None = None) -> Any:
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model

        key = (model_name, device, compute_type)
        if key in self._models:
            return self._models[key]
        if model_name in self._download_errors:
            raise self._download_errors[model_name]
        if model_name not in self._paths:
            cached = None
            try:
                candidate = download_model(model_name, local_files_only=True)
                if self._complete(candidate):
                    cached = candidate
            except OSError:
                pass
            if cached is None:
                if status:
                    status(f"{model_name}のモデルをダウンロードしています。初回は時間がかかります。")
                try:
                    cached = download_model(model_name)
                    if not self._complete(cached):
                        raise RuntimeError("モデルファイルが不足しています。")
                except Exception as exc:
                    error = ModelDownloadError(
                        f"{model_name}のモデルを取得できませんでした。ネット接続と空き容量を確認して再実行してください。録音は保存されています。詳細: {exc}"
                    )
                    self._download_errors[model_name] = error
                    raise error from exc
            self._paths[model_name] = cached
        if status:
            status(f"{model_name}のモデルを読み込んでいます（{device} / {compute_type}）。")
        model = WhisperModel(self._paths[model_name], device=device,
                             compute_type=compute_type, local_files_only=True)
        self._models[key] = model
        return model

    def close(self) -> None:
        self._models.clear()
        self._paths.clear()
        self._download_errors.clear()

    def __enter__(self) -> WindowsTranscriptionSession:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
