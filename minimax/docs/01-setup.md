# 01 · 环境搭建与配置 (Setup, dependencies and configuration)

本文给出从零开始复现本方案的完整步骤。**所有命令在 Windows、Linux、macOS 上通用**：
唯一的差别是虚拟环境里解释器的路径（`.venv/bin/python` 与 `.venv/Scripts/python.exe`），
本文统一用「先激活虚拟环境、再用 `python`」的写法，避开这个差别。

> **先看这里**：按官方《比赛仓库地址》表，MiniMax 赛题的提交分支是
> **`2026-competition-ecosystem`**，本作品即在该同名分支上开发
> （`competition/minimax` 是同一提交的别名）。
> 该分支只包含 `minimax/` 子目录，**仓库根目录没有 `pyproject.toml`**，
> 因此 `uv pip install ... -e .`（根目录）在这条分支上**必然失败**，
> 必须安装 `./minimax`；只有合并进官方完整仓库（根目录含 PowerContext 官方源码）之后，
> 根目录的 `-e .` 才可用。

---

## 1. 依赖与版本 (Dependencies and versions)

### 1.1 运行环境

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 11 10.0.26200 (x64) | 本仓库产物即在此环境产出；同样可在 Linux / macOS 上复现，下面的命令不区分平台 |
| Python | 3.12.14 | 由 `uv` 创建的虚拟环境 `minimax/.venv` |
| uv | 0.12.15 | 虚拟环境与依赖安装工具 |
| PowerContext | `1.4.1`（PyPI）／`1.4.1.dev181+gee6f45acb`（仓库源码） | 上下文存储服务与官方 Python SDK |
| OceanBase seekdb | `1.4.0` | 容器镜像 `oceanbase/seekdb:1.4.0`，或 `pylibseekdb==1.4.0.post2` 嵌入式构建 |
| seekdb 版本串 | `5.7.25-OceanBase seekdb-v1.4.0.0` | 两种模式下 `SELECT VERSION()` 的结果一致 |

### 1.2 存储模式：容器 / 免 Docker 的嵌入式 seekdb

| | 模式 A · 容器 | 模式 B · 嵌入式（免 Docker） |
| --- | --- | --- |
| 启动方式 | `docker run oceanbase/seekdb:1.4.0` | PowerContext Server 进程内启动 seekdb |
| 配置 | `POWERCONTEXT_SERVER_DATABASE_KIND=oceanbase`<br>`POWERCONTEXT_SERVER_DATABASE_URL=mysql+aoceanbase://...` | `POWERCONTEXT_SERVER_DATABASE_KIND=seekdb`<br>`POWERCONTEXT_SERVER_DATABASE_PATH=<绝对路径>` |
| 环境模板 | `minimax/env/server.env.example` | `minimax/env/server.embedded-seekdb.env.example` |
| 额外依赖 | 无 | `pylibseekdb>=1.4.0.post1,<2`（`[seekdb]` extra 已包含） |
| 数据位置 | 容器卷 | 本地目录 `POWERCONTEXT_SERVER_DATABASE_PATH` |
| 直查 SQL | `docker exec ... mysql` | `pylibseekdb` 绑定 |
| 验证脚本参数 | `--storage docker` | `--storage embedded`（数据目录默认 `.runtime/seekdb-data`，可用 `--seekdb-dir` 覆盖） |

两种模式跑的是**同一套 SQL、同一套脚本、同一套断言**，
`sddctx/sqlprobe.py` 负责把差异收敛在一处。

> **验证脚本会自己管理服务**：每个脚本都按 `--storage` 派生服务环境、
> 自行启停 PowerContext Server，跑完即退出，因此**不需要手工准备
> `env/*.env`**，也不需要一个常驻服务。只有想复用一个已经跑起来的服务时，
> 才需要复制模板并传 `--server-url` / `--env-file`。
> 派生逻辑集中在 `scripts/server_runtime.py`，四个脚本共用同一份实现。

> PowerContext 上游的 `seekdb` extra 用环境标记把 `pylibseekdb` 限制在
> Linux / macOS。该绑定在 Windows 11 上同样可以加载，本仓库的产物即在
> Windows 11 + 嵌入式 seekdb 上产出。

