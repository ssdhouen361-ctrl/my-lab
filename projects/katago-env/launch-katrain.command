#!/bin/zsh
# KaTrain（KataGo 囲碁AI対局・検討ソフト）ワンクリック起動スクリプト

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "=========================================="
echo "⚫⚪ KaTrain (KataGo 囲碁AI) を起動します..."
echo "=========================================="

if [ ! -x "$SCRIPT_DIR/.venv/bin/katrain" ]; then
  echo "❌ エラー: 仮想環境 (.venv) に katrain が見つかりません。"
  exit 1
fi

"$SCRIPT_DIR/.venv/bin/katrain"
