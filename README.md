# Local Meeting Notes

Windows / macOS向けのローカル議事録作成ツールです。

## Mac版（Apple Silicon / macOS 15以降）

Mac版は `npm run build:mac` で作成した `Local Meeting Notes.app` をFinderから起動します。追加の音声ドライバーは不要です。初回録音時にマイクと画面収録・システムオーディオを許可してください。macOSの共有選択画面が出た場合はディスプレイを選択します。映像は保存しません。

標準保存先は `~/Documents/Local Meeting Notes`。初回のモデル取得にはネット接続が必要で、取得済みモデルはオフラインで利用できます。文字起こしはMLX WhisperでApple SiliconのGPUを使用し、CPUへの切り替えは行いません。Mac版の自動更新は未対応です。

モデルは `base`（軽量・高速）、`small`（速度と精度のバランス）、`medium`（精度重視）、`large-v3`（高精度・メモリ消費大）、`large-v3-turbo`（高精度と速度のバランス）の5種類です。初期値は `large-v3-turbo`。選択したモデルだけを初回に取得します。Mac版には処理デバイスの選択欄はありません。メモリ不足の場合は録音を保持したまま、小さいモデルで再実行できます。

セットアップ、ビルド、権限、終了時の動作は [Mac版の説明](native/macos/README.md) を参照してください。以下のインストーラー・CUDA・アップデートの説明はWindows版向けです。

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

1. 会議参加者に録音の同意を取り、`新しく録音` タブを開きます。
2. マイクと再生音の録音対象を確認します。Macではアプリを問わずMacの再生音全体が対象になります。
3. `文字起こしモデル` を選びます。Macの標準は `large-v3-turbo`、Windowsは `base` です。モデルの説明は選択欄の下に表示します。
4. 必要に応じて `録音の保存先` の `変更` から保存先を選びます。保存先は次回起動以降も保持されます。
5. `録音を開始` を押します。録音中は経過時間と使用中の音声入力を表示します。
6. 会議が終わったら `録音を停止して文字起こし` を押し、処理完了を待ちます。
7. 完了画面の `ChatGPT用プロンプトをコピー` を押してChatGPTへ貼り付けます。`保存フォルダを開く` から音声やMarkdownも確認できます。

保存先、権限の再確認、デバイス一覧・再読み込みはヘッダーの `設定` にまとめています。Windowsの処理デバイス選択、CUDA診断・セットアップ、更新も設定から操作します。詳細ログは画面下部で開閉できます。タブや設定を切り替えても入力と結果は保持されます。

終了するときは `保存して終了` を押します。録音中は音声を保存し、文字起こし中は処理完了を待って終了します。

## プロンプトの編集

`設定` の `プロンプト設定` で、毎回使用する依頼文・出力項目を編集して保存できます。`標準に戻す` で元の文面へ戻せます。文字起こし全文は生成時に末尾へ自動追加されるため、テンプレートへ貼り付ける必要はありません。変更は次に開始する録音・文字起こしから適用され、過去のファイルは変更しません。

完了画面の `プロンプトを編集` では、その会議の `chatgpt_prompt.md` 全体を編集できます。`保存済み音声` から録音フォルダを選んだ場合も、既存のプロンプトを開けます。`保存` はファイル更新、`保存してコピー` はファイル更新後のコピーです。共通テンプレートや元の音声・文字起こしは変更しません。未保存の変更を閉じる場合は破棄の確認が表示されます。

録音・文字起こし中は編集できません。文字起こしを再実行すると、手動編集したプロンプトも新しく生成した内容で上書きされます。

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

1. `保存済み音声` タブを開き、録音フォルダを選びます。
2. 使用する文字起こしモデルを選びます。
3. 上書きの注意を確認し、文字起こしを開始します。

この操作では、選択したフォルダ内の `mic_transcript.json`、`system_transcript.json`、`transcript.md`、`chatgpt_prompt.md` が上書きされます。

## アップデート方法

Windows版は `設定` の `アップデート` から更新できます。

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

Windowsのサウンド設定でマイクが有効か確認してください。USBマイクやヘッドセットを接続し直してから `設定` の音声デバイスで `再読み込み` を押してください。

### 文字起こしが遅い

`処理デバイス` が `cpu` の場合、長い会議では時間がかかります。NVIDIA GPUとCUDA環境が正しく入っているPCでは `auto` または `cuda` を試せます。

インストーラー本体は軽量なCPU版です。NVIDIA GPUがあるPCでは、`設定` の `GPU（CUDA）` で状態を診断できます。`GPU(CUDA)セットアップ可能` と表示された場合は、`セットアップ` を押すと、このアプリ専用の管理フォルダにGPU(CUDA)対応コンポーネントを追加インストールできます。

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

Mac・Windowsは同じソースとバージョンで管理します。WindowsのビルドはGitHub Actions、MacのビルドはApple Silicon Macで実行します。タグのpushだけでは公開しません。

両OSの配布物を1つのドラフトへ集約し、同じコミット・バージョン・チェックサムと実機検証の結果を確認してから正式公開します。[ビルド・検証・公開手順](docs/RELEASING.md)を参照してください。

Windowsのアプリ内更新は最新の正式リリースにある `LocalMeetingNotesSetup-x.y.z.exe` を参照するため、正式リリースにはWindowsのインストーラーを必ず含めます。Macのアプリ内更新は未対応です。

## プライバシーと同意

録音は、必ず参加者の同意を得てから行ってください。

音声、文字起こし、生成されたプロンプトはローカルPCに保存されます。外部サービスに自動送信されることはありません。
