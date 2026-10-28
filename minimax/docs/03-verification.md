# 03 · 验证样例与预期结果 (Verification samples and expected results)

本文按赛题 8 条要求逐条给出**可复现的命令**、**实际输出**与**预期结果**，
并指向对应的证据文件。所有输出均为本机实际运行结果，未做任何修饰。

本轮产物使用的存储模式是**模式 B · 嵌入式 seekdb**（免 Docker），
理由与容器模式的差异见 `docs/01-setup.md` §1.2；
两种模式跑的是同一套脚本与同一套断言。

复现入口（每条命令都自行启停 PowerContext Server，**不需要预先启动服务**）：

```bash
cd minimax

# 0) 清空嵌入式存储并重建作用域，保证从已知状态开始
.venv/Scripts/python.exe scripts/reset.py --database --storage embedded
.venv/Scripts/python.exe scripts/reset.py --scope minimax-sdd --storage embedded

# 1) 主流程（含模型调用、改动前后测试、进度落库）
.venv/Scripts/python.exe scripts/run_e2e.py --storage embedded \
    --model-answer model/SPEC-BILL-001-pricing.session-model.txt \
    --model-id "MiniMax-M3.1-Flash"

# 2) 重启持久化
.venv/Scripts/python.exe scripts/prove_restart_persistence.py --storage embedded

# 3) 规格修订
.venv/Scripts/python.exe scripts/prove_spec_revision.py --storage embedded
```

> 验证脚本的服务环境由 `scripts/server_runtime.py` 按 `--storage` 自动派生：
> 嵌入式模式写入 `POWERCONTEXT_SERVER_DATABASE_KIND=seekdb` 与
> `POWERCONTEXT_SERVER_DATABASE_PATH`，容器模式写入
> `POWERCONTEXT_SERVER_DATABASE_KIND=oceanbase` 与 `DATABASE_URL`。
> 只有想复用一个常驻服务时，才需要准备 `env/*.env.example` 并传 `--server-url`。

---

## 要求 1 · 可运行、有测试的样例项目与一处明确的代码改动

**样例项目**：`minimax/sample/`（纯 Python，无第三方依赖，pytest 驱动）。

```
minimax/sample/
├── pyproject.toml
├── pytest.ini
├── specs/
│   ├── SPEC-BILL-001-invoice-promo-discount.md   # 本次改动的新行为规格
│   └── SPEC-BILL-002-money-invariants.md          # 必须保持不变的既有行为
├── src/billing/
│   ├── money.py      # Money 值对象
│   ├── pricing.py    # ← 本次改动的目标文件
│   └── invoice.py    # 故意不改动，作为回归护栏
└── tests/
    ├── conftest.py
    ├── test_money.py       # 8 个回归用例
    ├── test_pricing.py     # 9 个回归用例 + 6 个功能用例
    └── test_invoice.py     # 3 个回归用例
```

**本次改动**：`billing.pricing.compute_invoice_totals` 新增关键字参数 `promo_code`，
实现促销码折扣（先折扣后计税）。详见 `SPEC-BILL-001`。

**必须保持的原有行为**：见 `SPEC-BILL-002` 与 20 个 `test_regression_*` 用例，
涵盖小计计算、税额舍入（`ROUND_HALF_UP` 而非银行家舍入）、
`tax_rate` 校验、`LineItem` 校验与发票渲染。

**验证命令与预期结果**：

```bash
cd minimax/sample
../.venv/Scripts/python.exe -m pytest -q
# 改动前：6 failed, 20 passed
# 改动后：26 passed
```

---

## 要求 2 · 导入规格 / 代码 / 测试到 seekdb，并提供明确的调用入口

**导入**（写入 PowerContext Content Sources，落库到 seekdb 的 `pc_sources`）：

```bash
cd minimax
.venv/Scripts/python.exe -m sddctx ingest --project sample --json artifacts/ingest-report.json
```

实际输出：

