"""Layer 1 unit & OS-pipe subprocess tests for app.katago_engine (Pitfalls #1,#3,#4,#5,#8,#10,#11,#13,#14,#17)."""

from __future__ import annotations

import asyncio
import os
import random
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.db import Database
from app.katago_engine import (
    EngineState,
    KataGoEngine,
    KataGoError,
    KataGoQueryError,
    STDOUT_BUFFER_LIMIT,
    compute_score_loss,
    select_ai_move,
)
from tests.fakes.fake_katago import make_fake_katago_command_builder


def _make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "idle_timeout_sec": 60.0,
        "katrain_idle_timeout_sec": 10.0,
        "warmup_timeout_sec": 10.0,
        "query_timeout_sec": 10.0,
        "interactive_debounce_sec": 0.02,
    }
    defaults.update(overrides)
    settings = Settings(**defaults)
    settings.ensure_dirs()
    return settings


async def _no_external_katago(_own_pid: int | None) -> list[dict[str, Any]]:
    return []


def _base_query(board_size: int = 19, moves: list[list[str]] | None = None, **extra: Any) -> dict[str, Any]:
    mv = moves if moves is not None else [["B", "Q16"], ["W", "D4"]]
    q: dict[str, Any] = {
        "moves": mv,
        "initialStones": [],
        "initialPlayer": "B",
        "rules": "japanese",
        "komi": 6.5,
        "boardXSize": board_size,
        "boardYSize": board_size,
        "analyzeTurns": [len(mv)],
        "maxVisits": 100,
        "includeOwnership": True,
    }
    q.update(extra)
    return q


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


async def test_large_ndjson_line_above_64kb_and_dynamic_ownership_sizes(tmp_path: Path) -> None:
    """Pitfall #1 (120KB-200KB single NDJSON line with 8MB limit) & Pitfall #10 (81/169/361 ownership)."""
    assert STDOUT_BUFFER_LIMIT == 8 * 1024 * 1024
    settings = _make_settings(tmp_path)
    engine = KataGoEngine(
        settings,
        command_builder=make_fake_katago_command_builder(large_bytes=155_000),
        external_process_probe=_no_external_katago,
    )
    try:
        res19 = await engine.analyze_once(_base_query(19, maxVisits=120))
        assert res19["is_final"] is True
        assert res19["ownership"] is not None
        assert len(res19["ownership"]) == 361
        # Padded moveInfos confirms >120KB line was cleanly parsed
        assert len(res19["moves"]) > 40

        res13 = await engine.analyze_once(_base_query(13, moves=[["B", "K10"]], maxVisits=50))
        assert res13["ownership"] is not None
        assert len(res13["ownership"]) == 169

        res9 = await engine.analyze_once(_base_query(9, moves=[["B", "E5"]], maxVisits=50))
        assert res9["ownership"] is not None
        assert len(res9["ownership"]) == 81
    finally:
        await engine.stop()


