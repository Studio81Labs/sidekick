from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.pokerstars_corpus_assessment as corpus_assessment
from app.pokerstars_corpus_assessment import (
    CorpusAssessmentError,
    PokerStarsCorpusAssessmentReport,
    PokerStarsCorpusManifest,
    assess_pokerstars_corpus,
    format_pokerstars_corpus_report,
    load_pokerstars_corpus_manifest,
    main,
)


FIXTURES = Path(__file__).parent / "fixtures" / "pokerstars"


def _origin(kind: str, basis: str, confidence: str | None, line: int) -> dict:
    return {
        "kind": kind,
        "basis": basis,
        "confidence": confidence,
        "semantics_revision": None,
        "automatic_reason": None,
        "evidence_lines": [line],
    }


def _action(
    sequence: int,
    actor_seat_number: int,
    action_type: str,
    amount: str | None,
    total_committed: str,
    line: int,
    *,
    origin_kind: str,
    origin_basis: str,
    origin_confidence: str | None,
) -> dict:
    return {
        "sequence": sequence,
        "actor_seat_number": actor_seat_number,
        "action_type": action_type,
        "amount": amount,
        "total_committed": total_committed,
        "all_in": False,
        "origin": _origin(
            origin_kind,
            origin_basis,
            origin_confidence,
            line,
        ),
        "evidence_lines": [line],
    }


def _parsed_expectation() -> dict:
    return {
        "outcome": "parsed",
        "disposition": "clean",
        "source_hand_id": "900000000003",
        "played_at": "2026-08-30T12:36:56-04:00",
        "source_timezone": "ET",
        "source_session_id": None,
        "game": {
            "variant": "texas_holdem",
            "betting_limit": "no_limit",
            "table_size": 2,
            "blinds": {
                "small_blind": "0.50",
                "big_blind": "1.00",
                "ante": "0",
                "ante_mode": "unknown",
                "straddle": None,
            },
            "economics": {
                "kind": "cash",
                "currency": "USD",
                "rake": None,
            },
        },
        "button_seat": 1,
        "seats": [
            {
                "seat_number": 1,
                "starting_stack": "100.00",
                "participation": "dealt_in",
                "position": {
                    "dealt_in_player_count": 2,
                    "action_index": 0,
                    "button_distance": 0,
                    "display_label": "BTN/SB",
                },
            },
            {
                "seat_number": 2,
                "starting_stack": "100.00",
                "participation": "dealt_in",
                "position": {
                    "dealt_in_player_count": 2,
                    "action_index": 1,
                    "button_distance": 1,
                    "display_label": "BB",
                },
            },
        ],
        "hero_seat_number": 1,
        "hero_cards": [
            {"rank": "9", "suit": "clubs"},
            {"rank": "8", "suit": "clubs"},
        ],
        "streets": [
            {
                "street": "preflop",
                "board_cards": [],
                "actions": [
                    _action(
                        0,
                        1,
                        "post_small_blind",
                        "0.50",
                        "0.50",
                        5,
                        origin_kind="forced_system",
                        origin_basis="explicit_marker",
                        origin_confidence="1",
                    ),
                    _action(
                        1,
                        2,
                        "post_big_blind",
                        "1.00",
                        "1.00",
                        6,
                        origin_kind="forced_system",
                        origin_basis="explicit_marker",
                        origin_confidence="1",
                    ),
                    _action(
                        2,
                        1,
                        "fold",
                        None,
                        "0.50",
                        9,
                        origin_kind="unknown",
                        origin_basis="unresolved",
                        origin_confidence=None,
                    ),
                    _action(
                        3,
                        2,
                        "uncalled_return",
                        "0.50",
                        "0.50",
                        10,
                        origin_kind="forced_system",
                        origin_basis="explicit_marker",
                        origin_confidence="1",
                    ),
                ],
            }
        ],
        "results": {
            "stated_pot": {
                "gross_total": "1.00",
                "rake": "0.00",
                "net_total": "1.00",
                "gross_pots": [],
            },
            "showdown": [],
            "awards": [
                {
                    "seat_number": 2,
                    "amount": "1.00",
                    "pot_index": None,
                    "evidence_lines": [11],
                }
            ],
            "players": [],
        },
        "warnings": [
            "Action origin is unresolved for 1 player decision(s); review is required."
        ],
    }


