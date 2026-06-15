# 短视频生产全链路字段 Schema

## 字段标记说明

| 标记 | 含义 | SQL 类型 |
|------|------|----------|
| ○ | 枚举类字段 | TEXT / VARCHAR |
| A: | 文本字段 | TEXT / VARCHAR |
| # | 数值字段 | INTEGER / REAL |
| A+ | 关键ID（重要标识） | TEXT / VARCHAR |
| A= | 错误/原因文本 | TEXT |
| 🕐 | 时间戳字段 | TEXT (ISO 8601) / DATETIME |

## 阶段一：基础信息

| 字段名 | 标记 | 说明 | 示例值 |
|--------|------|------|--------|
| date | 🕐 | 日期 | "2026-06-10" |
| short_link_publish_time | 🕐 | 短链接发布时间 | "2026-06-10 14:30:00" |
| assignee | ○ | 负责人(人员) | "张三" |
| assignee_source | ○ | 负责人识别来源 | "record" / "uid" / "team_id" / "social_account_id" / "account" / "fallback" / "unresolved" |
| uid | A+ | 人员/账号归属 uid，用于反查负责人 | "5621636507" |
| task_id | A+ | 任务唯一标识 | "task_20260610_001" |
| douyin_t8_account | ○ | 抖T8账号简称 | "好剧推荐001" |
| channel_id | A | channel_id | "ch_889012" |

## 阶段二：选剧/视频信息

| 字段名 | 标记 | 说明 | 示例值 |
|--------|------|------|--------|
| account_type | ○ | 账号类型 | "个人号" / "企业号" |
| clip_tool | ○ | 剪辑工具 | "剪映" / "Premiere" |
| drama_name | A | 选剧名称 | "庆余年" |
| drama_timestamp | 🕐 | 选剧时间戳 | "2026-06-10 10:15:00" |
| preview_duration_sec | # | 预览视频时长(s) | 60 |
| preview_size_mb | # | 预览视频大小(MB) | 45.2 |

## 阶段三：剪辑信息

| 字段名 | 标记 | 说明 | 示例值 |
|--------|------|------|--------|
| material_source | ○ | 素材来源 | "本地导入" / "云端" / "第三方" |
| clip_start_time | 🕐 | 剪辑开始时间 | "2026-06-10 10:20:00" |
| clip_end_time | 🕐 | 剪辑结束时间 | "2026-06-10 10:22:30" |
| clip_duration_sec | # | 剪辑耗时(s) | 150 |
| clip_params | A | 剪辑参数 (JSON) | '{"crop":"16:9","fps":30}' |
| output_duration_sec | # | 产物时长(s) | 45 |

## 阶段四：上传信息

| 字段名 | 标记 | 说明 | 示例值 |
|--------|------|------|--------|
| output_size_mb | # | 产物文件大小(MB) | 78.5 |
| output_quality | A | 产物清晰度/码率 | "1080p / 6000kbps" |
| upload_start_time | 🕐 | 上传开始时间 | "2026-06-10 10:25:00" |
| upload_end_time | 🕐 | 上传结束时间 | "2026-06-10 10:26:45" |
| upload_duration_sec | # | 上传耗时(s) | 105 |
| upload_retry_count | # | 上传重试次数 | 0 |

## 阶段五：发布信息

| 字段名 | 标记 | 说明 | 示例值 |
|--------|------|------|--------|
| publish_req_start_time | 🕐 | 发布请求开始时间 | "2026-06-10 11:00:00" |
| publish_req_end_time | 🕐 | 发布请求结束时间 | "2026-06-10 11:00:35" |
| publish_duration_sec | # | 发布耗时(s) | 35 |
| social_post_id | A+ | 发布平台post_id | "post_dy_88901234" |
| publish_status | ○ | 发布状态 | "成功" / "失败" / "审核中" |
| fail_stage | ○ | 失败阶段 | "上传" / "发布" / "审核" / null |

## 阶段六：错误/重试信息

| 字段名 | 标记 | 说明 | 示例值 |
|--------|------|------|--------|
| publish_fail_reason | A= | 发布失败原因 | "接口超时" / "账号权限不足" |
| retry_count | # | 重试次数 | 2 |
| update_time | 🕐 | 更新时间(执行完成时间) | "2026-06-10 11:05:00" |
| clip_fail_reason | A= | 剪辑失败原因 | "素材格式不支持" / null |

## 枚举值定义

### publish_status（发布状态）
- `success` — 成功
- `failed` — 失败
- `reviewing` — 审核中
- `cancelled` — 已取消

