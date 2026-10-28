# 规有所依 —— 面向软件持续演进的 SDD 上下文管理系统

以 **PowerContext** 为上下文底座、以 **OceanBase seekdb** 为持久化存储，
实现「规格 → 检索 → 模型 → 代码改动 → 验证」的闭环，并让每一步都**可追溯、可复现**。

赛题：<https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/qlqnoryzrs7gtqbw>

---

## 目录结构

```
minimax/
├── pyproject.toml        # 独立可安装的包定义（sddctx）
├── sddctx/              # 上下文管理系统（索引 · 检索 · 渲染 · MiniMax 客户端 · CLI）
│   ├── models.py        #   记录模型、JSON 信封、内容寻址 source_id
│   ├── parsing.py       #   规格 / 代码 / 测试的切分
│   ├── store.py         #   PowerContext 读写封装（Content Sources + Atomic Memory）
│   ├── retrieval.py     #   双语词法 + IDF + applies_to 变更面推导
│   ├── render.py        #   提示词与带出处的检索报告
│   ├── minimax_client.py#   MiniMax 客户端（密钥不落盘，丢弃私有思维链）
│   ├── model_answer.py  #   模型回答的出处封装（提示词 / 上下文包摘要）
│   ├── sqlprobe.py      #   直查 seekdb（容器模式与嵌入式模式同一套 SQL）
│   └── cli.py           #   ingest / query / prompt / state / minimax / apply / record-answer
├── sample/              # 样例项目：2 份规格 + 3 个源文件 + 26 个测试
│   ├── specs/           #   SPEC-BILL-001（新行为）· SPEC-BILL-002（不变量）
│   ├── src/billing/     #   money.py · pricing.py（改动目标）· invoice.py（回归护栏）
│   └── tests/           #   20 个回归用例 + 6 个功能用例
├── model/               # MiniMax 模型的原始回答（提交入库，作为「模型参与」的证据）
│   └── SPEC-BILL-001-pricing.session-model.txt
├── reference/           # SPEC-BILL-001 的手写参考实现（离线兜底，非模型产出）
├── scripts/             # 端到端验证 · 重启持久化验证 · 规格修订验证 · 重置
│   ├── server_runtime.py#   验证脚本共用的服务运行时（按存储模式派生环境、启停服务）
│   ├── run_e2e.py       #   导入 → 检索 → 调模型 → 应用改动 → 前后测试 → 复用进度
│   ├── prove_restart_persistence.py  # 空状态写入 → 冷重启 → 读回 → 复用
│   ├── prove_spec_revision.py        # 改规格 → 重新导入 → 上下文用新内容
│   └── reset.py         #   工作区 / 作用域 / 产物 / 数据库 四类重置
├── env/                 # 配置模板（仅占位值）
│   ├── server.env.example               # 容器模式
│   └── server.embedded-seekdb.env.example # 免 Docker 的嵌入式 seekdb 模式
├── docs/                # 搭建 · 架构 · 验证 · 重置 · 使用记录 · 技术说明 · 未完成项
└── artifacts/           # 全部验证证据
```

---

## 快速开始

### 0. 两种仓库形态

本参赛分支 `competition/minimax` 只包含 `minimax/` 目录；合并进官方
`2026-competition-ecosystem` 后，仓库根目录会同时包含 PowerContext 官方源码
（根目录有 `pyproject.toml`）。两种形态的安装命令不同，见
[`docs/01-setup.md`](docs/01-setup.md)。

### 1. Python 环境与依赖

```bash
cd PowerContext-minimax

uv venv --python 3.12 minimax/.venv

# 参赛分支（稀疏仓库）：从 PyPI 安装 PowerContext，同时以可编辑模式安装 sddctx
uv pip install --python minimax/.venv/Scripts/python.exe -e "./minimax[server,seekdb,dev]"

# 合并后的完整仓库：PowerContext 来自本仓库源码
uv pip install --python minimax/.venv/Scripts/python.exe -e . -e "./minimax[server,seekdb,dev]"
```

> `uv pip install ... -e .`（仓库根目录）只在**完整仓库**里可用；
> 参赛分支的仓库根目录没有安装文件，必须指向 `./minimax`。

### 2. 数据库（OceanBase seekdb）

两种模式，产物与验证脚本完全一致：