def _legacy_tournament_expectation() -> dict:
    expected = _parsed_expectation()
    expected["game"]["economics"] = {
        "kind": "tournament",
        "tournament_id": "tournament-1",
        "tournament_type": "freezeout",
        "stage": None,
        "currency": "USD",
        "paid_places": None,
        "players_remaining": None,
        "payouts": [],
        "remaining_stacks": [],
        "bounty_format": None,
        "bounties": [],
        "icm_inputs_complete": False,
    }
    return expected


def _manifest_payload(
    source_path: str = "synthetic-mixed.txt",
    *,
    include_rejection: bool = True,
) -> dict:
    cases = [
        {
            "case_id": "synthetic-clean",
            "source_path": source_path,
            "hand_ordinal": 1,
            "tags": [
                "cash",
                "forced_system_action",
                "heads_up",
                "uncalled_bet",
                "unknown_action",
            ],
            "expected": _parsed_expectation(),
        }
    ]
    if include_rejection:
        cases.append(
            {
                "case_id": "synthetic-unsupported",
                "source_path": source_path,
                "hand_ordinal": 2,
                "tags": ["full_ring", "tournament"],
                "expected": {
                    "outcome": "rejected",
                    "source_hand_id": "900000000004",
                    "diagnostic_code": "unsupported_header",
                },
            }
        )
    return {
        "schema_version": "pokerstars-corpus-manifest/v1",
        "cases": cases,
    }


