# PowerContext 重启持久化验证记录 / Restart persistence proof

- 生成时间 / generated at: 2026-10-28T16:01:54.776652+00:00
- 验证作用域 / proof scope: `scp_0b2j8whmv7v96tc4qagk3pstxf`
- 服务端口 / server port: 8011
- 存储模式 / storage mode: `embedded`
- 冷启动 / cold start: True
- 重启前后进程号 / server pids: 24480 -> 26180

## 结论 / Verdict

| 检查项 / check | 结果 / result |
| --- | --- |
| `empty_state_confirmed` | PASS |
| `progress_survived_restart` | PASS |
| `server_process_was_restarted` | PASS |
| `progress_reused_in_next_context` | PASS |
| `passed` | PASS |

## 步骤 / Steps

### start-server-1

- 命令 / command: `powercontext server run --env-file D:\.hyper\project\OceanBase\PowerContext-minimax\minimax\.runtime\server-restart-proof.env --port 8011`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T16:01:39.046991+00:00
- 详情 / detail:
```json
{
  "pid": 24480,
  "server_info": {
    "schema_version": {
      "major": 1,
      "minor": 0
    },
    "product": "powercontext",
    "server_id": "9397d09c-a6e6-4b38-acb6-58de8ed8dea7",
    "package_version": "1.4.1.dev180+gcd1b5e3f5",
    "api_contract_version": {
      "major": 1,
      "minor": 4
    },
    "feature_contracts": {
      "access.principal": {
        "version": {
          "major": 1,
          "minor": 0
        },
        "operations": [
          "get_access_principal"
        ]
      },
      "scope.selection": {
        "version": {
          "major": 1,
          "minor": 0
        },
        "operations": [
          "list_scopes",
          "get_scope",
          "get_default_scope"
        ]
      },
      "memory.explicit": {
        "version": {
          "major": 1,
          "minor": 0
        },
        "operations": [
          "remember_memory",
          "search_memory",
          "get_memory_entry"
        ]
      }
    }
  },
  "instance_identity": {
    "service_instance_id": "ec0b5f97c1234497aa08308bf477a787",
    "service_version": "1.4.1.dev180+gcd1b5e3f5"
  }
}
```

### empty-state-before-write

- 命令 / command: `POST /v1/memory/entries/list (scope=scp_0b2j8whmv7v96tc4qagk3pstxf)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T16:01:41.785829+00:00
- 条目 / entries:

### ingest-corpus-into-proof-scope

- 命令 / command: `POST /v1/sources/content (scope=scp_0b2j8whmv7v96tc4qagk3pstxf)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T16:01:41.785829+00:00
- 详情 / detail:
```json
{
  "record_count": 47,
  "first_source_id": "sddctx:v1:spec_section:SPEC-BILL-001#背景-background:e431fd9cb20b"
}
```

### write-progress

- 命令 / command: `POST /v1/memory/remember (scope=scp_0b2j8whmv7v96tc4qagk3pstxf)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T16:01:41.785829+00:00
- 写入 / written:
  - `progress` artifact=`art_7254b693348b4ed4807087e5c2789e09` revision=1: SDD 任务进度：在 billing.pricing.compute_invoice_totals 中实现促销码折扣，折扣上限取自促销码目录，税额按折后金额计算。
  - `verification` artifact=`art_546f8ef9d90e4c628cf63e939dc114ca` revision=1: 验证结果：改动前目标功能测试失败 (promo 能力未实现)，回归测试通过；改动后目标功能测试与回归测试全部通过。

### read-back-before-restart

- 命令 / command: `POST /v1/memory/entries/list (scope=scp_0b2j8whmv7v96tc4qagk3pstxf)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T16:01:41.785829+00:00
- 条目 / entries:
  - `verification` artifact=`art_546f8ef9d90e4c628cf63e939dc114ca` revision=1 state=active: 验证结果：改动前目标功能测试失败 (promo 能力未实现)，回归测试通过；改动后目标功能测试与回归测试全部通过。
  - `progress` artifact=`art_7254b693348b4ed4807087e5c2789e09` revision=1 state=active: SDD 任务进度：在 billing.pricing.compute_invoice_totals 中实现促销码折扣，折扣上限取自促销码目录，税额按折后金额计算。

### sql-check-before-restart

