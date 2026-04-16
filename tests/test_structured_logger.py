"""Tests for structured JSONL logger."""

import json
from pathlib import Path

import pytest

from alexandria.observability.logger import StructuredLogger, get_logger, init_logging


class TestStructuredLogger:
    def test_creates_log_file(self, tmp_path: Path) -> None:
        logger = StructuredLogger(tmp_path, family="test")
        logger.info("hello")
        files = list(tmp_path.glob("test-*.jsonl"))
        assert len(files) == 1

    def test_log_entry_is_json(self, tmp_path: Path) -> None:
        logger = StructuredLogger(tmp_path, family="test")
        logger.info("event_name", data={"key": "value"})
        files = list(tmp_path.glob("test-*.jsonl"))
        content = files[0].read_text()
        entry = json.loads(content.strip())
        assert entry["event"] == "event_name"
        assert entry["level"] == "info"
        assert entry["data"]["key"] == "value"
        assert "ts" in entry

    def test_log_levels(self, tmp_path: Path) -> None:
        logger = StructuredLogger(tmp_path, family="test")
        logger.info("i")
        logger.warn("w")
        logger.error("e")
        files = list(tmp_path.glob("test-*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 3
        assert json.loads(lines[0])["level"] == "info"
        assert json.loads(lines[1])["level"] == "warn"
        assert json.loads(lines[2])["level"] == "error"

    def test_run_id_and_workspace(self, tmp_path: Path) -> None:
        logger = StructuredLogger(tmp_path, family="test")
        logger.info("ev", run_id="r-123", workspace="global")
        files = list(tmp_path.glob("test-*.jsonl"))
        entry = json.loads(files[0].read_text().strip())
        assert entry["run_id"] == "r-123"
        assert entry["workspace"] == "global"

    def test_optional_fields_omitted(self, tmp_path: Path) -> None:
        logger = StructuredLogger(tmp_path, family="test")
        logger.info("minimal")
        files = list(tmp_path.glob("test-*.jsonl"))
        entry = json.loads(files[0].read_text().strip())
        assert "run_id" not in entry
        assert "workspace" not in entry
        assert "data" not in entry

    def test_multiple_families(self, tmp_path: Path) -> None:
        l1 = StructuredLogger(tmp_path, family="daemon")
        l2 = StructuredLogger(tmp_path, family="scheduler")
        l1.info("from_daemon")
        l2.info("from_scheduler")
        assert len(list(tmp_path.glob("daemon-*.jsonl"))) == 1
        assert len(list(tmp_path.glob("scheduler-*.jsonl"))) == 1


class TestGetLogger:
    def test_init_and_get(self, tmp_path: Path) -> None:
        init_logging(tmp_path)
        logger = get_logger("test")
        logger.info("test_event")
        files = list(tmp_path.glob("test-*.jsonl"))
        assert len(files) == 1

    def test_same_family_returns_same_logger(self, tmp_path: Path) -> None:
        init_logging(tmp_path)
        l1 = get_logger("shared")
        l2 = get_logger("shared")
        assert l1 is l2
