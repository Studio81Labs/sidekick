from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import ValidationError

from app.domain.hands import JobRecord
from app.domain.imported_hands import (
    ActionOrigin,
    CanonicalHandRevision,
    DeletionReceipt,
    DeletionRequest,
    DetectedImportedHand,
    ImportProvenance,
    ImportedAction,
    ImportedHandLifecycle,
    ImportedHandRecord,
    ImportedHandState,
    ImportedSeat,
    RawHandHistory,
    SourceChronology,
    SourceEvidence,
    StableHandIdentity,
    StatedPotSummary,
    StructuralPosition,
    TournamentEconomics,
    UserCorrection,
    classify_reimport,
    classify_restore,
    derive_structural_positions,
    imported_hand_state_sha256,
    structural_position_labels,
)


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
IDENTITY = StableHandIdentity(site="pokerstars", source_hand_id="123456789")


def evidence(raw_source_id: str = "file-1") -> dict[str, object]:
    return {
        "raw_source_id": raw_source_id,
        "line_start": 1,
        "excerpt": "PokerStars Hand #123456789",
    }


def chronology(raw_source_id: str = "file-1") -> SourceChronology:
    return SourceChronology(
        played_at=None,
        source_timezone=None,
        source_session_id="session-1",
        source_file_id=raw_source_id,
        hand_ordinal=1,
    )


def raw_source(
    *,
    raw_source_id: str = "file-1",
    raw_text: str = "PokerStars Hand #123456789\n",
    identity: StableHandIdentity = IDENTITY,
) -> RawHandHistory:
    return RawHandHistory(
        raw_source_id=raw_source_id,
        identity=identity,
        chronology=chronology(raw_source_id),
        provenance=ImportProvenance(
            import_id=f"import-{raw_source_id}",
            imported_at=NOW,
            adapter_id="pokerstars",
            adapter_version="1.0.0",
            format_revision="pokerstars-text/v1",
            source_filename="HH20260827.txt",
        ),
        content_sha256=sha256(raw_text.encode()).hexdigest(),
        raw_text=raw_text,
    )


def seats() -> list[ImportedSeat]:
    return [
        ImportedSeat(
            seat_number=1,
            player_id="hero",
            starting_stack=Decimal("100"),
            participation="dealt_in",
        ),
        ImportedSeat(
            seat_number=2,
            player_id="villain",
            starting_stack=Decimal("100"),
            participation="dealt_in",
        ),
    ]


def hand_state(*, hero_player_id: str | None = None) -> ImportedHandState:
    return ImportedHandState(
        identity=IDENTITY,
        chronology=chronology(),
        game={
            "betting_limit": "no_limit",
            "table_size": 2,
            "blinds": {
                "small_blind": Decimal("0.50"),
                "big_blind": Decimal("1.00"),
                "ante": None,
            },
            "economics": {"kind": "unknown", "reason": "not supplied"},
        },
        button_seat=None,
        seats=seats(),
        hero_player_id=hero_player_id,
        hero_cards=[],
        streets=[{"street": "preflop", "actions": []}],
    )


def detected(state: ImportedHandState | None = None) -> DetectedImportedHand:
    detected_state = state or hand_state()
    return DetectedImportedHand(
        detection_id="detection-1",
        raw_source_id="file-1",
        detector_id="pokerstars",
        detector_version="1.0.0",
        detected_at=NOW,
        state=detected_state,
        field_evidence={
            "/hero_player_id": {
                "confidence": Decimal("0.40"),
                "evidence": [evidence()],
                "warnings": ["Hero line was absent"],
            }
        },
        warnings=["Review hero identity"],
        content_sha256=imported_hand_state_sha256(detected_state),
    )


def revision() -> CanonicalHandRevision:
    return CanonicalHandRevision(
        revision=1,
        detection_id="detection-1",
        approved_at=NOW,
        state=hand_state(hero_player_id="hero"),
        corrections=[
            UserCorrection(
                field_pointer="/hero_player_id",
                detected_value=None,
                approved_value="hero",
                corrected_at=NOW,
                reason="Confirmed from the dealt-to line",
            )
        ],
    )


def active_record() -> ImportedHandRecord:
    return ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected()],
        canonical_revisions=[revision()],
        lifecycle=ImportedHandLifecycle(
            status="active",
            active_canonical_revision=1,
            changed_at=NOW,
        ),
    )


def test_missing_source_time_and_economics_stay_explicitly_unknown() -> None:
    state = hand_state()

    restored = ImportedHandState.model_validate_json(state.model_dump_json())

    assert restored.chronology.played_at is None
    assert restored.chronology.source_timezone is None
    assert restored.game.economics.kind == "unknown"
    assert restored.game.blinds.ante is None


@pytest.mark.parametrize("field", ["excerpt", "marker"])
@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_source_evidence_rejects_blank_text_locators(
    field: str,
    blank: str,
) -> None:
    payload: dict[str, object] = {
        "raw_source_id": "file-1",
        "line_start": 1,
        field: blank,
    }

    with pytest.raises(ValidationError, match="text locators cannot be empty"):
        SourceEvidence.model_validate(payload)


def test_source_evidence_preserves_meaningful_locator_whitespace() -> None:
    source = SourceEvidence(
        raw_source_id="file-1",
        excerpt="  PokerStars Hand #123456789  ",
    )

    assert source.excerpt == "  PokerStars Hand #123456789  "


def test_source_evidence_accepts_line_only_and_non_empty_text_only_locators() -> None:
    line_only = SourceEvidence(raw_source_id="file-1", line_start=1)
    excerpt_only = SourceEvidence(raw_source_id="file-1", excerpt="Hand #1")
    marker_only = SourceEvidence(raw_source_id="file-1", marker="hand-start")

    assert line_only.excerpt is None
    assert excerpt_only.line_start is None
    assert marker_only.line_start is None


def test_dealt_in_seat_rejects_a_known_zero_starting_stack() -> None:
    with pytest.raises(ValidationError, match="positive known starting stack"):
        ImportedSeat(
            seat_number=1,
            player_id="hero",
            starting_stack=Decimal(0),
            participation="dealt_in",
        )


@pytest.mark.parametrize("starting_stack", [None, Decimal("0.01")])
def test_dealt_in_seat_accepts_unknown_or_positive_starting_stack(
    starting_stack: Decimal | None,
) -> None:
    seat = ImportedSeat(
        seat_number=1,
        player_id="hero",
        starting_stack=starting_stack,
        participation="dealt_in",
    )

    assert seat.starting_stack == starting_stack


@pytest.mark.parametrize("participation", ["unknown", "sitting_out", "not_dealt"])
def test_known_zero_stack_remains_valid_for_non_dealt_in_seats(
    participation: str,
) -> None:
    seat = ImportedSeat(
        seat_number=1,
        player_id="hero",
        starting_stack=Decimal(0),
        participation=participation,
    )

    assert seat.starting_stack == 0


def test_zero_stack_dealt_in_hero_cannot_enter_the_canonical_state() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal(0)
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "hero",
                    "action_type": "check",
                    "total_committed": Decimal(0),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                }
            ],
        }
    ]

    with pytest.raises(ValidationError, match="positive known starting stack"):
        ImportedHandState.model_validate(payload)


def complete_tournament_economics() -> dict[str, object]:
    return {
        "tournament_id": "tournament-1",
        "tournament_type": "multi-table",
        "stage": "final-table",
        "currency": "USD",
        "paid_places": 2,
        "players_remaining": 3,
        "payouts": [
            {
                "place_from": 1,
                "place_to": 1,
                "share": Decimal("0.60"),
            },
            {
                "place_from": 2,
                "place_to": 2,
                "share": Decimal("0.40"),
            },
        ],
        "remaining_stacks": [
            {"player_id": "hero", "stack": Decimal("40")},
            {"player_id": "villain", "stack": Decimal("30")},
            {"player_id": "third-player", "stack": Decimal("20")},
        ],
        "icm_inputs_complete": True,
    }


def test_complete_icm_inputs_require_concrete_values_and_coherent_coverage() -> None:
    complete = complete_tournament_economics()
    economics = TournamentEconomics.model_validate(complete)
    assert economics.icm_inputs_complete is True

    missing_payout = complete_tournament_economics()
    missing_payout["payouts"][0]["share"] = None
    with pytest.raises(ValidationError, match="exactly one amount or share"):
        TournamentEconomics.model_validate(missing_payout)

    missing_stack = complete_tournament_economics()
    missing_stack["remaining_stacks"][0]["stack"] = None
    with pytest.raises(ValidationError, match="positive remaining stacks"):
        TournamentEconomics.model_validate(missing_stack)

    incomplete_stack_field = complete_tournament_economics()
    incomplete_stack_field["remaining_stacks"].pop()
    with pytest.raises(ValidationError, match="one remaining stack per player"):
        TournamentEconomics.model_validate(incomplete_stack_field)

    payout_gap = complete_tournament_economics()
    payout_gap["payouts"][1]["place_from"] = 3
    payout_gap["payouts"][1]["place_to"] = 3
    with pytest.raises(ValidationError, match="contiguous from first place"):
        TournamentEconomics.model_validate(payout_gap)

    bad_share_total = complete_tournament_economics()
    bad_share_total["payouts"][1]["share"] = Decimal("0.30")
    with pytest.raises(ValidationError, match="shares must sum to one"):
        TournamentEconomics.model_validate(bad_share_total)


def test_complete_bounty_icm_inputs_cover_every_remaining_player() -> None:
    complete = complete_tournament_economics()
    complete["bounty_format"] = "progressive-knockout"
    complete["bounties"] = [
        {"player_id": "hero", "value": Decimal("25")},
        {"player_id": "villain", "value": Decimal("10")},
        {"player_id": "third-player", "value": Decimal("5")},
    ]
    assert TournamentEconomics.model_validate(complete).icm_inputs_complete is True

    complete["bounties"][2]["player_id"] = "unrelated-player"
    with pytest.raises(ValidationError, match="cover the remaining players"):
        TournamentEconomics.model_validate(complete)


def test_paid_places_are_independent_from_the_remaining_field() -> None:
    late_stage = TournamentEconomics(
        paid_places=100,
        players_remaining=50,
        icm_inputs_complete=False,
    )
    assert late_stage.paid_places == 100
    assert late_stage.players_remaining == 50

    complete = complete_tournament_economics()
    complete["paid_places"] = 3
    complete["players_remaining"] = 2
    complete["remaining_stacks"].pop()
    complete["payouts"][1]["share"] = Decimal("0.30")

    economics = TournamentEconomics.model_validate(complete)
    assert economics.icm_inputs_complete is True
    assert economics.paid_places > economics.players_remaining


def test_stated_net_pot_cannot_exceed_gross_when_rake_is_unknown() -> None:
    with pytest.raises(ValidationError, match="net_total cannot exceed gross_total"):
        StatedPotSummary(
            gross_total=Decimal("2"),
            rake=None,
            net_total=Decimal("3"),
        )

    summary = StatedPotSummary(
        gross_total=Decimal("2"),
        rake=None,
        net_total=Decimal("1.5"),
    )
    assert summary.net_total == Decimal("1.5")


@pytest.mark.parametrize(
    "payload",
    [
        {"gross_pots": [Decimal("2")], "net_total": Decimal("3")},
        {"gross_pots": [Decimal("2")], "rake": Decimal("3")},
        {
            "gross_pots": [Decimal("2")],
            "rake": Decimal("0.5"),
            "net_total": Decimal("1.6"),
        },
    ],
)
def test_stated_gross_components_constrain_net_and_rake(
    payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        StatedPotSummary.model_validate(payload)

    summary = StatedPotSummary(
        gross_pots=[Decimal("2")],
        rake=Decimal("0.5"),
        net_total=Decimal("1.5"),
    )
    assert summary.net_total == Decimal("1.5")


def test_import_boundary_rejects_legacy_screenshot_provenance() -> None:
    payload = raw_source().model_dump()
    payload["provenance"] = {
        **payload["provenance"],
        "source_kind": "screenshot",
    }

    with pytest.raises(ValidationError, match="hand_history"):
        RawHandHistory.model_validate(payload)

    # The legacy model remains a separate, valid audit contract.
    legacy = JobRecord(
        original_filename="table.png",
        image_filename="original.png",
        parser_provider="mock",
        recommendation_provider="mock",
    )
    assert legacy.approved_state is None


def test_source_chronology_requires_timezone_aware_play_time() -> None:
    with pytest.raises(ValidationError):
        SourceChronology(
            played_at=datetime(2026, 8, 27, 12, 0),
            source_file_id="file-1",
        )

    with pytest.raises(ValidationError, match="source_timezone requires played_at"):
        SourceChronology(
            played_at=None,
            source_timezone="Europe/Prague",
            source_file_id="file-1",
        )


def test_position_derivation_skips_sitting_out_seats_and_preserves_full_ring_labels() -> None:
    table = [
        ImportedSeat(
            seat_number=number,
            player_id=f"p{number}",
            participation="sitting_out" if number == 5 else "dealt_in",
        )
        for number in range(1, 10)
    ]

    positions = derive_structural_positions(table, button_seat=9)

    assert 5 not in positions
    assert positions[9].display_label == "BTN"
    assert positions[1].display_label == "SB"
    assert positions[2].display_label == "BB"
    assert positions[3].display_label == "UTG"
    assert positions[4].display_label == "UTG+1"
    assert positions[6].display_label == "LJ"
    assert positions[8].display_label == "CO"
    assert positions[3].action_index == 0
    assert {position.dealt_in_player_count for position in positions.values()} == {8}


def test_structural_position_labels_cover_every_seat_from_heads_up_through_ten_max(
) -> None:
    for dealt_in_count in range(2, 11):
        labels = structural_position_labels(dealt_in_count)

        assert len(labels) == dealt_in_count
        assert len(labels) == len(set(labels))


@pytest.mark.parametrize(
    ("dealt_in_count", "expected_early_positions"),
    [
        (9, ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO"]),
        (10, ["UTG", "UTG+1", "UTG+2", "UTG+3", "LJ", "HJ", "CO"]),
    ],
)
def test_full_ring_position_labels_preserve_distinct_early_seats(
    dealt_in_count: int,
    expected_early_positions: list[str],
) -> None:
    assert structural_position_labels(dealt_in_count) == [
        "BTN",
        "SB",
        "BB",
        *expected_early_positions,
    ]


def test_heads_up_position_derivation_makes_button_the_small_blind() -> None:
    positions = derive_structural_positions(seats(), button_seat=1)

    assert positions[1].display_label == "BTN/SB"
    assert positions[1].action_index == 0
    assert positions[2].display_label == "BB"
    assert positions[2].button_distance == 1


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("display_label", "BB", "display_label must match"),
        ("action_index", 0, "action_index must match"),
    ],
)
def test_structural_position_fields_must_agree_without_a_seat_ring(
    field: str, value: object, message: str
) -> None:
    payload: dict[str, object] = {
        "dealt_in_player_count": 6,
        "action_index": 3,
        "button_distance": 0,
        "display_label": "BTN",
    }
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        StructuralPosition.model_validate(payload)


def test_hand_rejects_a_structural_position_shifted_by_a_sitting_out_seat() -> None:
    positioned = seats()
    positioned[0].position = {
        "dealt_in_player_count": 2,
        "action_index": 1,
        "button_distance": 1,
        "display_label": "BB",
    }

    with pytest.raises(ValidationError, match="does not match the dealt-in ring"):
        ImportedHandState(
            identity=IDENTITY,
            chronology=chronology(),
            game={
                "betting_limit": "no_limit",
                "table_size": 2,
                "blinds": {},
                "economics": {"kind": "unknown"},
            },
            button_seat=1,
            seats=positioned,
            streets=[{"street": "preflop"}],
        )


def test_supplied_position_count_must_match_the_actual_dealt_ring() -> None:
    payload = hand_state().model_dump()
    payload["button_seat"] = None
    payload["seats"][0]["position"] = {
        "dealt_in_player_count": 3,
        "action_index": 0,
        "button_distance": 0,
        "display_label": "BTN",
    }

    with pytest.raises(ValidationError, match="match the actual dealt-in ring"):
        ImportedHandState.model_validate(payload)


def test_supplied_positions_must_be_unique_without_a_live_button() -> None:
    payload = hand_state().model_dump()
    payload["button_seat"] = None
    duplicate = {
        "dealt_in_player_count": 2,
        "action_index": 0,
        "button_distance": 0,
        "display_label": "BTN/SB",
    }
    payload["seats"][0]["position"] = duplicate
    payload["seats"][1]["position"] = duplicate

    with pytest.raises(ValidationError, match="must have unique"):
        ImportedHandState.model_validate(payload)


def test_partial_unique_positions_remain_reviewable_without_a_button() -> None:
    payload = hand_state().model_dump()
    payload["button_seat"] = None
    payload["seats"][0]["position"] = {
        "dealt_in_player_count": 2,
        "action_index": 0,
        "button_distance": 0,
        "display_label": "BTN/SB",
    }

    state = ImportedHandState.model_validate(payload)

    assert state.seats[0].position is not None
    assert state.seats[1].position is None


def test_board_prefix_survives_an_unknown_intermediate_street() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {"street": "preflop", "actions": []},
        {
            "street": "flop",
            "board_cards": [
                {"rank": "A", "suit": "spades"},
                {"rank": "K", "suit": "hearts"},
                {"rank": "2", "suit": "clubs"},
            ],
            "actions": [],
        },
        {"street": "turn", "board_cards": [], "actions": []},
        {
            "street": "river",
            "board_cards": [
                {"rank": "A", "suit": "spades"},
                {"rank": "Q", "suit": "hearts"},
                {"rank": "2", "suit": "clubs"},
                {"rank": "4", "suit": "diamonds"},
                {"rank": "5", "suit": "spades"},
            ],
            "actions": [],
        },
    ]

    with pytest.raises(ValidationError, match="preserve the earlier board prefix"):
        ImportedHandState.model_validate(payload)


def test_unmarked_action_needs_versioned_semantics_to_be_player_selected() -> None:
    base = {
        "kind": "player_selected",
        "basis": "versioned_absence_semantics",
        "confidence": Decimal("0.90"),
        "evidence": [evidence()],
    }
    with pytest.raises(ValidationError, match="semantics revision"):
        ActionOrigin(**base)

    origin = ActionOrigin(
        **base,
        semantics_revision="pokerstars-actions/v3",
    )
    action = ImportedAction(
        sequence=0,
        actor_id="hero",
        action_type="fold",
        total_committed=Decimal("0.50"),
        origin=origin,
        evidence=[evidence()],
    )
    assert action.is_player_decision is True


