# 作業引き継ぎログ (Handoff Log)

このファイルは、AIアシスタント間で作業の進捗と次のタスクを引き継ぐための記録です。

---

## 構想・計画中プロジェクト: 対話型囲碁検討AI「Go Live Coach」(仮称)

- **プロジェクトディレクトリ:** `projects/go-live-coach/` (新規立ち上げ予定)
- **ステータス:** **プロトタイプ（Phase 2/3）実装完了・自動テスト全件合格（6/6 passed）**
- **最終更新:** 2026-11-26
- **主要決定事項・成果物:**
  1. **プロジェクト本体:** [projects/go-live-coach/](../projects/go-live-coach/)
     - `app/main.py`: FastAPI Web/REST サーバー（ポート `8095`）
     - `app/rules.py`: 19路盤ルール・着手判定・ツリー管理
     - `app/slicer.py`: KataGo 361マス ownership からの局所地合い・厚み集計スライサー
     - `app/adapter.py`: 多重入れ子構造によるモデル切り替えアダプター（`.env` で `gemini-2.5-flash` や `3.5-flash` へ1行切替可能）
     - `static/index.html` / `style.css` / `app.js`: Galaxy Tab S11横画面特化の2層Canvas盤面＋手番ナビ（下部）＋Gemini対話UI
  2. **自動テスト:** [projects/go-live-coach/tests/test_coach_engine.py](../projects/go-live-coach/tests/test_coach_engine.py) にて、盤面ルール・アゲハマ・部分ワカレ計算・スマート発話要約・APIナビゲーションを検証し、**全件 PASS（6/6 passed）** を確認。
  3. **統合設計書:** [docs/go-live-coach-design.md](../docs/go-live-coach-design.md) を作成・承認済み。
  4. **配置ワイヤーフレーム:** [docs/mockups/tablet_layout_wireframe.png](../docs/mockups/tablet_layout_wireframe.png)

---

## 完了プロジェクト: Galaxy Watch / Wear OS ブラインド・タップタイマー「TacTicTap」

- **プロジェクトディレクトリ:** [projects/galaxy-watch-timer/](../projects/galaxy-watch-timer/)
- **決定アプリ名:** `TacTicTap` (タク・ティック・タップ)
- **ステータス:** **ベータ版実装・動作シミュレータ＆Wear OSコードベース完成（テスト全件合格）**
- **最終更新:** 2026-11-23

### 1. 実装・検証済みの内容
1. **完全視覚・ブラインド特化 UI/UX 設計の確立:**
   - 余計な説明文字を一切排除し、「設定中の桁のみハイライト」「それ以外の桁は透過40%で視認性維持」「下部1/3に繊細なヘアライン境界」のみで操作可能にするミニマルデザインを確立。
   - Galaxy Watch 8（480×480px）など全主要Wear OS解像度で余白を極限まで削ぎ落とし、110pt ➔ **150pt 特大フォント** によるレスポンシブスケーリングを実現。
   - 全6テーマ（ダーク3種：オレンジ/グリーン/モノクロ、ライト3種：アンバー/エメラルド/チャコール）を策定。
2. **ブラインド操作インタラクション状態機械:**
   - **大味タップ認識:** 画面上部2/3タップで `+1`、下部1/3タップで `-1`。
   - **スワイプ操作:** 左右スワイプで桁移動（分十 ⇄ 分一 ⇄ 秒十 ⇄ 秒一）、上スワイプで即カウントダウン開始、下スワイプでリセット。
   - **アラーム停止:** 鳴動中は画面のどこでもワンタップするだけで即停止・設定画面へ復帰。
3. **インタラクティブ Web シミュレータ（ベータ版）の実装:**
   - [app/static/index.html](../projects/galaxy-watch-timer/app/static/index.html)
   - [app/static/style.css](../projects/galaxy-watch-timer/app/static/style.css)
   - [app/static/app.js](../projects/galaxy-watch-timer/app/static/app.js)
   - Web Audio API を用いた触覚・音響フィードバックシミュレーション、円形480pxウォッチベゼル描画、6テーマ切替、Galaxy Watch 8 / Pixel Watch 端末サイズシミュレーションを完備。
