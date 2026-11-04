"""A raw file edited from version A to B and back to A, ingested in place each time, against a
real sjd. Local beliefs follow the current version: A's beliefs are current again, B's are
superseded, and SJ keeps every claim standing because extraction never retracts. On a store
whose receipts expire after two later writes, A's source and page operations are settled
from their expired receipts instead of being refused."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.sj import daemon, reads
from tests.sj.conftest import Connect, configure, sj_settings
from tests.sj.daemon import Executables
from tests.sj.helpers import CODE, current_beliefs, ingest, page_of, workspace, write
from tests.sj.pki import SERVER_NAME, Credentials

if TYPE_CHECKING:
    from sj_client import StoreClient

pytestmark = pytest.mark.sj

PAGE_REL = "wiki/concepts/tides.md"
REVISED = CODE + "\n\ndef ebb(day):\n    return day\n"
A_STATEMENTS = ["Module defines TideTable", "Module defines predict(day)"]


def _revert(home: Path, before_return: Callable[[], None]) -> tuple[set[str], set[str]]:
    """Ingests raw/local/tides.py at A, then B, then, after `before_return`, A again; returns
    A's and B's SJ claims."""
    raw = write(workspace(home) / "raw/local/tides.py", CODE)
    first = ingest(home, raw)
    write(raw, REVISED)
    second = ingest(home, raw)
    before_return()
    write(raw, CODE)
    third = ingest(home, raw)
    assert first.sj is not None and second.sj is not None and third.sj is not None
    assert third.committed and third.sj.replayed
    assert page_of(third) == page_of(first) == page_of(second) == PAGE_REL
    assert set(third.sj.claims.values()) == set(first.sj.claims.values())
    assert sorted(current_beliefs(home).values()) == A_STATEMENTS
    return set(first.sj.claims.values()), set(second.sj.claims.values())


def _all_standing(client: StoreClient, claims: set[str]) -> None:
    from alexandria.core import sj_records as records

    assert reads.version(client) == 4  # the third ingest wrote nothing
    assert reads.entity_claims(client, records.page_id(reads.scope(), PAGE_REL)) == claims
    for claim in claims:
        assert not reads.explained_claim(client, claim).HasField("retraction")


def test_ingesting_a_reverted_file_makes_its_beliefs_current_again(
    sj_home: Path, connect: Connect,
) -> None:
    a_claims, b_claims = _revert(sj_home, lambda: None)
    assert len(a_claims) == 2 and len(b_claims) == 3
    _all_standing(connect("alexandria"), a_claims | b_claims)


@dataclass(frozen=True)
class ShortReceipts:
    home: Path
    address: str


@pytest.fixture
def short_receipts(
    tmp_path: Path, executables: Executables, credentials: Credentials,
    initialized_home: Path, offline_cli: None,
) -> Iterator[ShortReceipts]:
    """A store whose receipts expire once two later namespace versions commit."""
    root = tmp_path / "sj-short" / "state"
    root.parent.mkdir(parents=True)
    daemon.init_store(executables.sjctl, root, "default", "default", receipt_window=1)
    running = daemon.secured(executables.sjd, root, credentials, dict(os.environ))
    configure(initialized_home, sj_settings(running.address, credentials))
    yield ShortReceipts(initialized_home, running.address)
    running.stop()


def test_a_reverted_file_is_ingested_again_after_its_receipts_expired(
    short_receipts: ShortReceipts, credentials: Credentials,
) -> None:
    from sj_client import CONTRACT_VERSION, MutualTls, Outcome, StoreClient
    from sj_client.v3 import store_pb2 as v3

    from alexandria.core import sj_records as records

    tls = MutualTls(
        ca=credentials.path("ca.pem"), certificate=credentials.path("alexandria.pem"),
        private_key=credentials.path("alexandria.key"), server_name=SERVER_NAME,
    )
    scope = reads.scope()
    token = records.source_token(scope, "raw/local/tides.py", records.sha256_hex(CODE.encode()))
    lookup = v3.WriteRequest(
        contract_version=CONTRACT_VERSION, namespace=scope.namespace, idempotency_token=token,
    )
    with StoreClient.mutual_tls(short_receipts.address, tls) as client:

        def a_source_receipt_has_expired() -> None:
            assert client.reconcile(lookup).outcome is Outcome.EXPIRED

        a_claims, b_claims = _revert(short_receipts.home, a_source_receipt_has_expired)
        _all_standing(client, a_claims | b_claims)
