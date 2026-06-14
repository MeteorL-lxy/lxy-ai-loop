---
name: barry-publish
description: Use Barry Publish only for publish-account lookup, direct posting of already-prepared content, publish-record inspection, or publish-task deletion. Do not use it for content selection, novel workflows, short-drama loops, Vidu generation, or account-pool driven publish requests.
---

# Barry Publish

Use these tools:

- `barry_video_publish_accounts`
- `barry_video_publish`
- `barry_video_publish_records`
- `barry_video_publish_delete`
- `barry_video_pipeline`

This skill is publish-focused only.

Do not use this skill when the request includes any content-selection or content-generation intent such as:

- 小说 / 小说库 / 小说章节 / 选一本小说 / 选10本小说
- 小说账号池 / FB 小说账号池 / Facebook 小说账号池
- 短剧库随机选剧 / 随机挑剧 / 跑 loop
- 文生视频 / 生成视频 / 用 Vidu 生成
- 从账号池里选内容并发布 / 自动匹配生成规则 / 按账号池规则跑

In those cases, use `barry-video` instead of `barry-publish`.

If these tools are not directly exposed in the current agent session, do not execute bare tool names as shell commands such as `barry_video_publish_accounts`.

CLI fallback hard rules:

- For account lookup, use `barry-video backend publish accounts --json` or `python3 ~/.openclaw/extensions/barry-video/backend/inbeidou_cli.py publish accounts --json`.
- For publish records, use `barry-video backend publish records --json` or `python3 ~/.openclaw/extensions/barry-video/backend/inbeidou_cli.py publish records --json`.
- For direct publishing, use `barry-video backend publish create ...` or the installed backend path above.
- Always use `--json` for read-only publish queries and reason from the JSON payload, not from terminal table previews.
- Never treat MCP tool names like `barry_video_publish_accounts` as terminal commands.

Workflow:

1. If no account or team target is known, call `barry_video_publish_accounts`.
2. For direct posting, call `barry_video_publish`.
3. For clip then publish, prefer `barry_video_pipeline`.
4. After posting, call `barry_video_publish_records` if the user asks whether it finished.