> **首次启动要留出时间**：嵌入式模式下，数据目录为空时的第一次启动要建
> 61 张表，实测约 **2~3 分钟**才就绪。验证脚本的就绪超时已放宽到 300 秒，
> 但请不要中途 Ctrl+C——被打断的建表会让数据目录停在
> `recovery_required` 状态，之后每次启动都会拒绝。
> 恢复方式见 `docs/07-open-issues.md` §4.2。

### 1.3 Python 依赖

| 包 | 版本 | 用途 |
| --- | --- | --- |
| `powercontext` | 1.4.1 | 上下文存储服务与官方 Python SDK |
| `sddctx` | 0.1.0 | 本方案的上下文管理模块（可编辑安装） |
| `pylibseekdb` | 1.4.0.post2 | 嵌入式 seekdb 绑定（仅模式 B） |
| `sqlalchemy` | 2.1.6 | PowerContext 的异步 ORM 层 |
| `pyobvector` | 0.2.29 | OceanBase 官方异步方言 `mysql+aoceanbase` |
| `httpx` | 0.28.1 | 访问 MiniMax API 与 PowerContext Server |
| `fastapi` / `uvicorn` | 0.162.0 / 0.54.0 | PowerContext Server 的 HTTP 层 |
| `pydantic` | 2.14.1 | PowerContext 的数据模型 |
| `pytest` | 9.2.0 | 样例项目测试框架 |
| `typer` | 0.27.3 | PowerContext CLI |

完整清单：

```bash
uv pip list                      # 已激活虚拟环境时直接可用
```

---

## 2. 安装步骤 (Installation)

### 2.1 创建虚拟环境

```bash
# 在仓库根目录执行（本文所有路径都以仓库根目录为基准）
uv venv --python 3.12 minimax/.venv
```

### 2.2 安装依赖

**先激活虚拟环境**，之后所有命令里的 `python` / `powercontext` 都指向它：

```bash
. minimax/.venv/bin/activate              # Linux / macOS
# . minimax/.venv/Scripts/activate         # Windows Git Bash
# minimax\.venv\Scripts\activate           # Windows PowerShell / CMD
```

**参赛分支（根目录没有安装文件）**：

```bash
uv pip install -e "./minimax[server,seekdb,dev]"
```

这条命令做两件事：

* `-e "./minimax"` 以可编辑模式安装本方案的 `sddctx` 包；
* `[server]` 拉入 PowerContext Server 及其 CLI 依赖（`powercontext[server,cli]`），
  `[seekdb]` 拉入嵌入式 seekdb 绑定，`[dev]` 拉入 pytest。

已激活虚拟环境时 `uv pip install` 会自动使用它；也可以显式指定解释器
（路径随平台不同）：

```bash
# Linux / macOS
uv pip install --python minimax/.venv/bin/python -e "./minimax[server,seekdb,dev]"
# Windows
uv pip install --python minimax/.venv/Scripts/python.exe -e "./minimax[server,seekdb,dev]"
```

**合并后的完整仓库**（仓库根目录含 PowerContext 官方源码）：

```bash
uv pip install -e .
```

此时 `powercontext` 指向本仓库源码（`1.4.1.dev181+gee6f45acb`），
`import powercontext` 与 `powercontext` 命令都指向 `src/powercontext`。

> **网络说明**：若 `pypi.org` 不可达，改用镜像源，例如
> `uv pip install -e "./minimax[server,seekdb,dev]" --index-url https://mirrors.aliyun.com/pypi/simple/`
> （`mirrors.cloud.tencent.com/pypi/simple/` 同样可用）。

安装完成后校验：

```bash
python -c "from importlib.metadata import version; print(version('powercontext'), version('sddctx'))"
# 1.4.1 0.1.0
powercontext --help
python -m sddctx --help
```

### 2.3 准备数据库 (seekdb)

**模式 A · 容器**：

