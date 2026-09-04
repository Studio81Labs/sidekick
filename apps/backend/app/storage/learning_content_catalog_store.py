"""Private atomic storage for the current learning-content catalog."""

from __future__ import annotations

import json
import os
from pathlib import Path
from stat import S_ISREG
import tempfile
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from app.application.learning_content_catalog import LearningContentCatalog
from app.domain.learning_content import PrincipleRecord


LEARNING_CONTENT_CATALOG_FILENAME = ".poker-hero-learning-content-catalog.json"
LEARNING_CONTENT_CATALOG_SCHEMA = "poker-hero-learning-content-catalog"
LEARNING_CONTENT_CATALOG_SCHEMA_VERSION = 1
LEARNING_CONTENT_CATALOG_ID = "sidekick.learning-content"
MAX_LEARNING_CONTENT_CATALOG_BYTES = 16 * 1024 * 1024

Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^[a-f0-9]{64}$", strict=True),
]
NonNegativeInteger = Annotated[int, Field(ge=0, strict=True)]


class LearningContentCatalogStorageError(RuntimeError):
    """The install-local learning-content catalog cannot be trusted."""


class LearningContentCatalogConflict(LearningContentCatalogStorageError):
    """A catalog publication was based on stale or divergent current state."""


class LearningContentCatalogState(BaseModel):
    """Versioned persisted envelope for one canonical catalog snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_name: Literal[LEARNING_CONTENT_CATALOG_SCHEMA] = Field(alias="schema")
    schema_version: Literal[LEARNING_CONTENT_CATALOG_SCHEMA_VERSION]
    catalog_sha256: Sha256Digest
    catalog: LearningContentCatalog

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        try:
            catalog = LearningContentCatalog.model_validate(
                self.catalog.model_dump(mode="python")
            )
        except (AttributeError, ValidationError) as exc:
            raise ValueError(
                "stored learning-content catalog must be canonical"
            ) from exc
        if catalog != self.catalog:
            raise ValueError("stored learning-content catalog must be canonical")
        if catalog.catalog_id != LEARNING_CONTENT_CATALOG_ID:
            raise ValueError(
                "stored learning-content catalog has unsupported identity"
            )
        if self.catalog_sha256 != catalog.semantic_digest():
            raise ValueError("stored learning-content catalog digest does not match")
        return self

    @classmethod
    def from_catalog(cls, catalog: LearningContentCatalog) -> Self:
        validated = LearningContentCatalog.model_validate(
            catalog.model_dump(mode="python")
        )
        if validated != catalog:
            raise ValueError("stored learning-content catalog must be canonical")
        return cls(
            schema=LEARNING_CONTENT_CATALOG_SCHEMA,
            schema_version=LEARNING_CONTENT_CATALOG_SCHEMA_VERSION,
            catalog_sha256=validated.semantic_digest(),
            catalog=validated,
        )


class _CatalogPublicationPrecondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    catalog_revision: NonNegativeInteger
    catalog_sha256: Sha256Digest


def empty_learning_content_catalog_state() -> LearningContentCatalogState:
    return LearningContentCatalogState.from_catalog(
        LearningContentCatalog.empty(LEARNING_CONTENT_CATALOG_ID)
    )


def _payload(state: LearningContentCatalogState) -> bytes:
    return (
        json.dumps(
            state.model_dump(mode="json", by_alias=True),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _principle_key(record: PrincipleRecord) -> tuple[str, str, str]:
    principle = record.principle
    return (
        principle.taxonomy_series_id,
        principle.principle_id,
        principle.principle_revision,
    )


def _require_append_only_successor(
    current: LearningContentCatalog,
    successor: LearningContentCatalog,
) -> None:
    if (
        successor.catalog_id != current.catalog_id
        or successor.catalog_revision != current.catalog_revision + 1
        or successor.predecessor_catalog_sha256 != current.semantic_digest()
    ):
        raise LearningContentCatalogConflict(
            "Learning-content catalog successor must bind the current catalog"
        )
    if (
        successor.taxonomy_lineage[: len(current.taxonomy_lineage)]
        != current.taxonomy_lineage
        or successor.mapping_lineage[: len(current.mapping_lineage)]
        != current.mapping_lineage
    ):
        raise LearningContentCatalogConflict(
            "Learning-content catalog successor cannot rewrite revision history"
        )
    current_principles = {
        _principle_key(record): record for record in current.principles
    }
    successor_principles = {
        _principle_key(record): record for record in successor.principles
    }
    for key, previous in current_principles.items():
        candidate = successor_principles.get(key)
        if (
            candidate is None
            or candidate.principle != previous.principle
            or candidate.lifecycle[: len(previous.lifecycle)] != previous.lifecycle
        ):
            raise LearningContentCatalogConflict(
                "Learning-content catalog successor cannot rewrite principle history"
            )
    if (
        successor.taxonomy_lineage == current.taxonomy_lineage
        and successor.mapping_lineage == current.mapping_lineage
        and successor.principles == current.principles
    ):
        raise LearningContentCatalogConflict(
            "Learning-content catalog successor must change retained content"
        )


class FileLearningContentCatalogStore:
    """One install-local content authority guarded by the workspace data lock."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / LEARNING_CONTENT_CATALOG_FILENAME

    def initialize_empty(self) -> LearningContentCatalogState:
        """Create the empty authority without adopting caller-provided content."""

        expected = empty_learning_content_catalog_state()
        payload = _payload(expected)
        if len(payload) > MAX_LEARNING_CONTENT_CATALOG_BYTES:
            raise LearningContentCatalogStorageError(
                "Learning-content catalog exceeds its size limit"
            )
        temporary_path: Path | None = None
        publication_error: OSError | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=self.data_dir,
                prefix=".poker-hero-learning-content-catalog.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.fchmod(temporary.fileno(), 0o600)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.link(temporary_path, self.path)
            except FileExistsError:
                pass
        except OSError as exc:
            publication_error = exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError as exc:
                    if publication_error is None:
                        publication_error = exc
        if publication_error is not None:
            raise LearningContentCatalogStorageError(
                "Cannot durably initialize learning-content catalog:"
                f" {publication_error}"
            ) from publication_error
        state = self.load()
        if state != expected:
            raise LearningContentCatalogStorageError(
                "Cannot initialize learning-content catalog from a non-empty"
                " predecessor"
            )
        try:
            _fsync_directory(self.data_dir)
        except OSError as exc:
            raise LearningContentCatalogStorageError(
                f"Cannot make learning-content catalog durable: {exc}"
            ) from exc
        return state

    def load(self) -> LearningContentCatalogState:
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags)
        except OSError as exc:
            raise LearningContentCatalogStorageError(
                f"Cannot safely open learning-content catalog: {exc}"
            ) from exc
        try:
            file_stat = os.fstat(descriptor)
            if not S_ISREG(file_stat.st_mode):
                raise LearningContentCatalogStorageError(
                    "Learning-content catalog must be a regular file"
                )
            if file_stat.st_mode & 0o077:
                raise LearningContentCatalogStorageError(
                    "Learning-content catalog must be readable only by its owner"
                )
            if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
                raise LearningContentCatalogStorageError(
                    "Learning-content catalog must be owned by the current user"
                )
            chunks: list[bytes] = []
            total_bytes = 0
            while True:
                chunk = os.read(
                    descriptor,
                    MAX_LEARNING_CONTENT_CATALOG_BYTES + 1 - total_bytes,
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total_bytes += len(chunk)
                if total_bytes > MAX_LEARNING_CONTENT_CATALOG_BYTES:
                    raise LearningContentCatalogStorageError(
                        "Learning-content catalog exceeds its size limit"
                    )
            payload = b"".join(chunks)
        except OSError as exc:
            raise LearningContentCatalogStorageError(
                f"Cannot safely read learning-content catalog: {exc}"
            ) from exc
        finally:
            os.close(descriptor)
        try:
            return LearningContentCatalogState.model_validate_json(payload)
        except ValidationError as exc:
            raise LearningContentCatalogStorageError(
                "Learning-content catalog is malformed or unsupported"
            ) from exc

    def save(
        self,
        successor: LearningContentCatalog,
        *,
        expected_catalog_revision: int,
        expected_catalog_sha256: str,
    ) -> LearningContentCatalogState:
        """Publish one append-only snapshot with exact CAS preconditions."""

        try:
            precondition = _CatalogPublicationPrecondition(
                catalog_revision=expected_catalog_revision,
                catalog_sha256=expected_catalog_sha256,
            )
            validated_successor = LearningContentCatalog.model_validate(
                successor.model_dump(mode="python")
            )
        except (AttributeError, ValidationError) as exc:
            raise LearningContentCatalogStorageError(
                "Learning-content catalog publication is not canonical"
            ) from exc
        if validated_successor != successor:
            raise LearningContentCatalogStorageError(
                "Learning-content catalog successor is not canonical"
            )
        successor = validated_successor
        current = self.load()
        expected_revision = precondition.catalog_revision
        expected_digest = precondition.catalog_sha256

        if current.catalog == successor:
            if (
                successor.catalog_revision < 1
                or expected_revision != successor.catalog_revision - 1
                or expected_digest != successor.predecessor_catalog_sha256
            ):
                raise LearningContentCatalogConflict(
                    "Learning-content catalog publication is stale"
                )
        else:
            if (
                current.catalog.catalog_revision != expected_revision
                or current.catalog_sha256 != expected_digest
            ):
                raise LearningContentCatalogConflict(
                    "Learning-content catalog publication is stale"
                )
            _require_append_only_successor(current.catalog, successor)

        state = LearningContentCatalogState.from_catalog(successor)
        payload = _payload(state)
        if len(payload) > MAX_LEARNING_CONTENT_CATALOG_BYTES:
            raise LearningContentCatalogStorageError(
                "Learning-content catalog exceeds its size limit"
            )
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=self.data_dir,
                prefix=".poker-hero-learning-content-catalog.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.fchmod(temporary.fileno(), 0o600)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
            _fsync_directory(self.data_dir)
        except OSError as exc:
            raise LearningContentCatalogStorageError(
                f"Cannot durably write learning-content catalog: {exc}"
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
        return state
