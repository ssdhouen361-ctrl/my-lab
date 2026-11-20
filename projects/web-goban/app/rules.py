"""Go rules engine, SGF tree parser/serializer, position hashing, and safe file I/O.

Single Source of Truth for board legality, captures, ko, handicap rules,
canonical 7-element position hashing, and resilient iterative SGF parsing.

Pure standard library module (addresses Pitfalls #2, #6, #7, #9, #15, #16).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

from app.coords import (
    expand_sgf_coords,
    gtp_to_sgf,
    gtp_to_xy,
    handicap_stones_gtp,
    normalize_gtp,
    sgf_to_gtp,
    validate_board_size,
    xy_to_gtp,
)

VALID_COLORS = ("B", "W")
DEFAULT_MAX_SGF_BYTES = 1_048_576
DEFAULT_MAX_SGF_NODES = 5_000


class IllegalMoveError(Exception):
    """Raised when a Go move violates board rules or session state."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class SgfError(Exception):
    """Raised when SGF input is malformed or invalid."""


class SgfLimitError(SgfError):
    """Raised when SGF input exceeds byte size or node count limits."""


def opposite_color(color: str) -> str:
    if color == "B":
        return "W"
    if color == "W":
        return "B"
    raise ValueError(f"Invalid Go color: {color!r}")


def _validate_color(color: str) -> str:
    if color not in VALID_COLORS:
        raise IllegalMoveError("INVALID_COORD", f"無効な手番色です: {color}")
    return color


