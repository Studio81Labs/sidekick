from pathlib import Path
from typing import Any, get_type_hints

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.domain.benchmarks import BenchmarkFieldComparison, BenchmarkOverview
from app.domain.poker import (
    Card,
    CanonicalState,
    CompletedPostflopAction,
    CompletedPostflopStreetHistory,
    DetectedState,
    ParserResult,
    PreflopAction,
    PostflopAction,
)
from app.domain.recommendations import RecommendationAction, RecommendationResult
from app.domain.training import TrainingDecisionRequest


def test_benchmark_overview_requires_consistent_layout_counts() -> None:
    with pytest.raises(ValidationError):
        BenchmarkOverview(
            included_cases=2,
            included_cases_by_layout={"generic": 1},
            default_layout_profile="generic",
        )


def test_benchmark_overview_requires_pipeline_report_identity() -> None:
    with pytest.raises(ValidationError):
        BenchmarkOverview(
            included_cases=0,
            included_cases_by_layout={},
            default_layout_profile="generic",
            parser_pipelines=[{
                "parser": {
                    "id": "mock",
                    "label": "Mock parser",
                },
                "layout_profile": "generic",
                "latest_report": {
                    "id": "a" * 32,
                    "parser_provider": "ocr_cv",
                    "layout_profile": "generic",
                    "created_at": "2026-08-11T08:00:00Z",
                    "total_cases": 1,
                    "failed_cases": 0,
                    "accuracy": 1,
                },
            }],
        )


