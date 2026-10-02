"""Exercise the real HTTP lifecycle without microphone capture or external services."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='meeting-http-') as temp:
    env = {**os.environ, 'LOCAL_MEETING_NOTES_DATA_ROOT': temp,
           'LOCAL_MEETING_NOTES_PORT': '0', 'LOCAL_MEETING_NOTES_MANAGED': '1',
           'LOCAL_MEETING_NOTES_OPEN_BROWSER': '0'}
    process = subprocess.Popen([sys.executable, str(root / 'app_launcher.py')], cwd=temp,
                               env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        ready = json.loads(process.stdout.readline())
        assert ready['event'] == 'server_ready'
        base = ready['url']
        def call(route, body=None, origin=None):
            request = urllib.request.Request(base + route,
                data=json.dumps(body).encode() if body is not None else None,
                headers={**({'Content-Type': 'application/json'} if body is not None else {}),
                         **({'Origin': origin} if origin else {})})
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)
        assert call('/api/health')['pid'] == process.pid
        cap = call('/api/capabilities')
        assert cap['platform'] == 'darwin' and cap['transcribe_devices'] == ['mlx']
        assert cap['default_model'] == 'large-v3-turbo'
        assert [model['id'] for model in cap['models']] == ['base', 'small', 'medium', 'large-v3', 'large-v3-turbo']
        chosen = str(Path(temp).resolve() / '日本語 保存先')
        assert call('/api/settings', {'output_root': chosen})['output_root'] == chosen
        assert call('/api/settings')['output_root'] == chosen
        settings = call('/api/settings')
        assert settings['prompt_template'] == settings['default_prompt_template']
        custom = '# 依頼\n決定事項と担当者を整理してください。\n'
        assert call('/api/settings', {'prompt_template': custom})['prompt_template'] == custom
        assert call('/api/settings')['output_root'] == chosen
        audio = Path(temp) / '保存済み音声'
        audio.mkdir()
        (audio / 'mic.wav').touch()
        prompt = audio / 'chatgpt_prompt.md'
        original = '# 元の依頼\n会議の本文です。\n'
        prompt.write_text(original, encoding='utf-8')
        assert call('/api/prompt/read', {'outputDir': str(audio)})['text'] == original
        assert not call('/api/prompt/save', {'outputDir': str(audio), 'text': ' \n'})['ok']
        assert prompt.read_text(encoding='utf-8') == original
        edited = '# 会議ごとの編集\n担当: 田中\n期限: 金曜日\n'
        assert call('/api/prompt/save', {'outputDir': str(audio), 'text': edited})['ok']
        assert prompt.read_text(encoding='utf-8') == edited
        assert call('/api/settings')['prompt_template'] == custom
        assert call('/api/settings', {'prompt_template': settings['default_prompt_template']})['ok']
        assert prompt.read_text(encoding='utf-8') == edited
        assert not call('/api/update/check')['update_available']
        assert not call('/api/update/download', {})['ok']
        try:
            call('/api/shutdown', {}, origin='https://example.org')
            raise AssertionError('foreign origin was allowed')
        except urllib.error.HTTPError as error:
            assert error.code == 403
        assert call('/api/health')['ok']
        with urllib.request.urlopen(base) as response:
            assert response.status == 200 and b'<div id="root">' in response.read()
        assert call('/api/shutdown', {})['ok']
        process.wait(timeout=10)
        assert process.returncode == 0
        print('HTTP smoke passed: startup, static UI, capabilities, settings, prompt read/save/validation/isolation, update guards, origin guard, clean shutdown')
    finally:
        if process.poll() is None:
            process.stdin.close()
            process.wait(timeout=10)
        process.stdout.close()
        errors = process.stderr.read()
        process.stderr.close()
        if errors: print(errors, file=sys.stderr)