### fail_stage（失败阶段）
- `upload` — 上传阶段
- `publish` — 发布阶段
- `review` — 审核阶段
- `clip` — 剪辑阶段
- `null` — 无失败

### account_type（账号类型）
- `personal` — 个人号
- `enterprise` — 企业号

### clip_tool（剪辑工具）
- `jianying` — 剪映
- `premiere` — Premiere
- `finalcut` — Final Cut
- `auto` — 自动化剪辑

### material_source（素材来源）
- `local` — 本地导入
- `cloud` — 云端
- `third_party` — 第三方

## 人员识别规范

团队成员写入时可以不手填姓名，但系统必须能自动补出 `assignee`。负责人识别优先级如下：

1. 记录内已有 `assignee` / `owner`，直接使用，`assignee_source=record`。
2. 用 `uid` 查人员映射表，命中则 `assignee_source=uid`。当前会议截图给出的 `uid -> 归属人` 是最推荐主键。
3. 用 `team_id` 查人员映射表，命中则 `assignee_source=team_id`。
4. 用 `social_account_id` 查人员映射表，命中则 `assignee_source=social_account_id`。
5. 用账号简称 `account` / `douyin_t8_account` / `social_name` 查人员映射表，命中则 `assignee_source=account` 或 `social_name`。
6. 使用导入命令的 `--assignee` 或环境变量 `VIDEO_PIPELINE_ASSIGNEE` 兜底，`assignee_source=fallback`。
7. 仍无法识别时写入 `assignee=unknown`、`assignee_source=unresolved`；正式入库建议启用 `--require-assignee` 阻断。

### 人员映射表 JSON 示例

```json
{
  "uid": {
    "5621636507": "唐欢",
    "2265845568": "焦千为"
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

### 人员映射表 CSV 示例

```csv
owner,uid,team_id,social_account_id,account,social_name
黄梓鸣,8624445410,,3951334425172613,,Ariyan Joy
焦千为,2265845568,team_steven,,,
唐欢,5621636507,,,好剧推荐001,
```

### 正式写入要求

- 生产写入必须保证 `assignee != unknown`。
- 推荐写入前先用 `--require-assignee` 校验，失败时先补映射表，不要直接写库。
- `assignee_source` 不是业务负责人字段，而是审计字段，用于回溯这个负责人是怎么识别出来的。

## 策略接入规范

每个 loop 接入看板策略时，必须形成这条证据链：

```text
负责人/uid/loop_name
  -> strategy-bundle.json
  -> ai_loop_strategy_bindings.binding_id
  -> video_pipeline_tasks.clip_params.strategy_context
  -> ai_loop_runtime_events
```

### strategy_context 建议结构

写入每条任务的 `clip_params.strategy_context`：

```json
{
  "clip": {
    "binding_id": "loop:steven-jiao-ai-loop:焦千为:round-01:clip:去重剪辑02",
    "strategy_code": "去重剪辑02",
    "strategy_name": "短分段切片"
  },
  "publish": {
    "binding_id": "loop:steven-jiao-ai-loop:焦千为:round-01:publish:发布策略03",
    "strategy_code": "发布策略03",
    "strategy_name": "错峰发布"
  }
}
```

### ai_loop_strategy_bindings 核心字段

| 字段名 | 说明 |
|--------|------|
| binding_id | 策略绑定唯一 ID |
| owner | 执行负责人 |
| loop_name | loop 项目名，例如 `steven-jiao-ai-loop` |
| strategy_type | `clip` / `publish` / `account_selection` / `drama_selection` |
| strategy_code | 策略编号 |
| strategy_name | 策略名称 |
| round_name | loop 执行轮次 |
| ab_group | A/B 分组 |
| binding_status | `claimed` / `loop_active` / `has_reporting` / `metadata_only` |
| evidence_level | `loop_claimed` / `loop_active` / `owner_data_only` / `metadata_only` |
| task_count / success_count / failed_count | 策略对应任务表现 |
| source | 建议写 `video_pipeline_tracker_skill` |

### ai_loop_runtime_events 核心字段

| 字段名 | 说明 |
|--------|------|
| event_id | 日志唯一 ID |
| event_time | 事件时间 |
| owner | 负责人 |
| loop_name | loop 项目名 |
| event_type | `strategy_sync` / `loop_result` / `loop_round` / `reporting_sync` |
| event_title | 日志标题 |
| event_detail | 日志详情 |
| strategy_type / strategy_code / strategy_name | 关联策略 |
| round_name / ab_group | 关联轮次和实验组 |
| severity | `info` / `success` / `warn` / `error` |
| metric_json | 指标 JSON |
