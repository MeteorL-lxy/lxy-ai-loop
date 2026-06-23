---
name: video-pipeline-tracker
description: "短视频生产全链路数据追踪与策略接入工具。当用户需要从 AI Loop 看板读取剪辑/发布/选号/选剧策略，给各自 loop 绑定策略，或抓取、解析、入库基础信息、选剧视频信息、剪辑信息、上传信息、发布信息、错误重试信息时使用。支持 API JSON、daily-loop telemetry、Markdown 报告解析，通过 HTTP API 写入看板数据库，并生成策略绑定、运行日志和统计摘要。触发词：短视频数据、生产链路、策略拉取、策略绑定、loop 策略、剪辑数据入库、发布追踪、video pipeline、短剧发布、批量发布报告。"
agent_created: true
---

# 短视频生产全链路数据追踪

## 何时触发

当用户提出以下任一意图时，立即加载并执行本 Skill：

- "把这个 JSON 写入测试数据库" / "把这些字段入库"
- "把这个 skill 分享给其他 loop 接入" / "适配到我的 loop" / "检查我的 loop 能不能统计"
- "帮我分析这份发布报告" / "提取发布任务数据"
- "从服务器抓取 pipeline 数据并入库"
- "统计这些字段" / "检查字段完整度" / "按策略统计成功率"
- "建一个短视频生产测试库"
- 提供了包含 task_id、drama_name、publish_status、clip_params 等字段的 JSON 或 Markdown 数据

## 新 Loop 接入优先路径

当用户要把本 skill 分享给其他人，或让其他 loop 适配 Dashboard 统计时，优先读取 [references/integration_contract.md](references/integration_contract.md)，按接入契约执行。

分享包内置最小样例：

- [examples/minimal_loop_tasks.json](examples/minimal_loop_tasks.json)：覆盖成功、排队、剪辑中、预发布和未发布缺口。
- [examples/strategy_context.json](examples/strategy_context.json)：策略上下文样例。

接入前必须先本地自检：

```bash
python3 scripts/validate_loop_payload.py \
  --tasks examples/minimal_loop_tasks.json \
  --loop-name demo-shortdrama-loop \
  --strict
```

接入方交付自己的 `runtime/tasks.json` 后，先运行：

```bash
python3 scripts/validate_loop_payload.py \
  --tasks runtime/tasks.json \
  --loop-name <their-loop-name> \
  --daily-target <today-target> \
  --publish-start-time "YYYY-MM-DD HH:MM:SS" \
  --publish-interval-seconds 120
```

只有 `errors=[]`，且关键 warning 都解释清楚后，才允许执行 `push_loop_result.py --execute`。

所有分享接入的 loop 都要求每 30 分钟上报一次。优先使用：

```bash
python3 scripts/report_half_hour_loop.py \
  --tasks runtime/tasks.json \
  --owner <owner> \
  --loop-name <their-loop-name> \
  --daily-target <today-target> \
  --publish-start-time "YYYY-MM-DD HH:MM:SS" \
  --publish-interval-seconds 120 \
  --output-dir runtime/half-hour-reports \
  --execute
```

`runtime/tasks.json` 建议保存当天全量任务快照；半小时上报重复写稳定 `task_id` 时会更新同一条任务，不会重复计数。

## 核心流程

所有策略读取和数据写入都通过服务器 HTTP API 完成，**不需要直接访问数据库**：

```
┌──────────────────────────┐    ┌────────────────────────────┐
│  AI Loop 看板数据库       │<──>│ pull_dashboard_strategy.py │
│  策略表 / 账号池 / 证据表 │    └──────────┬─────────────────┘
└──────────────────────────┘               │ 策略包 JSON / env
                                           ▼
┌──────────────────────────┐    ┌────────────────────────────┐
│  大家的 loop              │───>│ claim_strategy_binding.py  │
│  Steven / Barry / 自定义  │    └──────────┬─────────────────┘
└──────────────────────────┘               │ 本轮策略绑定
                                           ▼
┌──────────────────────────┐    ┌────────────────────────────┐
│  任务结果 / telemetry     │───>│ push_loop_result.py        │
└──────────────────────────┘    └──────────┬─────────────────┘
                                           ▼
                                ┌────────────────────────────┐
                                │ video_pipeline_tasks        │
                                │ ai_loop_strategy_bindings   │
                                │ ai_loop_runtime_events      │
                                └────────────────────────────┘
```

## 服务器 API

基础地址：`http://124.174.76.6`