@pytest.mark.parametrize(
    ("kind", "basis", "reason"),
    [
        ("unknown", "unresolved", None),
        ("client_automatic", "explicit_marker", "timeout"),
    ],
)
def test_unknown_and_client_automatic_actions_are_not_player_decisions(
    kind: str,
    basis: str,
    reason: str | None,
) -> None:
    action = ImportedAction(
        sequence=0,
        actor_id="hero",
        action_type="fold",
        total_committed=Decimal("0.50"),
        origin={
            "kind": kind,
            "basis": basis,
            "confidence": None,
            "evidence": [evidence()],
            "automatic_reason": reason,
        },
        evidence=[evidence()],
    )

    assert action.is_player_decision is False


def test_reimport_classification_is_idempotent_or_conflicting_by_stable_identity() -> None:
    existing = raw_source()

    exact = classify_reimport(
        [existing],
        raw_source(raw_source_id="file-2"),
    )
    conflict = classify_reimport(
        [existing],
        raw_source(raw_source_id="file-2", raw_text="materially different\n"),
    )
    new = classify_reimport(
        [existing],
        raw_source(
            raw_source_id="file-2",
            identity=StableHandIdentity(site="pokerstars", source_hand_id="987"),
        ),
    )

    assert exact.kind == "exact_reimport"
    assert exact.existing_raw_source_id == "file-1"
    assert conflict.kind == "identity_conflict"
    assert new.kind == "new_identity"


def test_materially_different_detected_content_is_an_explicit_conflict() -> None:
    existing_raw = raw_source()
    candidate_raw = raw_source(raw_source_id="file-2")
    prior_detection = detected()
    candidate_state = hand_state(hero_player_id="villain").model_copy(
        update={"chronology": chronology("file-2")}
    )
    candidate_detection = DetectedImportedHand(
        detection_id="detection-2",
        raw_source_id="file-2",
        detector_id="pokerstars",
        detector_version="1.0.0",
        detected_at=NOW,
        state=candidate_state,
        content_sha256=imported_hand_state_sha256(candidate_state),
    )

    disposition = classify_reimport(
        [existing_raw],
        candidate_raw,
        existing_detections=[prior_detection],
        candidate_detection=candidate_detection,
    )

    assert disposition.kind == "identity_conflict"


def test_exact_reimport_ignores_source_location_in_detected_fingerprint() -> None:
    def detected_from_source(raw_source_id: str) -> DetectedImportedHand:
        payload = hand_state(hero_player_id="hero").model_dump()
        payload["chronology"] = chronology(raw_source_id).model_dump()
        payload["streets"] = [
            {
                "street": "preflop",
                "actions": [
                    {
                        "sequence": 0,
                        "actor_id": "hero",
                        "action_type": "fold",
                        "total_committed": Decimal("0"),
                        "origin": {
                            "kind": "player_selected",
                            "basis": "explicit_marker",
                            "evidence": [evidence(raw_source_id)],
                        },
                        "evidence": [evidence(raw_source_id)],
                    }
                ],
            }
        ]
        state = ImportedHandState.model_validate(payload)
        return DetectedImportedHand(
            detection_id=f"detection-{raw_source_id}",
            raw_source_id=raw_source_id,
            detector_id="pokerstars",
            detector_version="1.0.0",
            detected_at=NOW,
            state=state,
            content_sha256=imported_hand_state_sha256(state),
        )

    existing_detection = detected_from_source("file-1")
    candidate_detection = detected_from_source("file-2")

    assert existing_detection.content_sha256 != candidate_detection.content_sha256
    disposition = classify_reimport(
        [raw_source()],
        raw_source(raw_source_id="file-2"),
        existing_detections=[existing_detection],
        candidate_detection=candidate_detection,
    )

    assert disposition.kind == "exact_reimport"
    assert disposition.existing_raw_source_id == "file-1"


def test_detected_state_checksum_and_raw_source_link_are_enforced() -> None:
    state = hand_state()

    with pytest.raises(ValidationError, match="normalized detected state"):
        DetectedImportedHand(
            detection_id="detection-bad-hash",
            raw_source_id="file-1",
            detector_id="pokerstars",
            detector_version="1.0.0",
            detected_at=NOW,
            state=state,
            content_sha256="a" * 64,
        )

    with pytest.raises(ValidationError, match="detected raw_source_id"):
        DetectedImportedHand(
            detection_id="detection-wrong-source",
            raw_source_id="file-2",
            detector_id="pokerstars",
            detector_version="1.0.0",
            detected_at=NOW,
            state=state,
            content_sha256=imported_hand_state_sha256(state),
        )


def test_detected_evidence_must_reference_its_single_raw_source() -> None:
    state = hand_state()

    with pytest.raises(ValidationError, match="only the detected raw source"):
        DetectedImportedHand(
            detection_id="detection-wrong-field-evidence",
            raw_source_id="file-1",
            detector_id="pokerstars",
            detector_version="1.0.0",
            detected_at=NOW,
            state=state,
            field_evidence={
                "/hero_player_id": {
                    "evidence": [evidence("missing-file")],
                }
            },
            content_sha256=imported_hand_state_sha256(state),
        )

    payload = hand_state(hero_player_id="hero").model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "hero",
                    "action_type": "fold",
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence("missing-file")],
                    },
                    "evidence": [evidence("missing-file")],
                }
            ],
        }
    ]
    action_state = ImportedHandState.model_validate(payload)
    with pytest.raises(ValidationError, match="only the detected raw source"):
        DetectedImportedHand(
            detection_id="detection-wrong-action-evidence",
            raw_source_id="file-1",
            detector_id="pokerstars",
            detector_version="1.0.0",
            detected_at=NOW,
            state=action_state,
            content_sha256=imported_hand_state_sha256(action_state),
        )


@pytest.mark.parametrize(
    "pointer",
    ["/nonexistent", "/seats/9/player_id", "/seats/01/player_id"],
)
def test_detected_field_evidence_must_resolve_to_a_state_path(pointer: str) -> None:
    state = hand_state()

    with pytest.raises(ValidationError, match="path does not exist in detected state"):
        DetectedImportedHand(
            detection_id="detection-invalid-field-path",
            raw_source_id="file-1",
            detector_id="pokerstars",
            detector_version="1.0.0",
            detected_at=NOW,
            state=state,
            field_evidence={pointer: {"evidence": [evidence()]}},
            content_sha256=imported_hand_state_sha256(state),
        )


def test_canonical_evidence_must_reference_a_retained_raw_source() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "hero",
                    "action_type": "fold",
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence("missing-file")],
                    },
                    "evidence": [evidence("missing-file")],
                }
            ],
        }
    ]
    canonical_state = ImportedHandState.model_validate(payload)

    with pytest.raises(ValidationError, match="retained raw source"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[detected()],
            canonical_revisions=[
                CanonicalHandRevision(
                    revision=1,
                    detection_id="detection-1",
                    approved_at=NOW,
                    state=canonical_state,
                )
            ],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 1,
                "changed_at": NOW,
            },
        )


def test_conflict_detections_must_belong_to_the_conflict_sources() -> None:
    def source_detection(raw_source_id: str) -> DetectedImportedHand:
        payload = hand_state().model_dump()
        payload["chronology"] = chronology(raw_source_id).model_dump()
        state = ImportedHandState.model_validate(payload)
        return DetectedImportedHand(
            detection_id=f"detection-{raw_source_id}",
            raw_source_id=raw_source_id,
            detector_id="pokerstars",
            detector_version="1.0.0",
            detected_at=NOW,
            state=state,
            content_sha256=imported_hand_state_sha256(state),
        )

    with pytest.raises(ValidationError, match="belong to the conflict raw sources"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[
                raw_source(raw_source_id="file-1", raw_text="source one\n"),
                raw_source(raw_source_id="file-2", raw_text="source two\n"),
                raw_source(raw_source_id="file-3", raw_text="source three\n"),
            ],
            detections=[
                source_detection("file-1"),
                source_detection("file-3"),
            ],
            conflicts=[
                {
                    "conflict_id": "conflict-1",
                    "raw_source_ids": ["file-1", "file-2"],
                    "detected_ids": ["detection-file-1", "detection-file-3"],
                    "active_canonical_revision_at_creation": None,
                }
            ],
            lifecycle={"status": "pending_review", "changed_at": NOW},
        )


@pytest.mark.parametrize("status", ["resolved_keep_active", "resolved_use_source"])
def test_active_revision_must_use_the_selected_conflict_source(status: str) -> None:
    def source_detection(raw_source_id: str) -> DetectedImportedHand:
        payload = hand_state().model_dump()
        payload["chronology"] = chronology(raw_source_id).model_dump()
        state = ImportedHandState.model_validate(payload)
        return DetectedImportedHand(
            detection_id=f"detection-{raw_source_id}",
            raw_source_id=raw_source_id,
            detector_id="pokerstars",
            detector_version="1.0.0",
            detected_at=NOW,
            state=state,
            content_sha256=imported_hand_state_sha256(state),
        )

    file_1_detection = source_detection("file-1")
    file_2_detection = source_detection("file-2")

    with pytest.raises(ValidationError, match="use the selected conflict source"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[
                raw_source(raw_source_id="file-1", raw_text="source one\n"),
                raw_source(raw_source_id="file-2", raw_text="source two\n"),
            ],
            detections=[file_1_detection, file_2_detection],
            conflicts=[
                {
                    "conflict_id": "conflict-1",
                    "raw_source_ids": ["file-1", "file-2"],
                    "detected_ids": ["detection-file-1", "detection-file-2"],
                    "active_canonical_revision_at_creation": None,
                    "status": status,
                    "selected_raw_source_id": "file-1",
                    "resolved_at": NOW,
                }
            ],
            canonical_revisions=[
                {
                    "revision": 1,
                    "detection_id": "detection-file-2",
                    "approved_at": NOW,
                    "state": file_2_detection.state,
                }
            ],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 1,
                "changed_at": NOW,
            },
        )


def test_unresolved_conflict_cannot_replace_the_preserved_active_source() -> None:
    def source_detection(raw_source_id: str) -> DetectedImportedHand:
        payload = hand_state().model_dump()
        payload["chronology"] = chronology(raw_source_id).model_dump()
        state = ImportedHandState.model_validate(payload)
        return DetectedImportedHand(
            detection_id=f"detection-{raw_source_id}",
            raw_source_id=raw_source_id,
            detector_id="pokerstars",
            detector_version="1.0.0",
            detected_at=NOW,
            state=state,
            content_sha256=imported_hand_state_sha256(state),
        )

    file_1_detection = source_detection("file-1")
    file_2_detection = source_detection("file-2")

    with pytest.raises(ValidationError, match="cannot replace the preserved active source"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[
                raw_source(raw_source_id="file-1", raw_text="source one\n"),
                raw_source(raw_source_id="file-2", raw_text="source two\n"),
            ],
            detections=[file_1_detection, file_2_detection],
            conflicts=[
                {
                    "conflict_id": "conflict-1",
                    "raw_source_ids": ["file-1", "file-2"],
                    "detected_ids": ["detection-file-1", "detection-file-2"],
                    "active_canonical_revision_at_creation": 1,
                }
            ],
            canonical_revisions=[
                {
                    "revision": 1,
                    "detection_id": "detection-file-1",
                    "approved_at": NOW,
                    "state": file_1_detection.state,
                },
                {
                    "revision": 2,
                    "detection_id": "detection-file-2",
                    "approved_at": NOW,
                    "state": file_2_detection.state,
                },
            ],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 2,
                "changed_at": NOW,
            },
        )


def test_unresolved_conflict_allows_reapproval_from_the_preserved_source() -> None:
    def source_detection(raw_source_id: str) -> DetectedImportedHand:
        payload = hand_state().model_dump()
        payload["chronology"] = chronology(raw_source_id).model_dump()
        state = ImportedHandState.model_validate(payload)
        return DetectedImportedHand(
            detection_id=f"detection-{raw_source_id}",
            raw_source_id=raw_source_id,
            detector_id="pokerstars",
            detector_version="1.0.0",
            detected_at=NOW,
            state=state,
            content_sha256=imported_hand_state_sha256(state),
        )

    file_1_detection = source_detection("file-1")
    file_2_detection = source_detection("file-2")
    record = ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[
            raw_source(raw_source_id="file-1", raw_text="source one\n"),
            raw_source(raw_source_id="file-2", raw_text="source two\n"),
        ],
        detections=[file_1_detection, file_2_detection],
        conflicts=[
            {
                "conflict_id": "conflict-1",
                "raw_source_ids": ["file-1", "file-2"],
                "detected_ids": ["detection-file-1", "detection-file-2"],
                "active_canonical_revision_at_creation": 1,
            }
        ],
        canonical_revisions=[
            {
                "revision": revision_number,
                "detection_id": "detection-file-1",
                "approved_at": NOW,
                "state": file_1_detection.state,
            }
            for revision_number in (1, 2)
        ],
        lifecycle={
            "status": "active",
            "active_canonical_revision": 2,
            "changed_at": NOW,
        },
    )

    assert record.active_state_for_extraction == file_1_detection.state


def test_unresolved_conflict_without_a_prior_revision_cannot_activate_a_source() -> None:
    file_1_detection = detected()

    with pytest.raises(ValidationError, match="without a prior active revision"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[
                raw_source(raw_source_id="file-1", raw_text="source one\n"),
                raw_source(raw_source_id="file-2", raw_text="source two\n"),
            ],
            detections=[file_1_detection],
            conflicts=[
                {
                    "conflict_id": "conflict-1",
                    "raw_source_ids": ["file-1", "file-2"],
                    "detected_ids": ["detection-1"],
                    "active_canonical_revision_at_creation": None,
                }
            ],
            canonical_revisions=[revision()],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 1,
                "changed_at": NOW,
            },
        )


@pytest.mark.parametrize("participation", ["sitting_out", "not_dealt"])
def test_actions_by_known_nonparticipants_are_rejected(participation: str) -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["participation"] = participation
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "hero",
                    "action_type": "fold",
                    "total_committed": Decimal("0.50"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                }
            ],
        }
    ]

    with pytest.raises(ValidationError, match="sitting out or not dealt"):
        ImportedHandState.model_validate(payload)


def test_check_is_rejected_while_facing_a_known_wager() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "villain",
                    "action_type": "bet",
                    "amount": Decimal("2"),
                    "total_committed": Decimal("2"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
                {
                    "sequence": 1,
                    "actor_id": "hero",
                    "action_type": "check",
                    "total_committed": Decimal("0"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
            ],
        }
    ]

    with pytest.raises(ValidationError, match="cannot check while facing"):
        ImportedHandState.model_validate(payload)


def test_check_after_an_unknown_wager_remains_reviewable() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "villain",
                    "action_type": "bet",
                    "origin": {
                        "kind": "unknown",
                        "basis": "unresolved",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
                {
                    "sequence": 1,
                    "actor_id": "hero",
                    "action_type": "check",
                    "origin": {
                        "kind": "unknown",
                        "basis": "unresolved",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].action_type == "check"


@pytest.mark.parametrize(
    ("total", "all_in"),
    [(Decimal("1"), False), (Decimal("3"), False), (Decimal("3"), True)],
)
def test_call_must_match_a_known_wager_or_be_an_all_in_undercall(
    total: Decimal, all_in: bool
) -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "villain",
                    "action_type": "bet",
                    "amount": Decimal("2"),
                    "total_committed": Decimal("2"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
                {
                    "sequence": 1,
                    "actor_id": "hero",
                    "action_type": "call",
                    "amount": total,
                    "total_committed": total,
                    "all_in": all_in,
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
            ],
        }
    ]

    with pytest.raises(ValidationError, match="call must match"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("all_in", [False, True])
def test_call_requires_a_positive_outstanding_wager(all_in: bool) -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {"street": "preflop", "actions": []},
        {
            "street": "flop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "hero",
                    "action_type": "call",
                    "amount": Decimal("1"),
                    "total_committed": Decimal("1"),
                    "all_in": all_in,
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                }
            ],
        },
    ]

    with pytest.raises(ValidationError, match="call requires an outstanding wager"):
        ImportedHandState.model_validate(payload)


def test_unknown_call_amount_cannot_hide_a_known_absence_of_a_wager() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "hero",
                    "action_type": "call",
                    "origin": {
                        "kind": "unknown",
                        "basis": "unresolved",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                }
            ],
        }
    ]

    with pytest.raises(ValidationError, match="call requires an outstanding wager"):
        ImportedHandState.model_validate(payload)


