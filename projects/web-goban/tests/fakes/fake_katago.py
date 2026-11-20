"""Factory helpers to launch FakeKataGoSubprocess as a real OS-pipe NDJSON worker."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

FAKE_WORKER_PATH = Path(__file__).resolve().parent / "fake_katago_worker.py"
DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "sample_analysis.json"


def make_fake_katago_launcher(
    *,
    large_bytes: int = 0,
    stderr_flood_bytes: int = 0,
    delay_sec: float = 0.0,
    terminate_mode: str = "noresults",
    crash_on_query: int = 0,
    crash_once_file: str | Path | None = None,
    error_on_query: int = 0,
    fixture_json: str | Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Return ``(cmd, env)`` to spawn ``fake_katago_worker.py`` via ``KataGoEngine``.

    All scenario parameters are embedded both as explicit CLI flags on ``cmd`` (so
    ``KataGoEngine(command_builder=...)`` works with zero global ``os.environ`` mutation)
    and reflected in the returned ``env`` dict for direct subprocess launchers.
    """
    cmd: list[str] = [
        sys.executable,
        "-u",
        str(FAKE_WORKER_PATH),
        "--large-bytes",
        str(large_bytes),
        "--stderr-flood-bytes",
        str(stderr_flood_bytes),
        "--delay-sec",
        str(delay_sec),
        "--terminate-mode",
        terminate_mode,
        "--crash-on-query",
        str(crash_on_query),
        "--error-on-query",
        str(error_on_query),
    ]
    if crash_once_file is not None:
        cmd.extend(["--crash-once-file", str(crash_once_file)])
    if fixture_json is not None:
        cmd.extend(["--fixture-json", str(fixture_json)])

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["FAKE_KATAGO_LARGE_BYTES"] = str(large_bytes)
    env["FAKE_KATAGO_STDERR_FLOOD_BYTES"] = str(stderr_flood_bytes)
    env["FAKE_KATAGO_DELAY_SEC"] = str(delay_sec)
    env["FAKE_KATAGO_TERMINATE_MODE"] = terminate_mode
    env["FAKE_KATAGO_CRASH_ON_QUERY"] = str(crash_on_query)
    env["FAKE_KATAGO_ERROR_ON_QUERY"] = str(error_on_query)
    if crash_once_file is not None:
        env["FAKE_KATAGO_CRASH_ONCE_FILE"] = str(crash_once_file)
    else:
        env.pop("FAKE_KATAGO_CRASH_ONCE_FILE", None)
    if fixture_json is not None:
        env["FAKE_KATAGO_FIXTURE_JSON"] = str(fixture_json)
    else:
        env.pop("FAKE_KATAGO_FIXTURE_JSON", None)
    if extra_env:
        env.update(extra_env)
    return cmd, env


def make_fake_katago_command_builder(**kwargs: Any) -> Callable[[Any], list[str]]:
    """Return a ``command_builder(settings) -> list[str]`` injectable into ``KataGoEngine``."""
    cmd, _env = make_fake_katago_launcher(**kwargs)

    def _builder(_settings: Any) -> list[str]:
        return list(cmd)

    return _builder
