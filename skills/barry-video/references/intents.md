# Barry Video Intents

## Account

- "我的积分是多少" -> `barry_video_credit`
- "我是谁" / "当前账号信息" -> `barry_video_user`
- "北斗有哪些产品和价格" -> `barry_video_products`

## Drama

- "最新 dramabox 的新剧选一个" -> `barry_video_dramas` with `platform=dramabox`, `order=publish_at`, `size=10`
- "查 shortmax 最近的剧" -> `barry_video_dramas` with `platform=shortmax`

## Media

- "上传这个视频" -> `barry_video_upload`
- "分析这个视频" -> `barry_video_analyze`
- "剪成高燃短视频" -> `barry_video_clip`
- "翻译成英语" -> `barry_video_translate`
- "看看我已经生成过哪些作品" -> `barry_video_manus_list`
- "用 /path/to/video.mp4 剪辑后发布到 TikTok" -> local video flow; if account is missing, call `barry_video_publish_accounts` and ask the user to choose before `barry_video_local_pipeline`
- "从下载里的视频选一个，随机去重后发布" -> local video flow; platform/account are missing, so list publish accounts and ask before publishing
- "用这个本地视频发 TikTok" -> local video flow; account is missing, so list TikTok accounts and ask before publishing

## Publish

- "列出我能发 Facebook 的账号" -> `barry_video_publish_accounts`; show only platform/account names to the user, not internal account IDs or team IDs
- If tool exposure is missing and CLI fallback is required for account lookup, use `barry-video backend publish accounts --json` and decide account counts from parsed JSON only, never from terminal table previews.
- "把这个视频发到 Facebook" -> if account is missing, call `barry_video_publish_accounts` with `platform=FACEBOOK` and ask the user to choose, then `barry_video_publish`
- "查一下发布任务完成没" -> `barry_video_publish_records`
- "把这个视频剪完直接发 Facebook" -> if account is missing, list Facebook accounts and ask, then `barry_video_pipeline`

## Flywheel

- "随机选一部剧，随机剪辑后发布到 TikTok，最后统计数据" -> automatic flywheel flow; if account is missing, list TikTok accounts and ask, then `python3 ~/.openclaw/extensions/barry-video/backend/flywheel_cli.py run-round --execute --publish-platform TIKTOK --account-id ...`
- "跑一轮飞轮发布" -> automatic flywheel flow; platform/account are missing, so list publish accounts and ask before `run-round --execute`
- "帮我跑一轮短剧自动发布" -> automatic flywheel flow; this is the same intent as "飞轮", even if the user does not say "barry-video"
- "随机选 20 部剧，剪辑后随机分别发送到我的 Facebook 前 20 个账号" -> batch drama flow; resolve Facebook accounts internally, use the first 20 accounts, then run `barry_video_batch_drama`
- "我有 10 个 Facebook 账号，随机选择 10 部剧剪辑去重后分别发布" -> batch drama flow; resolve Facebook accounts internally; if exactly 10 Facebook accounts are available, execute without asking again, otherwise ask the user which 10 to use
- "帮我批量发 20 条 FB，每个账号一条，剧你随机选" -> batch drama flow; Facebook is the platform, count is 20, drama source is the drama library, one account gets one video. If exactly 20 Facebook accounts are available, treat all 20 as selected accounts and execute directly.
- "从短剧库随机挑剧，剪辑去重后发布到这些账号" -> batch drama flow if multiple accounts are selected; otherwise automatic single flywheel flow
- "今天给 20 个账号各发一条短剧" -> batch drama flow; ask for the target platform/account choices if missing
- "随机选剧、随机剪辑、随机去重，然后发到我的 TikTok 账号" -> automatic single flywheel flow unless the user mentions multiple accounts or a count
- "剪辑 Scandalous 第一集并发布" -> drama episode flow, not local video flow

For random/batch drama posting, never replace `run-batch-drama` or `run-round` with a handwritten loop of `inbeidou_cli.py clip create` plus `publish create`. The handwritten loop bypasses the built-in episode MP4/play_url precheck and can hit unsupported dramas that the flywheel batch route would skip before clipping.

For batch drama flow, do not pass a drama platform unless the user explicitly names one. Resolve publish accounts before execution, but do not stop for confirmation when the user's platform/count wording already determines the account set. If an account fails with a non-retryable capability error such as not being able to publish Reel videos, report that account as failed instead of repeatedly retrying it.

When plugin tools are not exposed and CLI fallback is needed, use `~/.openclaw/extensions/barry-video/backend/inbeidou_cli.py` or `~/.openclaw/extensions/barry-video/backend/flywheel_cli.py`; do not search the current workspace for development source files.

## Novel

- "随机选一本小说" -> `barry_video_novel_random`
- "查小说库里的小说" -> `barry_video_novels`
- "取这本小说的免费章节" -> `barry_video_novel_chapter`
- "随机选一本小说生成推广视频" -> `barry_video_novel_pipeline` with `execute=true`, `publish=false`
- "随机选一本小说生成视频并发布到 Facebook" -> novel flow with `publishPlatform=FACEBOOK`, and either a configured Facebook novel account pool or user-selected Facebook accounts
- "随机选一本小说生成视频并发布到 TikTok" -> novel flow with `generator=vidu`, `publishPlatform=TIKTOK`, then `barry_video_novel_pipeline` with `execute=true`, `publish=true`, and the selected account
- "选十部小说发布我 fb 小说账号池" -> novel flow with `publish=true`, `count=10`, `publishPlatform=FACEBOOK`, `accountPool=facebook_novel_dedicated_10`; do not first list accounts
- "选十部小说发布到我的十个 Facebook 账号" -> novel flow with `publish=true`, `count=10`, `publishPlatform=FACEBOOK`, `accountPool=facebook_novel_dedicated_10`; do not first list accounts
