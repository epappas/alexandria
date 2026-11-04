"""Alexandria records as SJ write items.

Every SJ identity is a UUIDv5 of the SJ tenant and space, the Alexandria workspace and the
Alexandria identity of the record, so a retried operation names the same records. A belief
becomes a claim only with evidence: an exact quote of the raw source bytes its footnote cites.
A record without such a quote is never given a citation. What SJ cannot carry is returned as
``Unsupported`` entries, never dropped silently.

Mapping (schema in ``sj_schema.json``):

- raw source revision  -> Source with its exact bytes, id from (path, SHA-256)
- raw source path      -> Document entity, canonical label = workspace-relative path
- wiki page            -> Page entity, canonical label = workspace-relative path
- page compiled from   -> COMPILED_FROM link Page -> Document (structural, no citation)
- belief with quotes   -> claim Page --states--> statement, one ExactQuote evidence per quote,
                          observed at the belief's asserted_at, valid time unknown
- belief_supersede     -> Retraction of the old claim, replacement = the new claim
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final

from sj_client.v3 import store_pb2 as v3

from alexandria.core.beliefs.model import Belief
from alexandria.core.citations import Footnote, extract_footnotes
from alexandria.core.citations.anchors import resolve_source_path

ID_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/epappas/alexandria#sj")
PAGE: Final = "Page"
DOCUMENT: Final = "Document"
COMPILED_FROM: Final = "COMPILED_FROM"
STATES: Final = ("states", 1)

# Belief fields SJ has no place for; reported whenever they hold a value.
_NOT_CARRIED: Final = (
    "subject", "predicate", "object", "topic", "wiki_section_anchor", "asserted_in_run",
    "source_valid_from", "source_valid_to", "confidence_hint", "contradicting_belief_ids",
    "provenance_ids",
)


@dataclass(frozen=True)
class Scope:
    """The SJ namespace and the Alexandria workspace every identity is derived in."""

    tenant: str
    space: str
    workspace: str

    @property
    def namespace(self) -> v3.Namespace:
        return v3.Namespace(tenant=self.tenant, space=self.space)

    def record_id(self, kind: str, *parts: str) -> str:
        name = json.dumps([self.tenant, self.space, self.workspace, kind, *parts])
        return str(uuid.uuid5(ID_NAMESPACE, name))


@dataclass(frozen=True)
class Unsupported:
    """One value SJ did not receive, and why."""

    record: str
    field: str
    detail: str

    def __str__(self) -> str:
        return f"{self.record}: {self.field}: {self.detail}"


@dataclass(frozen=True)
class Quote:
    """Exact bytes of one source version (`source_rel` at SHA-256 `source_sha`); `ambiguous`
    when they occur more than once there, in which case the first occurrence is cited, as
    Alexandria's verifier anchors it."""

    source_id: str
    source_rel: str
    source_sha: str
    text: bytes
    ambiguous: bool


@dataclass(frozen=True)
class Page:
    """A page's footnotes by id, and the ids defined more than once (merged or hedged pages),
    which cannot say which definition a reference means."""

    footnotes: dict[str, Footnote]
    repeated: frozenset[str]

    @classmethod
    def of(cls, text: str) -> Page:
        notes = extract_footnotes(text)
        counts = Counter(note.footnote_id for note in notes)
        repeated = frozenset(number for number, count in counts.items() if count > 1)
        return cls({note.footnote_id: note for note in notes}, repeated)


@dataclass
class ClaimPlan:
    """The beliefs that become claims, with their quotes, and what could not be carried."""

    cited: list[tuple[Belief, list[Quote]]] = field(default_factory=list)
    unsupported: list[Unsupported] = field(default_factory=list)

    def claims(self, scope: Scope) -> dict[str, str]:
        """Alexandria belief id -> SJ claim id."""
        return {belief.belief_id: claim_id(scope, belief.belief_id) for belief, _ in self.cited}

    def drop_sources(self, absent: set[tuple[str, str]]) -> None:
        """Removes quotes of source versions (path, SHA-256) SJ does not hold. A belief left
        without quotes is reported and stays uncited; no other version's bytes are used."""
        cited: list[tuple[Belief, list[Quote]]] = []
        for belief, quotes in self.cited:
            kept = [q for q in quotes if (q.source_rel, q.source_sha) not in absent]
            record = f"belief {belief.belief_id}"
            for quote in quotes:
                if (quote.source_rel, quote.source_sha) in absent:
                    self.unsupported.append(Unsupported(record, "evidence", (
                        f"cites {quote.source_rel} at a version SJ does not hold "
                        f"(SHA-256 {quote.source_sha[:12]}); import it first"
                    )))
            if kept:
                cited.append((belief, kept))
                continue
            self.unsupported.append(Unsupported(
                record, "claim", "no quote of a source SJ holds: kept as an uncited local belief",
            ))
        self.cited = cited

    def items(
        self, scope: Scope, page: str, held: frozenset[str] = frozenset(),
    ) -> list[v3.WriteItem]:
        """Evidence and claim items of every cited belief whose claim SJ does not hold."""
        items: list[v3.WriteItem] = []
        for belief, quotes in self.cited:
            if claim_id(scope, belief.belief_id) not in held:
                items.extend(claim_items(scope, belief, page, quotes))
        return items


