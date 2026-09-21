const { app, BrowserWindow, dialog, shell, Menu, nativeTheme } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const readline = require('node:readline');
const root = path.resolve(__dirname, '..');
let mainWindow;
let backend;
let backendURL;
let quitting = false;
let backendStopped = false;
let logStream;

function log(text) { logStream?.write(`${new Date().toISOString()} ${text}\n`); }
function startBackend() {
  return new Promise((resolve, reject) => {
    const binary = app.isPackaged
      ? path.join(process.resourcesPath, 'backend', 'LocalMeetingNotesBackend')
      : path.join(root, process.platform === 'darwin' ? '.venv-mlx' : '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
    const args = app.isPackaged ? [] : [path.join(root, 'app_launcher.py')];
    backend = spawn(binary, args, {
      cwd: app.getPath('userData'), stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
      env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8',
        LOCAL_MEETING_NOTES_MANAGED: '1', LOCAL_MEETING_NOTES_OPEN_BROWSER: '0',
        LOCAL_MEETING_NOTES_PORT: process.env.VITE_DEV_SERVER_URL ? '8765' : '0',
        LOCAL_MEETING_NOTES_AUDIO_HELPER: app.isPackaged
          ? path.join(process.resourcesPath, 'vendor', 'MeetingAudio')
          : path.join(root, 'vendor', 'MeetingAudio'),
        LOCAL_MEETING_NOTES_STATIC_ROOT: app.isPackaged
          ? path.join(process.resourcesPath, 'dist') : path.join(root, 'dist') }
    });
    const timeout = setTimeout(() => {
      reject(new Error('ローカル処理の起動がタイムアウトしました。ログを確認してください。'));
      backend.stdin.end();
    }, 30000);
    backend.on('error', error => { backendStopped = true; clearTimeout(timeout); reject(error); });
    backend.stderr.on('data', data => log(data.toString()));
    const lines = readline.createInterface({ input: backend.stdout });
    lines.on('line', async line => {
      log(line);
      let event;
      try { event = JSON.parse(line); } catch { return; }
      if (event.event === 'native_request' && event.command === 'pick-directory') {
        let result;
        try {
          const choice = await dialog.showOpenDialog(mainWindow, {
            title: event.create ? '録音の保存先を選択' : '既存の録音フォルダを選択',
            defaultPath: event.initial,
            properties: ['openDirectory', ...(event.create ? ['createDirectory'] : [])]
          });
          result = choice.canceled ? { ok: false, canceled: true } : { ok: true, output_dir: choice.filePaths[0] };
        } catch (error) { result = { ok: false, error: error.message }; }
        if (!backend.stdin.destroyed) backend.stdin.write(JSON.stringify({ id: event.id, result }) + '\n');
        return;
      }
      if (event.event !== 'server_ready') return;
      try {
        const response = await fetch(`${event.url}/api/health`);
        const health = await response.json();
        if (health.pid !== backend.pid || !health.ok) throw new Error('起動したローカルサーバーを確認できません。');
        backendURL = event.url;
        clearTimeout(timeout);
        resolve();
      } catch (error) { clearTimeout(timeout); reject(error); }
    });
    backend.on('exit', (code) => {
      clearTimeout(timeout);
      backendStopped = true;
      if (!backendURL) reject(new Error(`ローカル処理を開始できませんでした (${code})。`));
      else {
        if (!quitting && code !== 0) dialog.showErrorBox('Local Meeting Notes', 'ローカル処理が停止しました。アプリを再起動してください。');
        app.quit();
      }
    });
  });
}
function createWindow() {
  mainWindow = new BrowserWindow({ width: 1040, height: 840, minWidth: 860, minHeight: 640,
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#111816' : '#f5f7f5', show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true } });
  mainWindow.once('ready-to-show', () => mainWindow.show());
  const url = process.env.VITE_DEV_SERVER_URL || backendURL;
  mainWindow.loadURL(url);
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (target.startsWith('https://github.com/tokotoko090/local-meeting-notes/')) shell.openExternal(target);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, target) => {
    if (new URL(target).origin !== new URL(url).origin) event.preventDefault();
  });
  mainWindow.on('close', event => {
    if (!backendStopped) { event.preventDefault(); app.quit(); }
  });
  mainWindow.webContents.on('will-prevent-unload', event => {
    if (quitting) event.preventDefault();
  });
}
nativeTheme.on('updated', () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.setBackgroundColor(nativeTheme.shouldUseDarkColors ? '#111816' : '#f5f7f5');
  }
});
let checkingUnsaved = false;
async function stopBackend() {
  if (quitting || checkingUnsaved) return;
  checkingUnsaved = true;
  try {
    if (mainWindow && !mainWindow.isDestroyed()) {
      const edit = await mainWindow.webContents.executeJavaScript("({ dirty: document.documentElement.dataset.promptDirty === 'true', saving: document.documentElement.dataset.promptSaving === 'true' })");
      if (edit.saving) {
        await dialog.showMessageBox(mainWindow, { type: 'info', message: 'プロンプトを保存しています。', detail: '保存が完了してから終了してください。', buttons: ['戻る'] });
        return;
      }
      if (edit.dirty) {
        const choice = await dialog.showMessageBox(mainWindow, { type: 'question', message: '未保存の変更を破棄して終了しますか？', buttons: ['編集を続ける', '破棄して終了'], defaultId: 0, cancelId: 0 });
        if (choice.response !== 1) return;
      }
    }
  } catch (error) {
    log(`Could not inspect prompt draft: ${error.message}`);
  } finally {
    checkingUnsaved = false;
  }
  quitting = true;
  mainWindow?.setTitle('保存して終了中 — Local Meeting Notes');
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.executeJavaScript("window.dispatchEvent(new Event('meeting-app-closing'));").catch(() => {});
  }
  try {
    if (backendURL) await fetch(`${backendURL}/api/shutdown`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
  } catch (error) { log(error.message); }
  // EOF is also the backend's orderly-shutdown signal; never kill a WAV writer.
  if (backend?.stdin && !backend.stdin.destroyed) backend.stdin.end();
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { mainWindow?.show(); mainWindow?.focus(); });
  app.on('before-quit', event => {
    if (backend && !backendStopped) { event.preventDefault(); void stopBackend(); }
  });
  app.on('window-all-closed', () => app.quit());
  app.whenReady().then(async () => {
    fs.mkdirSync(app.getPath('userData'), { recursive: true });
    logStream = fs.createWriteStream(path.join(app.getPath('userData'), 'electron.log'), { flags: 'a' });
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: app.name, submenu: [{ role: 'about' }, { type: 'separator' }, { role: 'quit' }] },
      { label: '編集', submenu: [{ role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
      { label: 'ウインドウ', submenu: [{ role: 'minimize' }, { role: 'zoom' }] }
    ]));
    try { await startBackend(); createWindow(); }
    catch (error) { dialog.showErrorBox('起動できませんでした', error.message); app.quit(); }
  });
}
