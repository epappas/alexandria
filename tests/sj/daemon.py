"""Real sjctl and sjd processes for the SJ-marked tests: the executables named by the
environment, stores created with Alexandria's schema, and a secured sjd on a free port."""

from __future__ import annotations

import json
import os
import select
import subprocess
from dataclasses import dataclass
from pathlib import Path

from alexandria.core.sj_store import SCHEMA_PATH
from tests.sj.pki import Credentials

STARTUP_SECONDS = 60.0
STOP_SECONDS = 30.0
_VARIABLES = {"sjctl": "SJ_TEST_SJCTL", "sjd": "SJ_TEST_SJD", "hooked_sjd": "SJ_TEST_HOOKS_SJD"}


@dataclass(frozen=True)
class Executables:
    """sjctl, sjd and an sjd built with the test-hooks feature, which can pause a write."""

    sjctl: Path
    sjd: Path
    hooked_sjd: Path

    @classmethod
    def from_environment(cls) -> Executables:
        found: dict[str, Path] = {}
        for name, variable in _VARIABLES.items():
            value = os.environ.get(variable, "")
            if not value or not os.access(value, os.X_OK):
                raise RuntimeError(
                    f"{variable} must name an executable; the SJ-marked tests need real sjctl and "
                    "sjd builds (run them with -m sj in the local gate, or deselect with -m 'not sj')"
                )
            found[name] = Path(value)
        return cls(**found)


def init_store(
    sjctl: Path, root: Path, tenant: str, space: str, receipt_window: int | None = None,
) -> None:
    """Creates the namespace tenant/space at `root` with the shipped Alexandria schema; with
    `receipt_window`, a receipt expires once that many later namespace versions commit."""
    window = [] if receipt_window is None else ["--receipt-window", str(receipt_window)]
    subprocess.run(
        [str(sjctl), "--state", str(root), "init", "--schema", str(SCHEMA_PATH),
         "--tenant", tenant, "--space", space, *window],
        check=True, capture_output=True,
    )


@dataclass
class Daemon:
    process: subprocess.Popen[bytes]
    address: str

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=STOP_SECONDS)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        if self.process.stdout is not None:
            self.process.stdout.close()


def secured(sjd: Path, root: Path, credentials: Credentials, env: dict[str, str]) -> Daemon:
    """sjd in secured mode: mutual TLS, the credentials' policy, an audit log, logs to a file."""
    path = credentials.path
    command = [
        str(sjd), "--state", str(root), "--listen", "127.0.0.1:0",
        "--policy", str(path("policy.json")), "--tls-cert", str(path("server.pem")),
        "--tls-key", str(path("server.key")), "--client-ca", str(path("ca.pem")),
        "--audit-log", str(root.parent / "audit.jsonl"),
    ]
    with (root.parent / "sjd.log").open("ab") as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log, env=env)
    assert process.stdout is not None
    readable, _, _ = select.select([process.stdout], [], [], STARTUP_SECONDS)
    line = process.stdout.readline() if readable else b""
    if not line:
        process.kill()
        raise RuntimeError(f"sjd printed no ready line; exit status {process.wait()}")
    ready = json.loads(line)
    if ready["mode"] != "mutual_tls":
        process.kill()
        raise RuntimeError(f"sjd started in mode {ready['mode']}, not mutual_tls")
    return Daemon(process, ready["listening"])
