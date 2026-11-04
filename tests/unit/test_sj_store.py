"""The SJ write path when SJ is not configured or sj-client is missing, and the [sj]
settings. These need neither sj-client nor an sjd, so they run everywhere, public CI included."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from alexandria.config import Config, SjConfig, config_path, load_config, save_config
from alexandria.core.beliefs.model import Belief
from alexandria.core.ingest import ingest_file
from alexandria.core.repo_ingest import ingest_repo
from alexandria.core.runs import runs_dir
from alexandria.core.sj_store import (
    SCHEMA_PATH,
    SJ_CLIENT_REQUIREMENT,
    SjClientMissing,
    SourceFacts,
    publish_beliefs,
    publish_ingest,
    publish_source,
    publish_supersede,
    sj_config,
)
from alexandria.core.workspace import GLOBAL_SLUG, get_workspace
from alexandria.db.connection import connect, db_path

_LLM_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY")


def test_without_an_sj_section_nothing_is_configured_or_written(initialized_home: Path) -> None:
    assert sj_config(initialized_home) is None
    assert "[sj]" not in config_path(initialized_home).read_text(encoding="utf-8")


def test_without_sj_every_publish_returns_none_and_keeps_belief_ids(
    initialized_home: Path, tmp_path: Path,
) -> None:
    workspace = get_workspace(initialized_home, GLOBAL_SLUG).path
    raw = workspace / "raw" / "note.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("A note.\n", encoding="utf-8")
    belief = Belief(workspace=GLOBAL_SLUG, statement="A note exists.", topic="t")
    original = belief.belief_id
    home = initialized_home
    assert publish_beliefs(home, GLOBAL_SLUG, workspace, ("belief_add",), "", [belief]) is None
    assert publish_supersede(home, belief, belief, "r") is None
    assert publish_source(home, GLOBAL_SLUG, workspace, raw) is None
    facts = SourceFacts(kind="manual", ai_authored=False, extracted_by_llm=False, original_pdf=False)
    page = workspace / "wiki" / "x.md"
    assert publish_ingest(home, GLOBAL_SLUG, workspace, raw, "wiki/x.md", page, [belief], facts) is None
    assert belief.belief_id == original


def test_an_sj_section_is_read_and_written_back(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config_path(home).write_text(
        '[sj]\naddress = "127.0.0.1:50051"\nca = "ca.pem"\ncertificate = "c.pem"\n'
        'private_key = "c.key"\n',
        encoding="utf-8",
    )
    settings = load_config(home).sj
    assert settings is not None
    assert (settings.tenant, settings.space, settings.server_name) == ("default", "default", "")
    save_config(home, load_config(home))
    assert load_config(home).sj == settings


def test_relative_tls_paths_resolve_against_the_alexandria_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config_path(home).write_text(
        '[sj]\naddress = "127.0.0.1:50051"\nca = "sj/ca.pem"\ncertificate = "/abs/c.pem"\n'
        'private_key = "sj/c.key"\n',
        encoding="utf-8",
    )
    settings = sj_config(home)
    assert settings is not None
    assert (settings.ca, settings.certificate, settings.private_key) == (
        str(home / "sj/ca.pem"), "/abs/c.pem", str(home / "sj/c.key"),
    )


def _sj_without_client(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[sj] configured and sj-client not importable. Where sj-client is installed (the local
    gate), None in sys.modules makes the interpreter refuse the import exactly as it does
    where the package is absent (public CI)."""
    monkeypatch.setenv("CLAUDECODE", "1")  # no LLM: the deterministic extraction path
    for key in _LLM_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(sys.modules, "sj_client", None)
    config = load_config(home)
    config.sj = SjConfig(address="127.0.0.1:1", ca="ca.pem", certificate="c.pem", private_key="c.key")
    save_config(home, config)


def _nothing_done(home: Path, workspace: Path) -> None:
    """No run started, nothing copied into raw/, nothing indexed."""
    assert not list(runs_dir(home).glob("*/meta.json"))
    assert not list((workspace / "raw").rglob("note.md"))
    with connect(db_path(home)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_sj_configured_without_sj_client_stops_ingest_first_with_install_instructions(
    initialized_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _sj_without_client(initialized_home, monkeypatch)
    note = tmp_path / "note.md"
    note.write_text("# Tides\n\nTides rise twice a day along the survey coast.\n", encoding="utf-8")
    workspace = get_workspace(initialized_home, GLOBAL_SLUG).path
    with pytest.raises(SjClientMissing) as missing:
        ingest_file(initialized_home, GLOBAL_SLUG, workspace, note, no_merge=True)
    assert f'pip install "{SJ_CLIENT_REQUIREMENT}"' in str(missing.value)
    _nothing_done(initialized_home, workspace)


def test_sj_configured_without_sj_client_stops_a_directory_ingest_before_any_file(
    initialized_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _sj_without_client(initialized_home, monkeypatch)
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "note.md").write_text("# Tides\n\nTides rise twice a day.\n", encoding="utf-8")
    workspace = get_workspace(initialized_home, GLOBAL_SLUG).path
    with pytest.raises(SjClientMissing):
        ingest_repo(initialized_home, GLOBAL_SLUG, workspace, folder, no_merge=True)
    _nothing_done(initialized_home, workspace)


def test_an_sj_section_without_an_address_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="address"):
        Config.model_validate({"sj": {"ca": "ca.pem", "certificate": "c.pem", "private_key": "c.key"}})


def test_the_shipped_schema_declares_what_the_mapping_writes() -> None:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    for name in ('"Document"', '"Page"', '"COMPILED_FROM"', '"states"'):
        assert name in text