def compute_position_hash(
    board_size: int,
    stones: list[dict[str, str]] | list[tuple[str, str]] | Iterable[Any],
    next_player: str,
    ko_point: str | None,
    rules: str,
    komi: float,
    model_fingerprint: str,
) -> str:
    """Compute canonical 7-element SHA-256 hex digest for analysis caching (Pitfall #15).

    Elements: (board_size, stones, next_player, ko_point, rules, komi, model_fingerprint)
    """
    size = validate_board_size(board_size)
    if next_player not in VALID_COLORS:
        raise ValueError(f"Invalid next_player: {next_player!r}")

    canonical_stones: list[list[str]] = []
    for item in stones:
        if isinstance(item, dict):
            c = str(item["color"]).upper()
            m = normalize_gtp(str(item["move"]), size)
        else:
            c = str(item[0]).upper()
            m = normalize_gtp(str(item[1]), size)
        if c not in VALID_COLORS:
            raise ValueError(f"Invalid stone color: {c!r}")
        if m == "pass":
            raise ValueError("Pass cannot appear in board stone list")
        canonical_stones.append([c, m])
    canonical_stones.sort(key=lambda pair: (pair[1], pair[0]))

    ko_norm = normalize_gtp(ko_point, size) if ko_point else None
    if ko_norm == "pass":
        ko_norm = None

    payload = {
        "board_size": size,
        "stones": canonical_stones,
        "next_player": next_player,
        "ko_point": ko_norm,
        "rules": (rules or "japanese").strip().lower(),
        "komi": round(float(komi), 2),
        "model_fingerprint": model_fingerprint or "",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Atomically write text to path via temp file in same dir -> fsync -> os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def safe_resolve_under(base_dir: Path, relative_or_name: str) -> Path:
    """Resolve relative_or_name strictly under base_dir, preventing path traversal (Pitfall #7)."""
    if not isinstance(relative_or_name, str) or not relative_or_name.strip():
        raise ValueError("Path must be a non-empty string")
    if "\x00" in relative_or_name:
        raise ValueError("Null byte not allowed in path")
    if "\\" in relative_or_name:
        raise ValueError("Backslash not allowed in relative path")

    rel = Path(relative_or_name)
    if rel.is_absolute():
        raise ValueError(f"Absolute path not allowed: {relative_or_name!r}")
    if ".." in rel.parts:
        raise ValueError(f"Path traversal ('..') not allowed: {relative_or_name!r}")

    base_resolved = Path(base_dir).resolve()
    target_resolved = (base_resolved / rel).resolve()
    if not target_resolved.is_relative_to(base_resolved) or target_resolved == base_resolved:
        raise ValueError(f"Resolved path escapes base directory: {relative_or_name!r}")
    return target_resolved


@dataclass
class BoardState:
    """Immutable-style Go board snapshot with iterative flood-fill rule engine."""

    board_size: int
    grid: list[list[str | None]]
    next_player: str = "B"
    ko_point: tuple[int, int] | None = None
    captures: dict[str, int] = field(default_factory=lambda: {"B": 0, "W": 0})
    last_move: tuple[str, str] | None = None
    consecutive_passes: int = 0
    is_game_over: bool = False
    game_result: str | None = None

    @classmethod
    def empty(
        cls,
        board_size: int = 19,
        initial_stones: Iterable[tuple[str, str]] = (),
        initial_player: str = "B",
    ) -> BoardState:
        size = validate_board_size(board_size)
        _validate_color(initial_player)
        grid: list[list[str | None]] = [[None for _ in range(size)] for _ in range(size)]
        for color, gtp_move in initial_stones:
            _validate_color(color)
            xy = gtp_to_xy(gtp_move, size)
            if xy is None:
                continue
            x, y = xy
            grid[y][x] = color
        return cls(
            board_size=size,
            grid=grid,
            next_player=initial_player,
            ko_point=None,
            captures={"B": 0, "W": 0},
            last_move=None,
            consecutive_passes=0,
            is_game_over=False,
            game_result=None,
        )

    def clone(self) -> BoardState:
        return BoardState(
            board_size=self.board_size,
            grid=[row[:] for row in self.grid],
            next_player=self.next_player,
            ko_point=self.ko_point,
            captures={"B": self.captures["B"], "W": self.captures["W"]},
            last_move=self.last_move,
            consecutive_passes=self.consecutive_passes,
            is_game_over=self.is_game_over,
            game_result=self.game_result,
        )

    @staticmethod
    def _group_and_liberties(
        grid: list[list[str | None]],
        board_size: int,
        start_x: int,
        start_y: int,
    ) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
        """Iterative BFS returning (group_coords, liberty_coords)."""
        color = grid[start_y][start_x]
        if color is None:
            return set(), set()

        group: set[tuple[int, int]] = set()
        liberties: set[tuple[int, int]] = set()
        stack: list[tuple[int, int]] = [(start_x, start_y)]

        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in group:
                continue
            group.add((cx, cy))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < board_size and 0 <= ny < board_size:
                    cell = grid[ny][nx]
                    if cell is None:
                        liberties.add((nx, ny))
                    elif cell == color and (nx, ny) not in group:
                        stack.append((nx, ny))

        return group, liberties

    def play(
        self,
        color: str,
        gtp_move: str,
        *,
        allow_after_two_passes: bool = True,
    ) -> tuple[BoardState, list[str]]:
        """Validate and apply a move, returning (new_board, captured_gtp_list)."""
        _validate_color(color)
        if self.is_game_over and not allow_after_two_passes:
            raise IllegalMoveError("GAME_OVER", "対局はすでに終了しています。")

        try:
            xy = gtp_to_xy(gtp_move, self.board_size)
        except ValueError as exc:
            raise IllegalMoveError("INVALID_COORD", f"無効な座標です: {gtp_move}") from exc

        enemy = opposite_color(color)

        # Pass handling
        if xy is None:
            nxt = self.clone()
            nxt.ko_point = None
            nxt.next_player = enemy
            nxt.last_move = (color, "pass")
            nxt.consecutive_passes = self.consecutive_passes + 1
            if nxt.consecutive_passes >= 2 and not allow_after_two_passes:
                nxt.is_game_over = True
            else:
                nxt.is_game_over = False
                nxt.game_result = None
            return nxt, []

        x, y = xy
        norm_move = xy_to_gtp(x, y, self.board_size)

        if self.grid[y][x] is not None:
            raise IllegalMoveError(
                "ILLEGAL_OCCUPIED", f"{norm_move} にはすでに石が置かれています。"
            )

        if self.ko_point == (x, y):
            raise IllegalMoveError(
                "ILLEGAL_KO", f"{norm_move} はコウのため直後に取り返せません。"
            )

        nxt = self.clone()
        nxt.grid[y][x] = color

        # Check adjacent enemy groups in all 4 directions for capture
        captured_coords: set[tuple[int, int]] = set()
        visited_enemies: set[tuple[int, int]] = set()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.board_size and 0 <= ny < self.board_size:
                if nxt.grid[ny][nx] == enemy and (nx, ny) not in visited_enemies:
                    e_group, e_libs = self._group_and_liberties(
                        nxt.grid, self.board_size, nx, ny
                    )
                    visited_enemies.update(e_group)
                    if not e_libs:
                        captured_coords.update(e_group)

        for cx, cy in captured_coords:
            nxt.grid[cy][cx] = None

        # Suicide check after removing any captured enemy stones
        own_group, own_libs = self._group_and_liberties(nxt.grid, self.board_size, x, y)
        if not own_libs:
            raise IllegalMoveError(
                "ILLEGAL_SUICIDE", f"{norm_move} は自殺手のため着手できません。"
            )

        # Single-ko detection: 1 enemy stone captured, own group is 1 stone with 1 liberty
        new_ko: tuple[int, int] | None = None
        if len(captured_coords) == 1 and len(own_group) == 1 and len(own_libs) == 1:
            cap_pt = next(iter(captured_coords))
            if cap_pt in own_libs:
                new_ko = cap_pt

        captured_gtp = sorted(
            xy_to_gtp(cx, cy, self.board_size) for cx, cy in captured_coords
        )
        nxt.captures[color] += len(captured_gtp)
        nxt.ko_point = new_ko
        nxt.next_player = enemy
        nxt.last_move = (color, norm_move)
        nxt.consecutive_passes = 0
        nxt.is_game_over = False
        nxt.game_result = None
        return nxt, captured_gtp

    def ko_point_gtp(self) -> str | None:
        if self.ko_point is None:
            return None
        return xy_to_gtp(self.ko_point[0], self.ko_point[1], self.board_size)

    def stones_list(self) -> list[dict[str, str]]:
        """Return deterministically sorted list of stones on the board."""
        stones: list[dict[str, str]] = []
        for y in range(self.board_size):
            for x in range(self.board_size):
                cell = self.grid[y][x]
                if cell is not None:
                    stones.append(
                        {"color": cell, "move": xy_to_gtp(x, y, self.board_size)}
                    )
        stones.sort(key=lambda s: (s["move"], s["color"]))
        return stones

    def to_position_dict(
        self,
        rules: str,
        komi: float,
        model_fingerprint: str = "",
    ) -> dict[str, Any]:
        stones = self.stones_list()
        ko_gtp = self.ko_point_gtp()
        pos_hash = compute_position_hash(
            board_size=self.board_size,
            stones=stones,
            next_player=self.next_player,
            ko_point=ko_gtp,
            rules=rules,
            komi=komi,
            model_fingerprint=model_fingerprint,
        )
        return {
            "board_size": self.board_size,
            "stones": stones,
            "next_player": self.next_player,
            "ko_point": ko_gtp,
            "captures": {"B": self.captures["B"], "W": self.captures["W"]},
            "last_move": (
                {"color": self.last_move[0], "move": self.last_move[1]}
                if self.last_move
                else None
            ),
            "consecutive_passes": self.consecutive_passes,
            "is_game_over": self.is_game_over,
            "game_result": self.game_result,
            "rules": rules,
            "komi": komi,
            "position_hash": pos_hash,
        }


@dataclass
class GameNode:
    """Single node in an SGF game tree."""

    node_id: str
    parent_id: str | None
    move_number: int
    color: str | None
    move: str | None
    captured: list[str]
    captures_total: dict[str, int]
    comment: str
    children_ids: list[str]
    board: BoardState

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "move_number": self.move_number,
            "color": self.color,
            "move": self.move,
            "captured": list(self.captured),
            "captures_total": {
                "B": self.captures_total["B"],
                "W": self.captures_total["W"],
            },
            "comment": self.comment,
            "children_ids": list(self.children_ids),
        }


