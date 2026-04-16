"""Secret vault with AES-256-GCM encryption.

Per ``16_operations_and_reliability.md`` + amendment B4: encrypted secrets
stored on disk with keyring-backed master key, rotation, revocation, and
append-only audit logging.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class VaultError(Exception):
    """Raised on vault operations failures."""


@dataclass(frozen=True)
class SecretEntry:
    """Metadata about a stored secret (never contains the plaintext)."""

    ref: str
    created_at: str
    last_used_at: str | None
    rotated_at: str | None
    revoked: bool


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SecretVault:
    """AES-256-GCM encrypted secret storage.

    Secrets are stored as individual encrypted files under
    ``<home>/secrets/<ref>.enc``. The master key is derived from
    a passphrase via PBKDF2-SHA256.

    Master key source (in priority order):
    1. ``LLMWIKI_VAULT_PASSPHRASE`` environment variable
    2. OS keyring via ``keyring`` package (if available)
    3. Fail with a clear error message
    """

    SALT_SIZE = 16
    NONCE_SIZE = 12
    KEY_ITERATIONS = 600_000
    TAG_SIZE = 16

    def __init__(self, home: Path) -> None:
        self._home = home
        self._secrets_dir = home / "secrets"
        self._secrets_dir.mkdir(parents=True, exist_ok=True)
        self._audit_path = self._secrets_dir / "_audit.jsonl"

    def set(self, ref: str, plaintext: str) -> None:
        """Store or overwrite an encrypted secret."""
        self._validate_ref(ref)
        key, salt = self._derive_key()
        encrypted = self._encrypt(plaintext.encode("utf-8"), key, aad=ref.encode("utf-8"))
        payload = {
            "salt": base64.b64encode(salt).decode(),
            "ciphertext": base64.b64encode(encrypted).decode(),
            "created_at": _now_iso(),
            "rotated_at": None,
            "revoked": False,
        }
        path = self._secret_path(ref)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._audit("set", ref)

    def get(self, ref: str) -> str:
        """Retrieve and decrypt a secret. Raises VaultError if not found/revoked."""
        self._validate_ref(ref)
        path = self._secret_path(ref)
        if not path.exists():
            raise VaultError(f"secret {ref!r} not found")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("revoked"):
            raise VaultError(f"secret {ref!r} has been revoked")

        salt = base64.b64decode(payload["salt"])
        ciphertext = base64.b64decode(payload["ciphertext"])
        key = self._derive_key_from_salt(salt)
        plaintext = self._decrypt(ciphertext, key, aad=ref.encode("utf-8"))

        # Update last_used_at
        payload["last_used_at"] = _now_iso()
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return plaintext.decode("utf-8")

    def rotate(self, ref: str, new_plaintext: str) -> None:
        """Rotate a secret: store new value, keep old for 7 days."""
        self._validate_ref(ref)
        path = self._secret_path(ref)
        if not path.exists():
            raise VaultError(f"secret {ref!r} not found, cannot rotate")

        # Archive old value
        old_payload = json.loads(path.read_text(encoding="utf-8"))
        archive_path = self._secrets_dir / f"{ref}.old.enc"
        old_payload["archived_at"] = _now_iso()
        archive_path.write_text(json.dumps(old_payload, indent=2), encoding="utf-8")

        # Write new value
        self.set(ref, new_plaintext)

        # Update rotation timestamp
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["rotated_at"] = _now_iso()
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._audit("rotate", ref)

    def revoke(self, ref: str) -> None:
        """Wipe a secret and mark it as revoked."""
        self._validate_ref(ref)
        path = self._secret_path(ref)
        if not path.exists():
            raise VaultError(f"secret {ref!r} not found")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["ciphertext"] = ""
        payload["revoked"] = True
        payload["revoked_at"] = _now_iso()
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        # Remove old archive too
        archive = self._secrets_dir / f"{ref}.old.enc"
        if archive.exists():
            archive.unlink()

        self._audit("revoke", ref)

    def list_secrets(self) -> list[SecretEntry]:
        """List all secrets (metadata only, never plaintext)."""
        entries: list[SecretEntry] = []
        for path in sorted(self._secrets_dir.glob("*.enc")):
            if path.name.endswith(".old.enc"):
                continue
            ref = path.stem
            payload = json.loads(path.read_text(encoding="utf-8"))
            entries.append(SecretEntry(
                ref=ref,
                created_at=payload.get("created_at", ""),
                last_used_at=payload.get("last_used_at"),
                rotated_at=payload.get("rotated_at"),
                revoked=payload.get("revoked", False),
            ))
        return entries

    def reveal(self, ref: str) -> str:
        """Retrieve a secret with audit logging (for explicit reveal)."""
        self._audit("reveal", ref)
        return self.get(ref)

    def exists(self, ref: str) -> bool:
        return self._secret_path(ref).exists()

    # -- Internals -----------------------------------------------------------

    def _secret_path(self, ref: str) -> Path:
        return self._secrets_dir / f"{ref}.enc"

    def _validate_ref(self, ref: str) -> None:
        if not ref or "/" in ref or "\\" in ref or ".." in ref:
            raise VaultError(f"invalid secret ref: {ref!r}")
        if len(ref) > 128:
            raise VaultError(f"secret ref too long: {len(ref)} chars (max 128)")

    def _get_passphrase(self) -> str:
        env = os.environ.get("LLMWIKI_VAULT_PASSPHRASE")
        if env:
            return env
        try:
            import keyring
            stored = keyring.get_password("llmwiki", "vault_master")
            if stored:
                return stored
        except (ImportError, Exception):
            pass
        raise VaultError(
            "no vault passphrase found. Set LLMWIKI_VAULT_PASSPHRASE or "
            "install keyring and run: llmwiki secrets init"
        )

    def _derive_key(self) -> tuple[bytes, bytes]:
        """Derive a 256-bit key from the passphrase. Returns (key, salt)."""
        passphrase = self._get_passphrase()
        salt = os.urandom(self.SALT_SIZE)
        key = hashlib.pbkdf2_hmac(
            "sha256", passphrase.encode("utf-8"), salt, self.KEY_ITERATIONS
        )
        return key, salt

    def _derive_key_from_salt(self, salt: bytes) -> bytes:
        passphrase = self._get_passphrase()
        return hashlib.pbkdf2_hmac(
            "sha256", passphrase.encode("utf-8"), salt, self.KEY_ITERATIONS
        )

    def _encrypt(self, plaintext: bytes, key: bytes, aad: bytes | None = None) -> bytes:
        """AES-256-GCM encrypt. Returns nonce + ciphertext + tag."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = os.urandom(self.NONCE_SIZE)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
        return nonce + ciphertext

    def _decrypt(self, data: bytes, key: bytes, aad: bytes | None = None) -> bytes:
        """AES-256-GCM decrypt. Input is nonce + ciphertext + tag."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = data[:self.NONCE_SIZE]
        ciphertext = data[self.NONCE_SIZE:]
        aesgcm = AESGCM(key)
        try:
            return aesgcm.decrypt(nonce, ciphertext, aad)
        except Exception as exc:
            raise VaultError("decryption failed — wrong passphrase or corrupted data") from exc

    def _audit(self, action: str, ref: str) -> None:
        """Append to the audit log."""
        entry = {
            "timestamp": _now_iso(),
            "action": action,
            "ref": ref,
        }
        with self._audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
