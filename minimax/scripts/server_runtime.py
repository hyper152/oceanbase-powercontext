"""Runtime helpers shared by the verification scripts.

The scripts in this directory must be runnable without any hand-written
environment file, because the storage mode decides which store the
PowerContext Server talks to:

* ``docker``   -- an OceanBase / seekdb container reachable over MySQL.
* ``embedded`` -- the embedded seekdb engine (``pylibseekdb``) that PowerContext
  starts in-process from a local data directory.  No container is involved.

Both modes are derived into a concrete environment file here so the server is
always started with a configuration that matches the mode the caller asked
for.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

STORAGE_DOCKER = "docker"
STORAGE_EMBEDDED = "embedded"

DEFAULT_DOCKER_URL = (
    "mysql+aoceanbase://root:@127.0.0.1:2881/powercontext_sdd?charset=utf8mb4"
)


def now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(UTC).isoformat()


def port_is_free(port: int) -> bool:
    """Return True when nothing is listening on ``127.0.0.1:port``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def parse_env_file(path: Path) -> dict[str, str]:
    """Read the ``KEY=VALUE`` pairs of an environment file.

    Comments and blank lines are ignored.  Malformed lines are skipped so a
    stale operator file cannot break the verification run.
    """
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def build_server_env(
    *,
    storage: str,
    seekdb_dir: Path | None = None,
    port: int,
    host: str = "127.0.0.1",
    home: Path,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Derive the environment of a PowerContext Server for ``storage``.

    The environment-file parser of PowerContext treats a backslash as an
    escape character, so every Windows path is written with forward slashes.
    """
    env: dict[str, str] = dict(base_env or {})
    env["POWERCONTEXT_SERVER_HTTP_HOST"] = host
    env["POWERCONTEXT_SERVER_HTTP_PORT"] = str(port)
    env["POWERCONTEXT_HOME"] = Path(home).as_posix()
    env.setdefault("POWERCONTEXT_SERVER_ACCESS_MODE", "disabled")
    env.setdefault("POWERCONTEXT_SERVER_MCP_ENABLED", "false")
    env.setdefault("POWERCONTEXT_SERVER_DASHBOARD_ENABLED", "false")
    if storage == STORAGE_EMBEDDED:
        if seekdb_dir is None:
            raise ValueError("the embedded storage mode needs a seekdb data directory")
        env["POWERCONTEXT_SERVER_DATABASE_KIND"] = "seekdb"
        env["POWERCONTEXT_SERVER_DATABASE_PATH"] = Path(seekdb_dir).as_posix()
        # A stale container URL would win over the embedded store.
        env.pop("POWERCONTEXT_SERVER_DATABASE_URL", None)
    else:
        env["POWERCONTEXT_SERVER_DATABASE_KIND"] = "oceanbase"
        env.setdefault("POWERCONTEXT_SERVER_DATABASE_URL", DEFAULT_DOCKER_URL)
    return env


def write_env_file(env: dict[str, str], target: Path) -> Path:
    """Write ``env`` as a PowerContext environment file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"{key}={value}" for key, value in env.items())
    target.write_text(body + "\n", encoding="utf-8")
    return target


def powercontext_executable() -> Path:
    """Locate the ``powercontext`` console script of the active environment."""
    candidates = [
        Path(sys.executable).parent / "powercontext.exe",
        Path(sys.executable).parent / "powercontext",
        Path(sys.executable).parent / "powercontext-script.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "the 'powercontext' console script was not found next to the active interpreter; "
        "install the project with 'uv pip install -e .'"
    )


class ServerHandle:
    """A PowerContext Server process owned by a verification script."""

    def __init__(self, env_file: Path, port: int, log_path: Path) -> None:
        self.env_file = env_file
        self.port = port
        self.log_path = log_path
        self.process: subprocess.Popen[bytes] | None = None
        self.started_at: str | None = None

    def start(self) -> None:
        """Launch the server and return immediately."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.log_path.open("ab")
        executable = powercontext_executable()
        self.process = subprocess.Popen(
            [
                str(executable),
                "server",
                "run",
                "--env-file",
                str(self.env_file),
                "--port",
                str(self.port),
            ],
            stdout=handle,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        self.started_at = now_iso()

    @property
    def pid(self) -> int | None:
        """Return the process id of the running server, if any."""
        return self.process.pid if self.process is not None else None

    def wait_ready(self, timeout: float = 90.0) -> dict[str, object]:
        """Block until the server answers, then return its server info."""
        import urllib.error
        import urllib.request

        deadline = time.time() + timeout
        last_error = ""
        while time.time() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"PowerContext Server exited early with code {self.process.returncode}; "
                    f"see {self.log_path}"
                )
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/v1/server-info", timeout=3
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                last_error = str(error)
                time.sleep(0.5)
        raise RuntimeError(f"PowerContext Server was not ready in {timeout}s: {last_error}")

    def stop(self) -> dict[str, object]:
        """Stop the server with SIGTERM and report how it exited."""
        if self.process is None:
            return {"stopped": False, "reason": "process was never started"}
        self.process.send_signal(signal.SIGTERM)
        try:
            exit_code = self.process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.process.kill()
            exit_code = self.process.wait(timeout=30)
        return {
            "stopped": True,
            "signal": "SIGTERM",
            "exit_code": exit_code,
            "pid": self.process.pid,
            "started_at": self.started_at,
            "stopped_at": now_iso(),
        }

    def instance_identity(self) -> dict[str, str]:
        """Read the instance identity the server prints on every request."""
        identity: dict[str, str] = {}
        if not self.log_path.exists():
            return identity
        text = self.log_path.read_text(encoding="utf-8", errors="replace")
        for key in ("service_instance_id", "service_version"):
            marker = f'{key}="'
            index = text.rfind(marker)
            if index != -1:
                rest = text[index + len(marker) :]
                identity[key] = rest.split('"', 1)[0]
        return identity
