/** Compiled UI integration tests against synthetic ui-fixture-server.py only.
 * Run: node_modules/.bin/electron scripts/verify-ui.cjs
 * Uses Electron's real Chromium renderer; never touches audio or user data.
 */
const { app, BrowserWindow, nativeTheme } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const output = path.resolve(__dirname, '../build/ui-validation');
const origin = 'http://127.0.0.1:8877';
fs.mkdirSync(output, { recursive: true });
app.setPath('userData', path.join(output, 'electron-profile'));
const reports = [];
let win;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const js = (fn, ...args) => win.webContents.executeJavaScript(`(${fn.toString()})(...${JSON.stringify(args)})`, true);
async function until(fn, args = [], timeout = 10000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await js(fn, ...args)) return; await sleep(80); }
  throw new Error(`Timed out: ${fn.toString().slice(0, 180)}`);
}
async function button(text) {
  const result = await js(text => {
    const scope = document.querySelector('dialog[open],[role=dialog]:not(dialog)') || document;
    const found = [...scope.querySelectorAll('button')].find(e => !e.disabled && e.getClientRects().length && ((e.getAttribute('aria-label') || e.textContent).trim().includes(text)));
    if (!found) return false;
    found.focus(); found.click(); return true;
  }, text);
  assert(result, `Enabled button missing: ${text}`);
}
async function scenario(name, width = 1040, height = 840, theme = 'light') {
  nativeTheme.themeSource = theme;
  win.setContentSize(width, height);
  await win.loadURL(`${origin}/?scenario=${name}`);
  await until(() => !!document.querySelector('main'));
  if (name !== 'loading') {
    await until(() => !!document.querySelector('#model')?.options.length || document.body.innerText.includes('Apple Silicon') || !!document.querySelector('[role=tab]'));
    await sleep(850); // Allow the real event polling interval to publish the fixture state.
    const statusPatterns = { starting: '準備中|録音を準備', recording: '録音中|会話を録音', processing: '文字起こし中|処理中|文字起こししています', complete: '完了|文字起こしができました', error: 'エラー|失敗|完了できません' };
    if (statusPatterns[name]) await until(pattern => new RegExp(pattern).test(document.body.innerText), [statusPatterns[name]]);
  }
}
async function capture(name) {
  // DOM assertions can pass before Chromium commits the next compositor frame.
  await js(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await sleep(80);
  const image = await win.webContents.capturePage();
  fs.writeFileSync(path.join(output, name + '.png'), image.toPNG());
}
async function check(name, fn) {
  try { const details = await fn(); reports.push({ name, ok: true, details }); console.log(`PASS ${name}`); }
  catch (error) { reports.push({ name, ok: false, error: error.stack }); console.error(`FAIL ${name}: ${error.message}`); await capture('failure-' + name.replace(/[^a-z0-9-]/gi, '-')).catch(() => {}); }
}
async function layoutReport() {
  return js(() => {
    const controls = [...document.querySelectorAll('button,input,select,[role=tab]')].filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
    const describe = e => ({ text: (e.getAttribute('aria-label') || e.textContent || e.id).trim().slice(0, 75), width: Math.round(e.getBoundingClientRect().width), height: Math.round(e.getBoundingClientRect().height) });
    const decorativeText = ['会話を、次のアクションへ', '会議の記録を、シンプルに', 'YOUR LOCAL WORKSPACE', 'PREFERENCES', 'READY TO USE', 'GETTING READY', 'TRANSCRIBING'].filter(text => document.body.innerText.includes(text));
    const out = controls.filter(e => { const r = e.getBoundingClientRect(); return r.left < -1 || r.right > innerWidth + 1; });
    const small = controls.filter(e => { const r = e.getBoundingClientRect(); return r.width < 24 || r.height < 24; });
    return { decorativeText, width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth, horizontalOutliers: out.map(describe), undersizedTargets: small.map(describe), dark: matchMedia('(prefers-color-scheme: dark)').matches, background: getComputedStyle(document.body).backgroundColor, text: getComputedStyle(document.body).color };
  });
}
async function interactions(theme) {
  await scenario('idle', 1040, 840, theme);
  await button('設定');
  await until(() => !!document.querySelector('dialog[open],[role=dialog]:not(dialog)'));
  assert(await js(() => document.querySelector('dialog[open],[role=dialog]:not(dialog)').contains(document.activeElement)), 'Settings receives focus');
  // Move real Chromium keyboard focus through the dialog in both directions.
  for (let i = 0; i < 22; i++) {
    win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Tab' });
    win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Tab' });
    await sleep(15);
    assert(await js(() => document.querySelector('dialog[open],[role=dialog]:not(dialog)').contains(document.activeElement)), 'Focus must remain inside settings');
  }
  win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Escape' });
  win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Escape' });
  await until(() => !document.querySelector('dialog[open],[role=dialog]:not(dialog)'));
  assert(await js(() => (document.activeElement.getAttribute('aria-label') || document.activeElement.textContent).includes('設定')), 'Escape restores settings trigger focus');
  const tabs = await js(() => [...document.querySelectorAll('[role=tab]')].map(e => e.textContent.trim()));
  assert(tabs.length >= 2, 'Recording and existing-folder tabs available');
  await js(() => document.querySelector('[role=tab]').focus());
  win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Right' });
  win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Right' });
  await until(() => document.querySelectorAll('[role=tab]')[1]?.getAttribute('aria-selected') === 'true');
  assert(await js(() => /上書き/.test(document.body.innerText)), 'Existing-folder overwrite warning visible');
  win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Left' });
  win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Left' });
  await until(() => document.querySelector('[role=tab]')?.getAttribute('aria-selected') === 'true');
  await js(() => { const e = document.querySelector('#model'); e.value = 'medium'; e.dispatchEvent(new Event('change', { bubbles: true })); });
  await button('設定');
  await button('再確認');
  win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Escape' });
  win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Escape' });
  await sleep(180);
  assert.equal(await js(() => document.querySelector('#model').value), 'medium', 'Capabilities refresh preserves selected model');
  await button('録音を開始');
  await until(() => document.body.innerText.includes('録音中'));
  assert(await js(() => !document.querySelector('#model') || document.querySelector('#model').disabled), 'Model locked while recording');
  await button('録音を停止');
  await sleep(1700);
  assert(await js(() => document.querySelector('.process-steps li.current')?.textContent.includes('マイク')), 'Model status must not move progress backward from microphone');
  await until(() => document.body.innerText.includes('完了'), [], 10000);
  await button('コピー');
  await until(() => document.body.innerText.includes('コピーしました'));
  await capture(theme + '-flow-complete-copy');
  await button('保存して終了');
  await until(() => /終了中/.test(document.body.innerText));
  await capture(theme + '-closing');
  return { tabs, modelRetained: true, focusRestored: true, flowCompleted: true };
}
app.whenReady().then(async () => {
  win = new BrowserWindow({ show: false, width: 1040, height: 840, useContentSize: true, webPreferences: { contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
  win.webContents.on('console-message', (_event, level, message) => { if (level >= 3) console.error('renderer:', message); });
  for (const theme of ['light', 'dark']) for (const [width, height] of [[1040,840], [860,640], [1440,900], [390,844]]) {
    for (const state of ['idle', 'starting', 'recording', 'processing', 'complete', 'error', 'loading', 'empty', 'long', 'windows']) {
      await check(`${theme}-${width}-${state}`, async () => {
        await scenario(state, width, height, theme);
        const result = await layoutReport();
        await capture(`${theme}-${width}-${state}`);
        assert.equal(result.dark, theme === 'dark', 'OS theme applied');
        assert.equal(result.decorativeText.length, 0, 'No decorative slogans');
        assert(result.scrollWidth <= result.width + 1, `Horizontal overflow ${result.scrollWidth}/${result.width}`);
        assert.equal(result.horizontalOutliers.length, 0, `Controls outside viewport: ${JSON.stringify(result.horizontalOutliers)}`);
        assert.equal(result.undersizedTargets.length, 0, `Targets below24px: ${JSON.stringify(result.undersizedTargets)}`);
        if (['starting','recording','processing'].includes(state)) assert(await js(() => !document.querySelector('#model') || document.querySelector('#model').disabled), 'Busy model selection locked');
        if (state === 'empty') assert(await js(() => [...document.querySelectorAll('button')].filter(e => e.textContent.includes('録音を開始')).every(e => e.disabled)), 'No microphone prevents recording');
        if (state !== 'windows' && state !== 'loading') assert(await js(() => !document.querySelector('#transcribe-device,#model-device')), 'Mac has no processing-device picker');
        return result;
      });
    }
  }
  for (const theme of ['light', 'dark']) {
    await check(`${theme}-standard-window-primary-action`, async () => {
      await scenario('idle', 1040, 840, theme);
      win.setSize(1040, 840); await sleep(100);
      const result = await js(() => {
        const control = [...document.querySelectorAll('button')].find(e => e.textContent.includes('録音を開始'));
        if (!control) return null;
        const rect = control.getBoundingClientRect();
        return { top: rect.top, bottom: rect.bottom, viewportHeight: innerHeight, visible: rect.top >= 0 && rect.bottom <= innerHeight };
      });
      await capture(`${theme}-standard-window-primary-action`);
      assert(result?.visible, `Primary action outside standard window: ${JSON.stringify(result)}`);
      return result;
    });
    for (const [width, height] of [[860,640], [390,844]]) {
      await check(`${theme}-${width}-settings`, async () => {
        await scenario('idle', width, height, theme); await button('設定');
        await until(() => !!document.querySelector('dialog[open]'));
        await capture(`${theme}-${width}-settings`);
        const result = await layoutReport();
        assert.equal(result.horizontalOutliers.length, 0, 'Dialog controls fit horizontally');
        assert.equal(result.decorativeText.length, 0, 'No decorative settings headings');
        assert.equal(result.undersizedTargets.length, 0, 'Dialog target sizes');
        return result;
      });
      await check(`${theme}-${width}-existing`, async () => {
        await scenario('idle', width, height, theme); await button('保存済み音声');
        await until(() => /上書き/.test(document.body.innerText));
        await capture(`${theme}-${width}-existing`);
        const result = await layoutReport();
        assert(result.scrollWidth <= result.width + 1, 'Existing tab fits horizontally');
        return result;
      });
    }
    await check(`${theme}-keyboard-and-mock-flow`, () => interactions(theme));
  }
  await check('windows-features', async () => {
    await scenario('windows'); await button('設定');
    const text = await js(() => document.body.innerText);
    assert(/CUDA/.test(text), 'CUDA setup retained'); assert(/アップデート|更新/.test(text), 'Update controls retained');
    assert(await js(() => !!document.querySelector('#transcribe-device,#model-device')), 'Windows device selection retained');
    await capture('windows-settings');
  });
  await check('windows-meter-and-turbo', async () => {
    await scenario('windows');
    assert.equal(await js(() => document.querySelector('#model').value), 'large-v3-turbo');
    assert.equal(await js(() => document.querySelectorAll('[role=meter]').length), 2);
    let fixture = await (await fetch(`${origin}/__fixture/state`)).json();
    assert(!fixture.calls.some(c => c.path === '/api/audio-monitor/start'), 'No automatic capture');
    await button('入力テスト');
    await until(() => document.querySelector('[role=meter]')?.getAttribute('aria-valuenow') === '-18');
    assert(await js(() => document.body.innerText.includes('クリッピング')));
    await fetch(`${origin}/__fixture/config`, { method: 'POST', body: JSON.stringify({ monitor_error: '検証用デバイスの開始に失敗しました。' }) });
    await until(() => document.body.innerText.includes('検証用デバイスの開始に失敗しました。'));
    assert(await js(() => [...document.querySelectorAll('[role=meter]')].every(e => e.getAttribute('aria-valuenow') === '-60')));
    await button('入力テスト');
    await fetch(`${origin}/__fixture/config`, { method: 'POST', body: JSON.stringify({ levels_stale: true }) });
    await until(() => [...document.querySelectorAll('[role=meter]')].every(e => e.getAttribute('aria-valuenow') === '-60'));
    await fetch(`${origin}/__fixture/config`, { method: 'POST', body: JSON.stringify({ levels_stale: false }) });
    await js(() => { const e = document.querySelector('#mic-device'); e.value = ''; e.dispatchEvent(new Event('change', { bubbles: true })); });
    await until(() => [...document.querySelectorAll('button')].some(e => e.textContent === '入力テスト' && !e.disabled));
    await button('入力テスト'); await button('設定');
    await until(async () => !(await (await fetch('/__fixture/state')).json()).monitoring);
    assert.equal(await js(() => document.querySelector('#transcribe-device,#model-device').value), 'auto');
    await scenario('windows_saved');
    assert.equal(await js(() => document.querySelector('#model').value), 'small');
    await button('設定');
    assert.equal(await js(() => document.querySelector('#transcribe-device,#model-device').value), 'cpu');
    await scenario('windows');
    await button('入力テスト'); await button('保存済み音声');
    await until(async () => !(await (await fetch('/__fixture/state')).json()).monitoring);
    await button('新しく録音'); await button('入力テスト'); await button('録音を開始');
    await until(() => document.body.innerText.includes('会話を録音しています'));
    assert.equal(await js(() => document.querySelectorAll('[role=meter]').length), 2);
    fixture = await (await fetch(`${origin}/__fixture/state`)).json();
    const recordIndex = fixture.calls.findIndex(c => c.path === '/api/recording/start');
    assert.equal(fixture.calls[recordIndex - 1].path, '/api/audio-monitor/stop');
    assert.equal(fixture.calls[recordIndex].body.model, 'large-v3-turbo');
    assert.equal(fixture.calls[recordIndex].body.transcribeDevice, 'auto');
    await capture('windows-recording-meters');
    await scenario('idle');
    assert.equal(await js(() => document.querySelectorAll('[role=meter]').length), 0, 'Mac has no meter');
    fixture = await (await fetch(`${origin}/__fixture/state`)).json();
    assert(!fixture.calls.some(c => c.path.startsWith('/api/audio-monitor')), 'Mac never invokes monitoring');
  });
}).catch(error => reports.push({ name: 'runner', ok: false, error: error.stack })).finally(() => {
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(reports, null, 2));
  console.log(`${reports.filter(r => r.ok).length}/${reports.length} checks passed; ${output}/report.json`);
  if (win && !win.isDestroyed()) win.destroy();
  app.exit(reports.some(r => !r.ok) ? 1 : 0);
});
