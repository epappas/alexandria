"""Tests for secret vault encrypt/decrypt roundtrip."""

import os
from pathlib import Path

import pytest

from llmwiki.core.secrets.vault import SecretVault, VaultError


@pytest.fixture(autouse=True)
def vault_passphrase(monkeypatch) -> None:
    monkeypatch.setenv("LLMWIKI_VAULT_PASSPHRASE", "test-passphrase-12345")


@pytest.fixture
def vault(tmp_path: Path) -> SecretVault:
    return SecretVault(tmp_path)


class TestSecretVault:
    def test_set_and_get(self, vault: SecretVault) -> None:
        vault.set("my-token", "secret-value-123")
        assert vault.get("my-token") == "secret-value-123"

    def test_get_nonexistent_raises(self, vault: SecretVault) -> None:
        with pytest.raises(VaultError, match="not found"):
            vault.get("nonexistent")

    def test_overwrite(self, vault: SecretVault) -> None:
        vault.set("key", "value1")
        vault.set("key", "value2")
        assert vault.get("key") == "value2"

    def test_rotate(self, vault: SecretVault) -> None:
        vault.set("key", "old")
        vault.rotate("key", "new")
        assert vault.get("key") == "new"

    def test_rotate_nonexistent_raises(self, vault: SecretVault) -> None:
        with pytest.raises(VaultError, match="not found"):
            vault.rotate("nope", "value")

    def test_revoke(self, vault: SecretVault) -> None:
        vault.set("key", "secret")
        vault.revoke("key")
        with pytest.raises(VaultError, match="revoked"):
            vault.get("key")

    def test_list_secrets(self, vault: SecretVault) -> None:
        vault.set("a", "1")
        vault.set("b", "2")
        entries = vault.list_secrets()
        refs = [e.ref for e in entries]
        assert "a" in refs
        assert "b" in refs

    def test_list_shows_revoked(self, vault: SecretVault) -> None:
        vault.set("key", "val")
        vault.revoke("key")
        entries = vault.list_secrets()
        assert entries[0].revoked is True

    def test_reveal_audit_logged(self, vault: SecretVault) -> None:
        vault.set("key", "secret")
        value = vault.reveal("key")
        assert value == "secret"
        # Check audit log
        audit = vault._audit_path.read_text()
        assert '"reveal"' in audit

    def test_exists(self, vault: SecretVault) -> None:
        assert vault.exists("key") is False
        vault.set("key", "val")
        assert vault.exists("key") is True

    def test_invalid_ref_rejected(self, vault: SecretVault) -> None:
        with pytest.raises(VaultError, match="invalid"):
            vault.set("../escape", "val")
        with pytest.raises(VaultError, match="invalid"):
            vault.set("path/slash", "val")

    def test_wrong_passphrase_fails(self, vault: SecretVault, monkeypatch) -> None:
        vault.set("key", "secret")
        monkeypatch.setenv("LLMWIKI_VAULT_PASSPHRASE", "wrong-passphrase")
        with pytest.raises(VaultError, match="decryption failed"):
            vault.get("key")
