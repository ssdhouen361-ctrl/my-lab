"""FastAPI application factory, strict Origin validation, REST API & WebSocket endpoints.

Provides `create_app(settings=..., engine=...)` for clean DI in Layer 1/2 tests
and a module-level `app` instance for `uvicorn app.main:app --workers 1`.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Literal
import uuid

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import Settings
from app.db import Database
from app.game_hub import GameHub, VersionConflictError
from app.katago_engine import AnalysisEngineProtocol, EngineState, KataGoEngine
from app.rules import (
    DEFAULT_MAX_SGF_BYTES,
    SgfError,
    SgfLimitError,
    atomic_write_text,
    parse_sgf,
    safe_resolve_under,
)

logger = logging.getLogger("web_goban.api")


def configure_logging(logs_dir: Path) -> None:
    """Configure RotatingFileHandler (10MB x 5 backups) on web_goban logger."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = (logs_dir / "app.log").resolve()
    root_logger = logging.getLogger("web_goban")
    root_logger.setLevel(logging.INFO)

    for handler in root_logger.handlers:
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename).resolve() == log_file:
            return

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class WarmupRequest(BaseModel):
    force: bool = False


class CreateGameRequest(BaseModel):
    board_size: int = Field(default=19, ge=2, le=19)
    komi: float | None = None
    handicap: int = Field(default=0, ge=0, le=9)
    rules: str = "japanese"
    mode: Literal["review", "play"] = "review"
    ai_level: str = "5k"
    player_color: Literal["B", "W"] = "B"
    title: str = ""
    sgf_text: str | None = None
    sgf_id: str | None = None
    auto_analyze: bool | None = None


class UpdateSgfRecordRequest(BaseModel):
    title: str | None = None
    played_at: str | None = None
    player_color: Literal["B", "W"] | None = None
    result: str | None = None
    tags: list[str] | None = None
    summary: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helpers for dual multipart / JSON SGF ingestion
# ---------------------------------------------------------------------------


async def _extract_sgf_payload(
    request: Request,
) -> tuple[bytes | str, dict[str, Any]]:
    content_type = (request.headers.get("content-type") or "").lower()

    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            sgf_text_field = form.get("sgf_text")
            if isinstance(sgf_text_field, str) and sgf_text_field.strip():
                meta: dict[str, Any] = {
                    k: v for k, v in form.items() if k != "sgf_text" and isinstance(v, str)
                }
                return sgf_text_field, meta
            raise HTTPException(status_code=400, detail="SGF ファイルまたは sgf_text が必要です。")
        raw_bytes = await upload.read()
        if len(raw_bytes) > DEFAULT_MAX_SGF_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"SGF ファイルサイズが上限（{DEFAULT_MAX_SGF_BYTES} bytes）を超えています。",
            )
        meta = {k: v for k, v in form.items() if k != "file" and isinstance(v, str)}
        return raw_bytes, meta

    raw_body = await request.body()
    if len(raw_body) > DEFAULT_MAX_SGF_BYTES + 262_144:
        raise HTTPException(
            status_code=413,
            detail="リクエストサイズが上限を超えています。",
        )

    if "application/json" in content_type or raw_body.lstrip().startswith(b"{"):
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"不正な JSON です: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("sgf_text"), str):
            raise HTTPException(status_code=400, detail="sgf_text フィールドが必要です。")
        sgf_text = data["sgf_text"]
        if len(sgf_text.encode("utf-8")) > DEFAULT_MAX_SGF_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"SGF サイズが上限（{DEFAULT_MAX_SGF_BYTES} bytes）を超えています。",
            )
        return sgf_text, {k: v for k, v in data.items() if k != "sgf_text"}

    if len(raw_body) > DEFAULT_MAX_SGF_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"SGF サイズが上限（{DEFAULT_MAX_SGF_BYTES} bytes）を超えています。",
        )
    if not raw_body.strip():
        raise HTTPException(status_code=400, detail="SGF データが空です。")
    return raw_body, {}


# ---------------------------------------------------------------------------
# FastAPI Application Factory
# ---------------------------------------------------------------------------