def test_call_after_an_unknown_wager_remains_reviewable() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "villain",
                    "action_type": "bet",
                    "origin": {
                        "kind": "unknown",
                        "basis": "unresolved",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
                {
                    "sequence": 1,
                    "actor_id": "hero",
                    "action_type": "call",
                    "amount": Decimal("1"),
                    "total_committed": Decimal("1"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].action_type == "call"


def test_voluntary_action_after_folds_leave_one_winner_is_rejected() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "villain",
                    "action_type": "fold",
                    "total_committed": Decimal("0"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
                {
                    "sequence": 1,
                    "actor_id": "hero",
                    "action_type": "check",
                    "total_committed": Decimal("0"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
            ],
        }
    ]

    with pytest.raises(ValidationError, match="after folds end the hand"):
        ImportedHandState.model_validate(payload)


def test_sole_winner_can_receive_a_same_street_uncalled_return() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "hero",
                    "action_type": "bet",
                    "amount": Decimal("2"),
                    "total_committed": Decimal("2"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
                {
                    "sequence": 1,
                    "actor_id": "villain",
                    "action_type": "fold",
                    "total_committed": Decimal("0"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
                {
                    "sequence": 2,
                    "actor_id": "hero",
                    "action_type": "uncalled_return",
                    "amount": Decimal("2"),
                    "total_committed": Decimal("0"),
                    "origin": {
                        "kind": "forced_system",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].action_type == "uncalled_return"


def test_one_fold_does_not_end_a_multiway_hand() -> None:
    payload = hand_state().model_dump()
    payload["game"]["table_size"] = 3
    payload["seats"].append(
        {
            "seat_number": 3,
            "player_id": "third-player",
            "starting_stack": Decimal("100"),
            "participation": "dealt_in",
            "position": None,
        }
    )
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "villain",
                    "action_type": "fold",
                    "total_committed": Decimal("0"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
                {
                    "sequence": 1,
                    "actor_id": "hero",
                    "action_type": "check",
                    "total_committed": Decimal("0"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].action_type == "check"


@pytest.mark.parametrize(
    ("action_type", "total", "message"),
    [
        ("bet", Decimal("4"), "bet requires no outstanding wager"),
        ("raise", Decimal("2"), "raise must increase"),
    ],
)
def test_bet_and_raise_labels_must_match_the_known_wager_transition(
    action_type: str, total: Decimal, message: str
) -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "villain",
                    "action_type": "bet",
                    "amount": Decimal("2"),
                    "total_committed": Decimal("2"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
                {
                    "sequence": 1,
                    "actor_id": "hero",
                    "action_type": action_type,
                    "amount": total,
                    "total_committed": total,
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
            ],
        }
    ]

    with pytest.raises(ValidationError, match=message):
        ImportedHandState.model_validate(payload)


def wager_action(
    sequence: int,
    actor_id: str,
    action_type: str,
    *,
    amount: Decimal | None = None,
    total: Decimal | None = None,
    all_in: bool = False,
) -> dict[str, object]:
    forced = action_type.startswith("post_")
    return {
        "sequence": sequence,
        "actor_id": actor_id,
        "action_type": action_type,
        "amount": amount,
        "total_committed": total,
        "all_in": all_in,
        "origin": {
            "kind": "forced_system" if forced else "player_selected",
            "basis": "explicit_marker",
            "evidence": [evidence()],
        },
        "evidence": [evidence()],
    }


def three_player_wager_payload(
    *,
    third_stack: Decimal = Decimal("100"),
) -> dict[str, object]:
    payload = hand_state().model_dump()
    payload["game"]["table_size"] = 3
    payload["seats"].append(
        {
            "seat_number": 3,
            "player_id": "third-player",
            "starting_stack": third_stack,
            "participation": "dealt_in",
            "position": None,
        }
    )
    return payload


def positioned_wager_payload(player_count: int = 3) -> dict[str, object]:
    payload = three_player_wager_payload()
    payload["button_seat"] = 1
    if player_count == 4:
        payload["game"]["table_size"] = 4
        payload["seats"].append(
            {
                "seat_number": 4,
                "player_id": "fourth-player",
                "starting_stack": Decimal("100"),
                "participation": "dealt_in",
                "position": None,
            }
        )
    assert len(payload["seats"]) == player_count
    validated_seats = [
        ImportedSeat.model_validate(seat) for seat in payload["seats"]
    ]
    positions = derive_structural_positions(validated_seats, button_seat=1)
    for seat in payload["seats"]:
        seat["position"] = positions[seat["seat_number"]].model_dump()
    return payload


def three_way_blinds_and_calls() -> list[dict[str, object]]:
    return [
        wager_action(
            0,
            "villain",
            "post_small_blind",
            amount=Decimal("0.5"),
            total=Decimal("0.5"),
        ),
        wager_action(
            1,
            "third-player",
            "post_big_blind",
            amount=Decimal("1"),
            total=Decimal("1"),
        ),
        wager_action(
            2,
            "hero",
            "call",
            amount=Decimal("1"),
            total=Decimal("1"),
        ),
        wager_action(
            3,
            "villain",
            "call",
            amount=Decimal("0.5"),
            total=Decimal("1"),
        ),
        wager_action(4, "third-player", "check", total=Decimal("1")),
    ]


def incomplete_three_way_preflop_payload() -> dict[str, object]:
    payload = three_player_wager_payload()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    2,
                    "third-player",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
            ],
        }
    ]
    return payload


def test_preflop_cannot_advance_with_an_unmatched_small_blind() -> None:
    payload = incomplete_three_way_preflop_payload()
    payload["streets"].append({"street": "flop", "actions": []})

    with pytest.raises(ValidationError, match="has not matched the known wager"):
        ImportedHandState.model_validate(payload)


def test_preflop_can_advance_when_every_active_player_matches() -> None:
    payload = incomplete_three_way_preflop_payload()
    payload["streets"][0]["actions"].append(
        wager_action(
            3,
            "hero",
            "call",
            amount=Decimal("0.5"),
            total=Decimal("1"),
        )
    )
    payload["streets"].append({"street": "flop", "actions": []})

    state = ImportedHandState.model_validate(payload)

    assert len(state.streets) == 2


def test_postflop_cannot_advance_with_an_unmatched_wager() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {"street": "preflop", "actions": []},
        {
            "street": "flop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                )
            ],
        },
        {"street": "turn", "actions": []},
    ]

    with pytest.raises(ValidationError, match="has not matched the known wager"):
        ImportedHandState.model_validate(payload)


def test_results_require_the_final_street_wager_to_be_matched() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                )
            ],
        }
    ]
    payload["results"] = {}

    with pytest.raises(ValidationError, match="has not matched the known wager"):
        ImportedHandState.model_validate(payload)


def test_partial_final_street_without_results_remains_reviewable() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                )
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.results is None


@pytest.mark.parametrize("terminal_kind", ["fold", "all_in"])
def test_folded_and_all_in_players_need_not_match_at_a_street_boundary(
    terminal_kind: str,
) -> None:
    payload = incomplete_three_way_preflop_payload()
    if terminal_kind == "fold":
        payload["streets"][0]["actions"].append(
            wager_action(3, "hero", "fold", total=Decimal("0.5"))
        )
    else:
        payload["seats"][0]["starting_stack"] = Decimal("0.5")
        payload["streets"][0]["actions"][0]["all_in"] = True
    payload["streets"].append({"street": "flop", "actions": []})

    state = ImportedHandState.model_validate(payload)

    assert len(state.streets) == 2


def test_over_stack_raise_cannot_reach_extraction_even_if_excess_is_returned(
) -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "hero",
                    "raise",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
                wager_action(2, "villain", "fold", total=Decimal("1")),
                forced_post(
                    3,
                    "uncalled_return",
                    amount=Decimal("1"),
                    total=Decimal("2"),
                ),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match="hero cumulative commitment 3 exceeds known starting stack 2",
    ):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize(
    ("amount", "total", "message"),
    [
        (None, Decimal("3"), "street commitment 3"),
        (Decimal("3"), None, "chip action amount 3"),
    ],
)
def test_over_stack_action_after_unknown_prior_cannot_reach_extraction(
    amount: Decimal | None,
    total: Decimal | None,
    message: str,
) -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(
                    1,
                    "hero",
                    "bet",
                    amount=amount,
                    total=total,
                ),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match=rf"hero {message} exceeds known starting stack 2",
    ):
        ImportedHandState.model_validate(payload)


def test_split_amount_only_actions_accumulate_after_an_unknown_prior() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(
                    1,
                    "hero",
                    "bet",
                    amount=Decimal("1.5"),
                ),
                wager_action(
                    2,
                    "villain",
                    "raise",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
                wager_action(
                    3,
                    "hero",
                    "call",
                    amount=Decimal("1.5"),
                ),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match="hero cumulative commitment lower bound 3.0 exceeds.*stack 2",
    ):
        ImportedHandState.model_validate(payload)


def test_total_only_actions_accumulate_across_streets_after_an_unknown_prior(
) -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("3")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(1, "hero", "bet", total=Decimal("2")),
                wager_action(
                    2,
                    "villain",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
            ],
        },
        {
            "street": "flop",
            "actions": [
                wager_action(0, "hero", "bet", total=Decimal("2")),
            ],
        },
    ]

    with pytest.raises(
        ValidationError,
        match="hero cumulative commitment lower bound 4 exceeds.*stack 3",
    ):
        ImportedHandState.model_validate(payload)


def test_mixed_amount_and_total_lower_bounds_accumulate_across_streets() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("2.5")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(1, "hero", "bet", amount=Decimal("1")),
                wager_action(
                    2,
                    "villain",
                    "raise",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(3, "hero", "call", total=Decimal("2")),
            ],
        },
        {
            "street": "flop",
            "actions": [
                wager_action(0, "hero", "bet", amount=Decimal("1")),
            ],
        },
    ]

    with pytest.raises(
        ValidationError,
        match="hero cumulative commitment lower bound 3 exceeds.*stack 2.5",
    ):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("action_type", ["fold", "check"])
def test_non_chip_action_total_establishes_a_commitment_lower_bound(
    action_type: str,
) -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(1, "hero", action_type, total=Decimal("3")),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match="hero street commitment 3 exceeds.*stack 2",
    ):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("action_type", ["fold", "check"])
def test_fold_or_check_total_must_equal_an_exact_prior_commitment(
    action_type: str,
) -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["game"]["blinds"]["ante"] = Decimal("0.1")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(
                    0,
                    "post_ante",
                    amount=Decimal("0.1"),
                    total=Decimal("0.1"),
                ),
                wager_action(1, "hero", action_type, total=Decimal("0.5")),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match=rf"{action_type} total_committed 0.5 conflicts.*commitment 0.1",
    ):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("action_type", ["fold", "check"])
def test_fold_or_check_accepts_a_total_equal_to_the_exact_prior(
    action_type: str,
) -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["game"]["blinds"]["ante"] = Decimal("0.1")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(
                    0,
                    "post_ante",
                    amount=Decimal("0.1"),
                    total=Decimal("0.1"),
                ),
                wager_action(1, "hero", action_type, total=Decimal("0.1")),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("0.1")


def test_check_total_mismatch_cannot_enter_an_active_extractable_record() -> None:
    invalid_state = hand_state(hero_player_id="hero").model_dump()
    invalid_state["game"]["blinds"]["ante"] = Decimal("0.1")
    invalid_state["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(
                    0,
                    "post_ante",
                    amount=Decimal("0.1"),
                    total=Decimal("0.1"),
                ),
                wager_action(1, "hero", "check", total=Decimal("0.5")),
            ],
        }
    ]
    record_payload = active_record().model_dump()
    record_payload["canonical_revisions"][0]["state"] = invalid_state

    with pytest.raises(
        ValidationError,
        match="check total_committed 0.5 conflicts.*commitment 0.1",
    ):
        ImportedHandRecord.model_validate(record_payload)


def test_amount_and_total_cannot_undercut_an_unknown_prior_lower_bound() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("10")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(
                    1,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("1"),
                ),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match="bet total_committed 1 is below.*lower bound 2",
    ):
        ImportedHandState.model_validate(payload)


def test_fold_total_cannot_undercut_an_unknown_prior_lower_bound() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("10")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(1, "hero", "bet", amount=Decimal("2")),
                wager_action(
                    2,
                    "villain",
                    "raise",
                    amount=Decimal("4"),
                    total=Decimal("4"),
                ),
                wager_action(3, "hero", "fold", total=Decimal("1")),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match="fold total_committed 1 is below.*lower bound 2",
    ):
        ImportedHandState.model_validate(payload)


def test_check_total_cannot_undercut_an_unknown_prior_lower_bound() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("10")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(
                    1,
                    "hero",
                    "post_big_blind",
                    amount=Decimal("1"),
                ),
                wager_action(
                    2,
                    "villain",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(3, "hero", "check", total=Decimal("0")),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match="check total_committed 0 is below.*lower bound 1",
    ):
        ImportedHandState.model_validate(payload)


def test_return_total_cannot_undercut_the_proven_post_return_lower_bound() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("10")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(1, "hero", "bet", amount=Decimal("5")),
                wager_action(2, "villain", "fold", total=Decimal("0")),
                forced_post(
                    3,
                    "uncalled_return",
                    amount=Decimal("2"),
                    total=Decimal("1"),
                ),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match="uncalled_return total_committed 1 is below.*lower bound 3",
    ):
        ImportedHandState.model_validate(payload)


def test_supplied_total_at_an_unknown_prior_lower_bound_is_accepted() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("10")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(
                    1,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("2")


@pytest.mark.parametrize("action_type", ["fold", "check"])
def test_fold_or_check_total_at_an_unknown_prior_lower_bound_is_accepted(
    action_type: str,
) -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("10")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(
                    1,
                    "hero",
                    "post_big_blind",
                    amount=Decimal("1"),
                ),
                wager_action(2, "hero", action_type, total=Decimal("1")),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("1")


def test_return_total_at_the_proven_post_return_lower_bound_is_accepted() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("10")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(1, "hero", "bet", amount=Decimal("5")),
                wager_action(2, "villain", "fold", total=Decimal("0")),
                forced_post(
                    3,
                    "uncalled_return",
                    amount=Decimal("2"),
                    total=Decimal("3"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("3")


def test_unknown_return_amount_accepts_a_nonnegative_supplied_total() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("10")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(1, "hero", "bet", amount=Decimal("5")),
                wager_action(2, "villain", "fold", total=Decimal("0")),
                forced_post(3, "uncalled_return", total=Decimal("0")),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("0")


def test_forced_and_voluntary_amount_lower_bounds_accumulate_together() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("2")
    payload["game"]["blinds"]["small_blind"] = Decimal("0.75")
    payload["game"]["blinds"]["straddle"] = Decimal("0.75")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(
                    1,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.75"),
                ),
                wager_action(
                    2,
                    "hero",
                    "post_straddle",
                    amount=Decimal("0.75"),
                ),
                wager_action(3, "hero", "raise", amount=Decimal("1")),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match="hero cumulative commitment lower bound 2.50 exceeds.*stack 2",
    ):
        ImportedHandState.model_validate(payload)


def test_known_return_amount_reduces_the_future_commitment_lower_bound() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("3")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(1, "hero", "bet", amount=Decimal("2")),
                wager_action(2, "villain", "fold", total=Decimal("0")),
                forced_post(
                    3,
                    "uncalled_return",
                    amount=Decimal("1"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].amount == Decimal("1")


def test_known_post_return_total_replaces_an_unknown_commitment_lower_bound(
) -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("3")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(1, "hero", "bet", amount=Decimal("2.5")),
                wager_action(2, "villain", "fold", total=Decimal("0")),
                forced_post(
                    3,
                    "uncalled_return",
                    total=Decimal("1"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("1")


def test_unknown_return_allows_a_feasible_later_commitment() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("2.5")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    1,
                    "villain",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                forced_post(2, "uncalled_return"),
            ],
        },
        {
            "street": "flop",
            "actions": [
                wager_action(0, "hero", "bet", amount=Decimal("1")),
            ],
        },
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[-1].actions[0].amount == Decimal("1")


def test_unknown_return_cannot_rescue_an_earlier_over_stack_commitment() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(0, "hero", "bet", amount=Decimal("3")),
                forced_post(1, "uncalled_return"),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match="hero cumulative commitment 3 exceeds known starting stack 2",
    ):
        ImportedHandState.model_validate(payload)


def test_unknown_stack_keeps_split_amount_only_commitments_reviewable() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = None
    payload["seats"][1]["starting_stack"] = Decimal("500")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(
                    1,
                    "hero",
                    "bet",
                    amount=Decimal("150"),
                ),
                wager_action(
                    2,
                    "villain",
                    "raise",
                    amount=Decimal("300"),
                    total=Decimal("300"),
                ),
                wager_action(
                    3,
                    "hero",
                    "call",
                    amount=Decimal("150"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.seats[0].starting_stack is None


def test_lower_bound_below_known_stack_remains_reviewable_across_streets(
) -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("5")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                wager_action(1, "hero", "bet", total=Decimal("2")),
                wager_action(
                    2,
                    "villain",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
            ],
        },
        {
            "street": "flop",
            "actions": [
                wager_action(0, "hero", "bet", total=Decimal("2")),
            ],
        },
    ]

    state = ImportedHandState.model_validate(payload)

    assert len(state.streets) == 2


@pytest.mark.parametrize("action_type", ["bet", "call", "post_small_blind"])
def test_resolved_chip_action_cannot_exceed_a_known_starting_stack(
    action_type: str,
) -> None:
    payload = hand_state().model_dump()
    payload["seats"][0]["starting_stack"] = (
        Decimal("0.4")
        if action_type == "post_small_blind"
        else Decimal("2")
    )
    if action_type == "call":
        actions = [
            wager_action(
                0,
                "villain",
                "bet",
                amount=Decimal("3"),
                total=Decimal("3"),
            ),
            wager_action(
                1,
                "hero",
                "call",
                amount=Decimal("3"),
                total=Decimal("3"),
            ),
        ]
    elif action_type == "post_small_blind":
        actions = [
            wager_action(
                0,
                "hero",
                "post_small_blind",
                amount=Decimal("0.5"),
                total=Decimal("0.5"),
            )
        ]
    else:
        actions = [
            wager_action(
                0,
                "hero",
                "bet",
                amount=Decimal("3"),
                total=Decimal("3"),
            )
        ]
    payload["streets"] = [{"street": "preflop", "actions": actions}]

    with pytest.raises(ValidationError, match="exceeds known starting stack"):
        ImportedHandState.model_validate(payload)


def test_starting_stack_ceiling_uses_the_cumulative_multi_street_commitment(
) -> None:
    payload = hand_state().model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("5")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
                wager_action(
                    1,
                    "villain",
                    "call",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
            ],
        },
        {
            "street": "flop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                )
            ],
        },
    ]

    with pytest.raises(
        ValidationError,
        match="hero cumulative commitment 6 exceeds known starting stack 5",
    ):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("starting_stack", [Decimal("3"), None])
def test_exact_or_unknown_starting_stack_commitment_remains_reviewable(
    starting_stack: Decimal | None,
) -> None:
    payload = hand_state().model_dump()
    payload["seats"][0]["starting_stack"] = starting_stack
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                )
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[0].all_in is False


def test_exact_known_stack_commitment_still_infers_all_in() -> None:
    payload = hand_state().model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("3")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
                wager_action(
                    1,
                    "villain",
                    "call",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
                wager_action(2, "hero", "check", total=Decimal("3")),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match="cannot act after folding or going all-in",
    ):
        ImportedHandState.model_validate(payload)


def test_uncalled_return_may_lower_an_exact_inferred_stack_commitment() -> None:
    payload = hand_state().model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("3")
    payload["seats"][1]["starting_stack"] = Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
                wager_action(
                    1,
                    "villain",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                    all_in=True,
                ),
                forced_post(
                    2,
                    "uncalled_return",
                    amount=Decimal("1"),
                    total=Decimal("2"),
                ),
            ],
        }
    ]
    payload["results"] = {}

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("2")


def test_stack_exhausted_short_forced_blind_is_exempt_without_all_in_flag() -> None:
    payload = short_big_blind_payload()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "third-player",
                    "post_ante",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("1.5"),
                ),
                wager_action(
                    2,
                    "hero",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    3,
                    "villain",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
            ],
        },
        {"street": "flop", "actions": []},
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[1].all_in is False


def test_tied_actual_short_blinds_do_not_require_an_uncalled_return() -> None:
    payload = three_player_wager_payload(third_stack=Decimal("0.5"))
    payload["seats"][0]["starting_stack"] = Decimal("0.5")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(2, "villain", "fold", total=Decimal("0")),
            ],
        }
    ]
    payload["results"] = {}

    state = ImportedHandState.model_validate(payload)

    assert state.results is not None


def test_uncalled_return_settles_a_nominal_short_big_blind_bring_in() -> None:
    payload = three_player_wager_payload(third_stack=Decimal("0.5"))
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "hero",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(2, "villain", "fold", total=Decimal("0")),
                forced_post(
                    3,
                    "uncalled_return",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
            ],
        }
    ]
    payload["results"] = {}

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("0.5")


def test_same_street_action_cannot_follow_a_concrete_uncalled_return() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                forced_post(
                    1,
                    "uncalled_return",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    2,
                    "villain",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
            ],
        }
    ]
    payload["results"] = {}

    with pytest.raises(ValidationError, match="cannot follow an uncalled return"):
        ImportedHandState.model_validate(payload)


def test_concrete_uncalled_return_allows_the_next_street_and_results() -> None:
    payload = hand_state().model_dump()
    payload["seats"][1]["starting_stack"] = Decimal("1")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    1,
                    "villain",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                    all_in=True,
                ),
                forced_post(
                    2,
                    "uncalled_return",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
            ],
        },
        {"street": "flop", "actions": []},
    ]
    payload["results"] = {}

    state = ImportedHandState.model_validate(payload)

    assert state.results is not None


