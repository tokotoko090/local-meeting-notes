import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import meeting_notes


class WindowsFfmpegTests(unittest.TestCase):
    def test_frozen_uses_sibling_not_extracted_shim_or_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extracted = root / '_MEI' / 'vendor'
            extracted.mkdir(parents=True)
            (extracted / 'ffmpeg.exe').touch()
            vendor = root / 'install' / 'vendor'
            vendor.mkdir(parents=True)
            executable = vendor / 'ffmpeg.exe'
            executable.touch()
            with patch.object(meeting_notes, 'IS_FROZEN', True), \
                 patch.object(meeting_notes, 'RESOURCE_ROOT', extracted.parent), \
                 patch.object(meeting_notes.sys, 'executable', str(vendor.parent / 'LocalMeetingNotes.exe')), \
                 patch.dict(os.environ, {'LOCAL_MEETING_NOTES_DATA_ROOT': str(root / 'data')}), \
                 patch.object(meeting_notes.shutil, 'which') as which:
                self.assertEqual(meeting_notes.resolve_ffmpeg(), str(executable))
                executable.unlink()
                self.assertIsNone(meeting_notes.resolve_ffmpeg())
                which.assert_not_called()

    def test_managed_component_must_stay_inside_component_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component = root / 'components' / 'ffmpeg'
            component.mkdir(parents=True)
            executable = component / '8.1' / 'ffmpeg.exe'
            executable.parent.mkdir()
            executable.touch()
            marker = component / 'current.json'
            marker.write_text(json.dumps({'path': str(executable)}), encoding='utf-8')
            with patch.object(meeting_notes, 'IS_FROZEN', True), \
                 patch.object(meeting_notes.sys, 'executable', str(root / 'app.exe')), \
                 patch.dict(os.environ, {'LOCAL_MEETING_NOTES_DATA_ROOT': str(root)}):
                self.assertEqual(meeting_notes.resolve_ffmpeg(), str(executable))
                outside = root / 'ffmpeg.exe'
                outside.touch()
                marker.write_text(json.dumps({'path': str(outside)}), encoding='utf-8')
                self.assertIsNone(meeting_notes.resolve_ffmpeg())