def _escape_sgf(text: str) -> str:
    return text.replace("\\", "\\\\").replace("]", "\\]")


def _format_komi(komi: float) -> str:
    val = round(float(komi), 2)
    if val.is_integer():
        return str(int(val))
    return f"{val:g}"


def _normalize_rules_name(raw: str | None) -> str:
    if not raw:
        return "japanese"
    lowered = raw.strip().lower()
    if lowered in {"jp", "japan", "japanese", "nihon"}:
        return "japanese"
    if lowered in {"cn", "china", "chinese"}:
        return "chinese"
    if lowered in {"kr", "korea", "korean"}:
        return "korean"
    if lowered in {"aga", "nz", "tromp-taylor", "stone-scoring"}:
        return lowered
    return lowered


class GameTree:
    """Full branching Go game tree with mainline tracking and iterative SGF serialization."""

    def __init__(
        self,
        board_size: int = 19,
        komi: float | None = None,
        handicap: int = 0,
        rules: str = "japanese",
        initial_stones: list[tuple[str, str]] | None = None,
        initial_player: str | None = None,
        mode: str = "review",
        metadata: dict[str, str] | None = None,
    ) -> None:
        self.board_size: int = validate_board_size(board_size)
        self.handicap: int = int(handicap)
        if self.handicap < 0:
            raise ValueError(f"handicap must be >= 0, got {self.handicap}")
        self.rules: str = _normalize_rules_name(rules)
        self.mode: str = mode if mode in {"review", "play"} else "review"
        self.metadata: dict[str, str] = dict(metadata or {})

        # Pitfall #6: automatic handicap stones, komi=0.5, initial_player="W"
        stones_in: list[tuple[str, str]] = []
        if initial_stones:
            seen_pts: set[str] = set()
            for col, mv in initial_stones:
                _validate_color(col)
                norm = normalize_gtp(mv, self.board_size)
                if norm != "pass" and norm not in seen_pts:
                    seen_pts.add(norm)
                    stones_in.append((col, norm))
        elif self.handicap >= 2:
            for gtp_pt in handicap_stones_gtp(self.board_size, self.handicap):
                stones_in.append(("B", gtp_pt))

        self.initial_stones: list[tuple[str, str]] = stones_in

        if initial_player is not None:
            self.initial_player: str = _validate_color(initial_player)
        else:
            self.initial_player = "W" if self.handicap >= 2 else "B"

        if komi is not None:
            self.komi: float = float(komi)
        else:
            self.komi = 0.5 if self.handicap >= 2 else 6.5

        root_board = BoardState.empty(
            board_size=self.board_size,
            initial_stones=self.initial_stones,
            initial_player=self.initial_player,
        )
        root_node = GameNode(
            node_id="n-0000",
            parent_id=None,
            move_number=0,
            color=None,
            move=None,
            captured=[],
            captures_total={"B": 0, "W": 0},
            comment="",
            children_ids=[],
            board=root_board,
        )

        self.nodes: dict[str, GameNode] = {"n-0000": root_node}
        self.root_id: str = "n-0000"
        self.latest_node_id: str = "n-0000"
        self.mainline_ids: list[str] = ["n-0000"]
        self.warnings: list[str] = []
        self._next_seq: int = 1

    def _allocate_node_id(self) -> str:
        nid = f"n-{self._next_seq:04d}"
        self._next_seq += 1
        return nid

    def get_node(self, node_id: str) -> GameNode:
        node = self.nodes.get(node_id)
        if node is None:
            raise IllegalMoveError("INVALID_NODE", f"指定された局面が見つかりません: {node_id}")
        return node

    def play_move(
        self,
        parent_node_id: str,
        gtp_move: str,
        color: str | None = None,
    ) -> GameNode:
        """Play a move under parent_node_id, validating Go rules and updating tree."""
        parent = self.get_node(parent_node_id)
        allow_after_two = self.mode != "play"
        if not allow_after_two and parent.board.is_game_over:
            raise IllegalMoveError("GAME_OVER", "対局はすでに終了しています。")

        move_color = _validate_color(color) if color is not None else parent.board.next_player

        try:
            norm_move = normalize_gtp(gtp_move, self.board_size)
        except ValueError as exc:
            raise IllegalMoveError("INVALID_COORD", f"無効な座標です: {gtp_move}") from exc

        # Reuse identical sibling child if it already exists
        for cid in parent.children_ids:
            existing = self.nodes[cid]
            if existing.color == move_color and existing.move == norm_move:
                return existing

        new_board, captured = parent.board.play(
            move_color,
            norm_move,
            allow_after_two_passes=allow_after_two,
        )
        nid = self._allocate_node_id()
        child = GameNode(
            node_id=nid,
            parent_id=parent.node_id,
            move_number=parent.move_number + 1,
            color=move_color,
            move=norm_move,
            captured=captured,
            captures_total={
                "B": new_board.captures["B"],
                "W": new_board.captures["W"],
            },
            comment="",
            children_ids=[],
            board=new_board,
        )
        self.nodes[nid] = child
        parent.children_ids.append(nid)

        if parent.node_id == self.mainline_ids[-1]:
            self.mainline_ids.append(nid)
            self.latest_node_id = nid

        return child

    def get_node_path(self, node_id: str) -> list[GameNode]:
        """Iteratively trace path from root to node_id."""
        cur = self.get_node(node_id)
        rev: list[GameNode] = []
        seen: set[str] = set()
        while True:
            if cur.node_id in seen:
                raise SgfError("Cycle detected in GameTree")
            seen.add(cur.node_id)
            rev.append(cur)
            if cur.parent_id is None:
                break
            cur = self.get_node(cur.parent_id)
        rev.reverse()
        return rev

    def get_moves_path(
        self, node_id: str
    ) -> tuple[list[list[str]], str, list[list[str]]]:
        """Return (initial_stones_pairs, initial_player, moves_pairs) for KataGo queries."""
        path = self.get_node_path(node_id)
        init_pairs = [[c, m] for c, m in self.initial_stones]
        move_pairs = [
            [n.color, n.move]
            for n in path[1:]
            if n.color is not None and n.move is not None
        ]
        return init_pairs, self.initial_player, move_pairs

    def position_hash(self, node_id: str, model_fingerprint: str = "") -> str:
        node = self.get_node(node_id)
        return compute_position_hash(
            board_size=self.board_size,
            stones=node.board.stones_list(),
            next_player=node.board.next_player,
            ko_point=node.board.ko_point_gtp(),
            rules=self.rules,
            komi=self.komi,
            model_fingerprint=model_fingerprint,
        )

    def get_branch_info(self, node_id: str) -> dict[str, Any]:
        """Compute branch divergence info relative to mainline_ids."""
        path = self.get_node_path(node_id)
        mainline_index = {nid: idx for idx, nid in enumerate(self.mainline_ids)}

        if node_id in mainline_index:
            idx = mainline_index[node_id]
            next_main = (
                self.mainline_ids[idx + 1]
                if idx + 1 < len(self.mainline_ids)
                else None
            )
            return {
                "is_branch": False,
                "branch_depth": 0,
                "divergence_node_id": None,
                "divergence_move_number": 0,
                "mainline_next_node_id": next_main,
            }

        div_node = path[0]
        for node in path:
            if node.node_id in mainline_index:
                div_node = node
            else:
                break
        div_idx = mainline_index[div_node.node_id]
        next_main = (
            self.mainline_ids[div_idx + 1]
            if div_idx + 1 < len(self.mainline_ids)
            else None
        )
        return {
            "is_branch": True,
            "branch_depth": path[-1].move_number - div_node.move_number,
            "divergence_node_id": div_node.node_id,
            "divergence_move_number": div_node.move_number,
            "mainline_next_node_id": next_main,
        }

    def rebuild_mainline(self) -> None:
        """Rebuild mainline_ids iteratively by following children_ids[0] from root."""
        line: list[str] = [self.root_id]
        cur = self.nodes[self.root_id]
        while cur.children_ids:
            nxt_id = cur.children_ids[0]
            line.append(nxt_id)
            cur = self.nodes[nxt_id]
        self.mainline_ids = line
        self.latest_node_id = line[-1]

    def to_sgf(self) -> str:
        """Iteratively serialize the entire tree to standards-compliant SGF FF[4]."""
        root = self.nodes[self.root_id]
        parts: list[str] = ["(;"]
        parts.append("FF[4]GM[1]CA[UTF-8]")
        parts.append(f"SZ[{self.board_size}]")
        parts.append(f"KM[{_format_komi(self.komi)}]")
        parts.append(f"RU[{_escape_sgf(self.rules)}]")

        if self.handicap >= 2:
            parts.append(f"HA[{self.handicap}]")
        if self.initial_player != "B" or self.handicap >= 2:
            parts.append(f"PL[{self.initial_player}]")

        ab_coords = [
            gtp_to_sgf(m, self.board_size)
            for c, m in self.initial_stones
            if c == "B"
        ]
        aw_coords = [
            gtp_to_sgf(m, self.board_size)
            for c, m in self.initial_stones
            if c == "W"
        ]
        if ab_coords:
            parts.append("AB" + "".join(f"[{c}]" for c in ab_coords))
        if aw_coords:
            parts.append("AW" + "".join(f"[{c}]" for c in aw_coords))

        for key in ("GN", "DT", "PB", "PW", "RE", "BR", "WR", "PC", "EV"):
            val = self.metadata.get(key)
            if val:
                parts.append(f"{key}[{_escape_sgf(str(val))}]")

        for key, val in sorted(self.metadata.items()):
            if key not in {"GN", "DT", "PB", "PW", "RE", "BR", "WR", "PC", "EV"} and val:
                if key.isalpha() and key.isupper():
                    parts.append(f"{key}[{_escape_sgf(str(val))}]")

        if root.comment:
            parts.append(f"C[{_escape_sgf(root.comment)}]")

        # Iterative traversal stack: items are either ("token", str) or ("node", node_id)
        stack: list[tuple[str, str]] = []

        def _push_children(node: GameNode) -> None:
            if len(node.children_ids) == 1:
                stack.append(("node", node.children_ids[0]))
            elif len(node.children_ids) > 1:
                for cid in reversed(node.children_ids):
                    stack.append(("token", ")"))
                    stack.append(("node", cid))
                    stack.append(("token", "("))

        _push_children(root)

        while stack:
            kind, value = stack.pop()
            if kind == "token":
                parts.append(value)
                continue
            node = self.nodes[value]
            parts.append(";")
            if node.color and node.move is not None:
                sgf_pt = gtp_to_sgf(node.move, self.board_size)
                parts.append(f"{node.color}[{sgf_pt}]")
            if node.comment:
                parts.append(f"C[{_escape_sgf(node.comment)}]")
            _push_children(node)

        parts.append(")")
        return "".join(parts)