4. **Wear OS (Compose for Wear OS / Kotlin) ネイティブ実装:**
   - [wear-os-app/src/main/java/com/mylab/tactictap/MainActivity.kt](../projects/galaxy-watch-timer/wear-os-app/src/main/java/com/mylab/tactictap/MainActivity.kt)
   - Circular Compose Canvas と `detectTapGestures` / `detectDragGestures` によるネイティブタッチハンドラ、6テーマカラー定義を完全移植。
5. **自動テスト・品質検証:**
   - [tests/test_engine.py](../projects/galaxy-watch-timer/tests/test_engine.py) にて状態遷移・上下タップ境界・桁制限（分十位は5までなど）・ループ処理・アラーム停止など計9件の自動テストを作成し、**全件 PASS（9/9 passed）** を確認。

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
   - **汎用バックグラウンド専属エージェント機能（`!bg` / `!bg #<番号>` / `!jobs` / `!stop <番号|all>`）を実装（2026-11-21）**:
     - 表チャットと独立した非同期サブプロセスとして時間制限なし（`--print-timeout 0s`）・最大5並列で起動でき、完了時に自動で Git 反映＆Discord通知を行う汎用仕組みを追加（各裏エージェント内で複数サブエージェントによるチーム議論・審査統合も可能）。
     - 停止コマンドは `!stop`（表）・`!stop <番号>`（裏）・`!stop all`（全停止）に統合し、混同を防止。
   - **表チャット／裏エージェントのモデル＆思考量（effort）使い分け機能を実装（2026-11-21）**:
     - 初期値で表チャット=`effort: low`（高速応答）、裏エージェント=`effort: high`（高品質開発）へ自動分離。
     - Discord 上から `!models`（`agy models` 実行）・`!model [bg] <name|default|reset>`・`!effort [bg] <low|medium|high|xhigh|max|default>` で自在に切替可能とし、`.model_settings.json`（`.gitignore` 追加済み）へ永続化。
     - 表・裏同時実行時の Git 競合を防ぐ専用 `_git_lock` と、裏ジョブ継続用の `.bg_conversations.json`（`.gitignore` 追加済み）を実装。

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
1. **自動化基盤（n8n 等）や Obsidian / ローカル音声文字起こし（mlx-whisper）** の導入・連携
2. **社バスウィジェット v1.1.0 アップデート**（フォント拡大・時刻表スリム化・ルーチン連携）

---

## 開発中プロジェクト（v1.0.0 実装完了）: Galaxy Watch / Wear OS ブラインド・タップタイマー＆アラーム (`TacTicTap`)

- **設計書 & モックアップ:** [projects/galaxy-watch-timer/README.md](../projects/galaxy-watch-timer/README.md)
- **プログラム本体:**
  - UI・状態機械（Jetpack Compose for Wear OS）: [projects/galaxy-watch-timer/app/src/main/java/com/mylab/tactictap/MainActivity.kt](../projects/galaxy-watch-timer/app/src/main/java/com/mylab/tactictap/MainActivity.kt)
  - 6大テーマ定義: [projects/galaxy-watch-timer/app/src/main/java/com/mylab/tactictap/Theme.kt](../projects/galaxy-watch-timer/app/src/main/java/com/mylab/tactictap/Theme.kt)
  - アラーム・バックグラウンド鳴動: [projects/galaxy-watch-timer/app/src/main/java/com/mylab/tactictap/AlarmReceiver.kt](../projects/galaxy-watch-timer/app/src/main/java/com/mylab/tactictap/AlarmReceiver.kt)
  - 仮想ブラインド操作テストプレイ検証: [projects/galaxy-watch-timer/tests/test_playtest.py](../projects/galaxy-watch-timer/tests/test_playtest.py)
  - 自動APKビルド設定: [.github/workflows/build-tactictap.yml](../.github/workflows/build-tactictap.yml)
- **ステータス:** **v1.0.0 ネイティブアプリ実装完了・自動ビルド環境整備済み**
- **最終更新:** 2026-11-23

### 実装済みの仕様と特徴
1. **大味ブラインド操作の完全実現:**
   - 画面上部 2/3: `+1` 加算 / 画面下部 1/3: `-1` 減算。
   - 左スワイプ（⬅）または ダブルピンチ: 次の桁へ進む。
   - 上スワイプ（⬆）: 残り桁を00にして即スタート（フリック一発で15分タイマー等を2秒セット）。
   - 下スワイプ（⬇）: 1手戻る（Undo） / 最初の桁で全リセット。
   - タイマー鳴動時: 画面のどこでもポンと1タップまたはダブルピンチで即停止。