def relative(workspace_path: Path, path: Path) -> str:
    """The workspace-relative POSIX path that names a raw source or wiki page."""
    return path.resolve().relative_to(workspace_path.resolve()).as_posix()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_id(scope: Scope, raw_rel: str, data: bytes) -> str:
    return scope.record_id("source", raw_rel, sha256_hex(data))


def source_token(scope: Scope, raw_rel: str, sha_hex: str) -> str:
    """The token of the one operation that publishes this source version. Its committed
    Receipt is how Alexandria knows SJ holds the version."""
    return scope.record_id("operation", "source", raw_rel, sha_hex)


def document_id(scope: Scope, raw_rel: str) -> str:
    return scope.record_id("document", raw_rel)


def page_id(scope: Scope, page_rel: str) -> str:
    return scope.record_id("page", page_rel)


def link_id(scope: Scope, page_rel: str, raw_rel: str) -> str:
    return scope.record_id("compiled-from", page_rel, raw_rel)


def claim_id(scope: Scope, belief_id: str) -> str:
    return scope.record_id("claim", belief_id)


def evidence_id(scope: Scope, belief_id: str, index: int) -> str:
    return scope.record_id("evidence", belief_id, str(index))


def retraction_id(scope: Scope, belief_id: str) -> str:
    return scope.record_id("retraction", belief_id)


def derive_belief_id(token: str, belief: Belief) -> str:
    """The belief id under SJ: fixed by the operation and the belief's content, so a retry of
    the operation gives the same belief, and so the same claim, again."""
    parts = [
        token, belief.wiki_document_path, belief.statement, belief.topic,
        belief.subject, belief.predicate, belief.object, sorted(set(belief.footnote_ids)),
    ]
    return "b-" + sha256_hex(json.dumps(parts).encode("utf-8"))[:16]


def assign_belief_ids(token: str, beliefs: list[Belief]) -> None:
    """Gives every belief its SJ-derived id; the local index stores the same id."""
    for belief in beliefs:
        belief.belief_id = derive_belief_id(token, belief)


def plan_claims(
    scope: Scope,
    workspace_path: Path,
    page_text: str,
    beliefs: list[Belief],
    only_source: Path | None = None,
) -> ClaimPlan:
    """Splits beliefs into cited claims and reported, uncited beliefs. With `only_source`,
    evidence must quote that file: an ingest cites only the source it ingests."""
    page = Page.of(page_text)
    plan = ClaimPlan()
    seen: set[str] = set()
    for belief in beliefs:
        if belief.belief_id in seen:
            continue
        seen.add(belief.belief_id)
        plan.unsupported.extend(belief_fields(belief))
        quotes = _cited_quotes(scope, workspace_path, page, belief, only_source, plan.unsupported)
        if quotes:
            plan.cited.append((belief, quotes))
            continue
        plan.unsupported.append(Unsupported(
            f"belief {belief.belief_id}", "claim",
            "no verbatim quote: kept as an uncited local belief, not published as a claim",
        ))
    return plan


def belief_fields(belief: Belief) -> list[Unsupported]:
    record = f"belief {belief.belief_id}"
    found = [
        Unsupported(record, name, f"not carried ({value!r})")
        for name in _NOT_CARRIED
        if (value := getattr(belief, name))
    ]
    if belief.supporting_count != 1:
        found.append(Unsupported(record, "supporting_count", f"not carried ({belief.supporting_count})"))
    if observed_at(belief) is None:
        found.append(Unsupported(
            record, "asserted_at", f"unreadable ({belief.asserted_at!r}); observed at publication",
        ))
    return found


def observed_at(belief: Belief) -> int | None:
    """The belief's asserted_at in whole seconds, or None when it is not an ISO timestamp."""
    try:
        return int(datetime.fromisoformat(belief.asserted_at).timestamp())
    except ValueError:
        return None


