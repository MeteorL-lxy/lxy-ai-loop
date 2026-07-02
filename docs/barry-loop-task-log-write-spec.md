# `barry_loop_task_log` 统一写表规范

本文档用于约束多个 loop 向 `center.barry_loop_task_log` 写入数据时的统一口径。

目标只有一个：

`barry_loop_task_log` 是一张“任务事实表”，用于记录每一条 loop 任务的真实执行情况；不是轮次汇总表，也不是某个单独 loop 的自定义日志表。

## 1. 一条数据代表什么

- 表里一行只代表“一条真实任务”
- 不能一行代表一整轮
- 不能因为状态变化就重复插入多行
- 同一条任务后续推进时，只更新同一行

一句话理解：

`一条真实任务 = 表里一行；后续进度 = 更新这同一行`

## 2. 主键和唯一标识

### `id`

- 数据库自增主键
- 仅供数据库内部使用
- 业务侧不要依赖它识别任务

### `task_uid`

- 任务唯一 ID
- 必须全局唯一
- 同一条任务从开始到结束都使用同一个 `task_uid`

推荐格式：

```text
{writer_prefix}:{业务唯一任务号}
```

示例：

```text
liuxinyu-ai-loop:xxxx
drama:xxxx
warmup:xxxx
```

要求：

- 第一次出现任务时 `insert`
- 后续阶段按 `task_uid` `update`
- 不允许同一条任务生成多个不同的 `task_uid`

## 3. loop 维度字段怎么写

### `loop_name`

- 必须由写入方显式传入
- 不使用默认值
- 传什么写什么

示例：

- `liuxinyu-ai-loop`
- `macmini`
- `macmini（YC）`

含义：

- 表示“哪个 loop 在写这条任务”

### `line_name`

- 用来区分 loop 内部线路

示例：

- `realtime`
- `ordinary`
- `yourchannel`

含义：

- 表示“这个 loop 的哪条线”

### `round_name`

- 用来区分轮次

示例：

- `round1`
- `round10`
- `round26`

含义：

- 表示“这是第几轮”

结论：

- `loop_name` = 哪个 loop
- `line_name` = 哪条线路
- `round_name` = 第几轮

## 4. 状态字段怎么写

### `task_status`

表示任务当前总状态。

示例：

- `pending`
- `selected`
- `clipping`
- `clip_done`
- `publishing`
- `success`
- `failed`
- `blocked`

### `progress_stage`

表示更细粒度的阶段信息。

示例：

- `after_clip`
- `before_settle`
- `publish_attempt_2`

### `publish_status`

表示发布侧状态。

示例：

- `pending`
- `reviewing`
- `success`
- `failed`

### `status_label`

表示给人直接看的说明，建议写中文。

示例：

- `已完成`
- `素材不足`
- `发布失败`

## 5. 时间字段统一规则

以下时间字段，只能写“这条任务自己真实发生的时间”：

- `select_started_at`
- `select_finished_at`
- `clip_started_at`
- `clip_finished_at`
- `upload_started_at`
- `upload_finished_at`
- `publish_started_at`
- `publish_submitted_at`
- `publish_finished_at`
- `publish_success_at`
- `settle_finished_at`
- `last_event_at`

统一规则：

- 能准确拿到真实任务级时间，就写真实值
- 拿不到，就写 `NULL`
- 绝对不要写整轮统一时间
- 绝对不要为了占位写假时间

特别说明：

- 如果某个时间只是“这一轮所有任务统一打点”的时间，它就不是任务级真实时间，不能写入这些字段
- `last_event_at` 应该写这条任务最近一次状态变化的真实时间

## 6. 6 个耗时字段统一规则

以下 6 个字段统一按“可空”处理：

- `select_elapsed_sec`
- `clip_elapsed_sec`
- `upload_elapsed_sec`
- `publish_elapsed_sec`
- `settle_elapsed_sec`
- `total_elapsed_sec`

统一规则：

- 能准确计算出来才写
- 算不出来就写 `NULL`
- 不允许写 `0` 占位
- 只有在“真实耗时确实为 0 秒”的极端情况下才允许写 `0`，正常业务里基本不会出现

结论：

`NULL` 的含义是“当前拿不到真实耗时”，不是“这个步骤没发生”

## 7. 备注和口径说明怎么写

### `remark`

用途：

- 写这条任务当前最需要人一眼看懂的说明
- 偏业务说明

适合写：

