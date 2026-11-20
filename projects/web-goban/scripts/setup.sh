#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

PROD_ONLY=false
SKIP_PLAYWRIGHT=false

usage() {
  cat <<'EOF'
Usage: ./scripts/setup.sh [OPTIONS]

Options:
  --prod-only        Install only runtime dependencies (requirements.txt) and skip Playwright
  --skip-playwright  Install dev dependencies but skip Playwright Chromium download
  -h, --help         Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prod-only)
      PROD_ONLY=true
      SKIP_PLAYWRIGHT=true
      shift
      ;;
    --skip-playwright)
      SKIP_PLAYWRIGHT=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

select_python() {
  if [[ -x "/opt/homebrew/bin/python3.12" ]]; then
    echo "/opt/homebrew/bin/python3.12"
  elif command -v python3.12 >/dev/null 2>&1; then
    command -v python3.12
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    echo "[ERROR] Python 3 not found. Please install Python 3.12 (e.g. brew install python@3.12)." >&2
    exit 1
  fi
}

PYTHON_BIN="$(select_python)"
VENV_DIR="${PROJECT_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

echo "==> Project directory: ${PROJECT_DIR}"
echo "==> Using Python: ${PYTHON_BIN} ($("${PYTHON_BIN}" --version))"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "==> Creating virtual environment at ${VENV_DIR} ..."
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
else
  echo "==> Reusing existing virtual environment at ${VENV_DIR}"
fi

echo "==> Upgrading pip ..."
"${VENV_PYTHON}" -m pip install --upgrade pip

if [[ "${PROD_ONLY}" == "true" ]]; then
  echo "==> Installing production dependencies (requirements.txt) ..."
  "${VENV_PYTHON}" -m pip install -r "${PROJECT_DIR}/requirements.txt"
else
  echo "==> Installing development & QA dependencies (requirements-dev.txt) ..."
  "${VENV_PYTHON}" -m pip install -r "${PROJECT_DIR}/requirements-dev.txt"
fi

if [[ "${SKIP_PLAYWRIGHT}" == "false" ]]; then
  echo "==> Installing Playwright Chromium browser ..."
  "${VENV_PYTHON}" -m playwright install chromium
else
  echo "==> Skipping Playwright browser installation"
fi

echo "==> Creating data directories ..."
mkdir -p \
  "${PROJECT_DIR}/data/sgf" \
  "${PROJECT_DIR}/data/reports" \
  "${PROJECT_DIR}/data/db" \
  "${PROJECT_DIR}/data/logs/katago"

if [[ ! -f "${PROJECT_DIR}/.env" && -f "${PROJECT_DIR}/.env.example" ]]; then
  echo "==> Copying .env.example to .env ..."
  cp "${PROJECT_DIR}/.env.example" "${PROJECT_DIR}/.env"
elif [[ -f "${PROJECT_DIR}/.env" ]]; then
  echo "==> Existing .env preserved"
fi

cat <<EOF

Setup complete!

Next steps:
  1. Run Layer 1 fast unit/integration tests:
     cd "${PROJECT_DIR}" && ./scripts/qa.sh fast

  2. Run full 3-layer virtual QA pipeline (unit + Playwright E2E + AI visual QA):
     cd "${PROJECT_DIR}" && ./scripts/qa.sh all

  3. Start the Web Goban server locally:
     cd "${PROJECT_DIR}" && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8090 --workers 1
EOF