### 读取策略和账号池

```bash
# 读取策略定义
curl http://124.174.76.6/api/table/ai_loop_clip_strategies?limit=1000
curl http://124.174.76.6/api/table/ai_loop_publish_strategies?limit=1000
curl http://124.174.76.6/api/table/ai_loop_account_selection_strategies?limit=1000
curl http://124.174.76.6/api/table/ai_loop_drama_selection_strategies?limit=1000

# 读取账号池
curl http://124.174.76.6/api/table/ai_loop_fb_account_claims?limit=100000
```

### 写入数据

```bash
curl -X POST http://124.174.76.6/api/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "table": "video_pipeline_tasks",
    "rows": [
      {
        "task_id": "唯一ID",
        "date": "2026-06-10",
        "assignee": "负责人",
        "drama_name": "剧名",
        "publish_status": "success"
      }
    ]
  }'
```

- 必填字段：`task_id`（唯一标识）、`date`
- 相同 task_id 会自动覆盖更新（INSERT ON DUPLICATE KEY UPDATE）
- 不需要 API Key（当前为开放模式）

### 读取数据

```bash
# 查询表数据
curl http://124.174.76.6/api/table/video_pipeline_tasks?limit=100

# 健康检查
curl http://124.174.76.6/api/health
```

## 策略接入闭环

不要让成员直接连接数据库。标准流程是：

1. **拉策略**：loop 启动前调用 `pull_dashboard_strategy.py`，拿到负责人可用账号池、A/B 分组、四类策略和推荐策略。
2. **登记绑定**：loop 真正执行前调用 `claim_strategy_binding.py`，把“本轮使用哪些策略”写入 `ai_loop_strategy_bindings`。
3. **执行任务**：loop 把 `strategy_context` 写进每条任务的 `clip_params.strategy_context`。
4. **回写结果**：loop 执行后调用 `push_loop_result.py`，写入 `video_pipeline_tasks` 和 `ai_loop_runtime_events`。
5. **看板分析**：前端按负责人、策略、账号组、A/B 分组和运行日志展示效果。

### 1. 拉取策略包

```bash
python3 scripts/pull_dashboard_strategy.py \
  --api-base http://124.174.76.6 \
  --owner 焦千为 \
  --uid 2265845568 \
  --loop-name steven-jiao-ai-loop \
  --output runtime/strategy-bundle.json \
  --env-output runtime/strategy.env \
  --team-ids-output runtime/team-ids.txt \
  --min-accounts 1
```

输出内容：

- `strategy-bundle.json`：完整策略包，适合 Python/Node loop 读取。
- `strategy.env`：shell loop 可直接 `source`。
- `team-ids.txt`：当前负责人 FB 账号池。

### 2. 登记本轮策略绑定

默认使用策略包里的 `selected_strategies`：

```bash
python3 scripts/claim_strategy_binding.py \
  --api-base http://124.174.76.6 \
  --owner 焦千为 \
  --loop-name steven-jiao-ai-loop \
  --round-name round-20260611-01 \
  --ab-group A \
  --strategy-bundle runtime/strategy-bundle.json \
  --output runtime/strategy-context.json \
  --execute
```

也可以手动指定策略，适合临时实验：

```bash
python3 scripts/claim_strategy_binding.py \
  --owner 焦千为 \
  --loop-name steven-jiao-ai-loop \
  --round-name round-20260611-01 \
  --strategy clip:去重剪辑02:短分段切片 \
  --strategy publish:发布策略03:错峰发布 \
  --output runtime/strategy-context.json
```

### 3. 回写 loop 结果

`tasks.json` 可以是单条对象、数组，或 `{"rows":[...]}`。脚本会自动补 `assignee`、`uid`、`round_name`、`ab_group`，并把策略上下文合并到 `clip_params`。

```bash
python3 scripts/push_loop_result.py \
  --api-base http://124.174.76.6 \
  --owner 焦千为 \
  --uid 2265845568 \
  --loop-name steven-jiao-ai-loop \
  --round-name round-20260611-01 \
  --ab-group A \
  --strategy-context runtime/strategy-context.json \
  --tasks runtime/tasks.json \
  --daily-target 2540 \
  --publish-start-time "2026-06-22 19:00:00" \
  --publish-interval-seconds 120 \
  --execute
```

首次接入新 loop 时，先不加 `--execute` 做 dry-run，确认 `sample_task` 里的 `clip_params.strategy_context` 正确后再写入。

### 4. 接入前校验

