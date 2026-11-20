# 3台連携ネットワーク基盤（Mac mini × Galaxy S26 Ultra × Galaxy Tab）構築ガイド

Mac mini（常時稼働サーバー）・Galaxy S26 Ultra・Galaxy Tab の3台を、外出先からでも安全かつ高速に直結させるための基盤構築手順書です。

---

## 1. ツール選定の結論：なぜ Tailscale か？

個人利用の複数端末連携（VPN）では、以下の理由から **Tailscale** が最も評判が良く、導入・維持が簡単です。

- **無料枠が十分：** 個人プランは最大 100台まで完全無料。
- **すでに1台導入済み：** Galaxy S26 Ultra では利用可能な状態。
- **便利機能が標準搭載：**
  - **MagicDNS：** 覚えにくい数字（IPアドレス）ではなく `mac-mini` のような名前でアクセス可能。
  - **Taildrop：** Mac mini ⇄ Android 間で AirDrop のように直接ファイルを送信可能。
- **将来の引っ越しも簡単：** 今後 Mac mini 上に作るアプリ（Web 碁盤や Gemini 連携ツール等）はすべて標準の Web 通信（HTTP）で作るため、将来 **ZeroTier / Cloudflare Tunnel / NetBird** など別の仕組みに乗り換えてもアプリ側の作り直しは不要です。

---

## 2. 完成形のイメージ

```text
[Galaxy S26 Ultra] ──┐
                     ├── (Tailscale 暗号化トンネル) ──▶ [Mac mini (常時稼働)]
[Galaxy Tab]       ──┘                                    ├─ Web 碁盤 (KataGo × Gemini)
                                                          ├─ 自動化ツール (n8n 等)
                                                          └─ Taildrop ファイル共有
```

---

## 3. セットアップ手順（所要時間：約10分）

### Step 1: Mac mini に Tailscale を入れる
Mac mini で一番簡単で安定する **Mac App Store 版** を導入します。

1. Mac mini で **App Store** を開き、`Tailscale` を検索してインストールする。
2. インストール後、Tailscale を起動し、画面右上のメニューバーに出たアイコンをクリック。
3. **「Log in...」** を押し、**Galaxy S26 Ultra とまったく同じアカウント**（Google アカウント等）でログインする。
4. メニューバーの Tailscale アイコンから **「Settings（設定）」** を開き、**「Launch Tailscale at login（ログイン時に起動）」** をオンにする（Mac 再起動後も自動でつながるようにするため）。

### Step 2: Galaxy Tab に Tailscale を入れる
1. Galaxy Tab で **Google Play ストア** を開き、`Tailscale` をインストールする。
2. アプリを開き、**S26 Ultra・Mac mini と同じアカウント** でログインする。
3. VPN 接続の許可ダイアログが出たら **「OK」** を押し、左上のスイッチを **ON（Active）** にする。

### Step 3: 管理画面で 3台の確認＆常駐向け設定（おすすめ）
ブラウザ（Mac でもスマホでも可）で [Tailscale 管理画面](https://login.tailscale.com/admin/machines) を開きます。

1. **3台が並んでいることを確認：** Mac mini / Galaxy S26 Ultra / Galaxy Tab が `Connected` になっていれば接続成功！
2. **Mac mini の自動ログアウト防止（重要）：**
   - Mac mini の行の右端にある `...` メニュー ➔ **「Disable key expiry（キーの有効期限を無効化）」** をクリック。
   - ※これをオンにしておくと、数ヶ月後に Mac mini だけ勝手に切断されるのを防げます。
3. **覚えやすい名前に変更（任意）：**
   - Mac mini の `...` メニュー ➔ **「Edit machine name...」** で `mac-mini` のように短い名前にしておくと、後で URL が入力しやすくなります。
4. **MagicDNS の確認：**
   - 管理画面の上部メニュー **「DNS」** ➔ **「MagicDNS」** が `Enabled`（有効）になっていることを確認（通常は初期設定で有効です）。

---

## 4. 連携完了テスト（2つ通れば完成！）

### テスト①：Taildrop でファイル送信テスト
1. Galaxy S26 Ultra で適当な画像を1枚選び、**「共有」** ➔ **「Tailscale」** ➔ **Mac mini** をタップ。
2. Mac mini の「ダウンロード」フォルダに一瞬で画像が届けば成功！

### テスト②：スマホのブラウザから Mac mini へ接続テスト
Mac mini のターミナルで以下を実行し、一時的なテストサーバーを立てます。

```bash
# Mac mini にテスト用の簡易Webページを一時起動する（ポート8888番で待ち受け）
python3 -m http.server 8888 --bind 0.0.0.0
```

次に、**Galaxy S26 Ultra（Wi-Fi を切って 5G/4G 回線でもOK！）** と **Galaxy Tab** の Samsung ブラウザで、以下のどちらかのURLを開きます。

- `http://mac-mini:8888`（Step 3 で名前を `mac-mini` にした場合）
- または、Tailscale アプリに表示されている Mac mini の `100.x.x.x` アドレスを使って `http://100.x.x.x:8888`

Mac mini のフォルダ一覧が表示されれば、**3台連携の土台は完全完成です！**
確認が終わったら、Mac mini のターミナルで **`Control + C`** を押してテストサーバーを終了してください。
