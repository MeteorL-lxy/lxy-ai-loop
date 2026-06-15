---
name: barry-video
description: Use Barry Video for Barry's full end-to-end Inbeidou workflows, especially novel-video publishing and short-drama loops. Route here when the user wants the system to choose content, match a configured account pool, generate with official Vidu, and publish all the way to final status on TikTok or Facebook.
metadata: {"openclaw":{"skillKey":"barry-video","requires":{"anyBins":["python3","python"]},"os":["darwin","linux"]}}
homepage: https://creator.inbeidou.cn/tool
user-invocable: true
---

# Barry Video

Barry Video is the umbrella skill for Barry's Inbeidou package.

Use it when the user speaks naturally, for example:

- "我的积分是多少"
- "列出我能发 Facebook 的账号"
- "最新 dramabox 的新剧选一个"
- "随机选 20 部剧，剪辑后发到我的 20 个 Facebook 账号"
- "我有 10 个 FB 账号，帮我每个账号发一条短剧"
- "从短剧库随机挑剧，剪辑去重后发布"
- "帮我跑一轮自动短剧发布"
- "把这个视频上传后做智能剪辑"
- "把这个视频翻译成英语"
- "把剪好的视频直接发到 Facebook"
- "用本地视频剪辑后发布到 TikTok"
- "随机选一部剧剪辑后发布到 TikTok"
- "跑今天的 Facebook loop"
- "选十部小说发布到我 FB 小说账号池"

## Prefer dedicated tools

- Account and pricing: `barry_video_user`, `barry_video_credit`, `barry_video_products`, `barry_video_languages`
- Drama discovery: `barry_video_dramas`, `barry_video_drama_detail`
- Novel content: `barry_video_novel_quota`, `barry_video_novels`, `barry_video_novel_random`, `barry_video_novel_chapter`, `barry_video_novel_pipeline`
- Media and AI: `barry_video_uploads_list`, `barry_video_upload`, `barry_video_uploads_delete`, `barry_video_analyze`, `barry_video_clip_types`, `barry_video_deduplication_types`, `barry_video_clip_method_guide`, `barry_video_clip`, `barry_video_translate_languages`, `barry_video_translate_fonts`, `barry_video_translate_styles`, `barry_video_translate`
- Generated works: `barry_video_manus_list`, `barry_video_manus_detail`, `barry_video_download_manus`, `barry_video_manus_delete`
- Publish: `barry_video_publish_accounts`, `barry_video_publish`, `barry_video_publish_records`, `barry_video_publish_delete`, `barry_video_local_pipeline`, `barry_video_batch_drama`, `barry_video_pipeline`
- Failed publish follow-up: `barry_video_retry_failed_publish`, `barry_video_discard_failed_publish_output`, `barry_video_failed_publish_paths`

If these tools are not directly exposed in the current agent session, prefer the installed `barry-video backend ...` CLI because it can start the authorization link + polling flow automatically when token is missing. If the CLI is not on `PATH`, use the installed plugin backend under `~/.openclaw/extensions/barry-video/backend/`. Do not search or rely on a development checkout such as `/Users/xinyuliu/Desktop/work/barry-video`.

CLI fallback hard rules:

- For read-only queries, always request structured output and reason from the JSON payload, not from terminal tables. Use `--json` for account/profile/list/detail/records queries.
- Never infer account counts from partially visible terminal output, folded output, or a preview line such as `... +20 lines`.
- For publish-account lookup, the exact fallback command is `barry-video backend publish accounts --json` or `python3 ~/.openclaw/extensions/barry-video/backend/inbeidou_cli.py publish accounts --json`.
- Do not use development-checkout paths in fallback commands.
- If the terminal output looks truncated or folded, rerun the command in JSON mode and count from the parsed JSON payload.

Installed backend fallback:

- General/account/novel/media backend: `barry-video backend ...` or `python3 ~/.openclaw/extensions/barry-video/backend/inbeidou_cli.py ...`
- Flywheel/local-video backend: `python3 ~/.openclaw/extensions/barry-video/backend/flywheel_cli.py ...`

Flywheel CLI fallback hard rules:

- If you use the wrapper command, the exact form is `barry-video backend run-round ...`, `barry-video backend run-batch-drama ...`, `barry-video backend run-local ...`.
- Never insert an extra subcommand layer such as `barry-video backend flywheel run-batch-drama ...`. That is invalid because `flywheel` is not a subcommand of `inbeidou_cli.py`.
- Never invent unsupported flags such as `--clips-per-drama`. For batch drama, use only the real flags exposed by `run-batch-drama --help`, especially `--count`, `--output-count`, `--account-id`, `--team-id`, `--clip-concurrency`, `--publish-concurrency`, `--publish-retries`.