def test_action_cannot_follow_an_unknown_uncalled_return() -> None:
    payload = hand_state().model_dump()
    unresolved_return = forced_post(1, "uncalled_return")
    unresolved_return["actor_id"] = "villain"
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                unresolved_return,
                wager_action(2, "hero", "check", total=Decimal("0")),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="cannot follow an uncalled return"):
        ImportedHandState.model_validate(payload)


def test_unknown_uncalled_return_does_not_erase_a_known_wager_target() -> None:
    payload = hand_state().model_dump()
    unresolved_return = forced_post(1, "uncalled_return")
    unresolved_return["actor_id"] = "villain"
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                unresolved_return,
            ],
        }
    ]
    payload["results"] = {}

    with pytest.raises(ValidationError, match="has not matched the known wager"):
        ImportedHandState.model_validate(payload)


def test_player_decision_is_rejected_after_the_only_opponent_is_all_in() -> None:
    payload = hand_state().model_dump()
    payload["seats"][1]["starting_stack"] = Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    1,
                    "villain",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                    all_in=True,
                ),
            ],
        },
        {
            "street": "flop",
            "actions": [wager_action(0, "hero", "check", total=Decimal("0"))],
        },
    ]

    with pytest.raises(
        ValidationError,
        match="every pot-eligible opponent is all-in",
    ):
        ImportedHandState.model_validate(payload)


def test_all_in_runout_without_later_decisions_accepts_results() -> None:
    payload = hand_state().model_dump()
    payload["seats"][1]["starting_stack"] = Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    1,
                    "villain",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                    all_in=True,
                ),
            ],
        },
        {"street": "flop", "actions": []},
        {"street": "turn", "actions": []},
    ]
    payload["results"] = {
        "awards": [
            {
                "player_id": "villain",
                "amount": Decimal("4"),
                "evidence": [evidence()],
            }
        ]
    }

    state = ImportedHandState.model_validate(payload)

    assert state.results is not None
    assert state.results.awards[0].player_id == "villain"


def test_unknown_return_reopens_inferred_stack_exhaustion_for_next_street() -> None:
    payload = hand_state().model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    1,
                    "villain",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                forced_post(2, "uncalled_return"),
            ],
        },
        {
            "street": "flop",
            "actions": [
                wager_action(0, "villain", "check", total=Decimal("0")),
            ],
        },
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[-1].actions[0].actor_id == "villain"


def test_sole_player_may_complete_an_outstanding_all_in_call() -> None:
    payload = hand_state().model_dump()
    payload["seats"][1]["starting_stack"] = Decimal("4")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    1,
                    "villain",
                    "raise",
                    amount=Decimal("4"),
                    total=Decimal("4"),
                    all_in=True,
                ),
                wager_action(
                    2,
                    "hero",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("4"),
                ),
            ],
        },
        {"street": "flop", "actions": []},
    ]
    payload["results"] = {}

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].action_type == "call"


def test_sole_player_cannot_raise_when_every_opponent_is_all_in() -> None:
    payload = hand_state().model_dump()
    payload["seats"][1]["starting_stack"] = Decimal("4")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    1,
                    "villain",
                    "raise",
                    amount=Decimal("4"),
                    total=Decimal("4"),
                    all_in=True,
                ),
                wager_action(
                    2,
                    "hero",
                    "raise",
                    amount=Decimal("4"),
                    total=Decimal("6"),
                ),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="no opponent can respond"):
        ImportedHandState.model_validate(payload)


def test_other_deep_player_keeps_betting_open_against_an_all_in_opponent() -> None:
    payload = three_player_wager_payload(third_stack=Decimal("2"))
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "third-player",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                    all_in=True,
                ),
                wager_action(
                    1,
                    "hero",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    2,
                    "villain",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
            ],
        },
        {
            "street": "flop",
            "actions": [
                wager_action(0, "hero", "check", total=Decimal("0")),
                wager_action(1, "villain", "check", total=Decimal("0")),
            ],
        },
    ]
    payload["results"] = {}

    state = ImportedHandState.model_validate(payload)

    assert len(state.streets[1].actions) == 2


@pytest.mark.parametrize(
    "origin",
    [
        {
            "kind": "unknown",
            "basis": "unresolved",
            "evidence": [evidence()],
        },
        {
            "kind": "client_automatic",
            "basis": "explicit_marker",
            "automatic_reason": "timeout",
            "evidence": [evidence()],
        },
    ],
)
def test_non_player_action_after_all_in_runout_is_still_rejected(
    origin: dict[str, object],
) -> None:
    payload = hand_state().model_dump()
    payload["seats"][1]["starting_stack"] = Decimal("2")
    unresolved_check = wager_action(0, "hero", "check", total=Decimal("0"))
    unresolved_check["origin"] = origin
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    1,
                    "villain",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                    all_in=True,
                ),
            ],
        },
        {"street": "flop", "actions": [unresolved_check]},
    ]

    with pytest.raises(
        ValidationError,
        match="every pot-eligible opponent is all-in",
    ):
        ImportedHandState.model_validate(payload)


def test_known_ring_rejects_small_blind_action_before_button() -> None:
    payload = positioned_wager_payload()
    actions = three_way_blinds_and_calls()
    actions[2] = wager_action(
        2,
        "villain",
        "call",
        amount=Decimal("0.5"),
        total=Decimal("1"),
    )
    actions[3] = wager_action(
        3,
        "hero",
        "call",
        amount=Decimal("1"),
        total=Decimal("1"),
    )
    payload["streets"] = [{"street": "preflop", "actions": actions}]

    with pytest.raises(
        ValidationError,
        match="expected hero, got villain",
    ):
        ImportedHandState.model_validate(payload)


def test_known_ring_accepts_clockwise_preflop_actions() -> None:
    payload = positioned_wager_payload()
    payload["streets"] = [
        {"street": "preflop", "actions": three_way_blinds_and_calls()}
    ]

    state = ImportedHandState.model_validate(payload)

    assert [
        action.actor_id for action in state.streets[0].actions[-3:]
    ] == ["hero", "villain", "third-player"]


@pytest.mark.parametrize(
    ("responders", "expected_error"),
    [
        (["third-player", "hero"], None),
        (["hero", "third-player"], "expected third-player, got hero"),
    ],
)
def test_raise_rebuilds_clockwise_pending_responders(
    responders: list[str],
    expected_error: str | None,
) -> None:
    payload = positioned_wager_payload()
    actions = three_way_blinds_and_calls()[:2]
    actions.extend(
        [
            wager_action(
                2,
                "hero",
                "call",
                amount=Decimal("1"),
                total=Decimal("1"),
            ),
            wager_action(
                3,
                "villain",
                "raise",
                amount=Decimal("2.5"),
                total=Decimal("3"),
            ),
        ]
    )
    prior_totals = {"hero": Decimal("1"), "third-player": Decimal("1")}
    for sequence, player_id in enumerate(responders, start=4):
        actions.append(
            wager_action(
                sequence,
                player_id,
                "call",
                amount=Decimal("2"),
                total=prior_totals[player_id] + Decimal("2"),
            )
        )
    payload["streets"] = [{"street": "preflop", "actions": actions}]

    if expected_error is None:
        state = ImportedHandState.model_validate(payload)
        assert [action.actor_id for action in state.streets[0].actions[-2:]] == responders
    else:
        with pytest.raises(ValidationError, match=expected_error):
            ImportedHandState.model_validate(payload)


def test_known_ring_accepts_clockwise_postflop_action() -> None:
    payload = positioned_wager_payload()
    payload["streets"] = [
        {"street": "preflop", "actions": three_way_blinds_and_calls()},
        {
            "street": "flop",
            "actions": [
                wager_action(0, "villain", "check", total=Decimal("0")),
                wager_action(
                    1,
                    "third-player",
                    "bet",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(2, "hero", "fold", total=Decimal("0")),
                wager_action(
                    3,
                    "villain",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
            ],
        },
    ]

    state = ImportedHandState.model_validate(payload)

    assert [action.actor_id for action in state.streets[1].actions] == [
        "villain",
        "third-player",
        "hero",
        "villain",
    ]


@pytest.mark.parametrize(
    ("flop_actions", "message"),
    [
        (
            [
                wager_action(0, "villain", "check", total=Decimal("0")),
                wager_action(1, "hero", "check", total=Decimal("0")),
            ],
            "expected third-player, got hero",
        ),
        (
            [
                wager_action(0, "villain", "check", total=Decimal("0")),
                wager_action(1, "third-player", "check", total=Decimal("0")),
                wager_action(2, "hero", "check", total=Decimal("0")),
                wager_action(3, "villain", "check", total=Decimal("0")),
            ],
            "known action round is complete",
        ),
    ],
)
def test_known_ring_rejects_postflop_order_and_extra_orbit_errors(
    flop_actions: list[dict[str, object]],
    message: str,
) -> None:
    payload = positioned_wager_payload()
    payload["streets"] = [
        {"street": "preflop", "actions": three_way_blinds_and_calls()},
        {"street": "flop", "actions": flop_actions},
    ]

    with pytest.raises(ValidationError, match=message):
        ImportedHandState.model_validate(payload)


def test_known_ring_rejects_transition_before_check_round_is_complete() -> None:
    payload = positioned_wager_payload()
    payload["streets"] = [
        {"street": "preflop", "actions": three_way_blinds_and_calls()},
        {
            "street": "flop",
            "actions": [
                wager_action(0, "villain", "check", total=Decimal("0")),
            ],
        },
        {"street": "turn", "actions": []},
    ]

    with pytest.raises(ValidationError, match="known action round is complete"):
        ImportedHandState.model_validate(payload)


def test_known_ring_rejects_transition_before_big_blind_option() -> None:
    payload = positioned_wager_payload()
    payload["streets"] = [
        {"street": "preflop", "actions": three_way_blinds_and_calls()[:-1]},
        {"street": "flop", "actions": []},
    ]

    with pytest.raises(ValidationError, match="known action round is complete"):
        ImportedHandState.model_validate(payload)


def test_known_ring_rejects_results_before_final_action_round_is_complete() -> None:
    payload = positioned_wager_payload()
    payload["streets"] = [
        {"street": "preflop", "actions": three_way_blinds_and_calls()},
        {
            "street": "flop",
            "actions": [
                wager_action(0, "villain", "check", total=Decimal("0")),
            ],
        },
    ]
    payload["results"] = {}

    with pytest.raises(ValidationError, match="known action round is complete"):
        ImportedHandState.model_validate(payload)


def test_known_ring_keeps_partial_final_action_round_reviewable_without_results(
) -> None:
    payload = positioned_wager_payload()
    payload["streets"] = [
        {"street": "preflop", "actions": three_way_blinds_and_calls()},
        {
            "street": "flop",
            "actions": [
                wager_action(0, "villain", "check", total=Decimal("0")),
            ],
        },
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[-1].actions[0].actor_id == "villain"


def test_known_ring_all_in_closure_allows_an_empty_runout() -> None:
    payload = positioned_wager_payload()
    payload["seats"][1]["starting_stack"] = Decimal("1")
    payload["seats"][2]["starting_stack"] = Decimal("1")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                    all_in=True,
                ),
                wager_action(
                    2,
                    "hero",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    3,
                    "villain",
                    "call",
                    amount=Decimal("0.5"),
                    total=Decimal("1"),
                    all_in=True,
                ),
            ],
        },
        {"street": "flop", "actions": []},
    ]
    payload["results"] = {}

    state = ImportedHandState.model_validate(payload)

    assert state.results is not None


def test_known_ring_fold_end_does_not_require_the_winner_to_act() -> None:
    payload = positioned_wager_payload()
    payload["game"]["blinds"]["small_blind"] = Decimal("1")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_small_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(2, "hero", "fold", total=Decimal("0")),
                wager_action(3, "villain", "fold", total=Decimal("1")),
            ],
        },
    ]
    payload["results"] = {}

    state = ImportedHandState.model_validate(payload)

    assert state.results is not None


@pytest.mark.parametrize(
    ("street", "actor", "expected"),
    [
        ("preflop", "villain", "hero"),
        ("flop", "hero", "villain"),
    ],
)
def test_heads_up_known_ring_uses_street_specific_first_actor(
    street: str,
    actor: str,
    expected: str,
) -> None:
    payload = hand_state().model_dump()
    payload["button_seat"] = 1
    validated_seats = [
        ImportedSeat.model_validate(seat) for seat in payload["seats"]
    ]
    positions = derive_structural_positions(validated_seats, button_seat=1)
    for seat in payload["seats"]:
        seat["position"] = positions[seat["seat_number"]].model_dump()
    if street == "preflop":
        payload["streets"] = [
            {
                "street": "preflop",
                "actions": [
                    wager_action(
                        0,
                        "hero",
                        "post_small_blind",
                        amount=Decimal("0.5"),
                        total=Decimal("0.5"),
                    ),
                    wager_action(
                        1,
                        "villain",
                        "post_big_blind",
                        amount=Decimal("1"),
                        total=Decimal("1"),
                    ),
                    wager_action(2, actor, "fold", total=Decimal("1")),
                ],
            }
        ]
    else:
        payload["streets"] = [
            {
                "street": "preflop",
                "actions": [
                    wager_action(
                        0,
                        "hero",
                        "post_small_blind",
                        amount=Decimal("0.5"),
                        total=Decimal("0.5"),
                    ),
                    wager_action(
                        1,
                        "villain",
                        "post_big_blind",
                        amount=Decimal("1"),
                        total=Decimal("1"),
                    ),
                    wager_action(
                        2,
                        "hero",
                        "call",
                        amount=Decimal("0.5"),
                        total=Decimal("1"),
                    ),
                    wager_action(3, "villain", "check", total=Decimal("1")),
                ],
            },
            {
                "street": "flop",
                "actions": [wager_action(0, actor, "check", total=Decimal("0"))],
            },
        ]

    with pytest.raises(
        ValidationError,
        match=f"expected {expected}, got {actor}",
    ):
        ImportedHandState.model_validate(payload)


def test_missing_position_still_uses_the_derivable_action_order() -> None:
    payload = positioned_wager_payload()
    payload["seats"][0]["position"] = None
    actions = three_way_blinds_and_calls()
    actions[2] = wager_action(
        2,
        "villain",
        "call",
        amount=Decimal("0.5"),
        total=Decimal("1"),
    )
    actions[3] = wager_action(
        3,
        "hero",
        "call",
        amount=Decimal("1"),
        total=Decimal("1"),
    )
    payload["streets"] = [{"street": "preflop", "actions": actions}]

    with pytest.raises(ValidationError, match="expected hero, got villain"):
        ImportedHandState.model_validate(payload)


def test_all_missing_positions_still_use_a_known_heads_up_button_ring() -> None:
    payload = hand_state().model_dump()
    payload["button_seat"] = 1
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(2, "villain", "fold", total=Decimal("1")),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="expected hero, got villain"):
        ImportedHandState.model_validate(payload)


def test_all_missing_positions_accept_a_valid_known_multiway_ring() -> None:
    payload = positioned_wager_payload()
    for seat in payload["seats"]:
        seat["position"] = None
    payload["streets"] = [
        {"street": "preflop", "actions": three_way_blinds_and_calls()}
    ]

    state = ImportedHandState.model_validate(payload)

    assert [
        action.actor_id for action in state.streets[0].actions[2:]
    ] == ["hero", "villain", "third-player"]


def test_missing_button_keeps_action_order_reviewable_without_guessing() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [wager_action(0, "villain", "check", total=Decimal(0))],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.button_seat is None


@pytest.mark.parametrize(
    ("first_actor", "expected_error"),
    [("hero", None), ("fourth-player", "expected hero, got fourth-player")],
)
def test_last_predecision_straddle_rotates_preflop_action(
    first_actor: str,
    expected_error: str | None,
) -> None:
    payload = positioned_wager_payload(player_count=4)
    payload["game"]["blinds"]["straddle"] = Decimal("2")
    first_amount = Decimal("2") if first_actor == "hero" else Decimal("0")
    first_total = Decimal("2") if first_actor == "hero" else Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    2,
                    "fourth-player",
                    "post_straddle",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    3,
                    first_actor,
                    "call" if first_actor == "hero" else "check",
                    amount=first_amount or None,
                    total=first_total,
                ),
            ],
        }
    ]

    if expected_error is None:
        state = ImportedHandState.model_validate(payload)
        assert state.streets[0].actions[-1].actor_id == "hero"
    else:
        with pytest.raises(ValidationError, match=expected_error):
            ImportedHandState.model_validate(payload)


def test_forced_ante_is_rejected_after_a_completed_action_round() -> None:
    payload = positioned_wager_payload()
    actions = three_way_blinds_and_calls()
    late_ante = forced_post(
        5,
        "post_ante",
        amount=Decimal("1"),
        total=Decimal("2"),
    )
    late_ante["actor_id"] = "hero"
    actions.append(late_ante)
    payload["streets"] = [
        {"street": "preflop", "actions": actions},
        {"street": "flop", "actions": []},
    ]

    with pytest.raises(ValidationError, match="cannot follow a table decision"):
        ImportedHandState.model_validate(payload)


def test_straddle_is_rejected_after_the_first_table_decision() -> None:
    payload = positioned_wager_payload(player_count=4)
    payload["game"]["blinds"]["straddle"] = Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    2,
                    "fourth-player",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    3,
                    "hero",
                    "post_straddle",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
            ],
        },
    ]

    with pytest.raises(ValidationError, match="cannot follow a table decision"):
        ImportedHandState.model_validate(payload)


def test_unknown_origin_action_still_obeys_known_physical_turn_order() -> None:
    payload = positioned_wager_payload()
    actions = three_way_blinds_and_calls()
    actions[2] = wager_action(
        2,
        "villain",
        "call",
        amount=Decimal("0.5"),
        total=Decimal("1"),
    )
    actions[2]["origin"] = {
        "kind": "unknown",
        "basis": "unresolved",
        "evidence": [evidence()],
    }
    payload["streets"] = [{"street": "preflop", "actions": actions[:3]}]

    with pytest.raises(ValidationError, match="expected hero, got villain"):
        ImportedHandState.model_validate(payload)


def test_all_in_player_is_skipped_in_later_known_action_ring() -> None:
    payload = positioned_wager_payload()
    payload["seats"][2]["starting_stack"] = Decimal("1")
    actions = three_way_blinds_and_calls()
    actions[1]["all_in"] = True
    actions.pop()
    payload["streets"] = [
        {"street": "preflop", "actions": actions},
        {
            "street": "flop",
            "actions": [
                wager_action(0, "villain", "check", total=Decimal("0")),
                wager_action(1, "hero", "check", total=Decimal("0")),
            ],
        },
    ]

    state = ImportedHandState.model_validate(payload)

    assert [action.actor_id for action in state.streets[1].actions] == [
        "villain",
        "hero",
    ]