```
ingested 47 records into scope scp_6d4rq92ngwcnzytn87ebhqyqr3
(12 spec sections, 9 code symbols, 26 test cases)
```

**调用入口**：`python -m sddctx`
（子命令 `ingest` / `query` / `prompt` / `state` / `minimax` / `apply` / `record-answer`），
以及统一脚本 `scripts/run_e2e.py`。

**数据库直查**（证明数据确实在 seekdb 里，而不是本地文件）：

```bash
# 模式 B · 嵌入式（本轮实际使用）
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, '.')
from sddctx.sqlprobe import run_sql
r = run_sql('SELECT scope_id, COUNT(*) FROM pc_sources GROUP BY scope_id;',
            mode='embedded', seekdb_dir='.runtime/seekdb-data')
print(r.text)"

# 模式 A · 容器
docker exec oceanbase-seekdb mysql -h127.0.0.1 -P2881 -uroot -N -e \
  "SELECT scope_id, COUNT(*) FROM powercontext_sdd.pc_sources GROUP BY scope_id;"
```

本轮导入 **47 条语料**（`source_id` 前缀 `sddctx:v1:`）。
规格或测试文件每次被修改都会在内容寻址机制下留下一个新版本的 Source，旧版本仍然
保留（见要求 3），因此行数会随开发过程增长，但**同一内容重复导入是幂等的**：
重复执行 `ingest` 不会增加行数。
用 `scripts/reset.py --scope minimax-sdd --storage embedded` 重置作用域后，行数回到同一基线。

**seekdb 版本确认**（两种模式一致）：

```
5.7.25-OceanBase seekdb-v1.4.0.0
```

**按任务检索**：

```bash
.venv/Scripts/python.exe -m sddctx query --task "为发票总价增加促销码折扣能力，先折扣后计税"
```

实际输出（节选，完整见 `artifacts/context/pack-001.md`）：

```
Task: 为发票总价增加促销码折扣能力，先折扣后计税
Scope: scp_6d4rq92ngwcnzytn87ebhqyqr3
Corpus records considered: 47
Files to modify: src/billing/pricing.py

## Applicable specifications (12)
## Code to modify (7)
## Functional tests (6)
## Regression tests (20)
```

---

## 要求 3 · 输出包含适用规格、待改代码与测试的真实来源；改规格重导入后输出随之变化

### 3.1 输出内容与出处

每一条结果都带 `source_id` / `db_position` / `file_sha256` / `server_content_digest`，
可逐条回溯到数据库行与仓库文件。证据：`artifacts/context/pack-001.json`、`pack-001.md`。

- 适用规格：12 个规格小节（`SPEC-BILL-001` 7 节 + `SPEC-BILL-002` 5 节）
- 待改代码：7 个符号，全部来自 `src/billing/pricing.py`
- 功能测试：6 个（`test_promo_*`）
- 回归测试：20 个（`test_regression_*`）

### 3.2 规格修订后输出跟随变化

**命令**：

```bash
.venv/Scripts/python.exe scripts/prove_spec_revision.py --storage embedded
```

**实际输出**：

```json
{
  "spec_sections_before": 12,
  "spec_sections_after": 12,
  "respecified_sections": 7,
  "new_content_present_after_reimport": true,
  "new_content_absent_before_edit": true,
  "source_ids_changed": true,
  "repository_restored": true,
  "production_scope_untouched": true,
  "production_scope_holds_pre_edit_spec": true,
  "passed": true
}
```

**实际发生了什么**：脚本在独立作用域 `scp_66cw2vhn0j1g89xsc29p551pwk` 上把
`SPEC-BILL-001` 的促销码目录从 3 个码改为 4 个
（新增 `SAVE30`）、把 `SAVE20` 的折扣上限从 100.00 改为 150.00、`version` 从 1 改为 2，
重新导入后检索结果包含 `SAVE30`，而改动前的检索结果不包含。

