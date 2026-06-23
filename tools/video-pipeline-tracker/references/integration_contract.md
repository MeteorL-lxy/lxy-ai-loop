# Loop 接入契约

这份契约用于把任意短剧/视频 loop 接入 AI Loop Dashboard。接入方只需要产出标准任务 JSON，再用本 skill 的脚本自检和回写。

## 最小接入流程

1. loop 每轮生成任务结果 JSON，格式为对象、数组，或 `{"rows":[...]}`。
2. 先本地校验：

```bash
python3 scripts/validate_loop_payload.py \
  --tasks runtime/tasks.json \
  --loop-name your-loop-name \
  --daily-target 300 \
  --publish-start-time "2026-06-22 19:00:00" \
  --publish-interval-seconds 120
```

3. 再 dry-run 回写，确认 `sample_task` 和 `sample_event.metric_json`：

```bash
python3 scripts/push_loop_result.py \
  --tasks runtime/tasks.json \
  --owner 负责人姓名 \
  --uid 负责人UID \
  --loop-name your-loop-name \
  --round-name round-20260622-01 \
  --daily-target 300 \
  --publish-start-time "2026-06-22 19:00:00" \
  --publish-interval-seconds 120 \
  -o runtime/normalized-result.json
```

4. dry-run 无 error 后追加 `--execute` 写入 Dashboard API。

## 半小时上报要求

所有接入方必须每 30 分钟上报一次当前 loop 快照。推荐做法是让 loop 持续维护一个当天任务状态 JSON，例如 `runtime/tasks.json`，每条任务使用稳定 `task_id`；半小时上报重复写同一批 `task_id` 时会更新状态，不会重复计数。

半小时上报脚本：

```bash
python3 scripts/report_half_hour_loop.py \
  --tasks runtime/tasks.json \
  --owner 负责人姓名 \
  --uid 负责人UID \
  --loop-name your-loop-name \
  --round-name round-20260622-01 \
  --daily-target 300 \
  --publish-start-time "2026-06-22 19:00:00" \
  --publish-interval-seconds 120 \
  --output-dir runtime/half-hour-reports \
  --execute
```

默认 `--window-mode previous`，即在整点或半点运行时，上报刚结束的 30 分钟窗口，同时生成一条 `ai_loop_runtime_events.event_type=loop_window_report` 事件。

如果 `runtime/tasks.json` 保存的是当天全量任务快照，默认不要加 `--filter-window`，这样每半小时上报的是“当前全量进度快照”，最适合 Dashboard 展示“今天目标还差多少”。如果只想上报窗口内发生变化的任务，再加 `--filter-window`。

crontab 示例：

```cron
*/30 * * * * cd /path/to/video-pipeline-tracker && /usr/bin/python3 scripts/report_half_hour_loop.py --tasks /path/to/your-loop/runtime/tasks.json --owner 负责人姓名 --loop-name your-loop-name --daily-target 300 --publish-start-time "2026-06-22 19:00:00" --publish-interval-seconds 120 --output-dir /path/to/your-loop/runtime/half-hour-reports --execute >> /path/to/your-loop/runtime/half-hour-report.log 2>&1
```

如果接入方不用 crontab，也可以在自己的 scheduler 里每 30 分钟调用同一条命令。

## 必填字段

| 字段 | 用途 | 示例 |
|------|------|------|
| task_id | 任务唯一 ID，重复则更新 | `loop-a:round-1:account-001:drama-a` |
| date | 业务日期 | `2026-06-22` |
| loop_name | loop 项目名 | `barry-shortdrama-loop` |
| round_name | 执行轮次 | `round-20260622-01` |
| assignee | 负责人 | `焦千为` |
| drama_name | 选剧名称 | `Love After So Long` |
| social_account_id / douyin_t8_account / channel_id / uid | 账号 key，至少一个 | `3951334425172613` |
| clip_tool | 剪辑工具 | `auto_editing` |
| publish_status | 原始发布状态 | `success` / `failed` / `pending` / `reviewing` / `cancelled` |

## 强烈建议字段

| 字段 | 用途 |
|------|------|
| short_link_publish_time | 预发布/排期判断依据 |
| daily_publish_target | 当天目标，用于计算未发布缺口 |
| publish_start_time / publish_schedule_start_time | loop 计划开始发布时间 |
| publish_interval_sec / publish_account_interval_seconds | 每个账号发布间隔 |
| clip_status / clip_last_status | 剪辑状态：`completed` / `queued` / `clipping` |
| clip_start_time / clip_end_time | 剪辑中/剪辑完成判断 |
| output_duration_sec / output_size_mb | 剪辑产物判断 |
| publish_fail_reason / clip_fail_reason | 失败原因和队列状态证据 |
| ab_group | A/B 分组 |
| source_type | 候选源类型 |
| strategy_binding_status | 策略绑定状态 |

## Dashboard 指标口径

| 指标 | 统计方式 |
|------|----------|
| 最近半小时选剧数 | 最近 30 分钟 `drama_name` 去重 |
| 本轮选剧数 | 最新 `round_name` 内 `drama_name` 去重 |
| 本轮要发账号 | 最新 `round_name` 内账号 key 去重 |
| AI 剪辑工具 | 最新轮次 `clip_tool` 去重 |
| 剪辑完成 | 有 `clip_status=completed`，或有 `clip_end_time/output/social_post_id`，或发布成功/审核中 |
| 排队中 | `clip_status=queued`、`clip_last_status=queued`，或原因包含 `last_status=queued` |
| 剪辑中 | 已开始但未完成、未失败、未排队 |
| 已发布 | 当天 `publish_status=success` |
| 预发布 | `short_link_publish_time` 有值且状态不是 failed/cancelled/error |
| 未发布 | `daily_publish_target - 已发布` |
| 发布时间 | 优先 `publish_start_time` / `publish_schedule_start_time`，其次最早 `short_link_publish_time` |

## 验收标准

接入方交付前至少跑通：

```bash
python3 scripts/validate_loop_payload.py --tasks runtime/tasks.json --loop-name your-loop-name --strict
python3 scripts/summarize_pipeline_metrics.py --input runtime/tasks.json --loop-name your-loop-name --format markdown
python3 scripts/push_loop_result.py --tasks runtime/tasks.json --owner 负责人姓名 --loop-name your-loop-name
```

通过标准：

- `validate_loop_payload.py` 无 errors；正式接入建议 strict 模式无 warnings。
- `summarize_pipeline_metrics.py` 能输出 Loop 节点指标，且选剧、账号、剪辑、发布、发布时间数字符合本轮业务预期。
- `push_loop_result.py` dry-run 中 `sample_event.metric_json` 包含 `round_selected_drama_count`、`round_target_account_count`、`clip_done_count`、`clip_queued_count`、`clipping_count`、`daily_publish_target`、`unpublished_target_gap_count`。
- `report_half_hour_loop.py` dry-run 能输出 `event_type=loop_window_report`，并在 `runtime/half-hour-reports` 生成 selected tasks 和 report JSON。

## 常见误用

- 不要把任务行数当短剧数；短剧数按 `drama_name` 去重。
- 不要把原始 `publish_status=pending` 当 dashboard 的“未发布”；未发布必须按每日目标减已发布。
- 不要把失败任务的未来 `short_link_publish_time` 计入有效预发布。
- 不要只把 `loop_name` 写进 `clip_params`；正式接入应写顶层 `loop_name`。
- 不要用不稳定的随机 ID 做 `task_id`；同一任务重复回写必须更新同一条记录。
