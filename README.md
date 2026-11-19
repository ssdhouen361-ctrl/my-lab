# my-lab

AI支援による実験的開発やプログラミングの記録用リポジトリ。  
特定のAIサービスに依存しない共通規格（[AGENTS.md](AGENTS.md)）に基づき、試行錯誤の過程や成果を体系的に管理します。

## フォルダ構成

- `.github/workflows/` : GitHub Actions（クラウド自動実行）の設定ファイル
- `docs/` : 各プロジェクトの設計メモ・手順書
- `projects/` : プロジェクト別の専用フォルダ・プログラム本体
- `ai-context/` : AI間の作業引き継ぎログ（[handoff-log.md](ai-context/handoff-log.md)）

## 進行中のプロジェクト

- **[Galaxyアラーム連動 Apple Music自動再生](docs/music-automation.md)**  
  Galaxy S26 Ultraのアラーム鳴動時にDiscord経由でMac miniのApple Musicを自動再生するシステム（稼働中）。
- **[Discord連携 Mac mini AIエージェント](projects/discord-ai-agent/README.md)**  
  Discordの `#gemini-agent` チャンネルに指示を書くだけで、Mac mini上の Antigravity CLI (`agy`) が自律的に作業・GitHub反映・返信を行うシステム。
- **[社バス カウントダウンウィジェット (GNFJ)](projects/company-bus-widget/README.md)**  
  Yahoo!乗換案内風 × Galaxy「Home Up」対応の社バス発車カウントダウン Android ウィジェット（v1.0.0 完成・固定保管済み）。
- **[KataGo × KaTrain 囲碁AI 対局・検討環境](projects/katago-env/README.md)**  
  Mac mini（Apple M6）上で KataGo と定番ソフト KaTrain を動かし、Galaxy Tab からも19路盤の対局・検討を行う環境。
- **[スマホ連動 GitHub Issue AIエージェント](projects/github-issue-agent/README.md)** *(検証・保留)*  
  GitHub Issues に `@gemini-cli` と書き込むクラウド版ワークフロー（無料枠APIキーの1日20回制限により現在はDiscord版へ移行）。
