const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { packager } = require('@electron/packager');
const root = path.resolve(__dirname, '..');
(async () => {
  execFileSync('/bin/bash', [path.join(root, 'scripts/build-mac-icon.sh')], { stdio: 'inherit' });
  const iconOutput = path.join(root, 'build/mac-icon');
  const stage = path.join(root, 'build/mac-stage');
  fs.mkdirSync(path.join(stage, 'electron'), { recursive: true });
  fs.copyFileSync(path.join(root, 'electron/main.cjs'), path.join(stage, 'electron/main.cjs'));
  fs.writeFileSync(path.join(stage, 'package.json'), JSON.stringify({
    name: 'local-meeting-notes', productName: 'Local Meeting Notes', version: require('../package.json').version,
    main: 'electron/main.cjs', description: 'ローカル議事録作成ツール', author: 'Local Meeting Notes'
  }, null, 2));
  const apps = await packager({
    dir: stage, name: 'Local Meeting Notes', platform: 'darwin', arch: 'arm64',
    electronVersion: require('electron/package.json').version, out: path.join(root, 'release'),
    download: { cacheRoot: path.join(root, 'build/electron-cache') },
    ...(fs.existsSync(path.join(root, 'build/electron-zips', `electron-v${require('electron/package.json').version}-darwin-arm64.zip`))
      ? { electronZipDir: path.join(root, 'build/electron-zips') } : {}),
    icon: path.join(iconOutput, 'AppIcon.icns'),
    overwrite: true, asar: true, appBundleId: 'com.localmeetingnotes.desktop',
    appCategoryType: 'public.app-category.productivity', darwinDarkModeSupport: true,
    extendInfo: { LSMinimumSystemVersion: '15.0',
      CFBundleIconFile: 'AppIcon.icns', CFBundleIconName: 'AppIcon',
      NSMicrophoneUsageDescription: '会議中の自分の発言を録音し、このMacで文字起こしします。',
      NSAudioCaptureUsageDescription: '会議相手の音声をMacの再生音から録音します。' }
  });
  for (const outputPath of apps) {
    const appPath = path.join(outputPath, 'Local Meeting Notes.app');
    const resources = path.join(appPath, 'Contents/Resources');
    // Modern macOS uses the layered asset; macOS 15 uses the ICNS fallback.
    fs.copyFileSync(path.join(iconOutput, 'Assets.car'), path.join(resources, 'Assets.car'));
    fs.copyFileSync(path.join(iconOutput, 'AppIcon.icns'), path.join(resources, 'AppIcon.icns'));
    fs.cpSync(path.join(root, 'build/mac-backend/LocalMeetingNotesBackend'), path.join(resources, 'backend'), { recursive: true, verbatimSymlinks: true });
    fs.cpSync(path.join(root, 'dist'), path.join(resources, 'dist'), { recursive: true });
    fs.mkdirSync(path.join(resources, 'vendor'), { recursive: true });
    fs.copyFileSync(path.join(root, 'vendor/MeetingAudio'), path.join(resources, 'vendor/MeetingAudio'));
    fs.chmodSync(path.join(resources, 'vendor/MeetingAudio'), 0o755);
    execFileSync('/usr/bin/codesign', ['--force', '--deep', '--sign', '-', '--entitlements',
      path.join(root, 'native/macos/entitlements.plist'), appPath], { stdio: 'inherit' });
    execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', appPath], { stdio: 'inherit' });
    console.log(`Mac app: ${appPath}`);
  }
})().catch(error => { console.error(error); process.exit(1); });
