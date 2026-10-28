# PowerContext 重启持久化验证记录 / Restart persistence proof

- 生成时间 / generated at: 2026-10-28T15:33:12.424466+00:00
- 验证作用域 / proof scope: `scp_6bhfkc6vv9b769rxb5aj7qrwfn`
- 服务端口 / server port: 8011
- 存储模式 / storage mode: `embedded`
- 冷启动 / cold start: True
- 重启前后进程号 / server pids: 12560 -> 3020

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
- 时间 / timestamp: 2026-10-28T15:32:56.727298+00:00
- 详情 / detail:
```json
{
  "pid": 12560,
  "server_info": {
    "schema_version": {
      "major": 1,
      "minor": 0
    },
    "product": "powercontext",
    "server_id": "3fea6c1e-2853-4f0d-8cf9-35d57696f49a",
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
    "service_instance_id": "04aa6a783efd4653a9e9691a6eec96bc",
    "service_version": "1.4.1.dev180+gcd1b5e3f5"
  }
}
```

### empty-state-before-write

- 命令 / command: `POST /v1/memory/entries/list (scope=scp_6bhfkc6vv9b769rxb5aj7qrwfn)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T15:32:59.478686+00:00
- 条目 / entries:

### ingest-corpus-into-proof-scope

- 命令 / command: `POST /v1/sources/content (scope=scp_6bhfkc6vv9b769rxb5aj7qrwfn)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T15:32:59.478686+00:00
- 详情 / detail:
```json
{
  "record_count": 47,
  "first_source_id": "sddctx:v1:spec_section:SPEC-BILL-001#背景-background:5d4baa04af01"
}
```

### write-progress

- 命令 / command: `POST /v1/memory/remember (scope=scp_6bhfkc6vv9b769rxb5aj7qrwfn)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T15:32:59.478686+00:00
- 写入 / written:
  - `progress` artifact=`art_3428e17e8f724126bf4fd8818215f267` revision=1: SDD 任务进度：在 billing.pricing.compute_invoice_totals 中实现促销码折扣，折扣上限取自促销码目录，税额按折后金额计算。
  - `verification` artifact=`art_f99e853010644f5696715f1b63b19c85` revision=1: 验证结果：改动前目标功能测试失败 (promo 能力未实现)，回归测试通过；改动后目标功能测试与回归测试全部通过。

### read-back-before-restart

- 命令 / command: `POST /v1/memory/entries/list (scope=scp_6bhfkc6vv9b769rxb5aj7qrwfn)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T15:32:59.478686+00:00
- 条目 / entries:
  - `progress` artifact=`art_3428e17e8f724126bf4fd8818215f267` revision=1 state=active: SDD 任务进度：在 billing.pricing.compute_invoice_totals 中实现促销码折扣，折扣上限取自促销码目录，税额按折后金额计算。
  - `verification` artifact=`art_f99e853010644f5696715f1b63b19c85` revision=1 state=active: 验证结果：改动前目标功能测试失败 (promo 能力未实现)，回归测试通过；改动后目标功能测试与回归测试全部通过。

### sql-check-before-restart

- 命令 / command: `SELECT ... FROM powercontext_sdd.pc_atomic_memory_current (storage=embedded)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T15:32:59.515380+00:00
- 数据库直查 / direct SQL rows:
```
art_3428e17e8f724126bf4fd8818215f267	1	progress
art_f99e853010644f5696715f1b63b19c85	1	verification
```

### stop-server

- 命令 / command: `kill -TERM 12560`
- 退出码 / exit code: `1`
- 时间 / timestamp: 2026-10-28T15:32:59.518378+00:00
- 详情 / detail:
```json
{
  "stopped": true,
  "signal": "SIGTERM",
  "exit_code": 1,
  "pid": 12560,
  "started_at": "2026-10-28T15:32:33.805693+00:00",
  "stopped_at": "2026-10-28T15:32:59.518378+00:00"
}
```

### start-server-2

- 命令 / command: `powercontext server run --env-file D:\.hyper\project\OceanBase\PowerContext-minimax\minimax\.runtime\server-restart-proof.env --port 8011`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T15:33:12.257579+00:00
- 详情 / detail:
```json
{
  "pid": 3020,
  "server_info": {
    "schema_version": {
      "major": 1,
      "minor": 0
    },
    "product": "powercontext",
    "server_id": "3fea6c1e-2853-4f0d-8cf9-35d57696f49a",
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
    "service_instance_id": "e8821a49928e421ab5083a052e8afd76",
    "service_version": "1.4.1.dev180+gcd1b5e3f5"
  }
}
```

### read-back-after-restart

- 命令 / command: `POST /v1/memory/entries/list (scope=scp_6bhfkc6vv9b769rxb5aj7qrwfn)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T15:33:12.350949+00:00
- 条目 / entries:
  - `progress` artifact=`art_3428e17e8f724126bf4fd8818215f267` revision=1 state=active: SDD 任务进度：在 billing.pricing.compute_invoice_totals 中实现促销码折扣，折扣上限取自促销码目录，税额按折后金额计算。
  - `verification` artifact=`art_f99e853010644f5696715f1b63b19c85` revision=1 state=active: 验证结果：改动前目标功能测试失败 (promo 能力未实现)，回归测试通过；改动后目标功能测试与回归测试全部通过。

### sql-check-after-restart

- 命令 / command: `SELECT ... FROM powercontext_sdd.pc_atomic_memory_current (storage=embedded)`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T15:33:12.369715+00:00
- 数据库直查 / direct SQL rows:
```
art_3428e17e8f724126bf4fd8818215f267	1	progress
art_f99e853010644f5696715f1b63b19c85	1	verification
```

### reuse-progress-in-next-context

- 命令 / command: `python -m sddctx query --task '实现发票促销码折扣并保持金额不变量'`
- 退出码 / exit code: `0`
- 时间 / timestamp: 2026-10-28T15:33:12.420798+00:00
- 复用上下文 / reused progress: corpus=47 files_to_modify=['src/billing/pricing.py'] spec_sections=12 functional_tests=6 regression_tests=20
  - `progress` SDD 任务进度：在 billing.pricing.compute_invoice_totals 中实现促销码折扣，折扣上限取自促销码目录，税额按折后金额计算。
  - `verification` 验证结果：改动前目标功能测试失败 (promo 能力未实现)，回归测试通过；改动后目标功能测试与回归测试全部通过。

### stop-server-2

- 命令 / command: `kill -TERM`
- 退出码 / exit code: `1`
- 时间 / timestamp: 2026-10-28T15:33:12.424466+00:00
- 详情 / detail:
```json
{
  "stopped": true,
  "signal": "SIGTERM",
  "exit_code": 1,
  "pid": 3020,
  "started_at": "2026-10-28T15:32:59.533691+00:00",
  "stopped_at": "2026-10-28T15:33:12.424466+00:00"
}
```

## 说明 / Notes

- 服务进程收到 SIGTERM 后以退出码 1 结束，这是 PowerContext Server 自身的关闭行为，不代表数据丢失；数据保存在 seekdb 的 `pc_atomic_memory_current` 表中。
- `server_id` 与 `service_instance_id` 中的服务实例号在重启后改变，证明服务确实被重新启动，而不是复用了旧进程。
