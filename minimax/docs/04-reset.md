# 04 · 重置方法 (Reset)

本方案的所有状态都落在三个地方：**仓库工作区**、**PowerContext / seekdb 数据库**、
**`minimax/artifacts/` 产物目录**。下面的命令按从轻到重的顺序列出。

所有命令在仓库根目录执行（`minimax/` 的父目录）。

> **解释器**：本文命令里的 `python` 指虚拟环境里的解释器。先激活它：
> `. minimax/.venv/bin/activate`（Linux / macOS）、
> `. minimax/.venv/Scripts/activate`（Windows Git Bash）、
> `minimax\.venv\Scripts\activate`（Windows PowerShell / CMD）。
> 激活后 `python` 与 `powercontext` 都在 `PATH` 上，命令无需再写完整路径。
>
> **存储模式**：脚本默认按**嵌入式 seekdb**（`--storage embedded`，免 Docker）工作。
> 使用容器模式时改成 `--storage docker`（并按需加 `--env-file`）。
> 数据目录默认 `minimax/.runtime/seekdb-data`，可用 `--seekdb-dir` 覆盖。
>
> **服务生命周期**：`--server-url` 默认为空，此时脚本会自行启动一个
> PowerContext Server（按 `--storage` 派生环境）、跑完再关掉，
> 因此重置不需要一个已经跑着的服务。
>
> **嵌入式模式的提交语义**：seekdb 的握手不返回 autocommit 状态，
> 直连数据库的写操作必须显式 `COMMIT`，否则会在句柄关闭时被回滚。
> `sddctx/sqlprobe.py` 已统一补上这一步——早期版本正是在这里让
> 「删除作用域」变成了空操作。

---

## 1. 还原样例项目到改动前状态（最常用）

端到端脚本在运行结束时会自动还原工作区。手动还原：

```bash
cd minimax
python -m sddctx apply --help   # 查看用法
# 直接用快照覆盖：
rm -rf sample/src sample/specs sample/tests
cp -r artifacts/snapshots/before/src artifacts/snapshots/before/specs \
      artifacts/snapshots/before/tests sample/
```

核对（应输出 `no differences`）：

```bash
diff -r artifacts/snapshots/before/src sample/src
diff -r artifacts/snapshots/before/specs sample/specs
diff -r artifacts/snapshots/before/tests sample/tests
```

期望结果：改动前的 6 个功能测试失败、20 个回归测试通过：

```bash
cd sample && python -m pytest -q
# 6 failed, 20 passed
```

---

## 2. 清空产物目录

```bash
cd minimax
rm -rf artifacts
mkdir -p artifacts
```

产物会由 `scripts/run_e2e.py`、`scripts/prove_restart_persistence.py`、
`scripts/prove_spec_revision.py` 重新生成。

---

## 3. 重置 PowerContext 作用域（只清语料与进度，保留数据库）

作用域是 PowerContext 里的一个命名空间。PowerContext **没有提供删除作用域的 HTTP 端点**
（`/v1/scopes/{scope_id}` 只支持 `GET` 与 `PUT`），因此重置直接在存储层完成：
删除该作用域在所有带 `scope_id` 列的表中的行，然后重新导入。

```bash
cd minimax
# 查看现有作用域
python scripts/reset.py --list-scopes

# 删除作用域并重新导入
python scripts/reset.py --scope minimax-sdd
# deleted scope scp_xxxxxxxx, recreated it as scp_yyyyyyyy and re-imported 47 records

# 清理验证脚本产生的临时作用域
python scripts/reset.py --prune-demo-scopes
```

验证脚本每次运行会新建一个带时间戳的临时作用域（`minimax-sdd-restart-proof-<ts>`、
`minimax-sdd-spec-revision-<ts>`），用 `--prune-demo-scopes` 一次性清掉；
该命令同时清掉接口探测时留下的 `Probe` 作用域。

> 删除只针对指定的 `scope_id`，不影响 `powercontext_sdd` 库中的其它作用域。
> 删除会清掉该作用域的**语料与进度**（`pc_sources` 与 `pc_atomic_memory_current`
> 等所有带 `scope_id` 列的表），因此重置后 `prior_progress` 归零、
> 语料条数回到 47。

---

## 4. 完全重置数据库

