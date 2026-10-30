# 07 · 未完成项与实际错误 (Open items and the real errors)

本方案按赛题第 8 条要求，如实记录**未完成**的部分。
所有错误均为本机实际返回的原始信息，未做任何修饰。

---

## 1. MiniMax HTTP API 余额不足（未完成，但模型参与代码修改已完成）

### 实际错误

本轮运行（`artifacts/minimax/api-attempt.json`）：

```json
{
  "status": "failed",
  "model": "MiniMax-M3",
  "base_url": "https://api.minimaxi.com/v1",
  "error": "insufficient balance (1008)",
  "error_code": 1008,
  "http_status": 402,
  "error_payload": {
    "type": "error",
    "error": {
      "type": "insufficient_balance_error",
      "message": "insufficient balance (1008)",
      "http_code": "402"
    },
    "request_id": "07314f3ff008a2f1ec22969922a1d928"
  }
}
```

### 排查过程（均为实测）

| 尝试 | 端点 / 模型 | 实际返回 | 结论 |
| --- | --- | --- | --- |
| 1 | `https://api.minimax.io/v1` + `MiniMax-M3` | HTTP 401，`code 2049 invalid api key` | 密钥属于**国内站**账号，国际站端点不接受 |
| 2 | `https://api.minimaxi.com/v1` + `MiniMax-M2.5` | `code 2069 model no longer available` | M2.5 / M2.7 已下线 |
| 3 | `https://api.minimaxi.com/v1` + `MiniMax-M2.7` | `code 2069 model no longer available` | 同上 |
| 4 | `https://api.minimaxi.com/v1` + `MiniMax-M3` | HTTP 402，`code 1008 insufficient balance` | 鉴权通过、进入计费校验，**唯一阻塞点是余额** |
| 5 | `https://api.minimaxi.com/v1` + `MiniMax-M3.1-Flash` | HTTP 402，`code 1008 insufficient balance` | 同上 |
| 6 | `https://api.minimaxi.com/anthropic/v1/messages`（Anthropic 兼容路径） | HTTP 402，`code 1008 insufficient balance` | 路径正确（客户端已按 `<base>/anthropic/v1/messages` 实现），同样停在计费校验 |
| 7 | `https://api.minimax.chat/v1` + `MiniMax-M3` / `MiniMax-M3.1-Flash` | HTTP 402，`code 1008 insufficient balance` | 同上（2026-10-28 复测） |

### 「模型参与代码修改」本身**没有**因此落空

这一点必须说清楚，避免被误读：

* 本轮**「改动后」的 `sample/src/billing/pricing.py` 是 MiniMax 模型撰写的**，
  模型为会话承载的 **MiniMax-M3.1-Flash**；
* 它依据的提示词与走 HTTP API 时**完全相同**，都来自
  `sddctx` 从 seekdb 检索到的上下文包（`artifacts/context/prompt-001.md`，494 行）；
* 三者用 SHA-256 绑定，评审可自行复算（`artifacts/minimax/response.json`）：

  | 摘要 | 值 |
  | --- | --- |
  | `answer_sha256` | `d67f92c20af366b16b964981c163622a45b8688250198b45547c66eeb24d3a03` |
  | `prompt_sha256` | `9459cc244b8e9e7005a27c4350e664ec7bc56ae1759ebc54ae17dc940ac89d37` |
  | `context_pack_sha256` | `405dedf8dba31b4f5f95d5a6e0ed945fd058fe12480a6f6f7173fa815bd26134` |

  > `answer_sha256` 固定不变（回答文件固定）；`prompt_sha256` 与
  > `context_pack_sha256` 随运行变化，因为上下文包里带有 `db_position`、
  > 时间戳等本轮生成的字段——这本身就是「上下文来自数据库」的证据。

* 模型的**原始回答**已入库：`model/SPEC-BILL-001-pricing.session-model.txt`；
* 应用后的 diff：`artifacts/minimax/code.diff`；
* 落库时用的应用代码与 HTTP 路径**完全相同**（`sddctx apply`）；
* HTTP 通道的失败被单独记录在 `artifacts/minimax/api-attempt.json`，
  并原样附在被应用回答的 `api_attempt` 字段上，**两者不会混淆**。

