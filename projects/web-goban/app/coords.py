"""Coordinate conversion & validation (Single Source of Truth).

Centralizes all conversions between:
  - Internal (x, y): 0-indexed, origin at top-left (x=0 left col A, y=0 top row N)
  - GTP strings:     "A1".."T19" (column 'I' omitted, bottom-left origin) and "pass"
  - SGF strings:     "aa".."ss" (includes 'i', top-left origin), "" / "tt" for pass,
                     and compressed rectangles "aa:cc"
  - Ownership index: row-major y * board_size + x (matching KataGo output order)

Pure standard library module (addresses Pitfalls #2 and #10).
"""

from __future__ import annotations

GTP_COLS = "ABCDEFGHJKLMNOPQRST"
SUPPORTED_SIZES = (9, 13, 19)

_MIN_BOARD_SIZE = 2
_MAX_BOARD_SIZE = 19


def _check_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {type(value).__name__}")
    return value


def validate_board_size(board_size: int) -> int:
    """Validate that board_size is an integer in [2, 19]."""
    size = _check_int(board_size, "board_size")
    if size < _MIN_BOARD_SIZE or size > _MAX_BOARD_SIZE:
        raise ValueError(
            f"Unsupported board_size={size}; expected integer between "
            f"{_MIN_BOARD_SIZE} and {_MAX_BOARD_SIZE}"
        )
    return size


def _validate_xy(x: int, y: int, board_size: int) -> tuple[int, int, int]:
    size = validate_board_size(board_size)
    xi = _check_int(x, "x")
    yi = _check_int(y, "y")
    if not (0 <= xi < size and 0 <= yi < size):
        raise ValueError(
            f"Coordinates ({xi}, {yi}) out of bounds for {size}x{size} board"
        )
    return xi, yi, size


def is_gtp_pass(gtp: str | None) -> bool:
    """Return True if a GTP move string represents a pass."""
    if gtp is None:
        return False
    return isinstance(gtp, str) and gtp.strip().lower() == "pass"


def is_sgf_pass(sgf_coord: str | None, board_size: int = 19) -> bool:
    """Return True if an SGF coordinate string represents a pass."""
    size = validate_board_size(board_size)
    if sgf_coord is None or not isinstance(sgf_coord, str):
        return False
    s = sgf_coord.strip()
    if s == "":
        return True
    if s == "tt" and size <= 19:
        return True
    return False


def is_pass(move: str | None, board_size: int = 19) -> bool:
    """Return True if move is a pass in either GTP ('pass'/'PASS') or SGF (''/'tt')."""
    size = validate_board_size(board_size)
    if move is None or not isinstance(move, str):
        return False
    s = move.strip()
    if s == "" or s.lower() == "pass":
        return True
    if s == "tt" and size <= 19:
        return True
    return False


def xy_to_gtp(x: int, y: int, board_size: int) -> str:
    """Convert internal (x, y) [top-left origin] to GTP string (e.g. 'D4', 'A19')."""
    xi, yi, size = _validate_xy(x, y, board_size)
    col = GTP_COLS[xi]
    row = size - yi
    return f"{col}{row}"


def gtp_to_xy(gtp: str, board_size: int) -> tuple[int, int] | None:
    """Convert GTP move string to internal (x, y), or None for 'pass'.

    Explicitly rejects column 'I', out-of-range coordinates, leading zeros,
    and malformed strings.
    """
    size = validate_board_size(board_size)
    if not isinstance(gtp, str):
        raise ValueError(f"GTP move must be a string, got {type(gtp).__name__}")
    s = gtp.strip().upper()
    if not s:
        raise ValueError("Empty GTP move string")
    if s == "PASS":
        return None
    if len(s) < 2 or len(s) > 3:
        raise ValueError(f"Malformed GTP coordinate: {gtp!r}")

    col_char = s[0]
    row_str = s[1:]
    valid_cols = GTP_COLS[:size]
    if col_char not in valid_cols:
        raise ValueError(
            f"Invalid GTP column {col_char!r} for {size}x{size} board (input={gtp!r})"
        )
    if not row_str.isascii() or not row_str.isdigit() or row_str.startswith("0"):
        raise ValueError(f"Invalid GTP row {row_str!r} in {gtp!r}")

    row = int(row_str)
    if row < 1 or row > size:
        raise ValueError(
            f"GTP row {row} out of range 1..{size} (input={gtp!r})"
        )

    x = valid_cols.index(col_char)
    y = size - row
    return (x, y)