`validate_loop_payload.py` 用于分享给其他 loop 的第一道验收，不写库。

```bash
python3 scripts/validate_loop_payload.py \
  --tasks runtime/tasks.json \
  --loop-name steven-jiao-ai-loop \
  --daily-target 2540 \
  --publish-start-time "2026-06-22 19:00:00" \
  --publish-interval-seconds 120 \
  --strict
```

它会检查：

- 必填字段：`task_id`、`date`、`loop_name`、`drama_name`、`publish_status`、账号 key。
- 数据风险：重复 `task_id`、不支持的 `publish_status`、缺少剪辑状态证据、缺少发布时间或每日目标。
- 可统计指标：选剧数、账号数、剪辑完成/排队/剪辑中、已发布/预发布/未发布、发布时间和发布间隔。

### 5. 半小时上报

`report_half_hour_loop.py` 是分享给其他 loop 的推荐调度入口。它会先调用本地校验，再调用 `push_loop_result.py` 生成 `loop_window_report` 事件。

```bash
python3 scripts/report_half_hour_loop.py \
  --tasks runtime/tasks.json \
  --owner 焦千为 \
  --uid 2265845568 \
  --loop-name steven-jiao-ai-loop \
  --round-name round-20260622-01 \
  --daily-target 2540 \
  --publish-start-time "2026-06-22 19:00:00" \
  --publish-interval-seconds 120 \
  --output-dir runtime/half-hour-reports \
  --execute
```

默认上报刚结束的半小时窗口，并写出 selected tasks 与 report JSON 到 `--output-dir`。如果 `tasks.json` 是当天全量快照，默认不要加 `--filter-window`；如果只想上报窗口内变化任务，再加 `--filter-window`。

## 字段统计与完整度检查

当用户问“这些字段能不能统计”“哪些字段缺数据”“按负责人/策略/A-B 看效果”时，使用 `summarize_pipeline_metrics.py`。这个脚本只读，不写库。

```bash
# 统计全量 video_pipeline_tasks，输出 Markdown 报告
python3 scripts/summarize_pipeline_metrics.py \
  --api-base http://124.174.76.6 \
  --format markdown \
  -o runtime/pipeline-metrics.md

# 只看某个负责人和日期范围
python3 scripts/summarize_pipeline_metrics.py \
  --owner 焦千为 \
  --date-from 2026-06-01 \
  --date-to 2026-06-11 \
  --format json \
  -o runtime/pipeline-metrics.json
```

默认统计：

- 字段完整度：截图字段逐项检查“有值/缺失/完整率”
- 业务结果：总数、成功、失败、审核中、成功率
- Loop 节点指标：选剧、AI 剪辑工具、剪辑状态、发布状态、发布时间逻辑
- 维度拆分：负责人、稳定账号 key、FB 账号、loop、轮次、短剧、A/B 分组、策略
- 失败分析：失败阶段、失败原因 Top
- 耗时/数值指标：原视频、剪辑、产物、上传、发布、重试次数的平均/P50/P90/最大值

Dashboard 节点指标口径：

- 选剧：优先按最新 `round_name` 统计；如无明确轮次，则按最近 30 分钟窗口统计。短剧数按 `drama_name` 去重，不用任务行数冒充短剧数。
- 本轮要发账号：按最新轮次的稳定账号 key 去重，优先 `social_account_id`，其次 `douyin_t8_account` / `channel_id` / `uid` / `task_id`。
- AI 剪辑工具：任务级使用 `clip_tool`；轮次级展示 `round_clip_tools`。
- 剪辑状态：只展示完成、排队中、剪辑中。排队中优先识别 `clip_last_status=queued` 或失败原因里的 `last_status=queued`；完成优先看 `clip_end_time`、产物字段、`social_post_id` 或发布成功/审核中。
- 发布状态：已发布统计当天 `publish_status=success`；预发布统计 `short_link_publish_time` 有值且 `publish_status` 不是 `failed` / `cancelled` / `error`；未发布按 `daily_publish_target - 已发布` 计算，不直接等同于 pending/failed。
- 发布时间逻辑：优先使用命令行 `--publish-start-time`，其次使用行字段 `publish_schedule_start_time` / `publish_start_time`，再兜底取最早 `short_link_publish_time`；间隔使用 `--publish-interval-seconds` 或行字段 `publish_interval_sec` / `publish_account_interval_seconds`。

## 工作流程

## 人员识别规则

团队成员写入数据时，**不要依赖大家手工填写姓名**。所有写入都必须先解析出 `assignee`，并写入 `assignee_source` 说明识别来源。

