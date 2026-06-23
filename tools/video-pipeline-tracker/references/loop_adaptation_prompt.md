# Loop 适配提示词模板

把下面提示词发给需要接入 Dashboard 的 loop 维护者或编码代理。替换 `{{OWNER}}`、`{{UID}}`、`{{LOOP_NAME}}`、`{{DAILY_TARGET}}`、`{{PUBLISH_START_TIME}}`。

```text
你要把当前 loop 接入 video-pipeline-tracker skill。接入目标不是只写运行日志，而是必须让 AI Loop Dashboard 的 owner_loop_node_metrics 能展示本轮选剧、AI工具、剪辑状态、发布时间、发布状态。

请按以下要求适配：

1. 每轮或每 30 分钟产出 runtime/tasks.json，格式为 {"rows":[...]}。它必须是当天任务全量快照，重复上报同一个 task_id 时更新同一条任务。

2. 每条任务必须包含这些顶层字段：
   - task_id：稳定唯一 ID，不能每次随机变化
   - date：业务日期 YYYY-MM-DD
   - assignee：负责人姓名，必须精确等于 "{{OWNER}}"
   - uid：负责人 UID，必须精确等于 "{{UID}}"
   - loop_name：必须精确等于 "{{LOOP_NAME}}"
   - round_name：当前轮次
   - social_account_id / channel_id / douyin_t8_account / uid 至少一个账号 key
   - drama_name：短剧名
   - clip_tool：剪辑工具，例如 auto_editing / beidou_smart_clip / yc-animation
   - clip_status 或 clip_last_status 或 clip_end_time/output_size_mb/social_post_id：剪辑状态证据
   - publish_status：success / failed / pending / reviewing / cancelled
   - short_link_publish_time：发布时间或预发布时间
   - daily_publish_target：当天目标
   - publish_start_time 或 publish_schedule_start_time
   - publish_interval_sec 或 publish_account_interval_seconds

3. 如果需要策略归因，执行前先调用 claim_strategy_binding.py，拿到 runtime/strategy-context.json，并在上报时传 --strategy-context runtime/strategy-context.json。

4. 先执行 dry-run，不加 --execute：

python3 video-pipeline-tracker/scripts/report_half_hour_loop.py \
  --tasks runtime/tasks.json \
  --owner "{{OWNER}}" \
  --uid "{{UID}}" \
  --loop-name "{{LOOP_NAME}}" \
  --round-name "<round-name>" \
  --daily-target {{DAILY_TARGET}} \
  --publish-start-time "{{PUBLISH_START_TIME}}" \
  --publish-interval-seconds 120 \
  --output-dir runtime/half-hour-reports \
  --strict

5. dry-run 必须确认：
   - validation.errors = []
   - push_result.dashboard_gate.ok = true
   - sample_task.assignee = "{{OWNER}}"
   - sample_task.uid = "{{UID}}"
   - sample_task.loop_name = "{{LOOP_NAME}}"
   - sample_task.drama_name 有值
   - sample_task.clip_tool 有值
   - sample_event.metric_json 包含 round_selected_drama_count、round_target_account_count、clip_done_count、publish_scheduled_count、unpublished_target_gap_count

6. dry-run 通过后才能加 --execute：

python3 video-pipeline-tracker/scripts/report_half_hour_loop.py \
  --tasks runtime/tasks.json \
  --owner "{{OWNER}}" \
  --uid "{{UID}}" \
  --loop-name "{{LOOP_NAME}}" \
  --round-name "<round-name>" \
  --daily-target {{DAILY_TARGET}} \
  --publish-start-time "{{PUBLISH_START_TIME}}" \
  --publish-interval-seconds 120 \
  --output-dir runtime/half-hour-reports \
  --strict \
  --execute

7. execute 后必须确认：
   - push_result.ingest_verification.ok = true
   - video_pipeline_tasks 中能查到 assignee="{{OWNER}}" 且 uid="{{UID}}" 的今日任务
   - /api/dashboard 的 owner_loop_node_metrics 中出现 owner="{{OWNER}}"

如果只能写 ai_loop_runtime_events，但不能写 video_pipeline_tasks，则不算完成接入。Dashboard 仍会显示无 pipeline 任务明细。
```