**容器模式**：

```bash
# 停止 PowerContext Server 后再操作
docker exec oceanbase-seekdb mysql -h127.0.0.1 -P2881 -uroot \
  -e "DROP DATABASE IF EXISTS powercontext_sdd;"

# 重新建库；PowerContext 首次启动会自行建表
docker exec oceanbase-seekdb mysql -h127.0.0.1 -P2881 -uroot \
  -e "CREATE DATABASE powercontext_sdd CHARACTER SET utf8mb4;"

# 重新启动 PowerContext Server
powercontext server run --env-file minimax/.runtime/server.env

# 重新导入
cd minimax && python -m sddctx ingest --project sample
```

彻底重建 seekdb 容器：

```bash
docker rm -f oceanbase-seekdb
docker run -d --name oceanbase-seekdb -p 2881:2881 oceanbase/seekdb:1.4.0
```

**嵌入式模式**（数据就是一个本地目录，删目录即彻底重置）：

```bash
cd minimax
python scripts/reset.py --database --storage embedded
# deleted the embedded seekdb data directory ...; restart PowerContext Server to rebuild the schema

# 重新导入（脚本会自行拉起服务、建表、导入）
python scripts/reset.py --scope minimax-sdd --storage embedded
# deleted scope scp_xxxxxxxx, recreated it as scp_yyyyyyyy and re-imported 47 records
```

---

## 5. 清理运行时目录

`minimax/.runtime/` 已被 `.gitignore` 忽略，包含本机配置、服务器日志与密钥材料：

```bash
rm -rf minimax/.runtime/home minimax/.runtime/home-restart-proof
rm -f  minimax/.runtime/server-restart-proof.env minimax/.runtime/server-restart-proof.log
```

保留 `minimax/.runtime/server.env`（本机真实配置，不入库）。
若要完全重建：

```bash
# 容器模式
cp minimax/env/server.env.example minimax/.runtime/server.env
# 嵌入式 seekdb 模式
cp minimax/env/server.embedded-seekdb.env.example minimax/.runtime/server.env
# 编辑占位符
```

---

## 6. 清理 Python 缓存

```bash
find minimax -name "__pycache__" -type d -prune -exec rm -rf {} +
find minimax -name ".pytest_cache" -type d -prune -exec rm -rf {} +
```

---

## 7. 恢复到「干净克隆」状态

```bash
cd PowerContext-minimax
git status
# minimax/ 下的参赛资产是新增文件，尚未纳入版本控制时：
git clean -nd minimax/          # 先看会删什么
git clean -fd minimax/          # 确认后再执行（会删除 minimax/ 下所有未跟踪文件）
```

> **谨慎**：`git clean -fd minimax/` 会删除 `minimax/` 下所有未被 Git 跟踪的文件，
> 包括 `minimax/artifacts/` 中的验证证据。执行前先确认 `git status` 输出，
> 或先备份 `minimax/artifacts/`。

---

## 8. 一键重置脚本

`minimax/scripts/reset.py` 封装了上面最常用的几项：

```bash
cd minimax
python scripts/reset.py --help
python scripts/reset.py --list-scopes
python scripts/reset.py --scope minimax-sdd   # 重置作用域 + 重新导入
python scripts/reset.py --prune-demo-scopes    # 清理临时作用域
python scripts/reset.py --worktree             # 还原样例项目
python scripts/reset.py --artifacts            # 清空产物
python scripts/reset.py --database             # 重建数据库

# 容器模式（需要 Docker）
python scripts/reset.py --scope minimax-sdd --storage docker
```

存储模式相关的参数：

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `--storage` | `embedded`（默认）/ `docker` | 决定直查 SQL 的通道：`pylibseekdb` 绑定或 `docker exec ... mysql`；同时决定脚本为服务派生的环境 |
| `--seekdb-dir` | 目录路径（默认 `.runtime/seekdb-data`） | 嵌入式 seekdb 的数据目录 |
| `--container` | `oceanbase-seekdb` | 容器名 |
| `--server-url` | 空（默认）/ `http://127.0.0.1:8010` | 为空时脚本自行启停服务；填地址则复用 |
| `--port` | `8010` | 自行启动服务时使用的端口（重启持久化验证默认 `8011`，规格修订验证默认 `8012`） |
