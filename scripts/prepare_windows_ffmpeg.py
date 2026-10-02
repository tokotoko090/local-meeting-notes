"""Prepare a verified, relocatable ffmpeg; never package a PATH/Chocolatey shim."""

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import wave
import zipfile

ARCHIVE_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def extract_verified(archive: Path, checksum: str, destination: Path) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        raise ValueError("Invalid published ffmpeg SHA-256")
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != checksum.lower():
        raise ValueError("ffmpeg archive SHA-256 mismatch")
    with zipfile.ZipFile(archive) as bundle:
        candidates = []
        for entry in bundle.infolist():
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in entry.filename:
                raise ValueError("Unsafe ffmpeg archive path")
            if path.name == "ffmpeg.exe" and path.parent.name == "bin":
                candidates.append(entry)
        if len(candidates) != 1:
            raise ValueError("Expected exactly one bin/ffmpeg.exe in archive")
        with bundle.open(candidates[0]) as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)


def validate_standalone(executable: Path) -> None:
    # Copy ONLY this executable: a shim may work in its original installation
    # but fail after deployment because its relative target or DLLs are missing.
    with tempfile.TemporaryDirectory(prefix="lmn-ffmpeg-smoke-") as folder:
        isolated = Path(folder)
        copied = isolated / "ffmpeg.exe"
        shutil.copy2(executable, copied)
        options = dict(cwd=isolated, capture_output=True, timeout=30, check=True)
        subprocess.run([str(copied), "-hide_banner", "-version"], **options)
        source = isolated / "input.wav"
        target = isolated / "output.wav"
        with wave.open(str(source), "wb") as audio:
            audio.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0" * 19200)
        subprocess.run([
            str(copied), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(target),
        ], **options)
        with wave.open(str(target), "rb") as audio:
            if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (1, 16000, 2) or audio.getnframes() == 0:
                raise ValueError("ffmpeg conversion smoke test produced invalid audio")


def prepare(output: Path, allow_local_cache: bool = False) -> None:
    output = output.resolve()
    with tempfile.TemporaryDirectory(prefix="lmn-ffmpeg-download-") as folder:
        scratch = Path(folder)
        archive = scratch / "ffmpeg.zip"
        checksum_file = scratch / "ffmpeg.sha256"
        try:
            download(ARCHIVE_URL + ".sha256", checksum_file)
            download(ARCHIVE_URL, archive)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if not allow_local_cache or not output.is_file():
                raise
            print(f"Download unavailable ({error}); validating local ffmpeg cache.")
            validate_standalone(output)
            return
        candidate = scratch / "ffmpeg.exe"
        extract_verified(archive, checksum_file.read_text(encoding="ascii").strip(), candidate)
        validate_standalone(candidate)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Replace only after all validation succeeds; preserve a working cache
        # when a download, hash check, extraction or conversion fails.
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix="ffmpeg-", suffix=".tmp", delete=False) as stage:
            staged = Path(stage.name)
        try:
            shutil.copy2(candidate, staged)
            os.replace(staged, output)
        finally:
            staged.unlink(missing_ok=True)
        print(f"Verified standalone ffmpeg: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-local-cache", action="store_true")
    args = parser.parse_args()
    prepare(args.output, args.allow_local_cache)
