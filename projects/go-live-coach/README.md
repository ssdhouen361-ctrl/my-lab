# Go Live Coach（対話型囲碁検討AIプロトタイプ）

Galaxy Tab S11（横画面 16:10）に最適化された、リアルタイム音声・対話型囲碁検討AIアプリのプロトタイプです。

- **統合基本設計書:** [docs/go-live-coach-design.md](../../docs/go-live-coach-design.md)
- **配置設計ワイヤーフレーム:** [docs/mockups/tablet_layout_wireframe.png](../../docs/mockups/tablet_layout_wireframe.png)
- **ポート番号:** `8095`（既存の `web-goban`: 8090 と完全分離・安全共存）

---

## 1. 起動方法（Mac mini ターミナルで 1 行実行）

```bash
cd ~/my-lab/projects/go-live-coach && PYTHONPATH=. ../web-goban/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8095
```

ブラウザで `http://127.0.0.1:8095/` を開くと、Galaxy Tab S11向け2層Canvas盤面と対話UIが立ち上がります。

---

## 2. 自動テストの実行

```bash
cd ~/my-lab/projects/go-live-coach && PYTHONPATH=. ../web-goban/.venv/bin/pytest tests/
```
（碁盤ルール、部分ワカレ集計スライス、Single-Passスマート要約フィルター、REST APIテスト全6件がPASSします）
