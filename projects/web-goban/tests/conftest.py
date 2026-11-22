"""Shared pytest fixtures enforcing triple isolation (tmp_path data, ephemeral port, FakeKataGo)."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

import pytest
import pytest_asyncio
import uvicorn

from app.config import Settings
from app.katago_engine import KataGoEngine
from app.main import create_app
from tests.fakes.fake_katago import DEFAULT_FIXTURE_PATH, make_fake_katago_command_builder

PROJECT_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def find_free_port() -> int:
    """Allocate an unused local TCP port (never touching production 8090)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


async def _no_external_katago(_own_pid: int | None) -> list[dict[str, Any]]:
    return []


def build_isolated_app(
    data_dir: Path,
    *,
    allowed_origins: list[str] | None = None,
    fake_katago_kwargs: dict[str, Any] | None = None,
    idle_timeout_sec: float = 120.0,
    interactive_debounce_sec: float = 0.03,
) -> Any:
    """Create a FastAPI app fully isolated to `data_dir` with FakeKataGoSubprocess."""
    origins = (
        list(allowed_origins)
        if allowed_origins is not None
        else ["http://127.0.0.1:8090", "http://localhost:8090", "http://testserver"]
    )
    settings = Settings(
        project_dir=PROJECT_DIR,
        data_dir=data_dir,
        allowed_origins=origins,
        idle_timeout_sec=idle_timeout_sec,
        interactive_debounce_sec=interactive_debounce_sec,
        warmup_timeout_sec=15.0,
        query_timeout_sec=15.0,
    )
    settings.ensure_dirs()
    engine = KataGoEngine(
        settings,
        command_builder=make_fake_katago_command_builder(**(fake_katago_kwargs or {})),
        external_process_probe=_no_external_katago,
    )
    return create_app(settings=settings, engine=engine)


class RunningTestServer:
    """Context manager running an isolated uvicorn server on an ephemeral 127.0.0.1 port."""

    def __init__(
        self,
        data_dir: Path,
        *,
        fixture_json: Path | None = DEFAULT_FIXTURE_PATH,
        extra_origins: list[str] | None = None,
        fake_katago_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.port = find_free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.ws_base_url = f"ws://127.0.0.1:{self.port}"
        origins = [self.base_url, f"http://localhost:{self.port}"]
        if extra_origins:
            origins.extend(extra_origins)

        fk_kwargs = dict(fake_katago_kwargs or {})
        if fixture_json is not None and "fixture_json" not in fk_kwargs:
            fk_kwargs["fixture_json"] = fixture_json

        self.app = build_isolated_app(
            self.data_dir,
            allowed_origins=origins,
            fake_katago_kwargs=fk_kwargs,
        )
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self, timeout_sec: float = 15.0) -> str:
        config = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            lifespan="on",
            ws="websockets",
        )
        self._server = uvicorn.Server(config)
        # Prevent uvicorn from installing signal handlers in non-main thread
        self._server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                assert self._server is not None
                loop.run_until_complete(self._server.serve())
            finally:
                loop.close()

        self._thread = threading.Thread(target=_run, daemon=True, name=f"web-goban-test-{self.port}")
        self._thread.start()

        deadline = time.monotonic() + timeout_sec
        health_url = f"{self.base_url}/api/v1/health"
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(health_url, timeout=1.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("status") == "ok":
                            return self.base_url
            except Exception as exc:
                last_err = exc
                time.sleep(0.05)
        self.stop()
        raise RuntimeError(f"Test server failed to start on {self.base_url}: {last_err}")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=8.0)
        self._thread = None
        self._server = None

    def __enter__(self) -> RunningTestServer:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_analysis() -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / "sample_analysis.json").read_text(encoding="utf-8"))


@pytest.fixture
def isolated_app(tmp_path: Path) -> Any:
    """Function-scoped isolated FastAPI app backed by tmp_path & FakeKataGo."""
    return build_isolated_app(
        tmp_path / "data",
        allowed_origins=["http://testserver", "http://127.0.0.1:8090", "http://localhost:8090"],
        fake_katago_kwargs={"fixture_json": DEFAULT_FIXTURE_PATH},
    )


@pytest.fixture(scope="module")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningTestServer]:
    """Module-scoped isolated FastAPI server on an ephemeral free port for Layer 2 E2E tests."""
    data_dir = tmp_path_factory.mktemp("web_goban_e2e_data")
    server = RunningTestServer(data_dir, fixture_json=DEFAULT_FIXTURE_PATH)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest_asyncio.fixture(scope="function")
async def playwright_browser() -> AsyncIterator[Any]:
    """Function-scoped headless Chromium instance for Layer 2 E2E tests."""
    playwright_mod = pytest.importorskip("playwright.async_api")
    async with playwright_mod.async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            await browser.close()
