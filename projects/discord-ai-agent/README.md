# Discord連携 Mac mini AIエージェント (`#gemini-agent`)

スマホ（Galaxy S26 Ultra）やタブレット（Galaxy Tab）の **Discordアプリ** から専用チャンネル（`#gemini-agent`）にメッセージを送るだけで、自宅の Mac mini 上で **Antigravity CLI (`agy`)** が即座に起動し、リポジトリの調査・ファイル作成・編集・GitHubへのプッシュ・返信までを自動で行うシステムです。

> **なぜこの構成になったか（設計背景）:**
> 当初検討した GitHub Actions ＋ 無料版 `GEMINI_API_KEY` の組み合わせは、1日20リクエスト制限と混雑によるタイムアウトが多発し、また旧 `gemini` CLI の個人無料枠も提供終了となりました。そこで、すでに音楽自動化で安定稼働している **Discord × Mac mini 常駐環境** を活かし、後継の **`agy` CLI** をリアルタイムで呼び出す方式を採用しています。

---

## 1. システム全体像（アーキテクチャ）

```text
[Galaxy S26 Ultra / Galaxy Tab (Discord)]
  │ ① #gemini-agent チャンネル（またはスレッド）に指示を投稿
  ▼
[Mac mini 常駐Bot (projects/discord-ai-agent/bot.py)]
  │ ② サーバー所有者本人か確認し、即座に「🤖 受け付けました」を返信
  ▼
[Antigravity CLI (agy -p --sandbox --mode accept-edits)]
  │ ③ AGENTS.md に従ってリポジトリ内を調査・ファイル作成・編集
  ▼
[Mac mini Bot が自動で GitHub へ反映＆Discordへ返信]
  │ ④ 変更があれば git commit & push し、結果をDiscordに通知！
```

### 音楽自動化 Bot (`#mac-control`) との独立性
- `projects/music-automation/bot.py` とは **完全に別のプロセス** として動くため、AIの処理中に朝の目覚まし音楽再生がブロックされることはありません。
- `DISCORD_BOT_TOKEN` は設定がなければ `projects/music-automation/.env` のトークンを自動で共有利用するため、新しいBotを作り直す手間なく導入できます。

---

## 2. 安全設計（セキュリティ）

1. **実行者の制限**
   - Discordサーバーの **所有者（Owner）本人**（または `.env` の `DISCORD_ALLOWED_USER_IDS` で指定したID）以外の書き込みは無視します。
2. **サンドボックス制限 (`--sandbox`)**
   - `agy` はターミナルサンドボックス付きで起動するため、`my-lab` 以外の重要なMac設定ファイルを勝手に壊すリスクを抑えています。
3. **会話の分離（スレッド対応）**
   - Discord の **スレッド機能** を使うと、スレッドごとに独立した会話履歴（`conversation_id`）を保持できます。`!new`（または `リセット`）でいつでも会話をリセット可能です。

---

## 3. セットアップ手順

### Step 1: Discordに `#gemini-agent` チャンネルを作る
1. スマホまたはMacのDiscordアプリで、自分のサーバー（`#mac-control` があるサーバー）を開きます。
2. テキストチャンネルの横の **「＋」** を押し、**`gemini-agent`** という名前のチャンネルを作成します。
   - （※すでに `MacMagicBot` がサーバーに参加しているので、招待作業は不要です）

### Step 2: Python仮想環境を作って常駐起動する（Mac mini ターミナル）
```bash
cd ~/my-lab/projects/discord-ai-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp com.mylab.discord-ai-agent.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mylab.discord-ai-agent.plist
```

### Step 3: 起動確認
```bash
tail -n 20 ~/my-lab/projects/discord-ai-agent/bot.log
```
`✅ Discord AIエージェント起動:` と表示されていれば準備完了です！

---

## 4. 使い方（Discord からのコマンド・指示例）

`#gemini-agent` チャンネルにそのまま日本語で話しかけるだけで動作します。

- **通常の依頼例:**
  - `README.mdを読んで現在のプロジェクト構成を教えて`
  - `docs/ideas.md を作って、睡眠前にMacをスリープさせるアイデアをまとめて`
- **便利な組み込みコマンド:**
  - `!help`（または `ヘルプ`）：使い方を表示
  - **`!bg <指示>`**（または `!裏 <指示>`）：**裏エージェント**を別プロセス＆時間制限なしで起動（表チャットと同時並行OK・最大3並列・完了時に自動通知・音声/画像添付にも対応）
  - **`!bg #<番号> <続きの指示>`**：過去の裏エージェントの記憶を引き継いで続きを指示
  - **`!jobs`**（または `ジョブ`）：裏エージェントの稼働状況と経過時間を確認
  - **`!cancel <番号>`**（または `!cancel all`）：指定した裏エージェントを強制停止
  - `!new`（または `リセット`）：現在の会話の記憶をリセットして新しく始める
  - `!stop`（または `中断`）：表チャットで実行中の作業を強制終了
  - `!status`：`agy` のバージョン・裏エージェント稼働状況・`my-lab` の Git 状態を確認
  - `!restart`（または `再起動`）：Bot自身を再起動して最新コードを反映