async def test_streaming_noresults_and_terminated_partial_never_pollutes_cache(tmp_path: Path) -> None:
    """Pitfall #11: isDuringSearch streams, noResults ignored cleanly, terminated partial NEVER pollutes DB."""
    settings = _make_settings(tmp_path, interactive_debounce_sec=0.0)
    db = Database(settings.db_path)  # type: ignore[arg-type]
    await db.connect()

    # 1. Partial-visits terminate mode: verify terminated query returns None and NEVER writes poisoned visits=12
    engine_partial = KataGoEngine(
        settings,
        command_builder=make_fake_katago_command_builder(delay_sec=0.35, terminate_mode="partial"),
        external_process_probe=_no_external_katago,
    )
    try:
        interim_frames: list[dict[str, Any]] = []

        async def _on_update(frame: dict[str, Any]) -> None:
            interim_frames.append(frame)

        pos_hash = "hash-partial-test-001"
        # Seed high-quality cached entry (visits=500)
        inserted = await db.upsert_analysis_cache(
            position_hash=pos_hash,
            board_size=19,
            actual_visits=500,
            root_info={"winrate_black": 0.564, "score_lead_black": 2.4, "visits": 500},
            move_infos=[{"move": "Q14", "score_loss": 0.0}],
            ownership=[0.0] * 361,
            model_fingerprint=engine_partial.model_fingerprint,
        )
        assert inserted is True

        # Start slow interactive analysis, wait for interim frame, then terminate it
        task = asyncio.create_task(
            engine_partial.analyze_interactive(
                _base_query(19, maxVisits=500, position_hash=pos_hash),
                on_update=_on_update,
                debounce=False,
            )
        )
        deadline = asyncio.get_running_loop().time() + 3.0
        while not interim_frames and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.02)
        assert len(interim_frames) >= 1
        assert interim_frames[0]["is_final"] is False

        await engine_partial.cancel("interactive")
        result = await task
        assert result is None

        # Even if caller attempted to cache a lower-visits result, DB rejects downgrade
        downgraded = await db.upsert_analysis_cache(
            position_hash=pos_hash,
            board_size=19,
            actual_visits=12,
            root_info={"winrate_black": 0.1234, "score_lead_black": -19.75, "visits": 12},
            move_infos=[],
            ownership=None,
            model_fingerprint=engine_partial.model_fingerprint,
        )
        assert downgraded is False
        cached = await db.get_analysis_cache(pos_hash)
        assert cached is not None
        assert cached["actual_visits"] == 500
        assert cached["root"]["winrate_black"] == 0.564
    finally:
        await engine_partial.stop()

    # 2. noResults: true mode cleanly resolves to None without exception
    engine_nores = KataGoEngine(
        settings,
        command_builder=make_fake_katago_command_builder(delay_sec=0.35, terminate_mode="noresults"),
        external_process_probe=_no_external_katago,
    )
    try:
        got_interim = asyncio.Event()

        async def _on_u(_f: dict[str, Any]) -> None:
            got_interim.set()

        t2 = asyncio.create_task(
            engine_nores.analyze_interactive(_base_query(19, maxVisits=200), on_update=_on_u, debounce=False)
        )
        await asyncio.wait_for(got_interim.wait(), timeout=3.0)
        await engine_nores.cancel("interactive")
        assert await t2 is None
    finally:
        await engine_nores.stop()
        await db.close()


async def test_three_stage_cancellation_and_chunked_full_review_preemption(tmp_path: Path) -> None:
    """Verify 3-stage debounce/terminate/discard AND full-review pause on interactive + auto-resume."""
    settings = _make_settings(tmp_path, interactive_debounce_sec=0.08)
    engine = KataGoEngine(
        settings,
        command_builder=make_fake_katago_command_builder(delay_sec=0.06, terminate_mode="noresults"),
        external_process_probe=_no_external_katago,
    )
    try:
        await engine.warmup(force=True)

        # Stage 1+2+3: burst 4 rapid interactive requests -> only the final one returns a result
        burst_tasks = []
        for idx in range(4):
            q = _base_query(19, moves=[["B", "Q16"], ["W", "D4"], ["B", "Q4"]][: (idx % 3) + 1], node_id=f"n-{idx}")
            burst_tasks.append(asyncio.create_task(engine.analyze_interactive(q, debounce=True)))
            await asyncio.sleep(0.015)

        burst_results = await asyncio.gather(*burst_tasks)
        assert burst_results[0] is None
        assert burst_results[1] is None
        assert burst_results[2] is None
        assert burst_results[3] is not None
        assert burst_results[3]["node_id"] == "n-3"

        # Chunked full review (10 turns -> 3 chunks of 4, 4, 2) preempted by interactive query!
        moves_10 = [
            ["B", "Q16"], ["W", "D4"], ["B", "Q4"], ["W", "D16"],
            ["B", "F3"], ["W", "C6"], ["B", "K4"], ["W", "R14"],
            ["B", "O17"], ["W", "S16"],
        ]
        turns = [
            {
                "node_id": f"n-{i:04d}",
                "turn_number": i,
                "moves": moves_10[:i],
                "initialStones": [],
                "initialPlayer": "B",
                "rules": "japanese",
                "komi": 6.5,
                "boardXSize": 19,
                "boardYSize": 19,
                "maxVisits": 150,
            }
            for i in range(1, 11)
        ]

        progress_events: list[dict[str, Any]] = []
        completed_turns: list[dict[str, Any]] = []
        first_chunk_done = asyncio.Event()
        review_done = asyncio.Event()

        async def _on_turn(res: dict[str, Any]) -> None:
            completed_turns.append(res)
            if len(completed_turns) >= 2:
                first_chunk_done.set()

        async def _on_progress(ev: dict[str, Any]) -> None:
            progress_events.append(ev)
            if ev.get("status") in ("completed", "cancelled", "error"):
                review_done.set()

        await engine.start_full_review("job-preempt", turns, _on_turn, _on_progress)
        await asyncio.wait_for(first_chunk_done.wait(), timeout=5.0)

        # Trigger high-priority interactive query while full review is between chunks
        inter_res = await engine.analyze_interactive(
            _base_query(19, moves=moves_10[:5], node_id="n-interactive"),
            debounce=True,
        )
        assert inter_res is not None
        assert inter_res["node_id"] == "n-interactive"

        await asyncio.wait_for(review_done.wait(), timeout=10.0)
        statuses = [ev["status"] for ev in progress_events]
        assert "paused" in statuses, f"Expected full review to pause for interactive query, got {statuses}"
        assert statuses[-1] == "completed"
        assert len(completed_turns) == 10
    finally:
        await engine.stop()