def test_unknown_participation_is_not_assumed_to_owe_a_call() -> None:
    payload = incomplete_three_way_preflop_payload()
    payload["seats"][0]["participation"] = "unknown"
    payload["streets"].append({"street": "flop", "actions": []})

    state = ImportedHandState.model_validate(payload)

    assert state.seats[0].participation == "unknown"


def test_concrete_unknown_participant_cannot_hide_a_unique_top_wager() -> None:
    payload = hand_state().model_dump()
    payload["seats"][1]["participation"] = "unknown"
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(1, "villain", "fold", total=Decimal("0")),
            ],
        }
    ]
    payload["results"] = {}

    with pytest.raises(ValidationError, match="unique unmatched top wager"):
        ImportedHandState.model_validate(payload)


def test_unknown_participant_commitment_keeps_unique_top_reviewable() -> None:
    payload = hand_state().model_dump()
    payload["seats"][1]["participation"] = "unknown"
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(1, "villain", "call"),
                wager_action(2, "villain", "fold"),
            ],
        }
    ]
    payload["results"] = {}

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed is None


def test_unknown_live_commitment_remains_reviewable_at_a_street_boundary() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(2, "hero", "call"),
            ],
        },
        {"street": "flop", "actions": []},
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed is None


def test_unknown_current_wager_remains_reviewable_at_a_street_boundary() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(0, "villain", "bet"),
                wager_action(1, "hero", "check"),
            ],
        },
        {"street": "flop", "actions": []},
    ]

    state = ImportedHandState.model_validate(payload)

    assert len(state.streets) == 2


@pytest.mark.parametrize("include_return", [False, True])
def test_unique_top_wager_requires_an_uncalled_return_before_advancing(
    include_return: bool,
) -> None:
    payload = three_player_wager_payload()
    actions = [
        wager_action(
            0,
            "hero",
            "bet",
            amount=Decimal("2"),
            total=Decimal("2"),
        ),
        wager_action(
            1,
            "villain",
            "call",
            amount=Decimal("2"),
            total=Decimal("2"),
        ),
        wager_action(
            2,
            "third-player",
            "raise",
            amount=Decimal("4"),
            total=Decimal("4"),
        ),
    ]
    if include_return:
        returned = forced_post(
            3,
            "uncalled_return",
            amount=Decimal("2"),
            total=Decimal("2"),
        )
        returned["actor_id"] = "third-player"
        actions.append(returned)
    payload["streets"] = [
        {"street": "preflop", "actions": actions},
        {"street": "flop", "actions": []},
    ]

    if include_return:
        state = ImportedHandState.model_validate(payload)
        assert state.streets[0].actions[-1].action_type == "uncalled_return"
    else:
        with pytest.raises(ValidationError, match="has not matched the known wager"):
            ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("include_return", [False, True])
def test_short_all_in_does_not_make_a_unique_top_wager_called(
    include_return: bool,
) -> None:
    payload = hand_state().model_dump()
    payload["seats"][1]["starting_stack"] = Decimal("1")
    actions = [
        wager_action(
            0,
            "hero",
            "bet",
            amount=Decimal("2"),
            total=Decimal("2"),
        ),
        wager_action(
            1,
            "villain",
            "call",
            amount=Decimal("1"),
            total=Decimal("1"),
            all_in=True,
        ),
    ]
    if include_return:
        actions.append(
            forced_post(
                2,
                "uncalled_return",
                amount=Decimal("1"),
                total=Decimal("1"),
            )
        )
    payload["streets"] = [
        {"street": "preflop", "actions": actions},
        {"street": "flop", "actions": []},
    ]

    if include_return:
        state = ImportedHandState.model_validate(payload)
        assert state.streets[0].actions[-1].action_type == "uncalled_return"
    else:
        with pytest.raises(ValidationError, match="unique unmatched top wager"):
            ImportedHandState.model_validate(payload)


def test_fold_ended_hand_with_uncalled_return_can_accept_results() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(1, "villain", "fold", total=Decimal("0")),
                forced_post(
                    2,
                    "uncalled_return",
                    amount=Decimal("2"),
                    total=Decimal("0"),
                ),
            ],
        }
    ]
    payload["results"] = {}

    state = ImportedHandState.model_validate(payload)

    assert state.results is not None


def test_fold_ended_hand_requires_an_uncalled_return_for_a_unique_top_wager() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(1, "villain", "fold", total=Decimal("0")),
            ],
        }
    ]
    payload["results"] = {}

    with pytest.raises(ValidationError, match="unique unmatched top wager"):
        ImportedHandState.model_validate(payload)


def test_fold_ended_hand_without_an_unmatched_wager_can_accept_results() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(0, "villain", "fold", total=Decimal("0")),
            ],
        }
    ]
    payload["results"] = {}

    state = ImportedHandState.model_validate(payload)

    assert state.results is not None


def test_empty_later_street_is_rejected_after_folds_end_the_hand() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(0, "villain", "fold", total=Decimal("0")),
            ],
        },
        {"street": "flop", "actions": []},
    ]

    with pytest.raises(ValidationError, match="after folds end the hand"):
        ImportedHandState.model_validate(payload)


def test_non_all_in_raise_must_match_the_big_blind_minimum_increment() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "hero",
                    "raise",
                    amount=Decimal("1.5"),
                    total=Decimal("1.5"),
                ),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="non-all-in raise must be at least"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize(
    ("total", "all_in"),
    [(Decimal("2"), False), (Decimal("1.5"), True)],
)
def test_minimum_full_raise_and_short_all_in_raise_are_accepted(
    total: Decimal, all_in: bool
) -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "hero",
                    "raise",
                    amount=total,
                    total=total,
                    all_in=all_in,
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].all_in is all_in


def test_opening_bet_sets_the_next_minimum_raise_increment() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {"street": "preflop", "actions": []},
        {
            "street": "flop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    1,
                    "hero",
                    "raise",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
            ],
        },
    ]

    with pytest.raises(ValidationError, match="non-all-in raise must be at least"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("betting_limit", ["no_limit", "pot_limit"])
def test_non_all_in_opening_bet_must_reach_the_big_blind_minimum(
    betting_limit: str,
) -> None:
    payload = hand_state().model_dump()
    payload["game"]["betting_limit"] = betting_limit
    payload["streets"] = [
        {"street": "preflop", "actions": []},
        {
            "street": "flop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                )
            ],
        },
    ]

    with pytest.raises(ValidationError, match="non-all-in bet must be at least"):
        ImportedHandState.model_validate(payload)


def test_short_all_in_opening_bet_below_the_big_blind_is_accepted() -> None:
    payload = hand_state().model_dump()
    payload["seats"][0]["starting_stack"] = Decimal("0.5")
    payload["streets"] = [
        {"street": "preflop", "actions": []},
        {
            "street": "flop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                    all_in=True,
                )
            ],
        },
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[-1].actions[-1].all_in is True


@pytest.mark.parametrize("betting_limit", ["fixed_limit", "unknown"])
def test_unsupported_limit_minimum_raise_size_remains_reviewable(
    betting_limit: str,
) -> None:
    payload = hand_state().model_dump()
    payload["game"]["betting_limit"] = betting_limit
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "hero",
                    "raise",
                    amount=Decimal("1.5"),
                    total=Decimal("1.5"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("1.5")


def test_short_all_in_raise_does_not_reduce_the_next_full_raise_increment() -> None:
    payload = hand_state().model_dump()
    payload["game"]["table_size"] = 3
    payload["seats"].append(
        {
            "seat_number": 3,
            "player_id": "third-player",
            "starting_stack": Decimal("4"),
            "participation": "dealt_in",
            "position": None,
        }
    )
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "villain",
                    "raise",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
                wager_action(
                    2,
                    "third-player",
                    "raise",
                    amount=Decimal("4"),
                    total=Decimal("4"),
                    all_in=True,
                ),
                wager_action(
                    3,
                    "hero",
                    "raise",
                    amount=Decimal("4"),
                    total=Decimal("5"),
                ),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="non-all-in raise must be at least"):
        ImportedHandState.model_validate(payload)


def test_full_reraise_may_match_the_previous_full_raise_increment() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "hero",
                    "raise",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
                wager_action(
                    2,
                    "villain",
                    "raise",
                    amount=Decimal("4"),
                    total=Decimal("5"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("5")


def test_straddle_sets_the_preflop_minimum_raise_increment() -> None:
    payload = hand_state().model_dump()
    payload["game"]["blinds"]["straddle"] = Decimal("2")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_straddle",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    1,
                    "hero",
                    "raise",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="non-all-in raise must be at least"):
        ImportedHandState.model_validate(payload)


def test_unknown_raise_size_after_a_known_wager_remains_reviewable() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(1, "hero", "raise"),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed is None


def test_unknown_raise_size_keeps_later_minimum_raise_validation_reviewable() -> None:
    payload = hand_state().model_dump()
    payload["game"]["table_size"] = 3
    payload["seats"].append(
        {
            "seat_number": 3,
            "player_id": "third-player",
            "starting_stack": Decimal("100"),
            "participation": "dealt_in",
            "position": None,
        }
    )
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(0, "hero", "bet"),
                wager_action(
                    1,
                    "villain",
                    "raise",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                ),
                wager_action(
                    2,
                    "third-player",
                    "raise",
                    amount=Decimal("3.5"),
                    total=Decimal("3.5"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("3.5")


def test_minimum_raise_increment_resets_for_each_street() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(
                    1,
                    "hero",
                    "raise",
                    amount=Decimal("4"),
                    total=Decimal("4"),
                ),
                wager_action(
                    2,
                    "villain",
                    "call",
                    amount=Decimal("2"),
                    total=Decimal("4"),
                ),
            ],
        },
        {
            "street": "flop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "hero",
                    "raise",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
            ],
        },
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[-1].actions[-1].action_type == "raise"


def test_short_all_in_does_not_reopen_raising_for_a_player_who_already_acted() -> None:
    payload = three_player_wager_payload(third_stack=Decimal("1.5"))
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "villain",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    2,
                    "third-player",
                    "raise",
                    amount=Decimal("1.5"),
                    total=Decimal("1.5"),
                    all_in=True,
                ),
                wager_action(
                    3,
                    "hero",
                    "raise",
                    amount=Decimal("1.5"),
                    total=Decimal("2.5"),
                ),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="have not reopened betting"):
        ImportedHandState.model_validate(payload)


def test_player_who_has_not_acted_may_raise_over_a_short_all_in() -> None:
    payload = three_player_wager_payload()
    payload["seats"][1]["starting_stack"] = Decimal("1.5")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "villain",
                    "raise",
                    amount=Decimal("1.5"),
                    total=Decimal("1.5"),
                    all_in=True,
                ),
                wager_action(
                    2,
                    "third-player",
                    "raise",
                    amount=Decimal("2.5"),
                    total=Decimal("2.5"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("2.5")


def test_cumulative_short_all_ins_reopen_raising_at_one_full_increment() -> None:
    payload = three_player_wager_payload(third_stack=Decimal("2"))
    payload["game"]["table_size"] = 4
    payload["seats"][1]["starting_stack"] = Decimal("1.5")
    payload["seats"].append(
        {
            "seat_number": 4,
            "player_id": "fourth-player",
            "starting_stack": Decimal("100"),
            "participation": "dealt_in",
            "position": None,
        }
    )
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "villain",
                    "raise",
                    amount=Decimal("1.5"),
                    total=Decimal("1.5"),
                    all_in=True,
                ),
                wager_action(
                    2,
                    "third-player",
                    "raise",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                    all_in=True,
                ),
                wager_action(
                    3,
                    "hero",
                    "raise",
                    amount=Decimal("2"),
                    total=Decimal("3"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("3")


def test_unknown_short_raise_keeps_reopening_rights_reviewable() -> None:
    payload = three_player_wager_payload()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(1, "villain", "raise", all_in=True),
                wager_action(
                    2,
                    "hero",
                    "raise",
                    amount=Decimal("1"),
                    total=Decimal("2"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].action_type == "raise"


def test_big_blind_ante_is_dead_money_for_call_and_raise_targets() -> None:
    payload = three_player_wager_payload()
    payload["game"]["blinds"]["ante"] = Decimal("1")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "third-player",
                    "post_ante",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("2"),
                ),
                wager_action(
                    2,
                    "hero",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    3,
                    "villain",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("1")


def short_big_blind_payload() -> dict[str, object]:
    payload = three_player_wager_payload(third_stack=Decimal("1.5"))
    payload["game"]["blinds"]["ante"] = Decimal("1")
    return payload


@pytest.mark.parametrize(
    ("action_type", "total"),
    [("call", Decimal("1")), ("raise", Decimal("2"))],
)
def test_short_all_in_big_blind_preserves_the_nominal_multiway_bring_in(
    action_type: str,
    total: Decimal,
) -> None:
    payload = short_big_blind_payload()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "third-player",
                    "post_ante",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("1.5"),
                    all_in=True,
                ),
                wager_action(
                    2,
                    "hero",
                    action_type,
                    amount=total,
                    total=total,
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == total


def test_short_all_in_big_blind_does_not_reduce_the_minimum_full_raise() -> None:
    payload = short_big_blind_payload()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "third-player",
                    "post_ante",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("1.5"),
                    all_in=True,
                ),
                wager_action(
                    2,
                    "hero",
                    "raise",
                    amount=Decimal("1.5"),
                    total=Decimal("1.5"),
                ),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="non-all-in raise must be at least"):
        ImportedHandState.model_validate(payload)


def pot_limit_three_player_payload() -> dict[str, object]:
    payload = three_player_wager_payload()
    payload["game"]["betting_limit"] = "pot_limit"
    return payload


def pot_limit_postflop_bet_payload(
    amount: Decimal,
    *,
    all_in: bool = False,
) -> dict[str, object]:
    payload = hand_state().model_dump()
    payload["game"]["betting_limit"] = "pot_limit"
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    2,
                    "hero",
                    "call",
                    amount=Decimal("0.5"),
                    total=Decimal("1"),
                ),
                wager_action(3, "villain", "check", total=Decimal("1")),
            ],
        },
        {
            "street": "flop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=amount,
                    total=amount,
                    all_in=all_in,
                )
            ],
        },
    ]
    return payload


def test_pot_limit_opening_bet_may_equal_the_pot_before_the_action() -> None:
    state = ImportedHandState.model_validate(
        pot_limit_postflop_bet_payload(Decimal("2"))
    )

    assert state.streets[-1].actions[-1].total_committed == Decimal("2")


@pytest.mark.parametrize("all_in", [False, True])
def test_pot_limit_opening_bet_cannot_exceed_the_pot(
    all_in: bool,
) -> None:
    payload = pot_limit_postflop_bet_payload(
        Decimal("2.1"),
        all_in=all_in,
    )

    with pytest.raises(ValidationError, match="pot-limit wager adds"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize(
    ("raise_total", "valid"),
    [(Decimal("3.5"), True), (Decimal("3.6"), False)],
)
def test_pot_limit_preflop_raise_cap_includes_the_posted_blinds(
    raise_total: Decimal,
    valid: bool,
) -> None:
    payload = pot_limit_three_player_payload()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    2,
                    "third-player",
                    "raise",
                    amount=raise_total,
                    total=raise_total,
                ),
            ],
        }
    ]

    if valid:
        state = ImportedHandState.model_validate(payload)
        assert state.streets[0].actions[-1].total_committed == raise_total
    else:
        with pytest.raises(ValidationError, match="pot-limit wager adds"):
            ImportedHandState.model_validate(payload)


@pytest.mark.parametrize(
    ("raise_total", "valid"),
    [(Decimal("4"), True), (Decimal("4.1"), False)],
)
def test_pot_limit_raise_cap_grows_after_a_multiway_call(
    raise_total: Decimal,
    valid: bool,
) -> None:
    payload = pot_limit_three_player_payload()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    2,
                    "third-player",
                    "call",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    3,
                    "hero",
                    "raise",
                    amount=raise_total - Decimal("0.5"),
                    total=raise_total,
                ),
            ],
        }
    ]

    if valid:
        state = ImportedHandState.model_validate(payload)
        assert state.streets[0].actions[-1].total_committed == raise_total
    else:
        with pytest.raises(ValidationError, match="pot-limit wager adds"):
            ImportedHandState.model_validate(payload)


@pytest.mark.parametrize(
    ("raise_total", "valid"),
    [(Decimal("3.5"), True), (Decimal("3.6"), False)],
)
def test_pot_limit_short_big_blind_cap_counts_dead_bba_money(
    raise_total: Decimal,
    valid: bool,
) -> None:
    payload = short_big_blind_payload()
    payload["game"]["betting_limit"] = "pot_limit"
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "third-player",
                    "post_ante",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("1.5"),
                    all_in=True,
                ),
                wager_action(
                    2,
                    "hero",
                    "raise",
                    amount=raise_total,
                    total=raise_total,
                ),
            ],
        }
    ]

    if valid:
        state = ImportedHandState.model_validate(payload)
        assert state.streets[0].actions[-1].total_committed == raise_total
    else:
        with pytest.raises(ValidationError, match="pot-limit wager adds"):
            ImportedHandState.model_validate(payload)


@pytest.mark.parametrize(
    ("raise_total", "valid"),
    [(Decimal("5.5"), True), (Decimal("5.6"), False)],
)
def test_pot_limit_cap_after_a_short_all_in_uses_the_actual_pot_and_live_call(
    raise_total: Decimal,
    valid: bool,
) -> None:
    payload = pot_limit_three_player_payload()
    payload["seats"][2]["starting_stack"] = Decimal("1.5")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    2,
                    "third-player",
                    "raise",
                    amount=Decimal("1.5"),
                    total=Decimal("1.5"),
                    all_in=True,
                ),
                wager_action(
                    3,
                    "hero",
                    "raise",
                    amount=raise_total - Decimal("0.5"),
                    total=raise_total,
                ),
            ],
        }
    ]

    if valid:
        state = ImportedHandState.model_validate(payload)
        assert state.streets[0].actions[-1].total_committed == raise_total
    else:
        with pytest.raises(ValidationError, match="pot-limit wager adds"):
            ImportedHandState.model_validate(payload)


def test_pot_limit_cap_remains_reviewable_when_prior_pot_is_unknown() -> None:
    payload = hand_state().model_dump()
    payload["game"]["betting_limit"] = "pot_limit"
    payload["seats"][1]["starting_stack"] = Decimal("200")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(2, "hero", "call"),
            ],
        },
        {
            "street": "flop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=Decimal("100"),
                    total=Decimal("100"),
                )
            ],
        },
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[-1].actions[-1].total_committed == Decimal("100")


