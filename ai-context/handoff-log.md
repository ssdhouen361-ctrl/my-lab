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

## 進行中プロジェクト: Discord連携 Mac mini AIエージェント (`#gemini-agent`)

- **設計・手順書:** [projects/discord-ai-agent/README.md](../projects/discord-ai-agent/README.md)
- **プログラム本体:** [projects/discord-ai-agent/bot.py](../projects/discord-ai-agent/bot.py)
- **常駐設定ファイル:** [projects/discord-ai-agent/com.mylab.discord-ai-agent.plist](../projects/discord-ai-agent/com.mylab.discord-ai-agent.plist)
- **最終更新:** 2026-11-18

### これまでの経緯と完了した作業
1. **GitHub Actions 版（`projects/github-issue-agent/`）の検証結果**:
   - `.github/workflows/gemini-cli.yml` を構築して動作確認を行ったが、Google AI Studio 無料枠（`gemini-3.8-flash`）の1日20リクエスト制限および夜間混雑（503エラー）により、無料APIキーでの安定運用は困難と判明。
   - また Mac mini 上の旧 `gemini` CLI（`0.68.0`）も個人向けログイン（`oauth-personal`）が提供終了済みであることを確認。
2. **Discord × Antigravity CLI (`agy`) 版への方針転換と実装**:
   - Mac mini に公式後継の `agy` CLI（`/Users/sasadayuto/.local/bin/agy`）を導入し、`-p --output-format json --mode accept-edits --sandbox` での非対話実行が正常動作することを確認。
   - `projects/discord-ai-agent/` に、`#gemini-agent` チャンネル（および配下スレッド）を監視して `agy` を呼び出し、変更があれば自動で `git commit & push` し、2000文字超えの返信も自動分割して返す Bot (`bot.py`) と `launchd` 設定を作成。

### 現在のステータス・次のタスク
- **現在進行中:**
  1. Discordサーバーに `#gemini-agent` チャンネルを作成。
  2. Mac mini で `projects/discord-ai-agent/.venv` を作成し、`launchd`（`com.mylab.discord-ai-agent.plist`）で常駐起動して実機テストを行う。