```bash
docker run -d --name oceanbase-seekdb -p 2881:2881 oceanbase/seekdb:1.4.0
docker exec oceanbase-seekdb mysql -h127.0.0.1 -P2881 -uroot -N -e "SELECT VERSION();"
# 5.7.25-OceanBase seekdb-v1.4.0.0
docker exec oceanbase-seekdb mysql -h127.0.0.1 -P2881 -uroot \
  -e "CREATE DATABASE IF NOT EXISTS powercontext_sdd CHARACTER SET utf8mb4;"
```

**模式 B · 嵌入式**：

不需要任何外部进程，只需给出一个数据目录：

```bash
mkdir -p minimax/.runtime/seekdb-data
```

seekdb 由 PowerContext Server 启动时自动拉起，数据落在该目录；
`SELECT VERSION()` 同样返回 `5.7.25-OceanBase seekdb-v1.4.0.0`。

### 2.4 配置并启动 PowerContext Server（可选）

> **只有想复用一个常驻服务时才需要这一步。**
> 四个验证脚本默认会自行派生这份配置、启动服务、跑完再关掉，
> 因此直接跳到 §2.5 也可以完成全部验证。

仓库中只提交**占位值**模板：

```bash
cp minimax/env/server.embedded-seekdb.env.example minimax/.runtime/server.env
# 或容器模式：
# cp minimax/env/server.env.example minimax/.runtime/server.env
```

编辑 `minimax/.runtime/server.env`，把占位符替换为自己的值。

模式 B（嵌入式 seekdb）：

```dotenv
POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1
POWERCONTEXT_SERVER_HTTP_PORT=8010
POWERCONTEXT_SERVER_DATABASE_KIND=seekdb
POWERCONTEXT_SERVER_DATABASE_PATH=<绝对路径>/minimax/.runtime/seekdb-data
POWERCONTEXT_SERVER_ACCESS_MODE=disabled
POWERCONTEXT_SERVER_MCP_ENABLED=false
POWERCONTEXT_SERVER_DASHBOARD_ENABLED=false
POWERCONTEXT_HOME=<绝对路径>/minimax/.runtime/home
```

模式 A（容器 / OceanBase 集群）：

```dotenv
POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1
POWERCONTEXT_SERVER_HTTP_PORT=8010
POWERCONTEXT_SERVER_DATABASE_KIND=oceanbase
POWERCONTEXT_SERVER_DATABASE_URL=mysql+aoceanbase://<db-user>:<db-password>@<db-host>:<db-port>/<db-name>?charset=utf8mb4
POWERCONTEXT_SERVER_ACCESS_MODE=disabled
POWERCONTEXT_SERVER_MCP_ENABLED=false
POWERCONTEXT_SERVER_DASHBOARD_ENABLED=false
POWERCONTEXT_HOME=<绝对路径>/minimax/.runtime/home
```

配置说明：

| 变量 | 说明 |
| --- | --- |
| `POWERCONTEXT_SERVER_DATABASE_KIND` | `oceanbase` 适用于 OceanBase MySQL 模式集群与独立 seekdb 1.4；`seekdb` 为嵌入式模式。PowerContext 通过 `VERSION()` 识别独立 seekdb 构建并跳过多租户兼容校验。 |
| `POWERCONTEXT_SERVER_DATABASE_URL` | **仅 `oceanbase` 模式需要**。必须使用 `mysql+aoceanbase` 协议头（官方异步 OceanBase 方言），必须带显式端口，必须带 `charset=utf8mb4`。 |
| `POWERCONTEXT_SERVER_DATABASE_PATH` | **仅 `seekdb` 模式需要**，必须是绝对路径。 |
| `POWERCONTEXT_SERVER_ACCESS_MODE` | `disabled` 表示仅监听回环地址且不鉴权（本地验证脚本使用）。共享部署请改为 `enforced` 并设置 `POWERCONTEXT_SERVER_AUTH_TOKEN`。 |
| `POWERCONTEXT_HOME` | 运行时数据目录（游标签名密钥等）。**必须写成正斜杠路径**：环境文件解析器会把反斜杠当转义符处理。 |

启动：

```bash
powercontext server run --env-file minimax/.runtime/server.env
```

校验：

```bash
curl -s http://127.0.0.1:8010/v1/server-info
# {"schema_version":{"major":1,"minor":0},"product":"powercontext", ...}
```

