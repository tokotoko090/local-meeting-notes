"""Model capabilities and process-boundary regression tests."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

_test_root = tempfile.TemporaryDirectory()
os.environ.setdefault("LOCAL_MEETING_NOTES_DATA_ROOT", _test_root.name)
from backend import server, macos


class MlxApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "mic.wav").touch()

    def test_mac_capabilities(self):
        with patch.object(server.sys, "platform", "darwin"), patch.object(macos, "invoke", return_value={}):
            result = server.capabilities()
        self.assertEqual(result["transcribe_devices"], ["mlx"])
        self.assertEqual(result["default_model"], "large-v3-turbo")
        self.assertEqual([m["id"] for m in result["models"]], ["base", "small", "medium", "large-v3", "large-v3-turbo"])
        self.assertTrue(all(m["label"] for m in result["models"]))

    def test_windows_capabilities(self):
        with patch.object(server.sys, "platform", "win32"):
            result = server.capabilities()
        self.assertEqual(result["default_model"], "large-v3-turbo")
        self.assertEqual(result["default_transcribe_device"], "auto")
        with patch.object(server.sys, "platform", "win32"):
            self.assertEqual(server.default_transcription_model(), "large-v3-turbo")
        self.assertEqual(result["transcribe_devices"], ["cpu", "auto", "cuda"])
        self.assertEqual([m["id"] for m in result["models"]], ["base", "small", "medium", "large-v3-turbo"])

    def test_mac_legacy_device_is_normalized_and_default_applied(self):
        for device in ("", "cpu", "cuda", "auto", "mlx"):
            with self.subTest(device=device), patch.object(server.sys, "platform", "darwin"):
                self.assertEqual(server.normalize_transcription_options("", device), ("large-v3-turbo", "mlx"))

    def test_unsupported_model_never_starts_process(self):
        with patch.object(server.sys, "platform", "darwin"), patch.object(server, "SHUTTING_DOWN", False), patch.object(server, "any_process_running", return_value=False), patch.object(server, "start_backend_process") as start:
            self.assertFalse(server.start_recording("unknown", "cpu", output_root=str(self.root))["ok"])
            self.assertFalse(server.start_transcription(str(self.root), "unknown", "cpu")["ok"])
            start.assert_not_called()

    def test_both_process_entrypoints_force_mlx(self):
        with patch.object(server.sys, "platform", "darwin"), patch.object(server, "SHUTTING_DOWN", False), patch.object(server, "any_process_running", return_value=False), patch.object(server, "resolve_recording_root", return_value=self.root), patch.object(server, "emit"), patch.object(server, "RECORDER"), patch.object(server, "TRANSCRIBER"), patch.object(server, "LATEST_OUTPUT_DIR"), patch.object(server, "start_backend_process", return_value=Mock()) as start:
            self.assertTrue(server.start_recording("base", "cuda")["ok"])
            self.assertEqual(start.call_args.args[0][start.call_args.args[0].index("--transcribe-device") + 1], "mlx")
            self.assertTrue(server.start_transcription(str(self.root), "large-v3", "cpu")["ok"])
            self.assertEqual(start.call_args.args[0][-2:], ["--transcribe-device", "mlx"])


if __name__ == "__main__":
    unittest.main()
