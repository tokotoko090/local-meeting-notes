"""Local-only UI fixtures; never records, transcribes, opens files, or alters settings.

Build the frontend first, then run this server and visit http://127.0.0.1:8877/.
Use /?scenario=complete to reset a scenario before a fresh page load.
"""
import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ('idle', 'starting', 'recording', 'processing', 'complete', 'error', 'closing', 'loading', 'empty', 'long', 'windows', 'windows_saved', 'prompt_long', 'prompt_read_error', 'prompt_save_error', 'settings_error')
MODELS = [('base', '軽量・速度優先'), ('small', '速度と精度のバランス'), ('medium', '精度重視'), ('large-v3', '高精度・処理負荷大'), ('large-v3-turbo', '高精度と速度の両立（標準）')]
DEFAULT_TEMPLATE = '以下の文字起こしから日本語の議事録を作成してください。\n決定事項と担当者ごとの次のアクションを整理してください。'
DEFAULT_PROMPT = DEFAULT_TEMPLATE + '\n\n# 文字起こし\n\n## マイク\n[00:00] 公開日は来月十五日です。\n\n## PC音声\n[00:03] 田中さんが画面を確認します。'
OUTPUT = '/Users/demo/Documents/Meeting Notes/2026-09-18_プロジェクト定例会議'
LONG_OUTPUT = '/Users/demo/Documents/会議の記録と共有資料/クライアントとの共同プロジェクト/次年度の事業計画に関する検討会議/2026-09-18_非常に長い会議名と保存先フォルダの表示確認'


class Fixtures:
    def __init__(self, scenario):
        self.lock = threading.RLock()
        self.counter = 0
        self.reset(scenario)

    def emit(self, event, **data):
        self.counter += 1
        self.events.append({'id': self.counter, 'event': event, **data})

    def reset(self, scenario):
        if scenario not in SCENARIOS:
            raise ValueError('Unknown scenario')
        with self.lock:
            self.scenario = scenario
            self.events = []
            self.pending = []
            self.output = LONG_OUTPUT if scenario == 'long' else OUTPUT
            self.output_root = ''
            self.closing = False
            self.prompt_template = DEFAULT_TEMPLATE
            self.prompt_text = DEFAULT_PROMPT
            self.copied_text = None
            self.calls = []
            self.monitoring = False
            self.levels_stale = False
            self.monitor_error = None
            self.model = "small" if scenario == "windows_saved" else None
            self.transcribe_device = "cpu" if scenario == "windows_saved" else None
            self.fail_settings = scenario == 'settings_error'
            self.fail_read = scenario == 'prompt_read_error'
            self.fail_save = scenario == 'prompt_save_error'
            self.fail_copy = False
            self.delay_save_ms = 0
            if scenario == 'prompt_long':
                self.prompt_text += '\n\n' + ('## 詳細議事録\n- 担当者: 田中さん\n- 確認事項: 日本語の長い文章が折り返され、編集内容が失われないことを確認します。\n' * 30)
            self.busy = False
            self.recording = False
            self.began = time.monotonic()
            if scenario == 'starting':
                self.emit('recording_starting', message='録音の準備中です。権限の確認画面が表示された場合は許可してください。')
                self.busy = True
            elif scenario in ('recording', 'closing'):
                self.recording_event()
            elif scenario == 'processing':
                self.emit('transcription_started', model='large-v3-turbo', output_dir=self.output)
                self.emit('transcribing', file='mic.wav', message='マイク音声を文字起こししています。')
                self.busy = True
            elif scenario in ('complete', 'long', 'prompt_long', 'prompt_read_error', 'prompt_save_error'):
                self.emit('transcript_generated', output_dir=self.output)
                self.emit('prompt_generated', output_dir=self.output)
                self.emit('complete', output_dir=self.output)
            elif scenario == 'error':
                self.emit('recording_stopped', output_dir=self.output)
                self.emit('error', output_dir=self.output, message='文字起こしに失敗しました。録音は保存されています。メモリ不足の場合は小さいモデルを選んで再実行してください。')

    def recording_event(self):
        self.busy = self.recording = True
        self.emit('recording_started', output_dir=self.output, mic_device='MacBook Airのマイク', system_device='Macのシステム音声')

    def schedule(self, entries):
        now = time.monotonic()
        self.pending = [(now + delay, event, data) for delay, event, data in entries]

    def tick(self):
        with self.lock:
            now = time.monotonic()
            while self.pending and self.pending[0][0] <= now:
                _, event, data = self.pending.pop(0)
                if event == 'recording_started':
                    self.recording_event()
                else:
                    self.emit(event, **data)
                if event == 'complete':
                    self.busy = False

    def process(self):
        self.recording = False
        self.busy = True
        self.emit('recording_stopped', output_dir=self.output)
        self.schedule([
            (0.2, 'transcription_started', {'model': 'large-v3-turbo', 'output_dir': self.output}),
            (0.6, 'transcribing', {'file': 'mic.wav'}),
            (0.8, 'status', {'message': 'large-v3-turboのモデルを準備しています。初回はダウンロードに時間がかかります。'}),
            (2.2, 'transcribing', {'file': 'system.wav'}),
            (3.7, 'transcript_generated', {'output_dir': self.output}),
            (4.0, 'prompt_generated', {'output_dir': self.output}),
            (4.3, 'complete', {'output_dir': self.output}),
        ])


