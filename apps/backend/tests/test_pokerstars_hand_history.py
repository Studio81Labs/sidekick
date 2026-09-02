from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from app.application.imported_hand_ingestion import (
    ImportedHandImportIdConflict,
    ImportedHandIngestionService,
)
from app.infrastructure.hand_history.pokerstars import (
    POKERSTARS_ADAPTER_ID,
    POKERSTARS_ADAPTER_VERSION,
    PokerStarsImportContext,
    parse_pokerstars_text,
)
from app.storage.imported_hand_store import FileImportedHandStore


FIXTURES = Path(__file__).parent / "fixtures" / "pokerstars"
IMPORTED_AT = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)


def import_context(name: str = "synthetic-cash-sitout.txt") -> PokerStarsImportContext:
    return PokerStarsImportContext(
        import_id=f"test-import:{name}",
        imported_at=IMPORTED_AT,
        source_filename=name,
    )


def synthetic_straddle_source(*straddle_posts: str) -> str:
    posts = "".join(f"{post}\n" for post in straddle_posts)
    return (
        "PokerStars Hand #900000000008: Hold'em No Limit ($0.50/$1.00 USD) "
        "- 2026/08/30 12:41:56 ET\n"
        "Table 'Synthetic Straddle' 4-max Seat #1 is the button\n"
        "Seat 1: Straddle Hero ($100.00 in chips)\n"
        "Seat 2: Straddle Small ($100.00 in chips)\n"
        "Seat 3: Straddle Big ($100.00 in chips)\n"
        "Seat 4: Straddle Rival ($100.00 in chips)\n"
        "Straddle Small: posts small blind $0.50\n"
        "Straddle Big: posts big blind $1.00\n"
        f"{posts}"
        "*** HOLE CARDS ***\n"
        "Dealt to Straddle Hero [As Kd]\n"
    )


def test_cash_hand_preserves_evidence_positions_origin_and_reconciliation(
    tmp_path: Path,
) -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text()

    result = parse_pokerstars_text(source, context=import_context())

    assert result.diagnostics == ()
    assert len(result.hands) == 1
    parsed = result.hands[0]
    candidate = parsed.candidate
    state = candidate.detection.state
    assert candidate.raw.raw_text == source
    assert candidate.raw.content_sha256 == sha256(source.encode()).hexdigest()
    assert candidate.raw.identity.site == "pokerstars"
    assert candidate.raw.identity.source_hand_id == "900000000001"
    assert candidate.raw.chronology.source_timezone == "ET"
    assert candidate.raw.chronology.hand_ordinal == 1
    assert candidate.raw.provenance.adapter_id == POKERSTARS_ADAPTER_ID
    assert candidate.raw.provenance.adapter_version == POKERSTARS_ADAPTER_VERSION
    assert state.game.table_size == 6
    assert state.game.economics.kind == "cash"
    assert state.game.economics.currency == "USD"
    assert state.game.blinds.ante == Decimal(0)
    assert state.game.blinds.ante_mode == "unknown"
    assert [(seat.seat_number, seat.participation) for seat in state.seats] == [
        (1, "dealt_in"),
        (3, "sitting_out"),
        (5, "dealt_in"),
        (6, "dealt_in"),
    ]
    assert [
        seat.position.display_label if seat.position is not None else None
        for seat in state.seats
    ] == ["BTN", None, "SB", "BB"]
    assert state.hero_player_id == "seat-1"
    assert [card.code for card in state.hero_cards] == ["As", "Kd"]
    assert [action.action_type for action in state.streets[0].actions] == [
        "post_small_blind",
        "post_big_blind",
        "raise",
        "fold",
        "fold",
        "uncalled_return",
    ]
    assert [
        action.origin.kind for action in state.streets[0].actions
    ] == [
        "forced_system",
        "forced_system",
        "unknown",
        "unknown",
        "unknown",
        "forced_system",
    ]
    assert [
        action.origin.confidence for action in state.streets[0].actions
    ] == [
        Decimal("1"),
        Decimal("1"),
        None,
        None,
        None,
        Decimal("1"),
    ]
    assert parsed.reconciliation.status == "pass"
    assert parsed.disposition == "clean"
    assert parsed.reconciliation.derived_gross_total == state.results.stated_pot.gross_total
    table_size_evidence = candidate.detection.field_evidence["/game/table_size"]
    assert table_size_evidence.evidence[0].line_start == 2
    assert table_size_evidence.evidence[0].excerpt.startswith("Table 'Synthetic Alpha'")
    for pointer in ("/game/blinds/ante", "/game/blinds/ante_mode"):
        ante_evidence = candidate.detection.field_evidence[pointer]
        assert ante_evidence.evidence[0].line_start == 9
        assert ante_evidence.evidence[0].excerpt == "*** HOLE CARDS ***"
    for pointer in (
        "/identity/site",
        "/chronology/source_timezone",
        "/game/variant",
        "/game/betting_limit",
        "/game/economics/kind",
    ):
        header_evidence = candidate.detection.field_evidence[pointer]
        assert header_evidence.evidence[0].line_start == 1
    assert "No Limit" in candidate.detection.field_evidence[
        "/game/betting_limit"
    ].evidence[0].excerpt
    assert [
        source.line_start
        for source in candidate.detection.field_evidence[
            "/seats/0/position"
        ].evidence
    ] == [2, 3, 4, 5, 6]
    assert all(
        f"/seats/{index}/position" in candidate.detection.field_evidence
        for index in range(len(state.seats))
    )
    assert all(
        field.confidence == Decimal("1")
        for field in candidate.detection.field_evidence.values()
    )
    straddle_evidence = candidate.detection.field_evidence[
        "/game/blinds/straddle"
    ]
    assert straddle_evidence.evidence[0].line_start == 9
    assert straddle_evidence.evidence[0].excerpt == "*** HOLE CARDS ***"
    assert "/streets/0/actions/2" in candidate.detection.field_evidence
    assert candidate.detection.warnings == [
        "Action origin is unresolved for 3 player decision(s); review is required."
    ]

    ingestion = ImportedHandIngestionService(
        store=FileImportedHandStore(tmp_path)
    ).ingest(candidate)
    assert ingestion.disposition == "created_pending_review"
    assert ingestion.record.lifecycle.status == "pending_review"
    assert ingestion.record.canonical_revisions == []


