"""No network or GPU is used by these model lifecycle tests."""
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.windows_transcription import ModelDownloadError, WindowsTranscriptionSession
from backend import meeting_notes as notes


class WindowsTranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        for name in ("config.json", "model.bin", "tokenizer.json"):
            (self.path / name).write_bytes(b"test")
        self.download = Mock(return_value=str(self.path))
        self.factory = Mock(side_effect=lambda *args, **kwargs: object())
        modules = {"faster_whisper": Mock(WhisperModel=self.factory),
                   "faster_whisper.utils": Mock(download_model=self.download)}
        self.patcher = patch.dict(sys.modules, modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_mic_and_system_reuse_one_model_but_new_job_loads_again(self):
        with WindowsTranscriptionSession() as job:
            mic = job.get_model("large-v3-turbo", "cuda", "float16")
            self.assertIs(mic, job.get_model("large-v3-turbo", "cuda", "float16"))
            self.factory.assert_called_once_with(str(self.path), device="cuda",
                                                compute_type="float16", local_files_only=True)
            self.download.assert_called_once_with("large-v3-turbo", local_files_only=True)
        self.assertEqual(job._models, {})
        with WindowsTranscriptionSession() as next_job:
            self.assertIsNot(mic, next_job.get_model("large-v3-turbo", "cuda", "float16"))
        self.assertEqual(self.factory.call_count, 2)

    def test_download_once_then_load_status_and_reuse(self):
        self.download.side_effect = [OSError("cache miss"), str(self.path)]
        status = Mock()
        with WindowsTranscriptionSession() as job:
            job.get_model("large-v3-turbo", "cpu", "int8", status)
            job.get_model("large-v3-turbo", "cpu", "int8", status)
        self.assertEqual(self.download.call_count, 2)
        messages = [call.args[0] for call in status.call_args_list]
        self.assertIn("ダウンロード", messages[0])
        self.assertIn("読み込んで", messages[1])

    def test_download_error_is_not_retried_for_other_audio(self):
        self.download.side_effect = [OSError("cache miss"), OSError("offline")]
        with WindowsTranscriptionSession() as job:
            for _ in range(2):
                with self.assertRaisesRegex(ModelDownloadError, "録音は保存されています"):
                    job.get_model("large-v3-turbo", "cpu", "int8")
        self.assertEqual(self.download.call_count, 2)
        self.factory.assert_not_called()

    def test_incomplete_download_fails_without_loading(self):
        (self.path / "tokenizer.json").unlink()
        with WindowsTranscriptionSession() as job:
            with self.assertRaises(ModelDownloadError):
                job.get_model("base", "cpu", "int8")
        self.assertEqual(self.download.call_count, 2)
        self.factory.assert_not_called()

    def test_cuda_failure_can_retry_cpu_without_downloading_again(self):
        cpu_model = object()
        self.factory.side_effect = [RuntimeError("CUDA unavailable"), cpu_model]
        with WindowsTranscriptionSession() as job:
            with self.assertRaisesRegex(RuntimeError, "CUDA unavailable"):
                job.get_model("large-v3-turbo", "cuda", "float16")
            self.assertIs(cpu_model, job.get_model("large-v3-turbo", "cpu", "int8"))
        self.download.assert_called_once()
        self.assertEqual(self.factory.call_args.kwargs["compute_type"], "int8")

    def run_pair(self, events=None):
        events = events or Mock()
        with patch.object(notes.sys, "platform", "win32"), patch.object(notes, "CUDA_DISABLED", False), \
                patch.object(notes, "has_audio_frames", return_value=True), \
                patch.object(notes, "configure_cuda_dll_paths"), \
                patch.object(notes, "prepare_audio_for_whisper", side_effect=lambda path: path), \
                patch.object(notes, "emit", events):
            notes.transcribe_pair(self.path, "large-v3-turbo", "auto")
            return events

    def test_integrated_pair_reuses_model_and_writes_both_results(self):
        model = Mock()
        model.transcribe.side_effect = lambda *args, **kwargs: (
            iter([Mock(start=0.0, end=1.0, text=" test ")]),
            Mock(language="ja", language_probability=1.0),
        )
        self.factory.side_effect = None
        self.factory.return_value = model
        events = self.run_pair()
        self.factory.assert_called_once()
        self.assertEqual(model.transcribe.call_count, 2)
        for source in ("mic", "system"):
            result = json.loads((self.path / f"{source}_transcript.json").read_text(encoding="utf-8"))
            self.assertEqual(result["runtime_device"], "cuda")
            self.assertEqual(result["segments"][0]["text"], "test")
        self.assertIn("transcription_complete", [call.args[0] for call in events.call_args_list])

    def test_integrated_cuda_fallback_reuses_cpu_for_second_source(self):
        cpu = Mock()
        cpu.transcribe.side_effect = lambda *args, **kwargs: (iter([]), Mock(language="ja", language_probability=1.0))
        self.factory.side_effect = [RuntimeError("CUDA unavailable"), cpu]
        events = self.run_pair()
        self.assertEqual([call.kwargs["device"] for call in self.factory.call_args_list], ["cuda", "cpu"])
        self.assertEqual(cpu.transcribe.call_count, 2)
        self.assertEqual(sum(call.args[0] == "warning" for call in events.call_args_list), 1)
        for source in ("mic", "system"):
            result = json.loads((self.path / f"{source}_transcript.json").read_text(encoding="utf-8"))
            self.assertEqual((result["runtime_device"], result["compute_type"]), ("cpu", "int8"))

    def test_integrated_download_failure_never_emits_complete_or_cuda_fallback(self):
        self.download.side_effect = [OSError("cache miss"), OSError("offline")]
        events = Mock()
        with self.assertRaises(notes.UserFacingError):
            self.run_pair(events)
        self.factory.assert_not_called()
        self.assertEqual(self.download.call_count, 2)
        self.assertNotIn("transcription_complete", [call.args[0] for call in events.call_args_list])
        self.assertFalse(any("warning_code" in call.kwargs for call in events.call_args_list))
        for source in ("mic", "system"):
            result = json.loads((self.path / f"{source}_transcript.json").read_text(encoding="utf-8"))
            self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