# ---------------------------------------------------------------------------
# Iterative SGF Parser (Pitfall #9)
# ---------------------------------------------------------------------------

_CA_REGEX = re.compile(rb"CA\[([^\]]{1,32})\]")

_ENCODING_ALIASES = {
    "utf8": "utf-8",
    "utf-8": "utf-8",
    "shift_jis": "cp932",
    "shift-jis": "cp932",
    "sjis": "cp932",
    "ms932": "cp932",
    "cp932": "cp932",
    "gbk": "gb18030",
    "gb2312": "gb18030",
    "gb18030": "gb18030",
    "big5": "big5",
    "iso-8859-1": "latin-1",
    "latin1": "latin-1",
    "latin-1": "latin-1",
    "ascii": "utf-8",
}


def _decode_sgf_bytes(raw: bytes) -> str:
    candidates: list[str] = []
    match = _CA_REGEX.search(raw[:4096])
    if match:
        hint_raw = match.group(1).decode("ascii", errors="ignore").strip().lower()
        mapped = _ENCODING_ALIASES.get(hint_raw, hint_raw)
        if mapped:
            candidates.append(mapped)

    for fallback in ("utf-8-sig", "utf-8", "cp932", "gb18030", "latin-1"):
        if fallback not in candidates:
            candidates.append(fallback)

    for enc in candidates:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