def forced_post(
    sequence: int,
    action_type: str,
    *,
    amount: Decimal | None = None,
    total: Decimal | None = None,
    all_in: bool = False,
) -> dict[str, object]:
    return {
        "sequence": sequence,
        "actor_id": "hero",
        "action_type": action_type,
        "amount": amount,
        "total_committed": total,
        "all_in": all_in,
        "origin": {
            "kind": "forced_system",
            "basis": "explicit_marker",
            "evidence": [evidence()],
        },
        "evidence": [evidence()],
    }


@pytest.mark.parametrize(
    "action_type",
    ["post_ante", "post_small_blind", "post_big_blind", "post_straddle"],
)
def test_forced_post_must_match_its_configured_amount(action_type: str) -> None:
    payload = hand_state().model_dump()
    payload["game"]["blinds"] = {
        "ante": Decimal("0.1"),
        "small_blind": Decimal("0.5"),
        "big_blind": Decimal("1"),
        "straddle": Decimal("2"),
    }
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(
                    0,
                    action_type,
                    amount=Decimal("100"),
                    total=Decimal("100"),
                )
            ],
        }
    ]

    with pytest.raises(ValidationError, match="does not match configured"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize(
    ("action_type", "actor_id", "expected_actor", "amount"),
    [
        ("post_small_blind", "hero", "villain", Decimal("0.5")),
        ("post_big_blind", "villain", "third-player", Decimal("1")),
    ],
)
def test_known_ring_binds_forced_blinds_to_their_structural_seats(
    action_type: str,
    actor_id: str,
    expected_actor: str,
    amount: Decimal,
) -> None:
    payload = positioned_wager_payload()
    for seat in payload["seats"]:
        seat["position"] = None
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    actor_id,
                    action_type,
                    amount=amount,
                    total=amount,
                )
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match=rf"structural .* blind seat {expected_actor}; got {actor_id}",
    ):
        ImportedHandState.model_validate(payload)


def test_heads_up_button_and_big_blind_may_post_their_structural_blinds() -> None:
    payload = hand_state().model_dump()
    payload["button_seat"] = 1
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert [action.actor_id for action in state.streets[0].actions] == [
        "hero",
        "villain",
    ]


def test_partial_positions_accept_valid_multiway_structural_blind_posts() -> None:
    payload = positioned_wager_payload()
    payload["seats"][0]["position"] = None
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert [action.actor_id for action in state.streets[0].actions] == [
        "villain",
        "third-player",
    ]


@pytest.mark.parametrize("player_count", [2, 3])
@pytest.mark.parametrize(
    "included_posts",
    [(), ("post_small_blind",), ("post_big_blind",)],
)
@pytest.mark.parametrize("boundary", ["table_action", "street_end"])
def test_known_ring_requires_configured_structural_blinds_before_action_or_end(
    player_count: int,
    included_posts: tuple[str, ...],
    boundary: str,
) -> None:
    if player_count == 2:
        payload = hand_state().model_dump()
        payload["button_seat"] = 1
        blind_actors = {
            "post_small_blind": "hero",
            "post_big_blind": "villain",
        }
    else:
        payload = positioned_wager_payload()
        blind_actors = {
            "post_small_blind": "villain",
            "post_big_blind": "third-player",
        }
    blind_amounts = {
        "post_small_blind": Decimal("0.5"),
        "post_big_blind": Decimal("1"),
    }
    actions = [
        wager_action(
            sequence,
            blind_actors[action_type],
            action_type,
            amount=blind_amounts[action_type],
            total=blind_amounts[action_type],
        )
        for sequence, action_type in enumerate(included_posts)
    ]
    if boundary == "table_action":
        actions.append(
            wager_action(len(actions), "hero", "fold", total=Decimal("0"))
        )
    payload["streets"] = [{"street": "preflop", "actions": actions}]
    missing_posts = [
        action_type
        for action_type in ("post_small_blind", "post_big_blind")
        if action_type not in included_posts
    ]

    with pytest.raises(
        ValidationError,
        match=(
            "table decision requires"
            if boundary == "table_action"
            else "preflop street cannot end"
        )
        + rf".*missing {', '.join(missing_posts)}",
    ):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("player_count", [2, 3])
@pytest.mark.parametrize("include_table_action", [False, True])
def test_known_ring_accepts_both_structural_blinds_before_action_or_end(
    player_count: int,
    include_table_action: bool,
) -> None:
    if player_count == 2:
        payload = hand_state().model_dump()
        payload["button_seat"] = 1
        small_blind_actor = "hero"
        big_blind_actor = "villain"
    else:
        payload = positioned_wager_payload()
        small_blind_actor = "villain"
        big_blind_actor = "third-player"
    actions = [
        wager_action(
            0,
            small_blind_actor,
            "post_small_blind",
            amount=Decimal("0.5"),
            total=Decimal("0.5"),
        ),
        wager_action(
            1,
            big_blind_actor,
            "post_big_blind",
            amount=Decimal("1"),
            total=Decimal("1"),
        ),
    ]
    if include_table_action:
        actions.append(
            wager_action(
                2,
                "hero",
                "fold",
                total=(Decimal("0.5") if player_count == 2 else Decimal("0")),
            )
        )
    payload["streets"] = [{"street": "preflop", "actions": actions}]

    state = ImportedHandState.model_validate(payload)

    assert len(state.streets[0].actions) == len(actions)


@pytest.mark.parametrize(
    ("unconfigured_field", "remaining_action", "remaining_actor", "amount"),
    [
        ("small_blind", "post_big_blind", "third-player", Decimal("1")),
        ("big_blind", "post_small_blind", "villain", Decimal("0.5")),
    ],
)
def test_known_ring_does_not_require_an_unconfigured_structural_blind(
    unconfigured_field: str,
    remaining_action: str,
    remaining_actor: str,
    amount: Decimal,
) -> None:
    payload = positioned_wager_payload()
    payload["game"]["blinds"][unconfigured_field] = None
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    remaining_actor,
                    remaining_action,
                    amount=amount,
                    total=amount,
                ),
                wager_action(1, "hero", "fold", total=Decimal("0")),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].action_type == "fold"


def test_unknown_ring_does_not_require_configured_structural_blind_posts() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [wager_action(0, "hero", "fold", total=Decimal("0"))],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[0].action_type == "fold"


@pytest.mark.parametrize(
    ("short_action", "short_actor", "short_seat_index"),
    [
        ("post_small_blind", "villain", 1),
        ("post_big_blind", "third-player", 2),
    ],
)
def test_known_ring_short_all_in_structural_blind_satisfies_presence(
    short_action: str,
    short_actor: str,
    short_seat_index: int,
) -> None:
    payload = positioned_wager_payload()
    payload["seats"][short_seat_index]["starting_stack"] = Decimal("0.4")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_small_blind",
                    amount=(
                        Decimal("0.4")
                        if short_action == "post_small_blind"
                        else Decimal("0.5")
                    ),
                    total=(
                        Decimal("0.4")
                        if short_action == "post_small_blind"
                        else Decimal("0.5")
                    ),
                    all_in=short_action == "post_small_blind",
                ),
                wager_action(
                    1,
                    "third-player",
                    "post_big_blind",
                    amount=(
                        Decimal("0.4")
                        if short_action == "post_big_blind"
                        else Decimal("1")
                    ),
                    total=(
                        Decimal("0.4")
                        if short_action == "post_big_blind"
                        else Decimal("1")
                    ),
                    all_in=short_action == "post_big_blind",
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    short_post = next(
        action
        for action in state.streets[0].actions
        if action.action_type == short_action and action.actor_id == short_actor
    )
    assert short_post.all_in is True


@pytest.mark.parametrize("boundary", ["table_action", "street_end"])
@pytest.mark.parametrize(
    (
        "missing_blind",
        "exhausted_actor",
        "exhausted_seat_index",
        "remaining_blind",
        "remaining_actor",
        "remaining_amount",
    ),
    [
        (
            "post_small_blind",
            "villain",
            1,
            "post_big_blind",
            "third-player",
            Decimal("1"),
        ),
        (
            "post_big_blind",
            "third-player",
            2,
            "post_small_blind",
            "villain",
            Decimal("0.5"),
        ),
    ],
)
def test_prior_forced_ante_exhaustion_satisfies_structural_blind_presence(
    boundary: str,
    missing_blind: str,
    exhausted_actor: str,
    exhausted_seat_index: int,
    remaining_blind: str,
    remaining_actor: str,
    remaining_amount: Decimal,
) -> None:
    payload = positioned_wager_payload()
    payload["game"]["blinds"]["ante"] = Decimal("0.5")
    payload["seats"][exhausted_seat_index]["starting_stack"] = Decimal("0.5")
    actions = [
        wager_action(
            0,
            exhausted_actor,
            "post_ante",
            amount=Decimal("0.5"),
            total=Decimal("0.5"),
        ),
        wager_action(
            1,
            remaining_actor,
            remaining_blind,
            amount=remaining_amount,
            total=remaining_amount,
        ),
    ]
    if boundary == "table_action":
        actions.append(wager_action(2, "hero", "fold", total=Decimal("0")))
    payload["streets"] = [{"street": "preflop", "actions": actions}]

    state = ImportedHandState.model_validate(payload)

    assert all(
        action.action_type != missing_blind
        for action in state.streets[0].actions
    )


@pytest.mark.parametrize("boundary", ["table_action", "street_end"])
def test_unknown_stack_explicit_forced_all_in_satisfies_blind_presence(
    boundary: str,
) -> None:
    payload = positioned_wager_payload()
    payload["game"]["blinds"]["ante"] = Decimal("0.5")
    payload["seats"][2]["starting_stack"] = None
    actions = [
        wager_action(
            0,
            "third-player",
            "post_ante",
            amount=Decimal("0.5"),
            total=Decimal("0.5"),
            all_in=True,
        ),
        wager_action(
            1,
            "villain",
            "post_small_blind",
            amount=Decimal("0.5"),
            total=Decimal("0.5"),
        ),
    ]
    if boundary == "table_action":
        actions.append(wager_action(2, "hero", "fold", total=Decimal("0")))
    payload["streets"] = [{"street": "preflop", "actions": actions}]

    state = ImportedHandState.model_validate(payload)

    assert all(
        action.action_type != "post_big_blind"
        for action in state.streets[0].actions
    )


@pytest.mark.parametrize("boundary", ["table_action", "street_end"])
@pytest.mark.parametrize(
    ("starting_stack", "amount", "total", "all_in"),
    [
        (Decimal("0.5"), None, Decimal("0.5"), False),
        (None, None, Decimal("0.5"), True),
        (None, Decimal("0.5"), None, True),
    ],
)
def test_ante_exhaustion_uses_affirmative_commitment_lower_bounds(
    boundary: str,
    starting_stack: Decimal | None,
    amount: Decimal | None,
    total: Decimal | None,
    all_in: bool,
) -> None:
    payload = positioned_wager_payload()
    payload["game"]["blinds"]["ante"] = Decimal("0.5")
    payload["seats"][2]["starting_stack"] = starting_stack
    actions = [
        wager_action(0, "third-player", "post_ante"),
        wager_action(
            1,
            "third-player",
            "post_ante",
            amount=amount,
            total=total,
            all_in=all_in,
        ),
        wager_action(
            2,
            "villain",
            "post_small_blind",
            amount=Decimal("0.5"),
            total=Decimal("0.5"),
        ),
    ]
    if boundary == "table_action":
        actions.append(wager_action(3, "hero", "fold", total=Decimal("0")))
    payload["streets"] = [{"street": "preflop", "actions": actions}]

    state = ImportedHandState.model_validate(payload)

    assert all(
        action.action_type != "post_big_blind"
        for action in state.streets[0].actions
    )


@pytest.mark.parametrize("boundary", ["table_action", "street_end"])
def test_known_stack_amount_only_lower_bound_does_not_prove_ante_exhaustion(
    boundary: str,
) -> None:
    payload = positioned_wager_payload()
    payload["game"]["blinds"]["ante"] = Decimal("0.5")
    payload["seats"][2]["starting_stack"] = Decimal("0.5")
    actions = [
        wager_action(0, "third-player", "post_ante"),
        wager_action(
            1,
            "third-player",
            "post_ante",
            amount=Decimal("0.5"),
        ),
        wager_action(
            2,
            "villain",
            "post_small_blind",
            amount=Decimal("0.5"),
            total=Decimal("0.5"),
        ),
    ]
    if boundary == "table_action":
        actions.append(wager_action(3, "hero", "fold", total=Decimal("0")))
    payload["streets"] = [{"street": "preflop", "actions": actions}]

    with pytest.raises(ValidationError, match="missing post_big_blind"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("boundary", ["table_action", "street_end"])
def test_unknown_stack_zero_total_all_in_does_not_satisfy_blind_presence(
    boundary: str,
) -> None:
    payload = positioned_wager_payload()
    payload["seats"][2]["starting_stack"] = None
    actions = [
        wager_action(
            0,
            "third-player",
            "post_ante",
            total=Decimal("0"),
            all_in=True,
        ),
        wager_action(
            1,
            "villain",
            "post_small_blind",
            amount=Decimal("0.5"),
            total=Decimal("0.5"),
        ),
    ]
    if boundary == "table_action":
        actions.append(wager_action(2, "hero", "fold", total=Decimal("0")))
    payload["streets"] = [{"street": "preflop", "actions": actions}]

    with pytest.raises(ValidationError, match="missing post_big_blind"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("boundary", ["table_action", "street_end"])
@pytest.mark.parametrize("starting_stack", [Decimal("0.5"), None])
def test_exhausted_straddle_does_not_substitute_for_a_structural_blind(
    boundary: str,
    starting_stack: Decimal | None,
) -> None:
    payload = positioned_wager_payload()
    payload["seats"][2]["starting_stack"] = starting_stack
    actions = [
        wager_action(
            0,
            "third-player",
            "post_straddle",
            amount=Decimal("0.5"),
            total=Decimal("0.5"),
            all_in=starting_stack is None,
        ),
        wager_action(
            1,
            "villain",
            "post_small_blind",
            amount=Decimal("0.5"),
            total=Decimal("0.5"),
        ),
    ]
    if boundary == "table_action":
        actions.append(wager_action(2, "hero", "fold", total=Decimal("0")))
    payload["streets"] = [{"street": "preflop", "actions": actions}]

    with pytest.raises(ValidationError, match="missing post_big_blind"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("exhaustion_evidence", ["known_below_stack", "unresolved"])
def test_nonaffirmative_forced_all_in_does_not_satisfy_blind_presence(
    exhaustion_evidence: str,
) -> None:
    payload = positioned_wager_payload()
    payload["game"]["blinds"]["ante"] = Decimal("0.5")
    payload["seats"][2]["starting_stack"] = (
        Decimal("2") if exhaustion_evidence == "known_below_stack" else None
    )
    ante = wager_action(
        0,
        "third-player",
        "post_ante",
        amount=(
            Decimal("0.5")
            if exhaustion_evidence == "known_below_stack"
            else None
        ),
        total=(
            Decimal("0.5")
            if exhaustion_evidence == "known_below_stack"
            else None
        ),
        all_in=True,
    )
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                ante,
                wager_action(
                    1,
                    "villain",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="missing post_big_blind"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("terminal_action", ["fold", "bet"])
def test_table_action_cannot_substitute_for_a_missing_structural_blind(
    terminal_action: str,
) -> None:
    payload = positioned_wager_payload()
    payload["seats"][2]["starting_stack"] = Decimal("1")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "third-player",
                    terminal_action,
                    amount=Decimal("1") if terminal_action == "bet" else None,
                    total=Decimal("1") if terminal_action == "bet" else Decimal("0"),
                    all_in=terminal_action == "bet",
                ),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="missing post_big_blind"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize(
    ("action_type", "actor_id", "amount"),
    [
        ("post_small_blind", "villain", Decimal("0.5")),
        ("post_big_blind", "third-player", Decimal("1")),
    ],
)
def test_known_ring_rejects_duplicate_structural_blind_posts(
    action_type: str,
    actor_id: str,
    amount: Decimal,
) -> None:
    payload = positioned_wager_payload()
    for seat in payload["seats"]:
        seat["position"] = None
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    actor_id,
                    action_type,
                    amount=amount,
                    total=amount,
                ),
                wager_action(
                    1,
                    actor_id,
                    action_type,
                    amount=amount,
                    total=amount * 2,
                ),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match=rf"{action_type} may occur only once",
    ):
        ImportedHandState.model_validate(payload)


def test_known_ring_duplicate_blind_still_rejects_the_wrong_actor_first() -> None:
    payload = positioned_wager_payload()
    for seat in payload["seats"]:
        seat["position"] = None
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
            ],
        }
    ]

    with pytest.raises(
        ValidationError,
        match="structural small blind seat villain; got hero",
    ):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize(
    "unknown_structure",
    ["missing_button", "unknown_button_participation", "dead_button"],
)
def test_blind_actor_binding_remains_reviewable_when_the_ring_is_unknown(
    unknown_structure: str,
) -> None:
    payload = positioned_wager_payload()
    for seat in payload["seats"]:
        seat["position"] = None
    if unknown_structure == "missing_button":
        payload["button_seat"] = None
        small_blind_actor = "hero"
        big_blind_actor = "villain"
    elif unknown_structure == "unknown_button_participation":
        payload["seats"][0]["participation"] = "unknown"
        small_blind_actor = "hero"
        big_blind_actor = "villain"
    else:
        payload["seats"][0]["participation"] = "not_dealt"
        small_blind_actor = "third-player"
        big_blind_actor = "villain"
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    small_blind_actor,
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    big_blind_actor,
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert len(state.streets[0].actions) == 2


def test_duplicate_blind_posts_remain_reviewable_when_the_ring_is_unknown() -> None:
    payload = positioned_wager_payload()
    payload["button_seat"] = None
    for seat in payload["seats"]:
        seat["position"] = None
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("1"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert len(state.streets[0].actions) == 2


def test_total_only_forced_post_uses_the_increment_after_an_ante() -> None:
    payload = hand_state().model_dump()
    payload["game"]["blinds"]["ante"] = Decimal("0.1")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(
                    0,
                    "post_ante",
                    amount=Decimal("0.1"),
                    total=Decimal("0.1"),
                ),
                forced_post(
                    1,
                    "post_small_blind",
                    total=Decimal("100.1"),
                ),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="post_small_blind amount 100.0"):
        ImportedHandState.model_validate(payload)


def test_ante_plus_blind_cumulative_total_accepts_the_configured_increment() -> None:
    payload = hand_state().model_dump()
    payload["game"]["blinds"]["ante"] = Decimal("0.1")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(
                    0,
                    "post_ante",
                    amount=Decimal("0.1"),
                    total=Decimal("0.1"),
                ),
                forced_post(
                    1,
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.6"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("0.6")


def test_action_amount_and_total_must_reconcile_with_the_prior_commitment() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("3"),
                )
            ],
        }
    ]

    with pytest.raises(ValidationError, match="conflict with prior commitment 0"):
        ImportedHandState.model_validate(payload)


