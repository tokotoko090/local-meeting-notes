import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
import array
from unittest.mock import patch, Mock

# Import the server without writing real user preferences.
_test_root = tempfile.TemporaryDirectory()
os.environ['LOCAL_MEETING_NOTES_DATA_ROOT'] = _test_root.name
from backend import meeting_notes as notes, macos, server


class MacTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_no_windows_audio_dependency_on_mac(self):
        with patch.object(notes.sys, 'platform', 'darwin'), patch.object(macos, 'invoke', return_value={'ok': True, 'devices': []}), patch.object(notes, 'import_audio', side_effect=AssertionError('Windows audio imported')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(notes.run_list_devices(Mock()), 0)
            self.assertEqual(json.loads(output.getvalue())['devices'], [])

    @unittest.skipUnless(sys.platform == 'darwin' and (Path(__file__).resolve().parents[1] / 'vendor/MeetingAudio').exists(), 'Build native helper first')
    def test_native_wave_alignment_and_resampling(self):
        helper = Path(__file__).resolve().parents[1] / 'vendor/MeetingAudio'
        result = subprocess.run([str(helper), 'self-test', str(self.root)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, expected in [('mic', .1), ('system', .3)]:
            with wave.open(str(self.root / f'{name}.wav')) as track:
                self.assertEqual((track.getnframes(), track.getframerate(), track.getnchannels()), (24000, 48000, 1))
                samples = array.array('h', track.readframes(track.getnframes()))
            audible = [index / 48000 for index, value in enumerate(samples) if abs(value) > 50]
            self.assertAlmostEqual(audible[0], expected, delta=.005)
            self.assertAlmostEqual(audible[-1], expected + .1, delta=.005)

    def test_mac_cannot_use_legacy_runtime(self):
        with patch.object(notes.sys, 'platform', 'darwin'):
            with self.assertRaises(notes.UserFacingError):
                notes.whisper_runtime_attempts('auto')

    def test_windows_cuda_fallback_preserved(self):
        with patch.object(notes.sys, 'platform', 'win32'), patch.object(notes, 'CUDA_DISABLED', False):
            self.assertEqual(notes.whisper_runtime_attempts('auto'), [('cuda', 'float16'), ('cpu', 'int8')])

    def test_mac_update_and_gpu_routes_never_download_windows_files(self):
        with patch.object(server.sys, 'platform', 'darwin'), patch.object(server, 'latest_release_info', side_effect=AssertionError('network call')):
            self.assertFalse(server.check_update()['update_available'])
            self.assertFalse(server.download_update()['ok'])
            self.assertFalse(server.install_update()['ok'])
            self.assertFalse(server.setup_gpu_runtime()['ok'])

    def test_settings_persist_unicode_directory(self):
        with patch.object(server, 'SETTINGS_PATH', self.root / 'settings.json'):
            chosen = str((self.root / '日本語 空白').resolve())
            self.assertEqual(server.update_settings({'output_root': chosen})['output_root'], chosen)
            self.assertEqual(server.load_settings()['output_root'], chosen)

    def test_failed_model_download_is_failure_not_complete(self):
        with patch.object(notes, 'transcribe_audio', side_effect=RuntimeError('model download failed')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(notes.UserFacingError):
                    notes.transcribe_pair(self.root, 'base')
            events = [json.loads(line)['event'] for line in output.getvalue().splitlines()]
            self.assertNotIn('transcription_complete', events)
            self.assertNotIn('complete', events)
            self.assertIn('model download failed', (self.root / 'mic_transcript.json').read_text(encoding="utf-8"))

    def test_transcript_merges_aligned_timestamps(self):
        for name, segments in [('mic', [{'start': 2, 'text': '私の発言'}]), ('system', [{'start': 1, 'text': '相手の発言'}])]:
            (self.root / f'{name}_transcript.json').write_text(json.dumps({'segments': segments}))
        with contextlib.redirect_stdout(io.StringIO()):
            notes.generate_transcript(self.root)
            notes.generate_prompt(self.root)
        text = (self.root / 'transcript.md').read_text(encoding="utf-8")
        self.assertLess(text.index('[system] 相手の発言'), text.index('[mic] 私の発言'))
        self.assertIn(text, (self.root / 'chatgpt_prompt.md').read_text(encoding="utf-8"))

    def test_missing_helper_is_actionable(self):
        with patch.dict(os.environ, {'LOCAL_MEETING_NOTES_AUDIO_HELPER': str(self.root / 'missing')}):
            result = macos.invoke('permissions')
        self.assertFalse(result['ok'])
        self.assertIn('録音ヘルパー', result['error'])

    def test_native_permission_failure_never_emits_started_or_complete(self):
        fake = self.root / 'helper.py'
        fake.write_text('import json,sys\nprint(json.dumps({"event":"error","message":"microphone denied"}), flush=True)\nsys.exit(2)\n')
        args = Mock(output_dir=str(self.root), mic_device_id=None, mic_device_index=None, model='base', duration=None, skip_transcribe=True)
        with patch.object(macos, 'invoke', return_value={'ok': True, 'devices': []}), patch.object(macos, 'command', return_value=[sys.executable, str(fake)]), patch.object(notes.sys, 'stdin', io.StringIO('stop\n')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaisesRegex(notes.UserFacingError, 'microphone denied'):
                    notes.run_record_macos(args)
        events = [json.loads(line)['event'] for line in output.getvalue().splitlines()]
        self.assertNotIn('recording_started', events)
        self.assertNotIn('complete', events)

    def test_shutdown_stops_recording_then_waits(self):
        process = Mock()
        process.poll.return_value = None
        stop_server = threading.Event()
        fake_server = Mock()
        fake_server.shutdown.side_effect = stop_server.set
        with patch.object(server, 'RECORDER', process), patch.object(server, 'TRANSCRIBER', None), patch.object(server, 'SERVER', fake_server), patch.object(server, 'SHUTTING_DOWN', False), patch.object(server.sys, 'platform', 'darwin'):
            self.assertTrue(server.shutdown_app()['ok'])
            process.stdin.write.assert_called_once_with('shutdown\n')
            self.assertFalse(stop_server.wait(0.05))
            process.poll.return_value = 0
            self.assertTrue(stop_server.wait(2))

    def test_same_mic_id_is_sent_after_device_order_changes(self):
        with patch.object(server, 'RECORDER', None), patch.object(server, 'TRANSCRIBER', None), patch.object(server, 'SHUTTING_DOWN', False), patch.object(server, 'SETTINGS_PATH', self.root / 'settings.json'), patch.object(server, 'start_backend_process') as start:
            result = server.start_recording('base', 'cpu', 0, -1, str(self.root), 'stable-device-uid')
            self.assertTrue(result['ok'])
            args = start.call_args.args[0]
            self.assertEqual(args[args.index('--mic-device-id') + 1], 'stable-device-uid')


if __name__ == '__main__':
    unittest.main()
