"""Reset the local SDD context-management state.

The script offers the reset operations that the documentation describes, so
that a reviewer can return the environment to a known state without hunting
for the right SQL.  Destructive operations are opt-in and print what they are
about to do.

Usage::

    python scripts/reset.py --scope minimax-sdd      # drop a scope, re-import
    python scripts/reset.py --artifacts              # delete the recorded artefacts
    python scripts/reset.py --worktree               # restore the pre-change sample
    python scripts/reset.py --database               # drop and recreate the database
    python scripts/reset.py --all                    # scope + artefacts + worktree
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sddctx.parsing import scan_project  # noqa: E402
from sddctx.sqlprobe import (  # noqa: E402
    STORAGE_DOCKER,
    STORAGE_EMBEDDED,
    detect_schema,
    run_sql,
)
from sddctx.store import PowerContextStore, build_client  # noqa: E402
from server_runtime import (  # noqa: E402
    ServerHandle,
    parse_env_file,
    port_is_free,
    start_server,
)

SAMPLE_DIR = ROOT / "sample"
ARTIFACTS_DIR = ROOT / "artifacts"
BEFORE_SNAPSHOT = ARTIFACTS_DIR / "snapshots" / "before"
DEFAULT_DATABASE = "powercontext_sdd"
MYSQL_CONTAINER = "oceanbase-seekdb"
DEFAULT_SEEKDB_DIR = ROOT / ".runtime" / "seekdb-data"
DEFAULT_PORT = 8010


def _say(message: str) -> None:
    print(message, flush=True)


def _sql(
    sql: str,
    *,
    storage: str,
    database: str,
    container: str,
    seekdb_dir: Path,
) -> tuple[str, str]:
    """Run SQL against the configured store and return ``(output, error)``."""
    result = run_sql(
        sql,
        mode=storage,
        database=database,
        container=container,
        seekdb_dir=seekdb_dir,
    )
    return result.text, result.error


def _scope_tables(storage: str, database: str, container: str, seekdb_dir: Path) -> list[str]:
    """Every PowerContext table that carries a ``scope_id`` column."""
    schema = detect_schema(
        mode=storage,
        database=database,
        container=container,
        seekdb_dir=seekdb_dir,
    )
    output, error = _sql(
        "SELECT table_name FROM information_schema.columns "
        f"WHERE table_schema = '{schema}' AND column_name = 'scope_id';",
        storage=storage,
        database=database,
        container=container,
        seekdb_dir=seekdb_dir,
    )
    if error:
        _say(f"could not resolve the PowerContext tables: {error}")
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def reset_scope(
    server_url: str,
    title: str,
    project: Path,
    database: str,
    *,
    storage: str,
    container: str,
    seekdb_dir: Path,
) -> int:
    """Delete a scope's rows from the database and import the project again.

    PowerContext does not expose a scope deletion endpoint, so the reset is done
    directly against the store.  Foreign key checks are disabled for the
    session because the scope's rows span several tables.
    """
    schema = detect_schema(
        mode=storage,
        database=database,
        container=container,
        seekdb_dir=seekdb_dir,
    )

    async def run() -> int:
        client = build_client(server_url)
        default_scope = await client.get_default_scope()
        store = PowerContextStore(client, default_scope.scope_id)
        deleted_scope = await store.ensure_scope(title, "MiniMax SDD context management corpus")

        tables = _scope_tables(storage, database, container, seekdb_dir)
        if not tables:
            _say("could not resolve the PowerContext tables; is the database reachable?")
            return 1
        statements = ["SET FOREIGN_KEY_CHECKS=0;"]
        statements += [
            f"DELETE FROM `{schema}`.`{table}` WHERE scope_id = '{deleted_scope}';" for table in tables
        ]
        statements.append("SET FOREIGN_KEY_CHECKS=1;")
        output, error = _sql(
            "\n".join(statements),
            storage=storage,
            database=database,
            container=container,
            seekdb_dir=seekdb_dir,
        )
        if error:
            _say(f"delete failed: {error.strip() or output.strip()}")
            return 1

        # The scope row itself was part of the deletion, so the scope is
        # recreated with a fresh identifier before the corpus is imported again.
        scope_id = await store.ensure_scope(title, "MiniMax SDD context management corpus")
        fresh = PowerContextStore(client, scope_id)
        records = scan_project(project)
        entries = await fresh.put_records(records)
        _say(
            f"deleted scope {deleted_scope}, recreated it as {scope_id} "
            f"and re-imported {len(entries)} records"
        )
        return 0

    return asyncio.run(run())


def reset_artifacts() -> int:
    """Delete the recorded artefacts."""
    if not ARTIFACTS_DIR.exists():
        _say("no artefacts directory")
        return 0
    shutil.rmtree(ARTIFACTS_DIR)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    _say(f"deleted {ARTIFACTS_DIR}")
    return 0


def reset_worktree() -> int:
    """Restore the sample project from the recorded pre-change snapshot."""
    if not BEFORE_SNAPSHOT.exists():
        _say("no pre-change snapshot available; run scripts/run_e2e.py first")
        return 1
    for sub in ("src", "specs", "tests"):
        source = BEFORE_SNAPSHOT / sub
        if not source.exists():
            continue
        target = SAMPLE_DIR / sub
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    _say(f"restored {SAMPLE_DIR} from {BEFORE_SNAPSHOT}")
    return 0


def prune_demo_scopes(
    server_url: str,
    prefixes: tuple[str, ...],
    database: str,
    *,
    storage: str,
    container: str,
    seekdb_dir: Path,
) -> int:
    """Delete the throwaway scopes created by the verification scripts."""

    with urllib.request.urlopen(f"{server_url}/v1/scopes", timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    targets = [
        item for item in payload.get("items", []) if str(item.get("title", "")).startswith(prefixes)
    ]
    if not targets:
        _say("no demo scopes to prune")
        return 0
    tables = _scope_tables(storage, database, container, seekdb_dir)
    schema = detect_schema(
        mode=storage,
        database=database,
        container=container,
        seekdb_dir=seekdb_dir,
    )
    statements = ["SET FOREIGN_KEY_CHECKS=0;"]
    for item in targets:
        scope_id = str(item.get("scope_id"))
        for table in tables:
            statements.append(
                f"DELETE FROM `{schema}`.`{table}` WHERE scope_id = '{scope_id}';"
            )
        _say(f"pruned scope {scope_id} ({item.get('title')})")
    statements.append("SET FOREIGN_KEY_CHECKS=1;")
    output, error = _sql(
        "\n".join(statements),
        storage=storage,
        database=database,
        container=container,
        seekdb_dir=seekdb_dir,
    )
    if error:
        _say(f"prune failed: {error.strip() or output.strip()}")
        return 1
    return 0


def reset_database(database: str, *, storage: str, container: str, seekdb_dir: Path) -> int:
    """Drop and recreate the PowerContext database."""
    if storage == STORAGE_EMBEDDED:
        # The embedded store is a directory; dropping the database means
        # removing it.  The server recreates the schema on the next start.
        if seekdb_dir.exists():
            shutil.rmtree(seekdb_dir)
        _say(
            f"deleted the embedded seekdb data directory {seekdb_dir}; "
            "restart PowerContext Server to rebuild the schema"
        )
        return 0
    output, error = _sql(
        f"DROP DATABASE IF EXISTS {database}; CREATE DATABASE {database} CHARACTER SET utf8mb4;",
        storage=storage,
        database=database,
        container=container,
        seekdb_dir=seekdb_dir,
    )
    if error:
        _say(f"drop failed: {error.strip() or output.strip()}")
        return 1
    _say(f"recreated database {database}; restart PowerContext Server to rebuild the schema")
    return 0


def list_scopes(server_url: str) -> int:
    with urllib.request.urlopen(f"{server_url}/v1/scopes", timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    for item in payload.get("items", []):
        _say(f"{item.get('scope_id')}  {item.get('title')}")
    return 0


def _start_managed_server(
    *,
    storage: str,
    seekdb_dir: Path,
    port: int,
    env_file: str | None,
) -> ServerHandle:
    """Start a PowerContext Server that matches the requested storage mode."""
    if not port_is_free(port):
        raise RuntimeError(f"port {port} is already in use")
    base_env: dict[str, str] = {}
    if env_file:
        base_env = parse_env_file(Path(env_file).expanduser().resolve())
    return start_server(
        storage=storage,
        seekdb_dir=seekdb_dir,
        port=port,
        env_file=ROOT / ".runtime" / "server.env",
        log_path=ROOT / ".runtime" / "server.log",
        home=ROOT / ".runtime" / "home",
        base_env=base_env,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset the local SDD context management state")
    parser.add_argument(
        "--server-url",
        default=None,
        help=(
            "Use an already running PowerContext Server. When omitted the script starts and "
            "stops its own server, so that a reset never depends on a long-running process."
        ),
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--env-file",
        default=None,
        help=(
            "Optional environment file of an existing PowerContext Server. In the embedded mode "
            "the script derives a complete environment itself."
        ),
    )
    parser.add_argument("--scope", default=None, help="Scope title to delete and re-import")
    parser.add_argument("--artifacts", action="store_true", help="Delete the recorded artefacts")
    parser.add_argument("--worktree", action="store_true", help="Restore the pre-change sample")
    parser.add_argument("--database", action="store_true", help="Drop and recreate the database")
    parser.add_argument("--database-name", default=DEFAULT_DATABASE)
    parser.add_argument(
        "--storage",
        choices=(STORAGE_DOCKER, STORAGE_EMBEDDED),
        default=STORAGE_EMBEDDED,
        help="Which store backs PowerContext: a seekdb container or the embedded seekdb.",
    )
    parser.add_argument(
        "--seekdb-dir",
        default=str(DEFAULT_SEEKDB_DIR),
        help="Data directory of the embedded seekdb instance.",
    )
    parser.add_argument("--container", default=MYSQL_CONTAINER)
    parser.add_argument(
        "--prune-demo-scopes",
        action="store_true",
        help="Delete the throwaway scopes created by the verification scripts",
    )
    parser.add_argument("--list-scopes", action="store_true")
    parser.add_argument("--all", action="store_true", help="Scope + artefacts + worktree")
    parser.add_argument("--project", default=str(SAMPLE_DIR))
    args = parser.parse_args()

    project = Path(args.project).resolve()
    seekdb_dir = Path(args.seekdb_dir).expanduser().resolve()
    storage_args = {
        "storage": args.storage,
        "container": args.container,
        "seekdb_dir": seekdb_dir,
    }
    exit_code = 0

    # Dropping the embedded store means deleting the directory, so it has to
    # happen while no server holds it.
    if args.database and args.storage == STORAGE_EMBEDDED:
        exit_code |= reset_database(args.database_name, **storage_args)

    server: ServerHandle | None = None
    server_url = args.server_url
    needs_server = bool(args.scope) or args.prune_demo_scopes or args.list_scopes
    if needs_server and not server_url:
        server = _start_managed_server(
            storage=args.storage,
            seekdb_dir=seekdb_dir,
            port=args.port,
            env_file=args.env_file,
        )
        server_url = f"http://127.0.0.1:{args.port}"

    try:
        if args.list_scopes and server_url:
            exit_code |= list_scopes(server_url)

        if args.all:
            exit_code |= reset_worktree()
            exit_code |= reset_artifacts()
            if args.scope and server_url:
                exit_code |= reset_scope(
                    server_url, args.scope, project, args.database_name, **storage_args
                )
        else:
            if args.worktree:
                exit_code |= reset_worktree()
            if args.artifacts:
                exit_code |= reset_artifacts()
            if args.scope and server_url:
                exit_code |= reset_scope(
                    server_url, args.scope, project, args.database_name, **storage_args
                )

        if args.prune_demo_scopes and server_url:
            exit_code |= prune_demo_scopes(
                server_url,
                ("minimax-sdd-restart-proof-", "minimax-sdd-spec-revision-", "minimax-sdd-reset-demo"),
                args.database_name,
                **storage_args,
            )
            # The API probes left a throwaway "Probe" scope behind; removing it keeps
            # the documented reproduction steps starting from a clean database.
            exit_code |= prune_demo_scopes(
                server_url, ("Probe",), args.database_name, **storage_args
            )
    finally:
        if server is not None:
            server.stop()

    if args.database and args.storage != STORAGE_EMBEDDED:
        exit_code |= reset_database(args.database_name, **storage_args)

    return 0 if exit_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