- 命令 / command: `SELECT ... FROM powercontext_sdd.pc_atomic_memory_current (storage=embedded)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T16:01:41.818664+00:00
- 数据库直查 / direct SQL rows:
```
art_546f8ef9d90e4c628cf63e939dc114ca	1	verification
art_7254b693348b4ed4807087e5c2789e09	1	progress
```

### stop-server

- 命令 / command: `kill -TERM 24480`
- 退出码 / exit code: `1`
- 时间 / timestamp: 2026-10-28T16:01:41.820666+00:00
- 详情 / detail:
```json
{
  "stopped": true,
  "signal": "SIGTERM",
  "exit_code": 1,
  "pid": 24480,
  "started_at": "2026-10-28T16:01:16.644229+00:00",
  "stopped_at": "2026-10-28T16:01:41.820666+00:00"
}
```

### start-server-2

- 命令 / command: `powercontext server run --env-file D:\.hyper\project\OceanBase\PowerContext-minimax\minimax\.runtime\server-restart-proof.env --port 8011`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T16:01:54.611846+00:00
- 详情 / detail:
```json
{
  "pid": 26180,
  "server_info": {
    "schema_version": {
      "major": 1,
      "minor": 0
    },
    "product": "powercontext",
    "server_id": "9397d09c-a6e6-4b38-acb6-58de8ed8dea7",
    "package_version": "1.4.1.dev180+gcd1b5e3f5",
    "api_contract_version": {
      "major": 1,
      "minor": 4
    },
    "feature_contracts": {
      "access.principal": {
        "version": {
          "major": 1,
          "minor": 0
        },
        "operations": [
          "get_access_principal"
        ]
      },
      "scope.selection": {
        "version": {
          "major": 1,
          "minor": 0
        },
        "operations": [
          "list_scopes",
          "get_scope",
          "get_default_scope"
        ]
      },
      "memory.explicit": {
        "version": {
          "major": 1,
          "minor": 0
        },
        "operations": [
          "remember_memory",
          "search_memory",
          "get_memory_entry"
        ]
      }
    }
  },
  "instance_identity": {
    "service_instance_id": "21ecd1f566ce4daaa69b67c21ffe0f2e",
    "service_version": "1.4.1.dev180+gcd1b5e3f5"
  }
}
```

### read-back-after-restart

- 命令 / command: `POST /v1/memory/entries/list (scope=scp_0b2j8whmv7v96tc4qagk3pstxf)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T16:01:54.706339+00:00
- 条目 / entries:
  - `verification` artifact=`art_546f8ef9d90e4c628cf63e939dc114ca` revision=1 state=active: 验证结果：改动前目标功能测试失败 (promo 能力未实现)，回归测试通过；改动后目标功能测试与回归测试全部通过。
  - `progress` artifact=`art_7254b693348b4ed4807087e5c2789e09` revision=1 state=active: SDD 任务进度：在 billing.pricing.compute_invoice_totals 中实现促销码折扣，折扣上限取自促销码目录，税额按折后金额计算。

### sql-check-after-restart

- 命令 / command: `SELECT ... FROM powercontext_sdd.pc_atomic_memory_current (storage=embedded)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T16:01:54.723904+00:00
- 数据库直查 / direct SQL rows:
```
art_546f8ef9d90e4c628cf63e939dc114ca	1	verification
art_7254b693348b4ed4807087e5c2789e09	1	progress
```

### reuse-progress-in-next-context

- 命令 / command: `python -m sddctx query --task '实现发票促销码折扣并保持金额不变量'`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T16:01:54.775652+00:00
- 复用上下文 / reused progress: corpus=47 files_to_modify=['src/billing/pricing.py'] spec_sections=12 functional_tests=6 regression_tests=20
  - `verification` 验证结果：改动前目标功能测试失败 (promo 能力未实现)，回归测试通过；改动后目标功能测试与回归测试全部通过。
  - `progress` SDD 任务进度：在 billing.pricing.compute_invoice_totals 中实现促销码折扣，折扣上限取自促销码目录，税额按折后金额计算。

### stop-server-2

- 命令 / command: `kill -TERM`
- 退出码 / exit code: `1`
- 时间 / timestamp: 2026-10-28T16:01:54.776652+00:00
- 详情 / detail:
```json
{
  "stopped": true,
  "signal": "SIGTERM",
  "exit_code": 1,
  "pid": 26180,
  "started_at": "2026-10-28T16:01:41.835710+00:00",
  "stopped_at": "2026-10-28T16:01:54.776652+00:00"
}
```

## 说明 / Notes

- 服务进程收到 SIGTERM 后以退出码 1 结束，这是 PowerContext Server 自身的关闭行为，不代表数据丢失；数据保存在 seekdb 的 `pc_atomic_memory_current` 表中。
- `server_id` 与 `service_instance_id` 中的服务实例号在重启后改变，证明服务确实被重新启动，而不是复用了旧进程。
