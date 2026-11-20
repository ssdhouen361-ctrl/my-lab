"""Multi-client WebSocket GameHub, session management, optimistic locking & analysis orchestration.

Pure standard library + asyncio (zero FastAPI imports) so Layer 1 tests can
exercise GameHub directly or via FastAPI TestClient.
Addresses Pitfalls #3, #7, #11, #12, #15, #16, #18.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
import time
from typing import Any
import uuid

from app.config import Settings
from app.db import Database
from app.katago_engine import (
    AI_PRESETS,
    FULL_REVIEW_DEFAULT_VISITS,
    AnalysisEngineProtocol,
    KataGoError,
    classify_move_quality,
    compute_score_loss,
    select_ai_move,
)
from app.rules import (
    GameTree,
    IllegalMoveError,
    atomic_write_text,
    opposite_color,
    parse_sgf,
    safe_resolve_under,
)

logger = logging.getLogger("web_goban.hub")


class VersionConflictError(Exception):
    """Raised when optimistic lock expected_version does not match state_version."""

    def __init__(self, expected: int, current: int) -> None:
        self.expected = expected
        self.current = current
        super().__init__(f"VERSION_CONFLICT: expected={expected}, current={current}")


def epoch_ms() -> int:
    return int(time.time() * 1000)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_envelope(
    event_type: str,
    payload: dict[str, Any],
    *,
    seq: int,
    state_version: int,
) -> dict[str, Any]:
    """Build standard WebSocket event envelope."""
    return {
        "type": event_type,
        "seq": seq,
        "state_version": state_version,
        "ts": epoch_ms(),
        "payload": payload,
    }


@dataclass
class ClientSession:
    """Per-client local viewport & heartbeat state (never leaks across terminals)."""

    client_id: str
    ws: Any
    current_node_id: str
    following_latest: bool = True
    last_seen_ts: float = field(default_factory=time.monotonic)
    seq: int = 0

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def touch(self) -> None:
        self.last_seen_ts = time.monotonic()


@dataclass
class GameSession:
    """Active in-memory game/review session backed by SQLite + atomic .sgf file."""

    game_id: str
    tree: GameTree
    state_version: int = 1
    mode: str = "review"
    ai_level: str = "5k"
    player_color: str = "B"
    auto_analyze: bool = True
    sgf_id: str | None = None
    sgf_path: Path | None = None
    title: str = ""
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    analysis_by_node: dict[str, dict[str, Any]] = field(default_factory=dict)
    clients: dict[str, ClientSession] = field(default_factory=dict)
    active_analysis_task: asyncio.Task[None] | None = None


class GameHub:
    """Coordinates game sessions, multi-client WS broadcast, persistence, and KataGo."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        engine: AnalysisEngineProtocol,
    ) -> None:
        self.settings = settings
        self.db = db
        self.engine = engine
        self.sessions: dict[str, GameSession] = {}
        self._reaper_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle & Zombie WS Reaper (Pitfall #18)
    # ------------------------------------------------------------------

    def start_reaper(self) -> None:
        if self._reaper_task is not None and not self._reaper_task.done():
            return
        self._reaper_task = asyncio.create_task(self._zombie_reaper_loop())

    async def stop_reaper(self) -> None:
        if self._reaper_task is not None and not self._reaper_task.done():
            self._reaper_task.cancel()
            await asyncio.gather(self._reaper_task, return_exceptions=True)
        self._reaper_task = None

        # Cancel any in-flight per-session analysis tasks
        tasks = [
            s.active_analysis_task
            for s in self.sessions.values()
            if s.active_analysis_task is not None and not s.active_analysis_task.done()
        ]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def reap_zombies_once(self) -> int:
        """Scan all sessions and close/drop WS clients idle past ws_zombie_timeout_sec."""
        now = time.monotonic()
        timeout = self.settings.ws_zombie_timeout_sec
        reaped = 0
        for session in list(self.sessions.values()):
            stale_clients = [
                c
                for c in list(session.clients.values())
                if (now - c.last_seen_ts) > timeout
            ]
            for client in stale_clients:
                session.clients.pop(client.client_id, None)
                reaped += 1
                try:
                    await client.ws.close(code=1001, reason="Idle heartbeat timeout")
                except Exception:
                    pass
        return reaped

    async def _zombie_reaper_loop(self) -> None:
        interval = min(5.0, max(0.05, self.settings.ws_zombie_timeout_sec / 4.0))
        try:
            while True:
                await asyncio.sleep(interval)
                await self.reap_zombies_once()
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # Session Creation, Loading & Atomic Persistence
    # ------------------------------------------------------------------

    def _allocate_sgf_path(self, file_uuid: str) -> Path:
        now = datetime.now(timezone.utc)
        rel = f"{now:%Y}/{now:%m}/{file_uuid}.sgf"
        assert self.settings.sgf_dir is not None
        return safe_resolve_under(self.settings.sgf_dir, rel)

    async def create_game(
        self,
        *,
        board_size: int = 19,
        komi: float | None = None,
        handicap: int = 0,
        rules: str = "japanese",
        mode: str = "review",
        ai_level: str = "5k",
        player_color: str = "B",
        title: str = "",
        sgf_text: str | bytes | None = None,
        sgf_id: str | None = None,
        auto_analyze: bool | None = None,
    ) -> GameSession:
        if mode not in ("review", "play"):
            mode = "review"
        if player_color not in ("B", "W"):
            player_color = "B"
        if ai_level not in AI_PRESETS:
            ai_level = "5k"

        if sgf_text is not None:
            tree = parse_sgf(sgf_text, mode=mode)
        else:
            tree = GameTree(
                board_size=board_size,
                komi=komi,
                handicap=handicap,
                rules=rules,
                mode=mode,
            )

        game_id = f"g-{uuid.uuid4().hex[:12]}"
        resolved_title = title or tree.metadata.get("GN", "") or f"{tree.board_size}路対局"
        resolved_auto = (mode == "review") if auto_analyze is None else bool(auto_analyze)
        sgf_path = self._allocate_sgf_path(game_id)

        now = _utc_now_iso()
        session = GameSession(
            game_id=game_id,
            tree=tree,
            state_version=1,
            mode=mode,
            ai_level=ai_level,
            player_color=player_color,
            auto_analyze=resolved_auto,
            sgf_id=sgf_id,
            sgf_path=sgf_path,
            title=resolved_title,
            created_at=now,
            updated_at=now,
        )
        self.sessions[game_id] = session
        await self._hydrate_mainline_cache(session)
        await self.persist_session(session)
        return session

    async def get_or_load_session(self, game_id: str) -> GameSession | None:
        if game_id in self.sessions:
            return self.sessions[game_id]

        row = await self.db.get_game(game_id)
        if row is None:
            return None

        sgf_text = row.get("sgf_text") or ""
        sgf_path_str = row.get("sgf_path") or ""
        sgf_path = Path(sgf_path_str) if sgf_path_str else self._allocate_sgf_path(game_id)

        if not sgf_text and sgf_path.is_file():
            sgf_text = sgf_path.read_text(encoding="utf-8", errors="replace")

        mode = row.get("mode") or "review"
        if sgf_text:
            tree = parse_sgf(sgf_text, mode=mode)
        else:
            tree = GameTree(
                board_size=int(row["board_size"]),
                komi=float(row["komi"]),
                handicap=int(row.get("handicap", 0)),
                rules=row.get("rules", "japanese"),
                mode=mode,
            )

        saved_latest = row.get("latest_node_id")
        if saved_latest and saved_latest in tree.nodes:
            tree.latest_node_id = saved_latest

        session = GameSession(
            game_id=game_id,
            tree=tree,
            state_version=int(row.get("state_version", 1)),
            mode=mode,
            ai_level=row.get("ai_level", "5k"),
            player_color=row.get("player_color", "B"),
            auto_analyze=(mode == "review"),
            sgf_id=row.get("sgf_id"),
            sgf_path=sgf_path,
            title=row.get("title", ""),
            created_at=row.get("created_at") or _utc_now_iso(),
            updated_at=row.get("updated_at") or _utc_now_iso(),
        )
        self.sessions[game_id] = session
        await self._hydrate_mainline_cache(session)
        return session

    async def persist_session(self, session: GameSession) -> None:
        session.updated_at = _utc_now_iso()
        sgf_text = session.tree.to_sgf()
        if session.sgf_path is not None:
            await asyncio.to_thread(atomic_write_text, session.sgf_path, sgf_text)

        await self.db.save_game(
            {
                "game_id": session.game_id,
                "sgf_id": session.sgf_id,
                "title": session.title,
                "board_size": session.tree.board_size,
                "komi": session.tree.komi,
                "handicap": session.tree.handicap,
                "rules": session.tree.rules,
                "mode": session.mode,
                "ai_level": session.ai_level,
                "player_color": session.player_color,
                "latest_node_id": session.tree.latest_node_id,
                "state_version": session.state_version,
                "sgf_text": sgf_text,
                "sgf_path": str(session.sgf_path or ""),
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            }
        )

    async def _hydrate_mainline_cache(self, session: GameSession) -> None:
        hash_to_nodes: dict[str, list[str]] = {}
        for nid in session.tree.mainline_ids:
            if nid in session.analysis_by_node:
                continue
            ph = session.tree.position_hash(nid, self.engine.model_fingerprint)
            hash_to_nodes.setdefault(ph, []).append(nid)
        if not hash_to_nodes:
            return
        cached_map = await self.db.get_analysis_cache_many(list(hash_to_nodes.keys()))
        for ph, cached in cached_map.items():
            for nid in hash_to_nodes.get(ph, []):
                entry = dict(cached)
                entry["node_id"] = nid
                session.analysis_by_node[nid] = entry

    async def _hydrate_node_cache(self, session: GameSession, node_id: str) -> dict[str, Any] | None:
        if node_id in session.analysis_by_node:
            return session.analysis_by_node[node_id]
        ph = session.tree.position_hash(node_id, self.engine.model_fingerprint)
        cached = await self.db.get_analysis_cache(ph)
        if cached is not None:
            entry = dict(cached)
            entry["node_id"] = node_id
            session.analysis_by_node[node_id] = entry
            return entry
        return None

    # ------------------------------------------------------------------
    # State Payloads & Graph Points
    # ------------------------------------------------------------------

    def build_graph_points(self, session: GameSession) -> list[dict[str, Any]]:
        """Build winrate/score graph points along mainline using cached analysis (Pitfall #3)."""
        points: list[dict[str, Any]] = []
        prev_an: dict[str, Any] | None = None
        for nid in session.tree.mainline_ids:
            node = session.tree.nodes.get(nid)
            an = session.analysis_by_node.get(nid)
            if node is None or an is None:
                prev_an = an
                continue

            root = an.get("root") or {}
            wr = float(root.get("winrate_black", 0.5))
            lead = float(root.get("score_lead_black", 0.0))

            score_loss = 0.0
            badge: str | None = None
            if prev_an is not None and node.color in ("B", "W"):
                prev_root = prev_an.get("root") or {}
                prev_moves = prev_an.get("moves") or []
                prev_wr = float(prev_root.get("winrate_black", 0.5))
                prev_best_lead = (
                    float(prev_moves[0].get("score_lead_black", prev_root.get("score_lead_black", 0.0)))
                    if prev_moves
                    else float(prev_root.get("score_lead_black", 0.0))
                )
                score_loss = compute_score_loss(prev_best_lead, lead, node.color)
                wr_loss = (
                    max(0.0, prev_wr - wr)
                    if node.color == "B"
                    else max(0.0, wr - prev_wr)
                )
                badge = classify_move_quality(
                    score_loss, wr_loss, session.tree.board_size
                )

            points.append(
                {
                    "move_number": node.move_number,
                    "node_id": nid,
                    "color": node.color,
                    "move": node.move,
                    "winrate_black": round(wr, 4),
                    "score_lead_black": round(lead, 2),
                    "score_loss": round(score_loss, 2),
                    "badge": badge,
                }
            )
            prev_an = an
        return points

    def build_state_sync_payload(
        self,
        session: GameSession,
        client_node_id: str | None = None,
    ) -> dict[str, Any]:
        node_id = (
            client_node_id
            if (client_node_id and client_node_id in session.tree.nodes)
            else session.tree.latest_node_id
        )
        node = session.tree.get_node(node_id)
        board_dict = node.board.to_position_dict(
            session.tree.rules,
            session.tree.komi,
            self.engine.model_fingerprint,
        )
        return {
            "game_id": session.game_id,
            "sgf_id": session.sgf_id,
            "title": session.title,
            "mode": session.mode,
            "ai_level": session.ai_level,
            "player_color": session.player_color,
            "auto_analyze": session.auto_analyze,
            "board_size": session.tree.board_size,
            "komi": session.tree.komi,
            "handicap": session.tree.handicap,
            "rules": session.tree.rules,
            "metadata": dict(session.tree.metadata),
            "warnings": list(session.tree.warnings),
            "root_id": session.tree.root_id,
            "latest_node_id": session.tree.latest_node_id,
            "current_node_id": node_id,
            "following_latest": node_id == session.tree.latest_node_id,
            "move_number": node.move_number,
            "mainline_ids": list(session.tree.mainline_ids),
            "total_mainline_moves": max(0, len(session.tree.mainline_ids) - 1),
            "branch_info": session.tree.get_branch_info(node_id),
            "board": board_dict,
            "last_captured": list(node.captured),
            "comment": node.comment,
            "analysis": session.analysis_by_node.get(node_id),
            "graph_points": self.build_graph_points(session),
            "nodes": [n.to_summary_dict() for n in session.tree.nodes.values()],
            "engine_status": self.engine.get_status(),
        }

    # ------------------------------------------------------------------
    # WebSocket Client Registration & Messaging
    # ------------------------------------------------------------------

    def register_client(
        self, session: GameSession, client_id: str, ws: Any
    ) -> ClientSession:
        client = ClientSession(
            client_id=client_id,
            ws=ws,
            current_node_id=session.tree.latest_node_id,
            following_latest=True,
        )
        session.clients[client_id] = client
        return client

    def unregister_client(self, session: GameSession, client_id: str) -> None:
        session.clients.pop(client_id, None)

    async def send_to_client(
        self,
        session: GameSession,
        client: ClientSession,
        event_type: str,
        payload: dict[str, Any],
    ) -> bool:
        envelope = make_envelope(
            event_type,
            payload,
            seq=client.next_seq(),
            state_version=session.state_version,
        )
        try:
            await client.ws.send_json(envelope)
            return True
        except Exception:
            session.clients.pop(client.client_id, None)
            return False

    async def broadcast(
        self,
        session: GameSession,
        event_type: str,
        payload: dict[str, Any],
        *,
        exclude_client_id: str | None = None,
    ) -> None:
        for client in list(session.clients.values()):
            if exclude_client_id is not None and client.client_id == exclude_client_id:
                continue
            await self.send_to_client(session, client, event_type, payload)

    async def broadcast_state_sync(self, session: GameSession) -> None:
        for client in list(session.clients.values()):
            if client.current_node_id not in session.tree.nodes:
                client.current_node_id = session.tree.latest_node_id
                client.following_latest = True
            payload = self.build_state_sync_payload(session, client.current_node_id)
            await self.send_to_client(session, client, "state_sync", payload)

    async def broadcast_engine_status(self, status: dict[str, Any]) -> None:
        for session in list(self.sessions.values()):
            await self.broadcast(session, "engine_status", status)

    # ------------------------------------------------------------------
    # REST SGF Import Helper
    # ------------------------------------------------------------------

    async def import_sgf_into_session(
        self,
        session: GameSession,
        raw_sgf: bytes | str,
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        new_tree = parse_sgf(raw_sgf, mode=session.mode)
        async with session.lock:
            if expected_version is not None and int(expected_version) != session.state_version:
                raise VersionConflictError(int(expected_version), session.state_version)
            session.tree = new_tree
            session.analysis_by_node.clear()
            session.state_version += 1
            if new_tree.metadata.get("GN"):
                session.title = new_tree.metadata["GN"]
            for client in session.clients.values():
                client.current_node_id = new_tree.latest_node_id
                client.following_latest = True
            await self._hydrate_mainline_cache(session)
            await self.persist_session(session)

        await self.broadcast_state_sync(session)
        return {
            "state_version": session.state_version,
            **self.build_state_sync_payload(session),
        }

    # ------------------------------------------------------------------
    # Analysis Helpers (Interactive, Full Review, AI Move)
    # ------------------------------------------------------------------

    def _build_katago_query_for_node(
        self,
        session: GameSession,
        node_id: str,
        *,
        max_visits: int = 500,
        priority: int = 10,
        report_during_search_every: float | None = 0.3,
        override_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        node = session.tree.get_node(node_id)
        init_stones, init_player, moves = session.tree.get_moves_path(node_id)
        pos_hash = session.tree.position_hash(node_id, self.engine.model_fingerprint)
        query: dict[str, Any] = {
            "moves": moves,
            "initialStones": init_stones,
            "initialPlayer": init_player,
            "rules": session.tree.rules,
            "komi": session.tree.komi,
            "boardXSize": session.tree.board_size,
            "boardYSize": session.tree.board_size,
            "analyzeTurns": [node.move_number],
            "maxVisits": int(max_visits),
            "includeOwnership": True,
            "includePVVisits": True,
            "priority": int(priority),
            "next_player": node.board.next_player,
            "node_id": node_id,
            "position_hash": pos_hash,
        }
        if report_during_search_every is not None:
            query["reportDuringSearchEvery"] = report_during_search_every
        if override_settings:
            query["overrideSettings"] = dict(override_settings)
        return query

    def schedule_interactive_analysis(
        self,
        session: GameSession,
        node_id: str,
        *,
        max_visits: int = 500,
        priority: int = 10,
        debounce: bool = True,
        force: bool = False,
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(
            self._run_interactive_analysis(
                session,
                node_id,
                max_visits=max_visits,
                priority=priority,
                debounce=debounce,
                force=force,
            )
        )
        session.active_analysis_task = task
        return task

    async def _run_interactive_analysis(
        self,
        session: GameSession,
        node_id: str,
        *,
        max_visits: int = 500,
        priority: int = 10,
        debounce: bool = True,
        force: bool = False,
    ) -> None:
        if node_id not in session.tree.nodes:
            return
        pos_hash = session.tree.position_hash(node_id, self.engine.model_fingerprint)

        # Serve directly from SQLite cache if visits are already sufficient
        if not force:
            cached = await self._hydrate_node_cache(session, node_id)
            if cached is not None and int(cached.get("root", {}).get("visits", 0)) >= max_visits:
                await self.broadcast(
                    session,
                    "analysis_update",
                    {
                        "query_id": "cache",
                        "node_id": node_id,
                        "position_hash": pos_hash,
                        "is_final": True,
                        "from_cache": True,
                        "root": cached["root"],
                        "moves": cached["moves"],
                        "ownership": cached.get("ownership"),
                        "graph_points": self.build_graph_points(session),
                    },
                )
                return

        query = self._build_katago_query_for_node(
            session,
            node_id,
            max_visits=max_visits,
            priority=priority,
            report_during_search_every=0.3,
        )

        async def _on_interim(update: dict[str, Any]) -> None:
            # Interim frame: NEVER save to SQLite or overwrite final analysis
            await self.broadcast(
                session,
                "analysis_update",
                {
                    "query_id": update.get("query_id", ""),
                    "node_id": node_id,
                    "position_hash": pos_hash,
                    "is_final": False,
                    "from_cache": False,
                    "root": update["root"],
                    "moves": update["moves"],
                    "ownership": update.get("ownership"),
                },
            )

        try:
            final = await self.engine.analyze_interactive(
                query, on_update=_on_interim, debounce=debounce
            )
        except asyncio.CancelledError:
            return
        except KataGoError as exc:
            await self.broadcast(
                session,
                "error",
                {"code": "KATAGO_ERROR", "message": str(exc), "node_id": node_id},
            )
            return

        if final is None:
            # Cancelled / superseded / terminated -> NEVER cache (Pitfall #11)
            return

        visits = int(final.get("root", {}).get("visits", 0))
        await self.db.upsert_analysis_cache(
            position_hash=pos_hash,
            board_size=session.tree.board_size,
            actual_visits=visits,
            root_info=final["root"],
            move_infos=final["moves"],
            ownership=final.get("ownership"),
            model_fingerprint=self.engine.model_fingerprint,
        )
        final["node_id"] = node_id
        final["position_hash"] = pos_hash
        final["from_cache"] = False
        session.analysis_by_node[node_id] = final

        await self.broadcast(
            session,
            "analysis_update",
            {
                "query_id": final.get("query_id", ""),
                "node_id": node_id,
                "position_hash": pos_hash,
                "is_final": True,
                "from_cache": False,
                "root": final["root"],
                "moves": final["moves"],
                "ownership": final.get("ownership"),
                "graph_points": self.build_graph_points(session),
            },
        )

    # ------------------------------------------------------------------
    # WebSocket Message Dispatcher
    # ------------------------------------------------------------------

    async def handle_ws_message(
        self,
        session: GameSession,
        client: ClientSession,
        msg: dict[str, Any],
    ) -> None:
        client.touch()
        msg_type = str(msg.get("type") or "")
        raw_payload = msg.get("payload")
        payload: dict[str, Any] = (
            dict(raw_payload)
            if isinstance(raw_payload, dict)
            else {k: v for k, v in msg.items() if k != "type"}
        )

        if msg_type == "ping":
            await self.send_to_client(
                session,
                client,
                "pong",
                {"client_ts": payload.get("client_ts"), "server_ts": epoch_ms()},
            )
            return

        if msg_type == "sync_request":
            req_node = payload.get("node_id")
            if req_node and req_node in session.tree.nodes:
                client.current_node_id = req_node
                client.following_latest = (req_node == session.tree.latest_node_id)
            elif client.current_node_id not in session.tree.nodes:
                client.current_node_id = session.tree.latest_node_id
                client.following_latest = True
            await self._hydrate_node_cache(session, client.current_node_id)
            sync_payload = self.build_state_sync_payload(session, client.current_node_id)
            await self.send_to_client(session, client, "state_sync", sync_payload)
            return

        if msg_type == "play_move":
            await self._handle_play_move(session, client, payload)
            return

        if msg_type == "navigate":
            await self._handle_navigate(session, client, payload)
            return

        if msg_type == "set_mode":
            await self._handle_set_mode(session, client, payload)
            return

        if msg_type == "request_analysis":
            await self._handle_request_analysis(session, client, payload)
            return

        if msg_type == "request_full_review":
            await self._handle_request_full_review(session, client, payload)
            return

        if msg_type == "cancel_analysis":
            scope = str(payload.get("scope", "all"))
            if scope not in ("interactive", "full_review", "all"):
                scope = "all"
            await self.engine.cancel(scope)
            return

        if msg_type == "request_ai_move":
            await self._handle_request_ai_move(session, client, payload)
            return

        if msg_type == "undo":
            await self._handle_undo(session, client, payload)
            return

        if msg_type == "resign":
            await self._handle_resign(session, client, payload)
            return

        await self.send_to_client(
            session,
            client,
            "error",
            {"code": "UNKNOWN_EVENT", "message": f"未対応のイベントです: {msg_type}"},
        )

    async def _handle_play_move(
        self,
        session: GameSession,
        client: ClientSession,
        payload: dict[str, Any],
    ) -> None:
        parent_node_id = str(payload.get("parent_node_id") or client.current_node_id)
        move = payload.get("move")
        expected_version = payload.get("expected_version")
        color = payload.get("color")

        if not isinstance(move, str) or not move.strip():
            await self.send_to_client(
                session,
                client,
                "move_rejected",
                {"code": "INVALID_COORD", "message": "着手座標が指定されていません。"},
            )
            return

        async with session.lock:
            if expected_version is not None and int(expected_version) != session.state_version:
                await self.send_to_client(
                    session,
                    client,
                    "move_rejected",
                    {
                        "code": "VERSION_CONFLICT",
                        "message": "盤面が他端末で更新されました。最新状態を同期してください。",
                        "expected_version": int(expected_version),
                        "current_version": session.state_version,
                    },
                )
                return

            try:
                node = session.tree.play_move(parent_node_id, move, color=color)
            except IllegalMoveError as exc:
                await self.send_to_client(
                    session,
                    client,
                    "move_rejected",
                    {
                        "code": exc.code,
                        "message": exc.message,
                        "move": move,
                        "parent_node_id": parent_node_id,
                    },
                )
                return

            session.state_version += 1
            client.current_node_id = node.node_id
            client.following_latest = (node.node_id == session.tree.latest_node_id)

            # Only advance other clients that are following latest mainline
            for other in session.clients.values():
                if other.client_id == client.client_id:
                    continue
                if other.following_latest and node.node_id == session.tree.latest_node_id:
                    other.current_node_id = node.node_id

            cached_an = await self._hydrate_node_cache(session, node.node_id)
            await self.persist_session(session)

            accepted_payload = {
                "actor_client_id": client.client_id,
                "node": node.to_summary_dict(),
                "node_id": node.node_id,
                "parent_node_id": node.parent_id,
                "move_number": node.move_number,
                "color": node.color,
                "move": node.move,
                "captured": list(node.captured),
                "latest_node_id": session.tree.latest_node_id,
                "mainline_ids": list(session.tree.mainline_ids),
                "branch_info": session.tree.get_branch_info(node.node_id),
                "board": node.board.to_position_dict(
                    session.tree.rules,
                    session.tree.komi,
                    self.engine.model_fingerprint,
                ),
                "analysis": cached_an,
                "graph_points": self.build_graph_points(session),
            }

        await self.broadcast(session, "move_accepted", accepted_payload)

        if session.mode == "review" and session.auto_analyze:
            self.schedule_interactive_analysis(session, node.node_id, debounce=True)

    async def _handle_navigate(
        self,
        session: GameSession,
        client: ClientSession,
        payload: dict[str, Any],
    ) -> None:
        node_id = payload.get("node_id")
        if node_id is None and payload.get("target") is not None:
            target = str(payload["target"]).lower()
            if target == "root":
                node_id = session.tree.root_id
            elif target == "latest":
                node_id = session.tree.latest_node_id
            elif target == "mainline":
                bi = session.tree.get_branch_info(client.current_node_id)
                node_id = bi.get("divergence_node_id") or session.tree.latest_node_id
        if node_id is None and payload.get("move_number") is not None:
            mv_num = max(0, min(len(session.tree.mainline_ids) - 1, int(payload["move_number"])))
            node_id = session.tree.mainline_ids[mv_num]
        if node_id is None and payload.get("delta") is not None:
            delta = int(payload["delta"])
            cur = session.tree.nodes.get(client.current_node_id)
            if cur is not None:
                if delta == -1 and cur.parent_id:
                    node_id = cur.parent_id
                elif delta == 1 and cur.children_ids:
                    mainline_set = set(session.tree.mainline_ids)
                    node_id = next((c for c in cur.children_ids if c in mainline_set), cur.children_ids[0])
                else:
                    target_mv = max(0, min(len(session.tree.mainline_ids) - 1, cur.move_number + delta))
                    node_id = session.tree.mainline_ids[target_mv]

        if not node_id or node_id not in session.tree.nodes:
            await self.send_to_client(
                session,
                client,
                "error",
                {"code": "INVALID_NODE", "message": f"移動先の局面が存在しません: {node_id}"},
            )
            return

        # Terminal-local viewport ONLY: never modifies other connected clients!
        client.current_node_id = str(node_id)
        client.following_latest = (client.current_node_id == session.tree.latest_node_id)

        cached = await self._hydrate_node_cache(session, client.current_node_id)
        sync_payload = self.build_state_sync_payload(session, client.current_node_id)
        await self.send_to_client(session, client, "state_sync", sync_payload)

        if session.mode == "review" and session.auto_analyze and cached is None:
            self.schedule_interactive_analysis(
                session, client.current_node_id, debounce=True
            )

    async def _handle_set_mode(
        self,
        session: GameSession,
        client: ClientSession,
        payload: dict[str, Any],
    ) -> None:
        async with session.lock:
            if "mode" in payload and payload["mode"] in ("review", "play"):
                session.mode = str(payload["mode"])
                session.tree.mode = session.mode
            if "ai_level" in payload and payload["ai_level"] in AI_PRESETS:
                session.ai_level = str(payload["ai_level"])
            if "player_color" in payload and payload["player_color"] in ("B", "W"):
                session.player_color = str(payload["player_color"])
            if "auto_analyze" in payload:
                session.auto_analyze = bool(payload["auto_analyze"])
            session.state_version += 1
            await self.persist_session(session)

        await self.broadcast_state_sync(session)

    async def _handle_request_analysis(
        self,
        session: GameSession,
        client: ClientSession,
        payload: dict[str, Any],
    ) -> None:
        node_id = str(payload.get("node_id") or client.current_node_id)
        if node_id not in session.tree.nodes:
            await self.send_to_client(
                session,
                client,
                "error",
                {"code": "INVALID_NODE", "message": f"解析対象の局面が見つかりません: {node_id}"},
            )
            return
        max_visits = int(payload.get("max_visits", 500))
        priority = int(payload.get("priority", 10))
        force = bool(payload.get("force", False))
        debounce = bool(payload.get("debounce", False))
        self.schedule_interactive_analysis(
            session,
            node_id,
            max_visits=max_visits,
            priority=priority,
            debounce=debounce,
            force=force,
        )

    async def _handle_request_full_review(
        self,
        session: GameSession,
        client: ClientSession,
        payload: dict[str, Any],
    ) -> None:
        max_visits = int(payload.get("max_visits", FULL_REVIEW_DEFAULT_VISITS))
        job_id = f"fr-{uuid.uuid4().hex[:8]}"

        await self._hydrate_mainline_cache(session)
        mainline = list(session.tree.mainline_ids)
        init_stones, init_player, all_moves = session.tree.get_moves_path(mainline[-1])

        uncached_turns: list[dict[str, Any]] = []
        skipped_cached = 0
        for idx, nid in enumerate(mainline):
            existing = session.analysis_by_node.get(nid)
            if existing is not None and int(existing.get("root", {}).get("visits", 0)) >= max_visits:
                skipped_cached += 1
                continue
            node = session.tree.get_node(nid)
            pos_hash = session.tree.position_hash(nid, self.engine.model_fingerprint)
            uncached_turns.append(
                {
                    "node_id": nid,
                    "position_hash": pos_hash,
                    "turn_number": idx,
                    "next_player": node.board.next_player,
                    "moves": all_moves[:idx],
                    "initialStones": init_stones,
                    "initialPlayer": init_player,
                    "rules": session.tree.rules,
                    "komi": session.tree.komi,
                    "boardXSize": session.tree.board_size,
                    "boardYSize": session.tree.board_size,
                    "maxVisits": max_visits,
                }
            )

        total_all = len(mainline)

        async def _on_turn(result: dict[str, Any]) -> None:
            nid = result.get("node_id")
            ph = result.get("position_hash")
            if not nid or not ph:
                return
            visits = int(result.get("root", {}).get("visits", 0))
            await self.db.upsert_analysis_cache(
                position_hash=ph,
                board_size=session.tree.board_size,
                actual_visits=visits,
                root_info=result["root"],
                move_infos=result["moves"],
                ownership=result.get("ownership"),
                model_fingerprint=self.engine.model_fingerprint,
            )
            session.analysis_by_node[nid] = result

        async def _on_progress(prog: dict[str, Any]) -> None:
            await self.broadcast(
                session,
                "full_review_progress",
                {
                    "job_id": prog.get("job_id", job_id),
                    "status": prog.get("status", "running"),
                    "completed": skipped_cached + int(prog.get("completed", 0)),
                    "total": total_all,
                    "cached_skipped": skipped_cached,
                    "node_id": prog.get("node_id"),
                    "error": prog.get("error"),
                    "graph_points": self.build_graph_points(session),
                },
            )

        await self.engine.start_full_review(job_id, uncached_turns, _on_turn, _on_progress)

    async def _handle_request_ai_move(
        self,
        session: GameSession,
        client: ClientSession,
        payload: dict[str, Any],
    ) -> None:
        parent_node_id = str(payload.get("parent_node_id") or session.tree.latest_node_id)
        ai_level = str(payload.get("ai_level") or session.ai_level)
        if ai_level not in AI_PRESETS:
            ai_level = "5k"
        expected_version = payload.get("expected_version")

        async with session.lock:
            if expected_version is not None and int(expected_version) != session.state_version:
                await self.send_to_client(
                    session,
                    client,
                    "move_rejected",
                    {
                        "code": "VERSION_CONFLICT",
                        "message": "盤面が他端末で更新されました。",
                        "expected_version": int(expected_version),
                        "current_version": session.state_version,
                    },
                )
                return
            if parent_node_id not in session.tree.nodes:
                await self.send_to_client(
                    session,
                    client,
                    "error",
                    {"code": "INVALID_NODE", "message": f"局面が見つかりません: {parent_node_id}"},
                )
                return
            parent_node = session.tree.get_node(parent_node_id)
            if session.mode == "play" and parent_node.board.is_game_over:
                await self.send_to_client(
                    session,
                    client,
                    "move_rejected",
                    {"code": "GAME_OVER", "message": "対局はすでに終了しています。"},
                )
                return
            side_to_move = parent_node.board.next_player
            start_version = session.state_version
            preset = AI_PRESETS[ai_level]
            query = self._build_katago_query_for_node(
                session,
                parent_node_id,
                max_visits=int(preset["max_visits"]),
                priority=20,
                report_during_search_every=None,
                override_settings={"wideRootNoise": 0.0},
            )

        try:
            analysis = await self.engine.analyze_once(query, priority=20)
        except KataGoError as exc:
            await self.send_to_client(
                session,
                client,
                "error",
                {"code": "KATAGO_ERROR", "message": str(exc)},
            )
            return

        decision = select_ai_move(analysis, side_to_move, ai_level)

        async with session.lock:
            if session.state_version != start_version:
                await self.send_to_client(
                    session,
                    client,
                    "move_rejected",
                    {
                        "code": "VERSION_CONFLICT",
                        "message": "AI 思考中に盤面が更新されました。",
                        "expected_version": start_version,
                        "current_version": session.state_version,
                    },
                )
                return

            if decision["should_resign"]:
                winner = opposite_color(side_to_move)
                result_str = f"{winner}+R"
                latest = session.tree.get_node(parent_node_id)
                latest.board.is_game_over = True
                latest.board.game_result = result_str
                session.tree.metadata["RE"] = result_str
                session.state_version += 1
                await self.persist_session(session)
                ai_payload = {
                    "move": "resign",
                    "color": side_to_move,
                    "ai_level": ai_level,
                    "resigned": True,
                    "game_result": result_str,
                }
                resign_sync = True
            else:
                chosen_move = str(decision["move"])
                try:
                    node = session.tree.play_move(
                        parent_node_id, chosen_move, color=side_to_move
                    )
                except IllegalMoveError:
                    # Safe fallback to pass if chosen move is somehow illegal
                    node = session.tree.play_move(
                        parent_node_id, "pass", color=side_to_move
                    )
                session.state_version += 1
                for c in session.clients.values():
                    if c.following_latest and node.node_id == session.tree.latest_node_id:
                        c.current_node_id = node.node_id
                await self.persist_session(session)
                ai_payload = {
                    "move": node.move,
                    "color": node.color,
                    "node_id": node.node_id,
                    "move_number": node.move_number,
                    "ai_level": ai_level,
                    "resigned": False,
                    "selected_info": decision.get("selected_info"),
                }
                accepted_payload = {
                    "actor_client_id": "ai",
                    "node": node.to_summary_dict(),
                    "node_id": node.node_id,
                    "parent_node_id": node.parent_id,
                    "move_number": node.move_number,
                    "color": node.color,
                    "move": node.move,
                    "captured": list(node.captured),
                    "latest_node_id": session.tree.latest_node_id,
                    "mainline_ids": list(session.tree.mainline_ids),
                    "branch_info": session.tree.get_branch_info(node.node_id),
                    "board": node.board.to_position_dict(
                        session.tree.rules,
                        session.tree.komi,
                        self.engine.model_fingerprint,
                    ),
                    "analysis": None,
                    "graph_points": self.build_graph_points(session),
                }
                resign_sync = False

        await self.broadcast(session, "ai_move", ai_payload)
        if resign_sync:
            await self.broadcast_state_sync(session)
        else:
            await self.broadcast(session, "move_accepted", accepted_payload)

    async def _handle_undo(
        self,
        session: GameSession,
        client: ClientSession,
        payload: dict[str, Any],
    ) -> None:
        expected_version = payload.get("expected_version")
        steps = max(1, min(int(payload.get("steps", 1)), 20))

        async with session.lock:
            if expected_version is not None and int(expected_version) != session.state_version:
                await self.send_to_client(
                    session,
                    client,
                    "move_rejected",
                    {
                        "code": "VERSION_CONFLICT",
                        "message": "盤面が他端末で更新されました。",
                        "expected_version": int(expected_version),
                        "current_version": session.state_version,
                    },
                )
                return

            removed_ids: set[str] = set()
            for _ in range(steps):
                if len(session.tree.mainline_ids) <= 1:
                    break
                tail_id = session.tree.mainline_ids.pop()
                parent_id = session.tree.mainline_ids[-1]
                tail_node = session.tree.nodes.get(tail_id)
                parent_node = session.tree.nodes.get(parent_id)
                if tail_node is not None and not tail_node.children_ids:
                    session.tree.nodes.pop(tail_id, None)
                    session.analysis_by_node.pop(tail_id, None)
                    removed_ids.add(tail_id)
                    if parent_node is not None and tail_id in parent_node.children_ids:
                        parent_node.children_ids.remove(tail_id)

            session.tree.latest_node_id = session.tree.mainline_ids[-1]
            # Clear game-over lock if stepping back
            latest_node = session.tree.get_node(session.tree.latest_node_id)
            latest_node.board.is_game_over = False
            latest_node.board.game_result = None
            session.tree.metadata.pop("RE", None)

            session.state_version += 1
            for c in session.clients.values():
                if c.current_node_id in removed_ids or c.following_latest:
                    c.current_node_id = session.tree.latest_node_id
                    c.following_latest = True
            await self.persist_session(session)

        await self.broadcast_state_sync(session)

    async def _handle_resign(
        self,
        session: GameSession,
        client: ClientSession,
        payload: dict[str, Any],
    ) -> None:
        expected_version = payload.get("expected_version")
        async with session.lock:
            if expected_version is not None and int(expected_version) != session.state_version:
                await self.send_to_client(
                    session,
                    client,
                    "move_rejected",
                    {
                        "code": "VERSION_CONFLICT",
                        "message": "盤面が他端末で更新されました。",
                        "expected_version": int(expected_version),
                        "current_version": session.state_version,
                    },
                )
                return

            latest_node = session.tree.get_node(session.tree.latest_node_id)
            resign_color = str(payload.get("color") or latest_node.board.next_player)
            if resign_color not in ("B", "W"):
                resign_color = latest_node.board.next_player
            winner = opposite_color(resign_color)
            result_str = f"{winner}+R"
            latest_node.board.is_game_over = True
            latest_node.board.game_result = result_str
            session.tree.metadata["RE"] = result_str
            session.state_version += 1
            await self.persist_session(session)

        await self.broadcast_state_sync(session)


__all__ = [
    "VersionConflictError",
    "epoch_ms",
    "make_envelope",
    "ClientSession",
    "GameSession",
    "GameHub",
]