The backend reads auth from `~/.barry-video/auth_state.json` automatically. If the fallback CLI is invoked through `barry-video backend ...`, missing auth starts the Barry authorization link + polling flow automatically. If direct Python fallback returns an auth error, use `beidou-auth`.

Default API environment is test. Set `BARRY_VIDEO_API_ENV=prod` only when the user explicitly wants production APIs.

## Routing

1. If the user asks a factual account question such as balance, products, or profile, call the matching account tool directly.
2. Resolve the material source before choosing a workflow. If the user mentions a local path, "本地视频", "下载里的视频", "这个视频", or an uploaded asset, treat it as a local/media workflow.
3. If the user asks for local video + clip + publish in one sentence, first make sure the user has explicitly chosen both a publish platform and a publish account. If either is missing, call `barry_video_publish_accounts`, list only the user-facing platform/account names in Chinese, and ask the user to choose. Do not show `account_id`, `team_id`, or other internal IDs to the user. Only after that prefer `barry_video_local_pipeline`. If the request is being handled directly inside the flywheel CLI fallback, use `python3 ~/.openclaw/extensions/barry-video/backend/flywheel_cli.py run-local --file ... --publish-platform ... --account-id ...`.
4. If the user names a drama and an episode, use the drama episode tools/source options instead of the automatic flywheel.
5. If the user asks for random drama selection, drama-library selection, automatic drama posting, or statistics in natural language, use the automatic flywheel flow even if the user never says "barry-video" or "飞轮". Trigger phrases include "随机选剧", "随机挑剧", "从短剧库选", "剧你随机选", "自动选剧", "自动发布", "跑一轮", "发一轮", "统计数据", "每个账号发一条", "分别发布", "批量发短剧", "20 个账号发 20 条". For one drama/account use `run-round` or `barry_video_flywheel_round`; for multiple dramas, multiple accounts, a requested count, or "每个账号一条", use `barry_video_batch_drama` or `run-batch-drama`. Before any real publish, the platform and target accounts must be resolved.
   Important Facebook short-drama pool rule:
   - Short-drama accounts are split by line-specific pools. Do not use or invent a default `facebook_drama_pool`.
   - For loop execution, use the configured line pools such as `facebook_drama_realtime_pool`, `facebook_drama_ordinary_pool`, `facebook_drama_fbhot_test_pool`, `facebook_drama_creative_list_pool`, `facebook_drama_realtime_single_pool`, `facebook_drama_realtime_day_pool`, `facebook_drama_creative_list_day_pool`, or `facebook_drama_yourchannel_pool`.
   - If the user asks for a one-off short-drama batch without naming a line/pool, ask one short clarification for the target pool instead of silently choosing a pool.
   - If the user does not name a drama, do not ask the user to choose the drama either; let the backend randomly select from the short-drama library.
   Ask the user only when the platform is missing, no account/count is expressed, the request is not a Facebook short-drama pool case, or the user explicitly asks to choose exact account names.
   Special fixed phrase:
   - If the user says exactly or almost exactly "跑今天的 Facebook loop", "跑今天的 FB loop", or "今天的 Facebook loop", treat it as a daily batch short-drama execute request with these defaults:
     - `--publish-platform FACEBOOK`
     - `--count 20`
     - real execution, not dry run
     - up to 3 rounds in the same Claude session
     - stop early once cumulative successful publishes reach 40
     - random drama selection, random cut methods, and random dedup methods using the backend defaults
     - final output should be only one Chinese test report summary for the whole daily loop
   - For this fixed phrase, do not ask the user to restate counts, rounds, or dry-run preference.
   For these automatic short-drama flows, never hand-roll the pipeline by looping over `inbeidou_cli.py clip create` or `publish create` one by one. That bypasses the built-in episode-material precheck, clip-supported theater filtering, retries, summary reporting, and publish-state polling. Use the flywheel batch/round entrypoints only.
   Do not add `--drama-platform` or a `dramaPlatform` value unless the user explicitly names a theater such as SnackShort, GoodShort, MoboReels, TouchShort, FlickReels, or KalosTV. If the user only says "随机选剧" or "短剧库随机", leave the theater unspecified so the backend can randomly combine supported theaters.
   Execution default for agent behavior:
   - If the user wording clearly means "real execution" such as "发布到", "发到", "直接执行", "自动跑完", "不要停", "执行到底", "跑完后总结", the agent must execute the real workflow directly and include `--execute` for CLI fallback. Do not first run a planning-only dry run.
   - Only use dry run / planning mode when the user explicitly asks for "先看看", "先规划", "预览", "dry-run", "不要真正执行", or equivalent no-side-effect wording.
   - When platform and target accounts are already resolvable from the request, never stop with wording like "确认后我会执行" or "如需真实执行请加 --execute". Just execute.
