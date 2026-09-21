# リリース手順

## Windows の ffmpeg と修正候補

`scripts/build-windows.ps1` は `scripts/prepare_windows_ffmpeg.py` で gyan.dev の ZIP と公開 SHA-256 を取得し、ハッシュ・ZIP パス・単体 EXE の実行と WAV 変換を検証します。Chocolatey の `Get-Command ffmpeg.exe` は実体ではなく shim を返すため、コピーして配布しないでください。実体は NSIS がインストール先の `vendor/ffmpeg.exe` に配置します。PyInstaller の展開先に ffmpeg を同梱しません。

CI は検証済みダウンロード必須です。ローカルのみ、ネットワーク障害時に既存 `vendor/ffmpeg.exe` を隔離ディレクトリで同じ変換テストに通した場合に再利用できます。チェックサム不一致や変換失敗ではキャッシュにフォールバックしません。

既存の v0.3.0 タグは `3eac0985e40c40ffd7ad1fa392235794d43dc907` の候補を指しています。今回の Windows 修正候補は同じ `LocalMeetingNotesSetup-0.3.0.exe` という名前でも別の成果物です。保存先と `windows-manifest.json` の source commit / SHA-256 で区別し、既存タグや共通ドラフトの成果物を移動・差し替えしないでください。Mac も新しい候補コミットから再ビルド・実機検証してから、次の共通候補を決めます。

Windows の検証ではインストーラーから導入した EXE を使用し、専用 `LOCAL_MEETING_NOTES_DATA_ROOT` と保存フォルダで録音・停止・CPU/CUDA・プロンプト編集とコピー・再起動を確認します。v0.2.9 はポートが 8765 固定で、データ分離には `LOCALAPPDATA` を使用します。上書きインストール前後で既存設定と録音のハッシュを比較してください。音声、文字起こし、個人設定、ローカル検証ログをコミット・アップロードしないでください。

回帰確認: `python -m unittest discover -s tests -v`、`npm.cmd run build`、`npm.cmd run build:windows`。UI は `python scripts/ui-fixture-server.py` を起動後、Electron で `scripts/verify-ui.cjs` と `scripts/verify-prompt-ui.cjs` を順に実行します。同じ fixture を共有するため同時実行しないでください。これはテスト用 Chromium であり、Windows 配布形式は従来の EXE + ブラウザです。

公開 Release は GitHub Actions から自動作成しません。Windows workflow は `master`・`codex/**` への push / `master` 向け pull request と手動実行で候補をビルドし、インストーラーと SHA-256 付きマニフェストを Actions artifact に保存するだけです。

## 1. 同じソースから両 OS をビルドする

### Windows の音量メーターと turbo

Windows の新規設定は `large-v3-turbo` / `auto` です。保存済みのモデルと処理デバイスは引き継ぎます。Windows は faster-whisper 1.2.1 以上を使い、CUDA は FP16、CPU は INT8、CUDA 失敗時には通知して CPU へ切り替えます。Mac の MLX / GPU / FP16 専用経路は維持します。

モデルはインストーラーに含めません。初回利用時に取得し、以後は Hugging Face のローカルキャッシュを優先します。同一ジョブのマイク・PC 音声はモデルを共有し、ジョブ終了時に解放します。キャッシュ利用の検証は取得済みモデルと `HF_HUB_OFFLINE=1` で実行できます。取得失敗では録音を保持し、再実行できるエラーを表示します。

Windows 実機では入力テスト中に WAV や会議フォルダが作成されないこと、マイク・PC 音声のメーター、入力テストから録音への切り替え、無音状態での停止、デバイス変更・画面切り替え・終了時の後片付けを確認します。メーターは録音と同じ PCM を計測し、音量イベントを通常ログへ蓄積しません。Mac ではメーターと監視 API 呼び出しがないことも回帰テストで確認します。

速度・認識精度の比較は今回の依頼から除外されました。GPU / CPU の動作確認を性能比較や Mac と同等の速度・精度の証明として扱わないでください。

候補 commit の完全な SHA を控えます。Windows artifact から `LocalMeetingNotesSetup-<version>.exe` と `windows-manifest.json` を取得します。

Apple Silicon Mac で同じ commit を checkout し、次を実行します。

```bash
npm ci
bash scripts/setup-mac.sh
python3 scripts/release_mac.py --source-commit <40桁の候補SHA>
```

`release/` に `LocalMeetingNotes-<version>-macOS-arm64.zip` と `macos-manifest.json` ができます。zip は macOS の属性を保つため `ditto` で作成されます。

4ファイルを同じ作業ディレクトリへ置き、結合マニフェストを作ります。

```bash
python3 scripts/release.py assemble \
  --manifest-dir ./candidate --artifact-dir ./candidate \
  --output ./candidate/release-manifest.json
```

異なるバージョン、異なる source commit、想定外のファイル名、壊れたハッシュ、Windows exe または Mac zip の欠落は拒否されます。

## 2. 実機確認と draft 作成

ドラフトは検証前に作成して配布できます。正式公開前にWindows と Mac それぞれで、起動、録音、停止、文字起こし、プロンプト設定・個別編集・コピー、保存して終了を実機で確認します。合格後だけ、次の厳密な JSON を各検証ファイルへ保存します（platform だけを OS ごとに変えます）。

```json
{"status":"passed","platform":"windows-x64","version":"0.3.0","source_commit":"<40桁の候補SHA>"}
```

Windows は 0.2.9 が入った利用者環境でも上書き更新を確認します。先に保存先、モデル、処理デバイス、共通プロンプトなどの設定値を控え、0.3.0 をインストール後も設定と既存録音が残ることを確認します。アンインストールしてから試す方法では更新確認になりません。

候補 commit に `v<version>` タグを付けて push し、チェックと draft 作成を行います。master への反映は publish 時に検査します。

```bash
git tag v0.3.0 <候補SHA>
git push origin v0.3.0
python3 scripts/release.py check --manifest-dir ./candidate --artifact-dir ./candidate --bundle ./candidate/release-manifest.json
python3 scripts/release.py draft --manifest-dir ./candidate --artifact-dir ./candidate --bundle ./candidate/release-manifest.json
```

同名 Release が既に存在する場合、script は上書きしません。GitHub 上の draft で版、2つの成果物、結合マニフェスト、説明を目視確認します。

## 3. 明示的に公開する

公開する操作は次の `publish` だけです。両 OS の検証証跡、タグ、master、全 SHA-256 を再確認し、既存の公開 Release や存在しない draft は拒否します。

```bash
python3 scripts/release.py publish \
  --manifest-dir ./candidate --artifact-dir ./candidate \
  --bundle ./candidate/release-manifest.json \
  --windows-validation ./candidate/windows-validation.json \
  --mac-validation ./candidate/mac-validation.json
```

公開後は GitHub Releases の latest から Windows exe を実際にダウンロードし、ファイル名と SHA-256 がマニフェストに一致することを確認します。アプリの「設定 → アップデート」でも latest の版を検出し、exe のダウンロードと起動まで確認します。

Mac 版は Developer ID 署名・notarization 済みではなく ad-hoc 署名です。配布先では Gatekeeper の警告が出る場合があり、自動更新にも対応していません。この制約を Release notes に明記します。