> `production_scope_holds_pre_edit_spec` 是本轮新增的检查项：它断言生产作用域里
> 确实存着**改动前**的规格文本（`SAVE20` 上限仍为 100.00）。
> 没有这一项，「生产作用域未被污染」会因为作用域本来就是空的而变成空断言。

**数据库中的两个版本**（`artifacts/spec-revision/spec-revision-proof.json` 的
`stored_source_versions` 字段，实际 SQL 结果，节选 4 行，共 14 行）：

```
sddctx:v1:spec_section:SPEC-BILL-001#背景-background:5d4baa04af01	1
sddctx:v1:spec_section:SPEC-BILL-001#促销码目录-promotion-catalog:13bbead34177	3
sddctx:v1:spec_section:SPEC-BILL-001#背景-background:b0ce76248b9e	48
sddctx:v1:spec_section:SPEC-BILL-001#促销码目录-promotion-catalog:2cf2853168b2	50
```

前 7 行是改动前的版本，后 7 行是改动后重新导入的新版本——`source_id` 后缀不同，
`journal_position` 也随之后移。

**脚本会还原仓库**：退出前用原始字节覆盖回规格文件，并校验 SHA-256 一致
（`repository_restored: true`，`git status -- minimax/sample/specs/` 为空），
同时确认生产作用域 `minimax-sdd` 未被污染（`production_scope_untouched: true`）。

对比报告：`artifacts/spec-revision/report-before.md` 与 `report-after.md`。

---

## 要求 4 · 把真正检索到的上下文交给 MiniMax，并留下可核验记录

### 4.1 检索到的上下文确实来自 seekdb

检索链路：PowerContext Server → seekdb `pc_sources` → `sddctx query` → 上下文包。
上下文包里的每一条都带数据库位置与内容摘要，例如：

```
- SPEC-BILL-001 折扣计算规则 (Discount rules)
  | specs/SPEC-BILL-001-invoice-promo-discount.md:56-67
  | score=0.6588
  | sddctx:v1:spec_section:SPEC-BILL-001#折扣计算规则-discount-rules:7a974a0a7887
  | db_position=4
  | file_sha256=d501c0167c7e418d141403b0f20dfd735ba9d684988bca29eee7ff9ab5c7d260
  | server_digest=sha256:198721ea340aa7804d63a149335c2674224936468e9532e1050c3befa1fa7cfa
```

`db_position` 是 seekdb 中的行位置，`server_digest` 是服务端回读的正文摘要，
两者都能与数据库逐条对上。

### 4.2 交给模型的提示词

提示词由上下文包渲染而成（`artifacts/context/prompt-001.md`，共 494 行）：
任务 → 适用规格 → 待改代码 → 功能测试 → 回归测试 → 已存进度，
每段都带 `source_id` / `db_position` / 摘要。

### 4.3 模型产出了代码

**「改动后」的 `sample/src/billing/pricing.py` 由 MiniMax 模型撰写。**

| 项目 | 值 |
| --- | --- |
| 模型 | `MiniMax-M3.1-Flash`（本会话承载的 MiniMax 模型） |
| 来源 | `model/SPEC-BILL-001-pricing.session-model.txt`（已提交入库） |
| 回答摘要 | `answer_sha256 = d67f92c20af366b16b964981c163622a45b8688250198b45547c66eeb24d3a03` |
| 提示词摘要 | `prompt_sha256 = 5e5624cbcf6f14e3ba9780f2355b3b438e8d25bf0123de028fc123ca5ac071c4` |
| 上下文包摘要 | `context_pack_sha256 = a504506cb9ceaa4af298be5006bfc85466bff148bd5f9e91c663ff287379021d` |
| 落库 diff | `artifacts/minimax/code.diff` |
| 应用结果 | `artifacts/minimax/response.json`（`code_source: minimax-session-model`） |

三个摘要把「检索到的上下文 → 提示词 → 模型回答」绑成一条链：
评审可以自行重算这三个 SHA-256 并与应用到的 diff 对照。