@dataclass
class _RawSgfNode:
    props: dict[str, list[str]] = field(default_factory=dict)
    children: list[_RawSgfNode] = field(default_factory=list)


def _parse_sgf_ast_iterative(text: str, max_nodes: int) -> _RawSgfNode:
    """Iterative stack-based SGF FF[4] parser returning the root _RawSgfNode."""
    n = len(text)
    pos = text.find("(")
    if pos == -1:
        raise SgfError("有効な SGF ツリー ('(') が見つかりません。")

    root_node: _RawSgfNode | None = None
    # Stack tracks the parent node at the entry of each '(' branch
    branch_stack: list[_RawSgfNode | None] = []
    current_parent: _RawSgfNode | None = None
    node_count = 0
    started = False

    while pos < n:
        ch = text[pos]
        if ch.isspace():
            pos += 1
            continue

        if ch == "(":
            branch_stack.append(current_parent)
            started = True
            pos += 1
            continue

        if ch == ")":
            if not branch_stack:
                raise SgfError("SGF の閉じ括弧 ')' が多すぎます。")
            current_parent = branch_stack.pop()
            pos += 1
            # Stop after finishing the first top-level GameTree
            if not branch_stack and started:
                break
            continue

        if ch == ";":
            if not branch_stack:
                raise SgfError("SGF ノード ';' が括弧外に存在します。")
            node_count += 1
            if node_count > max_nodes:
                raise SgfLimitError(
                    f"SGF ノード数が上限（{max_nodes}）を超えています。"
                )
            pos += 1
            raw_node = _RawSgfNode()

            # Parse zero or more properties: IDENT [val1][val2]...
            while pos < n:
                while pos < n and text[pos].isspace():
                    pos += 1
                if pos >= n or text[pos] in ";()":
                    break

                # Read property identifier (letters; tolerate lowercase in wild SGFs)
                ident_start = pos
                while pos < n and text[pos].isalpha():
                    pos += 1
                ident = text[ident_start:pos]
                if not ident:
                    # Skip stray unrecognized character safely
                    pos += 1
                    continue
                ident_upper = "".join(c for c in ident if c.isupper()) or ident.upper()

                values: list[str] = []
                while pos < n:
                    while pos < n and text[pos].isspace():
                        pos += 1
                    if pos >= n or text[pos] != "[":
                        break
                    pos += 1  # consume '['
                    buf: list[str] = []
                    closed = False
                    while pos < n:
                        c = text[pos]
                        if c == "\\":
                            pos += 1
                            if pos < n:
                                nxt_c = text[pos]
                                # SGF FF[4] soft line break
                                if nxt_c == "\r":
                                    pos += 1
                                    if pos < n and text[pos] == "\n":
                                        pos += 1
                                elif nxt_c == "\n":
                                    pos += 1
                                    if pos < n and text[pos] == "\r":
                                        pos += 1
                                else:
                                    buf.append(nxt_c)
                                    pos += 1
                            continue
                        if c == "]":
                            pos += 1
                            closed = True
                            break
                        buf.append(c)
                        pos += 1
                    if not closed:
                        raise SgfError("SGF プロパティ値 ']' が閉じられていません。")
                    values.append("".join(buf))

                if values:
                    raw_node.props.setdefault(ident_upper, []).extend(values)

            if root_node is None:
                root_node = raw_node
            elif current_parent is not None:
                current_parent.children.append(raw_node)
            else:
                # Multiple root nodes in malformed SGF: attach under root
                root_node.children.append(raw_node)
            current_parent = raw_node
            continue

        # Unexpected character outside property value: advance safely
        pos += 1

    if root_node is None:
        raise SgfError("SGF にノードが存在しません。")
    return root_node