未完成的只是「由**该账号的 HTTP 端点**直接返回答案」这一条通道。

### 恢复步骤

1. 在 MiniMax 平台控制台（国内站 `platform.minimaxi.com`）为该账号充值，
   或兑换比赛赠送额度；
2. 确认额度已到账后，重新执行：

```bash
cd minimax
python scripts/run_e2e.py
```

3. 预期结果：

```
[OK ] MiniMax code generation (exit=0) MiniMax-M3
[OK ] apply the model answer to the working tree (exit=0)
[OK ] test suite after the change (exit=0)
```

4. 产物会更新为 API 直接产出的真实内容：`artifacts/minimax/response.json`
   （`origin: api`）、`artifacts/minimax/code.diff`；
   `artifacts/minimax-status.json` 的 `code_source` 会从
   `minimax-session-model` 变为 `minimax-api`。
   应用与测试环节无需任何改动。

---

## 2. 本机 Docker 不可用（存储模式改为嵌入式 seekdb）

### 实际错误

本机 Docker Desktop 启动后，引擎无法启动，原因是宿主机的安全策略屏蔽了
`wsl.exe`：

```
[com.docker.backend.exe.wslexec][E] c:\windows\system32\wsl.exe --version failed:
fork/exec C:\WINDOWS\System32\wsl.exe: Access is denied. (stdout: "", stderr: "")
[com.docker.backend.exe.engines][E] starting engine linux/wsl failed to start:
checking preconditions: checking WSL version: ... running wslexec:
DockerDesktop/Wsl/ExecError: ... wsl.exe --version: fork/exec ...: Access is denied.
```

`docker ps` 的返回：

```
Error response from daemon: Docker Desktop is unable to start
```

这是**本机环境限制**，不是方案本身的缺陷：容器模式（`oceanbase/seekdb:1.4.0`）
在本仓库的上一轮运行中已验证可用，配置模板 `minimax/env/server.env.example`
与全部脚本参数都保持兼容。

### 采取的替代：模式 B · 嵌入式 seekdb

PowerContext 官方支持 `POWERCONTEXT_SERVER_DATABASE_KIND=seekdb`，
由 `pylibseekdb` 绑定在进程内拉起 seekdb。它与容器镜像是**同一个 seekdb 构建**：

```
SELECT VERSION();  ->  5.7.25-OceanBase seekdb-v1.4.0.0
```

本轮全部产物即在该模式下产出。

**为什么这不是「降低标准」**：

| | 容器模式 | 嵌入式模式 |
| --- | --- | --- |
| 数据库产品 | OceanBase seekdb 1.4.0 | OceanBase seekdb 1.4.0 |
| `VERSION()` | `5.7.25-OceanBase seekdb-v1.4.0.0` | `5.7.25-OceanBase seekdb-v1.4.0.0` |
| PowerContext 的表 | `pc_*`（61 张） | `pc_*`（61 张） |
| 直查 SQL | `docker exec ... mysql` | `pylibseekdb` 绑定 |
| 验证脚本 | 同一套 | 同一套 |

`sddctx/sqlprobe.py` 把两种模式的差异收敛在一个模块里，
验证脚本与重置脚本用**同一套 SQL 与同一套断言**，
因此本轮的证据对容器模式同样成立。

> 附带收益：嵌入式模式让「干净环境复现」不再依赖 Docker，
> 评审在一台只有 Python 的机器上也能跑通全流程。

---

## 3. 嵌入式模式下直查 SQL 未提交，导致「重置作用域」静默失效（已修复）

### 现象

用 `scripts/reset.py --scope minimax-sdd --storage embedded` 重置后，
脚本报告「deleted scope ... and re-imported 47 records」，
但直接查库发现**旧作用域的行一条都没少**：

```
scp_20ewjwse5dm1gzq1295qkdevzm	71      <- 期望为 0，实际仍为 71
scp_2awpszgx9z1pwwh5qxttzgzcf0	47      <- 新导入的
```

由此派生出一连锁假象：上下文包的 `corpus_size` 是 52 而不是 47、
`prior_progress` 一次比一次多，看起来像「历史遗留」，
其实是删除从未生效。