> `answer_sha256` 在多次运行之间保持不变（模型回答文件是固定的）；
> `prompt_sha256` 与 `context_pack_sha256` 随运行变化，因为上下文包中带有
> `db_position`、时间戳等本轮生成的字段——这正是「上下文确实来自数据库」的证据。

### 4.4 HTTP API 的真实状态（未完成项，如实记录）

本机调用 MiniMax API 的**真实**结果是（`artifacts/minimax/api-attempt.json`）：

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
    "request_id": "0731488434bb3cc5a578b8e3bb78817a"
  }
}
```

排查结论（均为实测，非推测）：

* 密钥有效：`api.minimax.io`（国际站）返回 `401 / code 2049 invalid api key`，
  说明该密钥属于**国内站**账号；
* 端点必须是 `https://api.minimaxi.com/v1`（该端点鉴权通过并进入计费校验）；
* 模型必须是 `MiniMax-M3` 或 `MiniMax-M3.1-Flash`；
  `MiniMax-M2.5` / `MiniMax-M2.7` 返回 `code 2069 model no longer available`；
* 唯一剩余阻塞点是**账户余额**（HTTP 402 / 业务码 1008）。

**这不影响「模型参与代码修改」这一事实**：模型参与由 §4.3 的摘要链证明，
HTTP API 的失败被单独记录在 `api-attempt.json`，并原样附在被应用的回答上
（`response.json` 的 `api_attempt` 字段）。两者不会混淆。

额度恢复后重跑同一条流水线即可改为由 API 直接产出代码，链路完全一致。

### 4.5 不记录密钥，也不记录模型的私有思维链

* `request.json` / `response.json` 中 `api_key` 字段被写为 `<redacted>`，密钥从不落盘；
* MiniMax 客户端在返回前就丢弃 `reasoning_content` 字段，只保留公开元数据
  （`model` / `usage` / `finish_reason` / `request_id` / `content`）；
* 会话模型路径同样只保留公开回答文本与其摘要。

**产物**（`artifacts/minimax/`）：

| 文件 | 内容 |
| --- | --- |
| `request.json` | 真实发出的任务、上下文包、完整提示词、系统提示词、模型与端点 |
| `api-attempt.json` | HTTP API 的真实失败载荷（余额不足） |
| `response.json` | **被应用的模型回答**，含 `answer_sha256` / `prompt_sha256` / `context_pack_sha256` / `api_attempt` |
| `code.diff` | 应用到工作区的真实 diff |

---

## 要求 5 · 保留改动前后快照与同一套目标测试，证明「改前失败、改后通过、回归仍通过」

**命令**：

```bash
.venv/Scripts/python.exe scripts/run_e2e.py --storage embedded \
    --model-answer model/SPEC-BILL-001-pricing.session-model.txt \
    --model-id "MiniMax-M3.1-Flash"
```

**实际输出**（`artifacts/e2e-steps.json` 与 `artifacts/tests/*.txt`）：

