"""The one SJ write path of Alexandria.

With an ``[sj]`` section in ``config.toml``, every knowledge write (ingest, the jobs worker,
MCP ``belief_add`` and ``belief_supersede``, ``reindex --rebuild-beliefs``, ``paste``,
``query --save`` and conversation capture) publishes its records here before Alexandria
updates its local index. A refused, failed or
uncertain write raises ``SjWriteError`` and the operation stops; there is no SQLite-only
fallback. Without ``[sj]`` every ``publish_*`` function returns None and nothing changes.

Each operation has an idempotency token derived from its Alexandria identity. The token's
Receipt is asked first: a committed operation is not written again, and a write whose deadline
passes is reconciled through Receipt, never assumed committed.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from alexandria.config import SjConfig, load_config
from alexandria.core.beliefs.model import Belief
from alexandria.core.ingest import IngestError

if TYPE_CHECKING:
    from sj_client import Reconciliation, StoreClient
    from sj_client.v3 import store_pb2 as v3

    from alexandria.core.sj_records import ClaimPlan, Scope, Unsupported

log = logging.getLogger(__name__)

# The schema an SJ namespace for Alexandria is created with: sjctl init --schema <this file>.
SCHEMA_PATH: Final = Path(__file__).with_name("sj_schema.json")

Build = Callable[["StoreClient"], list["v3.WriteItem"]]

# Reported for every published Source.
DOCUMENT_NOTE: Final = (
    "document",
    "SJ has no relation from a Source to its Document entity; the Source id derives from the "
    "path and SHA-256",
)

# sj-client is not on PyPI and is installed separately; the README's SJ section says the same.
SJ_CLIENT_REQUIREMENT: Final = (
    "sj-client @ git+ssh://git@github.com/epappas/graph-db-engine.git"
    "@74594441783519b4f23f315bd50cba91d51cdc8f#subdirectory=sdk/python"
)


class SjWriteError(IngestError):
    """SJ refused or failed the write; the operation did not update the local index."""


class SjClientMissing(SjWriteError):
    """[sj] is configured but the sj-client package cannot be imported; nothing was sent."""


class SjUnavailable(SjWriteError):
    """No connection to SJ could be made; nothing was sent."""


class SjUncertain(SjWriteError):
    """SJ has not reported a final outcome; retrying the same operation reconciles it."""


@dataclass(frozen=True)
class Publication:
    """What one operation published: its token, the committed snapshot (None when there was
    nothing to write), whether an earlier attempt had committed it, the SJ claim of each cited
    belief, and every value SJ did not carry."""

    token: str
    snapshot: int | None
    replayed: bool
    claims: dict[str, str] = field(default_factory=dict)
    unsupported: list[Unsupported] = field(default_factory=list)

    def lines(self) -> list[str]:
        """A short human report: the outcome, then the unsupported fields with counts."""
        if self.snapshot is None:
            head = f"SJ: nothing published (operation {self.token})"
        else:
            how = "already committed" if self.replayed else "committed"
            head = f"SJ: {how} {len(self.claims)} claim(s) at snapshot {self.snapshot}"
        counts = Counter(item.field for item in self.unsupported)
        if not counts:
            return [head]
        listed = ", ".join(f"{name} x{count}" for name, count in sorted(counts.items()))
        return [head, f"SJ did not carry: {listed}"]


@dataclass(frozen=True)
class SourceFacts:
    """What Alexandria knows about an ingested source that SJ has no field for."""

    kind: str
    ai_authored: bool
    extracted_by_llm: bool
    original_pdf: bool

    def notes(self, page_rel: str | None) -> list[tuple[str, str]]:
        """(field, detail) pairs for the unsupported report; `page_rel` is the page compiled
        from the source, if any."""
        found = [("source_kind", f"not carried ({self.kind!r})"), DOCUMENT_NOTE]
        if self.ai_authored:
            found.append(("ai_authored", "not carried (True)"))
        if self.kind == "conversation":
            found.append(("speaker", "speaker attribution inside the transcript is not carried"))
        if self.original_pdf:
            found.append(("original_artifact", "the PDF bytes are not published; the extracted "
                          "text is the cited source"))
        if self.extracted_by_llm:
            found.append(("model/provider", "the extracting model and provider are not carried"))
        if page_rel:
            found.append(page_note(page_rel))
        return found


def page_note(page_rel: str) -> tuple[str, str]:
    return ("page_content", f"the compiled text of {page_rel} is not carried; SJ holds its "
            "identity, its COMPILED_FROM links and its cited claims")


def sj_config(home: Path) -> SjConfig | None:
    """The [sj] settings, with relative TLS paths resolved against the Alexandria home."""
    config = load_config(home).sj
    if config is None:
        return None
    paths = {name: str(home / getattr(config, name)) for name in ("ca", "certificate", "private_key")}
    return config.model_copy(update=paths)


def _configured(home: Path) -> SjConfig | None:
    """The [sj] settings, or None; with [sj] but no importable sj-client, one clear error
    saying how to install it, before anything else is done."""
    config = sj_config(home)
    if config is None:
        return None
    try:
        import sj_client  # noqa: F401
    except ImportError as error:
        raise SjClientMissing(
            "SJ is configured (the sj section of config.toml) but the sj-client package is not "
            f'installed. Install it into this environment: pip install "{SJ_CLIENT_REQUIREMENT}"'
        ) from error
    return config


def publish_ingest(
    home: Path,
    workspace: str,
    workspace_path: Path,
    raw_file: Path,
    page_rel: str,
    page_file: Path,
    beliefs: list[Belief],
    facts: SourceFacts,
) -> Publication | None:
    """Publishes one ingested source revision: its Source and bytes, its Document and Page
    entities, the COMPILED_FROM link and the beliefs that quote this source on the page
    (`page_file` is the staged copy of `page_rel`). Assigns each belief its SJ-derived id."""
    config = _configured(home)
    if config is None:
        return None
    from alexandria.core import sj_records as records

    scope = records.Scope(config.tenant, config.space, workspace)
    raw_rel = records.relative(workspace_path, raw_file)
    data = raw_file.read_bytes()
    token = scope.record_id("operation", "ingest", raw_rel, records.sha256_hex(data))
    records.assign_belief_ids(token, beliefs)
    page_text = page_file.read_text(encoding="utf-8") if page_file.is_file() else ""
    plan = records.plan_claims(scope, workspace_path, page_text, beliefs, only_source=raw_file)
    source = f"source {raw_rel}"
    notes = facts.notes(page_rel)
    plan.unsupported[:0] = [records.Unsupported(source, name, text) for name, text in notes]
    page, document = records.page_id(scope, page_rel), records.document_id(scope, raw_rel)
    link = records.link_id(scope, page_rel, raw_rel)

    def build(client: StoreClient) -> list[v3.WriteItem]:
        items = records.source_items(scope, records.source_id(scope, raw_rel, data), data)
        items += _absent_entity(client, scope, document, records.DOCUMENT, raw_rel)
        page_items = _absent_entity(client, scope, page, records.PAGE, page_rel)
        if page_items or not _link_exists(client, scope, page, link):
            page_items.append(records.link_item(link, page, document))
        return items + page_items + plan.items(scope, page)

    return _publish(config, scope, token, build, plan)


def publish_beliefs(
    home: Path,
    workspace: str,
    workspace_path: Path,
    operation: tuple[str, ...],
    page_rel: str,
    beliefs: list[Belief],
    *,
    derive_ids: bool = True,
) -> Publication | None:
    """Publishes the cited beliefs of one wiki page as claims of its Page entity, skipping
    claims SJ already holds. `operation` names the Alexandria operation and fixes its token.
    With `derive_ids`, each belief gets its SJ-derived id; otherwise its stored id is kept."""
    config = _configured(home)
    if config is None:
        return None
    from alexandria.core import sj_records as records

    scope = records.Scope(config.tenant, config.space, workspace)
    token = scope.record_id("operation", *operation)
    if derive_ids:
        records.assign_belief_ids(token, beliefs)
    plan = records.plan_claims(scope, workspace_path, _page_text(workspace_path, page_rel), beliefs)
    if not plan.cited:
        return _reported(Publication(token, None, False, {}, plan.unsupported))
    page = records.page_id(scope, page_rel)

    def build(client: StoreClient) -> list[v3.WriteItem]:
        held = _held_claims(client, scope, plan.claims(scope).values())
        items = _absent_entity(client, scope, page, records.PAGE, page_rel)
        return items + plan.items(scope, page, held)

    return _publish(config, scope, token, build, plan)


def publish_supersede(home: Path, old: Belief, new: Belief, reason: str) -> Publication | None:
    """Publishes an explicit correction in the old belief's workspace: the new belief's claim,
    and a Retraction of the old belief's claim naming it as the replacement. Assigns the new
    belief its id."""
    config = _configured(home)
    if config is None:
        return None
    from alexandria.core import sj_records as records
    from alexandria.core.workspace import get_workspace

    workspace_path = get_workspace(home, old.workspace).path
    scope = records.Scope(config.tenant, config.space, old.workspace)
    token = scope.record_id("operation", "belief_supersede", old.belief_id, new.statement, reason)
    records.assign_belief_ids(token, [new])
    page_rel = new.wiki_document_path
    plan = records.plan_claims(scope, workspace_path, _page_text(workspace_path, page_rel), [new])
    if not plan.cited:
        plan.unsupported.append(records.Unsupported(
            f"belief {old.belief_id}", "retraction",
            "not published: the replacement has no verbatim quote to justify it",
        ))
        return _reported(Publication(token, None, False, {}, plan.unsupported))
    page = records.page_id(scope, page_rel)
    evidence = [records.evidence_id(scope, new.belief_id, n) for n in range(len(plan.cited[0][1]))]

    def build(client: StoreClient) -> list[v3.WriteItem]:
        items = _absent_entity(client, scope, page, records.PAGE, page_rel)
        items += plan.items(scope, page)
        items.append(records.retraction_item(scope, old.belief_id, new.belief_id, reason, evidence))
        return items

    return _publish(config, scope, token, build, plan)


def publish_source(
    home: Path, workspace: str, workspace_path: Path, raw_file: Path,
    facts: SourceFacts | None = None,
) -> Publication | None:
    """Publishes one captured raw source (paste, conversation capture): its Source and bytes
    and its Document entity. `facts` adds what SJ does not carry about the source."""
    config = _configured(home)
    if config is None:
        return None
    from alexandria.core import sj_records as records

    scope = records.Scope(config.tenant, config.space, workspace)
    raw_rel = records.relative(workspace_path, raw_file)
    data = raw_file.read_bytes()
    token = scope.record_id("operation", "source", raw_rel, records.sha256_hex(data))
    document = records.document_id(scope, raw_rel)

    def build(client: StoreClient) -> list[v3.WriteItem]:
        items = records.source_items(scope, records.source_id(scope, raw_rel, data), data)
        return items + _absent_entity(client, scope, document, records.DOCUMENT, raw_rel)

    notes = facts.notes(None) if facts else [DOCUMENT_NOTE]
    plan = records.ClaimPlan(
        unsupported=[records.Unsupported(f"source {raw_rel}", name, text) for name, text in notes],
    )
    return _publish(config, scope, token, build, plan)


def publish_page(
    home: Path, workspace: str, workspace_path: Path, page_rel: str, page_file: Path,
    cited: list[str],
) -> Publication | None:
    """Publishes a page Alexandria generated without quoted evidence (a saved query answer):
    its Page entity and a COMPILED_FROM link to each cited raw source SJ holds. Its text and
    every other citation are reported. `page_file` is the staged copy of `page_rel`."""
    config = _configured(home)
    if config is None:
        return None
    from alexandria.core import sj_records as records

    scope = records.Scope(config.tenant, config.space, workspace)
    token = scope.record_id(
        "operation", "page", page_rel, records.sha256_hex(page_file.read_bytes()),
    )
    page, record = records.page_id(scope, page_rel), f"page {page_rel}"
    raw = sorted({source for source in cited if source.startswith("raw/")})
    plan = records.ClaimPlan(unsupported=[
        records.Unsupported(record, *page_note(page_rel)),
        records.Unsupported(record, "model/provider", "the answering model and provider are not carried"),
        *(records.Unsupported(record, "citation", f"cites {source!r}; only raw sources are linked")
          for source in sorted(set(cited) - set(raw))),
    ])

    def build(client: StoreClient) -> list[v3.WriteItem]:
        created = _absent_entity(client, scope, page, records.PAGE, page_rel)
        links = [_cited_link(client, scope, page_rel, source, bool(created), plan) for source in raw]
        return created + [link for link in links if link is not None]

    return _publish(config, scope, token, build, plan)


def _cited_link(
    client: StoreClient, scope: Scope, page_rel: str, source: str, new_page: bool,
    plan: ClaimPlan,
) -> v3.WriteItem | None:
    """The COMPILED_FROM link from the page to the Document of raw `source`, when SJ holds
    that Document and not yet the link. A Document SJ does not hold is reported."""
    from alexandria.core import sj_records as records

    document = records.document_id(scope, source)
    if _absent_entity(client, scope, document, records.DOCUMENT, source):
        plan.unsupported.append(records.Unsupported(
            f"page {page_rel}", "citation", f"cites {source}, which SJ does not hold; not linked",
        ))
        return None
    page, link = records.page_id(scope, page_rel), records.link_id(scope, page_rel, source)
    if not new_page and _link_exists(client, scope, page, link):
        return None
    return records.link_item(link, page, document)


def _publish(config: SjConfig, scope: Scope, token: str, build: Build, plan: ClaimPlan) -> Publication:
    """Asks Receipt first; writes only an operation SJ has never admitted."""
    from sj_client import CONTRACT_VERSION, Outcome
    from sj_client.v3 import store_pb2 as v3

    claims = plan.claims(scope)
    request = v3.WriteRequest(
        contract_version=CONTRACT_VERSION, namespace=scope.namespace, idempotency_token=token,
    )
    with _open(config) as client:
        prior = client.reconcile(request)
        if prior.outcome is not Outcome.UNKNOWN:
            snapshot = _settled(client, scope, token, prior, list(claims.values()))
            return _reported(Publication(token, snapshot, True, claims, plan.unsupported))
        items = build(client)
        if not items:
            return _reported(Publication(token, None, False, claims, plan.unsupported))
        request.items.extend([v3.WriteItem(tenant=scope.tenant), *items])
        receipt = _commit(client, request, config.deadline_s)
    return _reported(Publication(token, receipt.snapshot.version, False, claims, plan.unsupported))


def _settled(
    client: StoreClient, scope: Scope, token: str, prior: Reconciliation, claims: list[str],
) -> int:
    """The snapshot of an operation an earlier attempt decided, once its claims are checked.
    An expired receipt counts as committed only when every claim it should hold is in SJ."""
    from sj_client import Outcome

    if prior.outcome is Outcome.COMMITTED:
        _require_claims(client, scope, token, claims)
        return prior.response.committed.snapshot.version
    if prior.outcome is Outcome.EXPIRED and claims:
        _require_claims(client, scope, token, claims)
        return prior.response.expired.decided_version
    raise _unsettled(token, prior)


def _commit(client: StoreClient, request: v3.WriteRequest, deadline: float) -> v3.Receipt:
    from sj_client import Outcome, Reconciliation, StoreError

    try:
        outcome = client.write_reconciled(request, timeout=deadline)
    except StoreError as error:
        if error.error is not None:
            raise
        raise SjUncertain(
            f"the write of operation {request.idempotency_token} failed in transport ({error}); "
            "nothing was recorded locally. Retry the same operation to reconcile it."
        ) from None
    if not isinstance(outcome, Reconciliation):
        return outcome.receipt
    if outcome.outcome is Outcome.COMMITTED:
        return outcome.response.committed
    raise _unsettled(request.idempotency_token, outcome)


def _reported(publication: Publication) -> Publication:
    for line in publication.lines()[1:]:
        log.warning("%s (operation %s)", line, publication.token)
    return publication


def _unsettled(token: str, reconciliation: Reconciliation) -> SjWriteError:
    from sj_client import Outcome
    from sj_client.v3 import store_pb2 as v3

    outcome = reconciliation.outcome
    if outcome is Outcome.REJECTED:
        code = v3.ErrorCode.Name(reconciliation.response.rejected.code)
        return SjWriteError(f"SJ rejected operation {token} ({code}); it is refused again")
    if outcome is Outcome.EXPIRED:
        return SjWriteError(
            f"SJ decided operation {token} long ago and its receipt has expired; with no claim "
            "to check, its outcome cannot be confirmed"
        )
    return SjUncertain(
        f"SJ reports operation {token} as {outcome.value}, not committed; nothing was recorded "
        "locally. Retry the same operation to reconcile it."
    )


def _require_claims(client: StoreClient, scope: Scope, token: str, claims: list[str]) -> None:
    """An earlier attempt decided this operation; its claims must be the ones this attempt
    would publish, or the local index would describe records SJ does not hold."""
    held = _held_claims(client, scope, claims)
    missing = [claim for claim in claims if claim not in held]
    if missing:
        raise SjWriteError(
            f"operation {token} was committed earlier with other content (claim {missing[0]} "
            "is not in SJ); nothing was recorded locally"
        )


def _held_claims(client: StoreClient, scope: Scope, claims: Iterable[str]) -> frozenset[str]:
    """The claims of `claims` that SJ holds."""
    from sj_client import StoreError
    from sj_client.v3 import store_pb2 as v3

    held: set[str] = set()
    for claim in claims:
        try:
            client.query(_query(scope, explain=v3.ExplainRequest(claim_id=claim)))
        except StoreError as error:
            if error.code != v3.ERROR_CODE_UNKNOWN_CLAIM:
                raise
            continue
        held.add(claim)
    return frozenset(held)


def _absent_entity(
    client: StoreClient, scope: Scope, entity: str, kind: str, label: str,
) -> list[v3.WriteItem]:
    """The items creating `entity` with its canonical label, or none when SJ holds it."""
    from sj_client import StoreError
    from sj_client.v3 import store_pb2 as v3

    from alexandria.core.sj_records import entity_items

    try:
        client.query(_query(scope, entity=v3.GetEntityRequest(entity_id=entity)))
    except StoreError as error:
        if error.code != v3.ERROR_CODE_UNKNOWN_ENTITY:
            raise
        return entity_items(scope, entity, kind, label)
    return []


def _link_exists(client: StoreClient, scope: Scope, page: str, link: str) -> bool:
    from sj_client.v3 import store_pb2 as v3

    from alexandria.core.sj_records import COMPILED_FROM

    neighbors = v3.NeighborsRequest(
        entity_id=page, relation_type=COMPILED_FROM, direction=v3.DIRECTION_OUTGOING,
    )
    response = client.query(_query(scope, neighbors=neighbors))
    return any(item.link.id == link for item in response.items)


def _query(scope: Scope, **kind: Any) -> v3.QueryRequest:
    from sj_client import CONTRACT_VERSION
    from sj_client.v3 import store_pb2 as v3

    latest = v3.SnapshotSelection(latest=v3.SnapshotSelection.Latest())
    return v3.QueryRequest(
        contract_version=CONTRACT_VERSION, namespace=scope.namespace, snapshot=latest, **kind,
    )


@contextmanager
def _open(config: SjConfig) -> Iterator[StoreClient]:
    """A mutual-TLS client; every client failure inside becomes an SjWriteError."""
    from sj_client import (
        ConfigurationError,
        ConnectError,
        MutualTls,
        SjClientError,
        StoreClient,
        StoreError,
    )

    tls = MutualTls(
        ca=Path(config.ca), certificate=Path(config.certificate),
        private_key=Path(config.private_key), server_name=config.server_name or None,
    )
    try:
        client = StoreClient.mutual_tls(config.address, tls, timeout=config.deadline_s)
    except ConfigurationError as error:
        raise SjWriteError(f"SJ TLS settings are invalid: {error}") from None
    except ConnectError as error:
        raise SjUnavailable(f"SJ is unavailable: {error}") from None
    with client:
        try:
            yield client
        except StoreError as error:
            if error.error is None:
                raise SjUncertain(f"SJ failed without a typed answer: {error}") from None
            raise SjWriteError(f"SJ refused the operation: {error}") from None
        except SjClientError as error:
            raise SjWriteError(f"SJ answered outside its contract: {error}") from None


def _page_text(workspace_path: Path, page_rel: str) -> str:
    """The wiki page whose footnotes a belief cites; empty when it is not inside the workspace."""
    if not page_rel:
        return ""
    page = (workspace_path / page_rel).resolve()
    if not page.is_relative_to(workspace_path.resolve()) or not page.is_file():
        return ""
    return page.read_text(encoding="utf-8")
