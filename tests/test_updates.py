from __future__ import annotations

import json
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import server, meeting_notes


class UpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_installer = server.DOWNLOADED_INSTALLER
        self.previous_integrity = server.DOWNLOADED_INTEGRITY
        self.previous_shutdown = server.SHUTTING_DOWN

    def tearDown(self) -> None:
        server.DOWNLOADED_INSTALLER = self.previous_installer
        server.DOWNLOADED_INTEGRITY = self.previous_integrity
        server.SHUTTING_DOWN = self.previous_shutdown

    def test_server_version_matches_package_version(self) -> None:
        package_json = Path(__file__).resolve().parents[1] / "package.json"
        package_version = json.loads(package_json.read_text(encoding="utf-8"))["version"]

        self.assertEqual(server.SERVER_VERSION, package_version)
        self.assertEqual(meeting_notes.APP_VERSION, package_version)

    def test_latest_release_selects_windows_installer_from_mixed_assets(self) -> None:
        release = {
            "tag_name": "v1.4.0",
            "html_url": "https://example.test/releases/v1.4.0",
            "assets": [
                {"name": "Local-Meeting-Notes-1.4.0-arm64.dmg"},
                {"name": "Local-Meeting-Notes-1.4.0-mac.zip"},
                {
                    "name": "LocalMeetingNotesSetup-1.4.0.exe",
                    "browser_download_url": "https://example.test/windows.exe",
                    "size": 9,
                    "digest": "sha256:" + "0" * 64,
                },
            ],
        }

        with mock.patch.object(server, "read_url_json", return_value=release):
            info = server.latest_release_info()

        self.assertEqual(info["version"], "1.4.0")
        self.assertEqual(info["asset"]["name"], "LocalMeetingNotesSetup-1.4.0.exe")

    def test_check_update_does_not_offer_same_version(self) -> None:
        release_info = {
            "version": server.SERVER_VERSION,
            "release_url": "https://example.test/releases/current",
            "asset": {"name": f"LocalMeetingNotesSetup-{server.SERVER_VERSION}.exe", "size": 123},
        }

        with (
            mock.patch.object(server.sys, "platform", "win32"),
            mock.patch.object(server, "latest_release_info", return_value=release_info),
        ):
            result = server.check_update()

        self.assertTrue(result["ok"])
        self.assertFalse(result["update_available"])
        self.assertEqual(result["latest_version"], server.SERVER_VERSION)

    def test_check_update_network_failure(self) -> None:
        with mock.patch.object(server.sys, "platform", "win32"), mock.patch.object(server, "latest_release_info", side_effect=OSError("offline")):
            result = server.check_update()
        self.assertFalse(result["ok"])
        self.assertIn("offline", result["error"])

    def test_latest_release_ignores_wrong_version_installer(self) -> None:
        with mock.patch.object(server, "read_url_json", return_value={"tag_name": "v1.0.0", "assets": [{"name": "LocalMeetingNotesSetup-0.3.0.exe"}]}):
            self.assertIsNone(server.latest_release_info()["asset"])

    def test_update_lock_blocks_other_update_and_audio_start(self) -> None:
        server.UPDATE_LOCK.acquire()
        try:
            self.assertFalse(server.download_update()["ok"])
            self.assertFalse(server.install_update()["ok"])
            self.assertFalse(server.start_audio_monitor()["ok"])
            self.assertFalse(server.start_recording("small", "cpu")["ok"])
            self.assertFalse(server.start_transcription("unused", "small", "cpu")["ok"])
        finally:
            server.UPDATE_LOCK.release()

    def test_failed_download_cannot_install_stale_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stale_installer = Path(temp_dir) / "LocalMeetingNotesSetup-0.2.8.exe"
            stale_installer.write_bytes(b"old installer")
            server.DOWNLOADED_INSTALLER = stale_installer
            release_info = {
                "version": "99.0.0",
                "asset": {
                    "name": "LocalMeetingNotesSetup-99.0.0.exe",
                    "browser_download_url": "https://example.test/windows.exe",
                    "size": 9,
                    "digest": "sha256:" + "0" * 64,
                },
            }

            with (
                mock.patch.object(server.sys, "platform", "win32"),
                mock.patch.object(server, "any_process_running", return_value=False),
                mock.patch.object(server, "latest_release_info", return_value=release_info),
                mock.patch.object(server.tempfile, "gettempdir", return_value=temp_dir),
                mock.patch.object(server.urllib.request, "urlopen", side_effect=OSError("network failed")),
            ):
                download_result = server.download_update()
                with mock.patch.object(server.subprocess, "Popen") as popen:
                    install_result = server.install_update()

        self.assertFalse(download_result["ok"])
        self.assertIsNone(server.DOWNLOADED_INSTALLER)
        self.assertEqual(install_result, {"ok": False, "error": "Download the update before installing it."})
        popen.assert_not_called()

    def test_failed_copy_removes_partial_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            release_info = {
                "version": "99.0.0",
                "asset": {
                    "name": "LocalMeetingNotesSetup-99.0.0.exe",
                    "browser_download_url": "https://example.test/windows.exe",
                    "size": 9,
                    "digest": "sha256:" + "0" * 64,
                },
            }
            response = mock.MagicMock()
            response.__enter__.return_value = response
            target = Path(temp_dir) / "LocalMeetingNotesUpdates" / "LocalMeetingNotesSetup-99.0.0.exe"

            def fail_during_copy(_source: object, destination: object) -> None:
                destination.write(b"partial")
                raise OSError("connection reset")

            with (
                mock.patch.object(server.sys, "platform", "win32"),
                mock.patch.object(server, "any_process_running", return_value=False),
                mock.patch.object(server, "latest_release_info", return_value=release_info),
                mock.patch.object(server.tempfile, "gettempdir", return_value=temp_dir),
                mock.patch.object(server.urllib.request, "urlopen", return_value=response),
                mock.patch.object(server.shutil, "copyfileobj", side_effect=fail_during_copy),
            ):
                result = server.download_update()

            self.assertFalse(result["ok"])
            self.assertFalse(target.exists())
            self.assertIsNone(server.DOWNLOADED_INSTALLER)

    def test_verified_download_and_tampered_install(self) -> None:
        payload = b"verified installer"
        with tempfile.TemporaryDirectory() as directory:
            info = {"version": "99.0.0", "asset": {
                "name": "LocalMeetingNotesSetup-99.0.0.exe", "size": len(payload),
                "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "browser_download_url": "https://example.test/installer.exe"}}
            with (mock.patch.object(server.sys, "platform", "win32"),
                  mock.patch.object(server, "any_process_running", return_value=False),
                  mock.patch.object(server, "MONITORS", []),
                  mock.patch.object(server, "latest_release_info", return_value=info),
                  mock.patch.object(server.tempfile, "gettempdir", return_value=directory),
                  mock.patch.object(server.urllib.request, "urlopen", return_value=io.BytesIO(payload))):
                self.assertTrue(server.download_update()["ok"])
                server.DOWNLOADED_INSTALLER.write_bytes(b"tampered")
                with mock.patch.object(server.subprocess, "Popen") as launch:
                    self.assertFalse(server.install_update()["ok"])
                    launch.assert_not_called()

    def test_download_rejects_bad_metadata_and_hash(self) -> None:
        payload = b"installer"
        valid = {"name": "LocalMeetingNotesSetup-99.0.0.exe", "size": len(payload),
                 "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
                 "browser_download_url": "https://example.test/installer.exe"}
        for change in ({"name": "../escape.exe"}, {"size": 100}, {"digest": "sha256:" + "0" * 64}, {"digest": None}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                with (mock.patch.object(server.sys, "platform", "win32"),
                      mock.patch.object(server, "any_process_running", return_value=False),
                      mock.patch.object(server, "MONITORS", []),
                      mock.patch.object(server, "latest_release_info", return_value={"version": "99.0.0", "asset": {**valid, **change}}),
                      mock.patch.object(server.tempfile, "gettempdir", return_value=directory),
                      mock.patch.object(server.urllib.request, "urlopen", return_value=io.BytesIO(payload))):
                    self.assertFalse(server.download_update()["ok"])
                    self.assertIsNone(server.DOWNLOADED_INSTALLER)
                    self.assertFalse(list(Path(directory).rglob("*.part")))

    def test_updates_blocked_by_recording_transcription_and_monitor(self) -> None:
        for busy, monitors in ((True, []), (False, [object()])):
            with self.subTest(busy=busy), mock.patch.object(server.sys, "platform", "win32"), mock.patch.object(server, "any_process_running", return_value=busy), mock.patch.object(server, "MONITORS", monitors):
                self.assertFalse(server.download_update()["ok"])
                self.assertFalse(server.install_update()["ok"])

    def test_verified_installer_launcher_quotes_path_and_preserves_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "日本語 ' update.exe"
            path.write_bytes(b"installer")
            server.DOWNLOADED_INSTALLER = path
            server.DOWNLOADED_INTEGRITY = (9, hashlib.sha256(b"installer").hexdigest())
            with (mock.patch.object(server.sys, "platform", "win32"),
                  mock.patch.object(server, "any_process_running", return_value=False),
                  mock.patch.object(server, "MONITORS", []),
                  mock.patch.object(server.subprocess, "Popen") as launch,
                  mock.patch.object(server.threading, "Timer")):
                self.assertTrue(server.install_update()["ok"])
                self.assertEqual(launch.call_args.args[0][0], server.WINDOWS_POWERSHELL)
                import base64
                command = base64.b64decode(launch.call_args.args[0][-1]).decode("utf-16-le")
                self.assertIn("Wait-Process", command)
                self.assertIn("日本語 '' update.exe", command)
                self.assertIn("/D=" + str(server.ROOT), command)


if __name__ == "__main__":
    unittest.main()
