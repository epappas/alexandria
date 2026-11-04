"""Reads through SJ's own query interface, used to check what Alexandria published. sj_client
is imported inside each function so that collecting this package needs no sj-client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sj_client import StoreClient
    from sj_client.v3 import store_pb2 as v3

    from alexandria.core.sj_records import Scope


def scope(workspace: str = "global", tenant: str = "default") -> Scope:
    from alexandria.core.sj_records import Scope

    return Scope(tenant, "default", workspace)


def _query(tenant: str, **kind: Any) -> v3.QueryRequest:
    from sj_client import CONTRACT_VERSION
    from sj_client.v3 import store_pb2 as v3

    return v3.QueryRequest(
        contract_version=CONTRACT_VERSION,
        namespace=v3.Namespace(tenant=tenant, space="default"),
        snapshot=v3.SnapshotSelection(latest=v3.SnapshotSelection.Latest()),
        **kind,
    )


def version(client: StoreClient, tenant: str = "default") -> int:
    from sj_client import CONTRACT_VERSION
    from sj_client.v3 import store_pb2 as v3

    request = v3.StatusRequest(
        contract_version=CONTRACT_VERSION, namespace=v3.Namespace(tenant=tenant, space="default"),
    )
    return client.status(request).snapshot.version


def explain(client: StoreClient, claim: str) -> v3.QueryResponse:
    from sj_client.v3 import store_pb2 as v3

    return client.query(_query("default", explain=v3.ExplainRequest(claim_id=claim)))


def explained_claim(client: StoreClient, claim: str) -> v3.ClaimItem:
    items = [item.claim for item in explain(client, claim).items if item.HasField("claim")]
    assert [item.claim_id for item in items] == [claim]
    found: v3.ClaimItem = items[0]
    return found


def entity(client: StoreClient, entity_id: str) -> v3.QueryResponse:
    from sj_client.v3 import store_pb2 as v3

    return client.query(_query("default", entity=v3.GetEntityRequest(entity_id=entity_id)))


def entity_claims(client: StoreClient, entity_id: str) -> set[str]:
    return {item.claim.claim_id for item in entity(client, entity_id).items if item.HasField("claim")}


def links(client: StoreClient, page: str) -> list[v3.QueryItem]:
    from sj_client.v3 import store_pb2 as v3

    neighbors = v3.NeighborsRequest(
        entity_id=page, relation_type="COMPILED_FROM", direction=v3.DIRECTION_OUTGOING,
    )
    return list(client.query(_query("default", neighbors=neighbors)).items)


def resolve(client: StoreClient, label: str) -> list[str]:
    from sj_client.v3 import store_pb2 as v3

    request = v3.ResolveRequest(name=label, mode=v3.MATCH_MODE_EXACT, max_candidates=10)
    response = client.query(_query("default", resolve=request))
    return [item.candidate.label.entity_id for item in response.items]
