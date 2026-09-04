"""Retain one append-only authority for current versioned learning content."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.domain.learning_content import (
    ConceptMappingRevision,
    PrincipleRecord,
    TaxonomyRevision,
    validate_mapping_revision,
    validate_mapping_successor,
    validate_principle_successor,
    validate_taxonomy_successor,
)


Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]*$",
        strict=True,
    ),
]
Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^[a-f0-9]{64}$", strict=True),
]
NonNegativeInteger = Annotated[int, Field(ge=0, strict=True)]


class LearningContentCatalog(BaseModel):
    """Complete current lineage for one install-local concept series.

    The catalog keeps historical taxonomy, mapping, immutable principle, and
    principle-lifecycle evidence. Its final taxonomy and mapping revisions are
    current. Publication remains separate from mastery and drill mutation.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    catalog_id: Identifier
    catalog_revision: NonNegativeInteger
    predecessor_catalog_sha256: Sha256Digest | None = None
    taxonomy_lineage: tuple[TaxonomyRevision, ...] = ()
    mapping_lineage: tuple[ConceptMappingRevision, ...] = ()
    principles: tuple[PrincipleRecord, ...] = ()

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        if self.catalog_revision == 0:
            if self.predecessor_catalog_sha256 is not None:
                raise ValueError("an empty catalog cannot have a predecessor")
            if self.taxonomy_lineage or self.mapping_lineage or self.principles:
                raise ValueError("an empty catalog cannot contain learning content")
            return self
        if self.predecessor_catalog_sha256 is None:
            raise ValueError("a published catalog must bind its predecessor")
        if not self.taxonomy_lineage or not self.mapping_lineage:
            raise ValueError(
                "a published catalog requires taxonomy and mapping lineages"
            )
        if self.taxonomy_lineage[0].predecessor_taxonomy_revision is not None:
            raise ValueError("taxonomy lineage must begin at its root revision")
        if self.mapping_lineage[0].predecessor_mapping_revision is not None:
            raise ValueError("mapping lineage must begin at its root revision")

        for revision_index, candidate in enumerate(
            self.taxonomy_lineage[1:],
            start=1,
        ):
            validate_taxonomy_successor(
                self.taxonomy_lineage[:revision_index],
                candidate,
            )
        taxonomy_by_revision = {
            taxonomy.taxonomy_revision: taxonomy
            for taxonomy in self.taxonomy_lineage
        }
        if len(taxonomy_by_revision) != len(self.taxonomy_lineage):
            raise ValueError("taxonomy lineage revision identifiers must be unique")

        for mapping_index, mapping in enumerate(self.mapping_lineage):
            taxonomy = taxonomy_by_revision.get(mapping.taxonomy_revision)
            if taxonomy is None:
                raise ValueError("mapping lineage references an unknown taxonomy")
            validate_mapping_revision(taxonomy, mapping)
            if mapping_index:
                validate_mapping_successor(
                    self.mapping_lineage[:mapping_index],
                    mapping,
                )
        current_taxonomy = self.taxonomy_lineage[-1]
        current_mapping = self.mapping_lineage[-1]
        if (
            current_mapping.taxonomy_series_id,
            current_mapping.taxonomy_revision,
        ) != (
            current_taxonomy.series_id,
            current_taxonomy.taxonomy_revision,
        ):
            raise ValueError("current mapping must target the current taxonomy")

        principle_keys = tuple(
            (
                record.principle.taxonomy_series_id,
                record.principle.principle_id,
                record.principle.principle_revision,
            )
            for record in self.principles
        )
        if len(set(principle_keys)) != len(principle_keys):
            raise ValueError("principle revision identities must be unique")
        groups: dict[tuple[str, str], list[PrincipleRecord]] = {}
        for record in self.principles:
            principle = record.principle
            taxonomy = taxonomy_by_revision.get(principle.taxonomy_revision)
            if (
                taxonomy is None
                or taxonomy.series_id != principle.taxonomy_series_id
            ):
                raise ValueError("principle references an unknown taxonomy revision")
            concept = taxonomy.concept(principle.concept_id)
            if (
                concept is None
                or concept.definition_revision
                != principle.concept_definition_revision
            ):
                raise ValueError("principle references an unknown concept definition")
            groups.setdefault(
                (principle.taxonomy_series_id, principle.principle_id), []
            ).append(record)
        canonical_principles = tuple(
            record
            for key in sorted(groups)
            for record in groups[key]
        )
        if canonical_principles != self.principles:
            raise ValueError("principle lineages must use canonical key order")
        for records in groups.values():
            revisions = tuple(record.principle for record in records)
            if revisions[0].supersedes_principle_revision is not None:
                raise ValueError("principle lineage must begin at its root revision")
            for revision_index, revision in enumerate(revisions[1:], start=1):
                validate_principle_successor(
                    revisions[:revision_index],
                    revision,
                )
            if sum(record.current_status == "approved" for record in records) > 1:
                raise ValueError(
                    "a principle lineage cannot have multiple approved revisions"
                )
            if records[-1].current_status == "superseded":
                raise ValueError(
                    "a superseded principle revision requires its retained successor"
                )
        return self

    @classmethod
    def empty(cls, catalog_id: str) -> Self:
        return cls(catalog_id=catalog_id, catalog_revision=0)

    @property
    def current_taxonomy(self) -> TaxonomyRevision | None:
        return self.taxonomy_lineage[-1] if self.taxonomy_lineage else None

    @property
    def current_mapping(self) -> ConceptMappingRevision | None:
        return self.mapping_lineage[-1] if self.mapping_lineage else None

    def semantic_digest(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(payload).hexdigest()
