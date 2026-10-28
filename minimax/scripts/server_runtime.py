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
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

STORAGE_DOCKER = "docker"
STORAGE_EMBEDDED = "embedded"

DEFAULT_DOCKER_URL = (
    "mysql+aoceanbase://root:@127.0.0.1:2881/powercontext_sdd?charset=utf8mb4"
)

# The very first start on an empty embedded data directory has to create the
# whole schema (61 tables) before the server can answer, which takes roughly
# two minutes.  The readiness check therefore needs a generous timeout, and it
# must never be cut short: an interrupted bootstrap leaves the store in a
# "recovery_required" state that refuses to start.
DEFAULT_READY_TIMEOUT = 300.0


def now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(UTC).isoformat()


def remove_file(path: Path) -> None:
    """Delete a file, ignoring the case where another process still holds it.

    On Windows a log file of a server that has just been stopped can still be
    open, and deleting it then fails.  A stale log is harmless, so the failure
    is ignored on purpose.
    """
    try:
        path.unlink()
    except OSError:
        pass


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


class ServerStartupError(RuntimeError):
    """The PowerContext Server could not be started."""


def start_server(
    *,
    storage: str,
    seekdb_dir: Path | None,
    port: int,
    env_file: Path,
    log_path: Path,
    home: Path,
    base_env: dict[str, str] | None = None,
    recreate_store: bool = False,
    timeout: float = DEFAULT_READY_TIMEOUT,
) -> ServerHandle:
    """Derive the environment, start the server and wait until it answers.

    ``recreate_store`` lets the caller recover from an interrupted bootstrap:
    a store that was left in the ``recovery_required`` state refuses to start,
    and a script that owns its data directory can simply start over with a
    fresh one.
    """
    env = build_server_env(
        storage=storage,
        seekdb_dir=seekdb_dir,
        port=port,
        home=home,
        base_env=base_env,
    )
    write_env_file(env, env_file)
    remove_file(log_path)
    server = ServerHandle(env_file, port, log_path)
    try:
        server.start()
        server.wait_ready(timeout)
    except RuntimeError as error:
        message = str(error)
        broken_store = "recovery_required" in message
        if not (broken_store and recreate_store and storage == STORAGE_EMBEDDED):
            raise ServerStartupError(
                f"{message}\n"
                "If the log mentions 'recovery_required', the store was left in a state that "
                "refuses to start: delete the data directory (scripts/reset.py --database "
                "--storage embedded) or apply the pending migration with "
                "'powercontext server db-migrate apply --env-file <file>'."
            ) from error
        # The bootstrap of the previous run was interrupted; start over.
        remove_file(log_path)
        if seekdb_dir is not None:
            shutil.rmtree(seekdb_dir, ignore_errors=True)
        write_env_file(env, env_file)
        server = ServerHandle(env_file, port, log_path)
        server.start()
        server.wait_ready(timeout)
    return server


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
        self._server_info: dict[str, object] = {}

    def server_info(self) -> dict[str, object]:
        """Return the server info that was read when the server became ready."""
        return self._server_info

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

    def wait_ready(self, timeout: float = DEFAULT_READY_TIMEOUT) -> dict[str, object]:
        """Block until the server answers, then return its server info."""
        # The health check must not go through an HTTP proxy: the server
        # listens on the loopback interface, and an environment proxy turns a
        # perfectly healthy server into a "502 Bad Gateway".
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.time() + timeout
        last_error = ""
        while time.time() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"PowerContext Server exited early with code {self.process.returncode}."
                    f"{self.log_tail()}"
                )
            try:
                with opener.open(
                    f"http://127.0.0.1:{self.port}/v1/server-info", timeout=3
                ) as response:
                    self._server_info = json.loads(response.read().decode("utf-8"))
                    return self._server_info
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                last_error = str(error)
                time.sleep(0.5)
        raise RuntimeError(
            f"PowerContext Server was not ready in {timeout}s: {last_error}."
            f"{self.log_tail()}"
        )

    def log_tail(self, lines: int = 12) -> str:
        """Return the last lines of the server log, for error messages."""
        if not self.log_path.exists():
            return ""
        text = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not text:
            return ""
        return "\n--- server log ---\n" + "\n".join(text[-lines:])

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
