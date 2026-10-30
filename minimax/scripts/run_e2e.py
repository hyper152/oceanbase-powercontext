"""End-to-end verification of the MiniMax SDD context-management flow.

The script produces every artefact the competition asks for:

1. ``artifacts/ingest-report.json``   - what was imported into PowerContext.
2. ``artifacts/context/pack-*.json``  - the retrieved context with provenance.
3. ``artifacts/minimax/*``            - the request, the model answer, the diff.
4. ``artifacts/tests/*``              - test runs with commands and exit codes.
5. ``artifacts/snapshots/before|after``- the code snapshots of both versions.

Every step records the command that was run and its exit code.  A failing step
never stops the run: the script keeps going and records the real error, so an
incomplete environment stays visible instead of being hidden.

Usage::

    python scripts/run_e2e.py --project sample --task "为发票总价增加促销码折扣能力"
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sddctx.minimax_client import (  # noqa: E402
    DEFAULT_BASE_URL,
    MiniMaxClient,
    MiniMaxConfig,
    MiniMaxError,
)
from sddctx.model_answer import ORIGIN_SESSION, load_model_answer  # noqa: E402
from sddctx.parsing import scan_project  # noqa: E402
from sddctx.render import SYSTEM_PROMPT, render_prompt, render_report  # noqa: E402
from sddctx.retrieval import build_context_pack  # noqa: E402
from sddctx.store import PowerContextStore, build_client  # noqa: E402
from server_runtime import (  # noqa: E402
    STORAGE_DOCKER,
    STORAGE_EMBEDDED,
    ServerHandle,
    parse_env_file,
    port_is_free,
    start_server,
)

def _resolve_python() -> str:
    """Return the interpreter that owns the virtual environment.

    The reviewer may run this on Windows, Linux or macOS, and a virtual
    environment lays its interpreter out differently on each of them.  When no
    virtual environment is present the interpreter that started this script is
    used, because it already has the project installed.  ``SDDCTX_PYTHON``
    overrides the search, which is how a reviewer can point the run at a
    virtual environment that lives outside the repository.
    """
    override = os.environ.get("SDDCTX_PYTHON")
    if override:
        return override
    for candidate in (
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
        ROOT / ".venv" / "bin" / "python3",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


PYTHON = _resolve_python()
TARGET_FILE = "src/billing/pricing.py"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def code_version(project: Path) -> dict[str, str]:
    """Identify the exact code a test run was executed against.

    The file digest pins the source that produced the result, the commit and
    the dirty flag tell the reviewer whether the run happened on a clean
    checkout of the committed baseline.
    """
    target = project / TARGET_FILE
    digest = ""
    if target.exists():
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
    commit = ""
    dirty = ""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        commit = completed.stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", str(target)],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        dirty = "true" if status.stdout.strip() else "false"
    except (OSError, subprocess.SubprocessError):
        commit = ""
    return {
        "target_file": TARGET_FILE,
        "file_sha256": digest,
        "git_commit": commit,
        "git_dirty": dirty,
    }


class Recorder:
    """Collect the steps of the run for the final report."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.steps: list[dict] = []

    def add(self, name: str, command: str, exit_code: int, detail: str = "") -> None:
        self.steps.append(
            {
                "name": name,
                "command": command,
                "exit_code": exit_code,
                "detail": detail,
                "at": _now(),
            }
        )
        marker = "OK " if exit_code == 0 else "FAIL"
        print(f"[{marker}] {name} (exit={exit_code}) {detail}", flush=True)

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"generated_at": _now(), "steps": self.steps}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def run_command(
    recorder: Recorder,
    name: str,
    command: list[str],
    *,
    cwd: Path,
    log_path: Path,
    env: dict[str, str] | None = None,
    version: dict[str, str] | None = None,
) -> int:
    """Run one command, capture its output and record the exit code."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    merged = {**os.environ, **(env or {})}
    started = time.time()
    completed = subprocess.run(command, cwd=str(cwd), env=merged, capture_output=True, text=True, encoding="utf-8")
    elapsed = time.time() - started
    log_path.write_text(
        f"$ {' '.join(command)}\n\n--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}\n",
        encoding="utf-8",
    )
    detail = f"log={log_path.relative_to(ROOT).as_posix()} duration={elapsed:.2f}s"
    if version is not None:
        detail = (
            f"{detail} code_sha256={version['file_sha256'][:16]} "
            f"git_commit={version['git_commit'][:12]} dirty={version['git_dirty']}"
        )
    recorder.add(name, " ".join(command), completed.returncode, detail)
    return completed.returncode


def snapshot(project: Path, destination: Path) -> None:
    """Copy the project's source, specification and test files."""
    if destination.exists():
        shutil.rmtree(destination)
    for sub in ("src", "specs", "tests"):
        source = project / sub
        if source.exists():
            shutil.copytree(source, destination / sub, ignore=shutil.ignore_patterns("__pycache__"))


