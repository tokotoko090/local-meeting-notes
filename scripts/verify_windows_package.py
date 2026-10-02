"""Verify the packaged Windows app with isolated data and no developer PATH."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request
import wave


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--version", default=json.loads((Path(__file__).resolve().parents[1] / "package.json").read_text(encoding="utf-8"))["version"])
    args = parser.parse_args()
    exe = args.exe.resolve()
    assert exe.is_file(), exe
    ffmpeg = exe.parent / "vendor" / "ffmpeg.exe"
    assert ffmpeg.is_file(), ffmpeg
    with tempfile.TemporaryDirectory(prefix="lmn-package-") as directory:
        root = Path(directory)
        data = root / "日本語 設定"
        data.mkdir()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "PATH": str(Path(os.environ["SystemRoot"]) / "System32"),
               "LOCAL_MEETING_NOTES_DATA_ROOT": str(data), "LOCAL_MEETING_NOTES_PORT": str(port),
               "LOCAL_MEETING_NOTES_OPEN_BROWSER": "0", "PYTHONPATH": "", "PYTHONHOME": ""}
        base = f"http://127.0.0.1:{port}"

        def call(route, body=None):
            request = urllib.request.Request(base + route,
                data=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)

        def start():
            process = subprocess.Popen([str(exe)], cwd=root, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Packaged app exited: {process.returncode}")
                try:
                    health = call("/api/health")
                    assert health["server_version"] == args.version
                    # PyInstaller onefile runs the HTTP server in its child.
                    assert isinstance(health["pid"], int) and health["pid"] > 0
                    return process
                except OSError:
                    time.sleep(.2)
            process.kill()
            process.wait()
            raise TimeoutError("Packaged startup timed out")

        process = start()
        try:
            with urllib.request.urlopen(base, timeout=10) as response:
                assert b'<div id="root">' in response.read()
            capabilities = call("/api/capabilities")
            assert capabilities["platform"] == "win32"
            assert capabilities["default_model"] == "large-v3-turbo"
            assert "cpu" in capabilities["transcribe_devices"]
            settings = call("/api/settings")
            assert settings["model"] == "large-v3-turbo"
            chosen = str(data / "会議の保存先")
            template = "# 依頼\n決定事項と担当者を整理してください。\n"
            assert call("/api/settings", {"output_root": chosen, "model": "small",
                "transcribe_device": "cpu", "prompt_template": template})["ok"]
            audio = data / "保存済み音声"
            audio.mkdir()
            source = audio / "mic.wav"
            with wave.open(str(source), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(bytes(32000))
            converted = root / "converted.wav"
            subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source), "-ar", "16000", "-ac", "1", str(converted)],
                env=env, check=True, timeout=30, capture_output=True)
            assert converted.stat().st_size > 44
            edited = "# 会議\n担当: 田中 😀\n"
            (audio / "chatgpt_prompt.md").write_text("# 元の依頼\n", encoding="utf-8")
            saved_prompt = call("/api/prompt/save", {"outputDir": str(audio), "text": edited})
            assert saved_prompt["ok"], saved_prompt
            assert call("/api/prompt/read", {"outputDir": str(audio)})["text"] == edited
            assert call("/api/shutdown", {})["ok"]
            process.wait(timeout=30)
            process = start()
            saved = call("/api/settings")
            assert saved["output_root"] == chosen
            assert saved["model"] == "small" and saved["transcribe_device"] == "cpu"
            assert saved["prompt_template"] == template
            assert call("/api/prompt/read", {"outputDir": str(audio)})["text"] == edited
            assert call("/api/shutdown", {})["ok"]
            process.wait(timeout=30)
        finally:
            if process.poll() is None:
                try:
                    call("/api/shutdown", {})
                    process.wait(timeout=30)
                except (OSError, subprocess.TimeoutExpired):
                    subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"),
                        "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                    process.wait(timeout=10)
    print("PASS packaged startup, static UI, CPU capability, Unicode settings/prompt, FFmpeg conversion, restart and shutdown without developer PATH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
