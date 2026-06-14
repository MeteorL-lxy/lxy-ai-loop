# Barry Video Flywheel Implementation Plan

## 1. 目的

本文档把 `/Users/xinyuliu/Downloads/beidou-flywheel-spec.md` 改写成适合当前仓库 `/Users/xinyuliu/Desktop/work/barry-video` 的渐进式实施计划。

目标不是一次性把完整飞轮全部写完，而是按低风险顺序逐轮落地：

1. 先补骨架和状态层
2. 再补评分、选剧、匹配
3. 再补素材、剪辑、发布
4. 最后补数据回收和插件接入

这样可以避免一开始就把现有 `barry-video` 插件能力改乱，也方便每轮单独验收。

## 2. 当前仓库现实边界

当前仓库已经具备的是“执行层”和“插件层”，而不是“飞轮决策层”。

已有能力：

- `backend/inbeidou_cli.py`
  - 短剧列表
  - 短剧详情
  - 剧集列表与按集取素材
  - 智能剪辑
  - 视频翻译
  - 社媒发布
- `index.ts`
  - Node 插件层
  - 参数整理
  - 子进程调用 Python CLI
- `skills/`
  - 自然语言路由
  - 中文解释剪辑手法和去重手法

当前缺失的是：

- 飞轮状态库
- 飞轮配置
- 打分逻辑
- 选剧逻辑
- 账号匹配逻辑
- 调度与回收逻辑
- 独立的飞轮 CLI

## 3. 设计原则

为降低风险，默认采用以下约束：

1. 不直接把大量飞轮逻辑塞进 `backend/inbeidou_cli.py`
2. 先新增独立入口 `backend/flywheel_cli.py`
3. `backend/inbeidou_cli.py` 只作为飞轮的下游执行器复用
4. 插件层接入延后，等后端 CLI 稳定后再加
5. 每一轮都优先支持 `--dry-run`
6. 每一轮都要能单独验证

## 4. 推荐目录结构

第一阶段不重构现有仓库，只新增最小目录：

```text
barry-video/
├── backend/
│   ├── inbeidou_cli.py
│   ├── flywheel_cli.py
│   └── flywheel/
│       ├── __init__.py
│       ├── config.py
│       ├── orchestrator.py
│       ├── logging_setup.py
│       ├── db/
│       ├── scoring/
│       ├── selection/
│       ├── matching/
│       ├── clipping/
│       ├── publishing/
│       ├── collection/
│       └── stages/
├── conf/
│   └── flywheel.yaml
├── data/
│   └── flywheel.db
├── logs/
│   └── flywheel/
├── scripts/
│   └── init_flywheel_db.py
└── docs/
    └── flywheel-implementation-plan.md
```

说明：

- 使用 `backend/flywheel/` 而不是 spec 里的 `src/flywheel/`
- 这样可以最大化贴合当前仓库结构
- 现有插件调用路径保持不变

## 5. 分轮实施计划

## Round 0：方案适配与落盘

### 目标

把原始 spec 转成当前仓库可执行计划，并冻结基础架构决策。

### 本轮产物

- 本文档
- 目录结构决策
- 命令入口决策
- 外部依赖清单

### 关键决策

- 飞轮入口：`python3 backend/flywheel_cli.py`
- 状态存储：SQLite
- 运行模式：默认 `--dry-run`
- 插件接入：放到 Round 7

### 验收

- 团队对目录结构和推进顺序无歧义
- 后续 Round 1 可以直接开始建骨架

## Round 1：基础骨架与本地状态库

### 目标

先让飞轮具备“可初始化、可创建 round、可执行空流程”的能力。

### 要新增的文件

- `backend/flywheel_cli.py`
- `backend/flywheel/__init__.py`
- `backend/flywheel/config.py`
- `backend/flywheel/orchestrator.py`
- `backend/flywheel/logging_setup.py`
- `backend/flywheel/db/__init__.py`
- `backend/flywheel/db/sqlite_local.py`
- `backend/flywheel/db/schema.sql`
- `backend/flywheel/stages/__init__.py`
- `backend/flywheel/stages/s00_init.py`
- `scripts/init_flywheel_db.py`
- `conf/flywheel.yaml`

