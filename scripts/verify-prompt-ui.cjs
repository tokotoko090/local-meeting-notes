/** Synthetic prompt-editing integration checks; start ui-fixture-server.py first. */
const { app, BrowserWindow, nativeTheme } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const output = path.resolve(__dirname, '../build/prompt-ui-validation');
const origin = 'http://127.0.0.1:8877';
fs.mkdirSync(output, { recursive: true });
app.setPath('userData', path.join(output, 'electron-profile'));
let win;
const reports = [];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const js = (fn, ...args) => win.webContents.executeJavaScript(`(${fn.toString()})(...${JSON.stringify(args)})`, true);
async function until(fn, args = [], timeout = 6000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await js(fn, ...args)) return; await sleep(60); }
  throw new Error(`Timed out: ${fn.toString().slice(0, 180)}`);
}
async function api(url, body) {
  return js(async (url, body) => (await fetch(url, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined)).json(), url, body);
}
async function button(label, exact = false) {
  const point = await js((label, exact) => {
    const modal = document.querySelector('dialog[open]');
    const e = [...(modal || document).querySelectorAll('button')].find(e => !e.disabled && e.getClientRects().length && (exact ? (e.getAttribute('aria-label') || e.textContent).trim() === label : (e.getAttribute('aria-label') || e.textContent).includes(label)));
    if (!e) return null;
    e.scrollIntoView({ block: 'nearest' });
    const r = e.getBoundingClientRect();
    return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
  }, label, exact);
  assert(point, `Enabled button missing: ${label}`);
  // Real pointer events supply browser activation for dialog CloseWatcher behavior.
  win.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, ...point });
  win.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, ...point });
  await js(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function edit(selector, value) {
  assert(await js((selector, value) => {
    const e = document.querySelector(selector); if (!e || e.disabled || e.readOnly) return false;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(e, value);
    e.dispatchEvent(new Event('input', { bubbles: true })); return true;
  }, selector, value), `Editable textarea missing: ${selector}`);
}
async function openScenario(name = 'idle', theme = 'light', width = 1040, height = 840) {
  nativeTheme.themeSource = theme; win.setContentSize(width, height);
  await win.loadURL(`${origin}/?scenario=${name}`);
  await until(() => !!document.querySelector('main'));
  await sleep(850);
}
async function shot(name) {
  await js(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await sleep(80);
  fs.writeFileSync(path.join(output, name + '.png'), (await win.webContents.capturePage()).toPNG());
}
async function check(name, fn) {
  try { const details = await fn(); reports.push({ name, ok: true, details }); console.log(`PASS ${name}`); }
  catch (error) { reports.push({ name, ok: false, error: error.stack }); console.error(`FAIL ${name}: ${error.message}`); await shot('failure-' + name).catch(() => {}); }
}
const templateSelector = '#prompt-template';
const promptSelector = '#prompt-text';
async function openSettings() { await button('設定', true); await until(selector => !!document.querySelector(selector), [templateSelector]); }
async function openPrompt() { await button('プロンプトを編集'); await until(selector => !!document.querySelector(selector) && !document.querySelector(selector).disabled, [promptSelector]); }
async function value(selector) { return js(selector => document.querySelector(selector)?.value, selector); }
async function closeDialog() {
  win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Escape' });
  win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Escape' });
  await sleep(100);
}
async function settingsFlow() {
  await openScenario(); await openSettings();
  const original = await value(templateSelector);
  const custom = '# 議事録の指示\n決定事項を箇条書きでまとめ、担当者と期限を表にしてください。';
  await edit(templateSelector, custom);
  await until(() => document.documentElement.dataset.promptDirty === 'true');
  await button('プロンプト設定を保存');
  await until(text => document.body.innerText.includes(text), ['保存しました']);
  assert.equal((await api('/__fixture/state')).prompt_template, custom);
  await until(() => document.documentElement.dataset.promptDirty === 'false');
  await closeDialog(); await openSettings(); assert.equal(await value(templateSelector), custom, 'Saved template persists when reopened');
  await button('標準に戻す'); assert.equal(await value(templateSelector), original, 'Reset restores default draft');
  await button('プロンプト設定を保存'); assert.equal((await api('/__fixture/state')).prompt_template, original);
  await edit(templateSelector, custom + '\n未保存の変更');
  await closeDialog(); await button('編集に戻る');
  assert.equal(await value(templateSelector), custom + '\n未保存の変更', 'Cancel dismissal retains draft');
  await closeDialog(); await button('変更を破棄して閉じる'); await openSettings();
  assert.equal(await value(templateSelector), original, 'Discard does not persist draft');
  await api('/__fixture/config', { fail_settings: true }); await edit(templateSelector, custom); await button('プロンプト設定を保存');
  await until(() => document.body.innerText.includes('保存できません'));
  assert.equal(await value(templateSelector), custom, 'Failed template save retains draft');
  assert.equal((await api('/__fixture/state')).prompt_template, original, 'Failed template save preserves original');
  await api('/__fixture/config', { fail_settings: false }); await button('プロンプト設定を保存');
  await until(text => document.body.innerText.includes(text), ['保存しました']);
  return { persisted: true, reset: true, discardProtected: true, failedDraftRetained: true };
}
async function promptFlow() {
  await openScenario('complete'); await openPrompt();
  const original = await value(promptSelector);
  const custom = '# 編集済みプロンプト\n\n重要な決定事項だけを抽出してください。\n\n' + original;
  await edit(promptSelector, custom);
  await until(() => document.documentElement.dataset.promptDirty === 'true');
  // Hold this request until the saving-state assertions finish. A timed fixture
  // delay can expire before Windows delivers the pointer/frame acknowledgments.
  await js(() => {
    const originalFetch = window.fetch;
    let release;
    const pending = new Promise(resolve => { release = resolve; });
    window.__releasePromptSave = () => { window.fetch = originalFetch; release(); };
    window.fetch = async (...args) => {
      if (String(args[0]).endsWith('/api/prompt/save')) await pending;
      return originalFetch.apply(window, args);
    };
  });
  try {
    await button('保存してコピー');
    await until(() => document.documentElement.dataset.promptSaving === 'true');
    await closeDialog();
    assert(await js(() => !!document.querySelector('dialog[open]')), 'Cannot dismiss while saving');
    assert(await js(() => document.documentElement.dataset.promptSaving === 'true'), 'Escape must not finish the pending save');
  } finally {
    await js(() => { window.__releasePromptSave(); delete window.__releasePromptSave; });
  }
  await until(() => document.body.innerText.includes('コピーしました'));
  await until(() => document.documentElement.dataset.promptSaving === 'false');
  let state = await api('/__fixture/state'); assert.equal(state.prompt_text, custom); assert.equal(state.copied_text, custom, 'Copies exact edited text');
  await closeDialog(); await openPrompt(); assert.equal(await value(promptSelector), custom);
  await edit(promptSelector, custom + '\n破棄する草稿');
  await closeDialog(); await button('編集に戻る'); assert.equal(await value(promptSelector), custom + '\n破棄する草稿');
  await closeDialog(); await button('変更を破棄して閉じる'); await openPrompt(); assert.equal(await value(promptSelector), custom);
  const failedDraft = custom + '\n失敗時も保持する草稿';
  await edit(promptSelector, failedDraft); await api('/__fixture/config', { fail_save: true }); await button('保存してコピー');
  await until(() => document.body.innerText.includes('保存できません'));
  state = await api('/__fixture/state'); assert.equal(state.prompt_text, custom); assert.equal(await value(promptSelector), failedDraft);
  await api('/__fixture/config', { fail_save: false, fail_copy: true }); await button('保存してコピー');
  await until(() => document.body.innerText.includes('コピーできません'));
  state = await api('/__fixture/state'); assert.equal(state.prompt_text, failedDraft); assert.equal(state.copied_text, custom); assert.equal(await value(promptSelector), failedDraft);
  await api('/__fixture/config', { fail_copy: false }); await button('保存してコピー');
  await until(() => document.body.innerText.includes('コピーしました'));
  assert.equal((await api('/__fixture/state')).copied_text, failedDraft);
  return { exactCopy: true, savedCopyFailureDistinguished: true, draftsPreserved: true };
}
app.whenReady().then(async () => {
  win = new BrowserWindow({ show: false, width: 1040, height: 840, useContentSize: true, webPreferences: { contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
  // Scenario navigation deliberately discards synthetic state after a failed check.
  win.webContents.on('will-prevent-unload', event => event.preventDefault());
  await check('settings-edit-save-reset-cancel-failure', settingsFlow);
  await check('result-edit-save-copy-cancel-failures', promptFlow);
  await check('existing-prompt-and-save-only', async () => {
    await openScenario(); await button('保存済み音声'); await button('フォルダを選択');
    await until(() => [...document.querySelectorAll('button')].some(e => e.textContent.includes('保存済みプロンプトを編集') && !e.disabled));
    await button('保存済みプロンプトを編集'); await until(selector => !!document.querySelector(selector) && !document.querySelector(selector).disabled, [promptSelector]);
    const custom = '# 保存済み音声から編集\n担当者を一覧にしてください。';
    await edit(promptSelector, custom); await button('保存', true);
    await until(() => document.body.innerText.includes('保存しました'));
    const state = await api('/__fixture/state'); assert.equal(state.prompt_text, custom); assert.equal(state.copied_text, null, 'Save-only does not copy');
    assert(!state.calls.some(call => call.path === '/api/transcribe-existing'), 'Editing never retranscribes');
    await closeDialog();
    assert(await js(() => (document.activeElement.textContent || '').includes('保存済みプロンプトを編集')), 'Focus restores to existing editor trigger');
  });
  await check('read-failure-no-overwrite', async () => {
    await openScenario('prompt_read_error'); await button('プロンプトを編集');
    await until(() => document.body.innerText.includes('読み込めません'));
    assert(await js(selector => document.querySelector(selector).disabled, promptSelector));
    assert(await js(() => [...document.querySelectorAll('dialog[open] button')].filter(e => e.textContent.trim().startsWith('保存')).every(e => e.disabled)));
    const state = await api('/__fixture/state'); assert(!state.calls.some(call => call.path === '/api/prompt/save'));
    await shot('read-failure'); await closeDialog();
  });
  await check('busy-template-locked', async () => {
    await openScenario('processing'); await openSettings();
    assert(await js(selector => document.querySelector(selector).disabled, templateSelector));
    assert(await js(() => [...document.querySelectorAll('button')].filter(e => e.textContent.includes('プロンプト設定を保存')).every(e => e.disabled)));
    await shot('busy-settings');
  });
  for (const theme of ['light', 'dark']) for (const width of [1040, 860]) {
    await check(`${theme}-${width}-long-prompt`, async () => {
      await openScenario('prompt_long', theme, width, width === 860 ? 640 : 840); await openPrompt();
      const metrics = await js(() => { const d = document.querySelector('dialog[open]'); const e = d.querySelector('textarea'); return { width: innerWidth, scrollWidth: document.documentElement.scrollWidth, dialogRight: d.getBoundingClientRect().right, textareaHeight: e.clientHeight, textareaScroll: e.scrollHeight, focused: d.contains(document.activeElement) }; });
      assert(metrics.scrollWidth <= metrics.width + 1, 'No horizontal overflow'); assert(metrics.dialogRight <= metrics.width + 1, 'Dialog fits window'); assert(metrics.textareaScroll > metrics.textareaHeight, 'Long markdown scrolls inside editor'); assert(metrics.focused, 'Focus enters editor');
      await shot(`${theme}-${width}-long-prompt`);
      for (let index = 0; index < 10; index++) {
        win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Tab' });
        win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Tab' });
        await sleep(15);
        assert(await js(() => document.querySelector('dialog[open]').contains(document.activeElement)), 'Prompt editor keeps keyboard focus inside');
      }
      await closeDialog();
      assert(await js(() => document.activeElement.textContent.includes('プロンプトを編集')), 'Clean editor dismissal restores trigger focus');
      return metrics;
    });
    await check(`${theme}-${width}-template-settings`, async () => { await openScenario('idle', theme, width, width === 860 ? 640 : 840); await openSettings(); await js(selector => document.querySelector(selector).scrollIntoView({ block: 'center' }), templateSelector); await shot(`${theme}-${width}-template-settings`); });
  }
}).catch(error => reports.push({ name: 'runner', ok: false, error: error.stack })).finally(() => {
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(reports, null, 2));
  console.log(`${reports.filter(r => r.ok).length}/${reports.length} checks passed`);
  if (win && !win.isDestroyed()) win.destroy(); app.exit(reports.some(r => !r.ok) ? 1 : 0);
});