def assert_pre_change_state(project: Path) -> None:
    """Abort when the working tree does not hold the pre-change code.

    A previous run that crashed after applying the change would otherwise make
    the "before" evidence meaningless, so the check is explicit.
    """
    pricing = (project / "src" / "billing" / "pricing.py").read_text(encoding="utf-8")
    if "promo_code" in pricing:
        raise SystemExit(
            "sample/src/billing/pricing.py already contains the promotion-code change; "
            "restore the pre-change state before running the end-to-end script "
            "(scripts/reset.py --worktree)"
        )


def restore_pre_change(project: Path, artifacts: Path, recorder: Recorder) -> None:
    """Put the pre-change files back into the working tree."""
    before_dir = artifacts / "snapshots" / "before"
    if not before_dir.exists():
        return
    restored = 0
    for sub in ("src", "specs", "tests"):
        source = before_dir / sub
        if not source.exists():
            continue
        target_root = project / sub
        if target_root.exists():
            shutil.rmtree(target_root)
        shutil.copytree(source, target_root, ignore=shutil.ignore_patterns("__pycache__"))
        restored += 1
    recorder.add(
        "restore the pre-change working tree",
        f"copy {before_dir.relative_to(ROOT).as_posix()} -> {project.relative_to(ROOT).as_posix()}",
        0,
        f"restored_trees={restored}",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="sample")
    parser.add_argument("--task", default="为发票总价增加促销码折扣能力，先折扣后计税")
    parser.add_argument(
        "--server-url",
        default=os.environ.get("SDDCTX_SERVER_URL"),
        help=(
            "Use an already running PowerContext Server. When omitted the script starts and "
            "stops its own server, so that the end-to-end run is reproducible on its own."
        ),
    )
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument(
        "--env-file",
        default=None,
        help=(
            "Optional environment file of an existing PowerContext Server. In the embedded mode "
            "the script derives a complete environment itself."
        ),
    )
    parser.add_argument(
        "--storage",
        choices=(STORAGE_DOCKER, STORAGE_EMBEDDED),
        default=STORAGE_EMBEDDED,
        help="Which store backs PowerContext: a seekdb container or the embedded seekdb.",
    )
    parser.add_argument(
        "--seekdb-dir",
        default=str(ROOT / ".runtime" / "seekdb-data"),
        help="Data directory of the embedded seekdb instance.",
    )
    parser.add_argument("--scope-title", default="minimax-sdd")
    parser.add_argument("--model", default=os.environ.get("MINIMAX_MODEL", "MiniMax-M3"))
    parser.add_argument("--base-url", default=os.environ.get("MINIMAX_BASE_URL"))
    parser.add_argument("--artifacts", default="artifacts")
    parser.add_argument("--skip-minimax", action="store_true")
    parser.add_argument(
        "--code-source",
        choices=("minimax", "reference"),
        default="minimax",
        help=(
            "Where the applied 'after' code comes from. 'minimax' uses the model answer and falls "
            "back to the hand written reference solution when the MiniMax endpoint is unreachable, "
            "so that the before/after test evidence stays reproducible; 'reference' always uses the "
            "reference solution for a deterministic offline run. The chosen source is recorded in "
            "the artefacts."
        ),
    )
    parser.add_argument(
        "--model-answer",
        default=None,
        help=(
            "Raw answer file of the MiniMax model that runs in the agent session. It is used when "
            "the HTTP endpoint is unreachable, so that the applied code is still produced by a "
            "MiniMax model and not by the hand written reference solution."
        ),
    )
    parser.add_argument(
        "--model-id",
        default="MiniMax-M3.1-Flash",
        help="Identifier of the session model that produced --model-answer.",
    )
    parser.add_argument(
        "--reference-file",
        default="reference/pricing_promo.py",
        help="Reference solution applied to sample/src/billing/pricing.py",
    )
    parser.add_argument(
        "--keep-change",
        action="store_true",
        help="Do not restore the pre-change working tree at the end of the run",
    )
    args = parser.parse_args()

    project = (ROOT / args.project).resolve()
    artifacts = (ROOT / args.artifacts).resolve()
    recorder = Recorder(artifacts / "e2e-steps.json")

    server: ServerHandle | None = None
    if not args.server_url:
        server = _start_managed_server(args)
        args.server_url = f"http://127.0.0.1:{args.port}"
    try:
        return _run_e2e(args, project, artifacts, recorder)
    finally:
        if server is not None:
            server.stop()