### 根因

seekdb 的握手不返回 autocommit 状态位，`pylibseekdb` 的连接因此**默认不开自动提交**。
`sqlprobe` 之前只负责执行语句，句柄关闭时未提交的事务被回滚，
于是 `DELETE` 语句「执行成功、一行不删」。

同样的原因，跨进程直查看到的也只是未提交的中间状态。
PowerContext 自身不受影响：它的 SQLAlchemy 会话在事务上下文退出时显式提交。

### 修复

`sddctx/sqlprobe.py` 在每条语句之后显式 `COMMIT`：

```python
cursor.execute(_strip_database(statement, database))
fetched = cursor.fetchall()
...
# The embedded connection does not report the autocommit flag in
# its handshake, so it starts with autocommit disabled.  Without an
# explicit commit every write would be rolled back when the handle
# is closed, which silently turns a reset into a no-op.
cursor.execute("COMMIT")
```

修复后重跑重置：旧作用域的 71 条语料与 14 条进度全部清空，
新作用域恰好 47 条语料、Atomic Memory 为 0 条，
上下文包回到 `corpus_size = 47`、`prior_progress = 0`。
本轮全部产物即在这个「已修复」的状态下重新生成。

### 对评审的影响

无。这是实现缺陷而非方案缺陷，已在提交前修复并重新生成了全部证据。
把它写在这里，是为了说明证据里的数字为什么与「未修复时」不同。

---

## 4. 干净环境复现暴露的三个问题（均已修复）

为了验证「换一台机器就能复现」，本方案在提交之后做了一次**真正的干净环境复现**：
把参赛分支从 GitHub 全新克隆到空目录，新建虚拟环境，
从 PyPI 安装 `powercontext` 与本方案，然后逐条跑四个脚本。
这一步暴露了三个只有在「本机之外」才会出现的问题。

### 4.1 健康检查走了 HTTP 代理，把活着的服务判成「没起来」

本机设置了 `HTTP_PROXY` / `HTTPS_PROXY`，而 `urllib.request` 默认会使用它们。
于是脚本访问 `http://127.0.0.1:8010/v1/server-info` 时，请求被转发给代理，
代理连不上本机端口，返回：

```
RuntimeError: PowerContext Server was not ready in 90.0s: HTTP Error 502: Bad Gateway
```

服务其实好好地在跑，是检查方式不对。
（PowerContext 官方 SDK 本身已经处理了这个问题——它明确让回环流量不经过环境代理；
只有本方案自己写的健康检查漏掉了。）

**修复**：健康检查改用不带代理的 opener：

```python
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
```

### 4.2 首次建表要两分钟，90 秒超时把启动打断成「损坏状态」

空数据目录上的第一次启动要建 61 张表，实测约 **120 秒**才 ready。
原先 90 秒的超时会在建表途中放弃，把服务杀掉，
数据目录因此留在 `recovery_required` 状态，之后每次启动都直接失败：

```
powercontext.builtin.persistence.migrations.server_readiness.MigrationError:
recovery_required: Stop writers and run powercontext server db-migrate apply before startup.
```

**修复**：就绪超时放宽到 300 秒（`DEFAULT_READY_TIMEOUT`）；
另外给「拥有自己数据目录」的两个证明脚本加了自动恢复：
遇到 `recovery_required` 就删掉目录重来一次。
共享数据目录的脚本不自动删除，改为给出可操作的提示：

```
If the log mentions 'recovery_required', the store was left in a state that refuses to start:
delete the data directory (scripts/reset.py --database --storage embedded) or apply the
pending migration with 'powercontext server db-migrate apply --env-file <file>'.
```

### 4.3 服务刚停，日志文件仍被占用，删除日志导致崩溃

Windows 上上一个服务进程还没完全释放日志文件时，删除它会抛
`PermissionError: [WinError 32] The process cannot access the file ...`，
第二次运行直接崩在启动之前。

**修复**：日志删除改为「删不掉就算了」——旧日志留着无害。

### 4.4 修复后的干净环境复现结果

重新克隆、全新虚拟环境、从 PyPI 安装后逐条执行：