```bash
# 模式 A · 容器
docker run -d --name oceanbase-seekdb -p 2881:2881 oceanbase/seekdb:1.4.0
docker exec oceanbase-seekdb mysql -h127.0.0.1 -P2881 -uroot \
  -e "CREATE DATABASE powercontext_sdd CHARACTER SET utf8mb4;"

# 模式 B · 免 Docker 的嵌入式 seekdb（同一个 seekdb 构建，数据落在本地目录）
# 绑定已随上面的 [seekdb] extra 装好，验证脚本会自动使用 .runtime/seekdb-data
```

> **验证脚本不再需要手工准备服务**：每个脚本都会按 `--storage` 自行派生服务环境、
> 自行启停 PowerContext Server，跑完即退出。只有想复用一个常驻服务时，才需要
> 第 3、4 步并显式传 `--server-url`。

### 3. 配置（仅当复用常驻服务时才需要；模板里全是占位值，真实值只写本机、不入库）

```bash
cp minimax/env/server.embedded-seekdb.env.example minimax/.runtime/server.env
# 编辑 minimax/.runtime/server.env，填入绝对路径
```

### 4. 启动 PowerContext Server（可选）

```bash
minimax/.venv/Scripts/powercontext.exe server run --env-file minimax/.runtime/server.env
```

### 5. 导入 + 检索

```bash
cd minimax
.venv/Scripts/python.exe -m sddctx ingest --project sample
.venv/Scripts/python.exe -m sddctx query --task "为发票总价增加促销码折扣能力，先折扣后计税"
```

完整的依赖版本、配置项与初始化步骤见 [`docs/01-setup.md`](docs/01-setup.md)。

---

## 验证

四条命令各自独立，每条都会自行启停 PowerContext Server，**不需要预先启动服务**：

```bash
cd minimax

# 0) 清理上一个作用域并重新导入（保证从已知状态开始）
.venv/Scripts/python.exe scripts/reset.py --scope minimax-sdd --storage embedded

# 1) 端到端：导入 → 检索 → 调模型 → 应用改动 → 前后测试 → 复用进度
.venv/Scripts/python.exe scripts/run_e2e.py --storage embedded \
    --model-answer model/SPEC-BILL-001-pricing.session-model.txt \
    --model-id "MiniMax-M3.1-Flash"

# 2) 重启持久化：空状态写入 → 冷重启（连存储引擎一起停） → 读回 → 复用
.venv/Scripts/python.exe scripts/prove_restart_persistence.py --storage embedded

# 3) 规格修订：改规格 → 重新导入 → 上下文用新内容
.venv/Scripts/python.exe scripts/prove_spec_revision.py --storage embedded
```

> 容器模式把 `--storage embedded` 换成 `--storage docker`（可选 `--env-file` 指定
> 自己的服务环境）；复用常驻服务则额外传 `--server-url http://127.0.0.1:8010`。

最近一次实际运行结果（`artifacts/e2e-steps.json`，14 步）：

| 步骤 | 退出码 |
| --- | --- |
| 导入语料到 PowerContext（47 条 → seekdb） | 0 |
| 检索开发上下文（12 规格节 / 7 待改符号 / 6 功能测试 / 20 回归测试） | 0 |
| 写入任务进度到 PowerContext | 0 |
| 改动前全量测试 | **1**（`6 failed, 20 passed`） |
| 改动前回归测试 | 0（`20 passed`） |
| 改动前目标功能测试 | **1**（`6 failed`，`AttributeError`：功能未实现） |
| MiniMax HTTP API 调用 | **4**（HTTP 402 / code 1008 `insufficient balance`） |
| 应用 **MiniMax 模型回答**到工作区 | 0 |
| 改动后全量测试 | 0（`26 passed`） |
| 改动后回归测试 | 0（`20 passed`） |
| 改动后目标功能测试 | 0（`6 passed`） |
| 写入改动后验证结果到 PowerContext | 0 |
| 还原改动前工作区 | 0 |
| 带进度再次检索上下文（`prior_progress=14`） | 0 |

| 证明脚本 | 结论 |
| --- | --- |
| 重启持久化验证 | 通过（4 项检查全部 PASS；**冷启动**，存储引擎随服务一起停机后再拉起，直查数据库行留存） |
| 规格修订验证 | 通过（9 项检查全部 PASS） |

