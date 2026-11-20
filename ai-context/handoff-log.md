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

## 完了プロジェクト（v1.0.0）: 社バス カウントダウンウィジェット (`company-bus-widget`)

- **設計・手順書:** [projects/company-bus-widget/README.md](../projects/company-bus-widget/README.md)
- **固定保管版 APK（v1.0.0・読み取り専用保護）:** [projects/company-bus-widget/releases/company-bus-widget-v1.0.0.apk](../projects/company-bus-widget/releases/company-bus-widget-v1.0.0.apk)
- **GitHub Releases 固定保管URL:** `https://github.com/ssdhouen361-ctrl/my-lab/releases/tag/bus-widget-v1.0.0`
- **時刻表データ:** [projects/company-bus-widget/app/src/main/java/com/mylab/buswidget/BusTimetable.kt](../projects/company-bus-widget/app/src/main/java/com/mylab/buswidget/BusTimetable.kt)
- **ウィジェット本体:** [projects/company-bus-widget/app/src/main/java/com/mylab/buswidget/BusWidgetProvider.kt](../projects/company-bus-widget/app/src/main/java/com/mylab/buswidget/BusWidgetProvider.kt)
- **アプリ本体画面:** [projects/company-bus-widget/app/src/main/java/com/mylab/buswidget/MainActivity.kt](../projects/company-bus-widget/app/src/main/java/com/mylab/buswidget/MainActivity.kt)
- **自動ビルド設定:** [.github/workflows/build-bus-widget.yml](../.github/workflows/build-bus-widget.yml)
- **最終更新:** 2026-11-19

### 実装・保管済みの内容（v1.0.0）
1. **時刻表画像からの全便データ化 (`1-1` 〜 `1-25`) と 2×2 ウィジェット最適化**:
   - デフォルトの「JR発 ➔ GNFJ（会社行）」と「GNFJ発 ➔ 駅（帰り）」をヘッダーの大きな `⇄ 切替` ボタンでワンタップ往復切替。
   - 便番号（`1-1` 等）やバスアイコンを省き、2×2サイズでも「次発」「次々発」「3本目」の発着時刻が見切れないレイアウトに調整。
2. **アプリ内の全体時刻表（5列テーブル）**:
   - 元の時刻表画像と同じ5列（`GNFJ発 | 京急(降) | JR発 | 京急(乗) | GNFJ着`）の全便一覧表と次発ハイライト表示を実装。
3. **v1.0.0 成果物の書き換え防止保管**:
   - ローカル＆Gitリポジトリ内の `projects/company-bus-widget/releases/company-bus-widget-v1.0.0.apk` に読み取り専用（`chmod 444`）で保管。
   - GitHub Releases にも上書きされない固定タグ `bus-widget-v1.0.0` としてリリースを作成済み。

### 次回アップデート（v1.1.0）の課題・ダメ出し記録
1. **ウィジェット内のフォント拡大:**
   - ウィジェット内の余白にまだ余裕があるため、余白を詰めて発車時刻・カウントダウン・次々発/3本目のフォントサイズを全体的に大きくする。
2. **アプリ内の時刻表の縦長解消＆カウントダウン表示のコンパクト化:**
   - アプリを開いた際、上部のカウントダウン表示が大きすぎて時刻表全体が縦に長くなり見づらいため、上部カウントダウンをスリム化し、時刻表の行間も詰めて一画面での一覧性を高める。
3. **Galaxy「モードとルーチン」での往復切替対応:**
   - ルーチンから「往路（JR発）に切替」「復路（GNFJ発）に切替」「往復トグル切替」を直接実行できるよう、専用のショートカット／アクティビティ（Activity Alias / App Shortcuts）を追加する。

---

## 完了プロジェクト: KataGo × KaTrain 囲碁AI 対局・検討環境 (`katago-env`)

- **手順書:** [projects/katago-env/README.md](../projects/katago-env/README.md)
- **ワンクリック起動スクリプト:** [projects/katago-env/launch-katrain.command](../projects/katago-env/launch-katrain.command)
- **最終更新:** 2026-11-19

### 導入・設定済みの内容
1. **KataGo v1.18.2（Apple M6 Metal GPU バックエンド）導入:**
   - Homebrew で `/opt/homebrew/bin/katago` および `python@3.12` を導入。
   - 同梱の最新強モデル `/opt/homebrew/share/katago/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz` を使い、Metal GPU 上で19路盤の高速解析が正常動作することを実機検証済み。
2. **KaTrain v1.20.0 導入・日本語＆高速設定済み:**
   - `projects/katago-env/.venv`（Python 3.12）に `katrain` を導入。
   - `~/.katrain/config.json` を事前設定し、初回起動時から **日本語UI・19路日本ルール（コミ6.5目）・Homebrew Metal版 KataGo＋b18c384nbtモデル** が自動で使われる状態にした。
   - Finder からダブルクリックで起動できる `launch-katrain.command` を作成済み。
3. **デスクトップショートカット＆遠隔ワンタップ起動連携:**
   - Mac mini のデスクトップに `KaTrain_囲碁AI.command` ショートカットを配置済み。
   - `projects/music-automation/bot.py`（`MacMagicBot` / `#mac-control`）に `katrain`（起動・最前面表示）および `katrain stop`（終了）コマンドを追加し、`launchd` を再起動して稼働済み。
   - Galaxy Tab 側で「HTTP Request Shortcuts（`{"content": "katrain"}`）」＋「モードとルーチン（手動で開始）」を組み合わせることで、ホーム画面1タップで「Mac mini の KaTrain 起動＋Chrome リモートデスクトップ起動」を同時実行可能。

---

## 完了・稼働中プロジェクト: 3台連携ネットワーク基盤構築（Tailscale）

- **環境プロファイル:** [ai-context/environment.md](environment.md)
- **構築ガイド:** [docs/device-network-setup.md](../docs/device-network-setup.md)
- **最終更新:** 2026-11-21

### 完了した内容
- Mac mini（App Store 版・ログイン時自動起動・`Disable key expiry` 有効化）・Galaxy S26 Ultra・Galaxy Tab の **3台 Tailscale 連携が完了**。
- Mac mini の簡易 Web サーバー（`python3 -m http.server 8888 --bind 0.0.0.0`）に対し、Tailscale 経由でブラウザからアクセスし一覧表示できることを実機確認済み。
- 将来別ツール（ZeroTier / Cloudflare Tunnel / NetBird 等）へ引っ越す可能性も見据え、今後載せるアプリは標準 HTTP 通信で非依存に設計する方針。

### 次のステップ候補（この土台の上に載せるもの）
1. **スマホ・タブレット対応 Web 碁盤（KataGo × Gemini）** — 設計構想書 [docs/web-goban-design.md](../docs/web-goban-design.md) を作成済み（未実装・構想フェーズ）。
2. **自動化基盤（n8n 等）や Obsidian / ローカル音声文字起こし（mlx-whisper）** の導入・連携
3. **社バスウィジェット v1.1.0 アップデート**（フォント拡大・時刻表スリム化・ルーチン連携）
