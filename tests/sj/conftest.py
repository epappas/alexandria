"""Fixtures of the SJ-marked tests: real sjctl-created stores, a secured sjd per test with
certificates generated per test, and an Alexandria home configured to publish into it.

Every test in this package is marked ``sj``. They run in the local gate against real SJ
builds named by SJ_TEST_SJCTL, SJ_TEST_SJD and SJ_TEST_HOOKS_SJD, with the ``sj`` extra
installed. Public CI deselects them explicitly with ``-m "not sj"``. This module imports
nothing from sj_client at import time, so deselection works without the extra.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from alexandria.config import SjConfig, load_config, save_config
from tests.sj import daemon
from tests.sj.daemon import Daemon, Executables
from tests.sj.pki import SERVER_NAME, Credentials

if TYPE_CHECKING:
    from sj_client import StoreClient

# Who may use which namespace: Alexandria's principal only default/default.
GRANTS = {"alexandria": [("default", "default")], "other": [("other", "default")]}
DEADLINE_S = 120.0
_LLM_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY")

Connect = Callable[[str], "StoreClient"]


@pytest.fixture(scope="session")
def executables() -> Executables:
    return Executables.from_environment()


@pytest.fixture
def credentials(tmp_path: Path) -> Credentials:
    return Credentials(tmp_path / "credentials", GRANTS)


@pytest.fixture
def store(tmp_path: Path, executables: Executables) -> Path:
    """A store holding default/default and other/default, created with Alexandria's schema."""
    root = tmp_path / "sj" / "state"
    root.parent.mkdir(parents=True)
    daemon.init_store(executables.sjctl, root, "default", "default")
    daemon.init_store(executables.sjctl, root, "other", "default")
    return root


@pytest.fixture
def sjd(store: Path, credentials: Credentials, executables: Executables) -> Iterator[Daemon]:
    running = daemon.secured(executables.sjd, store, credentials, dict(os.environ))
    yield running
    running.stop()


def sj_settings(
    address: str, credentials: Credentials, *, principal: str = "alexandria",
    tenant: str = "default", deadline_s: float = DEADLINE_S,
) -> SjConfig:
    return SjConfig(
        address=address, tenant=tenant, space="default",
        ca=str(credentials.path("ca.pem")),
        certificate=str(credentials.path(f"{principal}.pem")),
        private_key=str(credentials.path(f"{principal}.key")),
        server_name=SERVER_NAME, deadline_s=deadline_s,
    )


def configure(home: Path, settings: SjConfig | None) -> None:
    """Writes the [sj] section of the home's config.toml."""
    config = load_config(home)
    config.sj = settings
    save_config(home, config)


@pytest.fixture
def offline_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """No LLM provider is reachable, so ingest takes Alexandria's deterministic extraction;
    CLI output is not wrapped, so messages can be matched whole."""
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("COLUMNS", "1000")
    for key in _LLM_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def sj_home(initialized_home: Path, sjd: Daemon, credentials: Credentials, offline_cli: None) -> Path:
    configure(initialized_home, sj_settings(sjd.address, credentials))
    return initialized_home


@pytest.fixture
def connect(sjd: Daemon, credentials: Credentials) -> Iterator[Connect]:
    """Opens a mutual-TLS reader of the test's sjd as the named principal."""
    from sj_client import MutualTls, StoreClient

    opened: list[StoreClient] = []

    def open_client(principal: str) -> StoreClient:
        tls = MutualTls(
            ca=credentials.path("ca.pem"), certificate=credentials.path(f"{principal}.pem"),
            private_key=credentials.path(f"{principal}.key"), server_name=SERVER_NAME,
        )
        client = StoreClient.mutual_tls(sjd.address, tls)
        opened.append(client)
        return client

    yield open_client
    for client in opened:
        client.close()
