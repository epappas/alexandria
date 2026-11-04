"""An ingest whose SJ write outlives its deadline: sjd built with test hooks holds the write at
a real storage barrier, Alexandria reports the outcome as uncertain and records nothing, and
retrying the same ingest after the write commits reconciles it without writing it again."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from alexandria.core.ingest import ingest_file
from alexandria.core.workspace import GLOBAL_SLUG, get_workspace
from alexandria.db.connection import connect as open_db
from alexandria.db.connection import db_path
from tests.sj import daemon, reads
from tests.sj.conftest import configure, sj_settings
from tests.sj.daemon import Daemon, Executables
from tests.sj.helpers import CODE
from tests.sj.pki import SERVER_NAME, Credentials

pytestmark = pytest.mark.sj

# The first manifest of the write is synced but HEAD does not name it: no reader sees it yet.
PAUSE_BARRIER = "manifest-written"
WRITE_DEADLINE_S = 5.0
# Only ends a hang; never decides a result.
HANG_GUARD_S = 180.0


@dataclass(frozen=True)
class Paused:
    daemon: Daemon
    ready: Path
    release: Path


@pytest.fixture
def paused(
    tmp_path: Path, store: Path, credentials: Credentials, executables: Executables,
) -> Iterator[Paused]:
    ready, release = tmp_path / "paused", tmp_path / "release"
    env = dict(os.environ)
    env.update(
        SJ_TEST_PAUSE=PAUSE_BARRIER, SJ_TEST_PAUSE_ARRIVAL="1",
        SJ_TEST_READY=str(ready), SJ_TEST_RELEASE=str(release),
    )
    running = daemon.secured(executables.hooked_sjd, store, credentials, env)
    yield Paused(running, ready, release)
    release.touch()
    running.stop()


def _wait(done: Callable[[], bool], what: str) -> None:
    give_up = time.monotonic() + HANG_GUARD_S
    while not done():
        if time.monotonic() >= give_up:
            raise AssertionError(f"{what} within {HANG_GUARD_S}s")
        time.sleep(0.1)


def test_an_interrupted_ingest_is_reconciled_on_retry_without_a_duplicate(
    initialized_home: Path, paused: Paused, credentials: Credentials, offline_cli: None,
    tmp_path: Path,
) -> None:
    from sj_client import CONTRACT_VERSION, MutualTls, Outcome, StoreClient
    from sj_client.v3 import store_pb2 as v3

    from alexandria.core import sj_records as records
    from alexandria.core.sj_store import SjUncertain

    home, address = initialized_home, paused.daemon.address
    workspace = get_workspace(home, GLOBAL_SLUG).path
    source = tmp_path / "tides.py"
    source.write_text(CODE, encoding="utf-8")
    configure(home, sj_settings(address, credentials, deadline_s=WRITE_DEADLINE_S))
    with pytest.raises(SjUncertain, match="not committed"):
        ingest_file(home, GLOBAL_SLUG, workspace, source, no_merge=True)
    with open_db(db_path(home)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM wiki_beliefs").fetchone()[0] == 0
    _wait(paused.ready.exists, "sjd did not pause the write")
    paused.release.touch()
    tls = MutualTls(
        ca=credentials.path("ca.pem"), certificate=credentials.path("alexandria.pem"),
        private_key=credentials.path("alexandria.key"), server_name=SERVER_NAME,
    )
    scope = reads.scope()
    data = (workspace / "raw/local/tides.py").read_bytes()
    # The held write is the ingest's first operation: the source version.
    token = records.source_token(scope, "raw/local/tides.py", records.sha256_hex(data))
    lookup = v3.WriteRequest(
        contract_version=CONTRACT_VERSION, namespace=scope.namespace, idempotency_token=token,
    )
    with StoreClient.mutual_tls(address, tls) as client:
        _wait(lambda: client.reconcile(lookup).outcome is Outcome.COMMITTED,
              "the released write did not commit")
        assert reads.version(client) == 1
        configure(home, sj_settings(address, credentials))
        retried = ingest_file(home, GLOBAL_SLUG, workspace, source, no_merge=True)
        assert retried.committed and retried.sj is not None
        # The source operation is reconciled, not written again; only the page is new.
        assert (retried.sj.replayed, retried.sj.snapshot) == (False, 2)
        assert reads.version(client) == 2
        with open_db(db_path(home)) as conn:
            beliefs = [row[0] for row in conn.execute("SELECT belief_id FROM wiki_beliefs")]
        assert len(beliefs) == 2
        page = records.page_id(scope, f"wiki/{retried.committed_paths[0]}")
        assert reads.entity_claims(client, page) == {records.claim_id(scope, b) for b in beliefs}
