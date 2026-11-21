"""KataGo Analysis Engine subprocess controller, chunk scheduler & AI move selector.

Pure standard library + asyncio. Addresses Pitfalls:
  #1  stdout 8MB StreamReader buffer + forbid includeMovesOwnership
  #3  Black-perspective winrate/scoreLead + centralized score_loss helper
  #4  Always-running stderr drain loop + await stdin.drain() on every write
  #5  Graceful terminate_all -> stdin close -> wait(5s) -> SIGTERM -> SIGKILL + timeouts
  #8  External KataGo (KaTrain) detection, warmup suppression, 180s idle shortening
  #10 Dynamic ownership length validation (board_size * board_size)
  #11 terminated_ids tracking so cancelled partial-visits frames NEVER pollute cache
  #13 Top-level KataGo "error" fails ALL pending turns for that query id immediately
  #14 2-stage startup handshake (query_version -> 9x9 1-visit warmup with 60s timeout)
  #17 AnalysisEngineProtocol & injectable command_builder for OS-pipe fake testing
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import random
import time
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable
import uuid

from app.config import Settings

logger = logging.getLogger("web_goban.katago")

STDOUT_BUFFER_LIMIT = 8 * 1024 * 1024  # 8 MB (Pitfall #1)
FULL_REVIEW_CHUNK_SIZE = 4
FULL_REVIEW_DEFAULT_VISITS = 150
EXTERNAL_PROBE_CACHE_SEC = 5.0
KATAGO_LOG_KEEP_FILES = 5
MAX_TERMINATED_IDS = 2048


class EngineState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    WARMING_UP = "WARMING_UP"
    IDLE = "IDLE"
    ANALYZING = "ANALYZING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class KataGoError(Exception):
    """Base error for KataGo engine failures."""


class KataGoQueryError(KataGoError):
    """Error returned by KataGo for a specific analysis query (engine stays alive)."""


class KataGoTimeoutError(KataGoError):
    """Query or warmup timed out."""


AI_PRESETS: dict[str, dict[str, Any]] = {
    "15k": {
        "max_visits": 30,
        "temperature": 1.8,
        "min_loss": 1.0,
        "max_loss": 6.0,
        "resign_enabled": True,
        "resign_winrate": 0.03,
        "resign_lead": -25.0,
    },
    "10k": {
        "max_visits": 50,
        "temperature": 1.3,
        "min_loss": 0.5,
        "max_loss": 4.5,
        "resign_enabled": True,
        "resign_winrate": 0.03,
        "resign_lead": -25.0,
    },
    "5k": {
        "max_visits": 80,
        "temperature": 0.85,
        "min_loss": 0.2,
        "max_loss": 3.0,
        "resign_enabled": True,
        "resign_winrate": 0.03,
        "resign_lead": -25.0,
    },
    "1d": {
        "max_visits": 120,
        "temperature": 0.45,
        "min_loss": 0.0,
        "max_loss": 1.8,
        "resign_enabled": True,
        "resign_winrate": 0.03,
        "resign_lead": -25.0,
    },
    "5d": {
        "max_visits": 200,
        "temperature": 0.20,
        "min_loss": 0.0,
        "max_loss": 0.9,
        "resign_enabled": True,
        "resign_winrate": 0.03,
        "resign_lead": -25.0,
    },
    "max": {
        "max_visits": 300,
        "temperature": 0.0,
        "min_loss": 0.0,
        "max_loss": 0.0,
        "resign_enabled": True,
        "resign_winrate": 0.03,
        "resign_lead": -25.0,
    },
}


def compute_score_loss(
    best_lead_black: float,
    move_lead_black: float,
    side_to_move: str,
) -> float:
    """Compute non-negative point loss from side_to_move's perspective (Pitfall #3).

    KataGo always reports scoreLead from BLACK's perspective:
      - Black wants higher scoreLead -> loss = max(0.0, best - move)
      - White wants lower scoreLead  -> loss = max(0.0, move - best)
    """
    if side_to_move == "B":
        return max(0.0, round(float(best_lead_black) - float(move_lead_black), 3))
    if side_to_move == "W":
        return max(0.0, round(float(move_lead_black) - float(best_lead_black), 3))
    raise ValueError(f"Invalid side_to_move: {side_to_move!r}")


def classify_move_quality(
    score_loss: float,
    winrate_loss: float = 0.0,
    board_size: int = 19,
    *,
    is_garbage_time: bool = False,
    entered_competitive_band: bool = False,
) -> str | None:
    """Classify move loss into blunder/mistake/inaccuracy/None per Section 5-3."""
    if is_garbage_time and not entered_competitive_band:
        return "inaccuracy" if score_loss >= 8.0 else None

    if board_size <= 9:
        blunder_pts, blunder_combo, mistake_pts, mistake_combo, inacc_pts = (
            2.8, 1.7, 1.4, 0.8, 0.7
        )
    elif board_size <= 13:
        blunder_pts, blunder_combo, mistake_pts, mistake_combo, inacc_pts = (
            3.8, 2.3, 1.9, 1.1, 0.9
        )
    else:
        blunder_pts, blunder_combo, mistake_pts, mistake_combo, inacc_pts = (
            5.0, 3.0, 2.5, 1.5, 1.2
        )

    if score_loss >= blunder_pts or (score_loss >= blunder_combo and winrate_loss >= 0.20):
        return "blunder"
    if score_loss >= mistake_pts or (score_loss >= mistake_combo and winrate_loss >= 0.15):
        return "mistake"
    if score_loss >= inacc_pts:
        return "inaccuracy"
    return None


def normalize_katago_response(
    raw: dict[str, Any],
    next_player: str,
    board_size: int,
) -> dict[str, Any]:
    """Normalize raw KataGo analysis JSON to canonical Black-perspective payload.

    Validates dynamic ownership length == board_size * board_size (Pitfall #10)
    and rounds ownership entries to 2 decimal places.
    """
    root_raw = raw.get("rootInfo") or {}
    root_wr_black = float(root_raw.get("winrate", 0.5))
    root_lead_black = float(root_raw.get("scoreLead", 0.0))
    root_visits = int(root_raw.get("visits", 0))

    raw_moves = list(raw.get("moveInfos") or [])
    raw_moves.sort(key=lambda m: int(m.get("order", 9999)))

    best_lead_black = (
        float(raw_moves[0].get("scoreLead", root_lead_black))
        if raw_moves
        else root_lead_black
    )

    normalized_moves: list[dict[str, Any]] = []
    for idx, m in enumerate(raw_moves):
        m_wr = float(m.get("winrate", root_wr_black))
        m_lead = float(m.get("scoreLead", root_lead_black))
        loss = compute_score_loss(best_lead_black, m_lead, next_player)
        entry: dict[str, Any] = {
            "move": str(m.get("move", "pass")),
            "order": int(m.get("order", idx)),
            "visits": int(m.get("visits", 0)),
            "winrate_black": round(m_wr, 4),
            "score_lead_black": round(m_lead, 2),
            "score_loss": round(loss, 2),
            "prior": round(float(m.get("prior", 0.0)), 4),
            "pv": [str(p) for p in (m.get("pv") or [])],
        }
        if m.get("pvVisits") is not None:
            entry["pv_visits"] = [int(v) for v in m["pvVisits"]]
        normalized_moves.append(entry)

    ownership_raw = raw.get("ownership")
    ownership_norm: list[float] | None = None
    if ownership_raw is not None:
        expected_len = board_size * board_size
        if len(ownership_raw) != expected_len:
            raise KataGoQueryError(
                f"Ownership array length mismatch: got {len(ownership_raw)}, "
                f"expected {expected_len} for {board_size}x{board_size} board"
            )
        ownership_norm = [round(float(v), 2) for v in ownership_raw]

    return {
        "query_id": str(raw.get("id", "")),
        "turn_number": int(raw.get("turnNumber", 0)),
        "is_final": not bool(raw.get("isDuringSearch", False)),
        "root": {
            "winrate_black": round(root_wr_black, 4),
            "score_lead_black": round(root_lead_black, 2),
            "visits": root_visits,
        },
        "moves": normalized_moves,
        "ownership": ownership_norm,
    }


def select_ai_move(
    analysis_result: dict[str, Any],
    side_to_move: str,
    ai_level: str = "5k",
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Select an AI move according to strength preset with loss-filtered Softmax sampling."""
    if side_to_move not in ("B", "W"):
        raise ValueError(f"Invalid side_to_move: {side_to_move!r}")

    preset = AI_PRESETS.get(ai_level, AI_PRESETS["5k"])
    root = analysis_result.get("root") or {}
    root_wr_black = float(root.get("winrate_black", root.get("winrate", 0.5)))
    root_lead_black = float(root.get("score_lead_black", root.get("scoreLead", 0.0)))

    if side_to_move == "B":
        side_wr = root_wr_black
        side_lead = root_lead_black
    else:
        side_wr = 1.0 - root_wr_black
        side_lead = -root_lead_black

    if (
        preset["resign_enabled"]
        and side_wr < preset["resign_winrate"]
        and side_lead < preset["resign_lead"]
    ):
        return {
            "move": "resign",
            "should_resign": True,
            "selected_info": None,
            "ai_level": ai_level,
        }

    moves = list(analysis_result.get("moves") or [])
    if not moves:
        return {
            "move": "pass",
            "should_resign": False,
            "selected_info": None,
            "ai_level": ai_level,
        }

    # Recompute/verify losses from side_to_move perspective against top move
    moves_sorted = sorted(moves, key=lambda m: int(m.get("order", 9999)))
    best_lead_black = float(
        moves_sorted[0].get("score_lead_black", moves_sorted[0].get("scoreLead", root_lead_black))
    )

    scored: list[tuple[dict[str, Any], float]] = []
    for m in moves_sorted:
        m_lead = float(m.get("score_lead_black", m.get("scoreLead", best_lead_black)))
        loss = compute_score_loss(best_lead_black, m_lead, side_to_move)
        scored.append((m, loss))

    # Re-sort by computed loss ascending so best move is always index 0
    scored.sort(key=lambda pair: (pair[1], int(pair[0].get("order", 9999))))

    temp = float(preset["temperature"])
    if temp <= 0.0 or len(scored) == 1:
        chosen = scored[0][0]
        return {
            "move": str(chosen["move"]),
            "should_resign": False,
            "selected_info": chosen,
            "ai_level": ai_level,
        }

    max_loss = float(preset["max_loss"])
    min_loss = float(preset["min_loss"])

    eligible = [(m, loss) for m, loss in scored if loss <= max_loss]
    if not eligible:
        eligible = [scored[0]]

    # Softmax sampling biased around target min_loss band while avoiding blunders > max_loss
    energies = [-abs(loss - min_loss) / temp for _, loss in eligible]
    max_e = max(energies)
    weights = [math.exp(e - max_e) for e in energies]

    rand = rng if rng is not None else random.Random()
    chosen_pair = rand.choices(eligible, weights=weights, k=1)[0]
    chosen = chosen_pair[0]
    return {
        "move": str(chosen["move"]),
        "should_resign": False,
        "selected_info": chosen,
        "ai_level": ai_level,
    }


def compute_model_fingerprint(model_path: str) -> str:
    """Compute a stable short fingerprint for the active KataGo neural net model."""
    path = Path(model_path)
    try:
        st = path.stat()
        raw = f"{path.name}:{st.st_size}"
    except OSError:
        raw = str(model_path)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{path.stem[:24]}:{digest}"


@runtime_checkable
class AnalysisEngineProtocol(Protocol):
    state: EngineState
    model_fingerprint: str

    def get_status(self) -> dict[str, Any]: ...

    async def warmup(self, force: bool = False) -> dict[str, Any]: ...

    async def stop(self) -> None: ...

    async def analyze_interactive(
        self,
        query_payload: dict[str, Any],
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        debounce: bool = True,
    ) -> dict[str, Any] | None: ...

    async def analyze_once(
        self,
        query_payload: dict[str, Any],
        priority: int = 20,
    ) -> dict[str, Any]: ...

    async def start_full_review(
        self,
        job_id: str,
        turns: list[dict[str, Any]],
        on_turn: Callable[[dict[str, Any]], Awaitable[None]],
        on_progress: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None: ...

    async def cancel(self, scope: str = "all") -> None: ...


@dataclass
class _PendingTurn:
    query_id: str
    turn_number: int
    next_player: str
    board_size: int
    future: asyncio.Future[dict[str, Any] | None]
    is_interactive: bool = False
    on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def default_katago_command(settings: Settings) -> list[str]:
    """Build standard KataGo Analysis Engine CLI arguments."""
    return [
        settings.katago_bin,
        "analysis",
        "-config",
        str(settings.katago_config),
        "-model",
        settings.katago_model,
        "-quit-without-waiting",
        "-override-config",
        f"logDir={settings.katago_logs_dir}",
    ]


async def default_external_katago_probe(own_pid: int | None) -> list[dict[str, Any]]:
    """Detect external KataGo processes (e.g. KaTrain) without ever signalling them (Pitfall #8)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ps",
            "-eo",
            "pid,ppid,rss,command",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
    except Exception:
        return []

    my_py_pid = os.getpid()
    found: list[dict[str, Any]] = []
    for line in stdout_bytes.decode("utf-8", errors="replace").splitlines()[1:]:
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
            rss_kb = int(parts[2])
        except ValueError:
            continue
        cmd = parts[3]
        if pid in (own_pid, my_py_pid):
            continue
        cmd_lower = cmd.lower()
        # Match actual katago binary invocations; exclude grep/ps/pytest/fake workers
        if "katago" not in cmd_lower:
            continue
        if any(
            skip in cmd_lower
            for skip in ("pytest", "fake_katago", "grep ", "ps -eo", "web-goban")
        ):
            continue
        exe_token = cmd.split()[0]
        if Path(exe_token).name.lower() == "katago" or "/katago " in cmd_lower:
            found.append(
                {
                    "pid": pid,
                    "ppid": ppid,
                    "rss_kb": rss_kb,
                    "rss_mb": round(rss_kb / 1024.0, 1),
                    "command": cmd,
                }
            )
    return found


def _sanitize_katago_query(raw: dict[str, Any]) -> dict[str, Any]:
    """Build clean KataGo query payload, strictly forbidding includeMovesOwnership (Pitfall #1)."""
    allowed_keys = {
        "id",
        "moves",
        "initialStones",
        "initialPlayer",
        "rules",
        "komi",
        "boardXSize",
        "boardYSize",
        "analyzeTurns",
        "maxVisits",
        "rootPolicyTemperature",
        "rootFpuReductionMax",
        "includeOwnership",
        "includeOwnershipStdev",
        "includePolicy",
        "includePVVisits",
        "reportDuringSearchEvery",
        "priority",
        "overrideSettings",
    }
    clean = {k: v for k, v in raw.items() if k in allowed_keys and v is not None}
    # Explicitly ensure includeMovesOwnership is never sent
    clean.pop("includeMovesOwnership", None)
    return clean


class KataGoEngine:
    """Managed KataGo Analysis Engine subprocess with 2-stage handshake,
    3-stage interactive cancellation, chunked full-review scheduler, and idle stop.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        command_builder: Callable[[Settings], list[str]] | None = None,
        external_process_probe: Callable[[int | None], Awaitable[list[dict[str, Any]]]] | None = None,
        on_status_change: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.settings = settings
        self._command_builder = command_builder or default_katago_command
        self._external_probe = external_process_probe or default_external_katago_probe
        self._on_status_change = on_status_change

        self.state: EngineState = EngineState.STOPPED
        self.model_fingerprint: str = compute_model_fingerprint(settings.katago_model)

        self._proc: asyncio.subprocess.Process | None = None
        self._start_lock = asyncio.Lock()
        self._stdin_lock = asyncio.Lock()

        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._idle_task: asyncio.Task[None] | None = None

        self._pending: dict[tuple[str, int], _PendingTurn] = {}
        self._control_pending: dict[str, asyncio.Future[dict[str, Any]]] = {}

        # Pitfall #11: track terminated query IDs (bounded FIFO) to block cache poisoning
        self._terminated_ids: set[str] = set()
        self._terminated_order: deque[str] = deque()

        # 3-stage interactive cancellation tracking
        self._interactive_seq: int = 0
        self._active_interactive_id: str | None = None
        self._high_prio_count: int = 0
        self._interactive_clear_event = asyncio.Event()
        self._interactive_clear_event.set()

        # Full-review chunk scheduler
        self._full_review_task: asyncio.Task[None] | None = None
        self._full_review_job_id: str | None = None
        self._full_review_state: str = "IDLE"
        self._full_review_active_chunk_id: str | None = None
        self._full_review_progress_cb: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self._full_review_completed: int = 0
        self._full_review_total: int = 0

        # Idle timer & KaTrain coexistence tracking
        self._idle_since: float | None = None
        self._idle_timeout_effective: float = settings.idle_timeout_sec
        self._external_katago: list[dict[str, Any]] = []
        self._ext_probe_ts: float = 0.0
        self._warmup_suppressed: bool = False
        self._last_error: str | None = None
        self._version_info: dict[str, Any] | None = None
        self._query_counter: int = 0
        self._stderr_recent: deque[str] = deque(maxlen=50)

    def set_status_callback(
        self, callback: Callable[[dict[str, Any]], Awaitable[None]] | None
    ) -> None:
        self._on_status_change = callback

    def _next_id(self, prefix: str) -> str:
        self._query_counter += 1
        return f"{prefix}-{uuid.uuid4().hex[:6]}-{self._query_counter}"

    def _mark_terminated(self, qid: str) -> None:
        if qid in self._terminated_ids:
            return
        self._terminated_ids.add(qid)
        self._terminated_order.append(qid)
        while len(self._terminated_order) > MAX_TERMINATED_IDS:
            oldest = self._terminated_order.popleft()
            self._terminated_ids.discard(oldest)

    def _cleanup_katago_logs(self) -> None:
        log_dir = self.settings.katago_logs_dir
        if log_dir is None:
            return
        log_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(
            (p for p in log_dir.iterdir() if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in files[KATAGO_LOG_KEEP_FILES:]:
            try:
                old.unlink()
            except OSError:
                pass

    async def _emit_status(self) -> None:
        cb = self._on_status_change
        if cb is not None:
            try:
                await cb(self.get_status())
            except Exception as exc:
                logger.debug("Status change callback failed: %s", exc)

    def _set_state(self, new_state: EngineState) -> None:
        self.state = new_state

    async def refresh_external_katago(self, *, force: bool = False) -> list[dict[str, Any]]:
        """Probe external KataGo (KaTrain) processes with 5s cache (Pitfall #8)."""
        now = time.monotonic()
        if not force and (now - self._ext_probe_ts) < EXTERNAL_PROBE_CACHE_SEC:
            return list(self._external_katago)
        own_pid = (
            self._proc.pid
            if self._proc is not None and self._proc.returncode is None
            else None
        )
        try:
            procs = await self._external_probe(own_pid)
        except Exception as exc:
            logger.debug("External KataGo probe failed: %s", exc)
            procs = []
        self._external_katago = list(procs)
        self._ext_probe_ts = now
        self._idle_timeout_effective = (
            self.settings.katrain_idle_timeout_sec
            if self._external_katago
            else self.settings.idle_timeout_sec
        )
        return list(self._external_katago)

    def get_status(self) -> dict[str, Any]:
        remaining: float | None = None
        if self.state == EngineState.IDLE and self._idle_since is not None:
            elapsed = time.monotonic() - self._idle_since
            remaining = max(0.0, round(self._idle_timeout_effective - elapsed, 1))
        ext_rss_mb = round(
            sum(float(p.get("rss_mb", 0.0)) for p in self._external_katago), 1
        )
        return {
            "state": self.state.value,
            "pid": (
                self._proc.pid
                if self._proc is not None and self._proc.returncode is None
                else None
            ),
            "model_fingerprint": self.model_fingerprint,
            "pending_queries": len(self._pending),
            "idle_remaining_sec": remaining,
            "idle_timeout_sec": self._idle_timeout_effective,
            "effective_idle_timeout_sec": self._idle_timeout_effective,
            "external_katago_detected": bool(self._external_katago),
            "external_katago_rss_mb": ext_rss_mb,
            "external_katago_processes": list(self._external_katago),
            "warmup_suppressed": self._warmup_suppressed,
            "full_review_state": self._full_review_state,
            "full_review_job_id": self._full_review_job_id,
            "version": self._version_info,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Low-level pipe I/O (Pitfalls #1, #4)
    # ------------------------------------------------------------------

    async def _send_json(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.returncode is not None:
            raise KataGoError("KataGo process is not running")
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        async with self._stdin_lock:
            if proc.stdin.is_closing():
                raise KataGoError("KataGo stdin is closing")
            proc.stdin.write(line)
            await proc.stdin.drain()  # Pitfall #4: always drain stdin

    async def _send_terminate(self, target_id: str) -> None:
        self._mark_terminated(target_id)
        matching_keys = [k for k in self._pending if k[0] == target_id]
        for key in matching_keys:
            pending = self._pending.pop(key, None)
            if pending is not None and not pending.future.done():
                pending.future.set_result(None)
        if self._proc is None or self._proc.returncode is not None:
            return
        try:
            await self._send_json(
                {
                    "id": self._next_id("term"),
                    "action": "terminate",
                    "terminateId": target_id,
                }
            )
        except Exception as exc:
            logger.debug("Failed to send terminate for %s: %s", target_id, exc)

    async def _stderr_drain_loop(self, proc: asyncio.subprocess.Process) -> None:
        """Continuously drain stderr in 8KB chunks so 64KB pipe NEVER deadlocks (Pitfall #4)."""
        assert proc.stderr is not None
        buf = ""
        try:
            while True:
                chunk = await proc.stderr.read(8192)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                buf += text
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    stripped = line.strip()
                    if stripped:
                        self._stderr_recent.append(stripped)
                        logger.debug("[katago stderr] %s", stripped)
                if len(buf) > 16384:
                    self._stderr_recent.append(buf[-512:])
                    buf = ""
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("stderr drain ended with error: %s", exc)

    async def _stdout_reader_loop(self, proc: asyncio.subprocess.Process) -> None:
        """Read NDJSON lines up to 8MB from KataGo stdout and dispatch safely."""
        assert proc.stdout is not None
        try:
            while True:
                raw_line = await proc.stdout.readline()
                if not raw_line:
                    break
                line_str = raw_line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue
                try:
                    msg = json.loads(line_str)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON line from KataGo stdout: %s", line_str[:200])
                    continue
                if not isinstance(msg, dict):
                    continue
                await self._handle_stdout_message(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = f"KataGo stdout reader failure: {exc}"
            logger.exception("KataGo stdout reader crashed")
        finally:
            # Fail all remaining pending futures if process exited unexpectedly
            unexpected = self.state not in (EngineState.STOPPING, EngineState.STOPPED)
            err = KataGoError(
                self._last_error or "KataGo process exited unexpectedly"
            )
            self._fail_all_pending(err)
            if unexpected:
                self._last_error = str(err)
                self._set_state(EngineState.ERROR)
                await self._emit_status()
                self._proc = None
                self._set_state(EngineState.STOPPED)
                await self._emit_status()

    async def _handle_stdout_message(self, msg: dict[str, Any]) -> None:
        qid = str(msg.get("id", ""))

        # Pitfall #13: Top-level "error" lacks turnNumber -> fail ALL pending turns for qid
        if "error" in msg:
            err_text = str(msg.get("error"))
            exc = KataGoQueryError(f"KataGo error for {qid}: {err_text}")
            ctrl_fut = self._control_pending.pop(qid, None)
            if ctrl_fut is not None and not ctrl_fut.done():
                ctrl_fut.set_exception(exc)

            matching_keys = [k for k in self._pending if k[0] == qid]
            for key in matching_keys:
                pending = self._pending.pop(key, None)
                if pending is not None and not pending.future.done():
                    pending.future.set_exception(exc)
            self._check_idle_transition()
            return

        # Control responses (e.g., query_version)
        if qid in self._control_pending:
            fut = self._control_pending.pop(qid)
            if not fut.done():
                fut.set_result(msg)
            return

        # Ack messages for terminate / terminate_all
        if "action" in msg and "rootInfo" not in msg and "noResults" not in msg:
            return

        turn_number = int(msg.get("turnNumber", 0))
        key = (qid, turn_number)
        pending = self._pending.get(key)

        # Clean cancellation (0 visits) -> resolve as None without error
        if msg.get("noResults") is True:
            self._pending.pop(key, None)
            if pending is not None and not pending.future.done():
                pending.future.set_result(None)
            self._check_idle_transition()
            return

        # Pitfall #11: Terminated query arrived with partial visits -> discard & NEVER cache
        if qid in self._terminated_ids:
            if not msg.get("isDuringSearch", False):
                self._pending.pop(key, None)
                if pending is not None and not pending.future.done():
                    pending.future.set_result(None)
                self._check_idle_transition()
            return

        if pending is None:
            return

        try:
            normalized = normalize_katago_response(
                msg, pending.next_player, pending.board_size
            )
        except Exception as exc:
            self._pending.pop(key, None)
            if not pending.future.done():
                pending.future.set_exception(exc)
            self._check_idle_transition()
            return

        if pending.meta:
            normalized.update(pending.meta)

        if msg.get("isDuringSearch", False):
            # Interim frame: NEVER cache, ONLY deliver if still active interactive query
            if (
                pending.is_interactive
                and qid == self._active_interactive_id
                and pending.on_update is not None
            ):
                try:
                    await asyncio.wait_for(pending.on_update(normalized), timeout=2.0)
                except Exception as exc:
                    logger.debug("on_update callback error: %s", exc)
            return

        # Final result
        self._pending.pop(key, None)
        if pending.is_interactive and qid != self._active_interactive_id:
            if not pending.future.done():
                pending.future.set_result(None)
        else:
            if not pending.future.done():
                pending.future.set_result(normalized)
        self._check_idle_transition()

    def _fail_all_pending(self, exc: Exception) -> None:
        for fut in list(self._control_pending.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._control_pending.clear()
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.set_exception(exc)
        self._pending.clear()

    # ------------------------------------------------------------------
    # Idle auto-stop timer (Pitfalls #5, #8)
    # ------------------------------------------------------------------

    def _cancel_idle_timer(self) -> None:
        self._idle_since = None
        if self._idle_task is not None and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    def _check_idle_transition(self) -> None:
        if self.state not in (EngineState.ANALYZING, EngineState.IDLE):
            return
        if not self._pending and self._full_review_state not in ("RUNNING", "PAUSED_FOR_INTERACTIVE"):
            if self.state != EngineState.IDLE:
                self._set_state(EngineState.IDLE)
                asyncio.create_task(self._emit_status())
            self._start_idle_timer()

    def _start_idle_timer(self) -> None:
        if self._idle_task is not None and not self._idle_task.done():
            return
        self._idle_since = time.monotonic()
        self._idle_task = asyncio.create_task(self._idle_watchdog_loop())

    async def _idle_watchdog_loop(self) -> None:
        try:
            while self.state == EngineState.IDLE and self._idle_since is not None:
                await self.refresh_external_katago()
                elapsed = time.monotonic() - self._idle_since
                remaining = self._idle_timeout_effective - elapsed
                if remaining <= 0:
                    logger.info(
                        "KataGo idle timeout reached (%.1fs); stopping process.",
                        self._idle_timeout_effective,
                    )
                    asyncio.create_task(self.stop())
                    return
                await asyncio.sleep(min(remaining, max(0.05, min(5.0, remaining))))
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # Startup (2-stage handshake, Pitfall #14) & Shutdown (Pitfall #5)
    # ------------------------------------------------------------------

    async def warmup(self, force: bool = False) -> dict[str, Any]:
        """Start KataGo and complete 2-stage handshake (query_version + 9x9 1-visit)."""
        async with self._start_lock:
            if (
                self.state in (EngineState.IDLE, EngineState.ANALYZING)
                and self._proc is not None
                and self._proc.returncode is None
            ):
                return self.get_status()

            if not force and self.state == EngineState.STOPPED:
                ext = await self.refresh_external_katago(force=True)
                if ext:
                    self._warmup_suppressed = True
                    logger.info(
                        "External KataGo detected (%d procs); auto-warmup suppressed.",
                        len(ext),
                    )
                    await self._emit_status()
                    return self.get_status()

            await self._start_locked()
            return self.get_status()

    async def _ensure_started(self) -> None:
        if (
            self.state in (EngineState.IDLE, EngineState.ANALYZING)
            and self._proc is not None
            and self._proc.returncode is None
        ):
            return
        async with self._start_lock:
            if (
                self.state in (EngineState.IDLE, EngineState.ANALYZING)
                and self._proc is not None
                and self._proc.returncode is None
            ):
                return
            await self._start_locked()

    async def _start_locked(self) -> None:
        self._warmup_suppressed = False
        self._last_error = None
        self._cleanup_katago_logs()

        self._set_state(EngineState.STARTING)
        await self._emit_status()

        cmd = self._command_builder(self.settings)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.settings.project_dir),
                limit=STDOUT_BUFFER_LIMIT,  # Pitfall #1: 8MB line limit
            )
        except Exception as exc:
            self._last_error = f"Failed to spawn KataGo: {exc}"
            self._set_state(EngineState.ERROR)
            await self._emit_status()
            self._set_state(EngineState.STOPPED)
            await self._emit_status()
            raise KataGoError(self._last_error) from exc

        self._proc = proc
        self._stdout_task = asyncio.create_task(self._stdout_reader_loop(proc))
        self._stderr_task = asyncio.create_task(self._stderr_drain_loop(proc))

        loop = asyncio.get_running_loop()
        try:
            # Stage 1: query_version handshake
            ver_id = self._next_id("sys-version")
            ver_fut: asyncio.Future[dict[str, Any]] = loop.create_future()
            self._control_pending[ver_id] = ver_fut
            await self._send_json({"id": ver_id, "action": "query_version"})
            ver_timeout = min(15.0, max(1.0, self.settings.warmup_timeout_sec))
            ver_resp = await asyncio.wait_for(ver_fut, timeout=ver_timeout)
            self._version_info = {
                k: v for k, v in ver_resp.items() if k not in ("id", "action")
            }

            # Stage 2: 9x9 1-visit Metal shader warmup (Pitfall #14)
            self._set_state(EngineState.WARMING_UP)
            await self._emit_status()

            warm_id = self._next_id("sys-warmup")
            warm_fut: asyncio.Future[dict[str, Any] | None] = loop.create_future()
            self._pending[(warm_id, 0)] = _PendingTurn(
                query_id=warm_id,
                turn_number=0,
                next_player="B",
                board_size=9,
                future=warm_fut,
                is_interactive=False,
            )
            await self._send_json(
                {
                    "id": warm_id,
                    "moves": [],
                    "initialStones": [],
                    "initialPlayer": "B",
                    "rules": "japanese",
                    "komi": 6.5,
                    "boardXSize": 9,
                    "boardYSize": 9,
                    "analyzeTurns": [0],
                    "maxVisits": 1,
                    "includeOwnership": False,
                    "priority": 100,
                }
            )
            await asyncio.wait_for(warm_fut, timeout=self.settings.warmup_timeout_sec)

            await self.refresh_external_katago(force=True)
            self._set_state(EngineState.IDLE)
            self._start_idle_timer()
            await self._emit_status()
        except Exception as exc:
            self._last_error = f"KataGo handshake/warmup failed: {exc}"
            logger.error("%s", self._last_error)
            self._set_state(EngineState.ERROR)
            await self._emit_status()
            await self._teardown_process()
            self._set_state(EngineState.STOPPED)
            await self._emit_status()
            if isinstance(exc, asyncio.TimeoutError):
                raise KataGoTimeoutError(self._last_error) from exc
            if isinstance(exc, KataGoError):
                raise
            raise KataGoError(self._last_error) from exc

    async def _teardown_process(self) -> None:
        """Graceful terminate_all -> stdin close -> wait(5s) -> SIGTERM -> SIGKILL (Pitfall #5)."""
        self._cancel_idle_timer()
        proc = self._proc
        self._proc = None

        if proc is not None and proc.returncode is None:
            try:
                if proc.stdin is not None and not proc.stdin.is_closing():
                    line = (
                        json.dumps({"id": self._next_id("term-all"), "action": "terminate_all"})
                        + "\n"
                    ).encode("utf-8")
                    proc.stdin.write(line)
                    await asyncio.wait_for(proc.stdin.drain(), timeout=1.0)
                    proc.stdin.close()
            except Exception:
                try:
                    if proc.stdin is not None and not proc.stdin.is_closing():
                        proc.stdin.close()
                except Exception:
                    pass

            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    await proc.wait()

        for task in (self._stdout_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
        tasks_to_await = [t for t in (self._stdout_task, self._stderr_task) if t is not None]
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)
        self._stdout_task = None
        self._stderr_task = None
        self._fail_all_pending(KataGoError("KataGo stopped"))

    async def stop(self) -> None:
        """Stop full review, interactive queries, and subprocess cleanly."""
        if self.state == EngineState.STOPPED and self._proc is None:
            return
        await self.cancel("all")
        self._set_state(EngineState.STOPPING)
        await self._emit_status()
        await self._teardown_process()
        self._set_state(EngineState.STOPPED)
        await self._emit_status()

    # ------------------------------------------------------------------
    # Interactive analysis (3-stage cancel) & One-shot analysis
    # ------------------------------------------------------------------

    async def _enter_high_priority(self) -> None:
        self._high_prio_count += 1
        self._interactive_clear_event.clear()
        if self._full_review_state == "RUNNING":
            self._full_review_state = "PAUSED_FOR_INTERACTIVE"
            cb = self._full_review_progress_cb
            if cb is not None and self._full_review_job_id is not None:
                try:
                    await cb(
                        {
                            "job_id": self._full_review_job_id,
                            "status": "paused",
                            "completed": self._full_review_completed,
                            "total": self._full_review_total,
                        }
                    )
                except Exception as exc:
                    logger.debug("Full review pause progress callback error: %s", exc)

    async def _exit_high_priority(self) -> None:
        self._high_prio_count = max(0, self._high_prio_count - 1)
        if self._high_prio_count == 0:
            self._interactive_clear_event.set()

    async def analyze_interactive(
        self,
        query_payload: dict[str, Any],
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        debounce: bool = True,
    ) -> dict[str, Any] | None:
        """Run interactive real-time analysis with 3-stage cancellation.

        Stage 1: Debounce rapid bursts (settings.interactive_debounce_sec)
        Stage 2: Explicit terminate for superseded query + mark in terminated_ids
        Stage 3: Discard late frames whose id != active_interactive_query_id
        """
        self._interactive_seq += 1
        my_seq = self._interactive_seq

        await self._enter_high_priority()
        qid: str | None = None
        turn_num = int((query_payload.get("analyzeTurns") or [len(query_payload.get("moves") or [])])[0])
        try:
            # Terminate any already-running interactive query right away
            if self._active_interactive_id is not None:
                prev_id = self._active_interactive_id
                self._active_interactive_id = None
                await self._send_terminate(prev_id)

            # Stage 1: Debounce
            if debounce and self.settings.interactive_debounce_sec > 0:
                await asyncio.sleep(self.settings.interactive_debounce_sec)
                if my_seq != self._interactive_seq:
                    return None

            await self._ensure_started()
            if my_seq != self._interactive_seq:
                return None

            # Stage 2: Register new active interactive query
            if self._active_interactive_id is not None:
                prev_id = self._active_interactive_id
                self._active_interactive_id = None
                await self._send_terminate(prev_id)

            qid = self._next_id("rt")
            self._active_interactive_id = qid

            board_size = int(query_payload.get("boardXSize", 19))
            next_player = str(query_payload.get("next_player") or self._infer_next_player(query_payload))
            meta = {
                k: query_payload[k]
                for k in ("node_id", "position_hash")
                if k in query_payload
            }

            raw_q = dict(query_payload)
            raw_q["id"] = qid
            raw_q.setdefault("analyzeTurns", [turn_num])
            raw_q.setdefault("maxVisits", 500)
            raw_q.setdefault("includeOwnership", True)
            raw_q.setdefault("includePVVisits", True)
            raw_q.setdefault("reportDuringSearchEvery", 0.3)
            raw_q.setdefault("priority", 10)
            sanitized = _sanitize_katago_query(raw_q)

            loop = asyncio.get_running_loop()
            fut: asyncio.Future[dict[str, Any] | None] = loop.create_future()
            self._pending[(qid, turn_num)] = _PendingTurn(
                query_id=qid,
                turn_number=turn_num,
                next_player=next_player,
                board_size=board_size,
                future=fut,
                is_interactive=True,
                on_update=on_update,
                meta=meta,
            )

            self._cancel_idle_timer()
            if self.state != EngineState.ANALYZING:
                self._set_state(EngineState.ANALYZING)
                await self._emit_status()

            await self._send_json(sanitized)

            # Stage 3: Await final response; stale/terminated returns None
            result = await asyncio.wait_for(fut, timeout=self.settings.query_timeout_sec)
            if qid != self._active_interactive_id or qid in self._terminated_ids:
                return None
            return result
        except asyncio.TimeoutError as exc:
            if qid is not None:
                await self._send_terminate(qid)
                self._pending.pop((qid, turn_num), None)
            self._check_idle_transition()
            raise KataGoTimeoutError(
                f"Interactive analysis timed out after {self.settings.query_timeout_sec}s"
            ) from exc
        except asyncio.CancelledError:
            if qid is not None:
                await self._send_terminate(qid)
                self._pending.pop((qid, turn_num), None)
            self._check_idle_transition()
            raise
        finally:
            if qid is not None and self._active_interactive_id == qid:
                self._active_interactive_id = None
            await self._exit_high_priority()
            self._check_idle_transition()

    async def analyze_once(
        self,
        query_payload: dict[str, Any],
        priority: int = 20,
    ) -> dict[str, Any]:
        """Run a single non-streaming analysis query (AI move or deep evaluation)."""
        high_prio = priority >= 10
        if high_prio:
            await self._enter_high_priority()
        qid: str | None = None
        turn_num = int((query_payload.get("analyzeTurns") or [len(query_payload.get("moves") or [])])[0])
        try:
            await self._ensure_started()
            qid = self._next_id("once")
            board_size = int(query_payload.get("boardXSize", 19))
            next_player = str(query_payload.get("next_player") or self._infer_next_player(query_payload))
            meta = {
                k: query_payload[k]
                for k in ("node_id", "position_hash")
                if k in query_payload
            }

            raw_q = dict(query_payload)
            raw_q["id"] = qid
            raw_q.setdefault("analyzeTurns", [turn_num])
            raw_q.setdefault("includeOwnership", True)
            raw_q["priority"] = priority
            raw_q.pop("reportDuringSearchEvery", None)  # Never stream on AI/once queries
            sanitized = _sanitize_katago_query(raw_q)

            loop = asyncio.get_running_loop()
            fut: asyncio.Future[dict[str, Any] | None] = loop.create_future()
            self._pending[(qid, turn_num)] = _PendingTurn(
                query_id=qid,
                turn_number=turn_num,
                next_player=next_player,
                board_size=board_size,
                future=fut,
                is_interactive=False,
                meta=meta,
            )

            self._cancel_idle_timer()
            if self.state != EngineState.ANALYZING:
                self._set_state(EngineState.ANALYZING)
                await self._emit_status()

            await self._send_json(sanitized)
            result = await asyncio.wait_for(fut, timeout=self.settings.query_timeout_sec)
            if result is None:
                raise KataGoQueryError("Analysis was cancelled before producing results")
            return result
        except asyncio.TimeoutError as exc:
            if qid is not None:
                await self._send_terminate(qid)
                self._pending.pop((qid, turn_num), None)
            self._check_idle_transition()
            raise KataGoTimeoutError(
                f"Analysis timed out after {self.settings.query_timeout_sec}s"
            ) from exc
        except asyncio.CancelledError:
            if qid is not None:
                await self._send_terminate(qid)
                self._pending.pop((qid, turn_num), None)
            self._check_idle_transition()
            raise
        finally:
            if high_prio:
                await self._exit_high_priority()
            self._check_idle_transition()

    # ------------------------------------------------------------------
    # Chunked Full-Review Scheduler (4 turns/chunk, interactive preemption)
    # ------------------------------------------------------------------

    async def start_full_review(
        self,
        job_id: str,
        turns: list[dict[str, Any]],
        on_turn: Callable[[dict[str, Any]], Awaitable[None]],
        on_progress: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Start chunked full-game review (4 turns/chunk, priority=-10, pauses for interactive)."""
        await self.cancel("full_review")
        self._full_review_job_id = job_id
        self._full_review_state = "RUNNING"
        self._full_review_task = asyncio.create_task(
            self._full_review_runner(job_id, list(turns), on_turn, on_progress)
        )

    @staticmethod
    def _chunk_can_batch_single_query(chunk: list[dict[str, Any]]) -> bool:
        """Check whether all turns in chunk share one game line for a single multi-turn query."""
        if not chunk:
            return False
        base = chunk[-1]
        base_moves = base.get("moves") or []
        base_init = base.get("initialStones") or []
        base_sig = (
            base.get("boardXSize", 19),
            base.get("boardYSize", 19),
            base.get("rules", "japanese"),
            base.get("komi", 6.5),
            base.get("initialPlayer", "B"),
        )
        seen_turns: set[int] = set()
        for item in chunk:
            sig = (
                item.get("boardXSize", 19),
                item.get("boardYSize", 19),
                item.get("rules", "japanese"),
                item.get("komi", 6.5),
                item.get("initialPlayer", "B"),
            )
            if sig != base_sig or (item.get("initialStones") or []) != base_init:
                return False
            t_num = int(item.get("turn_number", len(item.get("moves") or [])))
            if t_num in seen_turns or t_num > len(base_moves):
                return False
            seen_turns.add(t_num)
            item_moves = item.get("moves")
            if item_moves is not None and item_moves != base_moves[: len(item_moves)]:
                return False
        return True

    async def _full_review_runner(
        self,
        job_id: str,
        turns: list[dict[str, Any]],
        on_turn: Callable[[dict[str, Any]], Awaitable[None]],
        on_progress: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        total = len(turns)
        completed = 0
        self._full_review_progress_cb = on_progress
        self._full_review_completed = 0
        self._full_review_total = total
        try:
            await on_progress(
                {
                    "job_id": job_id,
                    "status": "running",
                    "completed": 0,
                    "total": total,
                }
            )
            if total == 0:
                self._full_review_state = "IDLE"
                await on_progress(
                    {
                        "job_id": job_id,
                        "status": "completed",
                        "completed": 0,
                        "total": 0,
                    }
                )
                return

            await self._ensure_started()

            for offset in range(0, total, FULL_REVIEW_CHUNK_SIZE):
                if self._full_review_state == "CANCELLED":
                    break

                # Interactive / AI priority gate: pause before submitting next chunk
                if not self._interactive_clear_event.is_set() or self._full_review_state == "PAUSED_FOR_INTERACTIVE":
                    if self._full_review_state != "PAUSED_FOR_INTERACTIVE":
                        self._full_review_state = "PAUSED_FOR_INTERACTIVE"
                        await on_progress(
                            {
                                "job_id": job_id,
                                "status": "paused",
                                "completed": completed,
                                "total": total,
                            }
                        )
                    await self._interactive_clear_event.wait()
                    if self._full_review_state == "CANCELLED":
                        break
                    self._full_review_state = "RUNNING"
                    await on_progress(
                        {
                            "job_id": job_id,
                            "status": "running",
                            "completed": completed,
                            "total": total,
                        }
                    )

                chunk = turns[offset : offset + FULL_REVIEW_CHUNK_SIZE]
                chunk_results = await self._execute_review_chunk(chunk)
                for res in chunk_results:
                    if self._full_review_state == "CANCELLED":
                        break
                    if res is not None:
                        await on_turn(res)
                    completed += 1
                    self._full_review_completed = completed
                    await on_progress(
                        {
                            "job_id": job_id,
                            "status": "running",
                            "completed": completed,
                            "total": total,
                            "node_id": res.get("node_id") if res else None,
                        }
                    )
                await asyncio.sleep(0)

            final_status = (
                "cancelled" if self._full_review_state == "CANCELLED" else "completed"
            )
            self._full_review_state = "IDLE"
            await on_progress(
                {
                    "job_id": job_id,
                    "status": final_status,
                    "completed": completed,
                    "total": total,
                }
            )
        except asyncio.CancelledError:
            self._full_review_state = "IDLE"
            try:
                await on_progress(
                    {
                        "job_id": job_id,
                        "status": "cancelled",
                        "completed": completed,
                        "total": total,
                    }
                )
            except Exception:
                pass
            raise
        except Exception as exc:
            logger.error("Full review job %s failed: %s", job_id, exc)
            self._full_review_state = "IDLE"
            try:
                await on_progress(
                    {
                        "job_id": job_id,
                        "status": "error",
                        "completed": completed,
                        "total": total,
                        "error": str(exc),
                    }
                )
            except Exception:
                pass
        finally:
            self._full_review_active_chunk_id = None
            self._full_review_progress_cb = None
            if self._full_review_job_id == job_id:
                self._full_review_job_id = None
            self._check_idle_transition()

    async def _execute_review_chunk(
        self, chunk: list[dict[str, Any]]
    ) -> list[dict[str, Any] | None]:
        loop = asyncio.get_running_loop()
        self._cancel_idle_timer()
        if self.state != EngineState.ANALYZING:
            self._set_state(EngineState.ANALYZING)
            await self._emit_status()

        if self._chunk_can_batch_single_query(chunk):
            qid = self._next_id("fr")
            self._full_review_active_chunk_id = qid
            base = chunk[-1]
            board_size = int(base.get("boardXSize", 19))
            max_visits = int(base.get("maxVisits", FULL_REVIEW_DEFAULT_VISITS))

            analyze_turns: list[int] = []
            futures: list[asyncio.Future[dict[str, Any] | None]] = []
            for item in chunk:
                t_num = int(item.get("turn_number", len(item.get("moves") or [])))
                analyze_turns.append(t_num)
                next_player = str(
                    item.get("next_player") or self._infer_next_player(item, t_num)
                )
                meta = {
                    k: item[k] for k in ("node_id", "position_hash") if k in item
                }
                fut: asyncio.Future[dict[str, Any] | None] = loop.create_future()
                self._pending[(qid, t_num)] = _PendingTurn(
                    query_id=qid,
                    turn_number=t_num,
                    next_player=next_player,
                    board_size=board_size,
                    future=fut,
                    is_interactive=False,
                    meta=meta,
                )
                futures.append(fut)

            query = _sanitize_katago_query(
                {
                    "id": qid,
                    "moves": base.get("moves") or [],
                    "initialStones": base.get("initialStones") or [],
                    "initialPlayer": base.get("initialPlayer", "B"),
                    "rules": base.get("rules", "japanese"),
                    "komi": base.get("komi", 6.5),
                    "boardXSize": board_size,
                    "boardYSize": int(base.get("boardYSize", board_size)),
                    "analyzeTurns": analyze_turns,
                    "maxVisits": max_visits,
                    "includeOwnership": True,
                    "priority": -10,
                }
            )
            await self._send_json(query)
            timeout = self.settings.query_timeout_sec * max(1, len(chunk))
            try:
                return list(await asyncio.wait_for(asyncio.gather(*futures), timeout=timeout))
            except asyncio.TimeoutError as exc:
                await self._send_terminate(qid)
                for t_num in analyze_turns:
                    self._pending.pop((qid, t_num), None)
                raise KataGoTimeoutError("Full review chunk timed out") from exc
            finally:
                self._full_review_active_chunk_id = None

        # Heterogeneous turns fallback: run sequentially/concurrently within chunk
        results: list[dict[str, Any] | None] = []
        for item in chunk:
            if self._full_review_state == "CANCELLED":
                break
            q = dict(item)
            q.setdefault("maxVisits", FULL_REVIEW_DEFAULT_VISITS)
            res = await self.analyze_once(q, priority=-10)
            results.append(res)
        return results

    async def cancel(self, scope: str = "all") -> None:
        """Cancel interactive analysis, full review, or all in-flight queries."""
        if scope in ("interactive", "all"):
            self._interactive_seq += 1
            if self._active_interactive_id is not None:
                old_id = self._active_interactive_id
                self._active_interactive_id = None
                await self._send_terminate(old_id)

        if scope in ("full_review", "all"):
            self._full_review_state = "CANCELLED"
            if self._full_review_active_chunk_id is not None:
                chunk_id = self._full_review_active_chunk_id
                self._full_review_active_chunk_id = None
                await self._send_terminate(chunk_id)
            if self._full_review_task is not None and not self._full_review_task.done():
                self._full_review_task.cancel()
                await asyncio.gather(self._full_review_task, return_exceptions=True)
            self._full_review_task = None
            self._full_review_job_id = None
            self._full_review_state = "IDLE"

        if scope == "all":
            for key, pending in list(self._pending.items()):
                self._mark_terminated(key[0])
                self._pending.pop(key, None)
                if not pending.future.done():
                    pending.future.set_result(None)
            if self._proc is not None and self._proc.returncode is None:
                try:
                    await self._send_json(
                        {"id": self._next_id("term-all"), "action": "terminate_all"}
                    )
                except Exception:
                    pass

        self._check_idle_transition()

    @staticmethod
    def _infer_next_player(
        query_payload: dict[str, Any], turn_number: int | None = None
    ) -> str:
        moves = query_payload.get("moves") or []
        idx = len(moves) if turn_number is None else turn_number
        if idx > 0 and idx <= len(moves):
            last_color = str(moves[idx - 1][0]).upper()
            return "W" if last_color == "B" else "B"
        return str(query_payload.get("initialPlayer", "B")).upper()


__all__ = [
    "STDOUT_BUFFER_LIMIT",
    "FULL_REVIEW_CHUNK_SIZE",
    "FULL_REVIEW_DEFAULT_VISITS",
    "EngineState",
    "KataGoError",
    "KataGoQueryError",
    "KataGoTimeoutError",
    "AI_PRESETS",
    "compute_score_loss",
    "classify_move_quality",
    "normalize_katago_response",
    "select_ai_move",
    "compute_model_fingerprint",
    "AnalysisEngineProtocol",
    "default_katago_command",
    "default_external_katago_probe",
    "KataGoEngine",
]
