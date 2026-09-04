"""Private atomic storage for the current reference-activation catalog."""

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

from app.application.reference_activation import (
    ReferenceActivation,
    ReferenceActivationCatalog,
)


REFERENCE_ACTIVATION_CATALOG_FILENAME = (
    ".poker-hero-reference-activation-catalog.json"
)
REFERENCE_ACTIVATION_CATALOG_SCHEMA = "poker-hero-reference-activation-catalog"
REFERENCE_ACTIVATION_CATALOG_SCHEMA_VERSION = 1
REFERENCE_ACTIVATION_CATALOG_ID = "sidekick.reference-activation"
MAX_REFERENCE_ACTIVATION_CATALOG_BYTES = 16 * 1024 * 1024

Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^[a-f0-9]{64}$", strict=True),
]
NonNegativeInteger = Annotated[int, Field(ge=0, strict=True)]


class ReferenceActivationCatalogStorageError(RuntimeError):
    """The install-local reference catalog cannot be trusted or persisted."""


class ReferenceActivationCatalogConflict(ReferenceActivationCatalogStorageError):
    """A catalog publication was based on stale or divergent current state."""


class ReferenceActivationCatalogState(BaseModel):
    """Versioned persisted envelope for one canonical catalog snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_name: Literal[REFERENCE_ACTIVATION_CATALOG_SCHEMA] = Field(
        alias="schema"
    )
    schema_version: Literal[REFERENCE_ACTIVATION_CATALOG_SCHEMA_VERSION]
    catalog_sha256: Sha256Digest
    catalog: ReferenceActivationCatalog

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        try:
            catalog = ReferenceActivationCatalog.model_validate(
                self.catalog.model_dump(mode="python")
            )
        except (AttributeError, ValidationError) as exc:
            raise ValueError("stored reference catalog must be canonical") from exc
        if catalog != self.catalog:
            raise ValueError("stored reference catalog must be canonical")
        if catalog.catalog_id != REFERENCE_ACTIVATION_CATALOG_ID:
            raise ValueError("stored reference catalog has an unsupported identity")
        if self.catalog_sha256 != catalog.semantic_digest():
            raise ValueError("stored reference catalog digest does not match")
        return self

    @classmethod
    def from_catalog(cls, catalog: ReferenceActivationCatalog) -> Self:
        validated = ReferenceActivationCatalog.model_validate(
            catalog.model_dump(mode="python")
        )
        if validated != catalog:
            raise ValueError("stored reference catalog must be canonical")
        return cls(
            schema=REFERENCE_ACTIVATION_CATALOG_SCHEMA,
            schema_version=REFERENCE_ACTIVATION_CATALOG_SCHEMA_VERSION,
            catalog_sha256=validated.semantic_digest(),
            catalog=validated,
        )


class _CatalogPublicationPrecondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    catalog_revision: NonNegativeInteger
    catalog_sha256: Sha256Digest


def empty_reference_activation_catalog_state() -> ReferenceActivationCatalogState:
    return ReferenceActivationCatalogState.from_catalog(
        ReferenceActivationCatalog.empty(REFERENCE_ACTIVATION_CATALOG_ID)
    )


def _payload(state: ReferenceActivationCatalogState) -> bytes:
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


def _active_ids_for(
    activations: tuple[ReferenceActivation, ...],
) -> tuple[str, ...]:
    latest_by_key: dict[tuple[str, str], ReferenceActivation] = {}
    for activation in activations:
        latest_by_key[activation.key] = activation
    return tuple(sorted(item.activation_id for item in latest_by_key.values()))


def _expected_predecessor(
    successor: ReferenceActivationCatalog,
) -> ReferenceActivationCatalog:
    predecessor_activations = successor.activations[:-1]
    return ReferenceActivationCatalog(
        catalog_id=successor.catalog_id,
        catalog_revision=successor.catalog_revision - 1,
        activations=predecessor_activations,
        active_activation_ids=_active_ids_for(predecessor_activations),
    )


class FileReferenceActivationCatalogStore:
    """One install-local catalog authority guarded by the workspace data lock."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / REFERENCE_ACTIVATION_CATALOG_FILENAME

    def initialize_empty(self) -> ReferenceActivationCatalogState:
        """Create the empty authority without adopting caller-provided content."""

        expected = empty_reference_activation_catalog_state()
        payload = _payload(expected)
        if len(payload) > MAX_REFERENCE_ACTIVATION_CATALOG_BYTES:
            raise ReferenceActivationCatalogStorageError(
                "Reference-activation catalog exceeds its size limit"
            )
        temporary_path: Path | None = None
        publication_error: OSError | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=self.data_dir,
                prefix=".poker-hero-reference-activation-catalog.",
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
            raise ReferenceActivationCatalogStorageError(
                "Cannot durably initialize reference-activation catalog:"
                f" {publication_error}"
            ) from publication_error
        state = self.load()
        if state != expected:
            raise ReferenceActivationCatalogStorageError(
                "Cannot initialize reference-activation catalog from a non-empty"
                " predecessor"
            )
        try:
            _fsync_directory(self.data_dir)
        except OSError as exc:
            raise ReferenceActivationCatalogStorageError(
                f"Cannot make reference-activation catalog durable: {exc}"
            ) from exc
        return state

    def load(self) -> ReferenceActivationCatalogState:
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags)
        except OSError as exc:
            raise ReferenceActivationCatalogStorageError(
                f"Cannot safely open reference-activation catalog: {exc}"
            ) from exc
        try:
            file_stat = os.fstat(descriptor)
            if not S_ISREG(file_stat.st_mode):
                raise ReferenceActivationCatalogStorageError(
                    "Reference-activation catalog must be a regular file"
                )
            if file_stat.st_mode & 0o077:
                raise ReferenceActivationCatalogStorageError(
                    "Reference-activation catalog must be readable only by its owner"
                )
            if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
                raise ReferenceActivationCatalogStorageError(
                    "Reference-activation catalog must be owned by the current user"
                )
            chunks: list[bytes] = []
            total_bytes = 0
            while True:
                chunk = os.read(
                    descriptor,
                    MAX_REFERENCE_ACTIVATION_CATALOG_BYTES + 1 - total_bytes,
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total_bytes += len(chunk)
                if total_bytes > MAX_REFERENCE_ACTIVATION_CATALOG_BYTES:
                    raise ReferenceActivationCatalogStorageError(
                        "Reference-activation catalog exceeds its size limit"
                    )
            payload = b"".join(chunks)
        except OSError as exc:
            raise ReferenceActivationCatalogStorageError(
                f"Cannot safely read reference-activation catalog: {exc}"
            ) from exc
        finally:
            os.close(descriptor)
        try:
            return ReferenceActivationCatalogState.model_validate_json(payload)
        except ValidationError as exc:
            raise ReferenceActivationCatalogStorageError(
                "Reference-activation catalog is malformed or unsupported"
            ) from exc

    def save(
        self,
        successor: ReferenceActivationCatalog,
        *,
        expected_catalog_revision: int,
        expected_catalog_sha256: str,
    ) -> ReferenceActivationCatalogState:
        """Publish exactly one append with compare-and-swap preconditions."""

        try:
            precondition = _CatalogPublicationPrecondition(
                catalog_revision=expected_catalog_revision,
                catalog_sha256=expected_catalog_sha256,
            )
            validated_successor = ReferenceActivationCatalog.model_validate(
                successor.model_dump(mode="python")
            )
        except (AttributeError, ValidationError) as exc:
            raise ReferenceActivationCatalogStorageError(
                "Reference-activation catalog publication is not canonical"
            ) from exc
        if validated_successor != successor:
            raise ReferenceActivationCatalogStorageError(
                "Reference-activation catalog successor is not canonical"
            )
        successor = validated_successor
        expected_catalog_revision = precondition.catalog_revision
        expected_catalog_sha256 = precondition.catalog_sha256
        current = self.load()
        expected_revision_matches = (
            current.catalog.catalog_revision == expected_catalog_revision
        )
        expected_digest_matches = (
            current.catalog_sha256 == expected_catalog_sha256
        )

        if current.catalog == successor:
            if successor.catalog_revision < 1:
                raise ReferenceActivationCatalogConflict(
                    "Reference-activation catalog publication has no predecessor"
                )
            predecessor = _expected_predecessor(successor)
            if (
                predecessor.catalog_revision != expected_catalog_revision
                or predecessor.semantic_digest() != expected_catalog_sha256
            ):
                raise ReferenceActivationCatalogConflict(
                    "Reference-activation catalog publication is stale"
                )
        else:
            if not expected_revision_matches or not expected_digest_matches:
                raise ReferenceActivationCatalogConflict(
                    "Reference-activation catalog publication is stale"
                )
            if (
                successor.catalog_id != current.catalog.catalog_id
                or successor.catalog_revision
                != current.catalog.catalog_revision + 1
                or successor.activations[:-1] != current.catalog.activations
            ):
                raise ReferenceActivationCatalogConflict(
                    "Reference-activation catalog successor must append exactly one"
                    " activation"
                )

        state = ReferenceActivationCatalogState.from_catalog(successor)
        payload = _payload(state)
        if len(payload) > MAX_REFERENCE_ACTIVATION_CATALOG_BYTES:
            raise ReferenceActivationCatalogStorageError(
                "Reference-activation catalog exceeds its size limit"
            )
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=self.data_dir,
                prefix=".poker-hero-reference-activation-catalog.",
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
            raise ReferenceActivationCatalogStorageError(
                f"Cannot durably write reference-activation catalog: {exc}"
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
        return state
