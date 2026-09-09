from pathlib import Path

import pytest

from api_test_support import make_client, upload_job_with_pipeline


def test_health_reports_active_parser(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "local",
        "parser_provider": "mock",
    }


def test_pipeline_endpoint_reports_runtime_choices(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        parser_layout_profile="generic",
        parser_enabled_layout_profiles=["fortuna_nations"],
    )

    response = client.get("/api/pipeline")

    assert response.status_code == 200
    payload = response.json()
    assert payload["defaults"] == {
        "parser_provider": "mock",
        "parser_layout_profile": "generic",
    }
    assert [option["id"] for option in payload["parser_layout_profiles"]] == [
        "generic",
        "fortuna_nations",
    ]
    assert payload["parser_layout_compatibility"] == {
        "mock": ["generic", "fortuna_nations"],
    }


def test_pipeline_endpoint_reports_fallbacks_for_unavailable_defaults(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        parser_provider="llm_vision",
        parser_enabled_providers=["mock"],
    )

    response = client.get("/api/pipeline")

    assert response.status_code == 200
    payload = response.json()
    assert payload["parser_providers"][0] == {
        "id": "llm_vision",
        "label": "External vision",
        "available": False,
        "unavailable_reason": "External parser URL is not configured",
    }
    assert payload["parser_providers"][1]["id"] == "mock"
    assert payload["parser_providers"][1]["available"] is True


def test_upload_persists_explicit_pipeline_selection(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        parser_enabled_layout_profiles=["pokerstars"],
    )

    response = upload_job_with_pipeline(
        client,
        parser_provider="mock",
        parser_layout_profile="pokerstars",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["parser_provider"] == "mock"
    assert payload["parser_layout_profile"] == "pokerstars"


def test_upload_rejects_pipeline_plugin_not_enabled_by_deployment(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = upload_job_with_pipeline(
        client,
        parser_provider="ocr_cv",
        parser_layout_profile="generic",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Parser provider 'ocr_cv' is not enabled for this deployment"
    )
    assert list((tmp_path / "jobs").iterdir()) == []


def test_upload_rejects_layout_not_supported_by_selected_parser(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        parser_enabled_providers=["ocr_cv"],
        parser_enabled_layout_profiles=["pokerstars"],
    )

    response = upload_job_with_pipeline(
        client,
        parser_provider="ocr_cv",
        parser_layout_profile="pokerstars",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Layout profile 'pokerstars' is not supported by parser provider 'ocr_cv'"
    )
    assert list((tmp_path / "jobs").iterdir()) == []


def test_pipeline_reports_administrative_ocr_test_capability(tmp_path: Path) -> None:
    enabled = make_client(tmp_path)
    disabled = make_client(
        tmp_path / "disabled",
        admin_ocr_test_enabled=False,
        admin_ocr_test_token=None,
    )

    assert enabled.get("/api/pipeline").json()["administrative_ocr_test"] == {"enabled": True}
    assert disabled.get("/api/pipeline").json()["administrative_ocr_test"] == {"enabled": False}