### 2.5 配置 MiniMax

密钥**只**从环境变量读取，不写入任何被提交的文件：

```bash
# Windows 用户级环境变量（推荐，重开终端后生效）
setx MINIMAX_API_KEY "<your-key>"
```

也可以只对当前会话生效：

```bash
export MINIMAX_API_KEY="<your-key>"      # Linux / macOS
$env:MINIMAX_API_KEY="<your-key>"         # PowerShell
```

`minimax/sddctx/minimax_client.py` 的 `resolve_api_key()` 依次读取进程环境变量与
Windows 用户注册表 `HKCU\Environment\MINIMAX_API_KEY`，**从不**把密钥写入日志或产物。

> **复现时可以不配密钥**：四个验证脚本跑的是**已提交的会话内模型回答**
> （`minimax/model/SPEC-BILL-001-pricing.session-model.txt`）。
> 没有密钥时，HTTP API 调用这一步会失败并被如实记录成一步退出码 4，
> 其余步骤（导入、检索、改动前后测试、状态落库与复用）不受影响，
> 整条流水线仍能跑通。有密钥且额度可用时，同一条流水线会改由 API 直接产出代码。

可选环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.com/v1` | 国内站地址。国际站请改为 `https://api.minimax.io/v1`；两种密钥不通用。 |
| `MINIMAX_MODEL` | `MiniMax-M3` | 可用模型为 `MiniMax-M3` 与 `MiniMax-M3.1-Flash`。 |
| `MINIMAX_API_STYLE` | `openai` | 设为 `anthropic` 时改用 `<base>/anthropic/v1/messages`。 |
| `MINIMAX_TIMEOUT` | `180` | 单次请求超时（秒）。 |

### 2.6 初始化：导入语料 (Initialization)

```bash
cd minimax
python -m sddctx ingest --project sample \
  --json artifacts/ingest-report.json
```

期望输出：

```
ingested 47 records into scope scp_... (12 spec sections, 9 code symbols, 26 test cases)
```

---

## 3. 常用命令速查 (Command reference)

| 目的 | 命令 |
| --- | --- |
| 导入项目 | `python -m sddctx ingest --project sample` |
| 检索开发上下文 | `python -m sddctx query --task "为发票总价增加促销码折扣能力"` |
| 渲染发给模型的提示词 | `python -m sddctx prompt --task "..." --out prompt.md` |
| 写入进度 | `python -m sddctx state save --kind progress --text "..."` |
| 读取进度 | `python -m sddctx state list` |
| 检索进度 | `python -m sddctx state search --text "回归"` |
| 调用 MiniMax 生成代码 | `python -m sddctx minimax --task "..." --apply` |
| 给模型回答盖上出处戳 | `python -m sddctx record-answer --answer <file> --model <id> --out <file>` |
| 应用已保存的模型回答 | `python -m sddctx apply --response artifacts/minimax/response.json --project sample` |
| **一条命令跑完全部验证** | `bash scripts/run_all.sh`（嵌入式）／`bash scripts/run_all.sh docker`（容器） |
| 端到端验证 | `python scripts/run_e2e.py --storage embedded` |
| 重启持久化验证 | `python scripts/prove_restart_persistence.py --storage embedded` |
| 规格修订验证 | `python scripts/prove_spec_revision.py --storage embedded` |
| 重置 | `python scripts/reset.py --all --storage embedded` |

> 上表中的 `python` 指虚拟环境里的解释器。`scripts/run_all.sh` 会自己找
> `.venv/bin/python` 或 `.venv/Scripts/python.exe`，不需要激活环境；
> 也可用 `SDDCTX_PYTHON=/path/to/python bash scripts/run_all.sh` 指定别的解释器。

`--server-url`（PowerContext Server 地址）默认为**空**：为空时脚本自行启动并
停止一个服务；填上地址则复用该服务。`sddctx` 的子命令与 `--scope-title`
（作用域标题，默认 `minimax-sdd`）同样受此影响。

验证脚本与重置脚本另支持 `--storage {docker,embedded}` 与 `--seekdb-dir <目录>`，
用于切换存储模式。
