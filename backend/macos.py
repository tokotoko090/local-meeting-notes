"""macOS native capture bridge. No audio driver or Python audio binding required."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def helper_path() -> Path:
    override = os.environ.get("LOCAL_MEETING_NOTES_AUDIO_HELPER")
    if override:
        return Path(override)
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "vendor" / "MeetingAudio"


def command(*args: str) -> list[str]:
    helper = helper_path()
    if not helper.is_file():
        raise RuntimeError("Mac録音ヘルパーがありません。npm run build:mac を実行してください。")
    return [str(helper), *args]


def invoke(*args: str, timeout: float = 15) -> dict[str, Any]:
    try:
        result = subprocess.run(command(*args), capture_output=True, text=True, timeout=timeout)
        lines = result.stdout.strip().splitlines()
        payload = json.loads(lines[-1]) if lines else {}
        if result.returncode and not payload.get("error"):
            payload = {"ok": False, "error": result.stderr.strip() or "Mac録音機能の起動に失敗しました。"}
        return payload
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