```
[OK ] ingest corpus into PowerContext (exit=0) scope=scp_6d4rq92ngwcnzytn87ebhqyqr3 records=47 {'spec_section': 12, 'code_symbol': 9, 'test_case': 26}
[OK ] retrieve development context (exit=0) specs=12 code=7 functional=6 regression=20
[OK ] write task progress into PowerContext (exit=0) artifacts=['art_9efbf4e29d884a38afedab6e1a4a0f7d', 'art_53f0e1c3229f4493b78c3e36c4b8a684']
[FAIL] test suite before the change (exit=1) log=artifacts/tests/before.txt duration=1.64s code_sha256=6a69111712e47e79 git_commit=87da1afaf4bb dirty=false
[OK ] regression suite before the change (exit=0) log=artifacts/tests/before-regression.txt duration=1.00s code_sha256=6a69111712e47e79 git_commit=87da1afaf4bb dirty=false
[FAIL] target functional suite before the change (exit=1) log=artifacts/tests/before-functional.txt duration=1.11s code_sha256=6a69111712e47e79 git_commit=87da1afaf4bb dirty=false
[FAIL] MiniMax code generation (exit=4) error=insufficient balance (1008) code=1008 http=402
[OK ] apply the session model answer to the working tree (exit=0) log=artifacts/tests/apply.txt duration=1.82s
[OK ] test suite after the change (exit=0) log=artifacts/tests/after.txt duration=0.93s code_sha256=baf6875696275ace git_commit=87da1afaf4bb dirty=true
[OK ] regression suite after the change (exit=0) log=artifacts/tests/after-regression.txt duration=1.01s code_sha256=baf6875696275ace git_commit=87da1afaf4bb dirty=true
[OK ] target functional suite after the change (exit=0) log=artifacts/tests/after-functional.txt duration=0.96s code_sha256=baf6875696275ace git_commit=87da1afaf4bb dirty=true
[OK ] write the after-change verification result into PowerContext (exit=0) artifact=art_f6be5372c59044be9c809cc68a78213a
[OK ] restore the pre-change working tree (exit=0) restored_trees=3
[OK ] retrieve the context again with the stored progress (exit=0) prior_progress=3 specs=12 code=7 functional=6 regression=20
```

14 个步骤中 11 个退出码为 0，3 个非 0：两个是**改动前的目标功能测试**（预期失败，
正是需求 5 要证明的「改前未实现」），一个是 **MiniMax HTTP API 调用**
（账户余额不足的真实错误）。

### 5.1 改动前：目标功能失败，回归通过

`artifacts/tests/before-functional.txt`：

```
FAILED tests/test_pricing.py::test_promo_code_applies_a_percentage_discount_before_tax
FAILED tests/test_pricing.py::test_promo_discount_is_capped_by_the_maximum_discount
FAILED tests/test_pricing.py::test_promo_without_code_keeps_the_discount_at_zero
FAILED tests/test_pricing.py::test_unknown_promo_code_is_rejected - AttributeError
FAILED tests/test_pricing.py::test_expired_promo_code_is_rejected - AttributeError
FAILED tests/test_pricing.py::test_promo_errors_are_pricing_errors - AttributeError
====================== 6 failed, 20 deselected in 0.10s =======================
```

即**目标能力尚未实现**（`promo_code` 参数与 `UnknownPromoError` 不存在），
而 20 个回归用例在改动前就全部通过（`before-regression.txt`：
`20 passed, 6 deselected`）。全量套件在改动前是 `6 failed, 20 passed`。

### 5.2 改动后：全部通过

| 日志 | 结果 |
| --- | --- |
| `artifacts/tests/after.txt` | `26 passed` |
| `artifacts/tests/after-functional.txt` | `6 passed, 20 deselected` |
| `artifacts/tests/after-regression.txt` | `20 passed, 6 deselected` |

**同一套测试**（`python -m pytest` + `-k regression` + `-k promo`）在改动前后各跑一次，
只有目标文件被换掉。

### 5.3 对应的代码版本

每一步测试都记录了它跑在哪份代码上
（`artifacts/tests/code-version-before.json` / `code-version-after.json`）：

| | `src/billing/pricing.py` SHA-256 | git commit | 工作区 |
| --- | --- | --- | --- |
| 改动前 | `6a69111712e47e79ec9a207e7d7c4f33590b7fbf0ff1919d5d3505bbeb01b94c` | `87da1afaf4bb276d0fd6b0841d650a12fd831efe` | clean |
| 改动后 | `baf6875696275ace7770ace5ae78f0224c27b1271d163ac0b1cb6bd911988210` | `87da1afaf4bb276d0fd6b0841d650a12fd831efe` | dirty（模型改动尚未提交） |

**代码快照**：`artifacts/snapshots/before/` 与 `artifacts/snapshots/after/`
（`src/`、`specs/`、`tests/` 三棵目录树，不含 `__pycache__`）。

