# Local Meeting Notes

Windows専用のローカル議事録作成ツールです。

マイク音声とPCから出ている音声を別々に録音し、PC上で文字起こしして、ChatGPTに貼り付けやすいMarkdownプロンプトを作成します。OpenAI APIは使いません。録音ファイルや文字起こし結果は、手動で共有しない限りこのPC内に残ります。

## インストール方法

1. GitHub Releasesから最新版の `LocalMeetingNotesSetup-x.y.z.exe` をダウンロードします。
2. ダウンロードしたインストーラーを実行します。
3. インストールが終わると、デスクトップとスタートメニューに `Local Meeting Notes` のショートカットが作成されます。
4. ショートカットから起動します。

インストール先は現在のWindowsユーザー配下です。管理者権限は不要です。

```text
%LOCALAPPDATA%\LocalMeetingNotes
```

## 起動方法

デスクトップまたはスタートメニューの `Local Meeting Notes` を開きます。

起動するとローカルサーバーが立ち上がり、通常は既定のブラウザで次の画面が開きます。

```text
http://127.0.0.1:8765
```

ブラウザが自動で開かない場合は、上のURLを手動で開いてください。

## 基本的な使い方

1. 会議参加者に録音の同意を取ります。
2. `文字起こしモデル` を選びます。迷ったら `base` のままで構いません。
3. `処理デバイス` は、まず `cpu` のまま使ってください。
4. `マイク` で自分のマイクを選びます。
5. `PC出力` で会議音声が流れているスピーカーやヘッドホンの `[Loopback]` デバイスを選びます。
6. 必要に応じて `録音の保存先` の `参照` から保存先フォルダを選びます。未選択の場合は、入力欄に灰色で表示されている標準フォルダに保存されます。一度選ぶと次回起動以降も同じ保存先が使われます。
7. `録音開始` を押して録音を開始します。
8. 会議が終わったら `録音停止` を押します。
9. 処理完了後、`保存フォルダを開く` で保存フォルダを開き、`chatgpt_prompt.md` や `transcript.md` を確認します。

## 保存される場所

録音結果は、`録音の保存先` で選んだフォルダに保存されます。保存先は次回起動以降も保持されます。未選択の場合は次の標準フォルダに保存されます。

```text
%LOCALAPPDATA%\LocalMeetingNotes\output
```

1回の録音ごとに、日時付きのフォルダが作成されます。

```text
output/
  2026-07-01_14-30-00/
    mic.wav
    system.wav
    mic_transcript.json
    system_transcript.json
    transcript.md
    chatgpt_prompt.md
    metadata.json
    app.log
```

主に使うファイルは次の2つです。

- `transcript.md`: マイク音声とPC音声をまとめた文字起こし
- `chatgpt_prompt.md`: ChatGPTに貼り付けるためのプロンプト

## 既存録音をもう一度文字起こしする

録音済みフォルダに対して、文字起こしやプロンプト生成だけをやり直せます。

1. `既存の保存フォルダ` の `参照` を押します。
2. `output` 配下の既存録音フォルダを選びます。
3. `既存フォルダを文字起こし` を押します。

この操作では、選択したフォルダ内の `mic_transcript.json`、`system_transcript.json`、`transcript.md`、`chatgpt_prompt.md` が上書きされます。

## アップデート方法

画面上部の `アップデート` から更新できます。

1. `確認` を押して、GitHub Releasesに新しいバージョンがあるか確認します。
2. 新しいバージョンがある場合は `ダウンロード` を押します。
3. ダウンロード後、`インストール` を押します。
4. インストーラーが起動するので、そのまま更新します。

録音中や文字起こし中は更新できません。処理が終わってから実行してください。

## よくあるトラブル

### PC側の音声が録音されない

`PC Output` で、実際に会議音声が流れている出力デバイスの `[Loopback]` を選んでください。

例えばヘッドホンで会議音声を聞いている場合は、スピーカーではなくヘッドホン側のloopbackを選びます。

### `No WASAPI loopback device found` と表示される

Windowsで再生デバイスが有効になっているか確認してください。会議音声やYouTubeなど、何か音を流した状態で `デバイス` を押すと見つかりやすくなります。

### `No microphone input device found` と表示される

Windowsのサウンド設定でマイクが有効か確認してください。USBマイクやヘッドセットを接続し直してから `デバイス` を押してください。

### 文字起こしが遅い

`処理デバイス` が `cpu` の場合、長い会議では時間がかかります。NVIDIA GPUとCUDA環境が正しく入っているPCでは `auto` または `cuda` を試せます。

インストーラー本体は軽量なCPU版です。NVIDIA GPUがあるPCでは、画面上部の `GPU(CUDA)対応` で状態を診断できます。`GPU(CUDA)セットアップ可能` と表示された場合は、`GPU(CUDA)セットアップ` を押すと、このアプリ専用の管理フォルダにGPU(CUDA)対応コンポーネントを追加インストールできます。

システム全体のCUDAやPATHは変更しません。ただし、NVIDIA GPU本体のドライバーはPC側に必要です。NVIDIAドライバーが古い、GPUがCUDAに対応していない、または別のCUDAエラーが出る場合は `cpu` に戻してください。CPUモードが最も互換性の高い設定です。

### `cublas64_12.dll is not found or cannot be loaded` と表示される

`GPU(CUDA)対応` の `GPU(CUDA)セットアップ` を実行してください。ダウンロードに失敗した場合やオフライン環境では、CPUでそのまま利用できます。

### `Applying the VAD filter requires the onnxruntime package` と表示される

古いインストーラー版では、文字起こし中の無音検出に必要な `onnxruntime` が同梱されていない場合があります。最新版へアップデートしてください。

### アップデート確認が失敗する

インターネット接続と、GitHub Releasesが公開されているかを確認してください。公開Releaseがない場合、アプリは更新を見つけられません。

## アンインストール

Windowsの「インストールされているアプリ」から `Local Meeting Notes` をアンインストールできます。

または次のアンインストーラーを実行します。

```text
%LOCALAPPDATA%\LocalMeetingNotes\Uninstall.exe
```

録音データはユーザーの出力フォルダに残る場合があります。不要であれば次のフォルダを手動で削除してください。

```text
%LOCALAPPDATA%\LocalMeetingNotes\output
```

## 開発者向け

開発に必要なもの:

- Windows 10 / 11
- Node.js 20以上
- Python 3.11以上
- ffmpeg
- NSIS

開発環境のセットアップ:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd install
```

開発用に起動:

```powershell
npm.cmd run start:browser
```

Windowsインストーラーを作成:

```powershell
npm.cmd run build:windows
```

作成されたインストーラー:

```text
release\LocalMeetingNotesSetup-x.y.z.exe
```

## リリース手順

1. `package.json`、`backend/server.py`、`backend/meeting_notes.py` のバージョンを揃えます。
2. 変更をGitHubにpushします。
3. `v0.2.0` のようなタグをpushします。
4. GitHub ActionsがWindowsインストーラーを作成し、GitHub Releaseに添付します。

アプリ内アップデートは、公開GitHub Releaseに添付された `LocalMeetingNotesSetup-x.y.z.exe` を探します。

## プライバシーと同意

録音は、必ず参加者の同意を得てから行ってください。

音声、文字起こし、生成されたプロンプトはローカルPCに保存されます。外部サービスに自動送信されることはありません。