def normalize_gtp(gtp: str, board_size: int) -> str:
    """Validate and normalize a GTP move to canonical uppercase coord or 'pass'."""
    xy = gtp_to_xy(gtp, board_size)
    if xy is None:
        return "pass"
    return xy_to_gtp(xy[0], xy[1], board_size)


def xy_to_sgf(x: int, y: int, board_size: int) -> str:
    """Convert internal (x, y) to SGF coordinate ('aa'..'ss', includes 'i')."""
    xi, yi, _ = _validate_xy(x, y, board_size)
    return chr(ord("a") + xi) + chr(ord("a") + yi)


def sgf_to_xy(sgf_coord: str, board_size: int) -> tuple[int, int] | None:
    """Convert SGF coordinate to internal (x, y), or None for pass ('' or 'tt')."""
    size = validate_board_size(board_size)
    if not isinstance(sgf_coord, str):
        raise ValueError(f"SGF coord must be a string, got {type(sgf_coord).__name__}")
    s = sgf_coord.strip()
    if s == "" or (s == "tt" and size <= 19):
        return None
    if len(s) != 2 or not ("a" <= s[0] <= "z" and "a" <= s[1] <= "z"):
        raise ValueError(f"Malformed SGF coordinate: {sgf_coord!r}")
    x = ord(s[0]) - ord("a")
    y = ord(s[1]) - ord("a")
    if not (0 <= x < size and 0 <= y < size):
        raise ValueError(
            f"SGF coordinate {sgf_coord!r} out of bounds for {size}x{size} board"
        )
    return (x, y)


def gtp_to_sgf(gtp: str, board_size: int) -> str:
    """Convert GTP move string to SGF coordinate ('pass' -> '')."""
    xy = gtp_to_xy(gtp, board_size)
    if xy is None:
        return ""
    return xy_to_sgf(xy[0], xy[1], board_size)


def sgf_to_gtp(sgf_coord: str, board_size: int) -> str:
    """Convert SGF coordinate to GTP move string ('' or 'tt' -> 'pass')."""
    xy = sgf_to_xy(sgf_coord, board_size)
    if xy is None:
        return "pass"
    return xy_to_gtp(xy[0], xy[1], board_size)


def expand_sgf_coords(value: str, board_size: int) -> list[tuple[int, int]]:
    """Expand a single SGF point ('dd') or compressed rectangle ('aa:cc') into (x, y) points."""
    size = validate_board_size(board_size)
    if not isinstance(value, str):
        raise ValueError(f"SGF point value must be a string, got {type(value).__name__}")
    s = value.strip()
    if not s:
        raise ValueError("Empty coordinate in SGF point list")

    if ":" not in s:
        xy = sgf_to_xy(s, size)
        if xy is None:
            raise ValueError(f"Pass coordinate {value!r} not allowed in SGF point list")
        return [xy]

    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(f"Malformed compressed SGF rectangle: {value!r}")

    p1 = sgf_to_xy(parts[0], size)
    p2 = sgf_to_xy(parts[1], size)
    if p1 is None or p2 is None:
        raise ValueError(f"Pass coordinate not allowed in compressed rectangle: {value!r}")

    x1, y1 = p1
    x2, y2 = p2
    if x1 > x2 or y1 > y2:
        raise ValueError(
            f"Inverted compressed SGF rectangle {value!r} (upper-left must precede lower-right)"
        )

    return [(x, y) for y in range(y1, y2 + 1) for x in range(x1, x2 + 1)]