### 本轮只做的能力

- 初始化 SQLite
- 初始化目录
- 创建 round 记录
- 顺序执行空 stage
- 记录基础日志

### 本轮不做

- 真实查剧
- 真实选剧
- 真实剪辑
- 真实发布

### 建议命令

```bash
python3 backend/flywheel_cli.py init-db
python3 backend/flywheel_cli.py run-round --dry-run
python3 backend/flywheel_cli.py show-round 1
```

### 验收标准

- 能生成 `data/flywheel.db`
- 能生成 `logs/flywheel/`
- 能插入一条 round 记录
- `run-round --dry-run` 能顺序跑完空流程

## Round 2：候选池与评分

### 目标

让系统先具备“从剧库拿候选剧并算分”的能力。

### 要新增的文件

- `backend/flywheel/scoring/__init__.py`
- `backend/flywheel/scoring/dimensions.py`
- `backend/flywheel/scoring/ucb.py`
- `backend/flywheel/scoring/aggregator.py`
- `backend/flywheel/selection/__init__.py`
- `backend/flywheel/selection/candidate_pool.py`
- `backend/flywheel/selection/tier_allocator.py`
- `backend/flywheel/stages/s01_score.py`
- `backend/flywheel/stages/s02_tier_allocate.py`

### 实现策略

- 第一版候选池先复用现有短剧接口能力
- 先不接 MySQL 直读
- 先做规则评分
- 所有 score breakdown 落 SQLite

### 本轮输出

- 候选剧列表
- 每部剧的维度分
- A/B/C/D 分桶结果

### 验收标准

- `score --dry-run` 能输出排序后的候选剧
- 每条候选剧都有 `score_breakdown`
- 能看到 Tier 配额和 Tier 候选分布

## Round 3：选剧与账号匹配

### 目标

让系统从“候选剧”走到“生成发布计划骨架”。

### 要新增的文件

- `backend/flywheel/db/account_repo.py`
- `backend/flywheel/db/pick_repo.py`
- `backend/flywheel/db/plan_repo.py`
- `backend/flywheel/selection/selector.py`
- `backend/flywheel/matching/__init__.py`
- `backend/flywheel/matching/constraints.py`
- `backend/flywheel/matching/account_matcher.py`
- `backend/flywheel/stages/s03_select.py`
- `backend/flywheel/stages/s04_match.py`
- `scripts/import_accounts.py`

### 实现策略

- 第一版 selector 用规则法
- 先不强依赖 LLM
- 账号导入采用 CSV
- 匹配算法先做贪心版

### 用户需要提供

- 账号清单 CSV
- 账号每日发布上限
- 语言映射

### 验收标准

- 能从候选池里选出本轮剧单
- 能给每部剧分配 slot
- 能把 slot 分配到账号
- 能生成 `publish_plan` 骨架

## Round 4：素材准备与剪辑

### 目标

让被选中的剧能自动取某一集并生成成片。

### 要新增的文件

- `backend/flywheel/clipping/__init__.py`
- `backend/flywheel/clipping/source_resolver.py`
- `backend/flywheel/clipping/clip_orchestrator.py`
- `backend/flywheel/db/asset_repo.py`
- `backend/flywheel/stages/s05_prepare_source.py`
- `backend/flywheel/stages/s06_clip.py`

### 实现策略

- 复用 `backend/inbeidou_cli.py episodes list/fetch`
- 复用 `backend/inbeidou_cli.py clip create`
- 第一版固定按第 1 集或配置的第 N 集
- 第一版只出 1 条成片

### 验收标准

- 能根据 pick 自动取集
- 能调用现有剪辑能力生成成片
- 能把视频信息写到 `video_asset`

## Round 5：推广链接、文案、调度、发布

### 目标

让飞轮生成真正可执行的发布计划，并可选择真实发布或 dry-run。

### 要新增的文件

- `backend/flywheel/publishing/__init__.py`
- `backend/flywheel/publishing/link_resolver.py`
- `backend/flywheel/publishing/caption_builder.py`
- `backend/flywheel/publishing/scheduler.py`
- `backend/flywheel/publishing/publisher.py`
- `backend/flywheel/stages/s07_gen_link.py`
- `backend/flywheel/stages/s08_gen_caption.py`
- `backend/flywheel/stages/s09_schedule.py`
- `backend/flywheel/stages/s10_publish.py`