def _parse_sz(raw_sz: str | None) -> int:
    if not raw_sz:
        return 19
    s = raw_sz.strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) != 2 or parts[0].strip() != parts[1].strip():
            raise SgfError(f"非正方形の盤サイズ SZ[{raw_sz}] は未対応です。")
        s = parts[0].strip()
    try:
        return validate_board_size(int(s))
    except ValueError as exc:
        raise SgfError(f"無効な盤サイズ SZ[{raw_sz}]: {exc}") from exc


def parse_sgf(
    raw_data: bytes | str,
    *,
    max_bytes: int = DEFAULT_MAX_SGF_BYTES,
    max_nodes: int = DEFAULT_MAX_SGF_NODES,
    mode: str = "review",
) -> GameTree:
    """Parse raw SGF bytes or string safely into a validated GameTree.

    Guarantees:
      - Strict byte size (1MB default) and node count (5,000 default) limits
      - Automatic encoding detection (CA header -> UTF-8 -> CP932 -> GB18030 -> latin-1)
      - Non-recursive (iterative) parsing and replay
      - Handicap normalization (HA>=2 with omitted KM -> komi=0.5, PL=W)
      - Illegal move resilience (skips offending branch with warning instead of crashing)
    """
    if isinstance(raw_data, bytes):
        if len(raw_data) > max_bytes:
            raise SgfLimitError(
                f"SGF ファイルサイズが上限（{max_bytes} bytes）を超えています。"
            )
        text = _decode_sgf_bytes(raw_data)
    elif isinstance(raw_data, str):
        if len(raw_data.encode("utf-8")) > max_bytes:
            raise SgfLimitError(
                f"SGF データサイズが上限（{max_bytes} bytes）を超えています。"
            )
        text = raw_data
    else:
        raise SgfError(f"SGF 入力は bytes または str である必要があります: {type(raw_data).__name__}")

    ast_root = _parse_sgf_ast_iterative(text, max_nodes=max_nodes)
    props = ast_root.props

    board_size = _parse_sz(props.get("SZ", [None])[0])

    handicap = 0
    if "HA" in props and props["HA"]:
        try:
            handicap = max(0, int(props["HA"][0].strip()))
        except ValueError:
            handicap = 0

    komi: float | None = None
    if "KM" in props and props["KM"]:
        raw_km = props["KM"][0].strip()
        if raw_km:
            try:
                komi = float(raw_km)
            except ValueError:
                komi = None

    rules = _normalize_rules_name(props.get("RU", ["japanese"])[0])

    initial_player: str | None = None
    if "PL" in props and props["PL"]:
        pl_raw = props["PL"][0].strip().upper()
        if pl_raw in VALID_COLORS:
            initial_player = pl_raw

    # Expand setup stones AB / AW / AE (supports compressed rectangles aa:cc)
    setup_map: dict[tuple[int, int], str] = {}
    warnings: list[str] = []

    for prop_key, color in (("AB", "B"), ("AW", "W")):
        for val in props.get(prop_key, []):
            try:
                for xy in expand_sgf_coords(val, board_size):
                    setup_map[xy] = color
            except ValueError as exc:
                warnings.append(f"初期配置 {prop_key}[{val}] を無視しました: {exc}")

    for val in props.get("AE", []):
        try:
            for xy in expand_sgf_coords(val, board_size):
                setup_map.pop(xy, None)
        except ValueError as exc:
            warnings.append(f"初期消去 AE[{val}] を無視しました: {exc}")

    initial_stones: list[tuple[str, str]] = [
        (color, xy_to_gtp(x, y, board_size))
        for (x, y), color in sorted(setup_map.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    ]

    metadata: dict[str, str] = {}
    for meta_key in ("PB", "PW", "RE", "DT", "GN", "BR", "WR", "PC", "EV", "TM", "OT"):
        if meta_key in props and props[meta_key]:
            metadata[meta_key] = props[meta_key][0]

    tree = GameTree(
        board_size=board_size,
        komi=komi,
        handicap=handicap,
        rules=rules,
        initial_stones=initial_stones,
        initial_player=initial_player,
        mode=mode,
        metadata=metadata,
    )
    tree.warnings.extend(warnings)

    if "C" in props and props["C"]:
        tree.nodes[tree.root_id].comment = "\n".join(props["C"])

    # Handle rare SGFs that include a move directly on the root node
    start_parent_id = tree.root_id
    for mv_color in ("B", "W"):
        if mv_color in props and props[mv_color]:
            raw_mv = props[mv_color][0]
            try:
                gtp = sgf_to_gtp(raw_mv, board_size)
                child = tree.play_move(start_parent_id, gtp, color=mv_color)
                start_parent_id = child.node_id
            except (IllegalMoveError, ValueError) as exc:
                tree.warnings.append(
                    f"ルートノードの手 ({mv_color}[{raw_mv}]) は非法手のためスキップしました: {exc}"
                )
            break

    # Iterative DFS replay of AST children into GameTree
    replay_stack: list[tuple[str, _RawSgfNode]] = []
    for ast_child in reversed(ast_root.children):
        replay_stack.append((start_parent_id, ast_child))

    while replay_stack:
        parent_id, ast_node = replay_stack.pop()
        nprops = ast_node.props

        move_color: str | None = None
        raw_val: str | None = None
        if "B" in nprops and nprops["B"]:
            move_color = "B"
            raw_val = nprops["B"][0]
        elif "W" in nprops and nprops["W"]:
            move_color = "W"
            raw_val = nprops["W"][0]

        if move_color is None:
            # Comment-only or non-move node: merge comment onto parent & continue children
            if "C" in nprops and nprops["C"]:
                parent_node = tree.get_node(parent_id)
                extra = "\n".join(nprops["C"])
                parent_node.comment = (
                    f"{parent_node.comment}\n{extra}" if parent_node.comment else extra
                )
            for ast_child in reversed(ast_node.children):
                replay_stack.append((parent_id, ast_child))
            continue

        try:
            gtp_mv = sgf_to_gtp(raw_val or "", board_size)
            played = tree.play_move(parent_id, gtp_mv, color=move_color)
        except (IllegalMoveError, ValueError) as exc:
            parent_num = tree.get_node(parent_id).move_number
            tree.warnings.append(
                f"{parent_num + 1}手目 ({move_color}[{raw_val}]) は非法手のため以降をスキップしました: {exc}"
            )
            # Skip offending move AND its descendants on this branch
            continue

        if "C" in nprops and nprops["C"]:
            played.comment = "\n".join(nprops["C"])

        for ast_child in reversed(ast_node.children):
            replay_stack.append((played.node_id, ast_child))

    tree.rebuild_mainline()
    return tree


__all__ = [
    "IllegalMoveError",
    "SgfError",
    "SgfLimitError",
    "opposite_color",
    "compute_position_hash",
    "atomic_write_text",
    "safe_resolve_under",
    "BoardState",
    "GameNode",
    "GameTree",
    "parse_sgf",
    "DEFAULT_MAX_SGF_BYTES",
    "DEFAULT_MAX_SGF_NODES",
]
