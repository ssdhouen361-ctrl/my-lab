"""Async SQLite persistence layer (WAL mode, serialized writes).

Uses aiosqlite when installed, with a transparent asyncio.to_thread + stdlib
sqlite3 fallback so pure-stdlib tests can run without extra dependencies.
Addresses Pitfall #11 (visits-monotonic UPSERT) and Pitfall #12 (lock contention).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

try:
    import aiosqlite  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - fallback for pure-stdlib environment
    aiosqlite = None  # type: ignore[assignment]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    sgf_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    board_size INTEGER NOT NULL,
    komi REAL NOT NULL,
    handicap INTEGER NOT NULL DEFAULT 0,
    rules TEXT NOT NULL DEFAULT 'japanese',
    mode TEXT NOT NULL DEFAULT 'review',
    ai_level TEXT NOT NULL DEFAULT '5k',
    player_color TEXT NOT NULL DEFAULT 'B',
    latest_node_id TEXT NOT NULL DEFAULT 'n-0000',
    state_version INTEGER NOT NULL DEFAULT 1,
    sgf_text TEXT NOT NULL DEFAULT '',
    sgf_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_games_updated_at ON games(updated_at DESC);

CREATE TABLE IF NOT EXISTS sgf_records (
    sgf_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    played_at TEXT NOT NULL DEFAULT '',
    board_size INTEGER NOT NULL,
    move_count INTEGER NOT NULL DEFAULT 0,
    player_color TEXT NOT NULL DEFAULT 'B',
    result TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    rel_path TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sgf_records_updated_at ON sgf_records(updated_at DESC);

CREATE TABLE IF NOT EXISTS analysis_cache (
    position_hash TEXT PRIMARY KEY,
    board_size INTEGER NOT NULL,
    actual_visits INTEGER NOT NULL,
    root_info_json TEXT NOT NULL,
    move_infos_json TEXT NOT NULL,
    ownership_json TEXT,
    model_fingerprint TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coach_cache (
    cache_key TEXT PRIMARY KEY,
    position_hash TEXT NOT NULL,
    target_move TEXT NOT NULL,
    coach_mode TEXT NOT NULL,
    skill_level TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drill_questions (
    drill_id TEXT PRIMARY KEY,
    sgf_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    position_hash TEXT NOT NULL,
    box INTEGER NOT NULL DEFAULT 0,
    next_review_at TEXT,
    excluded INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""


class Database:
    """Async SQLite manager with WAL mode and serialized write lock."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._write_lock = asyncio.Lock()
        self._aio_conn: Any = None
        self._sync_conn: sqlite3.Connection | None = None
        self._use_aiosqlite: bool = aiosqlite is not None

    @property
    def is_connected(self) -> bool:
        return self._aio_conn is not None or self._sync_conn is not None

    async def connect(self) -> None:
        if self.is_connected:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self._use_aiosqlite:
            conn = await aiosqlite.connect(str(self.db_path), timeout=5.0)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA synchronous=NORMAL;")
            await conn.execute("PRAGMA busy_timeout=5000;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            self._aio_conn = conn
        else:
            def _open_sync() -> sqlite3.Connection:
                conn = sqlite3.connect(
                    str(self.db_path),
                    timeout=5.0,
                    check_same_thread=False,
                )
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute("PRAGMA busy_timeout=5000;")
                conn.execute("PRAGMA foreign_keys=ON;")
                conn.executescript(_SCHEMA_SQL)
                conn.commit()
                return conn

            self._sync_conn = await asyncio.to_thread(_open_sync)

    async def close(self) -> None:
        async with self._write_lock:
            if self._aio_conn is not None:
                await self._aio_conn.close()
                self._aio_conn = None
            if self._sync_conn is not None:
                conn = self._sync_conn
                self._sync_conn = None
                await asyncio.to_thread(conn.close)

    async def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        if not self.is_connected:
            await self.connect()
        if self._aio_conn is not None:
            async with self._aio_conn.execute(sql, params) as cur:
                row = await cur.fetchone()
                return dict(row) if row is not None else None
        async with self._write_lock:
            def _run() -> dict[str, Any] | None:
                assert self._sync_conn is not None
                cur = self._sync_conn.execute(sql, params)
                row = cur.fetchone()
                return dict(row) if row is not None else None

            return await asyncio.to_thread(_run)

    async def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if not self.is_connected:
            await self.connect()
        if self._aio_conn is not None:
            async with self._aio_conn.execute(sql, params) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]
        async with self._write_lock:
            def _run() -> list[dict[str, Any]]:
                assert self._sync_conn is not None
                cur = self._sync_conn.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]

            return await asyncio.to_thread(_run)

    async def _execute_write(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        if not self.is_connected:
            await self.connect()
        async with self._write_lock:
            if self._aio_conn is not None:
                cur = await self._aio_conn.execute(sql, params)
                await self._aio_conn.commit()
                return cur.rowcount

            def _run() -> int:
                assert self._sync_conn is not None
                cur = self._sync_conn.execute(sql, params)
                self._sync_conn.commit()
                return cur.rowcount

            return await asyncio.to_thread(_run)

    # ------------------------------------------------------------------
    # Games CRUD
    # ------------------------------------------------------------------

    async def save_game(self, game: dict[str, Any]) -> None:
        now = _utc_now_iso()
        created_at = game.get("created_at") or now
        updated_at = game.get("updated_at") or now
        await self._execute_write(
            """
            INSERT INTO games (
                game_id, sgf_id, title, board_size, komi, handicap, rules,
                mode, ai_level, player_color, latest_node_id, state_version,
                sgf_text, sgf_path, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET
                sgf_id = excluded.sgf_id,
                title = excluded.title,
                board_size = excluded.board_size,
                komi = excluded.komi,
                handicap = excluded.handicap,
                rules = excluded.rules,
                mode = excluded.mode,
                ai_level = excluded.ai_level,
                player_color = excluded.player_color,
                latest_node_id = excluded.latest_node_id,
                state_version = excluded.state_version,
                sgf_text = excluded.sgf_text,
                sgf_path = excluded.sgf_path,
                updated_at = excluded.updated_at
            """,
            (
                game["game_id"],
                game.get("sgf_id"),
                game.get("title", ""),
                int(game["board_size"]),
                float(game["komi"]),
                int(game.get("handicap", 0)),
                game.get("rules", "japanese"),
                game.get("mode", "review"),
                game.get("ai_level", "5k"),
                game.get("player_color", "B"),
                game.get("latest_node_id", "n-0000"),
                int(game.get("state_version", 1)),
                game.get("sgf_text", ""),
                str(game.get("sgf_path", "")),
                created_at,
                updated_at,
            ),
        )

    async def get_game(self, game_id: str) -> dict[str, Any] | None:
        return await self._fetchone("SELECT * FROM games WHERE game_id = ?", (game_id,))

    async def list_recent_games(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        return await self._fetchall(
            """
            SELECT game_id, sgf_id, title, board_size, komi, handicap, rules,
                   mode, ai_level, player_color, latest_node_id, state_version,
                   created_at, updated_at
            FROM games
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        )

    async def delete_game(self, game_id: str) -> bool:
        count = await self._execute_write("DELETE FROM games WHERE game_id = ?", (game_id,))
        return count > 0

    # ------------------------------------------------------------------
    # SGF Records CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _hydrate_sgf_row(row: dict[str, Any]) -> dict[str, Any]:
        hydrated = dict(row)
        try:
            hydrated["tags"] = json.loads(row.get("tags_json") or "[]")
        except json.JSONDecodeError:
            hydrated["tags"] = []
        try:
            hydrated["summary"] = json.loads(row.get("summary_json") or "{}")
        except json.JSONDecodeError:
            hydrated["summary"] = {}
        return hydrated

    async def save_sgf_record(self, record: dict[str, Any]) -> None:
        now = _utc_now_iso()
        tags_json = (
            record["tags_json"]
            if "tags_json" in record and isinstance(record["tags_json"], str)
            else json.dumps(record.get("tags", []), ensure_ascii=False)
        )
        summary_json = (
            record["summary_json"]
            if "summary_json" in record and isinstance(record["summary_json"], str)
            else json.dumps(record.get("summary", {}), ensure_ascii=False)
        )
        await self._execute_write(
            """
            INSERT INTO sgf_records (
                sgf_id, title, played_at, board_size, move_count, player_color,
                result, tags_json, rel_path, summary_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sgf_id) DO UPDATE SET
                title = excluded.title,
                played_at = excluded.played_at,
                board_size = excluded.board_size,
                move_count = excluded.move_count,
                player_color = excluded.player_color,
                result = excluded.result,
                tags_json = excluded.tags_json,
                rel_path = excluded.rel_path,
                summary_json = excluded.summary_json,
                updated_at = excluded.updated_at
            """,
            (
                record["sgf_id"],
                record.get("title", ""),
                record.get("played_at", ""),
                int(record["board_size"]),
                int(record.get("move_count", 0)),
                record.get("player_color", "B"),
                record.get("result", ""),
                tags_json,
                record["rel_path"],
                summary_json,
                record.get("created_at") or now,
                record.get("updated_at") or now,
            ),
        )

    async def get_sgf_record(self, sgf_id: str) -> dict[str, Any] | None:
        row = await self._fetchone("SELECT * FROM sgf_records WHERE sgf_id = ?", (sgf_id,))
        return self._hydrate_sgf_row(row) if row is not None else None

    async def list_sgf_records(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        safe_offset = max(0, int(offset))
        rows = await self._fetchall(
            """
            SELECT * FROM sgf_records
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (safe_limit, safe_offset),
        )
        return [self._hydrate_sgf_row(r) for r in rows]

    async def update_sgf_record(
        self, sgf_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        existing = await self.get_sgf_record(sgf_id)
        if existing is None:
            return None
        merged = dict(existing)
        for key in ("title", "played_at", "player_color", "result", "move_count"):
            if key in updates and updates[key] is not None:
                merged[key] = updates[key]
        if "tags" in updates and updates["tags"] is not None:
            merged["tags"] = updates["tags"]
            merged.pop("tags_json", None)
        if "summary" in updates and updates["summary"] is not None:
            merged["summary"] = updates["summary"]
            merged.pop("summary_json", None)
        merged["updated_at"] = _utc_now_iso()
        await self.save_sgf_record(merged)
        return await self.get_sgf_record(sgf_id)

    async def delete_sgf_record(self, sgf_id: str) -> bool:
        count = await self._execute_write("DELETE FROM sgf_records WHERE sgf_id = ?", (sgf_id,))
        return count > 0

    # ------------------------------------------------------------------
    # Analysis Cache (Pitfall #11: NEVER downgrade actual_visits)
    # ------------------------------------------------------------------

    @staticmethod
    def _hydrate_analysis_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "position_hash": row["position_hash"],
            "board_size": int(row["board_size"]),
            "actual_visits": int(row["actual_visits"]),
            "root": json.loads(row["root_info_json"]),
            "moves": json.loads(row["move_infos_json"]),
            "ownership": json.loads(row["ownership_json"]) if row.get("ownership_json") else None,
            "model_fingerprint": row.get("model_fingerprint", ""),
            "updated_at": row["updated_at"],
            "is_final": True,
            "from_cache": True,
        }

    async def get_analysis_cache(self, position_hash: str) -> dict[str, Any] | None:
        row = await self._fetchone(
            "SELECT * FROM analysis_cache WHERE position_hash = ?",
            (position_hash,),
        )
        return self._hydrate_analysis_row(row) if row is not None else None

    async def get_analysis_cache_many(
        self, position_hashes: list[str]
    ) -> dict[str, dict[str, Any]]:
        unique = [h for h in dict.fromkeys(position_hashes) if h]
        if not unique:
            return {}
        placeholders = ",".join("?" for _ in unique)
        rows = await self._fetchall(
            f"SELECT * FROM analysis_cache WHERE position_hash IN ({placeholders})",
            tuple(unique),
        )
        return {r["position_hash"]: self._hydrate_analysis_row(r) for r in rows}

    async def upsert_analysis_cache(
        self,
        *,
        position_hash: str,
        board_size: int,
        actual_visits: int,
        root_info: dict[str, Any],
        move_infos: list[dict[str, Any]],
        ownership: list[float] | None,
        model_fingerprint: str = "",
    ) -> bool:
        """Insert or update analysis cache ONLY if actual_visits strictly increases.

        Returns True if the cache entry was inserted or upgraded, False if skipped.
        """
        if not self.is_connected:
            await self.connect()

        visits = int(actual_visits)
        if visits <= 0:
            return False

        now = _utc_now_iso()
        root_json = json.dumps(root_info, separators=(",", ":"))
        moves_json = json.dumps(move_infos, separators=(",", ":"))
        ownership_json = (
            json.dumps(ownership, separators=(",", ":")) if ownership is not None else None
        )

        async with self._write_lock:
            if self._aio_conn is not None:
                async with self._aio_conn.execute(
                    "SELECT actual_visits FROM analysis_cache WHERE position_hash = ?",
                    (position_hash,),
                ) as cur:
                    row = await cur.fetchone()
                    if row is not None and int(row["actual_visits"]) >= visits:
                        return False
                await self._aio_conn.execute(
                    """
                    INSERT INTO analysis_cache (
                        position_hash, board_size, actual_visits, root_info_json,
                        move_infos_json, ownership_json, model_fingerprint, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(position_hash) DO UPDATE SET
                        board_size = excluded.board_size,
                        actual_visits = excluded.actual_visits,
                        root_info_json = excluded.root_info_json,
                        move_infos_json = excluded.move_infos_json,
                        ownership_json = excluded.ownership_json,
                        model_fingerprint = excluded.model_fingerprint,
                        updated_at = excluded.updated_at
                    WHERE excluded.actual_visits > analysis_cache.actual_visits
                    """,
                    (
                        position_hash,
                        int(board_size),
                        visits,
                        root_json,
                        moves_json,
                        ownership_json,
                        model_fingerprint or "",
                        now,
                    ),
                )
                await self._aio_conn.commit()
                return True

            def _run() -> bool:
                assert self._sync_conn is not None
                cur = self._sync_conn.execute(
                    "SELECT actual_visits FROM analysis_cache WHERE position_hash = ?",
                    (position_hash,),
                )
                row = cur.fetchone()
                if row is not None and int(row["actual_visits"]) >= visits:
                    return False
                self._sync_conn.execute(
                    """
                    INSERT INTO analysis_cache (
                        position_hash, board_size, actual_visits, root_info_json,
                        move_infos_json, ownership_json, model_fingerprint, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(position_hash) DO UPDATE SET
                        board_size = excluded.board_size,
                        actual_visits = excluded.actual_visits,
                        root_info_json = excluded.root_info_json,
                        move_infos_json = excluded.move_infos_json,
                        ownership_json = excluded.ownership_json,
                        model_fingerprint = excluded.model_fingerprint,
                        updated_at = excluded.updated_at
                    WHERE excluded.actual_visits > analysis_cache.actual_visits
                    """,
                    (
                        position_hash,
                        int(board_size),
                        visits,
                        root_json,
                        moves_json,
                        ownership_json,
                        model_fingerprint or "",
                        now,
                    ),
                )
                self._sync_conn.commit()
                return True

            return await asyncio.to_thread(_run)

    # ------------------------------------------------------------------
    # Coach Cache (Phase 2 readiness)
    # ------------------------------------------------------------------

    async def get_coach_cache(self, cache_key: str) -> dict[str, Any] | None:
        row = await self._fetchone(
            "SELECT * FROM coach_cache WHERE cache_key = ?", (cache_key,)
        )
        if row is None:
            return None
        return {
            **row,
            "response": json.loads(row["response_json"]),
        }

    async def put_coach_cache(
        self,
        *,
        cache_key: str,
        position_hash: str,
        target_move: str,
        coach_mode: str,
        skill_level: str,
        prompt_version: str,
        response: dict[str, Any],
    ) -> None:
        await self._execute_write(
            """
            INSERT OR REPLACE INTO coach_cache (
                cache_key, position_hash, target_move, coach_mode,
                skill_level, prompt_version, response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                position_hash,
                target_move,
                coach_mode,
                skill_level,
                prompt_version,
                json.dumps(response, ensure_ascii=False),
                _utc_now_iso(),
            ),
        )


__all__ = ["Database"]
