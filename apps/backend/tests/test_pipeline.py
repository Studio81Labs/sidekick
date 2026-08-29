from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.pipeline import (
    PipelineSelectionError,
    pipeline_capabilities,
    resolve_pipeline_selection,
    settings_for_selection,
)


def test_capabilities_expose_defaults_and_enabled_plugins(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        parser_provider="ocr_cv",
        parser_layout_profile="fortuna_nations",
        parser_enabled_providers=["llm_vision"],
        parser_enabled_layout_profiles=["generic"],
    )

    capabilities = pipeline_capabilities(settings)

    assert capabilities.defaults.model_dump() == {
        "parser_provider": "ocr_cv",
        "parser_layout_profile": "fortuna_nations",
    }
    assert [option.id for option in capabilities.parser_providers] == [
        "ocr_cv",
        "llm_vision",
    ]
    assert capabilities.parser_providers[1].available is False
    assert capabilities.parser_providers[1].unavailable_reason == (
        "External parser URL is not configured"
    )
    assert [option.id for option in capabilities.parser_layout_profiles] == [
        "fortuna_nations",
        "generic",
    ]
    assert capabilities.parser_layout_compatibility == {
        "ocr_cv": ["fortuna_nations", "generic"],
        "llm_vision": ["fortuna_nations", "generic"],
    }


def test_capabilities_expose_fallbacks_when_defaults_are_unavailable(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        parser_provider="llm_vision",
        parser_enabled_providers=["mock"],
    )

    capabilities = pipeline_capabilities(settings)

    assert capabilities.defaults.parser_provider == "llm_vision"
    assert [option.model_dump() for option in capabilities.parser_providers] == [
        {
            "id": "llm_vision",
            "label": "External vision",
            "available": False,
            "unavailable_reason": "External parser URL is not configured",
        },
        {
            "id": "mock",
            "label": "Mock parser",
            "available": True,
            "unavailable_reason": None,
        },
    ]

    with pytest.raises(PipelineSelectionError, match="URL is not configured"):
        resolve_pipeline_selection(settings)


def test_custom_layout_profiles_are_provider_aware(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        parser_provider="llm_vision",
        parser_enabled_providers=["ocr_cv"],
        parser_layout_profile="pokerstars",
        parser_enabled_layout_profiles=["fortuna_nations"],
        external_parser_url="https://parser.example.com/analyze",
    )

    capabilities = pipeline_capabilities(settings)

    assert [option.id for option in capabilities.parser_layout_profiles] == [
        "pokerstars",
        "fortuna_nations",
    ]
    assert capabilities.parser_layout_profiles[0].label == "PokerStars"
    assert capabilities.parser_layout_compatibility == {
        "llm_vision": ["pokerstars", "fortuna_nations"],
        "ocr_cv": ["fortuna_nations"],
    }
    assert resolve_pipeline_selection(
        settings,
        parser_provider="llm_vision",
        parser_layout_profile="pokerstars",
    ).parser_layout_profile == "pokerstars"

    with pytest.raises(PipelineSelectionError, match="not supported"):
        resolve_pipeline_selection(
            settings,
            parser_provider="ocr_cv",
            parser_layout_profile="pokerstars",
        )


def test_automatic_parser_requires_external_fallback_and_supports_all_layouts(
    tmp_path: Path,
) -> None:
    unavailable_settings = Settings(
        data_dir=tmp_path,
        parser_provider="mock",
        parser_enabled_providers=["auto"],
        parser_layout_profile="generic",
        parser_enabled_layout_profiles=["pokerstars"],
    )

    unavailable = pipeline_capabilities(unavailable_settings)

    assert unavailable.parser_providers[1].model_dump() == {
        "id": "auto",
        "label": "Automatic recognition",
        "available": False,
        "unavailable_reason": (
            "External parser URL is required for automatic recognition"
        ),
    }
    assert unavailable.parser_layout_compatibility["auto"] == [
        "generic",
        "pokerstars",
    ]
    with pytest.raises(PipelineSelectionError, match="required for automatic"):
        resolve_pipeline_selection(unavailable_settings, parser_provider="auto")

    available_settings = unavailable_settings.model_copy(
        update={"external_parser_url": "https://parser.example.com/parse"}
    )
    selected = resolve_pipeline_selection(
        available_settings,
        parser_provider="auto",
        parser_layout_profile="pokerstars",
    )

    assert selected.parser_provider == "auto"
    assert selected.parser_layout_profile == "pokerstars"


def test_selection_rejects_plugins_not_enabled_for_deployment(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    with pytest.raises(PipelineSelectionError, match="not enabled"):
        resolve_pipeline_selection(settings, parser_provider="ocr_cv")

    with pytest.raises(PipelineSelectionError, match="Unknown parser provider"):
        resolve_pipeline_selection(settings, parser_provider="missing")


def test_selection_builds_job_scoped_settings_copy(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        parser_provider="mock",
        parser_enabled_providers=["ocr_cv"],
        parser_layout_profile="generic",
        parser_enabled_layout_profiles=["fortuna"],
    )
    selection = resolve_pipeline_selection(
        settings,
        parser_provider="ocr_cv",
        parser_layout_profile="fortuna",
    )

    scoped = settings_for_selection(settings, selection)

    assert scoped.parser_provider == "ocr_cv"
    assert scoped.parser_layout_profile == "fortuna"
    assert settings.parser_provider == "mock"
    assert settings.parser_layout_profile == "generic"


def test_enabled_plugin_ids_are_normalized_and_validated(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        parser_enabled_providers=[" OCR_CV ", "ocr_cv"],
        parser_enabled_layout_profiles=[" PokerStars ", "pokerstars"],
    )

    assert settings.parser_enabled_providers == ["ocr_cv"]
    assert settings.parser_enabled_layout_profiles == ["pokerstars"]

    with pytest.raises(ValidationError, match="unknown plugin ID"):
        Settings(data_dir=tmp_path, parser_enabled_providers=["shell_command"])

    with pytest.raises(ValidationError, match="invalid layout profile ID"):
        Settings(data_dir=tmp_path, parser_enabled_layout_profiles=["poker-stars"])
