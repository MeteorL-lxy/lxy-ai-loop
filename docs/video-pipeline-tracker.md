# Video Pipeline Tracker

当前项目已适配 `video-pipeline-tracker` 的三段式上报：

1. 拉取 dashboard 策略 bundle
2. 领取本轮 strategy binding
3. 回写 round 结果与 runtime event

接入文件：

- `conf/video_pipeline_tracker.json`
- `scripts/push-loop-round-to-tracker.py`
- `tools/video-pipeline-tracker/scripts/*`

当前设计约束：

- 不改 `video_pipeline_tasks` 表结构
- 策略归因依赖：
  - `ai_loop_strategy_bindings`
  - `video_pipeline_tasks.clip_params.strategy_context`
  - `video_pipeline_tasks.clip_params.loop_name`
  - `video_pipeline_tasks.round_name`
  - `ai_loop_runtime_events`

工作流：

1. `scripts/run-drama-line-worker.py` 在每轮启动前拉取策略 bundle
2. worker 为本轮生成 `strategy-context.json`
3. 轮次结束后，`scripts/push-loop-round-to-tracker.py` 把 round 归一化为 `video_pipeline_tasks`
4. 同时回写 `ai_loop_runtime_events`
