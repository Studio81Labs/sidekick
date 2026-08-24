import pytest
from pydantic import ValidationError

from app.domain.backups import ApplicationBackupRestoreResult
from app.domain.health import HealthResponse, DeploymentEnvironment
from app.models import (
    ApplicationBackupRestoreResult as CompatibilityApplicationBackupRestoreResult,
    DeploymentEnvironment as CompatibilityDeploymentEnvironment,
    HealthResponse as CompatibilityHealthResponse,
)


def test_health_and_backup_contracts_reexported_from_app_models() -> None:
    assert CompatibilityHealthResponse is HealthResponse
    assert CompatibilityApplicationBackupRestoreResult is ApplicationBackupRestoreResult
    assert CompatibilityDeploymentEnvironment == DeploymentEnvironment


def test_health_response_validates_literal_status_and_payload_shape() -> None:
    health = HealthResponse(
        status="ok",
        environment="production",
        parser_provider="ocr_cv",
        recommendation_provider="local_solver",
        recommendation_engine="local_solver",
    )

    assert health.status == "ok"
    assert health.environment == "production"
    assert health.model_dump() == {
        "status": "ok",
        "environment": "production",
        "parser_provider": "ocr_cv",
        "recommendation_provider": "local_solver",
        "recommendation_engine": "local_solver",
    }


def test_health_response_rejects_invalid_status_and_environment() -> None:
    with pytest.raises(ValidationError):
        HealthResponse(
            status="up",
            environment="production",
            parser_provider="ocr_cv",
            recommendation_provider="rule_based",
            recommendation_engine="engine",
        )

    with pytest.raises(ValidationError):
        HealthResponse(
            status="ok",
            environment="qa",  # type: ignore[arg-type]
            parser_provider="ocr_cv",
            recommendation_provider="rule_based",
            recommendation_engine="engine",
        )


def test_application_backup_restore_result_round_trip_and_constraints() -> None:
    restored = ApplicationBackupRestoreResult(
        imported_jobs=0,
        reused_jobs=1,
        imported_benchmark_reports=2,
        reused_benchmark_reports=3,
        total_jobs=4,
        total_benchmark_reports=5,
    )

    payload = restored.model_dump_json()
    round_tripped = ApplicationBackupRestoreResult.model_validate_json(payload)

    assert round_tripped == restored

    with pytest.raises(ValidationError):
        ApplicationBackupRestoreResult(
            imported_jobs=-1,
            reused_jobs=0,
            imported_benchmark_reports=0,
            reused_benchmark_reports=0,
            total_jobs=0,
            total_benchmark_reports=0,
        )
