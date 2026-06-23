---
name: fb-account-tag-pipeline
description: >-
  Facebook 账号打标独立技能包：手机号批量登录打标、social-list 过滤、合并 YYYYMMDD.csv、
  单号重跑、替换主表。包目录 d:/桌面文件/fb-account-tag-pipeline，可用 vendor 脱离 ai-loop
  仓库路径。用户提到账号打标、batch_tag_by_phones、打标表、合并主表时使用。
---

# Facebook 账号打标流水线（独立包）

**包根目录**：`d:\桌面文件\fb-account-tag-pipeline`（可整体复制到任意路径）

## 安装（首次）

```powershell
cd d:\桌面文件\fb-account-tag-pipeline
copy .env.example .env
copy config\phones.example.txt config\phones.txt
python scripts/sync_from_ai_loop.py --source "d:\桌面文件\ai-loop"
```

`vendor/ai-loop` 同步后，**无需打开 ai-loop 仓库**即可打标。

## 快速运行

```powershell
cd d:\桌面文件\fb-account-tag-pipeline

# 批量打标 → runs/latest/{YYYYMMDD}.csv
python scripts/run_batch.py

# 透传参数
python scripts/run_batch.py --outdir runs/my_run --skip-db-import
```

## 在 ai-loop 内直接跑（可选）

若未 sync vendor，设置 `.env` 中 `AI_LOOP_ROOT` 指向 ai-loop 根目录，或在 ai-loop 内：

```powershell
cd d:\桌面文件\ai-loop
python scripts/batch_tag_by_phones.py --phones ... --code 951103 --skip-apify
```

## 流水线

1. 登录 → social-list 白名单
2. 隔离 allocation → `account_tag_audit --daily`
3. social-list 过滤 → clean CSV
4. 合并 `{YYYYMMDD}.csv` + `_en.csv`

## 产出

| 文件 | 说明 |
|------|------|
| `{YYYYMMDD}.csv` | 中文合并表（agent_id + 33 列） |
| `{YYYYMMDD}_en.csv` | DB 英文列 |
| `summary.json` | `facebook_count` / `filtered_rows` |

`filtered=N` = **保留行数**。`filtered≈fb` 为正常。

## 单号重跑 + 替换主表

```powershell
python scripts/run_batch.py --phones config/rerun_one.txt --outdir runs/rerun_PHONE

python scripts/merge_agent_into_main.py `
  --main runs/all/20260622.csv `
  --patch runs/rerun_PHONE/20260622.csv `
  --agent-id 67020404
```

## 数据完整性

- 默认近 **30 天**（`LOOKBACK_DAYS=30`）；分页无上限，窗口内拉全
- 跑完查 `fetch_complete`；播放量对账看 `platform_total_views_api`

## 文档

- [README.md](README.md) — 安装与目录
- [references/troubleshooting.md](references/troubleshooting.md)
- [references/field-rules.md](references/field-rules.md)
- [references/runtime-config.md](references/runtime-config.md)

## Agent 清单

1. `cd` 到独立包根目录（或 ai-loop + AI_LOOP_ROOT）
2. 确认 `vendor/ai-loop` 或 `AI_LOOP_ROOT` 可用
3. **执行** `run_batch.py` 或 `batch_tag_by_phones.py`
4. 读 `summary.json` 汇报；检查 `fetch_complete`
5. 需替换时用 `merge_agent_into_main.py`
