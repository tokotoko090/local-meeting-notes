import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave
import numpy as np
from unittest.mock import Mock, patch

from backend import meeting_notes as notes, mlx_transcription as mlx


class MlxTranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "mic.wav"
        with wave.open(str(self.audio), "wb") as stream:
            stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            stream.writeframes(b"\x10\x00" * 16000)

    def test_mlx_output_and_supported_arguments(self):
        engine = Mock()
        engine.transcribe.return_value = {"segments": [{"start": 1.23456, "end": 2.34567, "text": " 日本語 "}]}
        runtime = Mock()
        with patch.object(mlx, "gpu_runtime", return_value=runtime), patch.object(mlx, "model_path", return_value="cached"), patch.dict(sys.modules, {"mlx_whisper": engine}):
            result = mlx.transcribe(self.audio, "large-v3-turbo")
        self.assertEqual(result["segments"], [{"start": 1.235, "end": 2.346, "text": "日本語"}])
        self.assertIsNone(result["language_probability"])
        self.assertEqual((result["runtime_device"], result["compute_type"]), ("mlx", "float16"))
        kwargs = engine.transcribe.call_args.kwargs
        self.assertTrue(kwargs["fp16"])
        self.assertEqual(kwargs["language"], "ja")
        self.assertNotIn("vad_filter", kwargs)
        self.assertNotIn("beam_size", kwargs)
        runtime.synchronize.assert_called_once()

    def test_gpu_failure_never_calls_cpu_or_completes(self):
        with patch.object(notes.sys, "platform", "darwin"), patch.object(notes, "prepare_audio_for_whisper", return_value=self.audio), patch.object(mlx, "gpu_runtime", side_effect=RuntimeError("GPU unavailable")), patch.object(notes, "whisper_runtime_attempts", side_effect=AssertionError("CPU fallback")):
            with contextlib.redirect_stdout(io.StringIO()) as events:
                with self.assertRaisesRegex(notes.UserFacingError, "GPU unavailable"):
                    notes.transcribe_pair(self.root, "base", "cpu")
        self.assertTrue(self.audio.exists())
        self.assertNotIn("transcription_complete", [json.loads(line)["event"] for line in events.getvalue().splitlines()])

    def test_cached_model_never_attempts_network(self):
        (self.root / "config.json").write_text("{}")
        (self.root / "weights.npz").write_bytes(b"cached model")
        hub = Mock()
        hub.snapshot_download.return_value = str(self.root)
        with patch.dict(mlx._MODEL_PATHS, {}, clear=True), patch.dict(sys.modules, {"huggingface_hub": hub}):
            self.assertEqual(mlx.model_path("base"), str(self.root))
            self.assertEqual(mlx.model_path("base"), str(self.root))
        hub.snapshot_download.assert_called_once()
        self.assertTrue(hub.snapshot_download.call_args.kwargs["local_files_only"])

    def test_silence_does_not_load_model(self):
        with wave.open(str(self.audio), "wb") as stream:
            stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            stream.writeframes(bytes(32000))
        with patch.object(mlx, "gpu_runtime"), patch.object(mlx, "model_path", side_effect=AssertionError("model not needed")):
            self.assertEqual(mlx.transcribe(self.audio, "base")["segments"], [])

    def test_mac_cli_defaults(self):
        with patch.object(notes.sys, "platform", "darwin"):
            for args in (["record"], ["generate", str(self.root), "--transcribe"]):
                parsed = notes.build_parser().parse_args(args)
                self.assertEqual(parsed.model, "large-v3-turbo")
                self.assertEqual(parsed.transcribe_device, "mlx")

    def test_silence_clips_keep_original_offsets_and_quiet_speech(self):
        samples = np.concatenate((np.zeros(35 * 16000), np.full(16000, 0.001), np.zeros(35 * 16000)))
        self.assertEqual(mlx.audible_clips(samples), [34.8, 36.2])
        self.assertEqual(mlx.audible_clips(np.zeros(16000)), [])


if __name__ == "__main__":
    unittest.main()
