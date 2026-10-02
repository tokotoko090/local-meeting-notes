import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

_test_root = tempfile.TemporaryDirectory()
os.environ.setdefault('LOCAL_MEETING_NOTES_DATA_ROOT', _test_root.name)
from backend import server
from backend import meeting_notes as notes


class TranscriptionSettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'settings.json'
        target = patch.object(server, 'SETTINGS_PATH', self.path)
        target.start()
        self.addCleanup(target.stop)

    def test_windows_fresh_settings_capability_and_cli_agree_on_turbo_auto(self):
        with patch.object(server.sys, 'platform', 'win32'):
            settings = server.settings_payload()
            capability = server.capabilities()
            self.assertEqual((settings['model'], settings['transcribe_device']), ('large-v3-turbo', 'auto'))
            self.assertEqual((capability['default_model'], capability['default_transcribe_device']), ('large-v3-turbo', 'auto'))
            self.assertIn('large-v3-turbo', [model['id'] for model in capability['models']])
            for argv in (['record'], ['generate', 'test-folder', '--transcribe']):
                parsed = notes.build_parser().parse_args(argv)
                self.assertEqual((parsed.model, parsed.transcribe_device), ('large-v3-turbo', 'auto'))
            self.assertFalse(self.path.exists(), 'Reading defaults must not rewrite user settings')

    def test_saved_base_cpu_stays_unchanged_and_turbo_can_be_persisted(self):
        original = {'model': 'base', 'transcribe_device': 'cpu'}
        self.path.write_text(json.dumps(original), encoding='utf-8')
        before = self.path.read_bytes()
        with patch.object(server.sys, 'platform', 'win32'):
            payload = server.settings_payload()
            self.assertEqual((payload['model'], payload['transcribe_device']), ('base', 'cpu'))
            self.assertEqual(self.path.read_bytes(), before)
            self.assertTrue(server.update_settings({'model': 'large-v3-turbo', 'transcribe_device': 'auto'})['ok'])
            self.assertEqual(server.load_settings(), {'model': 'large-v3-turbo', 'transcribe_device': 'auto'})

    def test_windows_upgrade_retains_saved_choices_and_other_settings(self):
        previous = {'model': 'medium', 'transcribe_device': 'cuda',
                    'output_root': 'C:/recordings', 'prompt_template': '日本語の設定'}
        self.path.write_text(json.dumps(previous), encoding='utf-8')
        with patch.object(server.sys, 'platform', 'win32'):
            self.assertEqual(server.settings_payload()['model'], 'medium')
            self.assertEqual(server.settings_payload()['transcribe_device'], 'cuda')
            self.assertTrue(server.update_settings({'model': 'small', 'transcribe_device': 'cpu'})['ok'])
            restored = server.settings_payload()
            self.assertEqual(restored['model'], 'small')
            self.assertEqual(restored['transcribe_device'], 'cpu')
            self.assertEqual(restored['output_root'], previous['output_root'])
            self.assertEqual(restored['prompt_template'], previous['prompt_template'])

    def test_invalid_choices_do_not_change_file(self):
        with patch.object(server.sys, 'platform', 'win32'):
            server.update_settings({'model': 'small'})
            before = self.path.read_bytes()
            for payload in ({'model': 'SMALL'}, {'transcribe_device': 'mlx'}, {'model': []},
                            {'model': 'medium', 'transcribe_device': 'invalid'}):
                self.assertFalse(server.update_settings(payload)['ok'])
                self.assertEqual(self.path.read_bytes(), before)

    def test_mac_retains_mlx_and_turbo_defaults(self):
        with patch.object(server.sys, 'platform', 'darwin'):
            self.assertEqual(server.settings_payload()['model'], 'large-v3-turbo')
            self.assertEqual(server.settings_payload()['transcribe_device'], 'mlx')
            self.assertFalse(server.update_settings({'transcribe_device': 'cpu'})['ok'])
            self.assertTrue(server.update_settings({'model': 'large-v3', 'transcribe_device': 'mlx'})['ok'])
            self.assertEqual(server.settings_payload()['model'], 'large-v3')

    def test_windows_clipboard_reads_utf8_without_pipeline_line_conversion(self):
        text = '日本語\n\n二行目 😀\n'
        with patch.object(server.sys, 'platform', 'win32'), patch.object(server.subprocess, 'run', return_value=Mock(returncode=0, stderr=b'')) as run:
            self.assertTrue(server.copy_text(text)['ok'])
        args, kwargs = run.call_args
        self.assertIn('[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)', args[0][-1])
        self.assertIn('[Console]::In.ReadToEnd()', args[0][-1])
        self.assertEqual(kwargs['input'], text.encode('utf-8'))
        self.assertNotIn('text', kwargs)


if __name__ == '__main__':
    unittest.main()
