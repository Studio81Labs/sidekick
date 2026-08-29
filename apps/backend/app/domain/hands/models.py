"""Post-upload hand and queue lifecycle contracts."""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.poker import CanonicalState, ParserResult
from app.domain.recommendations import RecommendationResult
from app.domain.training import TrainingDecision

JobStatus = Literal["created", "parsed", "approved", "recommended", "error"]
JobInputContext = Literal["legacy_player", "administrative_test"]


class ScreenshotMetadataRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("title", "notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            stripped = tag.strip()
            if not stripped:
                continue
            if len(stripped) > 32:
                raise ValueError("tags must be at most 32 characters")
            if "," in stripped:
                raise ValueError("tags cannot contain commas")
            key = stripped.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(stripped)
        return normalized


class JobRecord(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(default_factory=lambda: uuid4().hex)
    status: JobStatus = "created"
    input_context: JobInputContext = "legacy_player"
    upload_request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    original_filename: str
    title: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=10)
    image_filename: str
    parser_provider: str
    parser_layout_profile: str | None = None
    recommendation_provider: str
    recommendation_engine: str | None = None
    parser_result: ParserResult | None = None
    parser_auto_approval_eligible: bool | None = None
    approved_state: CanonicalState | None = None
    training_decision: TrainingDecision | None = None
    recommendation: RecommendationResult | None = None
    recommendation_pending: bool = False
    recommendation_request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    benchmark_import_request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    training_reviewed_at: datetime | None = None
    training_review_note: str | None = None
    benchmark_included: bool = False
    archived_at: datetime | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("title", "notes", mode="before")
    @classmethod
    def normalize_optional_metadata_text(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("tags")
    @classmethod
    def normalize_metadata_tags(cls, value: list[str]) -> list[str]:
        return ScreenshotMetadataRequest.normalize_tags(value)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


class ArchiveJobsRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("job_ids")
    @classmethod
    def validate_job_ids(cls, value: list[str]) -> list[str]:
        unique_ids = list(dict.fromkeys(value))
        if len(unique_ids) != len(value):
            raise ValueError("job_ids must not contain duplicates")
        return value


class JobHistory(BaseModel):
    total: int = Field(ge=0)
    jobs: list[JobRecord] = Field(default_factory=list)
    snapshot_version: str


class JobQueue(BaseModel):
    total: int = Field(ge=0)
    jobs: list[JobRecord] = Field(default_factory=list)
    snapshot_version: str
