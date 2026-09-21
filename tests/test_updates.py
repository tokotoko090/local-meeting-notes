from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import server, meeting_notes


class UpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_installer = server.DOWNLOADED_INSTALLER

    def tearDown(self) -> None:
        server.DOWNLOADED_INSTALLER = self.previous_installer

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


if __name__ == "__main__":
    unittest.main()