def _write_manifest(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_assessment_matches_complete_labels_and_redacts_report(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest(
        tmp_path / "manifest.json",
        _manifest_payload(),
    )

    report = assess_pokerstars_corpus(
        manifest_path,
        corpus_root=FIXTURES,
    )

    assert report.total_cases == 2
    assert report.expected_parse_cases == report.clean_cases == 1
    assert report.clean_parse_rate == 0.5
    assert report.expected_rejection_cases == report.correctly_rejected_cases == 1
    assert report.passed_cases == 2
    assert report.failed_cases == 0
    assert report.reconciliation_counts == {"pass": 1}
    assert report.diagnostic_counts == {"unsupported_header": 1}
    assert report.labeled_tag_counts == {
        "cash": 1,
        "forced_system_action": 1,
        "full_ring": 1,
        "heads_up": 1,
        "tournament": 1,
        "uncalled_bet": 1,
        "unknown_action": 1,
    }
    assert report.verified_parse_tag_counts == {
        "cash": 1,
        "forced_system_action": 1,
        "heads_up": 1,
        "uncalled_bet": 1,
        "unknown_action": 1,
    }
    assert report.economics_counts == {"cash": 1}
    assert report.table_size_counts == {"2": 1}
    assert [case.actual_outcome for case in report.cases] == [
        "parsed",
        "rejected",
    ]

    serialized = report.model_dump_json(indent=2)
    assert PokerStarsCorpusAssessmentReport.model_validate_json(serialized) == report
    rendered = format_pokerstars_corpus_report(report)
    for private_value in (
        "synthetic-mixed.txt",
        "900000000003",
        "900000000004",
        "Mixed Hero",
        "Mixed Rival",
        "Synthetic Mixed",
        "Uncalled bet",
    ):
        assert private_value not in serialized
        assert private_value not in rendered
    for card in ("9c", "8c"):
        assert f'"{card}"' not in serialized
        assert f" {card}" not in rendered


def test_assessment_reports_ground_truth_categories_without_values(
    tmp_path: Path,
) -> None:
    payload = _manifest_payload()
    payload["cases"][0]["expected"]["streets"][0]["actions"][2]["origin"].update(
        {
            "kind": "player_selected",
            "basis": "explicit_marker",
            "confidence": "1",
        }
    )
    payload["cases"][0]["tags"] = [
        "cash",
        "forced_system_action",
        "heads_up",
        "player_selected_action",
        "uncalled_bet",
    ]
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    report = assess_pokerstars_corpus(manifest_path, corpus_root=FIXTURES)

    assert report.passed_cases == 1
    assert report.failed_cases == 1
    assert report.cases[0].failure_codes == ["action_origins_mismatch"]
    serialized = report.model_dump_json()
    assert '"kind":"player_selected"' not in serialized
    assert '"kind":"unknown"' not in serialized


def test_assessment_compares_source_identity_without_emitting_it(
    tmp_path: Path,
) -> None:
    payload = _manifest_payload()
    payload["cases"][0]["expected"]["source_hand_id"] = "private-hand-label"
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    report = assess_pokerstars_corpus(manifest_path, corpus_root=FIXTURES)

    assert report.cases[0].failure_codes == ["provenance_mismatch"]
    serialized = report.model_dump_json()
    assert "private-hand-label" not in serialized
    assert "900000000003" not in serialized


def test_assessment_compares_source_wall_time_and_offset(
    tmp_path: Path,
) -> None:
    payload = _manifest_payload()
    payload["cases"][0]["expected"]["played_at"] = "2026-08-30T16:36:56Z"
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    report = assess_pokerstars_corpus(manifest_path, corpus_root=FIXTURES)

    assert report.cases[0].failure_codes == ["chronology_mismatch"]
    serialized = report.model_dump_json()
    assert "2026-08-30T12:36:56-04:00" not in serialized
    assert "2026-08-30T16:36:56Z" not in serialized


def test_assessment_compares_results_without_emitting_values(
    tmp_path: Path,
) -> None:
    payload = _manifest_payload()
    payload["cases"][0]["expected"]["results"]["awards"][0]["amount"] = "2.00"
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    report = assess_pokerstars_corpus(manifest_path, corpus_root=FIXTURES)

    assert report.passed_cases == 1
    assert report.failed_cases == 1
    assert report.cases[0].failure_codes == ["results_mismatch"]
    serialized = report.model_dump_json()
    assert "2.00" not in serialized
    assert "1.00" not in serialized


def test_assessment_rejects_unlabeled_hand_ordinals(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path / "manifest.json",
        _manifest_payload(include_rejection=False),
    )

    with pytest.raises(CorpusAssessmentError, match="unlabeled hand ordinal"):
        assess_pokerstars_corpus(manifest_path, corpus_root=FIXTURES)


def test_assessment_rejects_duplicate_parser_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_parse = corpus_assessment.parse_pokerstars_text

    def duplicate_first_hand(*args, **kwargs):
        parsed = original_parse(*args, **kwargs)
        return replace(parsed, hands=(parsed.hands[0], parsed.hands[0]))

    monkeypatch.setattr(
        corpus_assessment,
        "parse_pokerstars_text",
        duplicate_first_hand,
    )
    manifest_path = _write_manifest(
        tmp_path / "manifest.json",
        _manifest_payload(),
    )

    with pytest.raises(CorpusAssessmentError, match="duplicate parsed hand ordinals"):
        assess_pokerstars_corpus(manifest_path, corpus_root=FIXTURES)


def test_file_rejection_does_not_discard_another_source(
    tmp_path: Path,
) -> None:
    valid_source = (FIXTURES / "synthetic-mixed.txt").read_text(encoding="utf-8")
    (tmp_path / "a-valid.txt").write_text(valid_source, encoding="utf-8")
    (tmp_path / "b-preamble.txt").write_text(
        "unrecognized export preamble\n" + valid_source,
        encoding="utf-8",
    )
    payload = _manifest_payload("a-valid.txt")
    rejected_source_cases = copy.deepcopy(_manifest_payload("b-preamble.txt")["cases"])
    for case in rejected_source_cases:
        case["case_id"] = "preamble-" + case["case_id"]
        case["expected"]["source_hand_id"] = (
            "preamble-" + case["expected"]["source_hand_id"]
        )
    payload["cases"].extend(rejected_source_cases)
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    report = assess_pokerstars_corpus(manifest_path)

    assert report.passed_cases == 2
    assert report.failed_cases == 2
    assert report.diagnostic_counts == {
        "unsupported_header": 1,
        "unsupported_preamble": 1,
    }
    assert [case.actual_outcome for case in report.cases] == [
        "parsed",
        "rejected",
        "file_rejected",
        "file_rejected",
    ]
    assert all(
        case.failure_codes == ["file_rejection"]
        for case in report.cases[2:]
    )


def test_manifest_rejects_duplicate_cases_and_unsafe_paths(tmp_path: Path) -> None:
    duplicate = _manifest_payload()
    duplicate["cases"][1]["case_id"] = duplicate["cases"][0]["case_id"]
    duplicate_path = _write_manifest(tmp_path / "duplicate.json", duplicate)
    unsafe = _manifest_payload("../private.txt")
    unsafe_path = _write_manifest(tmp_path / "unsafe.json", unsafe)

    with pytest.raises(CorpusAssessmentError, match="manifest is invalid"):
        load_pokerstars_corpus_manifest(duplicate_path)
    with pytest.raises(CorpusAssessmentError, match="manifest is invalid"):
        load_pokerstars_corpus_manifest(unsafe_path)


def test_manifest_rejects_duplicate_source_hand_ids(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["cases"][1]["expected"]["source_hand_id"] = "900000000003"
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    with pytest.raises(CorpusAssessmentError, match="manifest is invalid"):
        load_pokerstars_corpus_manifest(manifest_path)


def test_assessment_rejects_duplicate_source_files(tmp_path: Path) -> None:
    source = (FIXTURES / "synthetic-mixed.txt").read_text(encoding="utf-8")
    (tmp_path / "a.txt").write_text(source, encoding="utf-8")
    (tmp_path / "b.txt").write_text(source, encoding="utf-8")
    payload = _manifest_payload("a.txt")
    copied_cases = copy.deepcopy(_manifest_payload("b.txt")["cases"])
    for case in copied_cases:
        case["case_id"] = "copy-" + case["case_id"]
        case["expected"]["source_hand_id"] = (
            "copy-" + case["expected"]["source_hand_id"]
        )
    payload["cases"].extend(copied_cases)
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    with pytest.raises(CorpusAssessmentError, match="duplicates another source"):
        assess_pokerstars_corpus(manifest_path)


def test_manifest_rejects_composition_tags_that_overstate_labels(
    tmp_path: Path,
) -> None:
    payload = _manifest_payload()
    payload["cases"][0]["tags"] = [
        "cash",
        "heads_up",
        "showdown",
        "sit_out",
        "uncalled_bet",
    ]
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    with pytest.raises(CorpusAssessmentError, match="manifest is invalid"):
        load_pokerstars_corpus_manifest(manifest_path)


def test_manifest_rejects_invalid_action_ground_truth(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["cases"][0]["expected"]["streets"][0]["actions"][2]["amount"] = "1"
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    with pytest.raises(CorpusAssessmentError, match="manifest is invalid"):
        load_pokerstars_corpus_manifest(manifest_path)


def test_manifest_requires_explicit_nullable_ground_truth(tmp_path: Path) -> None:
    payload = _manifest_payload()
    del payload["cases"][0]["expected"]["results"]
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    with pytest.raises(CorpusAssessmentError, match="manifest is invalid"):
        load_pokerstars_corpus_manifest(manifest_path)


def test_manifest_requires_schema_version(tmp_path: Path) -> None:
    payload = _manifest_payload()
    del payload["schema_version"]
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    with pytest.raises(CorpusAssessmentError, match="manifest is invalid"):
        load_pokerstars_corpus_manifest(manifest_path)


def test_v1_manifest_accepts_legacy_tournament_economics_without_source_facts(
    tmp_path: Path,
) -> None:
    payload = _manifest_payload(include_rejection=False)
    case = payload["cases"][0]
    case["tags"] = [
        "forced_system_action",
        "heads_up",
        "tournament",
        "uncalled_bet",
        "unknown_action",
    ]
    case["expected"] = _legacy_tournament_expectation()

    manifest = load_pokerstars_corpus_manifest(
        _write_manifest(tmp_path / "manifest.json", payload)
    )

    economics = manifest.cases[0].expected.game.economics
    assert economics.kind == "tournament"
    assert {
        "entry_buy_in",
        "entry_fee",
        "blind_level",
    }.isdisjoint(economics.model_fields_set)


def test_v1_manifest_accepts_known_tournament_entry_source_facts(
    tmp_path: Path,
) -> None:
    payload = _manifest_payload(include_rejection=False)
    case = payload["cases"][0]
    case["tags"] = [
        "forced_system_action",
        "heads_up",
        "tournament",
        "uncalled_bet",
        "unknown_action",
    ]
    expected = _legacy_tournament_expectation()
    expected["game"]["economics"].update(
        {
            "entry_buy_in": "3.19",
            "entry_fee": "0.31",
            "blind_level": "XI",
        }
    )
    case["expected"] = expected

    manifest = load_pokerstars_corpus_manifest(
        _write_manifest(tmp_path / "manifest.json", payload)
    )

    economics = manifest.cases[0].expected.game.economics
    assert economics.model_dump(mode="json")["entry_buy_in"] == "3.19"
    assert economics.model_dump(mode="json")["entry_fee"] == "0.31"
    assert economics.model_dump(mode="json")["blind_level"] == "XI"


def test_v1_manifest_still_requires_each_legacy_tournament_economics_field(
    tmp_path: Path,
) -> None:
    payload = _manifest_payload(include_rejection=False)
    case = payload["cases"][0]
    case["tags"] = [
        "forced_system_action",
        "heads_up",
        "tournament",
        "uncalled_bet",
        "unknown_action",
    ]
    expected = _legacy_tournament_expectation()
    del expected["game"]["economics"]["stage"]
    case["expected"] = expected

    with pytest.raises(ValidationError, match="expected economics"):
        PokerStarsCorpusManifest.model_validate_json(json.dumps(payload))


def test_corpus_fingerprint_changes_with_source_or_labels(tmp_path: Path) -> None:
    source = (FIXTURES / "synthetic-mixed.txt").read_text(encoding="utf-8")
    source_path = tmp_path / "source.txt"
    source_path.write_text(source, encoding="utf-8")
    manifest_path = _write_manifest(
        tmp_path / "manifest.json",
        _manifest_payload("source.txt"),
    )
    baseline = assess_pokerstars_corpus(manifest_path)
    repeated = assess_pokerstars_corpus(manifest_path)
    assert repeated == baseline

    source_path.write_text(source + "\n", encoding="utf-8")
    changed_source = assess_pokerstars_corpus(manifest_path)
    assert changed_source.corpus_fingerprint != baseline.corpus_fingerprint

    source_path.write_text(source, encoding="utf-8")
    changed_labels = _manifest_payload("source.txt")
    changed_labels["cases"][0]["expected"]["results"]["awards"][0][
        "amount"
    ] = "2.00"
    _write_manifest(manifest_path, changed_labels)
    changed_manifest = assess_pokerstars_corpus(manifest_path)
    assert changed_manifest.corpus_fingerprint != baseline.corpus_fingerprint


def test_cli_emits_redacted_json_and_enforces_all_gates(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _manifest_payload()
    payload["cases"][1]["tags"] = [
        "full_ring",
        "incomplete_hand",
        "side_pot",
        "tournament",
    ]
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    exit_code = main(
        [
            str(manifest_path),
            "--corpus-root",
            str(FIXTURES),
            "--minimum-cases",
            "3",
            "--minimum-clean-parse-rate",
            "1",
            "--minimum-tag-count",
            "side_pot=1",
            "--minimum-labeled-tag-count",
            "incomplete_hand=2",
            "--expected-corpus-fingerprint",
            "0" * 64,
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    report = json.loads(captured.out)
    assert report["total_cases"] == 2
    assert report["labeled_tag_counts"]["side_pot"] == 1
    assert "side_pot" not in report["verified_parse_tag_counts"]
    assert "synthetic-mixed.txt" not in captured.out
    assert "900000000003" not in captured.out
    assert "Corpus has 2 case(s), below the minimum 3" in captured.err
    assert (
        "Verified parsed corpus tag side_pot has 0 case(s), below the minimum 1"
        in captured.err
    )
    assert (
        "Labeled corpus tag incomplete_hand has 1 case(s), below the minimum 2"
        in captured.err
    )
    assert "Corpus fingerprint does not match" in captured.err


def test_cli_resolves_relative_manifest_from_invocation_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_manifest(tmp_path / "manifest.json", _manifest_payload())
    monkeypatch.setenv("POKER_CORPUS_BASE_DIR", str(tmp_path))

    exit_code = main(
        [
            "manifest.json",
            "--corpus-root",
            str(FIXTURES),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["total_cases"] == 2
    assert captured.err == ""


def test_manifest_round_trip_is_strict_and_complete() -> None:
    manifest = PokerStarsCorpusManifest.model_validate_json(
        json.dumps(_manifest_payload())
    )

    assert manifest.cases[0].expected.outcome == "parsed"
    assert manifest.cases[1].expected.outcome == "rejected"
