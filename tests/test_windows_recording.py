import queue
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from backend import meeting_notes as notes


class WindowsRecordingTests(unittest.TestCase):
    def test_stop_unblocks_silent_loopback_and_finalizes_wav(self):
        reading = threading.Event()
        interrupted = threading.Event()
        stop = threading.Event()
        errors = queue.Queue()
        stream = Mock()

        def blocking_read(*args, **kwargs):
            reading.set()
            if not interrupted.wait(3):
                raise RuntimeError('read was never interrupted')
            raise OSError('Stream is stopped')

        stream.read.side_effect = blocking_read
        stream.stop_stream.side_effect = interrupted.set
        stream.is_active.return_value = False
        pa = Mock()
        pa.open.return_value = stream
        audio = Mock()
        audio.PyAudio.return_value = pa
        with tempfile.TemporaryDirectory() as folder, patch.object(notes, 'import_audio', return_value=audio):
            worker = threading.Thread(target=notes.record_device, kwargs={
                'stop_event': stop, 'error_queue': errors, 'output_dir': Path(folder),
                'file_name': 'system.wav',
                'device': notes.AudioDevice(1, 'loopback', 2, 48000, True, False),
            })
            worker.start()
            try:
                self.assertTrue(reading.wait(1))
                stop.set()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertTrue(errors.empty())
                stream.stop_stream.assert_called_once()
                stream.close.assert_called_once()
                pa.terminate.assert_called_once()
                with wave.open(str(Path(folder) / 'system.wav'), 'rb') as saved:
                    self.assertEqual(saved.getnchannels(), 2)
                    self.assertEqual(saved.getnframes(), 0)
            finally:
                stop.set()
                interrupted.set()
                worker.join(3)

    def test_read_failure_is_reported_without_stop(self):
        stream = Mock()
        stream.read.side_effect = OSError('device disconnected')
        stream.is_active.return_value = False
        audio = Mock()
        audio.PyAudio.return_value.open.return_value = stream
        errors = queue.Queue()
        with tempfile.TemporaryDirectory() as folder, patch.object(notes, 'import_audio', return_value=audio):
            notes.record_device(
                stop_event=threading.Event(), error_queue=errors, output_dir=Path(folder),
                file_name='mic.wav', device=notes.AudioDevice(1, 'microphone', 1, 48000, False, True),
            )
        self.assertEqual(errors.get_nowait(), 'mic.wav: device disconnected')
        stream.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