6. If the user asks for "随机选一本小说", "小说库", "小说章节", "小说生成视频", or "小说推广视频", use the novel flow. Use `barry_video_novel_random` to pick a novel and fetch a free chapter without side effects. Use `barry_video_novel_pipeline` only when the user asks to generate or publish. The novel flow now also supports batch wording such as "选10本小说，发到我的10个Facebook账号": map that to `barry_video_novel_pipeline` with `count=10`, one generated novel video per target account. Novel video publish supports TikTok and Facebook, and the novel generator uses the lightweight official-Vidu chain by default: split the chapter into `5-6` short segments, sanitize high-risk expressions, generate one image per segment with `viduq2`, generate one short segment video per image with `viduq3-turbo` at `540p`, stitch locally, then locally extend to one `180` second `720x1280` MP4 before publish. Pool-routing hard rules for local manual requests:
   - If the request says `小说账号池`, `fb 小说账号池`, or a Facebook novel account count, route to the unified account pool `facebook_novel_dedicated_10`.
   - Do not stop to ask which Vidu generation mode to use, whether to choose exact accounts, or whether to choose publish order. Novel generation is already unified to one lightweight official Vidu flow.
   - Once a novel request already resolves to the configured pool, execute the novel pipeline directly instead of first calling `publish accounts`.
   If the request resolves to a configured account pool, use that pool directly; otherwise resolve publish accounts first.
7. If the user asks for a latest drama, call `barry_video_dramas` with platform `dramabox` unless another platform is specified.
8. If the user asks for a task detail page, promotion links, app link, serial link, or a drama's推广口令, call `barry_video_drama_detail`.
9. If the user asks to analyze, clip, or translate a local file, pass `file` directly to the AI media tool instead of forcing a separate upload step.
10. If the user asks to publish and there is no explicit platform or no resolvable account selection in the current request, call `barry_video_publish_accounts` first, list the available platform/account choices by platform name and account name only, and ask the user which platform and account to publish to. A resolvable account selection can be exact account names, "全部", "前 N 个", or a platform-specific count that exactly matches the available accounts for that platform. Do this for local video, manual publish, drama episode publish, automatic flywheel publish, and novel video publish. For novel video publish, filter/list TikTok accounts only.
    If tools are unavailable and CLI fallback is required, fetch publish accounts in JSON mode and determine availability from the parsed JSON payload only. Never base this decision on terminal table previews.
11. After publishing, use `barry_video_publish_records` to confirm the final status.
12. If the user asks "有哪些剪辑手法"、"支持哪些去重手法"、"这些参数是什么意思" 这类说明型问题，优先调用 `barry_video_clip_method_guide`；如果问法明显只针对剪辑或只针对去重，也可以分别调用 `barry_video_clip_types` 或 `barry_video_deduplication_types`，并用自然语言总结，不要只回参数枚举。
13. After any clip-and-publish workflow returns, output `user_summary_zh` as the main answer when available, and do not compress it into a shorter overview. For batch workflows, the final user-facing answer must include the per-account details from `账号发布明细` / `任务明细`: account, platform, drama, episode, theater, language, publish status, clipping method, deduplication method, video duration, resolution, local clip status, failure reason, and retry advice when applicable. If `user_summary_zh` is missing, fall back to `report_zh` and summarize `任务明细` first. Do not make the user read raw JSON unless they explicitly ask for debug details.
    Hard consistency rule for local/manual execution:
   - If a local manual batch run or publish run has already produced a final `report_zh` or `user_summary_zh`, the assistant must use that final report as the only user-facing result source.
   - Do not run extra publish-record spot checks and then restate a second set of totals such as “约成功 19 条”, “至少成功 6 条”, or “补查后完成 20 条” unless the user explicitly asks for an additional debug check.
   - Bot push content and terminal final summary must stay on the same final-report caliber. If a command returned a final report, do not invent another summary from partial logs, folded output, or follow-up ad hoc queries.
14. If a batch publish result says there are failed publish tasks waiting for confirmation and the user says "继续"、"重试失败发布"、"再试一次", call `barry_video_retry_failed_publish` once. If the user says "不继续"、"删除保留成片", call `barry_video_discard_failed_publish_output`. Only show retained local clip paths when the user explicitly asks, then call `barry_video_failed_publish_paths`.

## Workflow Separation

