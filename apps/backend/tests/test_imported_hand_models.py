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
    StableHandIdentity,
    StatedPotSummary,
    StructuralPosition,
    TournamentEconomics,
    UserCorrection,
    classify_reimport,
    classify_restore,
    derive_structural_positions,
    imported_hand_state_sha256,
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
        button_seat=1,
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
                        "total_committed": Decimal("0.50"),
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
            "actions": [first_action, *([later_action] if same_street else [])],
        },
        *(
            [{"street": "flop", "actions": [later_action]}]
            if not same_street
            else []
        ),
    ]

    with pytest.raises(ValidationError, match="after folding or going all-in"):
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


def test_extraction_returns_only_voluntary_hero_actions_from_active_approval() -> None:
    selected = {
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
