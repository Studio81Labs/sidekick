import pytest
from pydantic import BaseModel, ValidationError

from app.domain.pipeline import (
    PipelineCapabilities,
    PipelineOption,
    PipelineSelection,
)
def test_pipeline_capabilities_parse_nested_contracts() -> None:
    capabilities = PipelineCapabilities(
        defaults={
            "parser_provider": "ocr_cv",
            "parser_layout_profile": "fortuna_nations",
            "recommendation_provider": "local_solver",
            "recommendation_engine": "postflop_solver",
        },
        parser_providers=[{"id": "ocr_cv", "label": "Local OCR"}],
        parser_layout_profiles=[
            {"id": "fortuna_nations", "label": "Fortuna / Nations"}
        ],
        parser_layout_compatibility={"ocr_cv": ["fortuna_nations"]},
        recommendation_providers=[
            {"id": "local_solver", "label": "Local solver"}
        ],
        recommendation_engines=[
            {"id": "postflop_solver", "label": "Postflop solver"}
        ],
    )

    assert capabilities.defaults.recommendation_engine == "postflop_solver"
    assert capabilities.parser_providers[0].available is True
    assert capabilities.recommendation_engines[0].unavailable_reason is None


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (PipelineOption, {"id": "OCR-CV", "label": "Local OCR"}),
        (
            PipelineSelection,
            {
                "parser_provider": "ocr_cv",
                "parser_layout_profile": "fortuna_nations",
                "recommendation_provider": "local_solver",
                "recommendation_engine": "",
            },
        ),
    ],
)
def test_pipeline_contracts_reject_invalid_plugin_ids(
    model: type[BaseModel],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)