2. **誤リセット防止の2段階安全設計:**
   - 動作中は誤って下スワイプしてもリセットされず、画面タップで「一時停止（ポーズ）」にした状態でのみ下スワイプでリセット可能。
3. **全6大カラーテーマ & コロン点滅演出:**
   - アンバーオレンジ（ダーク/ライト）、エメラルドグリーン（ダーク/ライト）、モノクロ（ダーク/ライト）。
   - 画面長押しでテーマを瞬時に切り替え可能。
   - 動作中は中央の「 : 」（コロン）が1秒周期で滑らかにフェード点滅。
4. **自動テストプレイ検証（全件 PASS）:**
   - 画面説明を一切見ないブラインド操作シナリオ（33:24入力、上スワイプ即スタート、誤リセット防止、一時停止リセット）をシミュレータで検証し、100% PASS を確認。


- **統合設計書:** [docs/web-goban-design.md](../docs/web-goban-design.md)
- **手順書:** [projects/web-goban/README.md](../projects/web-goban/README.md)
- **バックエンド本体:** [projects/web-goban/app/main.py](../projects/web-goban/app/main.py)
- **フロントエンド本体:** [projects/web-goban/static/index.html](../projects/web-goban/static/index.html)
- **KataGo 設定:** [projects/web-goban/config/katago_analysis.cfg](../projects/web-goban/config/katago_analysis.cfg)
- **セットアップ＆QA スクリプト:** [projects/web-goban/scripts/setup.sh](../projects/web-goban/scripts/setup.sh) / [projects/web-goban/scripts/qa.sh](../projects/web-goban/scripts/qa.sh)
- **常駐設定:** `~/Library/LaunchAgents/com.mylab.web-goban.plist`（Mac mini `gui/501/com.mylab.web-goban` にて常駐稼働中）
- **最終更新:** 2026-11-23

### プロジェクト概要と実用化ステータス
- **ステータス:** **実用圏内到達によりクローズ（完了・運用中）**
- Galaxy S26 Ultra（スマートフォン縦画面）および Galaxy Tab S11（タブレット横・縦画面）から、Tailscale 経由でストレスなく KataGo 高精度AI解析・検討・分岐作成・Geminiコーチ解説・音声読み上げが利用可能な状態を達成。
- 今後新たなアイデアや要望が出た場合は、改善案メモ（下記）に追加して適宜バージョンアップを行う方針。

### 実装・検証済みの内容（Phase 1：Step 1-A / Step 1-B / Layer 1〜3 QA 基盤）
1. **Step 1-A（バックエンド土台）:**
   - Apple M6 / 16GB・KaTrain 共存向け `config/katago_analysis.cfg`（実機 KataGo v1.18.2 で全 23 パラメータ警告ゼロ読込・GPU-only MPSGraph 認識を確認済み）。
   - 単一ソースの座標変換（`coords.py`：9/13/19 路・`I` 除外・圧縮矩形・パス正規化）、囲碁ルール＆非再帰 SGF パーサ／原子的置換保存（`rules.py`：自殺手・単コウ・多子打ち上げ・置き石 `komi=0.5`/`W` 先手・CP932/GB18030/破損耐性・7 要素 `position_hash`）。
   - SQLite WAL 永続化（`db.py`：直列書込・`analysis_cache` 高 visits 保護）、KataGo NDJSON 管理（`katago_engine.py`：8MB `stdout` 上限・`stderr` 常時ドレイン・2 段ハンドシェイク・3 段キャンセル・`terminated_ids` キャッシュ非汚染・4 手チャンク一括検討と対話割り込み即時 `PAUSED_FOR_INTERACTIVE`・KaTrain 同時稼働検知とアイドル 15 分→3 分短縮・AI 強さ Softmax 温度選択）。
   - 複数端末 WebSocket 同期（`game_hub.py`：`expected_version` 楽観ロック・端末ローカル `navigate` 分離・45 秒ゾンビ掃除）および厳密 Origin 検証付き FastAPI（`main.py`）。
