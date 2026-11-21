"""GoFactBridge: Extracts 100% deterministic, hallucination-free facts from KataGo analysis and board rules.

Part of Phase 2 Gemini AI Go Coach foundation.
"""

from __future__ import annotations

import math
from typing import Any, Literal
from app.coords import xy_to_gtp, gtp_to_xy


def is_garbage_time(
    winrate_black: float,
    score_lead_black: float,
    handicap: int = 0,
    confirmed_ratio: float = 0.5,
) -> bool:
    """Unified garbage time (大差局面) checker across UI, graphs, and Gemini coach.
    
    Prevents noisy blunder badges when the game is already decided, while preserving
    drastic reversions (大逆転ポカ救済ルール).
    """
    wr = winrate_black
    lead = abs(score_lead_black)

    if handicap >= 2:
        # Handicap game: starts near 100% black winrate, so thresholds are higher
        return confirmed_ratio >= 0.55 and (wr >= 0.985 or wr <= 0.015) and lead >= 25.0

    # Even game (互先)
    return confirmed_ratio >= 0.25 and (wr >= 0.97 or wr <= 0.03) and lead >= 15.0


def classify_move_quality(
    score_loss: float,
    winrate_loss: float,
    board_size: int = 19,
    is_decided: bool = False,
    is_turn_reversion: bool = False,
) -> Literal["blunder", "mistake", "inaccuracy", "good", "normal"]:
    """Classify a move into quality badges based on board-size scaled loss metrics."""
    scale = 1.0 if board_size == 19 else (0.75 if board_size == 13 else 0.55)
    loss = abs(score_loss)
    wr_drop = abs(winrate_loss)

    # Reversion rescues blunder from garbage suppression
    if is_decided and not is_turn_reversion:
        if loss >= 8.0 * scale:
            return "inaccuracy"
        return "normal"

    # Blunder (大悪手)
    if loss >= 5.0 * scale or (loss >= 3.0 * scale and wr_drop >= 0.20):
        return "blunder"

    # Mistake (悪手)
    if loss >= 2.5 * scale or (loss >= 1.5 * scale and wr_drop >= 0.15):
        return "mistake"

    # Inaccuracy (疑問手)
    if loss >= 1.2 * scale:
        return "inaccuracy"

    # Good move
    if loss <= 0.3 * scale and wr_drop <= 0.02:
        return "good"

    return "normal"


def get_area_name_for_coord(col: int, row: int, board_size: int = 19) -> str:
    """Map board (col, row) to regional area name (e.g., '左上隅', '右辺', '天元/中央')."""
    if board_size == 19:
        c_third = 0 if col < 6 else (1 if col < 13 else 2)
        r_third = 0 if row < 6 else (1 if row < 13 else 2)
    elif board_size == 13:
        c_third = 0 if col < 4 else (1 if col < 9 else 2)
        r_third = 0 if row < 4 else (1 if row < 9 else 2)
    else:  # 9路
        c_third = 0 if col < 3 else (1 if col < 6 else 2)
        r_third = 0 if row < 3 else (1 if row < 6 else 2)

    col_names = ["左", "中央", "右"]
    row_names = ["下", "中央", "上"]

    c_name = col_names[c_third]
    r_name = row_names[r_third]

    if c_third == 1 and r_third == 1:
        return "中央（天元付近）"
    if c_third != 1 and r_third != 1:
        return f"{c_name}{r_name}隅"
    return f"{c_name}辺" if r_third == 1 else f"{r_name}辺"


class GoFactBridge:
    """Extracts normalized facts from game board state and KataGo root/candidate analyses."""

    def __init__(self, board_size: int = 19):
        self.board_size = board_size

    def extract_blunder_facts(
        self,
        actual_move_gtp: str,
        best_move_gtp: str,
        player: Literal["B", "W"],
        score_loss: float,
        winrate_loss: float,
        score_lead_before: float,
        score_lead_after: float,
        tactical_flags: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Produce structured fact payload for Gemini Coach 'explain' prompt."""
        flags = tactical_flags or {}
        return {
            "board_size": self.board_size,
            "player": "黒" if player == "B" else "白",
            "actual_move": actual_move_gtp,
            "best_move": best_move_gtp,
            "score_loss": round(abs(score_loss), 1),
            "winrate_loss_pct": round(abs(winrate_loss) * 100, 1),
            "lead_before": round(score_lead_before, 1),
            "lead_after": round(score_lead_after, 1),
            "is_atari_saved": bool(flags.get("was_in_atari_saved")),
            "is_self_atari": bool(flags.get("is_self_atari")),
            "is_tenuki": bool(flags.get("is_tenuki")),
            "captured_count": int(flags.get("captured_stones", 0)),
            "area_actual": flags.get("area_actual", "辺/隅"),
            "area_best": flags.get("area_best", "辺/隅"),
        }