### 5.4 「改动后代码的来源」

本轮来源是 **MiniMax 模型回答**，产物中明确标注：

```json
{
  "code_source": "minimax-session-model",
  "model": "MiniMax-M3.1-Flash",
  "answer_sha256": "d67f92c20af366b16b964981c163622a45b8688250198b45547c66eeb24d3a03"
}
```

`reference/pricing_promo.py` 是手写参考实现，**本轮没有被应用**；
它只在完全离线时作为兜底（`--code-source reference`），
此时产物中会以 `code_source: "reference"` 明确标注，不会与模型产出混淆。
参考实现的作用是证明 `SPEC-BILL-001` 可实现，并让离线环境也能复现「改前失败 / 改后通过」。

脚本运行结束会把工作区还原为改动前状态，因此可以重复执行。

---

## 要求 6 · 真正使用 PowerContext 保存进度与验证结果；空状态起步、模块重启后读回并复用

**命令**：

```bash
.venv/Scripts/python.exe scripts/prove_restart_persistence.py --storage embedded
```

**实际输出**：

```json
{
  "empty_state_confirmed": true,
  "progress_survived_restart": true,
  "server_process_was_restarted": true,
  "progress_reused_in_next_context": true,
  "passed": true
}
```

完整记录见 `artifacts/restart/restart-proof.md` 与 `restart-proof.json`。真实过程：

1. **空状态**：脚本使用自己的数据目录 `.runtime/seekdb-restart-proof`，
   运行前先整个删除（`storage.cold_start = true`），
   再新建作用域 `scp_6bhfkc6vv9b769rxb5aj7qrwfn`，
   `POST /v1/memory/entries/list` 返回 `entry_count: 0`；
2. **写入**：把任务进度与验证结果写入 Atomic Memory，
   得到 `art_3428e17e8f724126bf4fd8818215f267`（progress）与
   `art_f99e853010644f5696715f1b63b19c85`（verification），revision 均为 1；
3. **重启前读回**：2 条，artifact_id 与文本完全一致；
4. **模块重启**：`SIGTERM` 结束 PowerContext Server 进程（PID 12560 → 3020），
   再以同一环境文件重新启动，`service_instance_id` 随之改变；
   **嵌入式模式下这个数据目录由服务独占，进程退出时 seekdb 引擎一并停机，
   第二次启动是真正的冷启动**（不是挂到一个仍在运行的实例上）；
5. **重启后读回**：仍是同样 2 条，artifact_id / revision / text / state 逐字段一致；
6. **直查数据库**（`artifacts/restart/restart-proof.json` 的 `sql-check-*` 步骤，
   实际 SQL 结果，重启前后完全相同）：

```
art_3428e17e8f724126bf4fd8818215f267	1	progress
art_f99e853010644f5696715f1b63b19c85	1	verification
```

7. **复用**：重启后执行 `query`，上下文包中 `prior_progress` 带上这两条进度，
   并与从数据库读回的规格 / 代码 / 测试共同构成下一次开发的上下文：

```
corpus_size = 47
files_to_modify = ["src/billing/pricing.py"]
applicable_spec_sections = 12
functional_tests = 6
regression_tests = 20
prior_progress = [verification, progress]
```

> 说明：PowerContext Server 收到 `SIGTERM` 后以退出码 1 结束，这是它自身的关闭
> 行为，不代表数据丢失——数据落在 seekdb 的 `pc_atomic_memory_current` 表中，
> 与进程无关。嵌入式模式另有一个必须显式提交的细节：seekdb 的握手不返回
> autocommit 状态，直连数据库的写操作必须自己 `COMMIT`，
> 否则会在句柄关闭时被回滚——`sddctx/sqlprobe.py` 已统一补上这一步。

---

## 要求 7 · 源码、依赖与版本、配置与初始化步骤、验证样例、预期结果、重置方法、技术使用记录、一页技术说明

