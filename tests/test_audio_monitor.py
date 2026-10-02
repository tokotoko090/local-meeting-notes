import io
import struct
import subprocess
import threading
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend import meeting_notes, server


class AudioMonitorTests(unittest.TestCase):
    def tearDown(self):
        server.MONITORS.clear()
        server.MONITOR_ERROR = None
        server.reset_audio_levels()

    def test_pcm_levels(self):
        self.assertEqual(meeting_notes.measure_audio(b'')['rms_dbfs'], -60)
        self.assertEqual(meeting_notes.measure_audio(b'\x00\x00' * 8)['peak_dbfs'], -60)
        level = meeting_notes.measure_audio(struct.pack('<hh', 16384, -16384))
        self.assertAlmostEqual(level['rms_dbfs'], -6.02)
        self.assertFalse(level['clipping'])
        self.assertTrue(meeting_notes.measure_audio(struct.pack('<h', -32768))['clipping'])

    def test_events_bypass_history_and_expire(self):
        before = list(server.EVENT_HISTORY)
        with patch.object(server, 'log') as log:
            server.emit({'event': 'audio_level', 'source': 'mic', 'active': True,
                         'rms_dbfs': -3, 'peak_dbfs': -1, 'clipping': True})
            self.assertEqual(server.EVENT_HISTORY, before)
            log.assert_not_called()
        self.assertTrue(server.audio_levels_payload()['levels']['mic']['active'])
        with patch.object(server.time, 'time', return_value=server.AUDIO_LEVELS['mic']['updated_at'] + 2):
            level = server.audio_levels_payload()['levels']['mic']
            self.assertFalse(level['active'])
            self.assertEqual(level['peak_dbfs'], -60)

    def test_mac_rejected_without_opening_audio(self):
        with patch.object(server.sys, 'platform', 'darwin'), patch.object(meeting_notes, 'read_devices') as read:
            self.assertFalse(server.start_audio_monitor()['ok'])
            read.assert_not_called()

    def test_partial_spawn_failure_stops_first_worker(self):
        child = MagicMock()
        child.poll.return_value = None
        child.stdout = io.StringIO('')
        child.stderr = io.StringIO('')
        with patch.object(server.sys, 'platform', 'win32'), \
             patch.object(server, 'SHUTTING_DOWN', False), \
             patch.object(server, 'any_process_running', return_value=False), \
             patch.object(meeting_notes, 'read_devices', return_value=[]), \
             patch.object(meeting_notes, 'choose_microphone', return_value=SimpleNamespace(index=1)), \
             patch.object(meeting_notes, 'choose_loopback', return_value=SimpleNamespace(index=2)), \
             patch.object(server.subprocess, 'Popen', side_effect=[child, OSError('spawn failed')]), \
             patch.object(server, 'start_backend_process') as snapshot_worker:
            result = server.start_audio_monitor()
        self.assertFalse(result['ok'])
        self.assertEqual(server.MONITORS, [])
        child.stdin.write.assert_called_once_with('stop\n')
        child.wait.assert_called()
        snapshot_worker.assert_not_called()

    def test_worker_failure_stops_sibling_and_exposes_error(self):
        children = [MagicMock(), MagicMock()]
        for child in children:
            child.poll.return_value = None
            child.stdout = io.StringIO('')
            child.stderr = io.StringIO('')
        children[0].stdout = io.StringIO('{"event":"error","message":"Microphone unavailable"}\n')
        threads = []
        def thread(**kwargs):
            threads.append(kwargs)
            return MagicMock()
        with patch.object(server.sys, 'platform', 'win32'), \
             patch.object(server, 'SHUTTING_DOWN', False), \
             patch.object(server, 'any_process_running', return_value=False), \
             patch.object(server.subprocess, 'Popen', side_effect=children) as spawn, \
             patch.object(server.threading, 'Thread', side_effect=thread), \
             patch.object(meeting_notes, 'read_devices') as read, \
             patch.object(server, 'log'):
            self.assertTrue(server.start_audio_monitor()['ok'])
            read.assert_not_called()
            self.assertNotIn('--device-index', spawn.call_args_list[0].args[0])
            threads[0]['target'](*threads[0]['args'])
            children[0].poll.return_value = 2
            threads[-1]['target'](*threads[-1]['args'])
        result = server.audio_levels_payload()
        self.assertFalse(result['monitoring'])
        self.assertEqual(result['error'], 'mic: Microphone unavailable')
        children[1].stdin.write.assert_called_once_with('stop\n')
        server.stop_audio_monitor()
        self.assertIsNone(server.audio_levels_payload()['error'])

    def test_monitor_worker_selects_auto_device_by_source(self):
        for source, chooser_name in [('mic', 'choose_microphone'), ('system', 'choose_loopback')]:
            args = meeting_notes.build_parser().parse_args(['record-one', '--monitor-only', '--source', source])
            device = SimpleNamespace(index=7)
            with patch.object(meeting_notes.sys, 'platform', 'win32'), \
                 patch.object(meeting_notes, 'read_devices', return_value=[device]), \
                 patch.object(meeting_notes, chooser_name, return_value=device) as choose, \
                 patch.object(meeting_notes.threading, 'Thread'), \
                 patch.object(meeting_notes, 'record_device') as record:
                self.assertEqual(meeting_notes.run_record_one(args), 0)
                choose.assert_called_once_with([device], None)
                self.assertIsNone(record.call_args.kwargs['output_dir'])
                self.assertEqual(record.call_args.kwargs['source'], source)

    def test_stop_kills_and_reaps_unresponsive_worker(self):
        child = MagicMock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('test', 3), 0]
        child.monitor_readers = []
        server.MONITORS.append(child)
        server.stop_audio_monitor()
        child.kill.assert_called_once()
        self.assertEqual(child.wait.call_count, 2)
        self.assertEqual(server.MONITORS, [])

    def test_monitor_capture_does_not_create_files(self):
        stop = threading.Event()
        stream = MagicMock()
        def capture(*args, **kwargs):
            stop.set()
            return struct.pack('<hh', 1234, -1234)
        stream.read.side_effect = capture
        audio = MagicMock()
        audio.PyAudio.return_value.open.return_value = stream
        device = SimpleNamespace(channels=1, sample_rate=16000, index=1, name='test')
        with patch.object(meeting_notes, 'import_audio', return_value=audio), \
             patch.object(meeting_notes, 'create_wave') as wave, \
             patch.object(meeting_notes, 'write_log') as log, \
             patch.object(meeting_notes, 'emit') as emit:
            meeting_notes.record_device(stop_event=stop, error_queue=queue.Queue(),
                output_dir=None, file_name='monitor.wav', device=device, source='mic')
        wave.assert_not_called()
        log.assert_not_called()
        self.assertTrue(any(call.kwargs.get('active') for call in emit.call_args_list))
        stream.close.assert_called_once()
        audio.PyAudio.return_value.terminate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
