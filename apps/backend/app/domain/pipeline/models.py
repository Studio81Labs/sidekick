"""Provider-neutral pipeline selection and capability models."""

from pydantic import BaseModel, Field


class PipelineOption(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1, max_length=100)
    available: bool = True
    unavailable_reason: str | None = Field(default=None, max_length=300)


class PipelineSelection(BaseModel):
    parser_provider: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    parser_layout_profile: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    recommendation_provider: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    recommendation_engine: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )


class PipelineCapabilities(BaseModel):
    defaults: PipelineSelection
    parser_providers: list[PipelineOption]
    parser_layout_profiles: list[PipelineOption]
    parser_layout_compatibility: dict[str, list[str]]
    recommendation_providers: list[PipelineOption]
    recommendation_engines: list[PipelineOption]