| 命令 | 耗时 | 结果 |
| --- | --- | --- |
| `reset.py --database --storage embedded` | < 1s | 删除嵌入式存储目录 |
| `reset.py --scope minimax-sdd --storage embedded` | 3m24s | 首次建表 + 重新导入 47 条 |
| `run_e2e.py --storage embedded` | 1m32s | 14 步，退出码与本机一致（改前 `6 failed, 20 passed` → 改后 `26 passed`） |
| `prove_restart_persistence.py --storage embedded` | 2m39s | 4 项检查全部 PASS |
| `prove_spec_revision.py --storage embedded` | 2m10s | 9 项检查全部 PASS |

> 首次建表的 2～3 分钟是 seekdb 建 61 张表的固有开销，只在数据目录为空时出现一次；
> 之后的运行都是秒级。评审复现时请留出这段时间，不要中途 Ctrl+C。

---

## 5. 参考实现的定位（不是本轮的代码来源）

`minimax/reference/pricing_promo.py` 是**手写**的 `SPEC-BILL-001` 参考实现。
**本轮没有被应用**——本轮「改动后」的代码来自 MiniMax 模型。

它存在的两个理由：

* 证明 `SPEC-BILL-001` 是可实现的（规格没有自相矛盾或不可满足），
  且它的验收测试是可满足的；
* 提供一个完全离线、结果确定的兜底路径（`--code-source reference`），
  让「改前失败 / 改后通过 / 回归通过」这组证据在**任何**环境都能复现。

一旦使用参考实现，产物中会明确标注，不会与模型产出混淆：

```json
{
  "code_source": "reference",
  "source_file": "reference/pricing_promo.py",
  "target_file": "sample/src/billing/pricing.py",
  "reason": "the MiniMax endpoint was unreachable during this run"
}
```

`scripts/run_e2e.py` 的默认优先级：

1. HTTP API 成功 → `code_source: minimax-api`；
2. HTTP API 失败但给了 `--model-answer` → `code_source: minimax-session-model`；
3. 都没有 → `code_source: reference`。

---

## 6. 其它已知限制

| 限制 | 影响 | 缓解 |
| --- | --- | --- |
| 检索是词法的，没有语义向量 | 任务措辞与规格措辞差异大时召回下降 | `applies_to` 显式链接兜底；`keywords` 字段提供额外词面 |
| PowerContext 未配置推理服务 | `memory/search` 只走文本匹配（`matched_by: ["text"]`） | 本方案不依赖向量检索；如需可另行配置嵌入提供方 |
| 作用域删除无 HTTP 端点 | 重置需在存储层执行 | `scripts/reset.py` 用 SQL 精确删除指定 `scope_id` 的行（两种存储模式都支持） |
| `POWERCONTEXT_HOME` 必须用正斜杠 | 环境文件解析器会把反斜杠当转义符 | 模板与脚本统一使用正斜杠路径 |
| PowerContext 收到 `SIGTERM` 后退出码为 1 | 容易被误读为失败 | 属其自身关闭行为；数据在数据库中，重启后可读回 |
| 上游 `powercontext[seekdb]` extra 用环境标记把 `pylibseekdb` 限制在 Linux / macOS | Windows 上 `uv pip install "powercontext[seekdb]"` 不会自动装上绑定 | 绑定在 Windows 11 上可正常加载；本仓库的 `[seekdb]` extra 不带该标记，显式安装即可 |
| 参赛分支的仓库根目录没有安装文件 | `uv pip install -e .` 在该分支必然失败 | 本仓库提供 `minimax/pyproject.toml`，安装命令改为 `-e "./minimax"`；两种仓库形态的命令见 `docs/01-setup.md` §2.2 |
| 提交分支名必须是官方同名分支 | 平台按官方《比赛仓库地址》表 checkout `2026-competition-ecosystem`；若填 `competition/minimax`，平台在该分支上找不到所填 commit，会直接判定**执行失败** | 本作品的提交分支为 **`2026-competition-ecosystem`**（基线 `d647275c` 的后代）；`competition/minimax` 是同一提交的别名，两个分支指向同一 commit |
| 运行说明原本只写了 Windows 路径 | 评审机若为 Linux，照抄 `.venv/Scripts/python.exe` 会全部失败 | 运行说明已改为跨平台形式（激活虚拟环境后统一用 `python`），并提供 `scripts/run_all.sh` 一键入口；形式已在全新虚拟环境中实测，见 `docs/03-verification.md` §7.1.1 |