证据文件与逐条说明见 [`docs/03-verification.md`](docs/03-verification.md)。

---

## MiniMax 如何参与了这次代码修改

「改动后」的代码**由 MiniMax 模型撰写**，不是手写参考实现。

* **模型**：本会话所承载的 MiniMax 模型 `MiniMax-M3.1-Flash`；
* **驱动方式**：与调用 HTTP API 完全相同的提示词——由
  `sddctx` 从 seekdb 检索到的上下文包渲染而成（`artifacts/context/prompt-001.md`）；
* **可核验链路**：模型回答、提示词、上下文包三者都用 SHA-256 绑定在
  `artifacts/minimax/response.json` 中（`answer_sha256` / `prompt_sha256` /
  `context_pack_sha256`）；
* **原始回答**：`model/SPEC-BILL-001-pricing.session-model.txt` 已提交入库；
* **落库 diff**：`artifacts/minimax/code.diff`；
* **改动前后的代码版本**：`artifacts/tests/code-version-before.json` /
  `code-version-after.json`（文件 SHA-256 + git commit）。

**HTTP API 的真实状态**：本机 MiniMax 账户余额不足，API 一律返回
`HTTP 402 / code 1008 insufficient_balance_error`。该错误被**如实记录**在
`artifacts/minimax/api-attempt.json`，并原样附在被应用的回答上。
额度恢复后重跑同一条流水线即可改为由 API 直接产出代码，链路完全一致。

`reference/pricing_promo.py` 是手写参考实现，只在**完全离线**时作为兜底
（`--code-source reference`），产物中以 `code_source: "reference"` 明确标注，
不会与模型产出混淆。

---

## 当前缺口

| 缺口 | 影响 | 说明 |
| --- | --- | --- |
| MiniMax HTTP API 余额不足 | 仅影响「由 API 直接产出代码」这一条路径 | 模型回答由会话内的 MiniMax 模型产出，代码改动本身完整；API 错误已如实记录 |
| 检索是词法的，没有语义向量 | 任务措辞与规格措辞差异大时召回下降 | `applies_to` 显式链接兜底；`keywords` 字段提供额外词面 |
| PowerContext 未配置推理服务 | `memory/search` 只走文本匹配 | 本方案不依赖向量检索；如需可另行配置嵌入提供方 |
| 作用域删除无 HTTP 端点 | 重置需在存储层执行 | `scripts/reset.py` 用 SQL 精确删除指定 `scope_id` 的行（两种存储模式都支持） |
| 本机 Docker 不可用（宿主屏蔽 `wsl.exe`） | 本轮产物改用嵌入式 seekdb 产出 | 容器模式配置与脚本参数保持不变；两种模式同一套 SQL 与断言 |

详见 [`docs/07-open-issues.md`](docs/07-open-issues.md)。

---

## 文档

| 文档 | 内容 |
| --- | --- |
| [`docs/01-setup.md`](docs/01-setup.md) | 依赖与版本、两种仓库形态、两种存储模式、配置项、命令速查 |
| [`docs/02-architecture.md`](docs/02-architecture.md) | 记录模型、内容寻址、检索算法、变更面推导、出处追溯 |
| [`docs/03-verification.md`](docs/03-verification.md) | 按赛题 8 条要求逐条给出命令、实际输出、预期结果与证据索引 |
| [`docs/04-reset.md`](docs/04-reset.md) | 工作区 / 作用域 / 产物 / 数据库四类重置（两种存储模式） |
| [`docs/05-usage-record.md`](docs/05-usage-record.md) | 技术使用记录（版本、用途、验证证据）与未使用技术的理由 |
| [`docs/06-technical-note.md`](docs/06-technical-note.md) | 一页技术说明 |
| [`docs/07-open-issues.md`](docs/07-open-issues.md) | 未完成项、真实错误、排查过程与干净环境复现清单 |

---

## 安全与合规

* 仓库中**不含任何真实凭据**：`minimax/env/*.env.example` 全部为占位值，
  真实配置写在被 `.gitignore` 忽略的 `minimax/.runtime/`；
* MiniMax 密钥只从环境变量 / Windows 用户注册表读取，**从不**写入日志或产物
  （`request.json` 中固定为 `<redacted>`）；
* 模型的私有思维链（`reasoning_content`）在客户端就被丢弃，不进入任何产物。