2. **Step 1-B（フロントエンド UX＆無痛移行土台）:**
   - ビルド不要の Vanilla HTML / CSS / ES Modules 構成（`#1A1D21` ダークテーマ統一・`--app-inset-*` 安全領域統一・盤面レイアウトシフト `0.0px`・全ボタン `>= 44×44px`＆間隔保証）。
   - 2 層 Canvas 盤面（`goban-canvas.js`：非整数 DPR 物理ピクセルスナップ・9/13/19 路・CUD 色＋枠形状候補手・半透明 PV 石・地合いヒートマップ＆死活 `×`・Lv3 ヒント枠）。
   - 3 モードレスポンシブ（S26 Ultra 縦＋自動縮退する可変ミニ情報帯＆2 段ボトムシート／Tab S11 縦常設パネル／Tab S11 横フルハイト正方形盤面＋右統合パネル・左利き反転可）。
   - `PointerEvent` 状態機械（`input-controller.js`：初回 0px 仮置き→移動 >8px で上 `52px` イージング＆上端 5 路 Smoothstep 減衰・2 本指ピンチ 2.5x＆`200ms` ガード・Sペン Air View ホバー 80/50ms＆0ms 即消去＆`350ms`＋大面積パームリジェクション）。
   - `PlatformBridge`（`platform-bridge.js`：`window.WebGobanNative` / `window.WebGobanApp` 契約・WebView 時は SW 自動スキップ）と 15s/5s Heartbeat 対応 `ws-client.js`・SVG 勝率/目数グラフ・日本語囲碁 TTS 整形。
3. **Layer 1〜3 仮想自動試験基盤＋運用スクリプト:**
   - 本番完全隔離（`tmp_path`・エフェメラルポート・OS パイプ型 `FakeKataGoSubprocess`）の Layer 1 pytest スイート、Layer 2 Playwright 6 仮想端末＆7 大品質ゲート、Layer 3 厳選 10 枚決定論的スクショ撮影＆リポジトリ外隔離 `agy` CLI 8 項目ルーブリック審査スクリプト、`setup.sh` / `qa.sh` / `com.mylab.web-goban.plist` を整備。
   - サンドボックス内で実行可能な全検証（Layer 1 純 Python スイート 35/35 全 PASS・Node.js JS 構文＆入力数学テスト全 PASS・`katago_analysis.cfg` 実機パース確認・`bash -n`・`plutil -lint`・JSON/XML 検証）を通過済み。

### 直近の改善（スマホ・タブレット実機操作性向上）
- **再タップ着手確定（指・Sペン両対応）:** `input-controller.js` の状態遷移（`TOUCH_DOWN` 漏れ）を修正し、指・Sペンを問わず「仮置き石をもう一度タップして着手」を確実に発火するように改修。
- **盤面視認性・操作性向上:** 盤面キャンバス上に重なって目視・タップを阻害していた分岐バッジを盤面外（上部ヘッダーおよび下部アクションバー）へ完全移設。
- **右下リロードボタン追加:** 片手操作しやすい画面右下に「🔄 更新」ボタンを配置。
- **碁盤下スペースへの解析・詳細ウィンドウ常時固定表示（インライン統合化）:**
  - 碁盤と最下部ツールバーの間のスペースに、解析ウィンドウ（ヘッダー・タブ切替・コンテンツ）をインライン要素として常時固定配置。
  - 旧「ミニ情報帯（勝率推移・候補手チップ）」と重複していた構造を整理統合し、盤面下の固定枠内で「候補手」「グラフ」「🤖Gemini」「分岐」の4つのタブをスムーズに切り替え可能に。
  - 右上の最大化ボタン（`⤢` / `⤡`）または「詳細」ボタンで画面全体（全画面）への拡大・縮小も即座に行えるよう設計。
- **リロード時の分岐棋譜・局面維持:**
  - 着手やノード移動時にブラウザURLへ `?game=...&node=...&move=...` をリアルタイム反映。
  - 更新ボタン押下時やリロード時に、直前の分岐先・手番がそのまま復元されるよう改善。