- 发生了什么
- 当前卡在哪一步
- 是否在等待平台结果

示例：

- `该任务剪辑成功，发布接口已提交，正在等待平台返回最终结果`
- `该任务因素材不足被跳过`

### `data_note`

用途：

- 写这条数据本身的口径说明
- 偏统计解释

适合写：

- 这条数据有没有特殊统计口径
- 某些字段为什么为空
- 是否存在历史清洗或兼容逻辑

推荐固定写法：

```text
时间字段仅写任务级真实值；未知耗时留空，不使用批次统一时间或 0 占位。
```

## 8. 失败信息怎么写

### `fail_stage`

表示失败发生在哪个阶段。

示例：

- `select`
- `clip`
- `upload`
- `publish`
- `review`

### `fail_reason`

- 给业务排查看的失败原因
- 建议写成人能直接理解的话

### `error_text`

- 给技术排查用的原始错误文本
- 尽量保留原始报错，不要过度加工

## 9. 内容和发布信息怎么写

以下字段建议所有 loop 按统一含义写入：

### 基础发布信息

- `platform`：发布平台
- `account_name`：账号显示名称
- `account_id`：发布账号 ID
- `team_id`：团队 ID 或渠道归属 ID
- `channel_id`：渠道 ID
- `pool_name`：账号池名称

### 内容信息

- `drama_title`：内容名称
- `serial_id`：内容主 ID
- `episode_id`：剧集 ID
- `episode_order`：第几集
- `theater`：剧场名称或素材来源剧场
- `language`：语言

### 来源信息

- `material_source`：素材来源，例如 `official`、`external`、`local`
- `candidate_source`：候选来源，例如 `realtime_rank`、`creative_list`、`official_library`
- `selection_reason`：这条内容为什么被选中
- `source_reused`：是否因为补量而复用素材

### 成片信息

- `source_video_path`：本地源视频路径
- `source_video_url`：源视频 URL
- `output_video_path`：本地成片路径
- `output_duration_sec`：成片时长
- `output_size_mb`：成片大小
- `output_resolution`：成片分辨率
- `output_ratio`：成片比例

### 剪辑信息

- `clip_method`：剪辑手法
- `dedup_method`：去重手法
- `clip_provider`：剪辑执行引擎或服务提供方
- `manus_id`：剪辑作品 ID
- `source_upload_id`：源素材上传 ID
- `source_window_id`：剪辑窗口 ID

### 推广和发布信息

- `promotion_link`：推广链接
- `promotion_code`：推广口令
- `caption`：发布文案
- `publish_task_id`：发布任务 ID
- `social_post_id`：平台帖子 ID
- `publish_attempt_count`：总发布尝试次数
- `publish_retry_count`：发布重试次数

## 10. 原始数据留痕规则

以下字段建议尽量保留：

- `timeline_json`
- `raw_item_json`
- `raw_report_json`
- `raw_publish_json`
- `extra_json`

说明：

- `timeline_json` 最有价值，建议记录每一步事件流、重试时间、状态变化
- 如果某个 loop 有暂时还没有结构化的新字段，先放进 `extra_json`
- 不要因为某一个 loop 的特例，马上扩表加列

## 11. 推荐写入方式

推荐采用 upsert 思路：

1. 任务首次出现时，按 `task_uid` 插入
2. 后续选剧、剪辑、上传、发布、收敛时，持续更新同一行
3. 每次更新时，只覆盖当前已知且更准确的字段

建议：

- 不要把空值错误覆盖掉已存在的真实值
- 不要把批次级信息覆盖成任务级字段
- 不要把占位值覆盖真实值

## 12. 明确禁止的写法

以下写法都不允许：

- 用一行代表一整轮
- 同一条任务重复插入多行
- 任务级时间字段写整轮统一时间
- 耗时字段写 `0` 充数
- 拿不到真实值时编造时间或耗时
- 把某个 loop 的私有含义塞进公共字段，但不做说明

## 13. 当前统一口径总结

从现在开始，这张表的统一口径如下：

- 它是“任务事实表”
- 它记录“每一条任务”的真实执行情况
- 时间字段只写任务级真实时间
- 耗时字段拿不到就留空
- 多个 loop 共用同一套字段含义
- loop 应该适配表，不是表去适配每个 loop 的私有写法

## 14. 一句话要求

所有 loop 都去适配 `barry_loop_task_log` 的统一字段语义。

拿不到真实任务级时间和耗时，就留空，不要造值。
