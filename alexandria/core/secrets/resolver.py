"""Cached secret resolver injected into source adapters.

Wraps the vault with a TTL cache so repeated reads within a sync cycle
don't re-derive the PBKDF2 key on each call.
"""

from __future__ import annotations

import time
from pathlib import Path

from alexandria.core.secrets.vault import SecretVault, VaultError


class SecretResolver:
    """Lazy, caching wrapper around SecretVault for adapter use."""

    DEFAULT_TTL = 300.0  # 5 minutes

    def __init__(self, home: Path, ttl: float | None = None) -> None:
        self._vault = SecretVault(home)
        self._ttl = ttl if ttl is not None else self.DEFAULT_TTL
        self._cache: dict[str, tuple[str, float]] = {}

    def resolve(self, ref: str) -> str:
        """Resolve a secret by ref, caching for ``ttl`` seconds."""
        now = time.monotonic()
        cached = self._cache.get(ref)
        if cached is not None:
            value, fetched_at = cached
            if now - fetched_at < self._ttl:
                return value

        value = self._vault.get(ref)
        self._cache[ref] = (value, now)
        return value

    def clear_cache(self) -> None:
        self._cache.clear()

    @property
    def vault(self) -> SecretVault:
        return self._vault