def test_ante_and_blind_dual_fields_use_the_cumulative_street_total() -> None:
    payload = hand_state().model_dump()
    payload["game"]["blinds"]["ante"] = Decimal("0.1")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(
                    0,
                    "post_ante",
                    amount=Decimal("0.1"),
                    total=Decimal("0.1"),
                ),
                forced_post(
                    1,
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="conflict with prior commitment 0.1"):
        ImportedHandState.model_validate(payload)


def test_uncalled_return_dual_fields_subtract_from_the_prior_commitment() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                wager_action(1, "villain", "fold", total=Decimal(0)),
                forced_post(
                    2,
                    "uncalled_return",
                    amount=Decimal("1"),
                    total=Decimal(0),
                ),
            ],
        }
    ]

    with pytest.raises(ValidationError, match="conflict with prior commitment 2"):
        ImportedHandState.model_validate(payload)


def test_dual_fields_remain_reviewable_when_the_prior_commitment_is_unknown() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(0, "post_ante"),
                forced_post(
                    1,
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].total_committed == Decimal("0.5")


def test_short_forced_post_accepts_known_stack_exhaustion_after_an_ante() -> None:
    payload = hand_state().model_dump()
    payload["game"]["blinds"]["ante"] = Decimal("0.2")
    payload["seats"][0]["starting_stack"] = Decimal("0.6")
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(
                    0,
                    "post_ante",
                    amount=Decimal("0.2"),
                    total=Decimal("0.2"),
                ),
                forced_post(
                    1,
                    "post_small_blind",
                    amount=Decimal("0.4"),
                    total=Decimal("0.6"),
                    all_in=True,
                ),
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].all_in is True


@pytest.mark.parametrize("all_in", [False, True])
def test_short_forced_post_rejects_a_known_nonexhausted_stack(all_in: bool) -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(
                    0,
                    "post_big_blind",
                    amount=Decimal("0.4"),
                    total=Decimal("0.4"),
                    all_in=all_in,
                )
            ],
        }
    ]

    with pytest.raises(ValidationError, match="short-stack all-in"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("all_in", [False, True])
def test_short_forced_post_with_unknown_stack_requires_an_all_in_marker(
    all_in: bool,
) -> None:
    payload = hand_state().model_dump()
    payload["seats"][0]["starting_stack"] = None
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(
                    0,
                    "post_big_blind",
                    amount=Decimal("0.4"),
                    total=Decimal("0.4"),
                    all_in=all_in,
                )
            ],
        }
    ]

    if all_in:
        state = ImportedHandState.model_validate(payload)
        assert state.streets[0].actions[0].all_in is True
    else:
        with pytest.raises(ValidationError, match="short-stack all-in"):
            ImportedHandState.model_validate(payload)


def test_forced_post_with_unknown_configuration_remains_reviewable() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                forced_post(
                    0,
                    "post_straddle",
                    amount=Decimal("3"),
                    total=Decimal("3"),
                )
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[0].action_type == "post_straddle"


def test_forced_posts_are_rejected_after_preflop() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {"street": "preflop", "actions": []},
        {
            "street": "flop",
            "actions": [
                forced_post(
                    0,
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                )
            ],
        },
    ]

    with pytest.raises(ValidationError, match="posts must be preflop"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("terminal_action", ["fold", "all_in"])
@pytest.mark.parametrize("same_street", [True, False])
def test_actions_after_a_player_becomes_terminal_are_rejected(
    terminal_action: str, same_street: bool
) -> None:
    payload = hand_state().model_dump()
    first_action = {
        "sequence": 0,
        "actor_id": "hero",
        "action_type": "fold" if terminal_action == "fold" else "bet",
        "total_committed": Decimal("0") if terminal_action == "fold" else Decimal("10"),
        "all_in": terminal_action == "all_in",
        "origin": {
            "kind": "player_selected",
            "basis": "explicit_marker",
            "evidence": [evidence()],
        },
        "evidence": [evidence()],
    }
    if terminal_action == "all_in":
        first_action["amount"] = Decimal("10")
    later_action = {
        "sequence": 1 if same_street else 0,
        "actor_id": "hero",
        "action_type": "check",
        "total_committed": Decimal("10") if same_street else Decimal("0"),
        "origin": {
            "kind": "player_selected",
            "basis": "explicit_marker",
            "evidence": [evidence()],
        },
        "evidence": [evidence()],
    }
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                first_action,
                *(
                    [
                        wager_action(
                            1,
                            "villain",
                            "call",
                            amount=Decimal("10"),
                            total=Decimal("10"),
                        )
                    ]
                    if terminal_action == "all_in" and not same_street
                    else []
                ),
                *([later_action] if same_street else []),
            ],
        },
        *(
            [{"street": "flop", "actions": [later_action]}]
            if not same_street
            else []
        ),
    ]

    expected_message = (
        "after folds end the hand"
        if terminal_action == "fold"
        else "after folding or going all-in"
    )
    with pytest.raises(ValidationError, match=expected_message):
        ImportedHandState.model_validate(payload)


def test_same_street_uncalled_return_is_allowed_after_all_in() -> None:
    payload = hand_state().model_dump()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "hero",
                    "action_type": "bet",
                    "amount": Decimal("10"),
                    "total_committed": Decimal("10"),
                    "all_in": True,
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
                {
                    "sequence": 1,
                    "actor_id": "hero",
                    "action_type": "uncalled_return",
                    "amount": Decimal("2"),
                    "total_committed": Decimal("8"),
                    "origin": {
                        "kind": "forced_system",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                },
            ],
        }
    ]

    state = ImportedHandState.model_validate(payload)

    assert state.streets[0].actions[-1].action_type == "uncalled_return"


@pytest.mark.parametrize("participation", ["sitting_out", "not_dealt"])
@pytest.mark.parametrize("result_kind", ["showdown", "awards"])
def test_results_for_known_nonparticipants_are_rejected(
    participation: str, result_kind: str
) -> None:
    payload = hand_state().model_dump()
    payload["seats"][0]["participation"] = participation
    payload["results"] = {
        result_kind: [
            {
                "player_id": "hero",
                **(
                    {
                        "cards": [],
                        "disposition": "not_shown",
                        "evidence": [evidence()],
                    }
                    if result_kind == "showdown"
                    else {"amount": Decimal("1"), "evidence": [evidence()]}
                ),
            }
        ]
    }

    with pytest.raises(ValidationError, match="sitting out or not dealt"):
        ImportedHandState.model_validate(payload)


def test_results_for_unknown_participation_remain_reviewable() -> None:
    payload = hand_state().model_dump()
    payload["seats"][0]["participation"] = "unknown"
    payload["results"] = {
        "showdown": [
            {
                "player_id": "hero",
                "cards": [],
                "disposition": "not_shown",
                "evidence": [evidence()],
            }
        ],
        "awards": [
            {
                "player_id": "hero",
                "amount": Decimal("1"),
                "evidence": [evidence()],
            }
        ],
    }

    state = ImportedHandState.model_validate(payload)

    assert state.seats[0].participation == "unknown"
    assert state.results is not None
    assert state.results.showdown[0].player_id == "hero"
    assert state.results.awards[0].player_id == "hero"


@pytest.mark.parametrize("participation", ["sitting_out", "not_dealt", "unknown"])
def test_hero_cards_require_a_dealt_in_hero(participation: str) -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["participation"] = participation
    payload["hero_cards"] = [
        {"rank": "A", "suit": "hearts"},
        {"rank": "K", "suit": "diamonds"},
    ]

    with pytest.raises(ValidationError, match="require a dealt-in hero seat"):
        ImportedHandState.model_validate(payload)


def test_unknown_participation_remains_reviewable_but_is_not_extractable() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["seats"][0]["participation"] = "unknown"
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                        "sequence": 0,
                        "actor_id": "hero",
                        "action_type": "fold",
                        "total_committed": Decimal("0"),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                }
            ],
        }
    ]
    state = ImportedHandState.model_validate(payload)
    detection = detected(state)
    record = ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detection],
        canonical_revisions=[
            CanonicalHandRevision(
                revision=1,
                detection_id=detection.detection_id,
                approved_at=NOW,
                state=state,
            )
        ],
        lifecycle={
            "status": "active",
            "active_canonical_revision": 1,
            "changed_at": NOW,
        },
    )

    assert record.active_hero_actions_for_extraction == []


def test_showdown_cards_must_be_consistent_with_the_known_deck() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["hero_cards"] = [
        {"rank": "A", "suit": "hearts"},
        {"rank": "K", "suit": "diamonds"},
    ]
    payload["streets"] = [
        {"street": "preflop", "actions": []},
        {
            "street": "flop",
            "board_cards": [
                {"rank": "Q", "suit": "spades"},
                {"rank": "7", "suit": "clubs"},
                {"rank": "2", "suit": "hearts"},
            ],
            "actions": [],
        },
    ]
    payload["results"] = {
        "showdown": [
            {
                "player_id": "villain",
                "cards": [
                    {"rank": "Q", "suit": "spades"},
                    {"rank": "Q", "suit": "clubs"},
                ],
                "disposition": "shown",
                "evidence": [evidence()],
            }
        ]
    }

    with pytest.raises(ValidationError, match="must not duplicate any known card"):
        ImportedHandState.model_validate(payload)


def test_opponent_showdown_holdings_cannot_duplicate_each_other() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["game"]["table_size"] = 3
    payload["seats"].append(
        {
            "seat_number": 3,
            "player_id": "third-player",
            "starting_stack": Decimal("100"),
            "participation": "dealt_in",
            "position": None,
        }
    )
    payload["results"] = {
        "showdown": [
            {
                "player_id": "villain",
                "cards": [
                    {"rank": "Q", "suit": "spades"},
                    {"rank": "J", "suit": "clubs"},
                ],
                "disposition": "shown",
                "evidence": [evidence()],
            },
            {
                "player_id": "third-player",
                "cards": [
                    {"rank": "Q", "suit": "spades"},
                    {"rank": "T", "suit": "diamonds"},
                ],
                "disposition": "shown",
                "evidence": [evidence()],
            },
        ]
    }

    with pytest.raises(ValidationError, match="must not duplicate any known card"):
        ImportedHandState.model_validate(payload)


def test_hero_showdown_may_repeat_only_the_stored_hero_holding() -> None:
    payload = hand_state(hero_player_id="hero").model_dump()
    payload["hero_cards"] = [
        {"rank": "A", "suit": "hearts"},
        {"rank": "K", "suit": "diamonds"},
    ]
    payload["results"] = {
        "showdown": [
            {
                "player_id": "hero",
                "cards": [
                    {"rank": "K", "suit": "diamonds"},
                    {"rank": "A", "suit": "hearts"},
                ],
                "disposition": "shown",
                "evidence": [evidence()],
            }
        ]
    }

    state = ImportedHandState.model_validate(payload)
    assert {card.code for card in state.results.showdown[0].cards} == {"Ah", "Kd"}

    payload["results"]["showdown"][0]["cards"][0] = {
        "rank": "Q",
        "suit": "diamonds",
    }
    with pytest.raises(ValidationError, match="must match the stored hero holding"):
        ImportedHandState.model_validate(payload)


@pytest.mark.parametrize("betting_limit", ["no_limit", "pot_limit"])
def test_extraction_returns_only_voluntary_hero_actions_from_supported_approval(
    betting_limit: str,
) -> None:
    selected = {
        "sequence": 0,
        "actor_id": "hero",
        "action_type": "check",
        "total_committed": Decimal("0"),
        "origin": {
            "kind": "player_selected",
            "basis": "explicit_marker",
            "evidence": [evidence()],
        },
        "evidence": [evidence()],
    }
    automatic = {
        **selected,
        "sequence": 1,
        "actor_id": "villain",
        "origin": {
            "kind": "client_automatic",
            "basis": "explicit_marker",
            "automatic_reason": "timeout",
            "evidence": [evidence()],
        },
    }
    state_payload = hand_state(hero_player_id="hero").model_dump()
    state_payload["game"]["betting_limit"] = betting_limit
    state_payload["streets"] = [
        {
            "street": "preflop",
            "actions": [selected, automatic],
        }
    ]
    state = ImportedHandState.model_validate(state_payload)
    detected_state = detected(state)
    approved = CanonicalHandRevision(
        revision=1,
        detection_id=detected_state.detection_id,
        approved_at=NOW,
        state=state,
    )
    record = ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected_state],
        canonical_revisions=[approved],
        lifecycle={
            "status": "active",
            "active_canonical_revision": 1,
            "changed_at": NOW,
        },
    )

    assert [action.actor_id for action in record.active_hero_actions_for_extraction] == [
        "hero"
    ]

    withdrawn = record.model_copy(
        update={
            "lifecycle": ImportedHandLifecycle(status="withdrawn", changed_at=NOW)
        }
    )
    assert withdrawn.active_hero_actions_for_extraction == []


@pytest.mark.parametrize("betting_limit", ["fixed_limit", "unknown"])
def test_unsupported_limit_hands_remain_reviewable_but_are_not_extractable(
    betting_limit: str,
) -> None:
    state_payload = hand_state(hero_player_id="hero").model_dump()
    state_payload["game"]["betting_limit"] = betting_limit
    state_payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                {
                    "sequence": 0,
                    "actor_id": "hero",
                    "action_type": "check",
                    "total_committed": Decimal(0),
                    "origin": {
                        "kind": "player_selected",
                        "basis": "explicit_marker",
                        "evidence": [evidence()],
                    },
                    "evidence": [evidence()],
                }
            ],
        }
    ]
    state = ImportedHandState.model_validate(state_payload)
    detected_state = detected(state)
    record = ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected_state],
        canonical_revisions=[
            CanonicalHandRevision(
                revision=1,
                detection_id=detected_state.detection_id,
                approved_at=NOW,
                state=state,
            )
        ],
        lifecycle={
            "status": "active",
            "active_canonical_revision": 1,
            "changed_at": NOW,
        },
    )

    assert state.streets[0].actions[0].is_player_decision is True
    assert record.active_state_for_extraction == state
    assert record.active_hero_actions_for_extraction == []


def test_active_record_enforces_user_corrections_and_round_trips() -> None:
    record = active_record()

    restored = ImportedHandRecord.model_validate_json(record.model_dump_json())

    assert restored == record
    assert restored.active_state_for_extraction is not None
    assert restored.active_state_for_extraction.hero_player_id == "hero"

    bad_revision = revision().model_copy(
        update={"state": hand_state(hero_player_id="villain")}
    )
    with pytest.raises(ValidationError, match="only through corrections"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[detected()],
            canonical_revisions=[bad_revision],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 1,
                "changed_at": NOW,
            },
        )


def test_correction_cannot_be_recorded_after_its_approval() -> None:
    with pytest.raises(ValidationError, match="corrected_at cannot follow approved_at"):
        CanonicalHandRevision(
            revision=1,
            detection_id="detection-1",
            approved_at=NOW,
            state=hand_state(hero_player_id="hero"),
            corrections=[
                UserCorrection(
                    field_pointer="/hero_player_id",
                    detected_value=None,
                    approved_value="hero",
                    corrected_at=NOW + timedelta(microseconds=1),
                )
            ],
        )


@pytest.mark.parametrize(
    "corrected_at",
    [
        NOW - timedelta(minutes=1),
        NOW,
        datetime(2026, 8, 27, 14, 0, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_correction_at_or_before_approval_is_accepted(
    corrected_at: datetime,
) -> None:
    approved = CanonicalHandRevision(
        revision=1,
        detection_id="detection-1",
        approved_at=NOW,
        state=hand_state(hero_player_id="hero"),
        corrections=[
            UserCorrection(
                field_pointer="/hero_player_id",
                detected_value=None,
                approved_value="hero",
                corrected_at=corrected_at,
            )
        ],
    )

    assert approved.corrections[0].corrected_at == corrected_at


def test_aggregate_rechecks_correction_timestamps_after_unsafe_model_copy() -> None:
    unsafe_revision = revision().model_copy(
        update={"approved_at": NOW - timedelta(minutes=1)}
    )

    with pytest.raises(ValidationError, match="corrected_at cannot follow approved_at"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[detected()],
            canonical_revisions=[unsafe_revision],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 1,
                "changed_at": NOW,
            },
        )


@pytest.mark.parametrize(
    "pointers",
    [
        ("/seats/0", "/seats/0/display_name"),
        ("/seats/0/display_name", "/seats/0"),
    ],
)
def test_canonical_revision_rejects_overlapping_correction_paths(
    pointers: tuple[str, str],
) -> None:
    detected_state = hand_state()
    detected_seat = detected_state.model_dump(mode="json")["seats"][0]
    approved_seat = {**detected_seat, "display_name": "Hero"}
    values_by_pointer = {
        "/seats/0": (detected_seat, approved_seat),
        "/seats/0/display_name": (None, "Hero"),
    }

    with pytest.raises(ValidationError, match="overlapping fields"):
        CanonicalHandRevision(
            revision=1,
            detection_id="detection-1",
            approved_at=NOW,
            state=detected_state,
            corrections=[
                UserCorrection(
                    field_pointer=pointer,
                    detected_value=values_by_pointer[pointer][0],
                    approved_value=values_by_pointer[pointer][1],
                    corrected_at=NOW,
                )
                for pointer in pointers
            ],
        )


def test_canonical_revision_still_rejects_duplicate_correction_paths() -> None:
    correction = UserCorrection(
        field_pointer="/hero_player_id",
        detected_value=None,
        approved_value="hero",
        corrected_at=NOW,
    )

    with pytest.raises(ValidationError, match="same field twice"):
        CanonicalHandRevision(
            revision=1,
            detection_id="detection-1",
            approved_at=NOW,
            state=hand_state(hero_player_id="hero"),
            corrections=[correction, correction],
        )


def test_non_overlapping_corrections_apply_to_the_approved_copy() -> None:
    approved_payload = hand_state().model_dump()
    approved_payload["hero_player_id"] = "hero"
    approved_payload["seats"][0]["display_name"] = "Hero"
    approved_state = ImportedHandState.model_validate(approved_payload)
    approved_revision = CanonicalHandRevision(
        revision=1,
        detection_id="detection-1",
        approved_at=NOW,
        state=approved_state,
        corrections=[
            UserCorrection(
                field_pointer="/hero_player_id",
                detected_value=None,
                approved_value="hero",
                corrected_at=NOW,
            ),
            UserCorrection(
                field_pointer="/seats/0/display_name",
                detected_value=None,
                approved_value="Hero",
                corrected_at=NOW,
            ),
        ],
    )

    record = ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected()],
        canonical_revisions=[approved_revision],
        lifecycle={
            "status": "active",
            "active_canonical_revision": 1,
            "changed_at": NOW,
        },
    )

    assert record.active_state_for_extraction == approved_state


