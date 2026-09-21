# 検証記録（2026-09-17）

実行環境: Apple M2 / メモリ16GB / macOS 26.6.2 / Python 3.13 / Node.js 22。

## 確認済み

- ユーザー本人によるXcodeライセンス同意後、Swiftヘルパー、PyInstallerのPython実行環境、Electronアプリをビルド。ad-hoc署名の `codesign --verify --deep --strict` 成功。
- 生成した `release/Local Meeting Notes-darwin-arm64/Local Meeting Notes.app` のネイティブ起動、動的ポートでの同梱サーバー起動、画面表示成功。
- macOSのマイクと画面・システム音声の権限をユーザーが許可。通常の事前判定がfalseのままになる実機挙動に対してApple標準の共有選択画面を使用し、選択後の録音開始を確認。
- 実マイクとMac再生音の同時録音成功。検証録音の両WAVはmono PCM16 / 48kHz、長さ16.1554167秒で一致。両方に非ゼロの音声サンプルを確認。base / CPUで文字起こしと `transcript.md`・`chatgpt_prompt.md` を生成し、完了表示を確認。
- ネイティブ保存先選択、変更後の再起動で日本語パス保持、プロンプトコピー成功表示、Finderで保存先表示を確認。
- 日本語合成音声による文字起こし、既存フォルダの再文字起こし、JSON・Markdown・プロンプト生成を確認。baseの結果には誤字があり、校正は必要。
- 取得済みモデルで `HF_HUB_OFFLINE=1` を指定し、同梱Python実行ファイルによる再文字起こし成功。モデルはApplication Support配下にも配置済み。
- `npm run build`: Vite・TypeScript成功。
- `.venv/bin/python -m unittest discover -s tests -v`: 12件成功。Swiftの実バッファを使った44.1→48kHz変換、開始差0.1秒/0.3秒の補正と同長WAV生成、設定保存、CPU制限、Windows更新拒否、安定デバイスID、時刻順統合、終了待機を検証。
- 権限拒否相当のヘルパーエラーとモデル取得失敗は自動テストで、録音開始・正常完了を出さないことを確認。
- `.venv/bin/python scripts/smoke-http.py`: 実サーバー起動、静的UI、capabilities、設定、更新制限、不正Origin拒否、正常終了に成功。
- `git diff --check`、JavaScript・シェル構文チェック成功。

- 録音中にHTTPの終了APIを呼び出し、約4.038秒の両WAVが同長で確定することを実機確認。終了後の録音ヘルパー・Pythonサーバー残留なし。終了時は文字起こしを開始せず、WAV・メタデータ・ログを保存。
- 共有選択待ちのまま停止指示を受け取れるよう、録音開始前から標準入力と終了シグナルを監視するよう修正。選択待ちを解除して、録音未開始のエラーとして終了する。

## 検証範囲の限界

マイクの物理切断、再生音が完全に無音の実機ケース、長時間録音、macOS 15そのもの、別のMacへの移動、Windows上の実動作は未検証。Windows用コードと依存分離は維持し、CUDAフォールバックは自動テストで確認している。一般配布用のDeveloper ID署名・公証は対象外。
