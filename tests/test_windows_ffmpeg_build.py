import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from scripts import prepare_windows_ffmpeg as ffmpeg


class WindowsFfmpegBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "archive.zip"
        self.output = self.root / "ffmpeg.exe"

    def archive_with(self, names):
        with zipfile.ZipFile(self.archive, "w") as bundle:
            for name in names:
                bundle.writestr(name, b"standalone executable")
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def test_verified_archive_extracts_only_executable(self):
        digest = self.archive_with(["ffmpeg/bin/ffmpeg.exe", "ffmpeg/doc/readme.txt"])
        ffmpeg.extract_verified(self.archive, digest, self.output)
        self.assertEqual(self.output.read_bytes(), b"standalone executable")
        self.assertFalse((self.root / "ffmpeg").exists())

    def test_checksum_mismatch_preserves_existing_executable(self):
        self.archive_with(["ffmpeg/bin/ffmpeg.exe"])
        self.output.write_bytes(b"existing")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            ffmpeg.extract_verified(self.archive, "0" * 64, self.output)
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_rejects_unsafe_and_ambiguous_archives(self):
        for names in (["../bin/ffmpeg.exe"], ["C:/bin/ffmpeg.exe"],
                      ["one/bin/ffmpeg.exe", "two/bin/ffmpeg.exe"]):
            with self.subTest(names=names):
                digest = self.archive_with(names)
                with self.assertRaises(ValueError):
                    ffmpeg.extract_verified(self.archive, digest, self.output)

    def test_offline_cache_requires_permission_and_validation(self):
        self.output.write_bytes(b"cached")
        with patch.object(ffmpeg, "download", side_effect=urllib.error.URLError("offline")), patch.object(ffmpeg, "validate_standalone") as validate:
            with self.assertRaises(urllib.error.URLError):
                ffmpeg.prepare(self.output)
            validate.assert_not_called()
            ffmpeg.prepare(self.output, allow_local_cache=True)
            validate.assert_called_once_with(self.output.resolve())

    def test_shim_failure_in_isolated_copy_rejects_cache(self):
        self.output.write_bytes(b"shim")
        def fail(command, **options):
            copied = Path(command[0])
            self.assertNotEqual(copied.parent, self.output.parent)
            self.assertEqual(copied.read_bytes(), b"shim")
            self.assertEqual(list(copied.parent.iterdir()), [copied])
            raise subprocess.CalledProcessError(1, command)
        with patch.object(ffmpeg.subprocess, "run", side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError):
                ffmpeg.validate_standalone(self.output)

    def test_failed_conversion_preserves_existing_cache(self):
        digest = self.archive_with(["ffmpeg/bin/ffmpeg.exe"])
        self.output.write_bytes(b"existing")
        def download(url, destination):
            if url.endswith(".sha256"):
                destination.write_text(digest, encoding="ascii")
            else:
                destination.write_bytes(self.archive.read_bytes())
        with patch.object(ffmpeg, "download", side_effect=download), patch.object(ffmpeg, "validate_standalone", side_effect=ValueError("conversion failed")):
            with self.assertRaisesRegex(ValueError, "conversion failed"):
                ffmpeg.prepare(self.output, allow_local_cache=True)
        self.assertEqual(self.output.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
