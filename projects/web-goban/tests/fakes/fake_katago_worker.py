#!/usr/bin/env python3
"""Real OS-pipe NDJSON subprocess simulating KataGo Analysis Engine.

Supports deterministic analysis responses plus fault/stress scenarios for Layer 1/2/3 QA:
- action == "query_version"
- action == "terminate" (emits either noResults=True or partial-visits final frame)
- action == "terminate_all"
- Dynamic boardXSize * boardYSize ownership (81 / 169 / 361)
- Triggers via query ID prefixes, CLI args, OR environment variables:
  - large- / --large-bytes / FAKE_KATAGO_LARGE_BYTES: pads single NDJSON line to 120KB-200KB (> 64KB limit)
  - stderr-flood- / --stderr-flood-bytes / FAKE_KATAGO_STDERR_FLOOD_BYTES: writes 128KB+ to stderr
  - error- / --error-on-query / FAKE_KATAGO_ERROR_ON_QUERY: emits top-level {"id": qid, "error": "..."}
  - slow- / partial- / --delay-sec / reportDuringSearchEvery: streams isDuringSearch=True then final frame
  - crash- / --crash-on-query / --crash-once-file: exits non-zero immediately
  - hang-: waits until terminated or stdin closes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

GTP_COLS = "ABCDEFGHJKLMNOPQRST"  # 'I' intentionally omitted


def coord_to_gtp(x: int, y: int, board_y: int) -> str:
    return f"{GTP_COLS[x]}{board_y - y}"


def _load_fixture_override(path_str: str) -> dict[str, Any] | None:
    cleaned = path_str.strip()
    if not cleaned:
        return None
    p = Path(cleaned)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FakeKataGo Analysis Engine NDJSON worker.")
    parser.add_argument(
        "--large-bytes",
        type=int,
        default=int(os.environ.get("FAKE_KATAGO_LARGE_BYTES", "0")),
    )
    parser.add_argument(
        "--stderr-flood-bytes",
        type=int,
        default=int(os.environ.get("FAKE_KATAGO_STDERR_FLOOD_BYTES", "0")),
    )
    parser.add_argument(
        "--delay-sec",
        type=float,
        default=float(os.environ.get("FAKE_KATAGO_DELAY_SEC", "0.0")),
    )
    parser.add_argument(
        "--terminate-mode",
        default=os.environ.get("FAKE_KATAGO_TERMINATE_MODE", "noresults"),
        choices=("noresults", "partial"),
    )
    parser.add_argument(
        "--crash-on-query",
        type=int,
        default=int(os.environ.get("FAKE_KATAGO_CRASH_ON_QUERY", "0")),
    )
    parser.add_argument(
        "--crash-once-file",
        default=os.environ.get("FAKE_KATAGO_CRASH_ONCE_FILE", ""),
    )
    parser.add_argument(
        "--error-on-query",
        type=int,
        default=int(os.environ.get("FAKE_KATAGO_ERROR_ON_QUERY", "0")),
    )
    parser.add_argument(
        "--fixture-json",
        default=os.environ.get("FAKE_KATAGO_FIXTURE_JSON", ""),
    )
    args, _unknown = parser.parse_known_args(argv)
    return args


class FakeKataGoWorker:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.fixture_override = _load_fixture_override(args.fixture_json)
        self._stdout_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_events: dict[str, threading.Event] = {}
        self._terminated_ids: set[str] = set()
        self._real_query_count = 0
        self._shutdown_event = threading.Event()
        self._workers: list[threading.Thread] = []

        sys.stderr.write("FakeKataGo v1.18.2-fake analysis engine started\n")
        sys.stderr.flush()

    def emit(self, obj: dict[str, Any]) -> None:
        line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
        with self._stdout_lock:
            try:
                sys.stdout.write(line)
                sys.stdout.flush()
            except BrokenPipeError:
                self._shutdown_event.set()

    def _emit_stderr_flood(self, min_bytes: int) -> None:
        chunk = "FakeKataGo stderr flood diagnostic line " + "X" * 980 + "\n"
        chunk_len = len(chunk.encode("utf-8"))
        written = 0
        while written < min_bytes:
            try:
                sys.stderr.write(chunk)
                sys.stderr.flush()
            except BrokenPipeError:
                break
            written += chunk_len

    def _occupied_set(
        self,
        initial_stones: list[Any],
        moves: list[Any],
        turn_number: int,
    ) -> set[str]:
        occupied: set[str] = set()
        for item in initial_stones or []:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                mv = str(item[1]).upper()
                if mv != "PASS":
                    occupied.add(mv)
        for item in (moves or [])[:turn_number]:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                mv = str(item[1]).upper()
                if mv != "PASS":
                    occupied.add(mv)
        return occupied

    def _next_player(
        self,
        initial_player: str | None,
        moves: list[Any],
        turn_number: int,
    ) -> str:
        if turn_number > 0 and moves and turn_number <= len(moves):
            last_color = str(moves[turn_number - 1][0]).upper()
            return "W" if last_color == "B" else "B"
        start = (initial_player or "B").upper()
        if turn_number % 2 == 0:
            return start
        return "W" if start == "B" else "B"

    def _build_ownership(self, bx: int, by: int, turn_number: int) -> list[float]:
        if (
            self.fixture_override
            and bx == 19
            and by == 19
            and isinstance(self.fixture_override.get("ownership"), list)
            and len(self.fixture_override["ownership"]) == 361
        ):
            return list(self.fixture_override["ownership"])

        arr: list[float] = []
        shift = (turn_number % 5) * 0.01
        for y in range(by):
            for x in range(bx):
                nx = (x - (bx - 1) / 2.0) / max(1.0, bx / 2.0)
                ny = (y - (by - 1) / 2.0) / max(1.0, by / 2.0)
                val = max(-0.95, min(0.95, (nx * 0.72 - ny * 0.18) + shift))
                arr.append(round(val, 4))
        return arr

    def _generate_candidate_coords(
        self,
        bx: int,
        by: int,
        occupied: set[str],
        count: int,
    ) -> list[str]:
        preferred_19 = [
            "Q14", "R10", "D14", "K16", "O4", "F16", "C10", "K10", "Q16", "D4",
            "Q4", "D16", "R14", "C6", "F3", "O17", "G16", "M16", "G4", "M4",
        ]
        preferred_9 = ["E5", "C3", "G7", "C7", "G3", "E7", "E3", "C5", "G5", "D4", "F6"]
        candidates: list[str] = []
        seen: set[str] = set()

        seed = preferred_19 if (bx == 19 and by == 19) else (preferred_9 if (bx == 9 and by == 9) else [])
        for mv in seed:
            if mv not in occupied and mv not in seen:
                candidates.append(mv)
                seen.add(mv)
                if len(candidates) >= count:
                    return candidates

        for y in range(by):
            for x in range(bx):
                mv = coord_to_gtp(x, y, by)
                if mv not in occupied and mv not in seen:
                    candidates.append(mv)
                    seen.add(mv)
                    if len(candidates) >= count:
                        return candidates

        if not candidates:
            candidates.append("pass")
        return candidates

    def _build_response(
        self,
        req: dict[str, Any],
        turn_number: int,
        visits: int,
        is_during_search: bool,
        *,
        partial_poison: bool = False,
        target_large_bytes: int = 0,
    ) -> dict[str, Any]:
        qid = str(req.get("id", ""))
        bx = int(req.get("boardXSize", 19))
        by = int(req.get("boardYSize", 19))
        moves = req.get("moves") or []
        initial_stones = req.get("initialStones") or []
        initial_player = req.get("initialPlayer")
        include_ownership = bool(req.get("includeOwnership", False))
        include_pv_visits = bool(req.get("includePVVisits", False))

        occupied = self._occupied_set(initial_stones, moves, turn_number)
        next_player = self._next_player(initial_player, moves, turn_number)

        use_fixture = (
            not partial_poison
            and target_large_bytes <= 0
            and self.fixture_override is not None
            and bx == 19
            and by == 19
            and isinstance(self.fixture_override.get("moveInfos"), list)
        )

        if use_fixture:
            fixture_moves = []
            for m in self.fixture_override["moveInfos"]:
                mv_name = str(m["move"]).upper()
                if mv_name not in occupied:
                    entry = dict(m)
                    entry["order"] = len(fixture_moves)
                    if is_during_search:
                        entry["visits"] = max(1, int(entry.get("visits", 50) * 0.25))
                    fixture_moves.append(entry)
            if fixture_moves:
                root = dict(self.fixture_override.get("rootInfo") or {})
                root["currentPlayer"] = next_player
                root["visits"] = visits if is_during_search else max(visits, int(root.get("visits", visits)))
                resp: dict[str, Any] = {
                    "id": qid,
                    "turnNumber": turn_number,
                    "isDuringSearch": is_during_search,
                    "rootInfo": root,
                    "moveInfos": fixture_moves,
                }
                if include_ownership:
                    resp["ownership"] = self._build_ownership(bx, by, turn_number)
                return resp

        cand_coords = self._generate_candidate_coords(bx, by, occupied, 8)

        if partial_poison:
            root_wr = 0.1234
            root_lead = -19.75
        else:
            root_wr = 0.564 if next_player == "B" else 0.436
            root_lead = 2.4 if next_player == "B" else -2.4

        losses = [0.0, 0.5, 1.2, 2.2, 3.4, 8.5]
        priors = [0.34, 0.22, 0.15, 0.10, 0.07, 0.03]

        move_infos: list[dict[str, Any]] = []
        sign = 1.0 if next_player == "B" else -1.0
        for idx, mv in enumerate(cand_coords[: len(losses)]):
            loss = losses[idx]
            lead = round(root_lead - sign * loss, 3)
            wr = round(max(0.02, min(0.98, root_wr - sign * loss * 0.035)), 4)
            mv_visits = max(1, int(visits * max(0.05, 0.45 - idx * 0.07)))
            pv = [mv] + [c for c in cand_coords if c != mv][:7]
            info: dict[str, Any] = {
                "move": mv,
                "visits": mv_visits,
                "winrate": wr,
                "scoreLead": lead,
                "prior": priors[idx],
                "order": idx,
                "pv": pv,
            }
            if include_pv_visits:
                info["pvVisits"] = [max(1, mv_visits - i * 3) for i in range(len(pv))]
            move_infos.append(info)

        resp = {
            "id": qid,
            "turnNumber": turn_number,
            "isDuringSearch": is_during_search,
            "rootInfo": {
                "currentPlayer": next_player,
                "winrate": root_wr,
                "scoreLead": root_lead,
                "scoreStdev": 11.2,
                "visits": visits,
            },
            "moveInfos": move_infos,
        }

        if include_ownership:
            resp["ownership"] = self._build_ownership(bx, by, turn_number)

        if target_large_bytes > 0 and not is_during_search:
            all_coords = self._generate_candidate_coords(bx, by, occupied, bx * by)
            pad_idx = len(move_infos)
            current_size = len(json.dumps(resp, separators=(",", ":")).encode("utf-8"))
            long_pv = all_coords[: min(len(all_coords), 25)]
            while current_size < target_large_bytes:
                mv = all_coords[pad_idx % len(all_coords)]
                extra = {
                    "move": mv,
                    "visits": 1,
                    "winrate": round(root_wr - sign * 0.15, 6),
                    "scoreLead": round(root_lead - sign * 5.123456, 6),
                    "prior": 0.001234,
                    "order": pad_idx,
                    "lcb": round(root_wr - 0.18, 6),
                    "utility": round(sign * -0.25, 6),
                    "pv": long_pv,
                    "pvVisits": [1] * len(long_pv),
                }
                move_infos.append(extra)
                pad_idx += 1
                if pad_idx % 8 == 0:
                    current_size = len(json.dumps(resp, separators=(",", ":")).encode("utf-8"))

        return resp

    def _handle_query(
        self,
        req: dict[str, Any],
        cancel_event: threading.Event,
        real_query_seq: int,
    ) -> None:
        qid = str(req.get("id", ""))
        is_sys_warmup = qid.startswith("sys-")
        moves = req.get("moves") or []
        analyze_turns = req.get("analyzeTurns")
        if not analyze_turns:
            analyze_turns = [len(moves)]
        max_visits = int(req.get("maxVisits", 500))
        include_ownership = bool(req.get("includeOwnership", False))
        report_every = req.get("reportDuringSearchEvery")

        try:
            # 1. Crash triggers (never crash during sys-warmup unless prefix is crash-)
            should_crash = qid.startswith("crash-")
            if not is_sys_warmup and self.args.crash_on_query > 0 and real_query_seq == self.args.crash_on_query:
                should_crash = True
            if not is_sys_warmup and self.args.crash_once_file:
                marker = Path(self.args.crash_once_file)
                if not marker.exists():
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text("crashed\n", encoding="utf-8")
                    should_crash = True
            if should_crash:
                sys.stderr.write(f"FakeKataGo simulated crash on query {qid}\n")
                sys.stderr.flush()
                os._exit(42)

            # 2. Top-level error trigger (Pitfall #13: NO turnNumber)
            should_error = qid.startswith("error-") or (
                not is_sys_warmup
                and self.args.error_on_query > 0
                and real_query_seq == self.args.error_on_query
            )
            if should_error:
                self.emit({"id": qid, "error": f"Simulated KataGo error for {qid}"})
                return

            # 3. Hang trigger
            if qid.startswith("hang-"):
                cancel_event.wait(30.0)
                if cancel_event.is_set() and not self._shutdown_event.is_set():
                    for t in analyze_turns:
                        self.emit({"id": qid, "turnNumber": int(t), "noResults": True})
                return

            # 4. Stderr flood trigger (Pitfall #4: >= 128KB before response)
            if qid.startswith("stderr-flood-") or (not is_sys_warmup and self.args.stderr_flood_bytes > 0):
                self._emit_stderr_flood(max(131072, self.args.stderr_flood_bytes))

            # 5. Large payload target (Pitfall #1: 120KB-200KB single NDJSON line)
            target_large = 0
            if qid.startswith("large-"):
                target_large = max(145000, self.args.large_bytes)
            elif not is_sys_warmup and include_ownership and self.args.large_bytes > 0:
                target_large = self.args.large_bytes

            # 6. Slow / streaming behavior
            is_slow = qid.startswith(("slow-", "partial-", "stream-"))
            delay_sec = 0.0 if is_sys_warmup else self.args.delay_sec
            if is_slow and delay_sec <= 0.0:
                delay_sec = 0.25

            terminate_mode = self.args.terminate_mode.lower()
            if qid.startswith("partial-"):
                terminate_mode = "partial"

            for turn_raw in analyze_turns:
                turn_number = int(turn_raw)

                if self._shutdown_event.is_set():
                    return

                if cancel_event.is_set():
                    if terminate_mode == "partial":
                        self.emit(
                            self._build_response(
                                req,
                                turn_number,
                                visits=12,
                                is_during_search=False,
                                partial_poison=True,
                            )
                        )
                    else:
                        self.emit({"id": qid, "turnNumber": turn_number, "noResults": True})
                    continue

                if not is_sys_warmup and (report_every is not None or is_slow):
                    mid_visits = max(1, min(15, max_visits // 4))
                    self.emit(
                        self._build_response(
                            req,
                            turn_number,
                            visits=mid_visits,
                            is_during_search=True,
                        )
                    )

                if delay_sec > 0.0:
                    cancelled = cancel_event.wait(delay_sec)
                    if self._shutdown_event.is_set():
                        return
                    if cancelled:
                        if terminate_mode == "partial":
                            self.emit(
                                self._build_response(
                                    req,
                                    turn_number,
                                    visits=12,
                                    is_during_search=False,
                                    partial_poison=True,
                                )
                            )
                        else:
                            self.emit({"id": qid, "turnNumber": turn_number, "noResults": True})
                        continue

                self.emit(
                    self._build_response(
                        req,
                        turn_number,
                        visits=max_visits,
                        is_during_search=False,
                        target_large_bytes=target_large,
                    )
                )
        finally:
            with self._state_lock:
                self._active_events.pop(qid, None)

    def run(self) -> int:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                self.emit({"id": "", "error": f"Invalid JSON: {exc}"})
                continue

            action = req.get("action")
            if action == "query_version":
                self.emit(
                    {
                        "id": req.get("id", "sys-version"),
                        "action": "query_version",
                        "version": "1.18.2-fake",
                        "git_hash": "fake",
                    }
                )
                continue

            if action == "terminate":
                tid = str(req.get("terminateId", ""))
                with self._state_lock:
                    self._terminated_ids.add(tid)
                    ev = self._active_events.get(tid)
                if ev is not None:
                    ev.set()
                continue

            if action == "terminate_all":
                with self._state_lock:
                    events = list(self._active_events.values())
                    self._terminated_ids.update(self._active_events.keys())
                for ev in events:
                    ev.set()
                continue

            qid = str(req.get("id", f"q-{self._real_query_count + 1}"))
            cancel_event = threading.Event()
            with self._state_lock:
                if not qid.startswith("sys-"):
                    self._real_query_count += 1
                seq = self._real_query_count
                if qid in self._terminated_ids:
                    cancel_event.set()
                self._active_events[qid] = cancel_event

            worker = threading.Thread(
                target=self._handle_query,
                args=(req, cancel_event, seq),
                daemon=True,
            )
            self._workers.append(worker)
            worker.start()

        self._shutdown_event.set()
        with self._state_lock:
            for ev in self._active_events.values():
                ev.set()
        for w in self._workers:
            w.join(timeout=0.5)
        return 0


def main(argv: list[str] | None = None) -> int:
    return FakeKataGoWorker(_parse_args(argv)).run()


if __name__ == "__main__":
    raise SystemExit(main())
