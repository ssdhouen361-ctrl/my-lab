# Web 碁盤（KataGo × Gemini）— Phase 1 MVP

Galaxy S26 Ultra（縦画面・指＆Sペン）と Galaxy Tab S11（横画面・Sペン最適化）で快適に 19 路盤を対局・検討できる、Mac mini（Apple M6 Metal GPU）常駐型の Web 碁盤です。

- **統合設計書:** [docs/web-goban-design.md](../../docs/web-goban-design.md)
- **現在ステータス:** Phase 1（Step 1-A バックエンド土台＋Layer 1 pytest ＆ Step 1-B フロントエンド 2 層 Canvas・3 モードレスポンシブ・指 52px 仮置き・Sペンホバー・PlatformBridge ＋ Layer 2 Playwright E2E ＋ Layer 3 AI スクショ目視審査パイプライン）実装完了

---

## 1. 初回セットアップ（Mac mini ターミナルで 1 行実行）

Mac mini のターミナルを開き、以下の 1 行をコピペして実行するだけで、Python 3.12 仮想環境（`.venv`）・依存パッケージ・Playwright（仮想ブラウザ Chromium）・データフォルダ・`.env` の作成から自動テスト実行まで完了します。

```bash
cd ~/my-lab/projects/web-goban && ./scripts/setup.sh && ./scripts/qa.sh all
```

### 各コマンドの意味
1. `cd ~/my-lab/projects/web-goban` : Web 碁盤のフォルダへ移動します。
2. `./scripts/setup.sh` : `.venv` を作り、FastAPI / pytest / Playwright（Chromium）を入れ、保存先フォルダと `.env` を準備します。
3. `./scripts/qa.sh all` : Layer 1（バックエンド自動試験）→ Layer 2（Playwright 仮想端末 6 機種＆7 大品質ゲート）→ Layer 3（厳選 10 枚スクショ撮影＆`agy` AI 目視審査）を一気通貫で自動検証します。

---

## 2. サーバーの起動と確認

### 手動でローカル起動して試す
```bash
cd ~/my-lab/projects/web-goban
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8090 --workers 1
```
- 1 行目: Web 碁盤のフォルダへ移動します。
- 2 行目: Web サーバー（FastAPI）をポート `8090`・シングルワーカー（`--workers 1` 厳守）で起動します。Mac mini のブラウザで `http://127.0.0.1:8090/` を開くと盤面が表示されます。

### Tailscale 経由でスマホ・タブレットから開く（HTTPS PWA 化・初回のみ）
1. Tailscale 管理画面で **MagicDNS** と **HTTPS Certificates** を有効化します。
2. `.env` の `ALLOWED_ORIGINS` に自分の Tailscale URL（例：`https://mac-mini.<tailnet名>.ts.net`）を追記します。
3. Mac mini のターミナルで以下を 1 回だけ実行します。
```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg http://127.0.0.1:8090
```
   - `127.0.0.1:8090` の Web 碁盤を、Tailscale 内の正規 HTTPS（WSS 対応）として公開します（初回アクセス時は証明書取得で数十秒かかる場合があります）。
4. Galaxy S26 Ultra / Galaxy Tab S11 の Samsung ブラウザで `https://mac-mini.<tailnet名>.ts.net/` を開き、「ホーム画面に追加」するとアドレスバーなしの全画面アプリ（PWA）として使えます。

### Mac mini 常駐化（`launchd` 登録）
ターミナルを閉じても Mac 再起動後も自動で裏側稼働させる手順です。

```bash
cp ~/my-lab/projects/web-goban/com.mylab.web-goban.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mylab.web-goban.plist
```
- 1 行目: 常駐設定テンプレート（`ProcessType: Interactive` / `HOME=/Users/sasadayuto` / `--workers 1` 設定済）を macOS の自動起動フォルダへコピーします。
- 2 行目: 常駐サービスを登録・起動します。

