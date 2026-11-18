# 作業引き継ぎログ (Handoff Log)

このファイルは、AIアシスタント間で作業の進捗と次のタスクを引き継ぐための記録です。

---

## 完了プロジェクト: Galaxyアラーム連動 Apple Music自動再生

- **設計・運用マニュアル:** [docs/music-automation.md](../docs/music-automation.md)
- **プログラム本体:** [projects/music-automation/bot.py](../projects/music-automation/bot.py)
- **常駐設定ファイル:** [projects/music-automation/com.mylab.music-automation.plist](../projects/music-automation/com.mylab.music-automation.plist)
- **最終更新:** 2026-11-18

### 実装・構築済みの内容
1. **Discord連携基盤の構築**:
   - `#mac-control` チャンネル、Webhook、および `MacMagicBot` を作成。
2. **Mac mini 制御Bot (`bot.py`) の実装**:
   - `switchaudio-osx` (`/opt/homebrew/bin/SwitchAudioSource`) を導入し、イヤホン等が接続されていても起床時は強制的に `Mac miniのスピーカー` へ出力先を切り替える機能を実装。
   - `music wakeup` 受信時、変更前のスピーカーと音量を記憶した上で、音量を `100%` にして Apple Music の『`WakeUp`』プレイリストを再生。
   - Discordから `music wakeup stop`（または `music stop` 等）が送られた時だけでなく、Mac本体（キーボードやアプリ画面）で直接音楽が停止された場合もバックグラウンド監視（2秒周期）で自動検知し、先に音量を元の数値へ下げてから元のスピーカーへ自動復元する安全設計を実装。
3. **Galaxy S26 Ultra 連携**:
   - 「HTTP Request Shortcuts」にて `MacWakeUp`（再生用）と `MacWakeUp Stop`（停止用）を作成。
   - 「モードとルーチン」にて、平日アラーム解除時に `MacWakeUp` が自動実行されることを確認済み。
4. **Mac mini 常駐化 (`launchd`) & 本体設定**:
   - `~/Library/LaunchAgents/com.mylab.music-automation.plist` を登録・起動済み（`RunAtLoad` および `KeepAlive` 有効）。エディタやターミナルを閉じても、Mac再起動後も自動で裏側で稼働する状態。
   - Mac miniの「システム設定」にて、画面ロック（パスワード要求）を「しない」に設定済み（iPhoneミラーリングの自動認証を解除して設定）およびスリープ防止を確認済み。

### 今後の拡張アイデア（次のタスク候補）
- 今後 `MacMagicBot` に音楽再生以外のMac操作コマンド（アプリ起動、スリープ/ロック、通知読み上げなど）を追加する場合は、`projects/music-automation/bot.py` の `on_message` 内に新しいコマンド分岐を追加し、`launchctl kickstart -k gui/$(id -u)/com.mylab.music-automation` で再起動するだけで拡張可能。

---

## 完了・稼働中プロジェクト: Discord連携 Mac mini AIエージェント (`#gemini-agent`)

- **設計・手順書:** [projects/discord-ai-agent/README.md](../projects/discord-ai-agent/README.md)
- **プログラム本体:** [projects/discord-ai-agent/bot.py](../projects/discord-ai-agent/bot.py)
- **常駐設定ファイル:** [projects/discord-ai-agent/com.mylab.discord-ai-agent.plist](../projects/discord-ai-agent/com.mylab.discord-ai-agent.plist)
- **最終更新:** 2026-11-19

### これまでの経緯と完了した作業
1. **GitHub Actions 版（`projects/github-issue-agent/`）の検証結果**:
   - `.github/workflows/gemini-cli.yml` を構築して動作確認を行ったが、Google AI Studio 無料枠（`gemini-3.8-flash`）の1日20リクエスト制限および夜間混雑（503エラー）により、無料APIキーでの安定運用は困難と判明。
   - また Mac mini 上の旧 `gemini` CLI（`0.68.0`）も個人向けログイン（`oauth-personal`）が提供終了済みであることを確認。
2. **Discord × Antigravity CLI (`agy`) 版への方針転換と本稼働**:
   - Mac mini に公式後継の `agy` CLI（`/Users/sasadayuto/.local/bin/agy`）を導入し、`-p --output-format json --mode accept-edits --sandbox --dangerously-skip-permissions` での非対話実行が正常動作することを確認。
   - `projects/discord-ai-agent/` に Python 仮想環境（`.venv`）と `bot.py` を構築し、`~/Library/LaunchAgents/com.mylab.discord-ai-agent.plist` として `launchd` 常駐起動を完了。
   - Discord 上に `#gemini-agent` テキストチャンネルを作成し、`!status`・`!help`・自然言語指示（画像添付含む）の送受信と自動 `git commit & push` が動作することを確認。
3. **使いやすさ・安定性の改善**:
   - 受付時にタスク規模に応じた予測所要時間の目安（`約10〜30秒` / `約30秒〜2分` / `約1〜3分`）を表示し、作業中は15秒ごとに経過時間を自動更新、完了時に合計所要時間を表示する機能を追加。
   - Python 3.9 環境での `asyncio.Lock` イベントループ不整合を解消（遅延初期化化）。
   - `AGENTS.md` に「4. 新規プロジェクト立ち上げ・リポジトリ構成の判断方針」（基本は `my-lab/projects/` で開始し、独立アプリ等は別リポジトリ分離を提案する方針）を追記。

### 現在のステータス・次のタスク
- **稼働状態:** Discord `#gemini-agent` 経由での自然言語指示・ファイル生成・GitHub自動反映が稼働中。

---

## 進行中プロジェクト: 社バス カウントダウンウィジェット (`company-bus-widget`)

- **設計・手順書:** [projects/company-bus-widget/README.md](../projects/company-bus-widget/README.md)
- **時刻表データ:** [projects/company-bus-widget/app/src/main/java/com/mylab/buswidget/BusTimetable.kt](../projects/company-bus-widget/app/src/main/java/com/mylab/buswidget/BusTimetable.kt)
- **ウィジェット本体:** [projects/company-bus-widget/app/src/main/java/com/mylab/buswidget/BusWidgetProvider.kt](../projects/company-bus-widget/app/src/main/java/com/mylab/buswidget/BusWidgetProvider.kt)
- **自動ビルド設定:** [.github/workflows/build-bus-widget.yml](../.github/workflows/build-bus-widget.yml)
- **最終更新:** 2026-11-19

### 実装済みの内容
1. **時刻表画像からの全便データ化 (`1-1` 〜 `1-25`)**:
   - デフォルトの「JR発 ➔ GNFJ（会社行）」に加え、ワンタップ切替で「GNFJ発 ➔ JR・京急（帰り）」「京急発 ➔ GNFJ」の3ルートに対応。
2. **Yahoo!乗換案内風カウントダウン × Galaxy Home Up 対応**:
   - Android 標準の `Chronometer` により省電力で秒単位カウントダウンを表示。
   - 最小 1×1 マス（40dp）からの縦横自由リサイズに対応し、ウィジェットの高さに応じて「次発のみ」「次々発まで」「3本目まで」を自動出し分け。
3. **GitHub Actions 自動 APK ビルド**:
   - プッシュ時に自動で `company-bus-widget.apk` をビルドし、GitHub Releases (`bus-widget-latest`) に公開するワークフローを構築（Android SDK セットアップステップの非推奨パッケージエラーを解消済み）。