def test_benchmark_overview_requires_pipeline_reports_from_same_corpus() -> None:
    latest_report = {
        "id": "b" * 32,
        "parser_provider": "mock",
        "layout_profile": "generic",
        "corpus_fingerprint": "a" * 64,
        "created_at": "2026-08-11T09:00:00Z",
        "total_cases": 1,
        "failed_cases": 0,
        "accuracy": 1,
    }
    with pytest.raises(ValidationError):
        BenchmarkOverview(
            included_cases=0,
            included_cases_by_layout={},
            default_layout_profile="generic",
            parser_pipelines=[{
                "parser": {
                    "id": "mock",
                    "label": "Mock parser",
                },
                "layout_profile": "generic",
                "latest_report": latest_report,
                "previous_report": {
                    **latest_report,
                    "id": "a" * 32,
                    "corpus_fingerprint": "b" * 64,
                    "created_at": "2026-08-11T08:00:00Z",
                },
            }],
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("hero_cards", [10**400]),
        ("hero_cards", ["AX"]),
        ("hero_cards", ["Kd", "Ah"]),
        ("hero_cards", ["Ah", "Ah"]),
        ("pot_size", "12.5"),
        ("pot_size", float("inf")),
        ("preflop_open_size", 0),
        ("players_in_hand", True),
        ("street", "showdown"),
        ("facing_action", "check"),
        ("hero_position", []),
        ("hero_position", "BTN"),
        ("opponent_position", []),
        ("opponent_position", "BTN"),
        ("preflop_opener_position", " OOP "),
        ("action_context", ""),
        ("action_context", "  cutoff   raises  "),
    ],
)
def test_benchmark_comparison_rejects_values_outside_field_schema(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        BenchmarkFieldComparison(
            field=field_name,
            expected=value,
            detected=value,
            matched=True,
        )


def test_settings_defaults_use_local_training_backends(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert settings.data_dir == tmp_path
    assert settings.deployment_environment == "local"
    assert settings.data_volume_id is None
    assert settings.parser_provider == "mock"
    assert settings.parser_layout_profile == "generic"
    assert settings.parser_auto_approve_enabled is False
    assert settings.recommendation_provider == "rule_based"
    assert settings.local_solver_engine == "postflop_solver"
    assert settings.local_solver_timeout_seconds == 120
    assert settings.postflop_solver_fallback_enabled is True
    assert settings.postflop_solver_max_iterations == 400
    assert settings.postflop_solver_target_exploitability == 0.01
    assert settings.postflop_solver_max_memory_mb == 768
    assert settings.postflop_solver_bet_sizes == "70%"
    assert settings.postflop_solver_raise_sizes == "2.5x"
    assert settings.postflop_solver_range_mode == "contextual"
    assert settings.max_upload_bytes == 10 * 1024 * 1024
    assert settings.max_dataset_upload_bytes == 100 * 1024 * 1024
    assert settings.max_backup_upload_bytes == 100 * 1024 * 1024
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.proxy_shared_secret is None
    assert settings.sentry_dsn is None
    assert settings.sentry_environment == "local"
    assert settings.sentry_release is None
    assert settings.sentry_error_sample_rate == 1
    assert settings.api_rate_limit_enabled is True
    assert settings.api_rate_limit_uploads_per_minute == 120
    assert settings.api_rate_limit_recommendations_per_minute == 120
    assert settings.api_rate_limit_benchmarks_per_minute == 6
    assert settings.api_rate_limit_data_transfers_per_minute == 6
    assert settings.external_parser_bearer_token is None
    assert settings.external_provider_bearer_token is None
    assert settings.llm_advice_bearer_token is None
    assert settings.external_request_timeout_seconds == 60


def test_settings_normalize_blank_optional_sentry_release(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, sentry_release="  ")

    assert settings.sentry_release is None


@pytest.mark.parametrize(
    "dsn",
    [
        "http://public@example.ingest.sentry.io/123",
        "https://example.ingest.sentry.io",
        "https://example.ingest.sentry.io/123",
        "https://public@example.ingest.sentry.io/123?player=name",
        "not-a-url",
    ],
)
def test_settings_rejects_invalid_sentry_dsn(dsn: str) -> None:
    with pytest.raises(ValidationError, match="complete HTTPS Sentry DSN"):
        Settings(sentry_dsn=dsn)


def test_settings_reads_poker_prefixed_provider_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POKER_DEPLOYMENT_ENVIRONMENT", "staging")
    monkeypatch.setenv("POKER_PARSER_PROVIDER", "external")
    monkeypatch.setenv("POKER_RECOMMENDATION_PROVIDER", "solver")
    monkeypatch.setenv("POKER_LOCAL_SOLVER_ENGINE", "local_ev")
    monkeypatch.setenv("POKER_EXTERNAL_PROVIDER_BEARER_TOKEN", "solver-token")
    monkeypatch.setenv("POKER_EXTERNAL_REQUEST_TIMEOUT_SECONDS", "12.5")

    settings = Settings()

    assert settings.deployment_environment == "staging"
    assert settings.parser_provider == "external"
    assert settings.recommendation_provider == "solver"
    assert settings.local_solver_engine == "local_ev"
    assert settings.external_provider_bearer_token is not None
    assert settings.external_provider_bearer_token.get_secret_value() == "solver-token"
    assert settings.external_request_timeout_seconds == 12.5


def test_application_settings_loader_reads_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "POKER_PARSER_PROVIDER=ocr_cv\n"
        "POKER_POSTFLOP_SOLVER_MAX_ITERATIONS=17\n"
        "POKER_POSTFLOP_SOLVER_BET_SIZES=50%,100%\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert settings.parser_provider == "ocr_cv"
    assert settings.postflop_solver_max_iterations == 17
    assert settings.postflop_solver_bet_sizes == "50%,100%"


def test_settings_parses_thresholds_from_json_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "POKER_PARSER_AUTO_APPROVE_THRESHOLDS",
        '{"hero_cards": 0.9, "board_cards": 0.85}',
    )

    settings = Settings()

    assert settings.parser_auto_approve_thresholds == {
        "hero_cards": 0.9,
        "board_cards": 0.85,
    }


def test_settings_rejects_invalid_auto_approve_threshold() -> None:
    with pytest.raises(ValidationError):
        Settings(parser_auto_approve_thresholds={"hero_cards": 1.5})


def test_settings_rejects_non_positive_solver_timeout() -> None:
    with pytest.raises(ValidationError):
        Settings(local_solver_timeout_seconds=0)
    with pytest.raises(ValidationError):
        Settings(external_request_timeout_seconds=0)


def test_settings_rejects_invalid_postflop_solver_limits() -> None:
    with pytest.raises(ValidationError):
        Settings(postflop_solver_max_iterations=0)
    with pytest.raises(ValidationError):
        Settings(postflop_solver_target_exploitability=1.1)
    with pytest.raises(ValidationError):
        Settings(postflop_solver_max_memory_mb=0)
    with pytest.raises(ValidationError):
        Settings(postflop_solver_rake_rate=-0.01)
    with pytest.raises(ValidationError):
        Settings(postflop_solver_range_mode="automatic")


def test_settings_rejects_non_positive_max_upload_bytes() -> None:
    with pytest.raises(ValidationError):
        Settings(max_upload_bytes=0)
    with pytest.raises(ValidationError):
        Settings(max_dataset_upload_bytes=0)
    with pytest.raises(ValidationError):
        Settings(max_backup_upload_bytes=0)


def test_settings_rejects_invalid_api_rate_limits() -> None:
    with pytest.raises(ValidationError):
        Settings(api_rate_limit_uploads_per_minute=0)
    with pytest.raises(ValidationError):
        Settings(api_rate_limit_recommendations_per_minute=10_001)
    with pytest.raises(ValidationError):
        Settings(api_rate_limit_benchmarks_per_minute=0)
    with pytest.raises(ValidationError):
        Settings(api_rate_limit_data_transfers_per_minute=10_001)


def test_settings_validate_hosted_mcp_configuration() -> None:
    with pytest.raises(ValidationError, match="requires a staging or production"):
        Settings(
            mcp_enabled=True,
            mcp_public_url="https://poker.example/mcp",
        )
    with pytest.raises(ValidationError, match="POKER_MCP_PUBLIC_URL is required"):
        Settings(deployment_environment="staging", mcp_enabled=True)
    with pytest.raises(ValidationError, match="exact path /mcp"):
        Settings(
            deployment_environment="staging",
            mcp_enabled=True,
            mcp_public_url="https://poker.example/api/mcp",
        )
    with pytest.raises(ValidationError, match="exact path /mcp"):
        Settings(
            deployment_environment="staging",
            mcp_enabled=True,
            mcp_public_url="https://poker.example:not-a-port/mcp",
        )
    with pytest.raises(ValidationError, match="supported only in staging"):
        Settings(deployment_environment="production", mcp_allow_writes=True)

    settings = Settings(
        deployment_environment="staging",
        mcp_enabled=True,
        mcp_public_url="https://faß.example:443/mcp",
        mcp_allowed_origins=["https://faß.example:443"],
        mcp_allow_writes=True,
    )
    assert settings.mcp_enabled is True
    assert settings.mcp_allow_writes is True
    assert settings.mcp_public_url == "https://xn--fa-hia.example/mcp"
    assert settings.mcp_allowed_origins == ["https://xn--fa-hia.example"]

    ipv6 = Settings(
        deployment_environment="staging",
        mcp_enabled=True,
        mcp_public_url="https://[2001:0db8:0:0:0:0:0:1]:443/mcp",
        mcp_allowed_origins=["https://[2001:0db8:0:0:0:0:0:1]:443"],
    )
    assert ipv6.mcp_public_url == "https://[2001:db8::1]/mcp"
    assert ipv6.mcp_allowed_origins == ["https://[2001:db8::1]"]

    ipv4 = Settings(
        deployment_environment="staging",
        mcp_enabled=True,
        mcp_public_url="https://127.0.0.1:443/mcp",
    )
    assert ipv4.mcp_public_url == "https://127.0.0.1/mcp"

    non_default_port = Settings(
        deployment_environment="staging",
        mcp_enabled=True,
        mcp_public_url="https://poker.example:8443/mcp",
    )
    assert non_default_port.mcp_public_url == "https://poker.example:8443/mcp"


@pytest.mark.parametrize(
    "hostname",
    ["127.1", "0177.0.0.1", "2130706433", "0x7f.1"],
)
def test_settings_reject_browser_ambiguous_ipv4_hosts(hostname: str) -> None:
    with pytest.raises(ValidationError, match="POKER_MCP_PUBLIC_URL"):
        Settings(
            deployment_environment="staging",
            mcp_enabled=True,
            mcp_public_url=f"https://{hostname}/mcp",
        )

    with pytest.raises(ValidationError, match="POKER_MCP_ALLOWED_ORIGINS"):
        Settings(
            deployment_environment="staging",
            mcp_enabled=True,
            mcp_public_url="https://poker.example/mcp",
            mcp_allowed_origins=[f"https://{hostname}"],
        )


def test_settings_validates_data_volume_identity() -> None:
    assert Settings(data_volume_id="production-data-volume-01").data_volume_id == (
        "production-data-volume-01"
    )

    with pytest.raises(ValidationError):
        Settings(data_volume_id="too-short")
    with pytest.raises(ValidationError):
        Settings(data_volume_id="invalid volume identity")


def test_settings_normalizes_and_validates_proxy_shared_secret() -> None:
    assert Settings(proxy_shared_secret="").proxy_shared_secret is None
    secret = Settings(proxy_shared_secret=f"  {'s' * 32}  ").proxy_shared_secret

    assert secret is not None
    assert secret.get_secret_value() == "s" * 32

    with pytest.raises(ValidationError):
        Settings(proxy_shared_secret="too-short")


def test_settings_default_to_disabled_administrative_ocr_test_mode(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert settings.admin_ocr_test_enabled is False
    assert settings.admin_ocr_test_token is None


def test_settings_require_token_when_administrative_ocr_test_mode_is_enabled(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="POKER_ADMIN_OCR_TEST_TOKEN is required"):
        Settings(data_dir=tmp_path, admin_ocr_test_enabled=True)


@pytest.mark.parametrize(
    "token",
    ["short-token", "x" * 31, "has space " + "x" * 30, "tab\t" + "x" * 32, "ünïcode" + "x" * 30],
)
def test_settings_reject_weak_administrative_ocr_test_tokens(
    tmp_path: Path,
    token: str,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            data_dir=tmp_path,
            admin_ocr_test_enabled=True,
            admin_ocr_test_token=token,
        )


def test_settings_normalize_and_mask_administrative_ocr_test_token(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        admin_ocr_test_enabled=True,
        admin_ocr_test_token="  " + "a" * 40 + "  ",
    )

    assert settings.admin_ocr_test_token is not None
    assert settings.admin_ocr_test_token.get_secret_value() == "a" * 40
    assert "a" * 40 not in repr(settings)
    assert Settings(data_dir=tmp_path, admin_ocr_test_token="   ").admin_ocr_test_token is None


def test_settings_reject_administrative_ocr_test_token_reusing_proxy_secret(
    tmp_path: Path,
) -> None:
    secret = "b" * 40

    with pytest.raises(ValidationError, match="must differ from POKER_PROXY_SHARED_SECRET"):
        Settings(
            data_dir=tmp_path,
            proxy_shared_secret=secret,
            admin_ocr_test_enabled=True,
            admin_ocr_test_token=secret,
        )


def test_settings_normalizes_and_masks_external_bearer_tokens() -> None:
    assert Settings(external_parser_bearer_token="").external_parser_bearer_token is None
    token = Settings(external_parser_bearer_token="  parser-token  ").external_parser_bearer_token

    assert token is not None
    assert token.get_secret_value() == "parser-token"
    assert "parser-token" not in repr(token)

    with pytest.raises(ValidationError, match="must not contain whitespace"):
        Settings(external_parser_bearer_token="invalid token")
    with pytest.raises(ValidationError, match="ASCII"):
        Settings(external_parser_bearer_token="töken")


@pytest.mark.parametrize(
    ("url_field", "token_field"),
    [
        ("external_parser_url", "external_parser_bearer_token"),
        ("external_provider_url", "external_provider_bearer_token"),
        ("llm_advice_url", "llm_advice_bearer_token"),
    ],
)
def test_settings_require_https_for_authenticated_external_services(
    url_field: str,
    token_field: str,
) -> None:
    token = "must-not-appear-in-validation-output"

    with pytest.raises(ValidationError, match="must use HTTPS") as exc_info:
        Settings(**{url_field: "http://service.example/api", token_field: token})

    assert token not in str(exc_info.value)


def test_card_from_code_normalizes_rank_and_suit() -> None:
    card = Card.from_code("Ah")

    assert card.rank == "A"
    assert card.suit == "hearts"
    assert card.code == "Ah"


def test_card_rejects_unknown_rank() -> None:
    with pytest.raises(ValidationError):
        Card(rank="1", suit="hearts")


def test_card_schema_exposes_rank_and_suit_enums() -> None:
    schema = Card.model_json_schema()

    assert schema["properties"]["rank"]["enum"] == [
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "T",
        "J",
        "Q",
        "K",
        "A",
    ]
    assert schema["properties"]["suit"]["enum"] == ["clubs", "diamonds", "hearts", "spades"]


def test_detected_state_rejects_too_many_hero_cards() -> None:
    with pytest.raises(ValidationError):
        DetectedState(
            hero_cards=[
                Card.from_code("Ah"),
                Card.from_code("Kd"),
                Card.from_code("Qs"),
            ]
        )


def test_detected_state_rejects_too_many_board_cards() -> None:
    with pytest.raises(ValidationError):
        DetectedState(
            board_cards=[
                Card.from_code("Ah"),
                Card.from_code("Kd"),
                Card.from_code("Qs"),
                Card.from_code("Jc"),
                Card.from_code("2h"),
                Card.from_code("3d"),
            ]
        )


def test_canonical_state_rejects_duplicate_cards_across_state() -> None:
    with pytest.raises(ValidationError):
        CanonicalState(
            hero_cards=[Card.from_code("Ah")],
            board_cards=[Card.from_code("Ah")],
        )


def test_detected_state_rejects_unknown_facing_action() -> None:
    with pytest.raises(ValidationError):
        DetectedState(facing_action="call")


@pytest.mark.parametrize(
    "values",
    [
        {"actor": "oop", "action": "check", "amount": 1.0},
        {"actor": "ip", "action": "bet"},
        {"actor": "oop", "action": "raise", "amount": 0},
    ],
)
def test_postflop_action_rejects_inconsistent_amount(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PostflopAction.model_validate(values)


@pytest.mark.parametrize(
    "actions",
    [
        [{"actor": "oop", "action": "check"}],
        [
            {"actor": "ip", "action": "check"},
            {"actor": "oop", "action": "check"},
        ],
        [
            {"actor": "oop", "action": "bet", "amount": 2.0},
            {"actor": "ip", "action": "call", "amount": 1.5},
        ],
        [
            {"actor": "oop", "action": "bet", "amount": 2.0},
            {"actor": "ip", "action": "check"},
        ],
        [
            {"actor": "oop", "action": "bet", "amount": 2.0},
            {"actor": "ip", "action": "call", "amount": 2.0},
            {"actor": "oop", "action": "check"},
        ],
    ],
)
def test_completed_postflop_history_rejects_nonterminal_or_illegal_lines(
    actions: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError):
        CompletedPostflopStreetHistory(street="flop", actions=actions)


def test_completed_postflop_history_accepts_checked_and_raised_lines() -> None:
    checked = CompletedPostflopStreetHistory(
        street="flop",
        actions=[
            CompletedPostflopAction(actor="oop", action="check"),
            CompletedPostflopAction(actor="ip", action="check"),
        ],
    )
    raised = CompletedPostflopStreetHistory(
        street="turn",
        actions=[
            CompletedPostflopAction(actor="oop", action="check"),
            CompletedPostflopAction(actor="ip", action="bet", amount=2.0),
            CompletedPostflopAction(actor="oop", action="raise", amount=6.0),
            CompletedPostflopAction(actor="ip", action="call", amount=6.0),
        ],
    )

    assert checked.actions[-1].action == "check"
    assert raised.actions[-1].amount == 6.0


def test_completed_postflop_history_serializes_only_when_present() -> None:
    empty = CanonicalState(street="turn")
    populated = CanonicalState(
        street="turn",
        completed_postflop_streets=[
            CompletedPostflopStreetHistory(
                street="flop",
                actions=[
                    CompletedPostflopAction(actor="oop", action="check"),
                    CompletedPostflopAction(actor="ip", action="check"),
                ],
            )
        ],
    )

    assert "completed_postflop_streets" not in empty.model_dump(mode="json")
    assert populated.model_dump(mode="json")["completed_postflop_streets"] == [
        {
            "street": "flop",
            "actions": [
                {"actor": "oop", "action": "check", "amount": None},
                {"actor": "ip", "action": "check", "amount": None},
            ],
        }
    ]


def test_state_rejects_completed_history_at_or_after_current_street() -> None:
    history = CompletedPostflopStreetHistory(
        street="turn",
        actions=[
            CompletedPostflopAction(actor="oop", action="check"),
            CompletedPostflopAction(actor="ip", action="check"),
        ],
    )

    with pytest.raises(ValidationError, match="before the current street"):
        CanonicalState(street="turn", completed_postflop_streets=[history])


@pytest.mark.parametrize(
    "values",
    [
        {"actor": "dealer", "action": "raise", "amount": 2.5},
        {"actor": "button", "action": "check", "amount": 2.5},
        {"actor": "button", "action": "raise", "amount": 0},
        {"actor": "button", "action": "call", "amount": None},
    ],
)
def test_preflop_action_rejects_invalid_fields(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PreflopAction.model_validate(values)


def test_preflop_action_accepts_canonical_raise_and_call_totals() -> None:
    actions = [
        PreflopAction(actor="cutoff", action="raise", amount=2.5),
        PreflopAction(actor="button", action="call", amount=2.5),
    ]

    assert [action.model_dump(mode="json") for action in actions] == [
        {"actor": "cutoff", "action": "raise", "amount": 2.5},
        {"actor": "button", "action": "call", "amount": 2.5},
    ]


@pytest.mark.parametrize("action", ["fold", "check", "call"])
def test_recommendation_rejects_sizing_for_non_wager_action(
    action: RecommendationAction,
) -> None:
    with pytest.raises(
        ValidationError,
        match="Sizing is only valid for bet or raise recommendations",
    ):
        RecommendationResult(
            action=action,
            sizing=2.5,
            confidence=0.8,
            explanation="Malformed recommendation",
        )


@pytest.mark.parametrize(
    "model",
    [RecommendationResult, TrainingDecisionRequest],
)
def test_action_line_rejects_nonfinite_sizing(model: type[Any]) -> None:
    values: dict[str, Any] = {"action": "raise", "sizing": float("inf")}
    if model is RecommendationResult:
        values.update(confidence=0.8, explanation="Malformed recommendation")

    with pytest.raises(ValidationError, match="finite number"):
        model(**values)


@pytest.mark.parametrize(
    "model",
    [RecommendationResult, TrainingDecisionRequest],
)
def test_action_line_rejects_zero_wager_sizing(model: type[Any]) -> None:
    values: dict[str, Any] = {"action": "raise", "sizing": 0}
    if model is RecommendationResult:
        values.update(confidence=0.8, explanation="Malformed recommendation")

    with pytest.raises(ValidationError, match="greater than 0"):
        model(**values)


@pytest.mark.parametrize(
    ("model", "sizing"),
    [
        (RecommendationResult, True),
        (RecommendationResult, "7.5"),
        (TrainingDecisionRequest, True),
        (TrainingDecisionRequest, "7.5"),
    ],
)
def test_action_line_rejects_coerced_wager_sizing(
    model: type[Any],
    sizing: object,
) -> None:
    values: dict[str, Any] = {"action": "raise", "sizing": sizing}
    if model is RecommendationResult:
        values.update(confidence=0.8, explanation="Malformed recommendation")

    with pytest.raises(ValidationError, match="valid number"):
        model(**values)


@pytest.mark.parametrize("model", [RecommendationResult, TrainingDecisionRequest])
def test_action_line_accepts_integer_wager_sizing(model: type[Any]) -> None:
    values: dict[str, Any] = {"action": "raise", "sizing": 8}
    if model is RecommendationResult:
        values.update(confidence=0.8, explanation="Valid recommendation")

    result = model(**values)

    assert result.sizing == 8.0


@pytest.mark.parametrize("confidence", [True, "0.8"])
def test_recommendation_rejects_coerced_confidence(confidence: object) -> None:
    with pytest.raises(ValidationError, match="valid number"):
        RecommendationResult(
            action="check",
            confidence=confidence,
            explanation="Malformed recommendation",
        )


def test_recommendation_accepts_integer_confidence() -> None:
    result = RecommendationResult(
        action="check",
        confidence=1,
        explanation="Valid recommendation",
    )

    assert result.confidence == 1.0


@pytest.mark.parametrize("confidence", [True, "0.99"])
def test_parser_result_rejects_coerced_confidence(confidence: object) -> None:
    with pytest.raises(ValidationError, match="valid number"):
        ParserResult(
            state=DetectedState(),
            confidences={"hero_cards": confidence},
        )


def test_parser_result_accepts_integer_confidence() -> None:
    result = ParserResult(
        state=DetectedState(),
        confidences={"hero_cards": 1},
    )

    assert result.confidences["hero_cards"] == 1.0


@pytest.mark.parametrize(
    "model",
    [DetectedState, CanonicalState],
)
@pytest.mark.parametrize(
    "field_name",
    [
        "pot_size",
        "current_bet",
        "hero_stack",
        "opponent_stack",
        "effective_stack",
        "preflop_open_size",
    ],
)
@pytest.mark.parametrize("value", [True, "2.5", float("inf")])
def test_table_state_rejects_invalid_numeric_amounts(
    model: type[Any],
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        model(**{field_name: value})


@pytest.mark.parametrize(
    "model",
    [DetectedState, CanonicalState],
)
@pytest.mark.parametrize(
    "field_name",
    [
        "pot_size",
        "current_bet",
        "hero_stack",
        "opponent_stack",
        "effective_stack",
        "preflop_open_size",
    ],
)
def test_table_state_accepts_integer_numeric_amounts(
    model: type[Any],
    field_name: str,
) -> None:
    result = model(**{field_name: 2})

    assert getattr(result, field_name) == 2.0


@pytest.mark.parametrize("model", [DetectedState, CanonicalState])
@pytest.mark.parametrize("players_in_hand", [True, "3", 3.0])
def test_table_state_rejects_coerced_player_count(
    model: type[Any],
    players_in_hand: object,
) -> None:
    with pytest.raises(ValidationError):
        model(players_in_hand=players_in_hand)


@pytest.mark.parametrize("model", [DetectedState, CanonicalState])
def test_table_state_accepts_integer_player_count(model: type[Any]) -> None:
    result = model(players_in_hand=3)

    assert result.players_in_hand == 3


@pytest.mark.parametrize("model", [DetectedState, CanonicalState])
def test_table_state_validates_opponents_at_current_bet(model: type[Any]) -> None:
    state = model(
        pot_size=12.5,
        current_bet=2.5,
        players_in_hand=3,
        opponents_at_current_bet=2,
        opponent_wager=5,
        opponent_commitment_total=10,
    )

    assert state.opponents_at_current_bet == 2
    assert state.opponent_wager == 5
    assert state.opponent_commitment_total == 10
    with pytest.raises(ValidationError, match="lower than players_in_hand"):
        model(
            current_bet=2.5,
            players_in_hand=3,
            opponents_at_current_bet=3,
        )
    with pytest.raises(ValidationError, match="positive current_bet"):
        model(
            current_bet=0,
            players_in_hand=3,
            opponents_at_current_bet=1,
        )
    with pytest.raises(ValidationError, match="requires players_in_hand"):
        model(
            current_bet=2.5,
            opponents_at_current_bet=1,
        )
    with pytest.raises(ValidationError, match="opponent_wager requires"):
        model(opponent_wager=2.5)
    with pytest.raises(ValidationError, match="at least current_bet"):
        model(current_bet=2.5, opponent_wager=2)
    with pytest.raises(ValidationError, match="cannot exceed pot_size"):
        model(pot_size=9, opponent_commitment_total=10)
    with pytest.raises(ValidationError, match="must cover"):
        model(
            pot_size=12.5,
            current_bet=2.5,
            players_in_hand=3,
            opponents_at_current_bet=2,
            opponent_wager=5,
            opponent_commitment_total=9,
        )
    with pytest.raises(ValidationError, match="must cover"):
        model(
            pot_size=10,
            current_bet=2,
            players_in_hand=2,
            opponents_at_current_bet=1,
            opponent_commitment_total=4,
            street="preflop",
            preflop_action_history=[
                PreflopAction(actor="button", action="raise", amount=5),
            ],
        )
    with pytest.raises(ValidationError, match="cannot exceed the latest wager"):
        model(
            pot_size=30,
            current_bet=5,
            players_in_hand=2,
            opponent_wager=15,
            opponent_commitment_total=20,
        )
    cross_street = model(
        pot_size=30,
        current_bet=15,
        players_in_hand=3,
        opponents_at_current_bet=1,
        opponent_wager=15,
        opponent_commitment_total=20,
        preflop_action_history=[
            PreflopAction(actor="button", action="raise", amount=25),
        ],
        street="flop",
        postflop_action_history=[
            PostflopAction(actor="oop", action="bet", amount=5),
            PostflopAction(actor="ip", action="raise", amount=15),
        ],
    )
    assert cross_street.opponent_commitment_total == 20
    corrected_wager = model(
        pot_size=30,
        current_bet=5,
        players_in_hand=3,
        opponents_at_current_bet=1,
        opponent_wager=10,
        opponent_commitment_total=15,
        street="preflop",
        preflop_action_history=[
            PreflopAction(actor="button", action="raise", amount=20),
        ],
    )
    assert corrected_wager.opponent_commitment_total == 15


def test_canonical_state_rejects_non_positive_preflop_open_size() -> None:
    with pytest.raises(ValidationError):
        CanonicalState(preflop_open_size=0)


def test_canonical_state_copies_detected_values() -> None:
    detected = DetectedState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
        board_cards=[Card.from_code("Qs"), Card.from_code("Jc"), Card.from_code("2h")],
        pot_size=12.5,
        current_bet=2.5,
        hero_stack=97.5,
        opponent_stack=96.0,
        effective_stack=96.0,
        players_in_hand=3,
        opponents_at_current_bet=2,
        opponent_wager=5,
        opponent_commitment_total=10,
        hero_position="button",
        preflop_opener_position="cutoff",
        preflop_open_size=2.5,
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5)
        ],
        street="turn",
        facing_action="bet",
        postflop_action_history=[
            PostflopAction(actor="oop", action="bet", amount=2.5)
        ],
        completed_postflop_streets=[
            CompletedPostflopStreetHistory(
                street="flop",
                actions=[
                    CompletedPostflopAction(actor="oop", action="check"),
                    CompletedPostflopAction(actor="ip", action="check"),
                ],
            )
        ],
        action_context="Cutoff bet 2.5 into 12.5",
    )
    parser_result = ParserResult(
        state=detected,
        confidences={"hero_cards": 0.99, "board_cards": 0.98, "pot_size": 0.92, "street": 1.0},
        warnings=[],
        raw={"provider": "mock"},
    )

    canonical = CanonicalState.from_parser_result(parser_result)

    assert canonical.hero_cards == detected.hero_cards
    assert canonical.board_cards == detected.board_cards
    assert canonical.pot_size == 12.5
    assert canonical.hero_stack == 97.5
    assert canonical.opponent_stack == 96.0
    assert canonical.opponents_at_current_bet == 2
    assert canonical.opponent_wager == 5
    assert canonical.opponent_commitment_total == 10
    assert canonical.facing_action == "bet"
    assert canonical.postflop_action_history == detected.postflop_action_history
    assert (
        canonical.completed_postflop_streets
        == detected.completed_postflop_streets
    )
    assert canonical.preflop_action_history == detected.preflop_action_history
    assert canonical.preflop_opener_position == "cutoff"
    assert canonical.preflop_open_size == 2.5
    assert canonical.user_approved is False


def test_canonical_state_does_not_share_cards_with_detected_state() -> None:
    detected = DetectedState(hero_cards=[Card.from_code("Ah")])
    parser_result = ParserResult(state=detected)

    canonical = CanonicalState.from_parser_result(parser_result)
    detected.hero_cards[0].rank = "K"

    assert canonical.hero_cards[0].code == "Ah"


def test_raw_metadata_types_are_string_keyed_any_dicts() -> None:
    assert get_type_hints(ParserResult)["raw"] == dict[str, Any]
    assert get_type_hints(RecommendationResult)["raw"] == dict[str, Any]