---

## 7. 干净环境复现清单

从零开始复现（不依赖本机任何既有文件或数据库状态）。**下列命令在 Windows、Linux、macOS 上通用**，
只有激活虚拟环境那一行按平台二选一：

```bash
# 1. Python 环境与依赖（在仓库根目录执行）
uv venv --python 3.12 minimax/.venv
. minimax/.venv/bin/activate            # Linux / macOS
# . minimax/.venv/Scripts/activate       # Windows Git Bash
# minimax\.venv\Scripts\activate         # Windows PowerShell / CMD

# 参赛分支（根目录没有安装文件）：
uv pip install -e "./minimax[server,seekdb,dev]"
# 合并后的完整仓库：额外执行
# uv pip install -e .

# 2. 数据库（二选一）
# 2a. 容器模式
docker run -d --name oceanbase-seekdb -p 2881:2881 oceanbase/seekdb:1.4.0
docker exec oceanbase-seekdb mysql -h127.0.0.1 -P2881 -uroot \
  -e "CREATE DATABASE powercontext_sdd CHARACTER SET utf8mb4;"

# 2b. 免 Docker 的嵌入式 seekdb 模式
# 无需任何准备：验证脚本会自行拉起服务并建库
mkdir -p minimax/.runtime

# 3. （可选）只有想复用一个常驻服务时才需要准备环境文件
# cp minimax/env/server.embedded-seekdb.env.example minimax/.runtime/server.env
# 编辑 minimax/.runtime/server.env（填绝对路径）
# 容器模式则用：cp minimax/env/server.env.example minimax/.runtime/server.env
# 然后：powercontext server run --env-file minimax/.runtime/server.env
# 并给下面每条命令加上 --server-url http://127.0.0.1:8010

# 4. 验证（每条命令自行启停服务，互不依赖）
cd minimax

# 4a. 清空存储，从空状态开始
#     注意：第一次启动要在空目录上建 61 张表，实测约 2~3 分钟，请勿中途 Ctrl+C
python scripts/reset.py --database --storage embedded
python scripts/reset.py --scope minimax-sdd --storage embedded

# 4b. 端到端
python scripts/run_e2e.py --storage embedded \
    --model-answer model/SPEC-BILL-001-pricing.session-model.txt \
    --model-id "MiniMax-M3.1-Flash"

# 4c. 重启持久化
python scripts/prove_restart_persistence.py --storage embedded

# 4d. 规格修订
python scripts/prove_spec_revision.py --storage embedded
```

> 也可以用一键入口替代第 4 步的 4a~4d：
> `cd minimax && bash scripts/run_all.sh`（脚本自行定位虚拟环境解释器）。

第 4 步的预期结果：

| 步骤 | 退出码 |
| --- | --- |
| 导入语料（47 条） | 0 |
| 检索开发上下文 | 0 |
| 写入任务进度 | 0 |
| 改动前全量测试 | **1**（`6 failed, 20 passed`） |
| 改动前回归测试 | 0（`20 passed`） |
| 改动前目标功能测试 | **1**（`6 failed`） |
| MiniMax HTTP API 调用 | **4**（402 / 1008） |
| 应用模型回答 | 0 |
| 改动后全量测试 | 0（`26 passed`） |
| 改动后回归测试 | 0（`20 passed`） |
| 改动后目标功能测试 | 0（`6 passed`） |
| 写入改动后验证结果 | 0 |
| 还原改动前工作区 | 0 |
| 带进度再次检索 | 0 |
| 重启持久化验证 | 0（4 项检查全部 PASS） |
| 规格修订验证 | 0（9 项检查全部 PASS） |

> 容器模式下，把 `--storage embedded` 换成 `--storage docker`；
> 若已经在第 3 步起了常驻服务，再加 `--server-url http://127.0.0.1:8010`。
