# ⚫⚪ KataGo × KaTrain 囲碁AI 対局・検討環境 (`katago-env`)

Mac mini（Apple M6 / 16GB）の計算パワーを使って **19路盤の AI 対局・AI 検討** を行い、**Galaxy Tab** からも快適に操作するための環境です。

---

## 🛠️ 導入済みの構成

| 要素 | 導入内容 | 役割 |
| :--- | :--- | :--- |
| **囲碁AIエンジン** | `KataGo`（Homebrew 版・Metal GPU 高速化対応） | 勝率・目数差・候補手を高速計算する頭脳 |
| **碁盤・GUIソフト** | `KaTrain`（専用 Python 3.12 仮想環境 `.venv` 内） | 棋力調整AI対局・リアルタイム検討・形勢グラフ表示 |
| **ワンクリック起動** | [launch-katrain.command](launch-katrain.command) | Finder からダブルクリックするだけで起動 |

---

## ▶️ 起動方法（Mac mini）

### 方法①：Finder からダブルクリック（おすすめ）
1. Finder で `/Users/sasadayuto/my-lab/projects/katago-env/` を開く
2. **`launch-katrain.command`** をダブルクリックする（デスクトップにエイリアスを作っておくとさらに便利です）

### 方法②：ターミナルから起動
```bash
# KaTrain を起動する
/Users/sasadayuto/my-lab/projects/katago-env/launch-katrain.command
```

---

## ⚙️ 事前設定済みの内容（初回からそのまま使えます）

セットアップ時に `~/.katrain/config.json` を以下の内容で自動設定済みです。起動するだけでそのまま19路盤の日本語環境で使えます！

* **表示言語:** 日本語（`jp`）
* **盤面・ルール:** 19路盤・日本ルール・コミ 6.5目
* **エンジン:** `/opt/homebrew/bin/katago`（Apple M6 Metal GPU 高速版・動作確認済み）
* **AIモデル:** `/opt/homebrew/share/katago/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz`（プロ超えの最新強モデル）
* **※さらに人間っぽい手加減対局モデル（Human-likeモデル）を追加したい場合:**
  - `KaTrain` 画面左上のメニュー（`≡`） ➔ **`一般・エンジン設定`** ➔ **`モデルをダウンロード`** ボタンからワンクリックで追加できます。

---

## 🎮 基本の使い方（19路盤）

### ① AI と対局して練習する（棋力調整つき）
1. 左上のメニュー（`≡`） ➔ **`New Game（新規対局）`**
2. 盤面サイズ **`19x19`**、手番（黒／白）、置き石の数を選ぶ
3. 右側のパネルで **`Play（対局）`** モードにし、AI の強さ（**`Calibrated Rank`：15級〜九段** や **`Simple / Pick / Influence（模様派） / Territory（実利派）`** など）を選んで対局スタート！
4. 打ち終わったら右上の **`Analyze（検討）`** に切り替えると、全手の形勢グラフと悪手が一瞬で表示されます。

### ② 棋譜を読み込んで検討する
* **SGF 棋譜ファイル** や **クリップボードにコピーした棋譜** を `KaTrain` のウィンドウにそのまま貼り付け（`Cmd + V`）またはドラッグ＆ドロップするだけで、自動的に全手順の検討が始まります。
* 盤上の候補手（緑・黄・赤の丸）にカーソル（または Galaxy Tab の **Sペン**）を近づけると、その後の読み筋（変化図）が盤面に表示されます。

---

## 📱 Galaxy Tab から操作する手順（Chrome リモートデスクトップ）

1. **Mac mini 側：** Chrome ブラウザで https://remotedesktop.google.com/access を開き、この Mac mini のリモートアクセスをオン（PIN設定）にする。
2. **Galaxy Tab 側：** Google Play から **「Chrome リモートデスクトップ」** アプリを入れて同じ Google アカウントでログインし、Mac mini に接続する。
3. 接続したら、Mac mini 上で `KaTrain` を全画面表示にして、指タッチまたは **Sペン** で対局・検討を楽しめます！
   - 💡 **Sペン活用Tips：** Sペンを画面から少し浮かせて候補手の上にかざすだけで、PCのマウスホバーと同じようにAIの読み筋（変化図）が表示されます。