负责人识别优先级：

1. 记录内已有 `assignee` / `owner`：直接使用。
2. 用 `uid` 查人员映射表。当前会议截图给出的 `uid -> 归属人` 是首选识别方式。
3. 用 `team_id` 查人员映射表。
4. 用 `social_account_id` 查人员映射表。
5. 用账号简称 / 社媒账号名查人员映射表。
6. 用命令行 `--assignee` 或环境变量 `VIDEO_PIPELINE_ASSIGNEE` 兜底。
7. 仍无法识别：标记 `assignee=unknown`。正式入库必须启用 `--require-assignee` 阻断 unknown。

人员映射表建议由账号池生成，不让成员直接写数据库。JSON 示例：

```json
{
  "uid": {
    "5621636507": "唐欢",
    "2265845568": "焦千为",
    "8624445410": "黄梓鸣",
    "8815830611": "吴昱辰",
    "9402541668": "刘心雨",
    "7587048224": "姬博鹏",
    "3358160725": "周宇诗",
    "2487213567": "龙双霞（双双）",
    "1822510638": "张文琰"
  },
  "team_id": {
    "team_steven": "焦千为"
  },
  "social_account_id": {
    "3951334425172613": "黄梓鸣"
  },
  "account": {
    "好剧推荐001": "唐欢"
  },
  "social_name": {
    "Ariyan Joy": "黄梓鸣"
  }
}
```

严格解析示例：

```bash
python3 scripts/parse_source.py --daily-loop data.json \
  -p ai_loop_20260611 \
  --assignee-map references/owner_uid_map.json \
  --require-assignee \
  -o pipeline_data.json
```

### 场景 A：用户直接给了 JSON 数据

1. 校验数据格式（必须包含 task_id）
2. 校验或补齐 `assignee`，无法识别时不进入生产库
3. 调用 `POST /api/ingest` 写入
4. 调用 `GET /api/table/video_pipeline_tasks?limit=5` 验证
5. 输出写入结果摘要

**直接用 curl 写入**：

```bash
curl -s -X POST http://124.174.76.6/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"table":"video_pipeline_tasks","rows":[<用户的JSON数据>]}' 
```

### 场景 B：用户给了 Markdown 批量发布报告

1. 用 `scripts/parse_source.py` 解析 Markdown 表格
2. 用人员映射表补齐 `assignee`
3. 解析后生成标准 JSON
4. 调用 `POST /api/ingest` 写入
5. 输出统计摘要

```bash
# 解析 Markdown 报告
python3 scripts/parse_source.py reports.txt \
  -p <前缀> \
  --assignee-map references/owner_uid_map.json \
  --require-assignee \
  -o pipeline_data.json

# 写入服务器
curl -s -X POST http://124.174.76.6/api/ingest \
  -H "Content-Type: application/json" \
  -d "{\"table\":\"video_pipeline_tasks\",\"rows\":$(cat pipeline_data.json)}"
```

### 场景 C：用户给了 daily-loop JSON

```bash
# 解析 daily-loop JSON
python3 scripts/parse_source.py --daily-loop data.json \
  -p <前缀> \
  --assignee-map references/owner_uid_map.json \
  --require-assignee \
  -o pipeline_data.json

# 写入服务器
curl -s -X POST http://124.174.76.6/api/ingest \
  -H "Content-Type: application/json" \
  -d "{\"table\":\"video_pipeline_tasks\",\"rows\":$(cat pipeline_data.json)}"
```

### 场景 D：用户想查看统计

1. 调用 `summarize_pipeline_metrics.py` 只读拉取 `video_pipeline_tasks`
2. 先按负责人、loop、日期过滤
3. 输出节点指标、字段完整度、状态分布、平均耗时等

```bash
python3 scripts/summarize_pipeline_metrics.py \
  --api-base http://124.174.76.6 \
  --owner 焦千为 \
  --loop-name steven-jiao-ai-loop \
  --date-from 2026-06-22 \
  --date-to 2026-06-22 \
  --daily-target 2540 \
  --publish-start-time "2026-06-22 19:00:00" \
  --publish-interval-seconds 120 \
  --format markdown \
  -o runtime/pipeline-metrics.md
```

注意：dashboard 发布状态不是简单的 `publish_status` 分布。`publish_status` 是原始任务状态；展示状态必须按“已发布/预发布/未发布”派生口径计算。

## 字段映射

### 报告列 → 数据库字段

