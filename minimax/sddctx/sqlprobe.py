"""Direct SQL access to the OceanBase / seekdb store that backs PowerContext.

The verification scripts want to prove that the data really landed in the
database instead of in a process-local cache.  They therefore read the
PowerContext tables directly, with the same SQL in both storage modes:

``docker``
    The classic setup: a ``oceanbase/seekdb`` container reachable on the
    MySQL protocol.  The statements are executed with ``docker exec ... mysql``.

``embedded``
    The Docker-free setup: PowerContext starts seekdb in-process through the
    ``pylibseekdb`` binding and stores it in a local directory.  The same
    statements are executed through that binding, which attaches to the
    already running instance.

Both modes return the same :class:`SqlResult` shape, so the callers do not
have to know which storage is in use.  A failing query is reported, never
raised: a verification script must be able to record "the direct SQL check was
not available" instead of crashing.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "STORAGE_DOCKER",
    "STORAGE_EMBEDDED",
    "SqlResult",
    "available_modes",
    "detect_schema",
    "run_sql",
]

STORAGE_DOCKER = "docker"
STORAGE_EMBEDDED = "embedded"

DEFAULT_DATABASE = "powercontext_sdd"
DEFAULT_CONTAINER = "oceanbase-seekdb"
DEFAULT_SEEKDB_DIR = ".runtime/seekdb-data"


@dataclass(frozen=True)
class SqlResult:
    """The outcome of one direct SQL statement."""

    mode: str
    statement: str
    ok: bool
    rows: tuple[tuple[Any, ...], ...] = ()
    text: str = ""
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "statement": self.statement,
            "ok": self.ok,
            "rows": [list(row) for row in self.rows],
            "error": self.error,
        }


def available_modes() -> tuple[str, ...]:
    """The storage modes this module can talk to."""
    return (STORAGE_DOCKER, STORAGE_EMBEDDED)


def _split_statements(script: str) -> list[str]:
    """Split a SQL script into single statements.

    The embedded cursor executes one statement at a time, so a multi
    statement script has to be split.  Semicolons inside string literals are
    rare in the verification queries and are not handled.
    """
    parts = [part.strip() for part in script.split(";")]
    return [part for part in parts if part]


def _strip_database(statement: str, database: str) -> str:
    """Remove the database qualifier for the embedded store.

    The embedded seekdb instance uses its own fixed database name, so a
    qualified reference such as ``powercontext_sdd.pc_sources`` has to become
    ``pc_sources``.
    """
    if not database:
        return statement
    qualified = re.compile(rf"`?{re.escape(database)}`?\s*\.\s*`?(\w+)`?")
    return qualified.sub(r"`\1`", statement)


def _run_docker(statements: list[str], database: str, container: str) -> SqlResult:
    command = [
        "docker",
        "exec",
        "-i",
        container,
        "mysql",
        "-h127.0.0.1",
        "-P2881",
        "-uroot",
        "-N",
    ]
    if database:
        command += ["-D", database]
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            input=";\n".join(statements) + ";\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return SqlResult(
            mode=STORAGE_DOCKER,
            statement="; ".join(statements),
            ok=False,
            error=f"{type(error).__name__}: {error}",
        )
    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        return SqlResult(
            mode=STORAGE_DOCKER,
            statement="; ".join(statements),
            ok=False,
            text=output,
            error=(completed.stderr or "").strip() or f"exit code {completed.returncode}",
        )
    rows = tuple(
        tuple(line.split("\t")) for line in output.splitlines() if line.strip()
    ) if output else ()
    return SqlResult(
        mode=STORAGE_DOCKER,
        statement="; ".join(statements),
        ok=True,
        rows=rows,
        text=output,
    )


def _run_embedded(statements: list[str], database: str, seekdb_dir: Path) -> SqlResult:
    try:
        import pylibseekdb
    except ModuleNotFoundError as error:
        return SqlResult(
            mode=STORAGE_EMBEDDED,
            statement="; ".join(statements),
            ok=False,
            error=f"pylibseekdb is not installed: {error}",
        )

    if not seekdb_dir.exists():
        return SqlResult(
            mode=STORAGE_EMBEDDED,
            statement="; ".join(statements),
            ok=False,
            error=f"the embedded seekdb data directory does not exist: {seekdb_dir}",
        )

    instance = None
    try:
        instance = pylibseekdb.open(str(seekdb_dir))
        connection = instance.connect()
        cursor = connection.cursor()
        rows: list[tuple[Any, ...]] = []
        for statement in statements:
            cursor.execute(_strip_database(statement, database))
            fetched = cursor.fetchall()
            if fetched:
                rows.extend(tuple(row) for row in fetched)
            # The embedded connection does not report the autocommit flag in
            # its handshake, so it starts with autocommit disabled.  Without an
            # explicit commit every write would be rolled back when the handle
            # is closed, which silently turns a reset into a no-op.
            cursor.execute("COMMIT")
    except Exception as error:
        return SqlResult(
            mode=STORAGE_EMBEDDED,
            statement="; ".join(statements),
            ok=False,
            error=f"{type(error).__name__}: {error}",
        )
    finally:
        if instance is not None:
            # Closing the attached handle must never mask the query result.
            with contextlib.suppress(Exception):
                instance.close()

    text = "\n".join("\t".join(str(cell) for cell in row) for row in rows)
    return SqlResult(
        mode=STORAGE_EMBEDDED,
        statement="; ".join(statements),
        ok=True,
        rows=tuple(rows),
        text=text,
    )


def detect_schema(
    *,
    mode: str = STORAGE_DOCKER,
    database: str = DEFAULT_DATABASE,
    container: str = DEFAULT_CONTAINER,
    seekdb_dir: str | Path | None = None,
) -> str:
    """Return the schema that holds the PowerContext tables.

    The container deployment uses the configured database name, while the
    embedded instance owns a fixed schema of its own, so the real name has to
    be read from the server instead of assumed.
    """
    if mode == STORAGE_EMBEDDED:
        directory = Path(seekdb_dir or DEFAULT_SEEKDB_DIR).expanduser().resolve()
        try:
            import pylibseekdb
        except ModuleNotFoundError:
            return database
        instance = None
        try:
            instance = pylibseekdb.open(str(directory))
            cursor = instance.connect().cursor()
            cursor.execute("SELECT DATABASE()")
            rows = cursor.fetchall()
        except Exception:
            return database
        finally:
            if instance is not None:
                with contextlib.suppress(Exception):
                    instance.close()
        if rows and rows[0] and rows[0][0]:
            return str(rows[0][0])
        return database

    result = run_sql(
        "SELECT DATABASE();",
        mode=mode,
        database=database,
        container=container,
        seekdb_dir=seekdb_dir,
    )
    if result.ok and result.rows and result.rows[0] and result.rows[0][0]:
        return str(result.rows[0][0])
    return database


def run_sql(
    sql: str,
    *,
    mode: str = STORAGE_DOCKER,
    database: str = DEFAULT_DATABASE,
    container: str = DEFAULT_CONTAINER,
    seekdb_dir: str | Path | None = None,
) -> SqlResult:
    """Execute ``sql`` directly against the store that backs PowerContext."""
    statements = _split_statements(sql)
    if not statements:
        return SqlResult(mode=mode, statement=sql, ok=False, error="empty statement")
    if mode == STORAGE_EMBEDDED:
        directory = Path(seekdb_dir or DEFAULT_SEEKDB_DIR).expanduser().resolve()
        return _run_embedded(statements, database, directory)
    if mode == STORAGE_DOCKER:
        return _run_docker(statements, database, container)
    return SqlResult(mode=mode, statement=sql, ok=False, error=f"unknown storage mode: {mode}")
