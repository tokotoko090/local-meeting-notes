import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

_test_root = tempfile.TemporaryDirectory()
os.environ.setdefault('LOCAL_MEETING_NOTES_DATA_ROOT', _test_root.name)
from backend import server, prompts, meeting_notes


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.recording = self.root / '録音'
        self.recording.mkdir()
        (self.recording / 'mic.wav').write_bytes(b'fixture')
        self.prompt = self.recording / 'chatgpt_prompt.md'
        self.prompt.write_text('previous prompt', encoding='utf-8')
        for target, value in [('SETTINGS_PATH', self.root / 'settings.json'), ('WORK_ROOT', self.root), ('SHUTTING_DOWN', False)]:
            manager = patch.object(server, target, value)
            manager.start()
            self.addCleanup(manager.stop)
        manager = patch.object(server, 'any_process_running', return_value=False)
        manager.start()
        self.addCleanup(manager.stop)

    def test_default_output_matches_legacy_format(self):
        transcript = '# 文字起こし\n\n00:00 [mic] 日本語\n'
        legacy = '''# 依頼

以下は会議の文字起こしです。mic は自分の発言、system はPCから聞こえた相手側や共有音声です。この文字起こしをもとに、議事録を作成してください。

# 出力形式

## 会議概要
*

## 決定事項
*

## 議論内容
*

## ToDo

| 担当 | 内容 | 期限 |
| -- | -- | -- |

## 保留事項
*

## 次回確認事項
*

## 重要発言
*

## 文字起こし全文

''' + transcript + '\n'
        (self.recording / 'transcript.md').write_text(transcript, encoding='utf-8')
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()):
            meeting_notes.generate_prompt(self.recording)
        self.assertEqual(self.prompt.read_text(encoding='utf-8'), legacy)

    def test_settings_persist_and_do_not_rewrite_old_prompt(self):
        template = '  カスタム依頼\n\n箇条書きで\n'
        result = server.update_settings({'prompt_template': template, 'output_root': str(self.root)})
        self.assertTrue(result['ok'])
        self.assertEqual(result['prompt_template'], template)
        self.assertEqual(result['default_prompt_template'], prompts.DEFAULT_PROMPT_TEMPLATE)
        self.assertEqual(json.loads(server.SETTINGS_PATH.read_text(encoding="utf-8"))['prompt_template'], template)
        self.assertEqual(self.prompt.read_text(encoding="utf-8"), 'previous prompt')
        server.update_settings({'output_root': ''})
        self.assertEqual(server.settings_payload()['prompt_template'], template)

    def test_blank_template_rejected_without_changing_settings(self):
        server.update_settings({'prompt_template': 'keep'})
        for invalid in ['', ' \n', None, 123]:
            self.assertFalse(server.update_settings({'prompt_template': invalid})['ok'])
        self.assertEqual(server.settings_payload()['prompt_template'], 'keep')

    def test_snapshot_is_immutable_and_not_command_argument(self):
        server.update_settings({'prompt_template': 'start template'})
        process = Mock()
        with patch.object(server.subprocess, 'Popen', return_value=process) as spawn, patch.object(server.threading, 'Thread'):
            server.start_backend_process(['record'])
        snapshot = Path(spawn.call_args.kwargs['env'][prompts.TEMPLATE_SNAPSHOT_ENV])
        self.assertNotIn('start template', str(spawn.call_args.args))
        server.update_settings({'prompt_template': 'next template'})
        with patch.dict(os.environ, {prompts.TEMPLATE_SNAPSHOT_ENV: str(snapshot)}):
            self.assertEqual(prompts.worker_template(), 'start template')
        self.assertEqual(server.settings_payload()['prompt_template'], 'next template')
        process.stdout = io.StringIO('')
        process.stdin = None
        process.wait.return_value = 0
        with patch.object(server, 'emit'):
            server.stream_process_output(process)
        self.assertFalse(snapshot.exists())

    def test_snapshot_cleanup_when_spawn_fails(self):
        with patch.object(server.subprocess, 'Popen', side_effect=OSError('spawn failed')):
            with self.assertRaises(OSError):
                server.start_backend_process(['record'])
        self.assertEqual(list(self.root.glob('prompt-template-*')), [])

    def test_read_and_save_only_selected_prompt(self):
        self.assertEqual(server.read_prompt(str(self.recording))['text'], 'previous prompt')
        (self.recording / 'transcript.md').write_text('keep transcript')
        value = '  編集内容\n\n'
        self.assertEqual(server.save_prompt(str(self.recording), value), {'ok': True, 'saved': True})
        self.assertEqual(self.prompt.read_text(encoding="utf-8"), value)
        self.assertEqual((self.recording / 'transcript.md').read_text(encoding="utf-8"), 'keep transcript')
        self.assertEqual((self.recording / 'mic.wav').read_bytes(), b'fixture')

    def test_save_failure_preserves_previous_and_never_copies(self):
        with patch.object(prompts.os, 'replace', side_effect=OSError('disk full')), patch.object(server, 'copy_text') as copy:
            result = server.save_prompt(str(self.recording), 'new', copy=True)
        self.assertFalse(result['ok'])
        self.assertFalse(result['saved'])
        self.assertEqual(self.prompt.read_text(encoding="utf-8"), 'previous prompt')
        self.assertEqual(list(self.recording.glob('.*.tmp')), [])
        copy.assert_not_called()

    def test_copy_failure_reports_successful_save(self):
        with patch.object(server, 'copy_text', return_value={'ok': False, 'error': 'clipboard failed'}) as copy:
            result = server.save_prompt(str(self.recording), 'saved content', copy=True)
        self.assertFalse(result['ok'])
        self.assertTrue(result['saved'])
        self.assertEqual(self.prompt.read_text(encoding="utf-8"), 'saved content')
        copy.assert_called_once_with('saved content')

    def test_blank_and_missing_prompt_rejected(self):
        self.assertFalse(server.save_prompt(str(self.recording), ' \n')['saved'])
        self.prompt.unlink()
        self.assertFalse(server.save_prompt(str(self.recording), 'new')['saved'])
        self.assertFalse(self.prompt.exists())
        self.assertFalse(server.read_prompt(str(self.recording))['ok'])

    def test_symlink_escape_rejected(self):
        outside = self.root / 'outside.md'
        outside.write_text('protected')
        self.prompt.unlink()
        try:
            self.prompt.symlink_to(outside)
        except OSError as exc:
            if os.name == 'nt' and getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows symlink privilege is unavailable')
            raise
        self.assertFalse(server.save_prompt(str(self.recording), 'changed')['saved'])
        self.assertFalse(server.read_prompt(str(self.recording))['ok'])
        self.assertEqual(outside.read_text(encoding="utf-8"), 'protected')

    def test_busy_and_shutdown_reject_edit_operations(self):
        for flag in ['busy', 'shutdown']:
            with patch.object(server, 'any_process_running', return_value=flag == 'busy'), patch.object(server, 'SHUTTING_DOWN', flag == 'shutdown'):
                self.assertFalse(server.read_prompt(str(self.recording))['ok'])
                self.assertFalse(server.save_prompt(str(self.recording), 'new')['saved'])
                self.assertFalse(server.update_settings({'prompt_template': 'new'})['ok'])
        self.assertEqual(self.prompt.read_text(encoding="utf-8"), 'previous prompt')
        self.assertFalse(server.SETTINGS_PATH.exists())


if __name__ == '__main__':
    unittest.main()
