"""Layer 1 unit tests for app.coords (Pitfalls #2 and #10)."""

from __future__ import annotations

import pytest

from app.coords import (
    GTP_COLS,
    SUPPORTED_SIZES,
    expand_sgf_coords,
    gtp_to_ownership_index,
    gtp_to_sgf,
    gtp_to_xy,
    handicap_stones_gtp,
    is_gtp_pass,
    is_pass,
    is_sgf_pass,
    normalize_gtp,
    ownership_index_to_gtp,
    ownership_index_to_xy,
    sgf_to_gtp,
    sgf_to_xy,
    validate_board_size,
    xy_to_gtp,
    xy_to_ownership_index,
    xy_to_sgf,
)


@pytest.mark.parametrize("size", SUPPORTED_SIZES)
def test_corners_tengen_edges_full_roundtrip(size: int) -> None:
    mid = size // 2
    points = [
        (0, 0),              # top-left (A{size})
        (size - 1, 0),       # top-right
        (0, size - 1),       # bottom-left (A1)
        (size - 1, size - 1),  # bottom-right
        (mid, mid),          # tengen
        (mid, 0),            # top edge
        (0, mid),            # left edge
        (size - 1, mid),     # right edge
        (mid, size - 1),     # bottom edge
    ]
    for x, y in points:
        gtp = xy_to_gtp(x, y, size)
        sgf = xy_to_sgf(x, y, size)
        idx = xy_to_ownership_index(x, y, size)

        assert gtp_to_xy(gtp, size) == (x, y)
        assert sgf_to_xy(sgf, size) == (x, y)
        assert gtp_to_sgf(gtp, size) == sgf
        assert sgf_to_gtp(sgf, size) == gtp
        assert ownership_index_to_xy(idx, size) == (x, y)
        assert ownership_index_to_gtp(idx, size) == gtp
        assert gtp_to_ownership_index(gtp, size) == idx
        assert idx == y * size + x


def test_specific_known_coordinates_across_sizes() -> None:
    # 19x19
    assert xy_to_gtp(0, 0, 19) == "A19"
    assert xy_to_gtp(18, 18, 19) == "T1"
    assert xy_to_gtp(9, 9, 19) == "K10"
    assert xy_to_sgf(15, 3, 19) == "pd"
    assert sgf_to_gtp("pd", 19) == "Q16"
    assert xy_to_ownership_index(0, 0, 19) == 0
    assert xy_to_ownership_index(18, 18, 19) == 360

    # 13x13
    assert xy_to_gtp(6, 6, 13) == "G7"
    assert xy_to_gtp(12, 0, 13) == "N13"
    assert xy_to_ownership_index(12, 12, 13) == 168

    # 9x9
    assert xy_to_gtp(4, 4, 9) == "E5"
    assert xy_to_gtp(8, 0, 9) == "J9"
    assert xy_to_ownership_index(8, 8, 9) == 80


def test_i_j_boundary_rules() -> None:
    assert "I" not in GTP_COLS
    # GTP must strictly reject column 'I'
    for bad in ("I10", "i10", "I1", "I9", "I19"):
        with pytest.raises(ValueError):
            gtp_to_xy(bad, 19)

    # Column index 7 -> H, index 8 -> J in GTP, while SGF uses 'h' and 'i'
    assert xy_to_gtp(7, 9, 19) == "H10"
    assert xy_to_gtp(8, 9, 19) == "J10"
    assert xy_to_sgf(7, 9, 19) == "hj"
    assert xy_to_sgf(8, 9, 19) == "ij"

    # SGF 'i' MUST be accepted!
    assert sgf_to_xy("ii", 19) == (8, 8)
    assert sgf_to_gtp("ii", 19) == "J11"
    assert sgf_to_gtp("ii", 9) == "J1"
    assert gtp_to_sgf("J1", 9) == "ii"


