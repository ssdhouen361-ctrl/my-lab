# ユーザー環境・利用サービス一覧 (Environment Profile)

AIアシスタントが提案・開発・自動化設計を行う際の前提となる、ユーザーの利用端末・導入済みツール・普段使いのサービス一覧です。

最終更新: 2026-11-20

---

## 1. 端末・ハードウェア

- **Mac mini（Apple M6 / メモリ 16GB / macOS）**
  - メイン開発・常時稼働サーバー（スリープ防止・画面ロック自動解除設定済み）
- **Galaxy S26 Ultra（Android）**
  - モバイル指示・アイデア出し・日常メイン端末
  - Tailscale 導入・利用済み
  - 導入アプリ：Discord、HTTP Request Shortcuts、モードとルーチン、Good Lock（Home Up）、自作「社バスウィジェット」
- **Galaxy Tab（Android）**
  - ドキュメント閲覧・囲碁検討などの大画面操作
  - 導入アプリ：Discord、Chrome リモートデスクトップ、HTTP Request Shortcuts、モードとルーチン
- **ウェアラブル端末**
  - Galaxy Wearable アプリ利用（Samsung 製ウェアラブル連携）
- **スマートディスプレイ**
  - **Echo Show 5**（接続が不安定なため、現状はほぼ目覚まし時計としてのみ使用）

---

## 2. 普段使っているアプリ・サービス

### Samsung 純正アプリ群
- Samsung カレンダー
- Samsung メール
- Samsung Health（ヘルスケア）
- Samsung Notes（メモ・ノート）
- Samsung ブラウザ（Samsung Internet）
- Galaxy Wearable（ウェアラブル管理）

### Google 系サービス
- Google マップ
- Google ウォレット
- Google スプレッドシート
- Google ドキュメント

### コミュニケーション・音楽・ネットワーク
- LINE
- Discord（Mac mini 連携ハブ：`#gemini-agent` / `#mac-control`）
- Apple Music（Mac mini 起床自動再生用）
- **Tailscale**（Galaxy S26 Ultra で利用可能）
- GitHub（`ssdhouen361-ctrl/my-lab`）

---

## 3. Mac mini 稼働中・導入済み基盤

- **AIエージェント基盤**
  - Antigravity CLI (`agy`) ＋ Discord 常駐Bot（`projects/discord-ai-agent/bot.py`）
- **Mac 遠隔操作基盤**
  - `MacMagicBot`（`projects/music-automation/bot.py`：`music wakeup` / `music stop` / `katrain` / `katrain stop`）
  - `SwitchAudioSource` (`switchaudio-osx`)、AppleScript (`osascript`)、`launchd` 常駐
- **囲碁AI環境**
  - Homebrew `KataGo`（Metal GPU対応）＋ `KaTrain`（Python 3.12 `.venv`）
