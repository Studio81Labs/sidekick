from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from app.application.imported_hand_ingestion import ImportedHandIngestionService
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
    assert parsed.reconciliation.status == "pass"
    assert parsed.disposition == "clean"
    assert parsed.reconciliation.derived_gross_total == state.results.stated_pot.gross_total
    table_size_evidence = candidate.detection.field_evidence["/game/table_size"]
    assert table_size_evidence.evidence[0].line_start == 2
    assert table_size_evidence.evidence[0].excerpt.startswith("Table 'Synthetic Alpha'")
    betting_limit_evidence = candidate.detection.field_evidence[
        "/game/betting_limit"
    ]
    assert betting_limit_evidence.evidence[0].line_start == 1
    assert "No Limit" in betting_limit_evidence.evidence[0].excerpt
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


def test_occurrence_ids_are_deterministic_but_import_context_bound() -> None:
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

    assert replay.candidate == first.candidate
    assert replay.reconciliation == first.reconciliation
    assert later.candidate.raw.identity == first.candidate.raw.identity
    assert later.candidate.raw.raw_source_id != first.candidate.raw.raw_source_id


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
