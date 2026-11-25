"""Go board rules, move validation, tree node structure and SGF handling."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

Point = Tuple[int, int] # (col 0-18, row 0-18) where (0,0) is bottom-left A1

GTP_COLS = "ABCDEFGHJKLMNOPQRST"

def point_to_gtp(pt: Point) -> str:
    c, r = pt
    return f"{GTP_COLS[c]}{r + 1}"

def gtp_to_point(gtp: str) -> Point:
    gtp = gtp.upper().strip()
    c = GTP_COLS.index(gtp[0])
    r = int(gtp[1:]) - 1
    return (c, r)

@dataclass
class BoardState:
    size: int = 19
    grid: Dict[Point, str] = field(default_factory=dict) # pt -> 'B' or 'W'
    ko_point: Optional[Point] = None
    captures_black: int = 0
    captures_white: int = 0

    def copy(self) -> BoardState:
        return BoardState(
            size=self.size,
            grid=dict(self.grid),
            ko_point=self.ko_point,
            captures_black=self.captures_black,
            captures_white=self.captures_white
        )

    def get_adjacent(self, pt: Point) -> List[Point]:
        c, r = pt
        adj = []
        for dc, dr in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nc, nr = c + dc, r + dr
            if 0 <= nc < self.size and 0 <= nr < self.size:
                adj.append((nc, nr))
        return adj

    def get_group(self, pt: Point) -> Tuple[Set[Point], Set[Point]]:
        color = self.grid.get(pt)
        if not color:
            return set(), set()
        group = {pt}
        liberties = set()
        queue = [pt]
        while queue:
            curr = queue.pop()
            for neighbor in self.get_adjacent(curr):
                if neighbor not in self.grid:
                    liberties.add(neighbor)
                elif self.grid[neighbor] == color and neighbor not in group:
                    group.add(neighbor)
                    queue.append(neighbor)
        return group, liberties

    def play_move(self, pt: Optional[Point], color: str) -> Tuple[bool, str, List[Point]]:
        """Play a move. Returns (success, message, captured_stones). pt=None is PASS."""
        if pt is None:
            self.ko_point = None
            return True, "pass", []

        if pt in self.grid:
            return False, "Point already occupied", []
        if pt == self.ko_point:
            return False, "Ko violation", []

        opp_color = 'W' if color == 'B' else 'B'
        temp_grid = dict(self.grid)
        temp_grid[pt] = color

        captured: List[Point] = []
        for neighbor in self.get_adjacent(pt):
            if temp_grid.get(neighbor) == opp_color:
                grp, libs = self._get_group_with_grid(neighbor, opp_color, temp_grid)
                if not libs:
                    for s in grp:
                        if s in temp_grid:
                            del temp_grid[s]
                            captured.append(s)

        my_grp, my_libs = self._get_group_with_grid(pt, color, temp_grid)
        if not my_libs:
            return False, "Suicide move is illegal", []

        self.grid = temp_grid
        if color == 'B':
            self.captures_black += len(captured)
        else:
            self.captures_white += len(captured)

        # Ko detection: captured exactly 1 stone and playing stone has 1 liberty
        if len(captured) == 1 and len(my_libs) == 1 and len(my_grp) == 1:
            self.ko_point = captured[0]
        else:
            self.ko_point = None

        return True, "ok", captured

    def _get_group_with_grid(self, pt: Point, color: str, grid: Dict[Point, str]) -> Tuple[Set[Point], Set[Point]]:
        group = {pt}
        liberties = set()
        queue = [pt]
        while queue:
            curr = queue.pop()
            for neighbor in self.get_adjacent(curr):
                if neighbor not in grid:
                    liberties.add(neighbor)
                elif grid[neighbor] == color and neighbor not in group:
                    group.add(neighbor)
                    queue.append(neighbor)
        return group, liberties

@dataclass
class TreeNode:
    node_id: str
    parent_id: Optional[str] = None
    move: Optional[Point] = None # None if root or pass
    color: str = 'B'
    comment: str = ""
    board_state: BoardState = field(default_factory=BoardState)
    children: List[str] = field(default_factory=list) # List of node_id
