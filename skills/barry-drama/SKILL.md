---
name: barry-drama
description: Use Barry Drama only for short-drama discovery and browsing, such as finding the newest or hottest dramas or picking one candidate. Do not use it for any publish workflow, novel workflow, account selection, Vidu generation, or batch loop.
---

# Barry Drama

Primary tool: `barry_video_dramas`

This skill is discovery-only.

Do not use this skill when the request includes any workflow intent such as:

- 剪辑 / 去重 / 生成成片
- 发布 / 发到 / 发一轮 / 跑一轮
- 账号 / Facebook / TikTok / YouTube / Instagram
- 批量 / 每个账号一条 / 20 部剧发 20 个账号
- 小说 / 小说库 / 小说章节 / 小说视频 / 小说发布

In those cases, use `barry-video` instead of `barry-drama`.

Never hand-roll a clip/publish flow from here by chaining `barry-video backend list`, `episodes fetch`, `clip create`, or `publish create` manually. If the user wants the system to choose dramas and then clip/publish them, route to the `barry-video` batch or flywheel workflow.

Defaults:

- For "最新" or "最近", sort by `publish_at`
- If no platform is given, use `dramabox`
- If the user asks you to choose one, fetch several results first, then pick one and explain briefly
