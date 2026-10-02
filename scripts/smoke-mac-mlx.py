"""Verify the shipped backend, offline, using synthetic audio and no Homebrew PATH."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = Path(os.environ.get("LOCAL_MEETING_NOTES_TEST_RESOURCES", str(ROOT / "release/Local Meeting Notes-darwin-arm64/Local Meeting Notes.app/Contents/Resources")))
BINARY = RESOURCES / "backend/LocalMeetingNotesBackend"
FIXTURES = ROOT / "build/mlx-validation"


def main():
    reports = []
    with tempfile.TemporaryDirectory(prefix="meeting-mlx-packaged-") as temporary:
        root = Path(temporary)
        env = {**os.environ, "PATH": "/usr/bin:/bin", "HF_HUB_OFFLINE": "1",
               "HF_HOME": str(Path.home() / "Library/Application Support/Local Meeting Notes/models"),
               "LOCAL_MEETING_NOTES_DATA_ROOT": str(root / "state"),
               "LOCAL_MEETING_NOTES_AUDIO_HELPER": str(RESOURCES / "vendor/MeetingAudio"),
               "LOCAL_MEETING_NOTES_STATIC_ROOT": str(RESOURCES / "dist"),
               "LOCAL_MEETING_NOTES_PORT": "0", "LOCAL_MEETING_NOTES_MANAGED": "1",
               "LOCAL_MEETING_NOTES_OPEN_BROWSER": "0"}
        # Run both files in one process, exercising MLX's shared ModelHolder.
        for model in ("base", "large-v3-turbo"):
            output = root / model
            output.mkdir()
            shutil.copyfile(FIXTURES / "japanese.wav", output / "mic.wav")
            shutil.copyfile(FIXTURES / "long-silence.wav", output / "system.wav")
            start = time.perf_counter()
            run = subprocess.run([str(BINARY), "--backend", "generate", str(output), "--transcribe", "--model", model, "--transcribe-device", "cpu"],
                                 cwd=temporary, env=env, text=True, capture_output=True, timeout=180)
            assert run.returncode == 0, run.stdout + run.stderr
            for track in ("mic", "system"):
                result = json.loads((output / f"{track}_transcript.json").read_text())
                assert result["runtime_device"] == "mlx" and result["compute_type"] == "float16", result
                assert result["language_probability"] is None
                assert result["segments"], result
                if track == "system":
                    assert all(34 <= segment["start"] < 52 and segment["end"] < 53 for segment in result["segments"]), result
            assert (output / "transcript.md").is_file()
            assert (output / "chatgpt_prompt.md").is_file()
            report = {"model": model, "offline": True, "legacy_cpu_request_used_mlx": True,
                      "two_tracks_seconds": round(time.perf_counter() - start, 3), "events": run.stdout.splitlines()}
            reports.append(report)
            print(json.dumps(report, ensure_ascii=False), flush=True)

        process = subprocess.Popen([str(BINARY)], cwd=temporary, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready = json.loads(process.stdout.readline())
            with urllib.request.urlopen(ready["url"] + "/api/capabilities", timeout=20) as response:
                capabilities = json.load(response)
            assert capabilities["default_model"] == "large-v3-turbo"
            assert capabilities["transcribe_devices"] == ["mlx"]
            assert len(capabilities["models"]) == 5
            request = urllib.request.Request(ready["url"] + "/api/shutdown", data=b"{}", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=10) as response:
                assert json.load(response)["ok"]
            process.wait(timeout=15)
            assert process.returncode == 0
        finally:
            if process.poll() is None:
                process.stdin.close()
                process.wait(timeout=15)
            process.stdout.close()
            process.stderr.close()
    (FIXTURES / "packaged-smoke.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Packaged offline MLX smoke passed (base + large-v3-turbo, two tracks, absolute timestamps, HTTP capabilities).")


if __name__ == "__main__":
    main()