def xy_to_ownership_index(x: int, y: int, board_size: int) -> int:
    """Convert internal (x, y) to KataGo row-major ownership array index."""
    xi, yi, size = _validate_xy(x, y, board_size)
    return yi * size + xi


def ownership_index_to_xy(index: int, board_size: int) -> tuple[int, int]:
    """Convert KataGo row-major ownership array index to internal (x, y)."""
    size = validate_board_size(board_size)
    idx = _check_int(index, "index")
    total = size * size
    if idx < 0 or idx >= total:
        raise ValueError(
            f"Ownership index {idx} out of bounds 0..{total - 1} for {size}x{size} board"
        )
    return (idx % size, idx // size)


def ownership_index_to_gtp(index: int, board_size: int) -> str:
    """Convert KataGo ownership array index to GTP coordinate."""
    x, y = ownership_index_to_xy(index, board_size)
    return xy_to_gtp(x, y, board_size)


def gtp_to_ownership_index(gtp: str, board_size: int) -> int:
    """Convert non-pass GTP coordinate to KataGo ownership array index."""
    xy = gtp_to_xy(gtp, board_size)
    if xy is None:
        raise ValueError("Pass move has no ownership index")
    return xy_to_ownership_index(xy[0], xy[1], board_size)


_HANDICAP_TABLES: dict[int, dict[int, list[str]]] = {
    19: {
        2: ["D4", "Q16"],
        3: ["D4", "Q16", "Q4"],
        4: ["D4", "Q16", "Q4", "D16"],
        5: ["D4", "Q16", "Q4", "D16", "K10"],
        6: ["D4", "Q16", "Q4", "D16", "D10", "Q10"],
        7: ["D4", "Q16", "Q4", "D16", "D10", "Q10", "K10"],
        8: ["D4", "Q16", "Q4", "D16", "D10", "Q10", "K4", "K16"],
        9: ["D4", "Q16", "Q4", "D16", "D10", "Q10", "K4", "K16", "K10"],
    },
    13: {
        2: ["D4", "K10"],
        3: ["D4", "K10", "K4"],
        4: ["D4", "K10", "K4", "D10"],
        5: ["D4", "K10", "K4", "D10", "G7"],
        6: ["D4", "K10", "K4", "D10", "D7", "K7"],
        7: ["D4", "K10", "K4", "D10", "D7", "K7", "G7"],
        8: ["D4", "K10", "K4", "D10", "D7", "K7", "G4", "G10"],
        9: ["D4", "K10", "K4", "D10", "D7", "K7", "G4", "G10", "G7"],
    },
    9: {
        2: ["C3", "G7"],
        3: ["C3", "G7", "G3"],
        4: ["C3", "G7", "G3", "C7"],
        5: ["C3", "G7", "G3", "C7", "E5"],
    },
}


def handicap_stones_gtp(board_size: int, handicap: int) -> list[str]:
    """Return standard handicap star points in GTP coordinates.

    Supports:
      - 19x19: 2..9 stones
      - 13x13: 2..9 stones
      - 9x9:   2..5 stones
      - handicap 0 or 1 returns []
    """
    size = validate_board_size(board_size)
    ha = _check_int(handicap, "handicap")
    if ha < 0:
        raise ValueError(f"handicap must be >= 0, got {ha}")
    if ha in (0, 1):
        return []
    table = _HANDICAP_TABLES.get(size)
    if table is None or ha not in table:
        raise ValueError(
            f"Unsupported handicap={ha} for {size}x{size} board"
        )
    return list(table[ha])


__all__ = [
    "GTP_COLS",
    "SUPPORTED_SIZES",
    "validate_board_size",
    "is_gtp_pass",
    "is_sgf_pass",
    "is_pass",
    "xy_to_gtp",
    "gtp_to_xy",
    "normalize_gtp",
    "xy_to_sgf",
    "sgf_to_xy",
    "gtp_to_sgf",
    "sgf_to_gtp",
    "expand_sgf_coords",
    "xy_to_ownership_index",
    "ownership_index_to_xy",
    "ownership_index_to_gtp",
    "gtp_to_ownership_index",
    "handicap_stones_gtp",
]