- Local video flow: `local_file/upload_asset -> clip -> download -> publish -> publish records`. Use this when the user already has material.
- Drama episode flow: `drama/task + episode -> episode fetch -> clip/analyze/translate -> publish`. Use this when the user specifies a drama episode.
- Automatic flywheel flow: `candidate pool -> score -> select drama -> select episode -> clip -> link/caption -> publish -> collect`. Use this only when the user asks the system to choose from the drama library.
- Batch drama flow: `random theater plan -> candidate pool -> cross-language dedupe -> random N dramas -> data-driven episode selection -> parallel clip/dedup -> one video per selected account -> publish -> collect -> cleanup`. Use this when the user asks for multiple dramas, multiple accounts, a count, or batch posting such as "10 个 Facebook 账号随机发 10 部剧". If the user does not name a drama theater, the backend should randomly combine clip-supported theaters for the current round. For clipping, only use clip-supported drama theaters: KalosTV, SnackShort, GoodShort, MoboReels, TouchShort, and FlickReels.
- Novel flow: `novel library -> random/search novel -> receive platform task/promotion -> free chapter text -> split chapter into 5-6 short segments -> sanitize high-risk expressions -> official Vidu reference2image (viduq2) per segment -> official Vidu img2video (viduq3-turbo, 540p) per segment -> ffmpeg stitch -> local loop/extend into 180 second 720x1280 MP4 -> Facebook/TikTok publish with detail-page promotion copy -> publish-record polling -> final result summary`. Novel generation uses one lightweight official Vidu chain and the unified `facebook_novel_dedicated_10` account pool by default. Keep the content source separate from the short-drama flywheel, but keep the execution semantics the same: once the user asks to publish to a resolvable target, run from selection through publish without stopping for another confirmation, and do not treat "任务已提交" as the final result.
- Publish target confirmation is shared by all flows. Do not infer TikTok/Facebook/account defaults from config or previous examples except for explicit line-pool loop scripts. If platform/account/pool is missing or ambiguous, list choices and wait for the user's selection. If the request itself resolves the target set, such as "选择 20 部剧发布到 20 个 FB 账号", proceed directly with those pool-selected Facebook accounts instead of stopping for another confirmation.
- Account IDs, team IDs, social IDs, and channel IDs are internal execution fields. Keep them for tool calls, but do not include them in normal user-facing account lists unless the user explicitly asks for technical IDs.
- If a request mixes local video language with automatic drama selection, ask one short clarification about which material source to use.

## Natural-Language Trigger Guide

Treat these as user-facing ways to request the same Barry Video workflows:

- Batch short-drama posting: "随机选 20 部剧发到 20 个 Facebook 账号", "帮我批量发 20 条 FB，每个账号一条", "从短剧库随机挑剧剪辑去重后分别发布", "今天给这些账号各发一条短剧".
- Daily fixed phrase: "跑今天的 Facebook loop", "跑今天的 FB loop", "今天的 Facebook loop".
- Direct execute batch posting: "选择 20 部剧剪辑后发到我的 20 个 fb 账号", "选剧剪辑去重发布一套流程自动跑完", "不要停下来确认，直接执行发布到这些账号".
- Single automatic short-drama posting: "随机选一部剧剪辑后发布", "帮我跑一轮短剧自动发布", "剧你随机选，剪辑方式也随机".
- Novel posting: "选 1 本小说发布到我的 TikTok 账号", "随机选一本小说发到 Facebook 小说账号池", "选 10 本小说发到我的 10 个 Facebook 账号", "随机选 10 本小说，用官方 Vidu 生成小说视频，发到我的 10 个 Facebook 账号", "帮我跑一轮小说发布", "发一轮小说到我的 10 个 Facebook 账号".
- Specified drama episode: "剪辑 Scandalous 第一集", "The Diagnosis of Heartbreak 第 1 集剪完发布".
- Local video posting: "用下载里的视频剪辑后发布", "这个本地视频去重后发 TikTok", "从我的本地素材里选一个发".

If both local-material words and random-drama-library words appear in the same request, ask one short clarification before running a workflow.

## Authentication

If any tool returns a 401 or "token invalid" error, use the `beidou-auth` skill or `barry-video login` to obtain or refresh the token before retrying.

- Token is loaded automatically from `~/.barry-video/auth_state.json` (managed by beidou-auth)
- To authorize in an agent: `/beidou-auth`
- To authorize in terminal: `barry-video login`
- To check status: `/beidou-auth status`

## Account Display

When presenting account profile fields to the user, keep optional-field logic unchanged: show optional fields only when they are present in the tool/API result.

Use these user-facing Chinese labels for promotion capability fields:

- `ReelShort 推广权限：已开通/未开通`
- `Facebook 推广权限：已开通/未开通`

Do not label them as plain `ReelShort` or `Facebook`, because those labels are easy to confuse with social publish-account authorization.

## Read next

- Common natural-language patterns: [references/intents.md](references/intents.md)