async def test_stderr_128kb_flood_no_deadlock(tmp_path: Path) -> None:
    """Pitfall #4: continuous stderr drain prevents 64KB OS pipe deadlock on 128KB+ stderr output."""
    settings = _make_settings(tmp_path)
    engine = KataGoEngine(
        settings,
        command_builder=make_fake_katago_command_builder(stderr_flood_bytes=160_000),
        external_process_probe=_no_external_katago,
    )
    try:
        res = await asyncio.wait_for(engine.analyze_once(_base_query(9, moves=[])), timeout=8.0)
        assert res["is_final"] is True
        assert res["ownership"] is not None and len(res["ownership"]) == 81
    finally:
        await engine.stop()


async def test_top_level_error_releases_pending_futures_without_hang(tmp_path: Path) -> None:
    """Pitfall #13: top-level {'id': qid, 'error': ...} without turnNumber fails pending immediately."""
    settings = _make_settings(tmp_path)
    engine = KataGoEngine(
        settings,
        command_builder=make_fake_katago_command_builder(error_on_query=1),
        external_process_probe=_no_external_katago,
    )
    try:
        with pytest.raises(KataGoQueryError, match="Simulated KataGo error"):
            await asyncio.wait_for(engine.analyze_once(_base_query(9, moves=[])), timeout=5.0)

        # Engine subprocess MUST remain alive for query #2!
        res2 = await asyncio.wait_for(engine.analyze_once(_base_query(9, moves=[["B", "E5"]])), timeout=5.0)
        assert res2["is_final"] is True
        assert engine.state == EngineState.IDLE
    finally:
        await engine.stop()


async def test_crash_recovery_and_short_idle_auto_stop_zero_zombies(tmp_path: Path) -> None:
    """Pitfall #5: crash recovery restarts subprocess cleanly; short idle stops process with zero zombies."""
    marker = tmp_path / "crashed_once.flag"
    settings = _make_settings(tmp_path, idle_timeout_sec=0.35)
    engine = KataGoEngine(
        settings,
        command_builder=make_fake_katago_command_builder(crash_once_file=marker),
        external_process_probe=_no_external_katago,
    )
    try:
        await engine.warmup(force=True)
        first_pid = engine.get_status()["pid"]
        assert first_pid is not None

        # Query #1 triggers simulated crash
        with pytest.raises(KataGoError):
            await asyncio.wait_for(engine.analyze_once(_base_query(9, moves=[])), timeout=5.0)
        assert marker.exists()

        # Wait briefly for stdout reader cleanup -> STOPPED
        await asyncio.sleep(0.05)
        assert engine.state == EngineState.STOPPED

        # Query #2 auto-restarts subprocess and succeeds
        res = await asyncio.wait_for(engine.analyze_once(_base_query(9, moves=[["B", "E5"]])), timeout=5.0)
        assert res["is_final"] is True
        restarted_pid = engine.get_status()["pid"]
        assert restarted_pid is not None
        assert restarted_pid != first_pid

        # Wait for short idle_timeout_sec=0.35 to auto-stop the engine cleanly
        deadline = asyncio.get_running_loop().time() + 3.0
        while engine.state != EngineState.STOPPED and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)

        assert engine.state == EngineState.STOPPED
        assert engine.get_status()["pid"] is None
        assert not _pid_is_alive(restarted_pid), f"Zombie process left behind: pid={restarted_pid}"
    finally:
        await engine.stop()