class Handler(BaseHTTPRequestHandler):
    def reply(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        state = self.server.fixtures
        if parsed.path == '/' and 'scenario' in query:
            try:
                state.reset(query['scenario'][0])
            except ValueError as exc:
                return self.reply({'ok': False, 'error': str(exc)}, 400)
        state.tick()
        if state.scenario == 'loading' and parsed.path in ('/api/capabilities', '/api/devices', '/api/settings'):
            time.sleep(12)
        windows = state.scenario.startswith('windows')
        if parsed.path == '/api/capabilities':
            return self.reply({'ok': True, 'platform': 'win32' if windows else 'darwin', 'audio_monitor': windows, 'updates': windows, 'cuda_setup': windows, 'transcribe_devices': ['cpu', 'auto', 'cuda'] if windows else ['mlx'], 'models': [{'id': name, 'label': f'{name} — {label}'} for name, label in MODELS], 'default_model': 'large-v3-turbo', 'default_transcribe_device': 'auto' if windows else 'mlx', 'permissions': {'microphone': 'granted', 'system_audio': 'granted'}})
        if parsed.path == '/api/devices':
            devices = [] if state.scenario == 'empty' else [{'id': 'demo-mic', 'index': 0, 'name': '検証用の非常に長い名前のUSBオーディオインターフェース・会議室マイク入力チャンネル' if state.scenario == 'long' else 'MacBook Airのマイク', 'channels': 1, 'sample_rate': 48000, 'is_input': True, 'is_loopback': False, 'is_default': True, 'kind': 'mic'}, {'id': 'demo-system', 'index': 1, 'name': 'スピーカー (Loopback)' if windows else 'Macのシステム音声', 'channels': 2, 'sample_rate': 48000, 'is_input': False, 'is_loopback': True, 'kind': 'system'}]
            return self.reply({'ok': True, 'devices': devices})
        if parsed.path == '/api/audio-levels':
            active = state.monitoring or state.recording
            return self.reply({'ok': True, 'monitoring': state.monitoring, 'error': state.monitor_error, 'levels': {source: {'rms_dbfs': -18 if source == 'mic' else -8, 'peak_dbfs': -4, 'clipping': source == 'system', 'active': active, 'updated_at': time.time() - (5 if state.levels_stale else 0)} for source in ('mic', 'system')}})
        if parsed.path == '/api/events':
            since = int(query.get('since', ['0'])[0])
            return self.reply({'ok': True, 'events': [event for event in state.events if event['id'] > since]})
        if parsed.path == '/api/settings':
            return self.reply(self.settings())
        if parsed.path == '/api/health':
            return self.reply({'ok': True, 'server_version': 'ui-fixture', 'busy': state.busy, 'recording': state.recording, 'shutting_down': state.closing})
        if parsed.path == '/api/gpu/status':
            return self.reply({'ok': True, 'state': 'setup_available', 'label': 'GPUをセットアップできます', 'runtime_ready': False})
        if parsed.path == '/api/update/check':
            return self.reply({'ok': True, 'current_version': '1.0.0', 'latest_version': '1.1.0', 'update_available': True, 'asset_name': 'Local-Meeting-Notes-Setup.exe', 'asset_size': 104857600})
        if parsed.path == '/__fixture/state':
            return self.reply({'ok': True, 'prompt_template': state.prompt_template, 'prompt_text': state.prompt_text, 'copied_text': state.copied_text, 'calls': state.calls, 'monitoring': state.monitoring})
        if parsed.path == '/__fixture/scenario':
            return self.reply({'ok': True, 'scenario': state.scenario, 'scenarios': SCENARIOS})
        if parsed.path.startswith('/api/'):
            return self.reply({'ok': False, 'error': 'Unknown fixture endpoint'}, 404)
        target = (ROOT / 'dist' / (parsed.path.lstrip('/') or 'index.html')).resolve()
        if not target.is_relative_to((ROOT / 'dist').resolve()):
            return self.reply({'ok': False}, 403)
        if not target.is_file():
            return self.reply({'ok': False, 'error': 'Build frontend first: npm run build'}, 404)
        data = target.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(target)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def settings(self):
        return {'ok': True, 'model': self.server.fixtures.model, 'transcribe_device': self.server.fixtures.transcribe_device, 'prompt_template': self.server.fixtures.prompt_template, 'default_prompt_template': DEFAULT_TEMPLATE, 'output_root': self.server.fixtures.output_root, 'default_output_root': LONG_OUTPUT if self.server.fixtures.scenario == 'long' else '/Users/demo/Documents/Meeting Notes'}

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or '{}')
            state = self.server.fixtures
            with state.lock:
                state.calls.append({'path': self.path, 'body': body})
                if self.path == '/__fixture/config':
                    if 'monitor_error' in body:
                        state.monitor_error = str(body['monitor_error'])
                        state.monitoring = False
                    for key in ('fail_settings', 'fail_read', 'fail_save', 'fail_copy', 'busy', 'levels_stale'):
                        if key in body:
                            setattr(state, key, bool(body[key]))
                    if 'delay_save_ms' in body:
                        state.delay_save_ms = max(0, min(3000, int(body['delay_save_ms'])))
                    if 'prompt_text' in body:
                        state.prompt_text = str(body['prompt_text'])
                elif self.path == '/__fixture/scenario':
                    state.reset(body.get('scenario', 'idle'))
                elif self.path == '/api/audio-monitor/start':
                    state.monitor_error = None
                    state.monitoring = True
                elif self.path == '/api/audio-monitor/stop':
                    state.monitor_error = None
                    state.monitoring = False
                elif self.path == '/api/recording/start':
                    state.emit('recording_starting', message='録音を準備しています。')
                    state.busy = True
                    state.schedule([(1.5, 'recording_started', {})])
                elif self.path in ('/api/recording/stop', '/api/transcribe-existing'):
                    state.process()
                elif self.path in ('/api/output/pick-directory', '/api/output/pick-recording-root'):
                    return self.reply({'ok': True, 'output_dir': state.output})
                elif self.path == '/api/settings':
                    for key in ('model', 'transcribe_device'):
                        if key in body:
                            setattr(state, key, body[key])
                    if 'prompt_template' in body:
                        if state.busy or state.fail_settings:
                            return self.reply({'ok': False, 'error': 'テンプレートを保存できませんでした。再試行してください。'})
                        if not isinstance(body['prompt_template'], str) or not body['prompt_template'].strip():
                            return self.reply({'ok': False, 'error': '空のテンプレートは保存できません。'})
                        state.prompt_template = body['prompt_template']
                    if 'output_root' in body:
                        state.output_root = body['output_root']
                    return self.reply(self.settings())
                elif self.path == '/api/prompt/read':
                    if state.busy or state.fail_read:
                        return self.reply({'ok': False, 'error': 'プロンプトを読み込めませんでした。再試行してください。'})
                    return self.reply({'ok': True, 'text': state.prompt_text})
                elif self.path == '/api/prompt/save':
                    time.sleep(state.delay_save_ms / 1000)
                    if state.busy or state.fail_save:
                        return self.reply({'ok': False, 'saved': False, 'error': 'プロンプトを保存できませんでした。再試行してください。'})
                    if not isinstance(body.get('text'), str) or not body['text'].strip():
                        return self.reply({'ok': False, 'saved': False, 'error': '空のプロンプトは保存できません。'})
                    state.prompt_text = body['text']
                    if body.get('copy'):
                        if state.fail_copy:
                            return self.reply({'ok': False, 'saved': True, 'error': '保存しましたが、コピーできませんでした。'})
                        state.copied_text = state.prompt_text
                    return self.reply({'ok': True, 'saved': True})
                elif self.path == '/api/prompt/copy':
                    if state.fail_copy:
                        return self.reply({'ok': False, 'error': 'コピーできませんでした。'})
                    state.copied_text = state.prompt_text
                elif self.path == '/api/shutdown':
                    state.closing = True
                    state.emit('status', message='録音を保存して終了します。')
                elif self.path == '/api/gpu/setup':
                    return self.reply({'ok': True, 'state': 'available', 'label': 'GPUを利用できます', 'runtime_ready': True})
                elif self.path == '/api/update/download':
                    return self.reply({'ok': True, 'latest_version': '1.1.0', 'installer_path': 'C:\\Demo\\Local-Meeting-Notes-Setup.exe'})
                elif self.path not in ('/api/prompt/copy', '/api/output/open', '/api/update/install'):
                    return self.reply({'ok': False, 'error': 'Unknown fixture endpoint'}, 404)
            self.reply({'ok': True, 'output_dir': state.output})
        except (ValueError, TypeError) as exc:
            self.reply({'ok': False, 'error': str(exc)}, 400)

    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8877)
    parser.add_argument('--scenario', choices=SCENARIOS, default='idle')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.fixtures = Fixtures(args.scenario)
    print(f'UI fixtures: http://127.0.0.1:{args.port}/?scenario={args.scenario}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