| 内容 | 位置 |
| --- | --- |
| 完整源码 | `minimax/sddctx/`、`minimax/sample/`、`minimax/scripts/`、`minimax/reference/` |
| 依赖与版本 | `docs/01-setup.md` §1 |
| 配置与初始化步骤 | `docs/01-setup.md` §2 |
| 验证样例与预期结果 | 本文 `docs/03-verification.md` |
| 重置方法 | `docs/04-reset.md` |
| 技术使用记录 | `docs/05-usage-record.md` |
| 一页技术说明 | `docs/06-technical-note.md` |
| 配置模板（仅占位值） | `minimax/env/server.env.example`、`minimax/env/server.embedded-seekdb.env.example` |

仓库中**不含任何真实凭据**：`minimax/.runtime/` 被 `.gitignore` 忽略，
`minimax/env/*.env.example` 中所有连接串均为占位符。

---

## 要求 8 · 端到端验证与未完成项的真实记录

**已完成的端到端验证**：见 `artifacts/e2e-steps.json`，14 个步骤中 11 个退出码为 0、
3 个非 0——两个是改动前的目标功能测试（预期失败），一个是 MiniMax HTTP API 调用（真实错误）。

**未完成项**（真实错误，非伪造）：

| 未完成项 | 真实错误 | 证据 |
| --- | --- | --- |
| 由 MiniMax **HTTP API** 直接产出代码 | HTTP 402 / 业务码 1008 `insufficient balance` | `artifacts/minimax/api-attempt.json` |

**「模型参与代码修改」本身已完成**：代码由会话内的 MiniMax 模型
（`MiniMax-M3.1-Flash`）依据检索到的上下文撰写，
摘要链见本文 §4.3，diff 见 `artifacts/minimax/code.diff`。

详见 `docs/07-open-issues.md`。

---

## 证据文件索引

| 文件 | 内容 |
| --- | --- |
| `artifacts/e2e-steps.json` | 端到端每一步的命令、退出码、时间、代码版本 |
| `artifacts/ingest-report.json` | 导入 PowerContext 的 47 条记录及其 `source_id` / `db_position` |
| `artifacts/minimax-status.json` | 本次运行的模型状态、代码来源与改动前后的退出码 |
| `artifacts/context/pack-001.json` | 上下文包（含出处），`prior_progress` 为空 |
| `artifacts/context/pack-001.md` | 上下文包的人类可读报告 |
| `artifacts/context/prompt-001.md` | 实际发给模型的提示词（494 行） |
| `artifacts/context/pack-002.{json,md}` | 写入进度后再次检索的上下文包，`prior_progress` 为 3 条 |
| `artifacts/minimax/request.json` | MiniMax 请求记录（密钥已脱敏） |
| `artifacts/minimax/api-attempt.json` | HTTP API 的真实失败载荷 |
| `artifacts/minimax/response.json` | **被应用的模型回答**及其三个摘要 |
| `artifacts/minimax/code.diff` | 模型回答应用到工作区的 diff |
| `artifacts/progress-written.json` | 写入 Atomic Memory 的改动前进度条目 |
| `artifacts/progress-written-after.json` | 写入 Atomic Memory 的改动后验证条目 |
| `artifacts/tests/before*.txt` | 改动前的三组测试输出 |
| `artifacts/tests/after*.txt` | 改动后的三组测试输出 |
| `artifacts/tests/code-version-*.json` | 两组测试各自对应的代码版本（文件 SHA-256 + git commit） |
| `artifacts/snapshots/before/` `after/` | 改动前后的代码快照 |
| `artifacts/restart/restart-proof.{json,md}` | 重启持久化验证记录（含直查数据库结果） |
| `artifacts/spec-revision/spec-revision-proof.json` | 规格修订验证记录 |
| `artifacts/spec-revision/report-before.md` `report-after.md` | 修订前后的检索报告 |
| `model/SPEC-BILL-001-pricing.session-model.txt` | MiniMax 模型的原始回答（提交入库） |
