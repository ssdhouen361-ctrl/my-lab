#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"

MODE="${1:-fast}"
if [[ $# -gt 0 ]]; then
  shift
fi

usage() {
  cat <<'EOF'
Usage: ./scripts/qa.sh [fast|e2e|visual|live|all] [extra args...]

Modes:
  fast    Layer 1: pytest unit & integration tests (excludes real KataGo live smoke) [default]
  e2e     Layer 1 + Layer 2: Playwright 6 virtual devices & 7 quality gates
  visual  Layer 3: Capture 10 deterministic screenshots + agy AI visual QA rubric
  live    Real KataGo Metal GPU smoke test (@pytest.mark.katago_live)
  all     Full pipeline: fast -> e2e -> visual
EOF
}

if [[ "${MODE}" == "-h" || "${MODE}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "[ERROR] Virtual environment not found at ${PROJECT_DIR}/.venv" >&2
  echo "Please run './scripts/setup.sh' first." >&2
  exit 1
fi

cd "${PROJECT_DIR}"

run_fast() {
  echo "=========================================="
  echo "[QA Layer 1] Running fast unit & integration tests ..."
  echo "=========================================="
  "${VENV_PYTHON}" -m pytest tests/unit -m "not katago_live" "$@"
}

run_e2e() {
  echo "=========================================="
  echo "[QA Layer 2] Running Playwright virtual device E2E & 7 quality gates ..."
  echo "=========================================="
  "${VENV_PYTHON}" -m pytest tests/e2e -m e2e "$@"
}

run_visual() {
  echo "=========================================="
  echo "[QA Layer 3] Capturing 10 deterministic screenshots ..."
  echo "=========================================="
  "${VENV_PYTHON}" -m tests.visual_qa.capture_screenshots

  echo "=========================================="
  echo "[QA Layer 3] Running AI Visual QA rubric (agy CLI) ..."
  echo "=========================================="
  "${VENV_PYTHON}" -m tests.visual_qa.run_visual_qa "$@"
}

run_live() {
  echo "=========================================="
  echo "[QA Live] Running real KataGo Metal GPU smoke test ..."
  echo "=========================================="
  "${VENV_PYTHON}" -m pytest tests/unit/test_katago_live.py -m katago_live "$@"
}

case "${MODE}" in
  fast)
    run_fast "$@"
    ;;
  e2e)
    run_fast
    run_e2e "$@"
    ;;
  visual)
    run_visual "$@"
    ;;
  live)
    run_live "$@"
    ;;
  all)
    run_fast
    run_e2e
    run_visual "$@"
    ;;
  *)
    echo "[ERROR] Invalid mode: ${MODE}" >&2
    usage >&2
    exit 2
    ;;
esac

echo "==> QA mode '${MODE}' completed successfully."