- **ServiceWorker キャッシュ更新:** バージョンを `v10` に更新し、スマホ実機の再読み込みで新レイアウトが即座に反映されるよう設定。
- **Android 専用アプリ版（極薄 WebView ラッパー）の構築 & アプリ名「AetherGo」への刷新:**
  - `projects/web-goban/android/` 配下に Kotlin + Android Gradle プロジェクトを作成。
  - アプリ表示名を **「AetherGo」** に設定。
  - 起動エラー（`You need to use a Theme.AppCompat theme`）の原因だったテーマ設定を、正規の `Theme.AppCompat.NoActionBar` を継承した `@style/AppTheme`（ダーク `#1A1D21` 統一）に完全修正。
  - フロントエンドの `PlatformBridge`（`WebGobanNative`）と連動し、Android のシステム「戻る」ジェスチャー（詳細ウィンドウ閉じる ➔ 仮置き取消 ➔ 1手戻る）および常時点灯（`FLAG_KEEP_SCREEN_ON`）、ハプティクス（微小振動）、SGF 共有インテント受付を実装。
  - `.github/workflows/build-web-goban-apk.yml` を整備し、コミット時に GitHub Actions 上で自動ビルドされ、GitHub Releases（タグ: `web-goban-latest`）から `.apk` を直接ダウンロードできるように自動化。
- **Phase 2（Gemini AI コーチ基盤）の先行着手＆UIエンドポイント接続:**
  - `app/schemas/coach.py`: 単発解説・段階ヒント・1局振り返りの厳密 Pydantic / JSON Schema を定義。
  - `app/fact_bridge.py`: 確定ファクト抽出器（`GoFactBridge`）・大差局面判定（`is_garbage_time`）・盤サイズ別悪手/好手判定（`classify_move_quality`）・エリア名マッピングを実装。
  - `app/coach_provider.py`: 決定論的オフライン・ルールベースフォールバックコーチ（`RuleBasedFallbackCoach`）を実装。
  - `app/main.py`: `POST /api/v1/games/{game_id}/coach/explain`（悪手解説）および `hint`（段階ヒント）REST エンドポイントを追加。
  - `static/js/ui-shell.js`: 「🤖Gemini」タブ内に「❓ なぜ悪手・損失？」「💡 次の一手ヒント」ボタンを配置し、API から受信した解説カードや方針ヒント、思考の問いかけ、音声読み上げ（TTS）への連動を実装。
  - `static/css/app.css`:
    - S26 Ultra 縦画面での「解析・詳細」ウィンドウの高さとヘッダー（44px ➔ 32px）、タブバー（48px ➔ 34px、タブボタン 44px ➔ 30px）をスリムに凝縮しスマート化。
    - ウィンドウ最大化（広げた）時にも、画面下半分（`top: 48dvh`）に展開するよう調整し、碁盤が隠れず常に盤面と解説を同時に見渡せるレイアウトに改良。
  - `static/sw.js`: キャッシュバージョンを `v12` に更新。
  - `tests/unit/test_coach_and_facts.py`: ファクト抽出およびフォールバック解説の単体テストを整備し全件 PASS。