再起動・停止コマンド：
```bash
# 再起動
launchctl kickstart -k gui/$(id -u)/com.mylab.web-goban
# 停止・解除
launchctl bootout gui/$(id -u)/com.mylab.web-goban
```

---

## 3. 自動品質保証（4 層 QA パイプライン）

テストはすべて **本番 `data/`・本番ポート `8090`・実 KataGo と完全隔離** された状態で実行されるため、対局データに影響しません。

| コマンド | 内容 | 所要目安 |
| :--- | :--- | :---: |
| `./scripts/qa.sh fast` | **Layer 1:** バックエンド単体・統合試験（座標・ルール・SGF・8MB NDJSON・キャンセル・WS 同期） | 5〜15 秒 |
| `./scripts/qa.sh e2e` | **Layer 1 + Layer 2:** Playwright 仮想 6 端末（S26 Ultra / Tab S11）＋7 大レイアウト品質ゲート＋指 52px / Sペン / WebView 模擬 | 30〜60 秒 |
| `./scripts/qa.sh visual` | **Layer 3:** 決定論的スクショ 10 枚撮影（`tests/artifacts/screenshots/`）＋`agy` CLI による 8 項目ルーブリック目視審査 | 45〜120 秒 |
| `./scripts/qa.sh live` | **実機 KataGo スモーク:** 本物の Metal GPU 版 KataGo ＋ `config/katago_analysis.cfg` で 1 局面を実解析 | 10〜20 秒 |
| `./scripts/qa.sh all` | **一気通貫:** `fast` → `e2e` → `visual` を連続実行 | 1〜2.5 分 |

---

## 4. ディレクトリ構成

- `config/katago_analysis.cfg` : Apple M6 / 16GB・KaTrain 共存向け KataGo 設定（GPU-only・`2×8`・`nnMaxBatchSize=16`）
- `app/` : FastAPI バックエンド（`coords.py` / `rules.py` / `db.py` / `katago_engine.py` / `game_hub.py` / `main.py`）
- `static/` : ビルド不要のフロントエンド（`index.html` / `manifest.webmanifest` / `sw.js` / `css/app.css` / ES Modules JS 6 構成）
- `scripts/` : 初回セットアップ（`setup.sh`）および 1 コマンド QA ランナー（`qa.sh`）
- `tests/` : Layer 1（`unit/`）・Layer 2（`e2e/`）・Layer 3（`visual_qa/`）・OS パイプ版擬似 KataGo（`fakes/`）・決定論的フィクスチャ（`fixtures/`）
- `data/` : ユーザーデータ保存先（`.sgf` 原本・SQLite `goban.db`・ログ。`.gitignore` 対象）

---

## 5. 専門用語のかんたん補足

- **PWA（ピー・ダブリュー・エー）:** Web ページをホーム画面に追加して、ブラウザの URL バーなしでアプリのように動かせる仕組み。Mac mini 側を更新するだけで再インストール不要で最新化できます。
- **PlatformBridge / WebView ラッパー:** 振動・クリップボード・共有・戻るボタンなどの OS 依存機能を `platform-bridge.js` 1 箇所に閉じ込めた設計。将来 Android の外枠アプリ（APK）を被せても Web 側の書き換えゼロで移行できます。
- **Air View ホバー＆パームリジェクション:** Sペンを画面から数ミリ浮かせた状態で読み筋（PV）を即座に表示し、ペン操作中および離脱後 `350ms` 以内や大面積タッチ（手のひら）を自動で弾く仕組みです。
- **Smoothstep 減衰（指 52px オフセット）:** 指でドラッグ照準する際、指先で交点が隠れないよう石を上方向 `52px` へ浮かせて表示し、盤面上端 5 路では滑らかに `0px` へ減衰させて 19 線・隅も 1 路単位で狙えるようにする計算式です。
- **NDJSON / WAL:** NDJSON は KataGo と 1 行 1 JSON で高速通信する形式、WAL は SQLite の読み書き衝突を防いで安定動作させるモードです。