def test_heads_up_button_is_also_small_blind() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text()

    result = parse_pokerstars_text(
        source,
        context=import_context("synthetic-heads-up.txt"),
    )

    assert result.diagnostics == ()
    state = result.hands[0].candidate.detection.state
    assert [seat.position.display_label for seat in state.seats] == ["BTN/SB", "BB"]
    assert result.hands[0].reconciliation.status == "pass"


def test_exported_two_space_header_delimiter_is_supported() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text().replace(
        "#900000000002: Hold'em",
        "#900000000002:  Hold'em",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("two-space-header.txt"),
    )

    assert result.diagnostics == ()
    assert result.hands[0].candidate.raw.identity.source_hand_id == "900000000002"


def test_board_cards_retain_their_street_marker_evidence() -> None:
    source = (FIXTURES / "synthetic-flop.txt").read_text()

    result = parse_pokerstars_text(
        source,
        context=import_context("synthetic-flop.txt"),
    )

    assert result.diagnostics == ()
    parsed = result.hands[0]
    assert parsed.reconciliation.status == "pass"
    board = parsed.candidate.detection.field_evidence[
        "/streets/1/board_cards"
    ]
    assert board.evidence[0].line_start == 11
    assert board.evidence[0].excerpt == "*** FLOP *** [2c 3d 4h]"


def test_short_big_blind_uses_the_nominal_preflop_bring_in_for_raises() -> None:
    source = """PokerStars Hand #900000000007:  Hold'em No Limit ($0.50/$1.00 USD) - 2026/08/30 12:40:56 ET
Table 'Synthetic Short Blind' 3-max Seat #1 is the button
Seat 1: Short Hero ($100.00 in chips)
Seat 2: Short Small ($100.00 in chips)
Seat 3: Short Big ($0.50 in chips)
Short Small: posts small blind $0.50
Short Big: posts big blind $0.50 and is all-in
*** HOLE CARDS ***
Dealt to Short Hero [Kh Qh]
Short Hero: raises $1.00 to $2.00
Short Small: calls $1.50
"""

    result = parse_pokerstars_text(
        source,
        context=import_context("short-big-blind.txt"),
    )

    assert result.diagnostics == ()
    raise_action = result.hands[0].candidate.detection.state.streets[0].actions[2]
    assert raise_action.action_type == "raise"
    assert str(raise_action.total_committed) == "2.00"


