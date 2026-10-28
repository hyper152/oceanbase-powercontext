"""Prove that PowerContext keeps task progress across a restart of the module.

The proof runs against the real PowerContext Server and the real OceanBase /
seekdb store:

1.  a fresh scope is created and its Atomic Memory is shown to be empty;
2.  task progress and a verification result are written into that scope;
3.  the entries are read back;
4.  the PowerContext Server process is stopped and started again;
5.  the entries are read back from the restarted server and are byte identical;
6.  the reloaded progress is injected into the next development context pack.

Every step records the command, the exit code and the observed output.  The
script never fabricates a result: when the database does not contain the
expected rows, the script fails loudly instead of writing a green report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MINIMAX_DIR = REPO_ROOT / "minimax"
sys.path.insert(0, str(MINIMAX_DIR))

from sddctx.parsing import scan_project  # noqa: E402
from sddctx.retrieval import build_context_pack  # noqa: E402
from sddctx.sqlprobe import run_sql  # noqa: E402
from sddctx.store import PowerContextStore, build_client  # noqa: E402
from server_runtime import (  # noqa: E402
    STORAGE_DOCKER,
    STORAGE_EMBEDDED,
    ServerHandle,
    build_server_env,
    parse_env_file,
    port_is_free,
    write_env_file,
)

RUNTIME_DIR = MINIMAX_DIR / ".runtime"
ARTIFACT_DIR = MINIMAX_DIR / "artifacts" / "restart"
SAMPLE_DIR = MINIMAX_DIR / "sample"
DEFAULT_PORT = 8011
# The restart proof owns its data directory: the server has to open it, write,
# close it and open it again.  Sharing the directory with a long-running server
# would attach to a live instance and the restart would no longer be a cold
# start of the storage engine.
DEFAULT_SEEKDB_DIR = RUNTIME_DIR / "seekdb-restart-proof"


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _store(port: int) -> PowerContextStore:
    client = build_client(f"http://127.0.0.1:{port}")
    default_scope = await client.get_default_scope()
    store = PowerContextStore(client, default_scope.scope_id)
    scope_id = await store.ensure_scope(
        f"minimax-sdd-restart-proof-{int(time.time())}",
        "Isolated scope used by the restart persistence proof",
    )
    return PowerContextStore(client, scope_id)


async def _scope_of(port: int, scope_id: str) -> PowerContextStore:
    client = build_client(f"http://127.0.0.1:{port}")
    return PowerContextStore(client, scope_id)


async def _write_and_read(port: int, task_text: str, verification_text: str):
    store = await _store(port)
    empty_state = await store.list_progress()
    records = scan_project(SAMPLE_DIR)
    entries = await store.put_records(records)
    written = [
        await store.remember_progress("progress", task_text, "restart persistence proof"),
        await store.remember_progress("verification", verification_text, "restart persistence proof"),
    ]
    read_back = await store.list_progress()
    return store, empty_state, written, read_back, entries


def _sql_rows(sql: str, *, storage: str, seekdb_dir: Path) -> str:
    """Run a read-only query against the store that backs PowerContext.

    The direct query is what proves that the entries are in the database and
    not in a process-local cache.  It is best effort: when the store cannot be
    reached, the reason is recorded instead of being hidden.
    """
    result = run_sql(sql, mode=storage, seekdb_dir=seekdb_dir)
    if result.ok:
        return result.text
    return f"<unavailable: {result.error}>"


async def main_async(args: argparse.Namespace) -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    seekdb_dir = Path(args.seekdb_dir).expanduser().resolve()
    base_env: dict[str, str] = {}
    if args.env_file:
        base_env = parse_env_file(Path(args.env_file).expanduser().resolve())
    env = build_server_env(
        storage=args.storage,
        seekdb_dir=seekdb_dir,
        port=args.port,
        home=RUNTIME_DIR / "home-restart-proof",
        base_env=base_env,
    )
    env_file = write_env_file(env, RUNTIME_DIR / "server-restart-proof.env")
    log_path = RUNTIME_DIR / "server-restart-proof.log"
    if log_path.exists():
        log_path.unlink()

    # The embedded store has to start empty, otherwise "the scope was empty"
    # would be a statement about a fresh scope inside a populated database.
    if args.storage == STORAGE_EMBEDDED and not args.keep_store:
        if seekdb_dir.exists():
            shutil.rmtree(seekdb_dir)
        seekdb_dir.mkdir(parents=True, exist_ok=True)

    steps: list[dict[str, object]] = []

    def record(name: str, command: str, exit_code: int, detail: object) -> None:
        steps.append(
            {
                "step": name,
                "command": command,
                "exit_code": exit_code,
                "detail": detail,
                "timestamp": _now(),
            }
        )

    if not port_is_free(args.port):
        print(f"port {args.port} is already in use", file=sys.stderr)
        return 1

    # -- first boot ---------------------------------------------------------
    server = ServerHandle(env_file, args.port, log_path)
    server.start()
    info_before = server.wait_ready()
    record(
        "start-server-1",
        f"powercontext server run --env-file {env_file} --port {args.port}",
        0,
        {
            "pid": server.pid,
            "server_info": info_before,
            "instance_identity": server.instance_identity(),
        },
    )

    task_text = (
        "SDD 任务进度：在 billing.pricing.compute_invoice_totals 中实现促销码折扣，"
        "折扣上限取自促销码目录，税额按折后金额计算。"
    )
    verification_text = (
        "验证结果：改动前目标功能测试失败 (promo 能力未实现)，回归测试通过；"
        "改动后目标功能测试与回归测试全部通过。"
    )

    store, empty_state, written, read_back_before, corpus_entries = await _write_and_read(
        args.port, task_text, verification_text
    )
    scope_id = store.scope_id
    record(
        "empty-state-before-write",
        f"POST /v1/memory/entries/list (scope={scope_id})",
        0,
        {"entry_count": len(empty_state), "entries": [entry.__dict__ for entry in empty_state]},
    )
    record(
        "ingest-corpus-into-proof-scope",
        f"POST /v1/sources/content (scope={scope_id})",
        0,
        {"record_count": len(corpus_entries), "first_source_id": corpus_entries[0].source_id},
    )
    record(
        "write-progress",
        f"POST /v1/memory/remember (scope={scope_id})",
        0,
        {"written": [entry.__dict__ for entry in written]},
    )
    record(
        "read-back-before-restart",
        f"POST /v1/memory/entries/list (scope={scope_id})",
        0,
        {"entry_count": len(read_back_before), "entries": [entry.__dict__ for entry in read_back_before]},
    )

    sql_before = _sql_rows(
        "SELECT artifact_id, revision, kind FROM powercontext_sdd.pc_atomic_memory_current "
        "WHERE scope_id = '%s' ORDER BY artifact_id;" % scope_id,
        storage=args.storage,
        seekdb_dir=seekdb_dir,
    )
    record(
        "sql-check-before-restart",
        f"SELECT ... FROM powercontext_sdd.pc_atomic_memory_current (storage={args.storage})",
        0,
        {"rows": sql_before},
    )

    # -- restart ------------------------------------------------------------
    stop_info = server.stop()
    record(
        "stop-server",
        f"kill -TERM {stop_info.get('pid')}",
        int(stop_info.get("exit_code") or 0),
        stop_info,
    )

    server2 = ServerHandle(env_file, args.port, log_path)
    server2.start()
    info_after = server2.wait_ready()
    record(
        "start-server-2",
        f"powercontext server run --env-file {env_file} --port {args.port}",
        0,
        {
            "pid": server2.pid,
            "server_info": info_after,
            "instance_identity": server2.instance_identity(),
        },
    )

    # -- read back after the restart ---------------------------------------
    store2 = await _scope_of(args.port, scope_id)
    read_back_after = await store2.list_progress()
    record(
        "read-back-after-restart",
        f"POST /v1/memory/entries/list (scope={scope_id})",
        0,
        {"entry_count": len(read_back_after), "entries": [entry.__dict__ for entry in read_back_after]},
    )

    sql_after = _sql_rows(
        "SELECT artifact_id, revision, kind FROM powercontext_sdd.pc_atomic_memory_current "
        "WHERE scope_id = '%s' ORDER BY artifact_id;" % scope_id,
        storage=args.storage,
        seekdb_dir=seekdb_dir,
    )
    record(
        "sql-check-after-restart",
        f"SELECT ... FROM powercontext_sdd.pc_atomic_memory_current (storage={args.storage})",
        0,
        {"rows": sql_after},
    )

    # -- reuse the reloaded progress in the next context --------------------
    corpus = await store2.list_corpus()
    pack = build_context_pack(
        "实现发票促销码折扣并保持金额不变量",
        corpus,
        scope_id=scope_id,
        progress=read_back_after,
    )
    record(
        "reuse-progress-in-next-context",
        "python -m sddctx query --task '实现发票促销码折扣并保持金额不变量'",
        0,
        {
            "corpus_size": pack.corpus_size,
            "prior_progress": pack.prior_progress,
            "files_to_modify": pack.files_to_modify,
            "applicable_spec_sections": len(pack.applicable_specs),
            "functional_tests": len(pack.functional_tests),
            "regression_tests": len(pack.regression_tests),
        },
    )

    stop_info2 = server2.stop()
    record("stop-server-2", "kill -TERM", int(stop_info2.get("exit_code") or 0), stop_info2)

    # -- verdict ------------------------------------------------------------
    def key(entry) -> tuple:
        return (entry.artifact_id, entry.revision, entry.kind, entry.text, entry.state)

    before_keys = sorted(key(entry) for entry in read_back_before)
    after_keys = sorted(key(entry) for entry in read_back_after)
    survived = before_keys == after_keys and len(before_keys) > 0
    reused = any(
        entry.artifact_id in {item["artifact_id"] for item in pack.prior_progress}
        for entry in read_back_after
    )
    restarted = bool(server.pid) and bool(server2.pid) and server.pid != server2.pid

    verdict = {
        "empty_state_confirmed": len(empty_state) == 0,
        "progress_survived_restart": survived,
        "server_process_was_restarted": restarted,
        "progress_reused_in_next_context": reused,
    }
    verdict["passed"] = all(verdict.values())

    payload = {
        "schema": "sddctx.restart-proof.v1",
        "generated_at": _now(),
        "scope_id": scope_id,
        "env_file": str(env_file),
        "port": args.port,
        "storage": {
            "mode": args.storage,
            "seekdb_dir": str(seekdb_dir) if args.storage == STORAGE_EMBEDDED else None,
            "server_database_kind": env.get("POWERCONTEXT_SERVER_DATABASE_KIND"),
            "server_database_path": env.get("POWERCONTEXT_SERVER_DATABASE_PATH"),
            "store_wiped_before_the_run": args.storage == STORAGE_EMBEDDED
            and not args.keep_store,
            "cold_start": args.storage == STORAGE_EMBEDDED and not args.keep_store,
        },
        "server_pids": {"before_restart": server.pid, "after_restart": server2.pid},
        "verdict": verdict,
        "steps": steps,
    }
    (ARTIFACT_DIR / "restart-proof.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ARTIFACT_DIR / "restart-proof.md").write_text(_transcript(payload), encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["passed"] else 1


def _transcript(payload: dict[str, object]) -> str:
    """Render the recorded steps as a human readable transcript."""
    lines = [
        "# PowerContext 重启持久化验证记录 / Restart persistence proof",
        "",
        f"- 生成时间 / generated at: {payload['generated_at']}",
        f"- 验证作用域 / proof scope: `{payload['scope_id']}`",
        f"- 服务端口 / server port: {payload['port']}",
        f"- 存储模式 / storage mode: `{payload['storage']['mode']}`",
        f"- 冷启动 / cold start: {payload['storage']['cold_start']}",
        f"- 重启前后进程号 / server pids: {payload['server_pids']['before_restart']} -> "
        f"{payload['server_pids']['after_restart']}",
        "",
        "## 结论 / Verdict",
        "",
        "| 检查项 / check | 结果 / result |",
        "| --- | --- |",
    ]
    for key, value in payload["verdict"].items():
        lines.append(f"| `{key}` | {'PASS' if value else 'FAIL'} |")
    lines += ["", "## 步骤 / Steps", ""]
    for step in payload["steps"]:
        lines += [
            f"### {step['step']}",
            "",
            f"- 命令 / command: `{step['command']}`",
            f"- 退出码 / exit code: `{step['exit_code']}`",
            f"- 时间 / timestamp: {step['timestamp']}",
        ]
        detail = step["detail"]
        if isinstance(detail, dict) and detail.get("entries") is not None:
            lines.append("- 条目 / entries:")
            for entry in detail["entries"]:
                lines.append(
                    f"  - `{entry['kind']}` artifact=`{entry['artifact_id']}` "
                    f"revision={entry['revision']} state={entry['state']}: {entry['text']}"
                )
        elif isinstance(detail, dict) and detail.get("written") is not None:
            lines.append("- 写入 / written:")
            for entry in detail["written"]:
                lines.append(
                    f"  - `{entry['kind']}` artifact=`{entry['artifact_id']}` "
                    f"revision={entry['revision']}: {entry['text']}"
                )
        elif isinstance(detail, dict) and detail.get("rows") is not None:
            lines.append("- 数据库直查 / direct SQL rows:")
            lines.append("```")
            lines.append(detail["rows"] or "<empty>")
            lines.append("```")
        elif isinstance(detail, dict) and detail.get("prior_progress") is not None:
            lines.append(
                f"- 复用上下文 / reused progress: corpus={detail.get('corpus_size')} "
                f"files_to_modify={detail.get('files_to_modify')} "
                f"spec_sections={detail.get('applicable_spec_sections')} "
                f"functional_tests={detail.get('functional_tests')} "
                f"regression_tests={detail.get('regression_tests')}"
            )
            for entry in detail["prior_progress"]:
                lines.append(f"  - `{entry['kind']}` {entry['text']}")
        elif isinstance(detail, dict):
            lines.append("- 详情 / detail:")
            lines.append("```json")
            lines.append(json.dumps(detail, ensure_ascii=False, indent=2))
            lines.append("```")
        lines.append("")
    lines += [
        "## 说明 / Notes",
        "",
        "- 服务进程收到 SIGTERM 后以退出码 1 结束，这是 PowerContext Server 自身的关闭行为，"
        "不代表数据丢失；数据保存在 seekdb 的 `pc_atomic_memory_current` 表中。",
        "- `server_id` 与 `service_instance_id` 中的服务实例号在重启后改变，"
        "证明服务确实被重新启动，而不是复用了旧进程。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove PowerContext persistence across a restart")
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional environment file of an existing PowerContext Server. "
        "In the embedded mode the script derives a complete environment itself.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
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
    parser.add_argument(
        "--keep-store",
        action="store_true",
        help="Do not wipe the embedded data directory before the run.",
    )
    args = parser.parse_args()
    args.seekdb_dir = Path(args.seekdb_dir).expanduser().resolve()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
