"""Layer 3 AI Visual QA runner using isolated agy CLI + 4-stage resilient JSON parser.

Invokes `/Users/sasadayuto/.local/bin/agy` from an isolated sandbox directory outside
the git repository (`~/Library/Caches/web-goban-visual-qa-sandbox/`) so parent
`AGENTS.md` or `.git` files are never read.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

EXPECTED_SCREENSHOTS: tuple[str, ...] = (
    "01_s26_review_idle.png",
    "02_s26_ghost_drag.png",
    "03_s26_spen_pv_heatmap.png",
    "04_s26_sheet_half_pv.png",
    "05_s26_sheet_full_coach.png",
    "06_s26_hint_and_banner.png",
    "07_tab_2col_review.png",
    "08_tab_spen_pv_heatmap.png",
    "09_tab_coach_report.png",
    "10_s26_narrow_9x9.png",
)

SCORE_KEYS: tuple[str, ...] = (
    "board_geometry",
    "coordinates_margin",
    "candidate_readability_cud",
    "ghost_reticle_pv",
    "layout_alignment",
    "japanese_text_contrast",
    "graph_heatmap_badges",
    "dark_theme_aesthetics",
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
DEFAULT_AGY_BIN = "/Users/sasadayuto/.local/bin/agy"
ISOLATED_SANDBOX_CWD = Path.home() / "Library" / "Caches" / "web-goban-visual-qa-sandbox"
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parents[1]
DEFAULT_SCREENSHOTS_DIR = PROJECT_DIR / "tests" / "artifacts" / "screenshots"
DEFAULT_ARTIFACTS_DIR = PROJECT_DIR / "tests" / "artifacts"
SCHEMA_PATH = MODULE_DIR / "report_schema.json"
RUBRIC_PATH = MODULE_DIR / "rubric_prompt.md"


def _is_report_dict(obj: Any) -> bool:
    return (
        isinstance(obj, dict)
        and "overall_status" in obj
        and "images" in obj
        and isinstance(obj["images"], list)
    )


def _unwrap_envelope(obj: Any, depth: int = 0) -> dict[str, Any] | None:
    """Unwrap CLI JSON envelopes (e.g. {'result': '...'} or {'structured_output': {...}})."""
    if depth > 4:
        return None
    if _is_report_dict(obj):
        return obj
    if isinstance(obj, str):
        parsed = parse_resilient_json(obj, _allow_unwrap=False)
        if parsed is not None:
            return _unwrap_envelope(parsed, depth + 1)
        return None
    if isinstance(obj, dict):
        for key in (
            "structured_output",
            "structuredOutput",
            "result",
            "response",
            "output",
            "content",
            "text",
            "message",
            "data",
        ):
            if key in obj:
                inner = _unwrap_envelope(obj[key], depth + 1)
                if inner is not None:
                    return inner
    if isinstance(obj, list):
        for item in reversed(obj):
            inner = _unwrap_envelope(item, depth + 1)
            if inner is not None:
                return inner
    return None


def _extract_balanced_json_objects(text: str) -> list[str]:
    """Extract balanced `{...}` substrings while respecting string quotes & escapes."""
    candidates: list[str] = []
    n = len(text)
    i = 0
    while i < n:
        if text[i] == "{":
            depth = 0
            in_str = False
            escape = False
            start = i
            j = i
            while j < n:
                ch = text[j]
                if in_str:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            candidates.append(text[start : j + 1])
                            i = j
                            break
                j += 1
        i += 1
    return candidates


def parse_resilient_json(raw_text: str, *, _allow_unwrap: bool = True) -> dict[str, Any] | None:
    """4-stage resilient JSON parser:
    1. Reverse line scan
    2. Direct json.loads
    3. Markdown code fence stripping
    4. Balanced brace extraction
    """
    if not raw_text or not raw_text.strip():
        return None

    def _try_candidate(candidate: str) -> dict[str, Any] | None:
        try:
            loaded = json.loads(candidate)
        except Exception:
            return None
        if _is_report_dict(loaded):
            return loaded
        if _allow_unwrap:
            unwrapped = _unwrap_envelope(loaded)
            if unwrapped is not None:
                return unwrapped
        return loaded if (not _allow_unwrap and isinstance(loaded, dict)) else None

    # Stage 1: Reverse line scan (handles NDJSON / trailing summary lines)
    for line in reversed(raw_text.splitlines()):
        stripped = line.strip()
        if not stripped or not (stripped.startswith("{") and stripped.endswith("}")):
            continue
        res = _try_candidate(stripped)
        if res is not None and (_is_report_dict(res) or not _allow_unwrap):
            return res

    # Stage 2: Direct json.loads on full stdout
    res = _try_candidate(raw_text.strip())
    if res is not None and (_is_report_dict(res) or not _allow_unwrap):
        return res

    # Stage 3: Strip markdown code fences ```json ... ```
    fence_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw_text, flags=re.IGNORECASE)
    for block in reversed(fence_blocks):
        res = _try_candidate(block.strip())
        if res is not None and (_is_report_dict(res) or not _allow_unwrap):
            return res

    # Stage 4: Balanced brace extraction (preferring outermost/last valid report object)
    for snippet in reversed(_extract_balanced_json_objects(raw_text)):
        res = _try_candidate(snippet)
        if res is not None and (_is_report_dict(res) or not _allow_unwrap):
            return res

    return None


def verify_screenshots(screenshots_dir: Path) -> tuple[bool, list[str]]:
    """Verify all 10 deterministic PNGs exist, are non-empty, and have valid PNG signatures."""
    errors: list[str] = []
    if not screenshots_dir.is_dir():
        return False, [f"Screenshots directory does not exist: {screenshots_dir}"]
    for name in EXPECTED_SCREENSHOTS:
        p = screenshots_dir / name
        if not p.is_file():
            errors.append(f"Missing screenshot: {p}")
            continue
        data = p.read_bytes()
        if len(data) < 64:
            errors.append(f"Screenshot too small ({len(data)} bytes): {p}")
        elif not data.startswith(PNG_MAGIC):
            errors.append(f"Invalid PNG header: {p}")
    return len(errors) == 0, errors


def normalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Ensure fail_count & overall_status are consistent with image verdicts."""
    images = report.get("images") or []
    computed_fails = sum(1 for item in images if str(item.get("status", "")).upper() == "FAIL")
    computed_warns = sum(1 for item in images if str(item.get("status", "")).upper() == "WARN")
    report["fail_count"] = computed_fails
    if computed_fails > 0:
        report["overall_status"] = "FAIL"
    elif computed_warns > 0 and str(report.get("overall_status", "")).upper() == "PASS":
        report["overall_status"] = "WARN"
    elif "overall_status" not in report:
        report["overall_status"] = "WARN" if computed_warns > 0 else "PASS"
    return report


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render a concise human-readable Markdown summary from visual_report.json."""
    lines = [
        "# Web Goban Layer 3 Visual QA Report",
        "",
        f"- **Overall Status:** `{report.get('overall_status', 'UNKNOWN')}`",
        f"- **FAIL Count:** `{report.get('fail_count', 0)}`",
        f"- **Summary:** {report.get('summary', '')}",
        "",
        "## Screenshot Rubric Scores (1–5)",
        "",
        "| Screenshot | Status | Geo | Coord | CUD | Ghost/PV | Layout | JP Text | Graph/Map | Theme |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for img in report.get("images", []):
        s = img.get("scores") or {}
        lines.append(
            f"| `{img.get('filename', '?')}` | **{img.get('status', '?')}** | "
            f"{s.get('board_geometry', '-')} | "
            f"{s.get('coordinates_margin', '-')} | "
            f"{s.get('candidate_readability_cud', '-')} | "
            f"{s.get('ghost_reticle_pv', '-')} | "
            f"{s.get('layout_alignment', '-')} | "
            f"{s.get('japanese_text_contrast', '-')} | "
            f"{s.get('graph_heatmap_badges', '-')} | "
            f"{s.get('dark_theme_aesthetics', '-')} |"
        )

    lines.extend(["", "## Detailed Findings & Fix Suggestions", ""])
    for img in report.get("images", []):
        fname = img.get("filename", "?")
        status = img.get("status", "?")
        issues = img.get("issues") or []
        suggestion = img.get("fix_suggestion", "")
        lines.append(f"### `{fname}` ({status})")
        if issues:
            for issue in issues:
                lines.append(f"- {issue}")
        else:
            lines.append("- 特段の視覚欠陥なし")
        if suggestion:
            lines.append(f"- **Fix suggestion:** {suggestion}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _kill_process_group(proc: subprocess.Popen[str]) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


def invoke_agy_visual_qa(
    *,
    screenshots_dir: Path,
    agy_bin: str = DEFAULT_AGY_BIN,
    timeout_sec: int = 120,
    sandbox_cwd: Path = ISOLATED_SANDBOX_CWD,
) -> dict[str, Any]:
    """Run agy CLI from isolated sandbox cwd and return parsed report JSON."""
    sandbox_cwd.mkdir(parents=True, exist_ok=True)
    prompt_body = RUBRIC_PATH.read_text(encoding="utf-8")
    file_list = "\n".join(f"- {screenshots_dir / name}" for name in EXPECTED_SCREENSHOTS)
    full_prompt = (
        f"{prompt_body}\n\n"
        f"## 審査対象ファイル一覧（必ず全10枚を開いて目視評価すること）\n{file_list}\n"
    )

    cmd = [
        agy_bin,
        "-p",
        full_prompt,
        "--add-dir",
        str(screenshots_dir),
        "--mode",
        "plan",
        "--effort",
        "low",
        "--disable-slash-commands",
        "--sandbox",
        "--output-format",
        "json",
        "--json-schema",
        str(SCHEMA_PATH),
        "--print-timeout",
        f"{timeout_sec}s",
    ]

    env = dict(os.environ)
    env.setdefault("HOME", str(Path.home()))

    proc = subprocess.Popen(
        cmd,
        cwd=str(sandbox_cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec + 15)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        raise RuntimeError(f"agy visual QA timed out after {timeout_sec}s (process group killed)")

    parsed = parse_resilient_json(stdout)
    if parsed is None:
        parsed = parse_resilient_json(stderr)
    if parsed is None:
        snippet = (stdout or stderr or "")[:600]
        raise RuntimeError(
            f"Failed to parse structured Visual QA JSON from agy (exit={proc.returncode}): {snippet}"
        )

    return normalize_report(parsed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Layer 3 AI Visual QA via agy CLI.")
    parser.add_argument(
        "--screenshots-dir",
        type=Path,
        default=DEFAULT_SCREENSHOTS_DIR,
        help="Directory containing the 10 deterministic PNG screenshots.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help="Directory to write visual_report.json and visual_report.md.",
    )
    parser.add_argument(
        "--agy-bin",
        default=DEFAULT_AGY_BIN,
        help="Path to agy CLI executable.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="agy --print-timeout in seconds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify all 10 PNG screenshots exist and are valid without calling agy.",
    )
    args = parser.parse_args(argv)

    screenshots_dir: Path = args.screenshots_dir.resolve()
    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ok, errors = verify_screenshots(screenshots_dir)
    if not ok:
        for err in errors:
            print(f"[Visual QA ERROR] {err}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"[Visual QA DRY-RUN] Verified all {len(EXPECTED_SCREENSHOTS)} PNGs in {screenshots_dir}")
        return 0

    if not Path(args.agy_bin).is_file():
        print(f"[Visual QA ERROR] agy CLI not found at {args.agy_bin}", file=sys.stderr)
        return 1

    report = invoke_agy_visual_qa(
        screenshots_dir=screenshots_dir,
        agy_bin=args.agy_bin,
        timeout_sec=args.timeout,
    )

    json_path = output_dir / "visual_report.json"
    md_path = output_dir / "visual_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")

    fail_count = int(report.get("fail_count", 0))
    overall = report.get("overall_status", "UNKNOWN")
    print(f"[Visual QA] overall_status={overall} fail_count={fail_count}")
    print(f"[Visual QA] JSON report: {json_path}")
    print(f"[Visual QA] MD report:   {md_path}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