- **直近の改善（レイアウト微調整 & タブ・ボタン・E2Eテストプレイ品質検証）:**
  - `static/css/app.css`:
    - 操作バー（`action-bar`）およびグラフバー（`graph-toolbar`）内の各ボタン間隔を `8px` に確保し、誤タップ防止と品質ゲート（Gate 3: 間隔基準）を完全充足。
    - 最上部ヘッダーの本譜復帰ボタン（`top-branch-btn`）およびズームリセットボタン（`pill-action-btn`）の最小タッチターゲットを `44×44px` に確保。
    - グラフ SVG を 108px、凡例、候補手リスト等の縦幅・マージンを調整し、画面内での視覚情報の見切れや重なりを解消。
    - 下部タブを広げた（`full`）際、画面上半分（`top: 48dvh`）に留めることで、碁盤全体（1〜19路）が隠れず常に盤面と解析内容を同時に見渡せる状態を維持。
    - 下部シートの内部スクロール領域（`#sheet-body`）の下部余白を `calc(72px + var(--inset-bottom))` に拡大し、候補手一覧・グラフ凡例・Gemini解説・分岐ボタンの最下部が下部ナビゲーションバー（戻る/進む/検討/詳細/更新/Menu）に重ならず完全に視認・操作できるよう改善。
    - 下部タブ展開時（`full`）に碁盤ステージ（`#board-stage`）が上部エリア（高さ約 `48dvh`）に収まるよう自動縮小するレスポンシブスタイルを追加し、碁盤全体（1〜19路）の全景と詳細タブを同時に完全視認可能に。
  - `static/index.html` & `static/js/ui-shell.js`:
    - メニュー（Menu）内に「アプリ情報・バージョン」カードを追加。
      - アプリ名称（AetherGo）、クライアントビルドID、サーバー接続バージョン、実行環境（Android専用アプリ / PWA / ブラウザ）を表示。
      - 「🔄 強制再読み込み (キャッシュクリア)」ボタンを設置（CacheStorage全消去＋SW登録解除＋強制リロード）。
    - 手番・局面移動時の AI コーチ自動リセットおよび「🔄 閉じる」ボタン配置。
    - 下部タブ展開時のキャンバスリサイズ連動（`_resizeBoardFromStage`）を追加。
  - `app/main.py`:
    - AIコーチ解説（`coach_explain`）で `node.position_hash` を直接参照してクラッシュしていたバグを修正（`session.tree.position_hash(node.node_id)` で正しく算出）。
    - これにより「❓ なぜ悪手・損失？」「💡 次の一手ヒント」ボタンが 500 エラーにならず即座に応答を返すよう完全修正。
  - `static/sw.js`: キャッシュバージョンを `v17` に更新。
  - **根本原因の特定と重なり解消（タブボタンと候補手1行目の被りバグ修正）:**
    - ユーザーから指摘された青線で囲まれた部分（「候補手」「グラフ」「🤖Gemini」「分岐」タブが、下の詳細コンテンツの1行目と重なって文字が読めなくなっていた現象）の根本原因を特定。
    - **原因:** タブバーのコンテナ（`#sheet-tabs`）の高さが `34px` に指定されていた一方、アクセシビリティ・誤タップ防止基準である大原則「すべてのボタンは最低 44px」に従って内部のボタン（`.panel-tab`）が `44px` で描画されていたため、ボタンの下部 `10px` 分がコンテナをはみ出し、直下のコンテンツ（候補手1行目 `1. Q16...`）の文字に覆いかぶさって重なっていました。
    - **修正内容 ([app.css](file:///Users/sasadayuto/my-lab/projects/web-goban/static/css/app.css)):**
      - `#sheet-tabs` の高さを `34px ➔ 46px` に修正し、ボタン（`height: 44px; min-height: 44px;`）がコンテナ内に完全に収まるよう整合。
      - これにより、タブボタンと下の詳細記載（候補手、グラフ、Gemini解説、分岐一覧）の間に確実な余白（`7px`）が生まれ、重なりが完全に解消されました。
  - **直近の改善（各タブコンポーネントのスリム化＆タブ拡大時画面下部スペースの完全有効活用）:**
    - `static/css/app.css`:
      - **候補手（Candidate）カードのスリム化:**
        - `.cand-row` の内余白を `4px 8px`、gap を `6px` に圧縮。着手表記フォントを `13px`、勝率・目数表示を `11px` に微縮小。
        - 候補手の変化図（PV）ボタンの横幅・フォントをコンパクト化（44px の最小タッチターゲット規格を維持）。
      - **評価値グラフ（Evaluation Graph）のコンパクト化:**
        - グラフ SVG の高さを `110px ➔ 88px` に最適化。
        - ツールバー高さを 30px、凡例（大悪手・悪手・不急…）の余白を `2px`、フォントを `10px` にスリム化。
      - **勝率バー（Winrate Bar）:**
        - 最上部の勝率ゲージバー高さを `10px ➔ 8px` にスリム化。
      - **分岐・情報カード（Branch & Game Info）:**
        - カードのパディングを `8px 10px`、グリッド gap を `4px 8px`、フォントを `11px` に凝縮。
      - **Gemini コーチカード（Gemini Coach Card）:**
        - カードパディングを `8px 10px`、見出し・解説文・各アドバイスボックスの余白を凝縮し無駄な縦スペースを排除。
      - **タブ拡大時（full）の画面下側スペースの完全有効活用:**
        - タブを広げた（`full`）際は下部ナビゲーションツールバー（`#bottom-toolbar`）を自動非表示化。
        - 詳細シートの下端（`bottom`）を画面最下部セーフエリア（`var(--inset-bottom)`）まで完全解放。
        - これにより、拡大時は下部バーで隠れることなく、画面下端いっぱいに詳細コンテンツ（候補手・グラフ・Gemini解説）が広大な領域で展開され、スペースを100%活用できるように改良。
  - **テストプレイ・自動品質検証（E2E / 単体）:**
    - Galaxy S26 Ultra（Portrait / Narrow / Short）、Galaxy Tab S11（Landscape / Landscape+Bar / Portrait）の全 6 仮想プロファイルによる Playwright E2E テスト（7大品質ゲート：水平スクロール 0px、44px タッチターゲット、ボタン間隔 8px、ビューポート内収束、盤面シフト 0.0px、2層キャンバス描画、ランタイムエラー 0）を実行し、**全 6 プロファイル ALL PASS** を達成。
    - 単体テスト（42/42 件）およびタッチ・Sペン・WebViewテストも全件 PASS。
    - Mac mini 本体のサービス（`launchd`）を再起動し、最新版コードで正常稼働中。

  - **直近の改善（KataGo候補手のPV長大化・「打進む」検討譜分岐機能・試行回数表示）:**
    - **PV（変化図）の長大化:**
      - [goban-canvas.js](file:///Users/sasadayuto/my-lab/projects/web-goban/static/js/goban-canvas.js): 盤上に描画する変化図（PV）の最大手数をコンパクト時 `5 ➔ 10手`、通常時 `8 ➔ 15手` に拡大。
      - [ui-shell.js](file:///Users/sasadayuto/my-lab/projects/web-goban/static/js/ui-shell.js): 候補手リスト内のPV着手系列テキスト表示を従来の6手から最大15手まで表示するよう拡張。
      - [app.css](file:///Users/sasadayuto/my-lab/projects/web-goban/static/css/app.css): 長いPV表記がはみ出さないよう横スクロール（スクロールバー非表示）に対応。
    - **試行回数（Visits）の明示表示:**
      - [ui-shell.js](file:///Users/sasadayuto/my-lab/projects/web-goban/static/js/ui-shell.js): 各候補手カードの勝率・目数差の横に「(試行:◯◯回)」を明示表示。
    - **変化図の続きから検討譜を打ち進める機能（「打進む」ボタン）の実装:**
      - [ui-shell.js](file:///Users/sasadayuto/my-lab/projects/web-goban/static/js/ui-shell.js): 候補手カード右側に「PV▶（表示）」と並んで「打進む」ボタン（`.cand-branch-btn`）を追加。
      - 「打進む」をタップすると、その候補手のPV変化図（最大15手）を400ms間隔で順次自動着手して新規分岐ノード（検討譜）をツリー上に生成・展開。
      - 盤面が見えやすいよう自動でシートをドック位置（下部）へ調整し、展開完了時に「変化図の展開が完了しました。続けて検討譜を自由に着手できます。」とトースト案内を表示。
      - 展開後はそのまま碁盤をタップして検討譜の続きを自由に着手・探索可能。
    - **タッチ・ピンチズーム操作の安定化:**
      - [input-controller.js](file:///Users/sasadayuto/my-lab/projects/web-goban/static/js/input-controller.js): 2本指ピンチ操作終了時のタップ誤認識防止ガード（200ms）を、指が1本離れた瞬間から確実に発動するよう修正。
    - **Service Worker / キャッシュ更新:**
      - [sw.js](file:///Users/sasadayuto/my-lab/projects/web-goban/static/sw.js): キャッシュバージョンを `v18` に更新。
    - **テストプレイ・自動品質検証（E2E / 単体）:**
      - Playwright E2E テスト（全6プロファイル・タッチ/Sペン操作・WebView同期含む11件）および単体テスト（42件）を全件実行し、**計53件すべて ALL PASS** を確認。
    - **サーバー反映:**
      - Mac mini の常駐サービス（`launchd: com.mylab.web-goban`）を kickstart 再起動し、最新版コードで正常稼働中。

### 今後の改善案・アイデアメモ（次回アップデート用）
- **次回アップデート計画（計算パワー引き上げ＆初動高速化・段階的確実化）:**
  - **初動の高速化と最終棋力の両立アーキテクチャ（プログレッシブ探索）:**
    - 単純な複数モデル同時起動（GPUメモリ・競合課題）ではなく、KataGo Analysis Engine の `reportDuringSearchEvery`（段階的途中報告）機能を活用。
    - **動作フロー:**
      1. 着手直後（0.1秒〜0.2秒・Visits 30〜50回程度）に初動の候補手・勝率を盤上へ即座にプレビュー表示（初動レスポンス極大化）。
      2. ユーザーが考えている間にバックグラウンドで同じKataGoプロセスが探索を継続（Visits 500回まで深掘り）。
      3. 最善手・正確な目数差・長大な変化図へシームレスに更新（棋力・正確性の100%維持）。
    - これにより、メモリ消費やGPUリソースの無駄遣いなしに「初動は爆速、最終的には最高峰の棋力」を両立。
  - **エンジン設定のチューニング:**
    - `config/katago_analysis.cfg` のバッチサイズ・スレッド数最適化（M6 Metal GPUリソースをフル活用）。
  - **Gemini AI コーチングの高度化（アマ高段者向けプロ棋士YouTube解説の自律学習・知識蓄積）:**
    - **深遠な変化図見通し（長大PV・先読み解説）の設計:**
      - 盤面UI上のプレビューは15手で十分だが、Geminiの解説生成時にはKataGoから**30手〜50手先までの深遠な読み筋（終局または死活・定型収束まで）**をテキストとして渡す。
      - **計算・時間コスト検証:**
        - KataGoの探索処理において、訪問数（Visits）さえ十分あれば、探索木の中から最善手系列を15手から30〜50手取り出す処理自体は**ミリ秒単位（追加コストほぼゼロ・0.1秒未満）**で取得可能。
        - Geminiに渡す文字数がわずか数行増えるだけであるため、APIの待機時間も **0.5秒〜1秒程度** しか変わらない。
        - したがって、コストや待ち時間の増加をほぼ気にすることなく、「20〜30手先に石が死ぬ・地合いが確定する結末」まで見通した大局的解説を実現可能。
    - **進捗（プロの生きた自然言語コーパス学習へ方針転換）:**
      - プロ棋士の対局検討・指導対局における思考連鎖（「大場より急場 ➔ ケイマの薄み ➔ 寄り付き ➔ もたれ攻めで厚みを働かせる ➔ アジの消去」）の言語パターンを詳細リサーチ・収集。
      - [knowledge/go_coach/pro_commentary_patterns.md](../projects/web-goban/knowledge/go_coach/pro_commentary_patterns.md) を、30〜50手先の結末を見通した因果関係ダイアログ集（序盤の薄み放置が30手後の死活に響く必然の帰結、捨て石とカスの石、モタレと厚みの呼吸、逆先手とアジ消し）として大幅拡充。
      - 単なる分類ではなく「なぜ今の一手が30手先の破綻に繋がるのか」を有段者が腹落ちする生きた言葉として整理。
    - **対象棋力・解説レベルのターゲット設定:**
      - アマ5段クラス（有段・高段者レベル）。入門者向けの当たり前の説明（石の取り方や極端な基礎）は省き、「形勢判断の焦点」「石の軽重・利き筋」「大局観・サバキやモタレ」「厚みの働かせ方」「ヨセの出入り」など、高段者が納得する深い論理的解説を指向。
    - **自律的学習（収集・構造化パイプライン）のアーキテクチャ:**
      - Mac mini 上の裏エージェント（`!bg` や定期バッチ）を活用し、プロ棋士の公式YouTubeチャンネル（例：芝野虎丸九段・一力遼棋聖・つるりんチャンネル・洪道場等の対局解説）から字幕・音声（`yt-dlp` / ローカル `mlx-whisper`）を取得。
      - Gemini を使って「KataGo等の局面データに対するプロ棋士特有の着眼点・思考プロセスの言い回し・局面の要約パターン」を自動抽出し、ナレッジDB（高段者向け思考辞書）として構造化保存。
      - この知識ベースをコーチングプロンプトに注入することで、常に進化し続けるプロ棋士レベルのAI検討パートナーを実現。
- **KataGo 公式モデル・本体の自動監視と反映設計:**
  - 最適な監視周期：**週1回（毎週日曜の深夜など）** のチェック。
  - 最新モデルの自動取得・差し替え・サービス再起動・Discord通知。
- 候補手や変化図のさらなる分岐管理・ツリー可視化の拡張
- 対局・検討棋譜の外部エクスポート/インポート機能（SGFファイル共有など）
- その他実戦で気になった点やユーザーからの追加要望事項

---