@pytest.mark.parametrize(
    ("old", "new", "expected_line"),
    [
        (
            "Small Synthetic: posts small blind $0.50",
            "Small Synthetic: posts small blind $0.25",
            7,
        ),
        (
            "Big Synthetic: posts big blind $1.00",
            "Big Synthetic: posts big blind $0.50",
            8,
        ),
        (
            "Small Synthetic: posts small blind $0.50",
            "Hero Synthetic: posts small blind $0.50",
            7,
        ),
    ],
)
def test_invalid_structural_blind_points_to_its_source_line(
    old: str,
    new: str,
    expected_line: int,
) -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        old,
        new,
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("invalid-structural-blind.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "invalid_structural_blind"
    assert diagnostic.line_start == expected_line
    assert diagnostic.line_end == expected_line


def test_missing_structural_blind_points_to_forced_post_section_end() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text().replace(
        "Heads Rival: posts big blind $1.00\n",
        "",
        1,
    )
    source = source.split("Heads Hero: folds\n", 1)[0]

    result = parse_pokerstars_text(
        source,
        context=import_context("missing-big-blind.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "missing_structural_blind"
    assert diagnostic.line_start == 6
    assert diagnostic.line_end == 6


@pytest.mark.parametrize(
    ("old", "new", "expected_code", "expected_line"),
    [
        (
            "Hero Synthetic: raises $2.00 to $3.00",
            "Hero Synthetic: raises $2.00 to $3.00 and is all-in",
            "invalid_all_in",
            11,
        ),
        (
            "Small Synthetic: folds\nBig Synthetic: folds",
            "Big Synthetic: folds\nSmall Synthetic: folds",
            "action_out_of_turn",
            12,
        ),
        (
            "Seat 1: Hero Synthetic ($100.00 in chips)",
            "Seat 1: Hero Synthetic ($2.00 in chips)",
            "action_exceeds_stack",
            11,
        ),
        (
            "Uncalled bet ($2.00) returned to Hero Synthetic\n",
            (
                "Uncalled bet ($2.00) returned to Hero Synthetic\n"
                "Small Synthetic: folds\n"
            ),
            "action_after_uncalled_return",
            15,
        ),
        (
            "Small Synthetic: folds\n",
            "Small Synthetic: folds\nSmall Synthetic: calls $2.50\n",
            "terminal_actor_action",
            13,
        ),
    ],
)
def test_invalid_action_contract_points_to_its_source_line(
    old: str,
    new: str,
    expected_code: str,
    expected_line: int,
) -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        old,
        new,
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("invalid-action-contract.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == expected_code
    assert diagnostic.line_start == expected_line
    assert diagnostic.line_end == expected_line


@pytest.mark.parametrize(
    ("replacement", "expected_code"),
    [
        ("Small Synthetic: calls $0.50", "invalid_call"),
        ("Small Synthetic: checks", "invalid_check"),
        ("Small Synthetic: raises $1.00 to $4.00", "invalid_raise"),
    ],
)
def test_invalid_betting_rule_points_to_action_line(
    replacement: str,
    expected_code: str,
) -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Small Synthetic: folds",
        replacement,
        1,
    ).replace(
        "Seat 5: Small Synthetic (small blind) folded before Flop\n",
        "",
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("invalid-betting-rule.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == expected_code
    assert diagnostic.line_start == 12
    assert diagnostic.line_end == 12


def test_call_without_outstanding_wager_points_to_action_line() -> None:
    source = (FIXTURES / "synthetic-flop.txt").read_text().replace(
        "Flop Rival: checks\nFlop Hero: bets $1.00",
        "Flop Rival: calls $1.00\nFlop Hero: bets $1.00",
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("call-without-outstanding-wager.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "invalid_call"
    assert diagnostic.line_start == 12
    assert diagnostic.line_end == 12


def test_bet_facing_outstanding_wager_points_to_action_line() -> None:
    source = (FIXTURES / "synthetic-flop.txt").read_text().replace(
        "Flop Hero: calls $0.50",
        "Flop Hero: bets $2.00",
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("bet-facing-outstanding-wager.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "invalid_bet"
    assert diagnostic.line_start == 9
    assert diagnostic.line_end == 9


def test_premature_street_transition_points_to_marker_line() -> None:
    source = (FIXTURES / "synthetic-flop.txt").read_text().replace(
        "Flop Rival: checks\n",
        "",
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("premature-street-transition.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "premature_street_transition"
    assert diagnostic.line_start == 10
    assert diagnostic.line_end == 10


def test_invalid_uncalled_return_points_to_action_line() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Uncalled bet ($2.00) returned to Hero Synthetic",
        "Uncalled bet ($1.00) returned to Hero Synthetic",
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("invalid-uncalled-return.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "invalid_uncalled_return"
    assert diagnostic.line_start == 14
    assert diagnostic.line_end == 14


@pytest.mark.parametrize(
    ("replacement", "expected_code"),
    [
        ("Flop Hero: bets $0.50", "invalid_bet"),
        ("Flop Hero: raises $1.00 to $1.00", "invalid_raise"),
    ],
)
def test_additional_invalid_wager_points_to_action_line(
    replacement: str,
    expected_code: str,
) -> None:
    lines = (FIXTURES / "synthetic-flop.txt").read_text().splitlines()
    lines[12] = replacement
    source = "\n".join(lines[:13]) + "\n"

    result = parse_pokerstars_text(
        source,
        context=import_context("additional-invalid-wager.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == expected_code
    assert diagnostic.line_start == 13
    assert diagnostic.line_end == 13


def test_action_after_all_opponents_are_all_in_points_to_action_line() -> None:
    lines = (FIXTURES / "synthetic-flop.txt").read_text().splitlines()
    lines[3] = "Seat 2: Flop Rival ($1.00 in chips)"
    lines[5] = "Flop Rival: posts big blind $1.00 and is all-in"
    lines = [line for line in lines if line != "Flop Rival: checks"]
    source = "\n".join(lines[:11]) + "\n"

    result = parse_pokerstars_text(
        source,
        context=import_context("action-after-opponents-all-in.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "terminal_table_action"
    assert diagnostic.line_start == 11
    assert diagnostic.line_end == 11


def test_missing_uncalled_return_points_to_next_street_marker() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Uncalled bet ($2.00) returned to Hero Synthetic\n",
        "*** FLOP *** [2c 3d 4h]\n",
        1,
    ).split("Hero Synthetic collected", 1)[0]

    result = parse_pokerstars_text(
        source,
        context=import_context("missing-uncalled-return.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "missing_uncalled_return"
    assert diagnostic.line_start == 14
    assert diagnostic.line_end == 14


def test_street_after_fold_end_points_to_next_street_marker() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Hero Synthetic collected $2.50 from pot\n",
        "*** FLOP *** [2c 3d 4h]\n",
        1,
    ).split("*** SUMMARY ***", 1)[0]

    result = parse_pokerstars_text(
        source,
        context=import_context("street-after-fold-end.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "street_after_hand_end"
    assert diagnostic.line_start == 15
    assert diagnostic.line_end == 15


def test_premature_results_point_to_stated_pot_line() -> None:
    source = (FIXTURES / "synthetic-flop.txt").read_text().replace(
        "Flop Rival: folds",
        "Flop Rival: calls $1.00",
        1,
    ).replace(
        "Uncalled bet ($1.00) returned to Flop Hero\n",
        "",
        1,
    ).replace(
        "Seat 2: Flop Rival (big blind) folded on the Flop\n",
        "",
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("premature-results.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "premature_results"
    assert diagnostic.line_start == 17
    assert diagnostic.line_end == 17


def test_duplicate_summary_seat_is_rejected_at_duplicate_line() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text()
    source += "Seat 2: Heads Rival (big blind) collected ($1.00)\n"

    result = parse_pokerstars_text(
        source,
        context=import_context("duplicate-summary-seat.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "duplicate_summary_seat"
    assert diagnostic.line_start == 16
    assert diagnostic.line_end == 16


def test_action_after_valid_all_in_points_to_later_action() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Seat 1: Hero Synthetic ($100.00 in chips)",
        "Seat 1: Hero Synthetic ($3.00 in chips)",
        1,
    ).replace(
        "Hero Synthetic: raises $2.00 to $3.00\n",
        (
            "Hero Synthetic: raises $2.00 to $3.00 and is all-in\n"
            "Hero Synthetic: checks\n"
        ),
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("action-after-valid-all-in.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "terminal_actor_action"
    assert diagnostic.line_start == 12
    assert diagnostic.line_end == 12


def test_folded_player_award_points_to_collection_line() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Hero Synthetic collected $2.50 from pot",
        "Small Synthetic collected $2.50 from pot",
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("folded-player-award.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "invalid_award_recipient"
    assert diagnostic.line_start == 15
    assert diagnostic.line_end == 15


def test_folded_player_showdown_points_to_shown_cards_line() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Uncalled bet ($2.00) returned to Hero Synthetic\n",
        "*** SHOW DOWN ***\nSmall Synthetic: shows [2c 3d]\n",
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("folded-player-showdown.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "invalid_showdown_participant"
    assert diagnostic.line_start == 15
    assert diagnostic.line_end == 15


def test_hero_board_collision_points_to_street_marker() -> None:
    source = (FIXTURES / "synthetic-flop.txt").read_text().replace(
        "[2c 3d 4h]",
        "[Ad 3d 4h]",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("duplicate-known-card.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "duplicate_known_card"
    assert diagnostic.line_start == 11
    assert diagnostic.line_end == 11


def test_duplicate_hero_card_points_to_dealt_line() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Dealt to Hero Synthetic [As Kd]",
        "Dealt to Hero Synthetic [As As]",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("duplicate-hero-card.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "duplicate_known_card"
    assert diagnostic.line_start == 10
    assert diagnostic.line_end == 10


def test_changed_turn_board_prefix_points_to_turn_marker() -> None:
    source = (FIXTURES / "synthetic-flop.txt").read_text()
    prefix, _ = source.split("Flop Hero: bets $1.00", 1)
    source = (
        prefix
        + "Flop Hero: checks\n"
        + "*** TURN *** [2c 3d 5h] [6s]\n"
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("changed-board-prefix.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "board_prefix_mismatch"
    assert diagnostic.line_start == 14
    assert diagnostic.line_end == 14


def test_rake_above_total_pot_points_to_summary_total() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Total pot $2.50 | Rake $0.00",
        "Total pot $1.00 | Rake $2.00",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("invalid-total-pot.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "invalid_total_pot"
    assert diagnostic.line_start == 17
    assert diagnostic.line_end == 17


def test_per_player_antes_do_not_inflate_live_raise_or_return_totals() -> None:
    source = (FIXTURES / "synthetic-ante.txt").read_text()

    result = parse_pokerstars_text(
        source,
        context=import_context("synthetic-ante.txt"),
    )

    assert result.diagnostics == ()
    parsed = result.hands[0]
    state = parsed.candidate.detection.state
    assert state.game.blinds.ante_mode == "per_player"
    assert state.game.blinds.ante is not None
    assert str(state.game.blinds.ante) == "0.10"
    assert [
        source.line_start
        for source in result.hands[0].candidate.detection.field_evidence[
            "/game/blinds/ante"
        ].evidence
    ] == [6, 7, 8]
    assert [
        source.line_start
        for source in result.hands[0].candidate.detection.field_evidence[
            "/game/blinds/ante_mode"
        ].evidence
    ] == [6, 7, 8]
    returned = state.streets[0].actions[-1]
    assert returned.action_type == "uncalled_return"
    assert str(returned.total_committed) == "0.60"
    assert parsed.reconciliation.status == "pass"


@pytest.mark.parametrize(
    ("old", "new", "expected_line_end"),
    [
        (
            "Ante Small: posts the ante $0.10",
            "Ante Small: posts the ante $0.20",
            8,
        ),
        (
            "Ante Hero: posts the ante $0.10\n",
            "",
            7,
        ),
    ],
)
def test_unsupported_ante_structure_points_to_the_ante_lines(
    old: str,
    new: str,
    expected_line_end: int,
) -> None:
    source = (FIXTURES / "synthetic-ante.txt").read_text().replace(old, new)

    result = parse_pokerstars_text(
        source,
        context=import_context("unsupported-ante-structure.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "unsupported_ante_structure"
    assert diagnostic.line_start == 6
    assert diagnostic.line_end == expected_line_end


def test_all_in_antes_do_not_establish_a_nominal_amount() -> None:
    source = (FIXTURES / "synthetic-ante.txt").read_text().replace(
        "posts the ante $0.10",
        "posts the ante $0.05 and is all-in",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("all-in-antes.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "unsupported_ante_structure"
    assert diagnostic.line_start == 6
    assert diagnostic.line_end == 8


def test_short_all_in_ante_preserves_contribution_and_uses_nominal_amount() -> None:
    source = """PokerStars Hand #900000000009: Hold'em No Limit ($0.50/$1.00 USD) - 2026/08/30 12:42:56 ET
Table 'Synthetic Short Ante' 3-max Seat #1 is the button
Seat 1: Ante Hero ($100.00 in chips)
Seat 2: Ante Small ($100.00 in chips)
Seat 3: Ante Big ($0.05 in chips)
Ante Hero: posts the ante $0.10
Ante Small: posts the ante $0.10
Ante Big: posts the ante $0.05 and is all-in
Ante Small: posts small blind $0.50
*** HOLE CARDS ***
Dealt to Ante Hero [7s 6s]
"""

    result = parse_pokerstars_text(
        source,
        context=import_context("short-all-in-ante.txt"),
    )

    assert result.diagnostics == ()
    state = result.hands[0].candidate.detection.state
    assert state.game.blinds.ante == Decimal("0.10")
    assert state.game.blinds.ante_mode == "per_player"
    big_ante = next(
        action
        for action in state.streets[0].actions
        if action.action_type == "post_ante" and action.actor_id == "seat-3"
    )
    assert big_ante.amount == Decimal("0.05")
    assert big_ante.all_in is True


def test_straddle_value_retains_its_post_evidence() -> None:
    source = synthetic_straddle_source(
        "Straddle Rival: posts straddle $2.00",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("straddle.txt"),
    )

    assert result.diagnostics == ()
    parsed = result.hands[0]
    assert str(parsed.candidate.detection.state.game.blinds.straddle) == "2.00"
    straddle_evidence = parsed.candidate.detection.field_evidence[
        "/game/blinds/straddle"
    ]
    assert [source.line_start for source in straddle_evidence.evidence] == [9]


def test_unsupported_straddles_point_to_the_post_lines() -> None:
    source = synthetic_straddle_source(
        "Straddle Rival: posts straddle $2.00",
        "Straddle Hero: posts straddle $4.00",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("unsupported-straddles.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "unsupported_straddle_structure"
    assert diagnostic.line_start == 9
    assert diagnostic.line_end == 10


def test_short_all_in_straddle_does_not_establish_a_nominal_amount() -> None:
    source = synthetic_straddle_source(
        "Straddle Rival: posts straddle $1.50 and is all-in",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("short-all-in-straddle.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "unsupported_straddle_structure"
    assert diagnostic.line_start == 9
    assert diagnostic.line_end == 9


def test_seat_outside_the_table_points_to_the_seat_line() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Seat 6: Big Synthetic",
        "Seat 7: Big Synthetic",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("seat-outside-table.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "seat_outside_table"
    assert diagnostic.line_start == 6
    assert diagnostic.line_end == 6


@pytest.mark.parametrize("button_seat", [2, 3])
def test_unresolved_button_is_isolated_from_a_valid_sibling(button_seat: int) -> None:
    invalid = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Seat #1 is the button",
        f"Seat #{button_seat} is the button",
    )
    valid = (FIXTURES / "synthetic-heads-up.txt").read_text()

    result = parse_pokerstars_text(
        f"{invalid}\n\n{valid}",
        context=import_context("unresolved-button.txt"),
    )

    assert [hand.hand_ordinal for hand in result.hands] == [2]
    assert result.hands[0].candidate.raw.identity.source_hand_id == "900000000002"
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "unsupported_button_seat"
    assert diagnostic.hand_ordinal == 1
    assert diagnostic.line_start == 2
    assert diagnostic.line_end == 2


def test_duplicate_seat_number_points_to_the_second_declaration() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Seat 3: Sitting Synthetic",
        "Seat 1: Sitting Synthetic",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("duplicate-seat-number.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "duplicate_seat_number"
    assert diagnostic.line_start == 4


def test_insufficient_dealt_in_ring_points_to_the_seat_declarations() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text()
    source = source.replace(
        "Seat 5: Small Synthetic ($100.00 in chips)",
        "Seat 5: Small Synthetic ($100.00 in chips) is sitting out",
    ).replace(
        "Seat 6: Big Synthetic ($100.00 in chips)",
        "Seat 6: Big Synthetic ($100.00 in chips) is sitting out",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("insufficient-dealt-in-ring.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "insufficient_dealt_in_seats"
    assert diagnostic.line_start == 3
    assert diagnostic.line_end == 6


def test_unsupported_hand_is_isolated_from_valid_sibling() -> None:
    source = (FIXTURES / "synthetic-mixed.txt").read_text()

    result = parse_pokerstars_text(
        source,
        context=import_context("synthetic-mixed.txt"),
    )

    assert [hand.hand_ordinal for hand in result.hands] == [1]
    assert result.hands[0].candidate.raw.identity.source_hand_id == "900000000003"
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.hand_ordinal == 2
    assert diagnostic.source_hand_id == "900000000004"
    assert diagnostic.code == "unsupported_header"
    assert diagnostic.line_start == 17


def test_inter_hand_blank_lines_do_not_change_raw_identity_or_reimport(
    tmp_path: Path,
) -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text()
    sibling = (FIXTURES / "synthetic-ante.txt").read_text()
    standalone = parse_pokerstars_text(
        source,
        context=PokerStarsImportContext(
            import_id="standalone-import",
            imported_at=IMPORTED_AT,
            source_filename="standalone.txt",
        ),
    ).hands[0].candidate
    overlapping = parse_pokerstars_text(
        f"{source}\n\n{sibling}",
        context=PokerStarsImportContext(
            import_id="overlapping-import",
            imported_at=datetime(2026, 9, 2, 10, 1, tzinfo=timezone.utc),
            source_filename="overlapping.txt",
        ),
    ).hands[0].candidate

    assert overlapping.raw.raw_text == standalone.raw.raw_text
    assert overlapping.raw.content_sha256 == standalone.raw.content_sha256
    assert overlapping.raw.raw_source_id != standalone.raw.raw_source_id

    service = ImportedHandIngestionService(store=FileImportedHandStore(tmp_path))
    assert service.ingest(standalone).disposition == "created_pending_review"
    assert service.ingest(overlapping).disposition == "recorded_exact_reimport"


def test_unknown_action_produces_a_structured_rejection() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text().replace(
        "Heads Hero: folds",
        "Heads Hero: requests TIME",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("unknown-action.txt"),
    )

    assert result.hands == ()
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "unsupported_action"
    assert result.diagnostics[0].hand_ordinal == 1


def test_missing_hole_cards_marker_is_rejected() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text().replace(
        "*** HOLE CARDS ***\n",
        "",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("missing-hole-marker.txt"),
    )

    assert result.hands == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "hero_cards_order"
    ]


def test_unsupported_summary_origin_marker_is_not_silently_discarded() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text().replace(
        "Seat 1: Heads Hero (button) (small blind) folded before Flop",
        "Seat 1: Heads Hero (button) (small blind) timed out before Flop",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("automatic-marker.txt"),
    )

    assert result.hands == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "unsupported_summary_result"
    ]


def test_invalid_money_grouping_is_rejected_instead_of_reinterpreted() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text().replace(
        "$0.50/$1.00 USD",
        "$0.50/$1,2 USD",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("invalid-money.txt"),
    )

    assert result.hands == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "unsupported_header"
    ]


def test_zero_action_amount_reports_the_action_line() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text().replace(
        "Heads Hero: folds",
        "Heads Hero: calls $0.00",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("zero-action.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "invalid_action_amount"
    assert diagnostic.line_start == 9


def test_declarations_cannot_follow_forced_posts() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text()
    table = "Table 'Synthetic Heads Up' 2-max Seat #1 is the button\n"
    source = source.replace(table, "").replace(
        "Heads Rival: posts big blind $1.00\n",
        f"Heads Rival: posts big blind $1.00\n{table}",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("late-table.txt"),
    )

    assert result.hands == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "declaration_order"
    ]


def test_summary_position_tags_must_match_the_dealt_in_ring() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text().replace(
        "Heads Hero (button) (small blind) folded",
        "Heads Hero (big blind) folded",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("position-mismatch.txt"),
    )

    assert result.hands == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "summary_position_mismatch"
    ]


def test_reconciliation_failure_is_an_explicit_non_clean_disposition() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text().replace(
        "Total pot $1.00 | Rake $0.00",
        "Total pot $2.00 | Rake $0.00",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("bad-total.txt"),
    )

    assert result.diagnostics == ()
    assert result.hands[0].disposition == "reconciliation_failed"
    assert result.hands[0].reconciliation.status == "fail"
    assert result.hands[0].candidate.detection.warnings[-1] == (
        "Pot reconciliation failed; review action amounts and source totals."
    )


def test_unsupported_total_pot_suffix_is_not_silently_discarded() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text().replace(
        "Total pot $1.00 | Rake $0.00",
        "Total pot $1.00 | Rake $0.00 | Jackpot $0.50",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("unsupported-pot-suffix.txt"),
    )

    assert result.hands == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "unsupported_summary_line"
    ]


def test_unsupported_showdown_suffix_is_not_silently_discarded() -> None:
    source = (FIXTURES / "synthetic-flop.txt").read_text().replace(
        "Uncalled bet ($1.00) returned to Flop Hero\n",
        (
            "Uncalled bet ($1.00) returned to Flop Hero\n"
            "*** SHOW DOWN ***\n"
            "Flop Hero: shows [Ad Qd] and collected $2.00\n"
        ),
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("unsupported-showdown-suffix.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "unsupported_showdown"
    assert diagnostic.line_start == 17


def test_exact_shown_cards_syntax_is_supported() -> None:
    source = (FIXTURES / "synthetic-flop.txt").read_text().replace(
        "Uncalled bet ($1.00) returned to Flop Hero\n",
        (
            "Uncalled bet ($1.00) returned to Flop Hero\n"
            "*** SHOW DOWN ***\n"
            "Flop Hero: shows [Ad Qd]\n"
        ),
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("exact-showdown.txt"),
    )

    assert result.diagnostics == ()
    showdown = result.hands[0].candidate.detection.state.results.showdown
    assert len(showdown) == 1
    assert [card.code for card in showdown[0].cards] == ["Ad", "Qd"]


@pytest.mark.parametrize(
    ("player", "cards", "expected_code"),
    [
        ("Flop Rival", "5s 5s", "duplicate_showdown_card"),
        ("Flop Rival", "2c 5s", "showdown_card_collision"),
        ("Flop Hero", "Ac Qd", "hero_showdown_mismatch"),
    ],
)
def test_showdown_card_conflict_points_to_shown_cards_line(
    player: str,
    cards: str,
    expected_code: str,
) -> None:
    source = (FIXTURES / "synthetic-flop.txt").read_text()
    prefix, _ = source.split("Flop Rival: folds", 1)
    source = prefix + f"*** SHOW DOWN ***\n{player}: shows [{cards}]\n"

    result = parse_pokerstars_text(
        source,
        context=import_context("showdown-card-conflict.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == expected_code
    assert diagnostic.line_start == 15
    assert diagnostic.line_end == 15


def test_duplicate_showdown_player_points_to_second_entry() -> None:
    source = (FIXTURES / "synthetic-flop.txt").read_text()
    prefix, _ = source.split("Flop Rival: folds", 1)
    source = (
        prefix
        + "*** SHOW DOWN ***\n"
        + "Flop Hero: shows [Ad Qd]\n"
        + "Flop Hero: shows [Ad Qd]\n"
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("duplicate-showdown-player.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "duplicate_showdown_entry"
    assert diagnostic.line_start == 16
    assert diagnostic.line_end == 16


@pytest.mark.parametrize(
    ("later_line", "expected_code"),
    [
        ("Heads Hero: folds", "award_order"),
        (
            "Uncalled bet ($0.50) returned to Heads Rival",
            "uncalled_return_order",
        ),
        ("*** FLOP *** [2c 3d 4h]", "street_order"),
        ("*** SHOW DOWN ***", "showdown_order"),
    ],
)
def test_pot_award_ends_table_action_evidence(
    later_line: str,
    expected_code: str,
) -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text()
    prefix, _ = source.split("Heads Hero: folds", 1)
    source = (
        prefix
        + "Heads Rival collected $1.00 from pot\n"
        + later_line
        + "\n"
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("action-after-award.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.line_start == 10
    assert diagnostic.code == expected_code


def test_pot_award_rejects_later_hero_cards() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text()
    dealt = "Dealt to Heads Hero [Qc Jh]\n"
    prefix, _ = source.split(dealt, 1)
    source = prefix + "Heads Rival collected $1.00 from pot\n" + dealt

    result = parse_pokerstars_text(
        source,
        context=import_context("hero-cards-after-award.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "hero_cards_order"
    assert diagnostic.line_start == 9


def test_hero_cards_must_precede_the_first_non_forced_action() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text()
    dealt = "Dealt to Heads Hero [Qc Jh]\n"
    source = source.replace(dealt, "").replace(
        "Heads Hero: folds\n",
        "Heads Hero: folds\n" + dealt,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("late-hero-cards.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "hero_cards_order"
    assert diagnostic.line_start == 9


def test_sitting_out_player_cannot_be_assigned_as_hero() -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        "Dealt to Hero Synthetic [As Kd]",
        "Dealt to Sitting Synthetic [As Kd]",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("sitting-out-hero.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "hero_not_dealt_in"
    assert diagnostic.line_start == 10
    assert diagnostic.line_end == 10


@pytest.mark.parametrize(
    ("old", "new", "expected_line"),
    [
        (
            "Hero Synthetic: raises $2.00 to $3.00",
            "Sitting Synthetic: raises $2.00 to $3.00",
            11,
        ),
        (
            "Uncalled bet ($2.00) returned to Hero Synthetic",
            "Uncalled bet ($2.00) returned to Sitting Synthetic",
            14,
        ),
        (
            "Hero Synthetic collected $2.50 from pot",
            "Sitting Synthetic collected $2.50 from pot",
            15,
        ),
        (
            "Hero Synthetic collected $2.50 from pot",
            "*** SHOW DOWN ***\n"
            "Sitting Synthetic: shows [2c 3d]\n"
            "Hero Synthetic collected $2.50 from pot",
            16,
        ),
    ],
)
def test_sitting_out_table_participant_is_rejected_at_source_line(
    old: str,
    new: str,
    expected_line: int,
) -> None:
    source = (FIXTURES / "synthetic-cash-sitout.txt").read_text().replace(
        old,
        new,
        1,
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("sitting-out-participant.txt"),
    )

    assert result.hands == ()
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "actor_not_dealt_in"
    assert diagnostic.line_start == expected_line
    assert diagnostic.line_end == expected_line


def test_occurrence_ids_are_deterministic_but_import_context_bound(
    tmp_path: Path,
) -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text()
    first = parse_pokerstars_text(
        source,
        context=import_context("synthetic-heads-up.txt"),
    ).hands[0]
    replay = parse_pokerstars_text(
        source,
        context=import_context("synthetic-heads-up.txt"),
    ).hands[0]
    later = parse_pokerstars_text(
        source,
        context=PokerStarsImportContext(
            import_id="different-import",
            imported_at=IMPORTED_AT,
            source_filename="synthetic-heads-up.txt",
        ),
    ).hands[0]
    altered = parse_pokerstars_text(
        source.replace("Dealt to Heads Hero [Qc Jh]", "Dealt to Heads Hero [Qd Jc]"),
        context=import_context("synthetic-heads-up.txt"),
    ).hands[0]

    assert replay.candidate == first.candidate
    assert replay.reconciliation == first.reconciliation
    assert later.candidate.raw.identity == first.candidate.raw.identity
    assert later.candidate.raw.raw_source_id != first.candidate.raw.raw_source_id
    assert (
        altered.candidate.raw.provenance.import_id
        == first.candidate.raw.provenance.import_id
    )
    service = ImportedHandIngestionService(store=FileImportedHandStore(tmp_path))
    service.ingest(first.candidate)
    with pytest.raises(ImportedHandImportIdConflict):
        service.ingest(altered.candidate)


def test_missing_headers_return_a_file_diagnostic() -> None:
    result = parse_pokerstars_text(
        "not a hand\n",
        context=import_context("invalid.txt"),
    )

    assert result.hands == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "no_hand_headers"
    ]


def test_non_empty_preamble_rejects_the_file_without_losing_audit_silently() -> None:
    source = "export revision: unknown\n" + (
        FIXTURES / "synthetic-heads-up.txt"
    ).read_text()

    result = parse_pokerstars_text(
        source,
        context=import_context("preamble.txt"),
    )

    assert result.hands == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "unsupported_preamble"
    ]


def test_source_filename_rejects_local_path_metadata() -> None:
    with pytest.raises(ValueError, match="basename"):
        parse_pokerstars_text(
            (FIXTURES / "synthetic-heads-up.txt").read_text(),
            context=PokerStarsImportContext(
                import_id="path-metadata",
                imported_at=IMPORTED_AT,
                source_filename="/Users/example/private/history.txt",
            ),
        )


def test_ambiguous_et_timestamp_is_rejected_instead_of_guessed() -> None:
    source = (FIXTURES / "synthetic-heads-up.txt").read_text().replace(
        "2026/08/30 12:35:56 ET",
        "2026/11/01 01:30:00 ET",
    )

    result = parse_pokerstars_text(
        source,
        context=import_context("ambiguous-time.txt"),
    )

    assert result.hands == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "ambiguous_source_time"
    ]