def test_compressed_sgf_rectangle_expansion() -> None:
    pts = expand_sgf_coords("aa:cc", 19)
    assert len(pts) == 9
    expected = [(x, y) for y in range(3) for x in range(3)]
    assert pts == expected

    # Single point
    assert expand_sgf_coords("dd", 19) == [(3, 3)]

    # Inverted rectangle rejected
    with pytest.raises(ValueError):
        expand_sgf_coords("cc:aa", 19)
    with pytest.raises(ValueError):
        expand_sgf_coords("ca:ac", 19)

    # Out of bounds for 9x9
    with pytest.raises(ValueError):
        expand_sgf_coords("aa:jj", 9)

    # Pass or empty rejected
    for bad in ("", "tt", "aa:tt", "aa:bb:cc"):
        with pytest.raises(ValueError):
            expand_sgf_coords(bad, 19)


def test_pass_normalization() -> None:
    for gtp_pass in ("pass", "PASS", "Pass", "  pass  "):
        assert is_gtp_pass(gtp_pass) is True
        assert is_pass(gtp_pass, 19) is True
        assert gtp_to_xy(gtp_pass, 19) is None
        assert normalize_gtp(gtp_pass, 19) == "pass"
        assert gtp_to_sgf(gtp_pass, 19) == ""

    for sgf_pass in ("", "tt"):
        assert is_sgf_pass(sgf_pass, 19) is True
        assert is_pass(sgf_pass, 19) is True
        assert sgf_to_xy(sgf_pass, 19) is None
        assert sgf_to_gtp(sgf_pass, 19) == "pass"
        assert sgf_to_gtp(sgf_pass, 9) == "pass"

    assert is_gtp_pass("Q16") is False
    assert is_gtp_pass(None) is False
    assert is_sgf_pass("dd", 19) is False
    assert is_pass("Q16", 19) is False

    with pytest.raises(ValueError):
        gtp_to_ownership_index("pass", 19)


def test_invalid_sizes_and_coordinates() -> None:
    for bad_size in (0, 1, -9, 20, 25, True, False, "19", 19.0):
        with pytest.raises(ValueError):
            validate_board_size(bad_size)  # type: ignore[arg-type]

    for bad_gtp, size in (
        ("", 19),
        ("A", 19),
        ("A0", 19),
        ("A01", 19),
        ("A20", 19),
        ("U1", 19),
        ("Z19", 19),
        ("K5", 9),
        ("A10", 9),
        ("O13", 13),
        ("19A", 19),
    ):
        with pytest.raises(ValueError):
            gtp_to_xy(bad_gtp, size)

    for bad_sgf, size in (
        ("a", 19),
        ("aaa", 19),
        ("AA", 19),
        ("jj", 9),
        ("zz", 19),
        ("a1", 19),
    ):
        with pytest.raises(ValueError):
            sgf_to_xy(bad_sgf, size)

    with pytest.raises(ValueError):
        xy_to_gtp(-1, 0, 19)
    with pytest.raises(ValueError):
        xy_to_gtp(9, 0, 9)
    with pytest.raises(ValueError):
        ownership_index_to_xy(-1, 9)
    with pytest.raises(ValueError):
        ownership_index_to_xy(81, 9)
    with pytest.raises(ValueError):
        ownership_index_to_xy(169, 13)
    with pytest.raises(ValueError):
        ownership_index_to_xy(361, 19)


def test_handicap_stones_tables() -> None:
    assert handicap_stones_gtp(19, 0) == []
    assert handicap_stones_gtp(19, 1) == []
    for h in range(2, 10):
        stones_19 = handicap_stones_gtp(19, h)
        assert len(stones_19) == h
        assert len(set(stones_19)) == h
        stones_13 = handicap_stones_gtp(13, h)
        assert len(stones_13) == h
    for h in range(2, 6):
        stones_9 = handicap_stones_gtp(9, h)
        assert len(stones_9) == h
    with pytest.raises(ValueError):
        handicap_stones_gtp(9, 9)