| 报告列 | 数据库字段 | 转换规则 |
|--------|-----------|---------|
| 账号 | douyin_t8_account | 直接映射 |
| 短剧 | drama_name | 直接映射 |
| 剧场 | clip_params.theater | JSON 内嵌 |
| 剪辑手法 | clip_params.method | JSON 内嵌 |
| 去重手法 | clip_params.dedup | JSON 内嵌 |
| 视频时长 (MM:SS) | output_duration_sec | 转为秒数 |
| 发布状态 | publish_status | 中文→英文枚举映射 |
| 备注 | publish_fail_reason | 仅失败时填充 |
| 生成时间 | short_link_publish_time | 直接映射 |

### 发布状态映射

| 中文 | 英文 (publish_status) |
|------|----------------------|
| 成功 | success |
| 失败 | failed |
| 未提交 | failed (fail_stage=upload) |
| 处理中 | reviewing |
| 待执行 | pending |

`publish_status` 不等同于 dashboard 展示状态：

- 已发布：当天 `publish_status=success`
- 预发布：`short_link_publish_time` 有值，且 `publish_status` 不在 `failed` / `cancelled` / `error`
- 未发布：`daily_publish_target - 已发布`

## 完整字段 Schema

详见 [references/field_schema.md](references/field_schema.md)

关键字段速查：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | VARCHAR | ✅ | 唯一标识，重复则更新 |
| date | VARCHAR | ✅ | 日期 YYYY-MM-DD |
| assignee | VARCHAR | ❌ | 负责人 |
| assignee_source | VARCHAR | ❌ | 负责人识别来源：record/uid/team_id/social_account_id/account/fallback/unresolved |
| loop_name | VARCHAR | ❌ | loop 项目名，用于看板聚合 |
| round_name | VARCHAR | ❌ | loop 执行轮次，用于最新轮次统计 |
| ab_group | VARCHAR | ❌ | A/B 分组 |
| social_account_id | VARCHAR | ❌ | 平台账号 ID，账号统计优先 key |
| drama_name | VARCHAR | ❌ | 选剧名称 |
| clip_tool | VARCHAR | ❌ | 任务级 AI 剪辑工具 |
| publish_status | VARCHAR | ❌ | success/failed/reviewing/pending |
| short_link_publish_time | DATETIME | ❌ | 预发布/排期判断依据 |
| daily_publish_target | INTEGER | ❌ | 每日发布目标，用于计算未发布缺口 |
| publish_schedule_start_time | DATETIME | ❌ | 计划开始发布时间 |
| publish_interval_sec | INTEGER | ❌ | 账号发布间隔秒数 |
| clip_duration_sec | DOUBLE | ❌ | 剪辑耗时(秒) |
| output_duration_sec | DOUBLE | ❌ | 产物时长(秒) |
| publish_fail_reason | TEXT | ❌ | 失败原因 |
| clip_params | TEXT | ❌ | 剪辑参数 JSON |

## 脚本清单

| 脚本 | 用途 |
|------|------|
| `scripts/pull_dashboard_strategy.py` | 从看板读取账号池、A/B 分组和四类策略，输出 loop 可用策略包 / env / team_id 列表 |
| `scripts/claim_strategy_binding.py` | loop 执行前登记本轮使用的策略，写入 `ai_loop_strategy_bindings`，并输出 `strategy_context` |
| `scripts/push_loop_result.py` | loop 执行后回写任务结果和运行日志，写入 `video_pipeline_tasks` / `ai_loop_runtime_events` |
| `scripts/validate_loop_payload.py` | 新 loop 接入前的本地校验脚本，不写库，检查字段契约并预计算 Dashboard 节点指标 |
| `scripts/report_half_hour_loop.py` | 每 30 分钟上报一次 loop 快照，先校验再回写任务和 `loop_window_report` 运行事件 |
| `scripts/summarize_pipeline_metrics.py` | 只读统计 `video_pipeline_tasks`：字段完整度、负责人/账号/策略/A-B/失败原因/耗时指标 |
| `scripts/parse_source.py` | 解析 Markdown 报告 / daily-loop JSON → 标准 pipeline JSON |
| `scripts/import_steven_telemetry.py` | 将 Steven-jiao telemetry 转为 `video_pipeline_tasks` |
| `scripts/sync_steven_dashboard_strategy.py` | 将看板账号池与策略快照同步到 Steven-jiao loop 配置 |
| `references/field_schema.md` | 完整字段定义与枚举值 |
