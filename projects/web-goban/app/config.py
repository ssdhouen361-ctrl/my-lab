"""Configuration & environment settings for Web Goban.

Pure standard-library implementation (optional python-dotenv support) so all
core modules and Layer 1 tests can load Settings without extra dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import time
from typing import Iterable

DEFAULT_KATAGO_BIN = "/opt/homebrew/bin/katago"
DEFAULT_KATAGO_MODEL = (
    "/opt/homebrew/share/katago/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz"
)
DEFAULT_ALLOWED_ORIGINS = [
    "http://127.0.0.1:8090",
    "http://localhost:8090",
]


def _default_project_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_float(raw: str | None, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    return float(raw.strip())


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    return int(raw.strip())


def _normalize_origin(origin: str) -> str:
    return origin.strip().rstrip("/")


def _parse_origins(raw: str | None) -> list[str]:
    if raw is None or not raw.strip():
        return list(DEFAULT_ALLOWED_ORIGINS)
    parts = [_normalize_origin(item) for item in raw.split(",") if item.strip()]
    return parts


def load_dotenv_file(env_path: Path) -> dict[str, str]:
    """Load key-value pairs from a .env file without overriding existing os.environ."""
    if not env_path.is_file():
        return {}

    try:
        from dotenv import dotenv_values  # type: ignore[import-not-found]

        raw_map = dotenv_values(env_path)
        return {k: v for k, v in raw_map.items() if k and v is not None}
    except ImportError:
        pass

    parsed: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            parsed[key] = value
    return parsed


def compute_build_id(static_dir: Path) -> str:
    """Compute a deterministic short SHA-256 hash of static assets, or startup hash."""
    hasher = hashlib.sha256()
    found_files = False
    if static_dir.is_dir():
        for file_path in sorted(p for p in static_dir.rglob("*") if p.is_file()):
            found_files = True
            rel = file_path.relative_to(static_dir).as_posix()
            hasher.update(rel.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(file_path.read_bytes())
            hasher.update(b"\x00")
    if not found_files:
        hasher.update(f"startup-{time.time_ns()}".encode("utf-8"))
    return hasher.hexdigest()[:12]


@dataclass
class Settings:
    """Application settings with explicit DI boundaries for tests."""

    project_dir: Path = field(default_factory=_default_project_dir)
    data_dir: Path | None = None
    db_path: Path | None = None
    sgf_dir: Path | None = None
    reports_dir: Path | None = None
    logs_dir: Path | None = None
    katago_logs_dir: Path | None = None
    static_dir: Path | None = None

    katago_bin: str = DEFAULT_KATAGO_BIN
    katago_config: Path | None = None
    katago_model: str = DEFAULT_KATAGO_MODEL

    allowed_origins: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_ORIGINS))
    allow_missing_origin: bool = False

    idle_timeout_sec: float = 900.0
    katrain_idle_timeout_sec: float = 180.0
    warmup_timeout_sec: float = 60.0
    query_timeout_sec: float = 35.0
    interactive_debounce_sec: float = 0.12
    ws_zombie_timeout_sec: float = 45.0

    host: str = "127.0.0.1"
    port: int = 8090
    build_id: str = ""
    api_version: str = "1.0"
    min_client_version: str = "1.0"

    _normalized_origins: frozenset[str] = field(init=False, repr=False, default=frozenset())

    def __post_init__(self) -> None:
        self.project_dir = Path(self.project_dir)
        self.data_dir = Path(self.data_dir) if self.data_dir is not None else self.project_dir / "data"
        self.db_path = (
            Path(self.db_path) if self.db_path is not None else self.data_dir / "db" / "goban.db"
        )
        self.sgf_dir = Path(self.sgf_dir) if self.sgf_dir is not None else self.data_dir / "sgf"
        self.reports_dir = (
            Path(self.reports_dir) if self.reports_dir is not None else self.data_dir / "reports"
        )
        self.logs_dir = Path(self.logs_dir) if self.logs_dir is not None else self.data_dir / "logs"
        self.katago_logs_dir = (
            Path(self.katago_logs_dir)
            if self.katago_logs_dir is not None
            else self.logs_dir / "katago"
        )
        self.static_dir = (
            Path(self.static_dir) if self.static_dir is not None else self.project_dir / "static"
        )
        self.katago_config = (
            Path(self.katago_config)
            if self.katago_config is not None
            else self.project_dir / "config" / "katago_analysis.cfg"
        )

        # Normalize & validate allowed_origins (strictly forbid wildcard "*")
        normalized: list[str] = []
        for raw_origin in self.allowed_origins:
            cleaned = _normalize_origin(raw_origin)
            if not cleaned:
                continue
            if cleaned == "*" or "*" in cleaned:
                raise ValueError(
                    "Wildcard '*' is strictly forbidden in allowed_origins for CSWSH/CORS safety."
                )
            if cleaned not in normalized:
                normalized.append(cleaned)
        self.allowed_origins = normalized
        self._normalized_origins = frozenset(normalized)

        if not self.build_id:
            self.build_id = compute_build_id(self.static_dir)

    @classmethod
    def from_env(
        cls,
        project_dir: Path | None = None,
        env_file: Path | None = None,
        environ: dict[str, str] | None = None,
    ) -> Settings:
        """Create Settings from environment variables and optional .env file."""
        proj = Path(project_dir) if project_dir is not None else _default_project_dir()
        dotenv_path = env_file if env_file is not None else proj / ".env"
        file_env = load_dotenv_file(dotenv_path)
        active_env = dict(file_env)
        active_env.update(os.environ if environ is None else environ)

        def get_env(key: str) -> str | None:
            return active_env.get(key)

        data_dir_raw = get_env("WEB_GOBAN_DATA_DIR")
        katago_cfg_raw = get_env("KATAGO_CONFIG")

        return cls(
            project_dir=proj,
            data_dir=Path(data_dir_raw) if data_dir_raw else None,
            katago_bin=get_env("KATAGO_BIN") or DEFAULT_KATAGO_BIN,
            katago_config=Path(katago_cfg_raw) if katago_cfg_raw else None,
            katago_model=get_env("KATAGO_MODEL") or DEFAULT_KATAGO_MODEL,
            allowed_origins=_parse_origins(get_env("ALLOWED_ORIGINS")),
            allow_missing_origin=_parse_bool(get_env("ALLOW_MISSING_ORIGIN"), False),
            idle_timeout_sec=_parse_float(get_env("KATAGO_IDLE_TIMEOUT_SEC"), 900.0),
            katrain_idle_timeout_sec=_parse_float(
                get_env("KATAGO_KATRAIN_IDLE_TIMEOUT_SEC"), 180.0
            ),
            warmup_timeout_sec=_parse_float(get_env("KATAGO_WARMUP_TIMEOUT_SEC"), 60.0),
            query_timeout_sec=_parse_float(get_env("KATAGO_QUERY_TIMEOUT_SEC"), 35.0),
            interactive_debounce_sec=_parse_float(
                get_env("KATAGO_INTERACTIVE_DEBOUNCE_SEC"), 0.12
            ),
            ws_zombie_timeout_sec=_parse_float(get_env("WS_ZOMBIE_TIMEOUT_SEC"), 45.0),
            host=get_env("WEB_GOBAN_HOST") or "127.0.0.1",
            port=_parse_int(get_env("WEB_GOBAN_PORT"), 8090),
        )

    def ensure_dirs(self) -> None:
        """Create all required runtime data directories idempotently."""
        dirs: Iterable[Path] = (
            self.data_dir,  # type: ignore[arg-type]
            self.db_path.parent,  # type: ignore[union-attr]
            self.sgf_dir,  # type: ignore[arg-type]
            self.reports_dir,  # type: ignore[arg-type]
            self.logs_dir,  # type: ignore[arg-type]
            self.katago_logs_dir,  # type: ignore[arg-type]
        )
        for directory in dirs:
            directory.mkdir(parents=True, exist_ok=True)

    def is_origin_allowed(self, origin: str | None) -> bool:
        """Strictly verify an HTTP/WebSocket Origin header against allowed_origins."""
        if origin is None:
            return self.allow_missing_origin
        cleaned = _normalize_origin(origin)
        if not cleaned or cleaned == "*" or "*" in cleaned:
            return False
        return cleaned in self._normalized_origins


def load_settings(project_dir: Path | None = None, env_file: Path | None = None) -> Settings:
    """Convenience loader for application settings."""
    return Settings.from_env(project_dir=project_dir, env_file=env_file)
