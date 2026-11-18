# Galaxyアラーム連動 Apple Music自動再生システム 設計・手順書

Galaxy S26 Ultraのアラーム鳴動をトリガーにして、Discord経由でMac miniのApple Music（指定プレイリスト `WakeUp`）を自動再生するプロジェクトの設計書および運用マニュアルです。

---

## 1. システム全体像（アーキテクチャ）

スマホとMacを直接通信させるにはネットワーク設定が複雑になるため、**Discordを中継所（ハブ）として使う**ことで、安全かつ簡単に連携させています。

```text
[Galaxy S26 Ultra]
  │ ① アラーム解除（モードとルーチン → HTTP Request Shortcuts）
  ▼
[Discord Webhook]
  │ ② 専用チャンネル（#mac-control）に「music wakeup」と自動投稿
  ▼
[Mac mini (常駐Python Bot: MacMagicBot)]
  │ ③「music wakeup」を検知し、現在のスピーカー＆音量を記憶
  │ ④ 出力先を「Mac miniのスピーカー」へ強制切替＆音量を100%に設定
  ▼
[Apple Music (osascript)]
  │ ⑤ プレイリスト『WakeUp』を再生！
  │ ⑥ 音楽を止めたら（Discord経由でもMac直接操作でも）、自動で元の音量＆スピーカーに復元！
```

### 登場する用語の補足
- **Webhook（ウェブフック）**: 外部のアプリ（GalaxyのHTTP Request Shortcuts）から、特定のURL宛にデータを送るだけでDiscordのチャンネルにメッセージを投稿できる仕組みです。
- **Discord Bot（`MacMagicBot`）**: Discordの `#mac-control` チャンネルを見張り、特定のコマンドが来たらMacを操作するロボットアカウントです。
- **`SwitchAudioSource` (`switchaudio-osx`)**: Macの音声出力先（イヤホン、DAC、Mac mini本体のスピーカーなど）をコマンドで一瞬で切り替えるツールです。
- **AppleScript (`osascript`)**: Mac標準の自動操作機能です。PythonからApple Musicの再生やMac本体の音量変更を行うために使っています。
- **`launchd` (`LaunchAgents`)**: Macに標準搭載されている「裏側でプログラムを常駐させる仕組み」です。Macを再起動しても自動でBotを立ち上げ、万が一エラーで止まっても自動で再起動してくれます。

---

## 2. リポジトリ内のフォルダ・ファイル構成

```text
my-lab/
├── docs/
│   └── music-automation.md                      # 本設計書・運用マニュアル
├── projects/
│   └── music-automation/                        # プログラム本体
│       ├── bot.py                               # Discord監視＆Apple Music・音量制御スクリプト
│       ├── requirements.txt                     # Pythonライブラリ一覧
│       ├── com.mylab.music-automation.plist     # Mac常駐化（launchd）用の設定ファイル原本
│       ├── .env                                 # トークン・設定値（※Git管理外）
│       └── bot.log / bot.error.log              # 動作ログ（※Git管理外）
└── ai-context/
    └── handoff-log.md                           # AI引き継ぎ記録
```

---

## 3. 進捗ロードマップ（全ステップ完了🎉）

- [x] **Step 1: Discordのチャンネル・Webhook・Botの準備**
- [x] **Step 2: Mac miniでApple Musicを再生するテスト**
- [x] **Step 3: Mac miniでDiscord受信Botを作成・起動テスト（スピーカー強制切替＆音量自動復元機能つき）**
- [x] **Step 4: Galaxy S26 Ultraの「HTTP Request Shortcuts」＆「モードとルーチン」設定**
- [x] **Step 5: Mac mini起動時にBotを自動で裏側で動かす設定（常駐化）**

---

## 4. 使えるDiscordコマンド一覧（`#mac-control` チャンネル）

| 送信する文字（コマンド） | 動作内容 |
| :--- | :--- |
| **`music wakeup`**<br>（または `MacWakeUp`） | **【起床アラーム起動】**<br>1. 現在のスピーカーと音量を記憶<br>2. 出力先を `Mac miniのスピーカー` に切り替え、音量を `100%` に設定<br>3. Apple Musicでプレイリスト『`WakeUp`』を再生 |
| **`music wakeup stop`**<br>（または `MacWakeUpStop` / `music stop`） | **【音楽の停止＆元の設定へ復元】**<br>Apple Musicを一時停止し、記憶していた元の音量＆元のスピーカー（イヤホン等）に自動で戻す<br>※Mac本体のキーボードやマウスで直接音楽を止めた場合も、2秒以内に検知して自動で元の設定に戻ります。 |
| **`music play <プレイリスト名>`** | 指定した名前のプレイリストを再生する（例：`music play 作業用`） |
| **`music volume <0〜100>`** | Mac本体の音量を指定したパーセントに変更する（例：`music volume 40`） |

---

## 5. Galaxy S26 Ultra 側の設定メモ

### 5-1. アプリ「HTTP Request Shortcuts」の設定
1. **`MacWakeUp`（再生用）**
   - **Method**: `POST`
   - **URL**: `#mac-control` チャンネルのWebhook URL
   - **Request Body**: `{"content": "music wakeup"}`
   - **Response Handling**: トーストを表示（または何もしない）
2. **`MacWakeUp Stop`（停止用）**
   - `MacWakeUp` を複製して作成
   - **Request Body**: `{"content": "music wakeup stop"}`
   - ホーム画面にショートカット配置しておくとワンタップで停止可能。

### 5-2. 「モードとルーチン」の設定
- **開始条件（もし〜なら）**: 「アラーム解除時」（平日の定期アラーム、または起床用アラームを指定）
- **実行内容（〜を実行）**: 「アプリ」＞「アプリを開く、またはアプリのアクションを実行」＞ HTTP Shortcuts の **`MacWakeUp`**

---

## 6. Mac mini 常駐サービス（`launchd`）の管理コマンド

Botは `~/Library/LaunchAgents/com.mylab.music-automation.plist` に登録されており、Mac mini起動時に自動で裏側で動きます。  
もし設定（`.env` の音量やプレイリスト名など）を書き換えた後にBotを再起動したい場合は、ターミナルで以下のコマンドをコピペして実行してください。

```bash
# Botを再起動する（設定変更を反映したいとき）
launchctl kickstart -k gui/$(id -u)/com.mylab.music-automation

# Botの動作ログ（最新の履歴）を確認する
tail -n 30 ~/my-lab/projects/music-automation/bot.log

# 万が一Botの自動起動を止めたいとき
launchctl unload ~/Library/LaunchAgents/com.mylab.music-automation.plist

# 止めた自動起動をもう一度有効にしたいとき
launchctl load -w ~/Library/LaunchAgents/com.mylab.music-automation.plist
```
