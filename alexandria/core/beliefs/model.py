"""Belief data model.

A belief is one assertion the wiki currently makes, attached to provenance.
Per ``19_belief_revision.md``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Belief:
    """A single structured belief extracted from a wiki page."""

    belief_id: str = ""
    workspace: str = ""

    statement: str = ""
    topic: str = ""

    subject: str | None = None
    predicate: str | None = None
    object: str | None = None

    wiki_document_path: str = ""
    wiki_section_anchor: str | None = None
    footnote_ids: list[str] = field(default_factory=list)
    provenance_ids: list[str] = field(default_factory=list)

    asserted_at: str = ""
    asserted_in_run: str | None = None

    superseded_at: str | None = None
    superseded_by_belief_id: str | None = None
    superseded_in_run: str | None = None
    supersession_reason: str | None = None

    source_valid_from: str | None = None
    source_valid_to: str | None = None

    supporting_count: int = 1
    contradicting_belief_ids: list[str] = field(default_factory=list)
    confidence_hint: str | None = None

    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.belief_id:
            self.belief_id = f"b-{uuid.uuid4().hex[:16]}"
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()
        if not self.asserted_at:
            self.asserted_at = self.created_at

    @property
    def is_current(self) -> bool:
        return self.superseded_at is None

    def to_dict(self) -> dict:
        return {
            "belief_id": self.belief_id,
            "statement": self.statement,
            "topic": self.topic,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "wiki_document_path": self.wiki_document_path,
            "wiki_section_anchor": self.wiki_section_anchor,
            "footnote_ids": self.footnote_ids,
            "provenance_ids": self.provenance_ids,
            "asserted_at": self.asserted_at,
            "asserted_in_run": self.asserted_in_run,
            "superseded_at": self.superseded_at,
            "superseded_by_belief_id": self.superseded_by_belief_id,
            "superseded_in_run": self.superseded_in_run,
            "supersession_reason": self.supersession_reason,
            "source_valid_from": self.source_valid_from,
            "source_valid_to": self.source_valid_to,
            "supporting_count": self.supporting_count,
            "confidence_hint": self.confidence_hint,
        }

    @classmethod
    def from_dict(cls, data: dict, workspace: str = "") -> Belief:
        return cls(
            belief_id=data.get("belief_id", ""),
            workspace=workspace,
            statement=data.get("statement", ""),
            topic=data.get("topic", ""),
            subject=data.get("subject"),
            predicate=data.get("predicate"),
            object=data.get("object"),
            wiki_document_path=data.get("wiki_document_path", ""),
            wiki_section_anchor=data.get("wiki_section_anchor"),
            footnote_ids=data.get("footnote_ids", []),
            provenance_ids=data.get("provenance_ids", []),
            asserted_at=data.get("asserted_at", ""),
            asserted_in_run=data.get("asserted_in_run"),
            superseded_at=data.get("superseded_at"),
            superseded_by_belief_id=data.get("superseded_by_belief_id"),
            superseded_in_run=data.get("superseded_in_run"),
            supersession_reason=data.get("supersession_reason"),
            source_valid_from=data.get("source_valid_from"),
            source_valid_to=data.get("source_valid_to"),
            supporting_count=data.get("supporting_count", 1),
            confidence_hint=data.get("confidence_hint"),
            created_at=data.get("created_at", ""),
        )