### 实现策略

- 第一版文案先规则生成
- 第一版 schedule 先简单错峰
- 第一版发布复用现有 `publish create`
- 保留 `--skip-publish`

### 用户需要提供

- 推广链接生成方式
- 默认发布平台
- 可用账号或 team_id 规则

### 验收标准

- 每条计划都有链接、文案、调度时间
- `publish --dry-run` 能输出请求参数
- 允许真实发布并写入 `publish_record`

## Round 6：数据回收与飞轮闭环

### 目标

让系统第一次形成“发布结果反哺下一轮选剧”的闭环。

### 要新增的文件

- `backend/flywheel/collection/__init__.py`
- `backend/flywheel/collection/metrics_collector.py`
- `backend/flywheel/collection/revenue_collector.py`
- `backend/flywheel/collection/performance_aggregator.py`
- `backend/flywheel/collection/event_detector.py`
- `backend/flywheel/stages/s11_collect.py`

### 实现策略

- 第一版先回收本地可拿到的发布状态
- 再逐步补收益和互动指标
- learning log 先从简单规则事件开始

### 验收标准

- 已发布内容能落 `metrics_snapshot`
- 能聚合账号表现
- 下一轮评分能引用历史表现

## Round 7：插件层接入与自然语言调用

### 目标

让 Codex / Claude Code / OpenClaw 可以直接调用飞轮。

### 要新增或修改的文件

- `index.ts`
- `skills/barry-video/SKILL.md`
- 视情况新增 `skills/barry-flywheel/SKILL.md`

### 实现策略

- 只暴露稳定命令
- 输出中文自然语言解释
- 参数枚举不直接暴露给用户

### 验收标准

- 用户可以自然语言触发飞轮 dry-run
- 用户可以查看 round / picks / publish plan
- 返回信息是中文业务解释，而不是底层代码参数

## 6. 每轮建议验收顺序

按最稳妥方式，执行顺序固定为：

1. Round 0：方案落盘
2. Round 1：骨架与状态库
3. Round 2：候选池与评分
4. Round 3：选剧与匹配
5. Round 4：素材与剪辑
6. Round 5：链接、文案、发布
7. Round 6：数据回收
8. Round 7：插件接入

原因：

- 前三轮只影响新代码，不影响现有插件主链
- 第四轮开始复用现有执行器，但仍可保持 dry-run
- 第五轮之后才接触真实发布风险
- 第七轮最后接入自然语言，避免前期频繁改 skill 和 tool

## 7. 优先级与里程碑

### P0 里程碑

- 能初始化飞轮数据库
- 能运行 `run-round --dry-run`
- 能记录 round 和 stage 结果

### P1 里程碑

- 能给候选剧算分
- 能选出本轮剧单
- 能分配到账号

### P2 里程碑

- 能按第 N 集自动取素材
- 能自动剪出一条测试稿

### P3 里程碑

- 能自动生成文案与发布计划
- 能 dry-run 到发布

### P4 里程碑

- 能回收结果
- 能影响下一轮选剧

## 8. 当前需要用户配合提供的内容

这些信息不是 Round 1 的阻塞，但从 Round 3 开始会陆续需要：

1. 账号清单 CSV
2. 语言编码映射
3. 每账号每日发布上限
4. 推广链接生成方式
5. 真实发布默认平台
6. 若后续要收益回收，还需要对应数据源或接口方式

建议你先准备：

- 一个最小账号 CSV 样例
- 语言映射表
- 推广链接生成规则说明

## 9. 下一步执行建议

接下来直接进入 Round 1，优先做这 5 件事：

1. 新增 `backend/flywheel_cli.py`
2. 新增 `backend/flywheel/db/schema.sql`
3. 新增 `scripts/init_flywheel_db.py`
4. 新增 `conf/flywheel.yaml`
5. 新增 `backend/flywheel/orchestrator.py`

Round 1 完成后，再进入 Round 2。