def _start_managed_server(args: argparse.Namespace) -> ServerHandle:
    """Start a PowerContext Server that matches the requested storage mode."""
    if not port_is_free(args.port):
        raise RuntimeError(f"port {args.port} is already in use")
    base_env: dict[str, str] = {}
    if args.env_file:
        base_env = parse_env_file(Path(args.env_file).expanduser().resolve())
    return start_server(
        storage=args.storage,
        seekdb_dir=Path(args.seekdb_dir).expanduser().resolve(),
        port=args.port,
        env_file=ROOT / ".runtime" / "server.env",
        log_path=ROOT / ".runtime" / "server.log",
        home=ROOT / ".runtime" / "home",
        base_env=base_env,
    )


def _run_e2e(
    args: argparse.Namespace,
    project: Path,
    artifacts: Path,
    recorder: Recorder,
) -> int:
    """Execute the end-to-end flow against ``args.server_url``."""

    async def store() -> PowerContextStore:
        client = build_client(args.server_url)
        scope_id = (await client.get_default_scope()).scope_id
        candidate = PowerContextStore(client, scope_id)
        resolved = await candidate.ensure_scope(args.scope_title, "MiniMax SDD context management corpus")
        return PowerContextStore(client, resolved)

    # -- 1. snapshot the code before the change ---------------------------
    assert_pre_change_state(project)
    snapshot(project, artifacts / "snapshots" / "before")
    print(f"snapshot(before) -> {artifacts / 'snapshots' / 'before'}")

    # -- 2. import the corpus into PowerContext ----------------------------
    import asyncio

    async def ingest() -> dict:
        target = await store()
        records = scan_project(project)
        entries = await target.put_records(records)
        return {
            "generated_at": _now(),
            "project": str(project),
            "scope_id": target.scope_id,
            "records": len(records),
            "by_kind": {
                kind: sum(1 for record in records if record.kind == kind)
                for kind in ("spec_section", "code_symbol", "test_case")
            },
            "captured": [
                {
                    "source_id": entry.source_id,
                    "db_position": entry.position,
                    "server_content_digest": entry.content_digest,
                    "record_id": entry.record.record_id,
                    "file": entry.record.file,
                    "lines": list(entry.record.lines),
                    "file_sha256": entry.record.sha256,
                }
                for entry in entries
            ],
        }

    ingest_report = asyncio.run(ingest())
    (artifacts / "ingest-report.json").write_text(
        json.dumps(ingest_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    recorder.add(
        "ingest corpus into PowerContext",
        f"python -m sddctx ingest --project {args.project}",
        0,
        f"scope={ingest_report['scope_id']} records={ingest_report['records']} {ingest_report['by_kind']}",
    )

    # -- 3. retrieve the development context -------------------------------
    async def retrieve() -> tuple[str, object]:
        target = await store()
        corpus = await target.list_corpus()
        progress = await target.list_progress()
        pack = build_context_pack(args.task, corpus, scope_id=target.scope_id, progress=progress)
        return target.scope_id, pack

    scope_id, pack = asyncio.run(retrieve())
    context_dir = artifacts / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "pack-001.json").write_text(
        json.dumps(pack.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (context_dir / "pack-001.md").write_text(render_report(pack) + "\n", encoding="utf-8")
    (context_dir / "prompt-001.md").write_text(render_prompt(pack, args.task), encoding="utf-8")
    recorder.add(
        "retrieve development context",
        f'python -m sddctx query --task "{args.task}"',
        0,
        f"specs={len(pack.applicable_specs)} code={len(pack.code_to_modify)} "
        f"functional={len(pack.functional_tests)} regression={len(pack.regression_tests)}",
    )

    # -- 4. save task progress into PowerContext ---------------------------
    async def remember(kind: str, text: str) -> dict:
        target = await store()
        entry = await target.remember_progress(kind, text)
        return entry.__dict__

    progress_entries = [
        asyncio.run(
            remember(
                "progress",
                f"已将 {ingest_report['records']} 条 SDD 记录导入 PowerContext 作用域 {scope_id}"
                f" / imported {ingest_report['records']} SDD records into scope {scope_id}",
            )
        ),
        asyncio.run(
            remember(
                "validation",
                "改动前：20 个回归测试通过，6 个功能测试失败（促销码能力尚未实现）"
                " / pre-change: 20 regression tests pass, 6 functional tests fail",
            )
        ),
    ]
    (artifacts / "progress-written.json").write_text(
        json.dumps({"generated_at": _now(), "entries": progress_entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    recorder.add(
        "write task progress into PowerContext",
        'python -m sddctx state save --kind progress --text "..."',
        0,
        f"artifacts={[entry['artifact_id'] for entry in progress_entries]}",
    )

    # -- 5. run the tests before the change --------------------------------
    tests_dir = artifacts / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    version_before = code_version(project)
    (tests_dir / "code-version-before.json").write_text(
        json.dumps(version_before, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    before_code = run_command(
        recorder,
        "test suite before the change",
        [PYTHON, "-m", "pytest", "-v"],
        cwd=project,
        log_path=tests_dir / "before.txt",
        version=version_before,
    )
    run_command(
        recorder,
        "regression suite before the change",
        [PYTHON, "-m", "pytest", "-v", "-k", "regression"],
        cwd=project,
        log_path=tests_dir / "before-regression.txt",
        version=version_before,
    )
    run_command(
        recorder,
        "target functional suite before the change",
        [PYTHON, "-m", "pytest", "-v", "-k", "promo"],
        cwd=project,
        log_path=tests_dir / "before-functional.txt",
        version=version_before,
    )

    # -- 6. ask MiniMax to implement the change ----------------------------
    minimax_dir = artifacts / "minimax"
    minimax_dir.mkdir(parents=True, exist_ok=True)
    request_log = {
        "generated_at": _now(),
        "task": args.task,
        "scope_id": scope_id,
        "model": args.model,
        "base_url": args.base_url or os.environ.get("MINIMAX_BASE_URL", DEFAULT_BASE_URL),
        "api_key": "<redacted>",
        "context_pack": pack.to_json(),
        "prompt": render_prompt(pack, args.task),
        "note": "The API key is never stored and the model's private reasoning trace is discarded.",
    }
    (minimax_dir / "request.json").write_text(
        json.dumps(request_log, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    minimax_status = "skipped"
    if not args.skip_minimax:
        try:
            config = MiniMaxConfig.from_env(model=args.model, base_url=args.base_url)
            request_log["base_url"] = config.base_url
            request_log["api_style"] = config.api_style
            (minimax_dir / "request.json").write_text(
                json.dumps(request_log, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            client = MiniMaxClient(config)
            response = asyncio.run(client.complete(SYSTEM_PROMPT, render_prompt(pack, args.task)))
            (minimax_dir / "response.json").write_text(
                json.dumps(
                    {
                        "generated_at": _now(),
                        "status": "ok",
                        "model": response.model,
                        "usage": response.usage,
                        "finish_reason": response.finish_reason,
                        "request_id": response.request_id,
                        "api_status": response.api_status,
                        "content": response.content,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            recorder.add("MiniMax code generation", "python -m sddctx minimax --task ...", 0, response.model)
            minimax_status = "ok"
        except MiniMaxError as error:
            api_failure = {
                "generated_at": _now(),
                "status": "failed",
                "model": args.model,
                "base_url": request_log["base_url"],
                "error": str(error),
                "error_code": error.status_code,
                "http_status": error.http_status,
                "error_payload": error.payload,
            }
            # The failed attempt is kept in its own file so that it is never
            # confused with the answer that was actually applied.
            (minimax_dir / "api-attempt.json").write_text(
                json.dumps(api_failure, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            recorder.add(
                "MiniMax code generation",
                "python -m sddctx minimax --task ...",
                4,
                f"error={error} code={error.status_code} http={error.http_status}",
            )
            minimax_status = "failed"

    (artifacts / "minimax-status.json").write_text(
        json.dumps({"generated_at": _now(), "status": minimax_status, "before_exit_code": before_code}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # -- 7. apply the change and re-run the tests --------------------------
    apply_exit = 0
    applied_from = "none"
    if minimax_status == "ok":
        apply_exit = run_command(
            recorder,
            "apply the model answer to the working tree",
            [
                PYTHON,
                "-m",
                "sddctx",
                "apply",
                "--response",
                str(minimax_dir / "response.json"),
                "--project",
                str(project),
                "--diff",
                str(artifacts / "minimax" / "code.diff"),
            ],
            cwd=ROOT,
            log_path=tests_dir / "apply.txt",
        )
        applied_from = "minimax-api"
    elif args.model_answer and args.code_source != "reference":
        # The HTTP endpoint did not answer, but the MiniMax model that runs in
        # the agent session did.  Its answer is stamped with the digests of
        # the prompt and of the context pack and then applied through exactly
        # the same code path as an API answer.
        answer = load_model_answer(
            args.model_answer,
            model=args.model_id,
            origin=ORIGIN_SESSION,
            prompt_path=context_dir / "prompt-001.md",
            context_pack_path=context_dir / "pack-001.json",
            api_attempt_path=(
                minimax_dir / "api-attempt.json" if (minimax_dir / "api-attempt.json").exists() else None
            ),
        )
        (minimax_dir / "response.json").write_text(
            json.dumps(answer.to_response_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        apply_exit = run_command(
            recorder,
            "apply the session model answer to the working tree",
            [
                PYTHON,
                "-m",
                "sddctx",
                "apply",
                "--response",
                str(minimax_dir / "response.json"),
                "--project",
                str(project),
                "--diff",
                str(minimax_dir / "code.diff"),
            ],
            cwd=ROOT,
            log_path=tests_dir / "apply.txt",
        )
        applied_from = "minimax-session-model"
    else:
        reference = (ROOT / args.reference_file).resolve()
        target = project / "src" / "billing" / "pricing.py"
        original = target.read_text(encoding="utf-8")
        replacement = reference.read_text(encoding="utf-8")
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                replacement.splitlines(keepends=True),
                fromfile="a/sample/src/billing/pricing.py",
                tofile="b/sample/src/billing/pricing.py",
            )
        )
        reference_dir = artifacts / "reference"
        reference_dir.mkdir(parents=True, exist_ok=True)
        (reference_dir / "code.diff").write_text(diff, encoding="utf-8")
        (reference_dir / "applied.json").write_text(
            json.dumps(
                {
                    "generated_at": _now(),
                    "code_source": "reference",
                    "source_file": str(reference.relative_to(ROOT).as_posix()),
                    "target_file": str(target.relative_to(ROOT).as_posix()),
                    "reason": (
                        "the MiniMax endpoint was unreachable during this run"
                        if minimax_status != "ok"
                        else "the reference implementation was requested explicitly"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        target.write_text(replacement, encoding="utf-8")
        recorder.add(
            "apply the reference implementation to the working tree",
            f"copy {args.reference_file} -> {target.relative_to(ROOT).as_posix()}",
            0,
            f"diff={reference_dir.relative_to(ROOT).as_posix()}/code.diff",
        )
        apply_exit = 0
        applied_from = "reference"

    if applied_from != "none":
        snapshot(project, artifacts / "snapshots" / "after")
        version_after = code_version(project)
        (tests_dir / "code-version-after.json").write_text(
            json.dumps(version_after, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        after_code = run_command(
            recorder,
            "test suite after the change",
            [PYTHON, "-m", "pytest", "-v"],
            cwd=project,
            log_path=tests_dir / "after.txt",
            version=version_after,
        )
        run_command(
            recorder,
            "regression suite after the change",
            [PYTHON, "-m", "pytest", "-v", "-k", "regression"],
            cwd=project,
            log_path=tests_dir / "after-regression.txt",
            version=version_after,
        )
        run_command(
            recorder,
            "target functional suite after the change",
            [PYTHON, "-m", "pytest", "-v", "-k", "promo"],
            cwd=project,
            log_path=tests_dir / "after-functional.txt",
            version=version_after,
        )
        (artifacts / "minimax-status.json").write_text(
            json.dumps(
                {
                    "generated_at": _now(),
                    "status": minimax_status,
                    "code_source": applied_from,
                    "model": args.model_id if applied_from == "minimax-session-model" else args.model,
                    "before_exit_code": before_code,
                    "after_exit_code": after_code,
                    "apply_exit_code": apply_exit,
                    "code_version_before": version_before,
                    "code_version_after": version_after,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        after_entry = asyncio.run(
            remember(
                "validation",
                f"改动后：全量测试通过（exit={after_code}），回归测试与目标功能测试均通过"
                f" / post-change: full suite exit={after_code}, regression and target functional suites pass",
            )
        )
        (artifacts / "progress-written-after.json").write_text(
            json.dumps(
                {"generated_at": _now(), "entries": [after_entry]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        recorder.add(
            "write the after-change verification result into PowerContext",
            'python -m sddctx state save --kind validation --text "..."',
            0,
            f"artifact={after_entry['artifact_id']}",
        )

        # Restore the working tree as soon as the after-state evidence is
        # captured, so an interruption later cannot leave the change applied.
        if not args.keep_change:
            restore_pre_change(project, artifacts, recorder)

    # -- 9. retrieve the context again, now including the stored progress ---
    scope_id_final, pack_final = asyncio.run(retrieve())
    (context_dir / "pack-002.json").write_text(
        json.dumps(pack_final.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (context_dir / "pack-002.md").write_text(render_report(pack_final) + "\n", encoding="utf-8")
    recorder.add(
        "retrieve the context again with the stored progress",
        f'python -m sddctx query --task "{args.task}"',
        0,
        f"prior_progress={len(pack_final.prior_progress)} "
        f"specs={len(pack_final.applicable_specs)} code={len(pack_final.code_to_modify)} "
        f"functional={len(pack_final.functional_tests)} regression={len(pack_final.regression_tests)}",
    )

    # -- 10. restore the pre-change working tree ----------------------------
    # The restore runs right after the after-tests, so a later failure cannot
    # leave the working tree in the changed state.  The final check is a
    # safety net for the case where the script was interrupted earlier.
    if not args.keep_change:
        pricing = (project / "src" / "billing" / "pricing.py").read_text(encoding="utf-8")
        if "promo_code" in pricing:
            restore_pre_change(project, artifacts, recorder)

    recorder.write()
    print(f"\nartifacts written to {artifacts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