def create_app(
    settings: Settings | None = None,
    engine: AnalysisEngineProtocol | None = None,
) -> FastAPI:
    """Create and wire a complete Web Goban FastAPI application with DI support."""
    cfg = settings if settings is not None else Settings.from_env()
    db = Database(cfg.db_path)  # type: ignore[arg-type]
    eng: AnalysisEngineProtocol = engine if engine is not None else KataGoEngine(cfg)
    hub = GameHub(cfg, db, eng)

    if hasattr(eng, "set_status_callback"):
        eng.set_status_callback(hub.broadcast_engine_status)  # type: ignore[attr-defined]

    warmup_tasks: set[asyncio.Task[Any]] = set()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        cfg.ensure_dirs()
        configure_logging(cfg.logs_dir)  # type: ignore[arg-type]
        await db.connect()
        hub.start_reaper()
        logger.info(
            "Web Goban started (build_id=%s, data_dir=%s)",
            cfg.build_id,
            cfg.data_dir,
        )
        try:
            yield
        finally:
            for t in list(warmup_tasks):
                t.cancel()
            if warmup_tasks:
                await asyncio.gather(*warmup_tasks, return_exceptions=True)
            await hub.stop_reaper()
            await eng.stop()
            await db.close()
            logger.info("Web Goban stopped cleanly")

    app = FastAPI(
        title="Web Goban API",
        version=cfg.api_version,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.db = db
    app.state.engine = eng
    app.state.hub = hub

    # ------------------------------------------------------------------
    # Strict Origin / CORS Middleware (Pitfall #7: no "*" wildcard)
    # ------------------------------------------------------------------

    @app.middleware("http")
    async def strict_origin_middleware(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin is not None:
            if not cfg.is_origin_allowed(origin):
                return JSONResponse(
                    {"detail": "Origin not allowed"},
                    status_code=403,
                )
            normalized_origin = origin.strip().rstrip("/")
            if request.method == "OPTIONS":
                return Response(
                    status_code=204,
                    headers={
                        "Access-Control-Allow-Origin": normalized_origin,
                        "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type, X-Client-Id",
                        "Vary": "Origin",
                    },
                )
            response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = normalized_origin
            response.headers["Vary"] = "Origin"
            return response

        return await call_next(request)

    # ------------------------------------------------------------------
    # Static Frontend & PWA Shell Routes
    # ------------------------------------------------------------------

    static_dir = cfg.static_dir
    assert static_dir is not None

    @app.get("/", include_in_schema=False)
    async def serve_index() -> Response:
        index_path = static_dir / "index.html"
        if not index_path.is_file():
            return JSONResponse(
                {"detail": "Frontend index.html not yet installed"},
                status_code=404,
            )
        html = index_path.read_text(encoding="utf-8").replace("__BUILD_ID__", cfg.build_id)
        return HTMLResponse(
            content=html,
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    @app.get("/sw.js", include_in_schema=False)
    async def serve_service_worker() -> Response:
        sw_path = static_dir / "sw.js"
        if not sw_path.is_file():
            return JSONResponse({"detail": "sw.js not found"}, status_code=404)
        content = sw_path.read_text(encoding="utf-8").replace("__BUILD_ID__", cfg.build_id)
        return Response(
            content=content,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def serve_manifest() -> Response:
        manifest_path = static_dir / "manifest.webmanifest"
        if not manifest_path.is_file():
            return JSONResponse({"detail": "manifest.webmanifest not found"}, status_code=404)
        return Response(
            content=manifest_path.read_bytes(),
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    app.mount(
        "/static",
        StaticFiles(directory=str(static_dir), check_dir=False),
        name="static",
    )

    # ------------------------------------------------------------------
    # REST API: Health & Engine Lifecycle
    # ------------------------------------------------------------------

    @app.get("/api/v1/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "api_version": cfg.api_version,
            "min_client_version": cfg.min_client_version,
            "build_id": cfg.build_id,
        }

    @app.get("/api/v1/engine/status")
    async def engine_status() -> dict[str, Any]:
        if hasattr(eng, "refresh_external_katago"):
            await eng.refresh_external_katago()  # type: ignore[attr-defined]
        return eng.get_status()

    @app.post("/api/v1/engine/warmup")
    async def engine_warmup(
        request: Request,
        wait: bool = Query(default=False),
    ) -> JSONResponse:
        force = False
        try:
            body = await request.body()
            if body.strip():
                parsed = WarmupRequest.model_validate_json(body)
                force = parsed.force
        except Exception:
            pass

        if hasattr(eng, "refresh_external_katago"):
            await eng.refresh_external_katago(force=True)  # type: ignore[attr-defined]

        current = eng.get_status()
        if eng.state in (EngineState.IDLE, EngineState.ANALYZING):
            return JSONResponse(current, status_code=200)

        if not force and eng.state == EngineState.STOPPED and current.get("external_katago_detected"):
            suppressed = await eng.warmup(force=False)
            return JSONResponse(suppressed, status_code=200)

        if wait:
            status_after = await eng.warmup(force=force)
            return JSONResponse(status_after, status_code=200)

        async def _bg_warmup() -> None:
            try:
                await eng.warmup(force=force)
            except Exception as exc:
                logger.warning("Background warmup failed: %s", exc)

        task = asyncio.create_task(_bg_warmup())
        warmup_tasks.add(task)
        task.add_done_callback(warmup_tasks.discard)

        resp_status = dict(eng.get_status())
        if resp_status.get("state") == EngineState.STOPPED.value:
            resp_status["state"] = EngineState.STARTING.value
        return JSONResponse(resp_status, status_code=202)

    @app.post("/api/v1/engine/stop")
    async def engine_stop() -> dict[str, Any]:
        await eng.stop()
        return eng.get_status()

    # ------------------------------------------------------------------
    # REST API: Game Sessions
    # ------------------------------------------------------------------

    @app.post("/api/v1/games", status_code=201)
    async def create_game(req: CreateGameRequest) -> dict[str, Any]:
        sgf_content: str | bytes | None = req.sgf_text
        title = req.title

        if sgf_content is None and req.sgf_id:
            record = await db.get_sgf_record(req.sgf_id)
            if record is None:
                raise HTTPException(status_code=404, detail="指定された SGF レコードが見つかりません。")
            assert cfg.sgf_dir is not None
            try:
                sgf_file = safe_resolve_under(cfg.sgf_dir, record["rel_path"])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not sgf_file.is_file():
                raise HTTPException(status_code=404, detail="SGF ファイルがディスク上に見つかりません。")
            sgf_content = sgf_file.read_bytes()
            if not title:
                title = record.get("title", "")

        try:
            session = await hub.create_game(
                board_size=req.board_size,
                komi=req.komi,
                handicap=req.handicap,
                rules=req.rules,
                mode=req.mode,
                ai_level=req.ai_level,
                player_color=req.player_color,
                title=title,
                sgf_text=sgf_content,
                sgf_id=req.sgf_id,
                auto_analyze=req.auto_analyze,
            )
        except SgfLimitError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except (SgfError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "state_version": session.state_version,
            **hub.build_state_sync_payload(session),
        }

    @app.get("/api/v1/games/recent")
    async def list_recent_games(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
        games = await db.list_recent_games(limit=limit)
        return {"games": games}

    @app.get("/api/v1/games/{game_id}")
    async def get_game(game_id: str) -> dict[str, Any]:
        session = await hub.get_or_load_session(game_id)
        if session is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        return {
            "state_version": session.state_version,
            **hub.build_state_sync_payload(session),
        }

    @app.post("/api/v1/games/{game_id}/import-sgf")
    async def import_game_sgf(game_id: str, request: Request) -> dict[str, Any]:
        session = await hub.get_or_load_session(game_id)
        if session is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")

        raw_sgf, meta = await _extract_sgf_payload(request)
        expected_ver_raw = meta.get("expected_version")
        expected_version = int(expected_ver_raw) if expected_ver_raw is not None else None

        try:
            return await hub.import_sgf_into_session(
                session, raw_sgf, expected_version=expected_version
            )
        except VersionConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "VERSION_CONFLICT",
                    "expected_version": exc.expected,
                    "current_version": exc.current,
                },
            ) from exc
        except SgfLimitError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except SgfError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/games/{game_id}/export-sgf")
    async def export_game_sgf(
        game_id: str,
        request: Request,
        format: Literal["file", "json"] = Query(default="file"),
    ) -> Response:
        session = await hub.get_or_load_session(game_id)
        if session is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        sgf_text = session.tree.to_sgf()
        filename = f"{game_id}.sgf"

        accept = (request.headers.get("accept") or "").lower()
        if format == "json" or ("application/json" in accept and format != "file"):
            return JSONResponse(
                {
                    "game_id": game_id,
                    "filename": filename,
                    "sgf_text": sgf_text,
                }
            )
        return Response(
            content=sgf_text.encode("utf-8"),
            media_type="application/x-go-sgf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    # ------------------------------------------------------------------
    # REST API: SGF Library CRUD
    # ------------------------------------------------------------------

    @app.get("/api/v1/sgf")
    async def list_sgf_library(
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        records = await db.list_sgf_records(limit=limit, offset=offset)
        return {"records": records}

    @app.post("/api/v1/sgf", status_code=201)
    async def create_sgf_record(request: Request) -> dict[str, Any]:
        raw_sgf, meta = await _extract_sgf_payload(request)
        try:
            tree = parse_sgf(raw_sgf, mode="review")
        except SgfLimitError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except SgfError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        sgf_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        rel_path = f"{now:%Y}/{now:%m}/{sgf_id}.sgf"
        assert cfg.sgf_dir is not None
        target_path = safe_resolve_under(cfg.sgf_dir, rel_path)
        canonical_sgf = tree.to_sgf()
        await asyncio.to_thread(atomic_write_text, target_path, canonical_sgf)

        tags_raw = meta.get("tags")
        if isinstance(tags_raw, str):
            try:
                tags = json.loads(tags_raw)
            except json.JSONDecodeError:
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        elif isinstance(tags_raw, list):
            tags = [str(t) for t in tags_raw]
        else:
            tags = []

        record = {
            "sgf_id": sgf_id,
            "title": str(
                meta.get("title") or tree.metadata.get("GN") or f"{tree.board_size}路棋譜"
            ),
            "played_at": str(meta.get("played_at") or tree.metadata.get("DT") or now.strftime("%Y-%m-%d")),
            "board_size": tree.board_size,
            "move_count": max(0, len(tree.mainline_ids) - 1),
            "player_color": str(meta.get("player_color") or "B") if meta.get("player_color") in ("B", "W") else "B",
            "result": str(meta.get("result") or tree.metadata.get("RE") or ""),
            "tags": tags,
            "rel_path": rel_path,
            "summary": meta.get("summary") if isinstance(meta.get("summary"), dict) else {},
        }
        await db.save_sgf_record(record)
        saved = await db.get_sgf_record(sgf_id)
        assert saved is not None
        return {
            **saved,
            "warnings": list(tree.warnings),
        }

    @app.get("/api/v1/sgf/{sgf_id}")
    async def get_sgf_record(sgf_id: str) -> dict[str, Any]:
        record = await db.get_sgf_record(sgf_id)
        if record is None:
            raise HTTPException(status_code=404, detail="棋譜レコードが見つかりません。")
        assert cfg.sgf_dir is not None
        try:
            file_path = safe_resolve_under(cfg.sgf_dir, record["rel_path"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="棋譜ファイルが見つかりません。")
        sgf_text = file_path.read_text(encoding="utf-8", errors="replace")
        return {
            **record,
            "sgf_text": sgf_text,
        }

    @app.patch("/api/v1/sgf/{sgf_id}")
    async def patch_sgf_record(sgf_id: str, req: UpdateSgfRecordRequest) -> dict[str, Any]:
        updated = await db.update_sgf_record(
            sgf_id, req.model_dump(exclude_none=True)
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="棋譜レコードが見つかりません。")
        return updated

    @app.delete("/api/v1/sgf/{sgf_id}")
    async def delete_sgf_record(sgf_id: str) -> dict[str, Any]:
        record = await db.get_sgf_record(sgf_id)
        if record is None:
            raise HTTPException(status_code=404, detail="棋譜レコードが見つかりません。")
        assert cfg.sgf_dir is not None
        try:
            file_path = safe_resolve_under(cfg.sgf_dir, record["rel_path"])
            if file_path.is_file():
                file_path.unlink()
        except ValueError:
            pass
        await db.delete_sgf_record(sgf_id)
        return {"deleted": True, "sgf_id": sgf_id}

    # ------------------------------------------------------------------
    # REST API: Gemini AI Coach (Phase 2)
    # ------------------------------------------------------------------

    @app.post("/api/v1/games/{game_id}/coach/explain")
    async def coach_explain(game_id: str, request: Request) -> dict[str, Any]:
        session = await hub.get_or_load_session(game_id)
        if session is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")

        body = await request.json() if (await request.body()) else {}
        node_id = body.get("node_id") or session.tree.latest_node_id
        node = session.tree.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="指定のノードが見つかりません。")

        from app.fact_bridge import GoFactBridge
        from app.coach_provider import RuleBasedFallbackCoach

        bridge = GoFactBridge(session.tree.board_size)
        coach = RuleBasedFallbackCoach()

        # KataGo の最新解析からファクトを抽出
        pos_hash = session.tree.position_hash(node.node_id)
        analysis = await db.get_analysis_cache(pos_hash)
        actual_move = node.move or "pass"
        best_move = "D4"
        score_loss = 3.5
        winrate_loss = 0.15

        if analysis and analysis.get("moves"):
            top = analysis["moves"][0]
            best_move = top.get("move", "D4")
            score_loss = float(top.get("score_loss", 3.5))

        facts = bridge.extract_blunder_facts(
            actual_move_gtp=actual_move,
            best_move_gtp=best_move,
            player=node.board.next_player,
            score_loss=score_loss,
            winrate_loss=winrate_loss,
            score_lead_before=0.0,
            score_lead_after=-score_loss,
        )

        res = coach.explain_blunder(facts)
        return res.model_dump()

    @app.post("/api/v1/games/{game_id}/coach/hint")
    async def coach_hint(game_id: str, request: Request) -> dict[str, Any]:
        session = await hub.get_or_load_session(game_id)
        if session is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")

        body = await request.json() if (await request.body()) else {}
        stage = int(body.get("stage", 1))

        from app.coach_provider import RuleBasedFallbackCoach
        coach = RuleBasedFallbackCoach()
        hint = coach.provide_hint(stage, best_move="Q16", area_name="右辺")
        return hint.model_dump()

    # ------------------------------------------------------------------
    # WebSocket: Real-time Game & Analysis Stream (Pitfalls #7, #18)
    # ------------------------------------------------------------------

    @app.websocket("/ws/games/{game_id}")
    async def game_websocket(websocket: WebSocket, game_id: str) -> None:
        origin = websocket.headers.get("origin")
        if not cfg.is_origin_allowed(origin):
            await websocket.close(code=1008, reason="Forbidden origin")
            return

        session = await hub.get_or_load_session(game_id)
        if session is None:
            await websocket.close(code=1008, reason="Game not found")
            return

        await websocket.accept()
        client_id = (
            websocket.query_params.get("client_id")
            or websocket.headers.get("x-client-id")
            or f"c-{uuid.uuid4().hex[:8]}"
        )
        client = hub.register_client(session, client_id, websocket)

        try:
            initial_payload = hub.build_state_sync_payload(session, client.current_node_id)
            await hub.send_to_client(session, client, "state_sync", initial_payload)

            while True:
                raw_text = await websocket.receive_text()
                try:
                    data = json.loads(raw_text)
                except json.JSONDecodeError:
                    await hub.send_to_client(
                        session,
                        client,
                        "error",
                        {"code": "INVALID_JSON", "message": "JSON の形式が不正です。"},
                    )
                    continue
                if not isinstance(data, dict):
                    await hub.send_to_client(
                        session,
                        client,
                        "error",
                        {"code": "INVALID_MESSAGE", "message": "JSON オブジェクトを送信してください。"},
                    )
                    continue
                await hub.handle_ws_message(session, client, data)
        except WebSocketDisconnect:
            pass
        finally:
            hub.unregister_client(session, client_id)

    return app


app = create_app()

__all__ = ["create_app", "configure_logging", "app"]