async def test_external_katrain_detection_suppresses_warmup_and_shortens_idle(tmp_path: Path) -> None:
    """Pitfall #8: KaTrain detection suppresses warmup(force=False) & shortens idle timeout."""
    async def _fake_katrain_probe(_own_pid: int | None) -> list[dict[str, Any]]:
        return [{"pid": 99999, "ppid": 1, "rss_kb": 1_500_000, "rss_mb": 1464.8, "command": "/opt/homebrew/bin/katago analysis"}]

    settings = _make_settings(tmp_path, idle_timeout_sec=900.0, katrain_idle_timeout_sec=180.0)
    engine = KataGoEngine(
        settings,
        command_builder=make_fake_katago_command_builder(),
        external_process_probe=_fake_katrain_probe,
    )
    try:
        st = await engine.warmup(force=False)
        assert st["state"] == EngineState.STOPPED.value
        assert st["external_katago_detected"] is True
        assert st["warmup_suppressed"] is True
        assert st["effective_idle_timeout_sec"] == 180.0

        # Force warmup starts anyway, but keeps shortened idle timeout (180s instead of 900s)
        st_forced = await engine.warmup(force=True)
        assert st_forced["state"] == EngineState.IDLE.value
        assert st_forced["effective_idle_timeout_sec"] == 180.0
    finally:
        await engine.stop()


def test_ai_strength_softmax_and_black_white_sign_correctness() -> None:
    """Verify Pitfall #3 sign correctness and 15k vs max softmax temperature selection."""
    # Black to move: higher score_lead_black is better for Black
    assert compute_score_loss(2.4, 0.4, "B") == pytest.approx(2.0)
    assert compute_score_loss(2.4, 3.0, "B") == pytest.approx(0.0)
    # White to move: LOWER score_lead_black is better for White
    assert compute_score_loss(-2.4, -0.4, "W") == pytest.approx(2.0)
    assert compute_score_loss(-2.4, -3.0, "W") == pytest.approx(0.0)

    black_analysis = {
        "root": {"winrate_black": 0.56, "score_lead_black": 2.4},
        "moves": [
            {"move": "Q14", "order": 0, "score_lead_black": 2.4},   # loss 0.0
            {"move": "R10", "order": 1, "score_lead_black": 1.6},   # loss 0.8
            {"move": "D14", "order": 2, "score_lead_black": 0.4},   # loss 2.0
            {"move": "K16", "order": 3, "score_lead_black": -1.2},  # loss 3.6
            {"move": "A1", "order": 4, "score_lead_black": -8.5},   # loss 10.9 (blunder -> filtered out!)
        ],
    }

    # max level ALWAYS selects best move Q14
    for seed in range(20):
        choice = select_ai_move(black_analysis, "B", "max", rng=random.Random(seed))
        assert choice["move"] == "Q14"
        assert choice["should_resign"] is False

    # 15k samples non-best moves within max_loss=6.0, NEVER picks blunder A1 (-10.9 loss)
    picks_15k = {select_ai_move(black_analysis, "B", "15k", rng=random.Random(s))["move"] for s in range(60)}
    assert len(picks_15k) >= 2
    assert "A1" not in picks_15k

    # White to move: BEST move for White has LOWEST score_lead_black (-2.4)
    white_analysis = {
        "root": {"winrate_black": 0.44, "score_lead_black": -2.4},
        "moves": [
            {"move": "D16", "order": 0, "score_lead_black": -2.4},  # loss 0.0 for White
            {"move": "C14", "order": 1, "score_lead_black": -1.6},  # loss 0.8 for White
            {"move": "F17", "order": 2, "score_lead_black": -0.4},  # loss 2.0 for White
            {"move": "T1", "order": 3, "score_lead_black": 8.5},    # loss 10.9 blunder for White!
        ],
    }
    assert select_ai_move(white_analysis, "W", "max", rng=random.Random(0))["move"] == "D16"
    picks_w_15k = {select_ai_move(white_analysis, "W", "15k", rng=random.Random(s))["move"] for s in range(60)}
    assert "T1" not in picks_w_15k
    assert len(picks_w_15k) >= 2

    # Auto-resign sign check for both Black and White
    lost_for_black = {"root": {"winrate_black": 0.01, "score_lead_black": -30.0}, "moves": [{"move": "Q14", "order": 0, "score_lead_black": -30.0}]}
    assert select_ai_move(lost_for_black, "B", "5k")["should_resign"] is True
    assert select_ai_move(lost_for_black, "W", "5k")["should_resign"] is False

    lost_for_white = {"root": {"winrate_black": 0.99, "score_lead_black": 30.0}, "moves": [{"move": "Q14", "order": 0, "score_lead_black": 30.0}]}
    assert select_ai_move(lost_for_white, "W", "5k")["should_resign"] is True
    assert select_ai_move(lost_for_white, "B", "5k")["should_resign"] is False