def test_each_correction_detected_value_uses_the_immutable_detection() -> None:
    detected_state = hand_state()
    detected_seat = detected_state.model_dump(mode="json")["seats"][0]
    intermediate_seat = {**detected_seat, "display_name": "H"}
    approved_payload = detected_state.model_dump()
    approved_payload["seats"][0]["display_name"] = "Hero"
    approved_state = ImportedHandState.model_validate(approved_payload)
    unsafe_revision = CanonicalHandRevision(
        revision=1,
        detection_id="detection-1",
        approved_at=NOW,
        state=approved_state,
    ).model_copy(
        update={
            "corrections": [
                UserCorrection(
                    field_pointer="/seats/0",
                    detected_value=detected_seat,
                    approved_value=intermediate_seat,
                    corrected_at=NOW,
                ),
                UserCorrection(
                    field_pointer="/seats/0/display_name",
                    detected_value="H",
                    approved_value="Hero",
                    corrected_at=NOW,
                ),
            ]
        }
    )

    unsafe_record = ImportedHandRecord.model_construct(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected(detected_state)],
        conflicts=[],
        canonical_revisions=[unsafe_revision],
        lifecycle=ImportedHandLifecycle(
            status="active",
            active_canonical_revision=1,
            changed_at=NOW,
        ),
        deletion_receipt=None,
    )

    with pytest.raises(
        ValueError,
        match="detected_value does not match /seats/0/display_name",
    ):
        unsafe_record.validate_aggregate()


@pytest.mark.parametrize("wrong_detected_value", [True, 1.0])
def test_correction_detected_value_uses_strict_json_scalar_types(
    wrong_detected_value: bool | float,
) -> None:
    unchanged_revision = CanonicalHandRevision(
        revision=1,
        detection_id="detection-1",
        approved_at=NOW,
        state=hand_state(),
        corrections=[
            UserCorrection(
                field_pointer="/button_seat",
                detected_value=wrong_detected_value,
                approved_value=1,
                corrected_at=NOW,
            )
        ],
    )

    with pytest.raises(
        ValidationError,
        match="detected_value does not match /button_seat",
    ):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[detected()],
            canonical_revisions=[unchanged_revision],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 1,
                "changed_at": NOW,
            },
        )


@pytest.mark.parametrize("wrong_approved_value", [True, 1.0])
def test_approved_copy_uses_strict_json_scalar_types(
    wrong_approved_value: bool | float,
) -> None:
    mismatched_revision = CanonicalHandRevision(
        revision=1,
        detection_id="detection-1",
        approved_at=NOW,
        state=hand_state(),
        corrections=[
            UserCorrection(
                field_pointer="/button_seat",
                detected_value=None,
                approved_value=wrong_approved_value,
                corrected_at=NOW,
            )
        ],
    )

    with pytest.raises(ValidationError, match="only through corrections"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[detected()],
            canonical_revisions=[mismatched_revision],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 1,
                "changed_at": NOW,
            },
        )


def test_approved_copy_uses_strict_json_types_recursively() -> None:
    detected_state = hand_state()
    detected_seat = detected_state.model_dump(mode="json")["seats"][0]
    wrongly_typed_seat = {**detected_seat, "seat_number": True}
    mismatched_revision = CanonicalHandRevision(
        revision=1,
        detection_id="detection-1",
        approved_at=NOW,
        state=detected_state,
        corrections=[
            UserCorrection(
                field_pointer="/seats/0",
                detected_value=detected_seat,
                approved_value=wrongly_typed_seat,
                corrected_at=NOW,
            )
        ],
    )

    with pytest.raises(ValidationError, match="only through corrections"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[detected(detected_state)],
            canonical_revisions=[mismatched_revision],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 1,
                "changed_at": NOW,
            },
        )


@pytest.mark.parametrize("token", ["-1", "+1", "01", "1.0", "-"])
def test_correction_paths_reject_noncanonical_array_indices(token: str) -> None:
    invalid_revision = CanonicalHandRevision(
        revision=1,
        detection_id="detection-1",
        approved_at=NOW,
        state=hand_state(),
        corrections=[
            UserCorrection(
                field_pointer=f"/seats/{token}/player_id",
                detected_value="hero",
                approved_value="hero",
                corrected_at=NOW,
            )
        ],
    )

    with pytest.raises(ValidationError, match="non-canonical array index"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[detected()],
            canonical_revisions=[invalid_revision],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 1,
                "changed_at": NOW,
            },
        )


def test_approval_cannot_precede_its_referenced_detection() -> None:
    future_detection = detected().model_copy(
        update={"detected_at": NOW + timedelta(microseconds=1)}
    )
    approval = CanonicalHandRevision(
        revision=1,
        detection_id=future_detection.detection_id,
        approved_at=NOW,
        state=hand_state(),
    )

    with pytest.raises(ValidationError, match="cannot precede referenced detection"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[future_detection],
            canonical_revisions=[approval],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 1,
                "changed_at": NOW,
            },
        )


def test_successive_approval_timestamps_cannot_move_backward() -> None:
    first = CanonicalHandRevision(
        revision=1,
        detection_id="detection-1",
        approved_at=NOW + timedelta(minutes=2),
        state=hand_state(),
    )
    second = CanonicalHandRevision(
        revision=2,
        detection_id="detection-1",
        approved_at=NOW + timedelta(minutes=1),
        state=hand_state(),
    )

    with pytest.raises(
        ValidationError,
        match="revision 2 approved_at cannot precede canonical revision 1 approved_at",
    ):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[detected()],
            canonical_revisions=[first, second],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 2,
                "changed_at": NOW,
            },
        )


def test_active_lifecycle_cannot_precede_its_selected_approval() -> None:
    approval = revision().model_copy(
        update={"approved_at": NOW + timedelta(microseconds=1)}
    )

    with pytest.raises(
        ValidationError,
        match="active lifecycle changed_at cannot precede.*approved_at",
    ):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[detected()],
            canonical_revisions=[approval],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 1,
                "changed_at": NOW,
            },
        )


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(microseconds=1)])
def test_active_lifecycle_accepts_equal_or_later_selected_approval_time(
    offset: timedelta,
) -> None:
    approved_at = NOW + timedelta(minutes=1)
    approval = revision().model_copy(update={"approved_at": approved_at})

    record = ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected()],
        canonical_revisions=[approval],
        lifecycle={
            "status": "active",
            "active_canonical_revision": 1,
            "changed_at": approved_at + offset,
        },
    )

    assert record.lifecycle.changed_at == approved_at + offset


def test_pending_review_lifecycle_timestamp_does_not_order_canonical_approval(
) -> None:
    approval = revision().model_copy(
        update={"approved_at": NOW + timedelta(microseconds=1)}
    )

    record = ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected()],
        canonical_revisions=[approval],
        lifecycle={"status": "pending_review", "changed_at": NOW},
    )

    assert record.lifecycle.status == "pending_review"


def test_deletion_pending_lifecycle_timestamp_does_not_order_canonical_approval(
) -> None:
    approval = revision().model_copy(
        update={"approved_at": NOW + timedelta(microseconds=1)}
    )

    record = ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected()],
        canonical_revisions=[approval],
        lifecycle={
            "status": "deletion_pending",
            "deletion_generation": 1,
            "changed_at": NOW,
            "deletion_request": {
                "generation": 1,
                "requested_at": NOW,
                "cleanup_status": "pending",
            },
        },
    )

    assert record.lifecycle.status == "deletion_pending"


@pytest.mark.parametrize("status", ["withdrawn", "rejected"])
def test_withdrawn_or_rejected_lifecycle_cannot_precede_latest_approval(
    status: str,
) -> None:
    first = revision()
    latest = first.model_copy(
        update={
            "revision": 2,
            "approved_at": NOW + timedelta(microseconds=1),
        }
    )

    with pytest.raises(
        ValidationError,
        match="withdrawn/rejected lifecycle changed_at cannot precede.*approved_at",
    ):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[detected()],
            canonical_revisions=[first, latest],
            lifecycle={"status": status, "changed_at": NOW},
        )


@pytest.mark.parametrize("status", ["withdrawn", "rejected"])
@pytest.mark.parametrize("offset", [timedelta(0), timedelta(microseconds=1)])
def test_withdrawn_or_rejected_lifecycle_accepts_equal_or_later_latest_approval(
    status: str,
    offset: timedelta,
) -> None:
    approved_at = NOW + timedelta(minutes=1)
    approval = revision().model_copy(update={"approved_at": approved_at})

    record = ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected()],
        canonical_revisions=[approval],
        lifecycle={"status": status, "changed_at": approved_at + offset},
    )

    assert record.lifecycle.changed_at == approved_at + offset


def test_reapproval_revisions_are_monotonic_and_latest_only_is_active() -> None:
    first = revision()
    second = first.model_copy(update={"revision": 2, "approved_at": NOW})

    record = ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected()],
        canonical_revisions=[first, second],
        lifecycle={
            "status": "active",
            "active_canonical_revision": 2,
            "changed_at": NOW,
        },
    )
    assert record.active_state_for_extraction == second.state

    with pytest.raises(ValidationError, match="monotonic"):
        ImportedHandRecord(
            identity=IDENTITY,
            raw_sources=[raw_source()],
            detections=[detected()],
            canonical_revisions=[second],
            lifecycle={
                "status": "active",
                "active_canonical_revision": 2,
                "changed_at": NOW,
            },
        )


@pytest.mark.parametrize("status", ["withdrawn", "rejected"])
def test_withdrawal_and_rejection_retain_audit_but_clear_active_pointer(
    status: str,
) -> None:
    active = active_record()
    inactive = ImportedHandRecord(
        identity=active.identity,
        raw_sources=active.raw_sources,
        detections=active.detections,
        canonical_revisions=active.canonical_revisions,
        lifecycle={"status": status, "changed_at": NOW, "reason": "player request"},
    )

    assert inactive.active_state_for_extraction is None
    assert inactive.canonical_revisions == active.canonical_revisions


def test_failed_deletion_is_visibly_pending_and_learning_ineligible() -> None:
    active = active_record()
    pending = ImportedHandRecord(
        identity=active.identity,
        raw_sources=active.raw_sources,
        detections=active.detections,
        canonical_revisions=active.canonical_revisions,
        lifecycle=ImportedHandLifecycle(
            status="deletion_pending",
            deletion_generation=1,
            changed_at=NOW,
            deletion_request=DeletionRequest(
                generation=1,
                requested_at=NOW,
                cleanup_status="failed",
                last_error="aggregate rebuild failed",
            ),
        ),
    )

    assert pending.lifecycle.learning_eligible is False
    assert pending.active_state_for_extraction is None


def test_permanent_deletion_retains_only_non_sensitive_generation_receipt() -> None:
    deleted = ImportedHandRecord(
        identity=None,
        lifecycle={
            "status": "deleted",
            "deletion_generation": 2,
            "changed_at": NOW,
            "reason": "purged",
        },
        deletion_receipt=DeletionReceipt(
            receipt_id="deletion-2",
            generation=2,
            deleted_at=NOW,
            tombstone_sha256="b" * 64,
        ),
    )

    assert deleted.active_state_for_extraction is None
    assert deleted.raw_sources == []
    assert deleted.canonical_revisions == []

    with pytest.raises(ValidationError, match="cannot retain hand-linked"):
        ImportedHandRecord(
            identity=None,
            raw_sources=[raw_source()],
            lifecycle=deleted.lifecycle,
            deletion_receipt=deleted.deletion_receipt,
        )


def test_restore_cannot_resurrect_a_deleted_generation_without_explicit_reimport() -> None:
    deleted = ImportedHandRecord(
        identity=None,
        lifecycle={
            "status": "deleted",
            "deletion_generation": 2,
            "changed_at": NOW,
        },
        deletion_receipt=DeletionReceipt(
            receipt_id="deletion-2",
            generation=2,
            deleted_at=NOW,
            tombstone_sha256="b" * 64,
        ),
    )
    stale_backup = active_record()
    same_generation_backup = stale_backup.model_copy(
        update={
            "lifecycle": ImportedHandLifecycle(
                status="active",
                active_canonical_revision=1,
                deletion_generation=2,
                changed_at=NOW,
            )
        }
    )

    assert classify_restore(deleted, stale_backup).kind == "stale_deletion_generation"
    assert (
        classify_restore(deleted, same_generation_backup).kind
        == "explicit_reimport_required"
    )
    assert (
        classify_restore(
            deleted,
            same_generation_backup,
            user_authorized_reimport=True,
        ).kind
        == "allow"
    )


def record_with_revisions(
    revision_count: int,
    *,
    status: str = "active",
    changed_at: datetime = NOW,
) -> ImportedHandRecord:
    detected_state = detected()
    revisions = [
        revision().model_copy(update={"revision": revision_number})
        for revision_number in range(1, revision_count + 1)
    ]
    return ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected_state],
        canonical_revisions=revisions,
        lifecycle={
            "status": status,
            "active_canonical_revision": (
                revision_count if status == "active" else None
            ),
            "changed_at": changed_at,
        },
    )


def test_higher_generation_restore_rejects_a_different_retained_identity() -> None:
    alternate_identity = StableHandIdentity(
        site="pokerstars",
        source_hand_id="different-hand",
    )
    alternate_payload = hand_state().model_dump()
    alternate_payload["identity"] = alternate_identity.model_dump()
    alternate_state = ImportedHandState.model_validate(alternate_payload)
    alternate_detection = detected(alternate_state)
    candidate = ImportedHandRecord(
        identity=alternate_identity,
        raw_sources=[raw_source(identity=alternate_identity)],
        detections=[alternate_detection],
        canonical_revisions=[
            CanonicalHandRevision(
                revision=1,
                detection_id=alternate_detection.detection_id,
                approved_at=NOW,
                state=alternate_state,
            )
        ],
        lifecycle={
            "status": "active",
            "active_canonical_revision": 1,
            "deletion_generation": 1,
            "changed_at": NOW + timedelta(minutes=1),
        },
    )

    disposition = classify_restore(active_record(), candidate)

    assert disposition.kind == "conflict_merge_required"


def test_higher_generation_restore_requires_the_current_revision_prefix() -> None:
    current = record_with_revisions(2)
    candidate = record_with_revisions(1).model_copy(
        update={
            "lifecycle": ImportedHandLifecycle(
                status="active",
                active_canonical_revision=1,
                deletion_generation=1,
                changed_at=NOW + timedelta(minutes=1),
            )
        }
    )

    disposition = classify_restore(current, candidate)

    assert disposition.kind == "conflict_merge_required"


def test_higher_generation_restore_allows_a_same_identity_audit_extension() -> None:
    current = record_with_revisions(1)
    candidate = record_with_revisions(2).model_copy(
        update={
            "lifecycle": ImportedHandLifecycle(
                status="active",
                active_canonical_revision=2,
                deletion_generation=1,
                changed_at=NOW + timedelta(minutes=1),
            )
        }
    )

    disposition = classify_restore(current, candidate)

    assert disposition.kind == "allow"


def test_higher_generation_restore_allows_a_valid_deletion_tombstone() -> None:
    tombstone = ImportedHandRecord(
        identity=None,
        lifecycle={
            "status": "deleted",
            "deletion_generation": 1,
            "changed_at": NOW + timedelta(minutes=1),
        },
        deletion_receipt=DeletionReceipt(
            receipt_id="deletion-1",
            generation=1,
            deleted_at=NOW + timedelta(minutes=1),
            tombstone_sha256="b" * 64,
        ),
    )

    disposition = classify_restore(active_record(), tombstone)

    assert disposition.kind == "allow"


def test_higher_generation_retained_restore_still_requires_explicit_reimport() -> None:
    deleted = ImportedHandRecord(
        identity=None,
        lifecycle={
            "status": "deleted",
            "deletion_generation": 2,
            "changed_at": NOW,
        },
        deletion_receipt=DeletionReceipt(
            receipt_id="deletion-2",
            generation=2,
            deleted_at=NOW,
            tombstone_sha256="b" * 64,
        ),
    )
    candidate = active_record().model_copy(
        update={
            "lifecycle": ImportedHandLifecycle(
                status="active",
                active_canonical_revision=1,
                deletion_generation=3,
                changed_at=NOW + timedelta(minutes=1),
            )
        }
    )

    assert classify_restore(deleted, candidate).kind == "explicit_reimport_required"
    assert (
        classify_restore(
            deleted,
            candidate,
            user_authorized_reimport=True,
        ).kind
        == "allow"
    )


def test_same_generation_restore_rejects_an_older_canonical_revision() -> None:
    current = record_with_revisions(2, changed_at=NOW + timedelta(minutes=2))
    candidate = record_with_revisions(1, changed_at=NOW + timedelta(minutes=1))

    disposition = classify_restore(current, candidate)

    assert disposition.kind == "stale_record"


@pytest.mark.parametrize("status", ["withdrawn", "rejected"])
def test_same_generation_restore_cannot_reactivate_a_newer_inactive_record(
    status: str,
) -> None:
    current = record_with_revisions(
        1,
        status=status,
        changed_at=NOW + timedelta(minutes=2),
    )
    candidate = record_with_revisions(1, changed_at=NOW + timedelta(minutes=1))

    disposition = classify_restore(current, candidate)

    assert disposition.kind == "stale_record"


def test_same_generation_restore_allows_an_idempotent_record() -> None:
    current = active_record()

    disposition = classify_restore(current, current.model_copy(deep=True))

    assert disposition.kind == "allow"


def test_same_generation_restore_allows_a_monotonic_revision_extension() -> None:
    current = record_with_revisions(1, changed_at=NOW + timedelta(minutes=1))
    candidate = record_with_revisions(2, changed_at=NOW + timedelta(minutes=2))

    disposition = classify_restore(current, candidate)

    assert disposition.kind == "allow"


def test_same_generation_restore_requires_merge_for_divergent_revision_history() -> None:
    current = record_with_revisions(1, changed_at=NOW + timedelta(minutes=1))
    candidate_revision = revision().model_copy(
        update={"approved_at": NOW + timedelta(minutes=1)}
    )
    candidate = ImportedHandRecord(
        identity=IDENTITY,
        raw_sources=[raw_source()],
        detections=[detected()],
        canonical_revisions=[candidate_revision],
        lifecycle={
            "status": "active",
            "active_canonical_revision": 1,
            "changed_at": NOW + timedelta(minutes=2),
        },
    )

    disposition = classify_restore(current, candidate)

    assert disposition.kind == "conflict_merge_required"


def test_newer_lifecycle_on_an_older_revision_requires_conflict_merge() -> None:
    current = record_with_revisions(2, changed_at=NOW + timedelta(minutes=1))
    candidate = record_with_revisions(
        1,
        status="withdrawn",
        changed_at=NOW + timedelta(minutes=2),
    )

    disposition = classify_restore(current, candidate)

    assert disposition.kind == "conflict_merge_required"


def test_restore_requires_merge_before_reactivating_an_inactive_record() -> None:
    current = record_with_revisions(
        1,
        status="withdrawn",
        changed_at=NOW + timedelta(minutes=1),
    )
    candidate = record_with_revisions(2, changed_at=NOW + timedelta(minutes=2))

    disposition = classify_restore(current, candidate)

    assert disposition.kind == "conflict_merge_required"
