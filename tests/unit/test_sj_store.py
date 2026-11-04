"""The SJ write path when SJ is not configured, and the [sj] settings. These need neither the
sj extra nor an sjd, so they run everywhere, public CI included."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from alexandria.config import Config, config_path, load_config, save_config
from alexandria.core.beliefs.model import Belief
from alexandria.core.sj_store import (
    SCHEMA_PATH,
    SourceFacts,
    publish_beliefs,
    publish_ingest,
    publish_source,
    publish_supersede,
    sj_config,
)
from alexandria.core.workspace import GLOBAL_SLUG, get_workspace


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


def test_an_sj_section_without_an_address_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="address"):
        Config.model_validate({"sj": {"ca": "ca.pem", "certificate": "c.pem", "private_key": "c.key"}})


def test_the_shipped_schema_declares_what_the_mapping_writes() -> None:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    for name in ('"Document"', '"Page"', '"COMPILED_FROM"', '"states"'):
        assert name in text
