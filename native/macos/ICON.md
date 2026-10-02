# Macアプリアイコン

録音波形と議事録を一つの形にまとめた、ミント〜ティールのアイコンです。文字や細かな装飾を入れず、小さな表示でも識別できる構成にしています。

- 原本: `AppIcon.icon`（Icon Composerで編集可能）
- 前景: `Assets/AudioNote.svg`、1024×1024のベクター、波形と行を抜いたノート形状
- 背景: Icon Composerの不透明なグラデーション
- 外周の角丸、光沢、レイヤー間の影、透過表現: Appleのレンダラーが生成
- 外観: 通常・ダーク・クリア・色付き。共通の形状からシステムが生成
- 互換性: macOS 26以降は`Assets.car`内のレイヤーアイコン、macOS 15は`AppIcon.icns`

## ビルド

Xcode 26以降が必要です。アプリの最低動作OSはmacOS 15のままです。

```sh
bash scripts/build-mac-icon.sh
```

Appleの`actool`が`build/mac-icon/`へ`Assets.car`・`AppIcon.icns`・Info.plist用情報を生成します。`scripts/package-mac.cjs`からも自動で呼ばれ、アプリへ組み込み、署名をやり直します。アイコンだけの変更で既存バックエンドを再利用する場合は`node scripts/package-mac.cjs`を実行します。

## 確認

Icon Composerのレンダラーで通常・ダーク・クリア明暗・色付き明暗の6外観、16・32・64・128・256・1024pxを確認。ICNSの各解像度、アプリの`CFBundleIconFile`／`CFBundleIconName`、組み込んだアセット、署名も確認済みです。完成アプリからmacOSの`NSWorkspace`で取得した実際のアイコンが`AppIcon-preview.png`です。

基準: [Apple Human Interface Guidelines — App icons](https://developer.apple.com/design/human-interface-guidelines/app-icons)、[Icon Composer](https://developer.apple.com/icon-composer/)。