def _cited_quotes(
    scope: Scope,
    workspace_path: Path,
    page: Page,
    belief: Belief,
    only_source: Path | None,
    problems: list[Unsupported],
) -> list[Quote]:
    record = f"belief {belief.belief_id}"
    quotes: list[Quote] = []
    for number in sorted(set(belief.footnote_ids)):
        found = _footnote_evidence(scope, workspace_path, page, number, only_source)
        if isinstance(found, str):
            problems.append(Unsupported(record, "evidence", f"footnote [^{number}] {found}"))
            continue
        quotes.append(found)
    return quotes


def _footnote_evidence(
    scope: Scope, workspace_path: Path, page: Page, number: str, only_source: Path | None,
) -> Quote | str:
    """The quote footnote `number` binds to exact source bytes, or why it cannot be evidence.
    A quote the cited bytes do not hold is never sent."""
    note = page.footnotes.get(number)
    if note is None or note.quote is None or not note.quote.strip():
        return "has no verbatim quote on the page"
    if number in page.repeated:
        return "is defined more than once on the page, so its source is ambiguous"
    path = resolve_source_path(workspace_path, note.source_file)
    if path is None:
        return f"cites {note.source_file}, which is missing"
    if only_source is not None and path != only_source.resolve():
        return f"cites {note.source_file}, not the source this ingest publishes"
    data, text = path.read_bytes(), note.quote.strip().encode("utf-8")
    first = data.find(text)
    if first < 0:
        return f"quotes text that {note.source_file} does not hold"
    rel = relative(workspace_path, path)
    ambiguous = data.find(text, first + 1) >= 0
    return Quote(source_id(scope, rel, data), rel, sha256_hex(data), text, ambiguous)


def source_items(scope: Scope, source: str, data: bytes) -> list[v3.WriteItem]:
    digest = hashlib.sha256(data).digest()
    return [
        v3.WriteItem(source=v3.Source(id=source, tenant=scope.tenant, sha256=digest)),
        v3.WriteItem(content=v3.SourceContent(source_id=source, content=data)),
    ]


def entity_items(scope: Scope, entity: str, kind: str, label: str) -> list[v3.WriteItem]:
    canonical = v3.Candidate(
        entity_id=entity, tenant=scope.tenant, kind=v3.LABEL_KIND_CANONICAL, label=label,
    )
    return [
        v3.WriteItem(create_entity=v3.CreateEntity(id=entity, type=kind)),
        v3.WriteItem(label=canonical),
    ]


def link_item(link: str, page: str, document: str) -> v3.WriteItem:
    return v3.WriteItem(
        link=v3.Link(id=link, type=COMPILED_FROM, source_id=page, target_id=document),
    )


def claim_items(scope: Scope, belief: Belief, page: str, quotes: list[Quote]) -> list[v3.WriteItem]:
    """Evidence for each quote, then the claim Page --states--> statement citing them."""
    evidence = [evidence_id(scope, belief.belief_id, n) for n in range(len(quotes))]
    items = [
        v3.WriteItem(evidence=_evidence(scope, record, quote))
        for record, quote in zip(evidence, quotes, strict=True)
    ]
    seconds = observed_at(belief)
    claim = v3.Claim(
        id=claim_id(scope, belief.belief_id),
        tenant=scope.tenant,
        subject_id=page,
        predicate=v3.PredicateRef(id=STATES[0], version=STATES[1]),
        object=v3.ClaimObject(literal=v3.Literal(string=belief.statement)),
        evidence_ids=evidence,
        valid_time=v3.ValidTime(unknown=v3.ValidTime.Unknown()),
        observed_at=v3.Timestamp(unix_seconds=_now() if seconds is None else seconds),
    )
    items.append(v3.WriteItem(claim=claim))
    return items


def retraction_item(
    scope: Scope, old_belief: str, new_belief: str, reason: str, evidence: list[str],
) -> v3.WriteItem:
    """Withdraws the old belief's claim, offering the new one; justified by its evidence."""
    return v3.WriteItem(retract=v3.Retraction(
        id=retraction_id(scope, old_belief),
        tenant=scope.tenant,
        claim_id=claim_id(scope, old_belief),
        replacement_claim_id=claim_id(scope, new_belief),
        evidence_ids=evidence,
        reason=reason,
        observed_at=v3.Timestamp(unix_seconds=_now()),
    ))


def _evidence(scope: Scope, record: str, quote: Quote) -> v3.WriteEvidence:
    located = v3.ExactQuote(content=quote.text)
    if quote.ambiguous:
        located.occurrence = 1
    return v3.WriteEvidence(
        id=record,
        tenant=scope.tenant,
        source_id=quote.source_id,
        quote=located,
        sha256=hashlib.sha256(quote.text).digest(),
    )


def _now() -> int:
    return int(datetime.now().timestamp())
