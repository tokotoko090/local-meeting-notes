# Mac版の構成

Apple Silicon / macOS 15以上。ScreenCaptureKitでシステム音声とマイクを同じストリームから受け取り、共通のホスト時刻を起点にmono PCM16 / 48 kHzのWAVへ保存する。画像の出力ハンドラーは登録せず、映像ファイルは生成しない。

## 開発・ビルド

Node.js 22以上、Python 3.13、ffmpeg、Icon Composer対応のXcode 26以降が必要。アプリの最低動作OSはmacOS 15のまま。初回はユーザー本人が `sudo xcodebuild -license` でライセンスを確認・同意する。

```sh
bash scripts/setup-mac.sh
npm run build:mac
```

生成先: `release/Local Meeting Notes-darwin-arm64/Local Meeting Notes.app`

アプリアイコンはAppleのIcon Composer形式から自動生成します。原本・ビルド手順は[アイコンの説明](ICON.md)を参照してください。

このアプリにはElectron、Pythonの実行環境、MLX Whisper、MLXのMetalライブラリ・シェーダー、音声フィルター・トークナイザー資材、ffmpegとその動的ライブラリ、Swift製録音ヘルパーを同梱する。初回モデル取得後はローカルで動作する。開発マシンの `.venv-mlx` やHomebrewを実行時に参照しないことを、完成したアプリで確認する。

`backend/requirements-macos.lock` はPython 3.13 / arm64でのビルド依存を固定する。セットアップは `.venv-mlx` を作成し、macOS 26のホストでもmacOS 15対応のMLXバイナリを明示的に選ぶ。MLX Whisperの変換用依存として開発環境に入るPyTorchは完成アプリから除外する。Windowsは既存requirementsと既存インストーラーを使用する。Macビルドはローカル利用向けのad-hoc署名で、Developer ID署名・公証は行わない。

## 文字起こし

MLX WhisperでApple Silicon GPU・FP16のみを使用する。GPUが利用できない場合は理由を表示して停止し、CPUへは切り替えない。モデルは `base` / `small` / `medium` / `large-v3` / `large-v3-turbo`、初期値は `large-v3-turbo`。選択したモデルのみ初回に取得し、既存のアプリ用モデル保存先にキャッシュする。取得にはネット接続が必要で、取得後はオフラインで利用できる。

日本語でマイク音声とPC音声を順番に処理し、モデルを再利用する。ほぼデジタル無音の長い区間は文字起こしから除外し、元録音基準の時刻とトラック別の出力を保持する。メモリ不足・取得失敗でも録音を削除しないため、モデルを小さくして既存フォルダの文字起こしを再実行できる。

## 起動と権限

Finderから `.app` を起動。画面はアプリが所有する127.0.0.1の動的ポートのHTTPサーバーから読み込む。Electron IPCによる別の録音処理は使用しない。フォルダ選択もHTTP APIから要求し、アプリが所有するネイティブダイアログをElectronに表示させる。初回の「録音開始」でマイクと「画面収録とシステムオーディオ」の許可が必要。権限を変更後、macOSから指示された場合はアプリを再起動する。通常の権限確認で利用可能と判定されない場合は、Apple標準の共有選択画面を表示する。ディスプレイを選択してから録音が始まる。この場合、録音のたびに選択が必要。共有選択をキャンセルした場合は録音開始・正常完了とは扱わない。

Macの再生音全体が対象であり、会議アプリだけに限定はしない。機密情報を含む別の音声を同時に再生しないよう運用する。画面上にも全体録音であることを表示する。

保存先:

- 録音: `~/Documents/Local Meeting Notes`（画面から変更可能）
- 設定、処理ログ、モデル: `~/Library/Application Support/Local Meeting Notes`
- Electron起動ログ: ElectronのuserData配下の `electron.log`

アプリを終了すると、録音中なら停止してWAVを保存する。この場合の文字起こしは次回「保存済み音声」タブから実行できる。既に文字起こし中の場合は完了を待って終了する。処理中の強制終了は行わない。

## 画面とUI検証

「新しく録音」と「保存済み音声」の2タブで操作する。録音対象・モデル・保存先を確認して開始し、完了したら同じ領域からChatGPT用プロンプトをコピーする。保存先、権限再確認、デバイス再読み込みは「設定」に集約。OSのライト・ダーク設定に追従する。

状態別の検証方法と機能対応表は[UI検証記録](UI_VALIDATION.md)を参照。UIだけの変更では `npm run build` のあと `node scripts/package-mac.cjs` で既存の同梱バックエンドを再利用してアプリを作成できる。バックエンド変更時は `npm run build:mac` を使う。

## ネイティブヘルパーのインターフェース

- `MeetingAudio list-devices`: マイク一覧とシステム音声1件をJSONで返す。マイクの `id` はAVCaptureDevice.uniqueID。UIのindexが変化しても選んだIDで録音する。
- `MeetingAudio permissions`: マイクと画面収録の権限状態。確認だけでは許可ダイアログを表示しない。
- `MeetingAudio record <directory> [microphone-id]`: 権限を確認してから録音開始イベントをJSON Linesで出力する。標準入力の `stop` またはEOF、SIGTERM/SIGINTでWAVを確定して停止する。
- `MeetingAudio pick-directory --initial <path> [--create]`: ネイティブのフォルダ選択。キャンセルは `{ok:false,canceled:true}`。

録音失敗は非ゼロ終了とerrorイベント。無音のシステム音声はwarningで表示し、空の文字起こしを許容する。マイクのサンプル未取得、切断、変換・ファイル保存エラーは失敗。両トラックのタイムスタンプから先頭・途中の無音を補い、停止時の長さを揃える。

## 確認

```sh
npm run build
.venv-mlx/bin/python -m unittest discover -s tests -v
.venv-mlx/bin/python scripts/smoke-http.py
```

実機で別途確認する項目: Finder起動、初回権限許可と拒否、マイク＋再生音の分離、無音、マイク切断、長時間録音、録音中終了、再起動、ネイティブの保存先選択・コピー・Finder表示、モデル取得後のオフライン文字起こし。自動テストだけで実機確認済みとはしない。
