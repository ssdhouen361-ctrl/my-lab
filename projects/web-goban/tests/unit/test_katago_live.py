"""Optional live Metal GPU smoke test for real KataGo Analysis Engine (@pytest.mark.katago_live)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.config import DEFAULT_KATAGO_BIN, DEFAULT_KATAGO_MODEL, Settings
from app.katago_engine import EngineState, KataGoEngine

PROJECT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_DIR / "config" / "katago_analysis.cfg"


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@pytest.mark.katago_live
async def test_real_katago_metal_smoke(tmp_path: Path) -> None:
    katago_bin = os.environ.get("KATAGO_BIN", DEFAULT_KATAGO_BIN)
    katago_model = os.environ.get("KATAGO_MODEL", DEFAULT_KATAGO_MODEL)

    if not Path(katago_bin).is_file():
        pytest.skip(f"Real KataGo binary not found at {katago_bin}")
    if not Path(katago_model).is_file():
        pytest.skip(f"Real KataGo model not found at {katago_model}")
    if not CONFIG_PATH.is_file():
        pytest.skip(f"KataGo config not found at {CONFIG_PATH}")

    settings = Settings(
        project_dir=PROJECT_DIR,
        data_dir=tmp_path / "live_data",
        katago_bin=katago_bin,
        katago_config=CONFIG_PATH,
        katago_model=katago_model,
        warmup_timeout_sec=60.0,
        query_timeout_sec=45.0,
        idle_timeout_sec=120.0,
    )
    settings.ensure_dirs()

    async def _ignore_external(_own_pid: int | None) -> list[dict[str, object]]:
        return []

    engine = KataGoEngine(settings, external_process_probe=_ignore_external)
    pid: int | None = None
    try:
        status = await engine.warmup(force=True)
        assert status["state"] == EngineState.IDLE.value
        pid = status["pid"]
        assert isinstance(pid, int) and pid > 0

        res = await engine.analyze_once(
            {
                "moves": [["B", "Q16"], ["W", "D4"], ["B", "Q4"], ["W", "D16"]],
                "initialStones": [],
                "initialPlayer": "B",
                "rules": "japanese",
                "komi": 6.5,
                "boardXSize": 19,
                "boardYSize": 19,
                "analyzeTurns": [4],
                "maxVisits": 20,
                "includeOwnership": True,
                "includePVVisits": True,
            },
            priority=20,
        )

        assert res["is_final"] is True
        root = res["root"]
        assert 0.0 < root["winrate_black"] < 1.0
        assert isinstance(root["score_lead_black"], float)
        assert root["visits"] >= 1
        assert len(res["moves"]) >= 1
        assert res["ownership"] is not None
        assert len(res["ownership"]) == 361
        assert all(-1.0 <= v <= 1.0 for v in res["ownership"])
    finally:
        await engine.stop()
        assert engine.state == EngineState.STOPPED
        if pid is not None:
            # Give OS a short moment to reap child exit
            for _ in range(20):
                if not _pid_is_alive(pid):
                    break
                await asyncio.sleep(0.05)
            assert not _pid_is_alive(pid), f"Real KataGo left zombie process pid={pid}"
