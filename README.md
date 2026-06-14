# Barry Video

`barry-video` 是 Barry / 北斗创作者工作流的本地插件与 CLI 包，用来把短剧库、本地视频、小说内容、AI 剪辑、去重、下载和社媒发布串成一套可被自然语言触发的流程。

它同时提供三层能力：

- **Skills**：放在 [`skills/`](./skills)，负责让 Codex、Claude Code 等 Agent 理解用户的自然语言意图。
- **OpenClaw 插件工具**：入口在 [`index.ts`](./index.ts)，负责在 OpenClaw 环境里注册可执行工具。
- **通用 MCP 服务**：通过 `barry-video mcp` 启动，适合接入 Codex、Claude Code、Cursor 或其他支持 MCP 的客户端。

完整实现方案见 [`docs/barry-video-spec.md`](./docs/barry-video-spec.md)。

## 当前能力

- 查询当前北斗账号、积分余额、AI 产品价格和语言目录。
- 本地无 token 时自动发起北斗授权：输出授权链接、轮询授权结果、写入本地 token 后继续执行原命令。
- 查询已授权的发布账号，默认只向用户展示平台和昵称，不暴露 `account_id`、`team_id` 等内部 ID。
- 抓取 Dramabox、ShortMax、ReelShort 等短剧平台的短剧列表、详情和剧集信息。
- 按「某部剧第 N 集」获取素材，进入分析、剪辑、去重、下载和发布流程。
- 随机/数据驱动选择短剧与剧集，执行短剧飞轮流程。
- 上传用户本地视频，执行智能剪辑、9:16 标准化、发布和发布后清理。
- 从小说库随机选择小说章节，生成不同风格的视频，当前小说发布优先支持 TikTok。
- 查询、创建、轮询和删除发布任务。
- 通过 CLI、OpenClaw 插件或 MCP 工具调用同一套后端能力。

## 四条主流程

### 1. 短剧飞轮

适合用户说：

```text
帮我随机选一部剧，随机剪辑后发布到 TikTok，最后统计数据。
剪辑 Scandalous 这部剧第一集，去重一次后发布。
```

流程大致是：

1. 从短剧候选池中选择剧，支持多语言混池，并对同剧跨语言做去重。
2. 根据数据选择合适剧集，而不是固定只取第一集。
3. 获取剧集素材，执行智能剪辑和去重。
4. 将最终成片统一处理为 9:16。
5. 使用拿到的推广文案和推广链接作为发布文案。
6. 按用户选择的平台和账号发布。
7. 轮询发布状态，输出中文统计信息。
8. 发布成功后默认清理本地生成视频，避免长期占用磁盘。

常用命令：

```bash
python3 backend/inbeidou_cli.py episodes list --search "Scandalous" --start 1 --end 3 --json
python3 backend/inbeidou_cli.py episodes fetch --search "Scandalous" --episode-order 1 --json
python3 backend/inbeidou_cli.py clip create --search "Scandalous" --episode-order 1 --wait --json
python3 backend/flywheel_cli.py run-batch-drama --execute --publish-platform FACEBOOK --account-id <selected-account-id> --count 1
```

### 2. 批量短剧编排

适合用户已经选择了一批账号，希望系统自动从短剧库里选多部剧并分发，例如：

```text
我有 10 个 Facebook 账号，随机选择 10 部剧，剪辑去重后随机发布到 10 个账号。
```

流程是：

1. 用户先明确发布平台和账号池；如果没有明确选择，Agent 必须先列出账号让用户选。
2. 从支持剪辑的剧场候选池随机选择多部剧，默认使用全语言混池，并做同剧跨语言去重。当前支持剪辑的剧场是 `KalosTV`、`SnackShort`、`GoodShort`、`MoboReels`、`TouchShort`、`FlickReels`。
3. 入选前会先预检剧集素材，只保留剧集接口能拿到 `play_url/mp4` 的短剧。
4. 每部剧使用数据驱动选择更适合剪辑的剧集；也可以用 `--episode-order` 强制指定集数，但强制集数同样会先校验素材可用。
5. 按去重手法池轮换去重，并可通过 `--clip-concurrency` 并行提交剪辑任务。
6. 每条成片匹配一个账号发布，Facebook/Instagram 自动按 Reels 类型提交。
7. 轮询发布状态，输出中文统计信息；报告会单独列出发布成功的视频、账号、剪辑手法、去重手法、视频时长、分辨率、文件大小、发布时间和播放/点赞等数据。
8. 发布成功后默认删除本地生成视频；如果要保留，传 `--keep-output`。

常用命令：

```bash
python3 backend/flywheel_cli.py run-batch-drama --dry-run --count 10 --publish-platform FACEBOOK --account-id <account-1> --account-id <account-2>
python3 backend/flywheel_cli.py run-batch-drama --execute --count 10 --publish-platform FACEBOOK --account-id <account-1> --account-id <account-2> --clip-concurrency 3 --publish-concurrency 3
```

对应 MCP 工具名：

```text
barry_video_batch_drama
```

### 3. 本地视频剪辑发布

适合用户已经有素材文件，例如下载目录里的测试视频：

```text
用我本地这个视频剪辑一下，然后发布到 TikTok。
```

本地视频不会走短剧随机选剧逻辑，而是走「本地素材」流程：

1. 上传用户指定的视频文件。
2. 执行智能分析、智能剪辑和去重。
3. 下载生成成片。
4. 统一处理成 9:16。
5. 发布到用户选择的平台和账号。
6. 发布成功后默认删除本地生成成片，除非显式传入 `--keep-output`。

常用命令：

```bash
python3 backend/flywheel_cli.py run-local --file /path/to/video.mp4 --publish-platform TIKTOK --account-id <selected-account-id> --text "发布文案"
```

对应 MCP 工具名：

```text
barry_video_local_pipeline
```

### 4. 小说视频

小说流程与短剧流程分开。小说库使用 `task_type=2`，章节内容来自免费章节接口。当前小说生成链路统一走 `Vidu`，不再走旧的 `text2video` / 音色 / 后置 TTS 分支。默认逻辑是：取小说封面图 + 章节全文，自动切成 `12-14` 段，每段约 `14-15` 秒，全部段落下载到本地后再用 `ffmpeg` 拼成约 `3` 分钟、且不超过 `3.5` 分钟的成片。Facebook 小说专用池现在拆成两条子链：

- 前 10 个账号：封面图直接驱动 `img2video`，如果遇到 `AuditSubmitIllegal` 这类安审失败，会自动降级为“先生成图片再图生视频”。
- 后 10 个账号：章节内容先走 `reference2image` 生成分镜图，再用 `img2video` 生成视频。

`novels generate` 更适合指定小说或搜索小说后生成视频；`novels pipeline` 更适合从小说库随机选择小说、章节和风格，然后自动生成视频。

常用命令：

```bash
python3 backend/inbeidou_cli.py novels list --size 5 --json
python3 backend/inbeidou_cli.py novels random --json
python3 backend/inbeidou_cli.py novels pipeline --dry-run --json
python3 backend/inbeidou_cli.py novels pipeline --execute --publish-platform TIKTOK --account-id <selected-tiktok-account-id> --json
python3 backend/inbeidou_cli.py novels pipeline --execute --publish-platform FACEBOOK --account-pool facebook_novel_dedicated_10 --vidu-model viduq3-turbo --json
python3 backend/inbeidou_cli.py novels pipeline --execute --publish --count 10 --publish-platform FACEBOOK --account-pool facebook_novel_dedicated_10 --json
```

默认规则：

- 小说生成器默认走 `Vidu`。
- `Vidu` 默认使用 `viduq3-turbo + 9:16 + 720p`。
- 每次会把章节切成 `12-14` 段，每段默认约 `14-15` 秒，再拼成一条约 `3` 分钟、且不超过 `3.5` 分钟的完整视频。
- 小说 Facebook 专用池 `facebook_novel_dedicated_10` 已按账号顺序拆成两条生成链：前十封面直出视频，后十先出图再出视频。
- 章节提示词默认直接使用章节内容，但会在提交 Vidu 前做一层高风险表达清洗，降低 `AuditSubmitIllegal` / `TaskPromptPolicyViolation` 概率。
- 生成提示词默认直接使用章节内容，不再附带我们自己写的风格包装文案。
- 小说视频可发布到 `FACEBOOK` 或 `TIKTOK`。
- 小说发布统一立即发布，不走定时发布。
- `--count N` 可批量执行小说流，默认一条小说视频对应一个发布账号。
- 小说 loop 的执行语义与短剧一致：只要请求里已经明确“发布到/发到”且目标账号可解析，就直接从随机选小说跑到生成和发布，不再停下来做二次确认。
- 小说发布文案默认只用详情页按平台领取到的推广文案；不会再自己拼小说标题或简介当默认发布文案。
- 小说发布后会继续轮询发布记录，直到拿到最终结果摘要；不会再把“发布任务已提交”误当成“最终发布成功”。
- 支持通过 `--account-pool` 复用预设账号池；仓库内当前提供：
  - `facebook_novel_dedicated_10`

Vidu 鉴权不会写入仓库。运行时从以下位置读取：

- 环境变量：`BARRY_VIDEO_VIDU_API_KEY` 或 `VIDU_API_KEY`
- 本机文件：`~/.barry-video/vidu_auth.json`

## 发布账号确认规则

无论是短剧飞轮、本地视频，还是小说视频，只要用户没有明确说明发布平台和账号，就必须先列出可用账号并让用户选择。

面向普通用户时，只展示易懂信息，例如：

```text
TikTok：meteor_l0
Facebook：Barry Drama
YouTube：Barry Clips
```

不要默认展示这些内部字段：

```text
account_id
team_id
social_id
channel_id
```

内部执行时仍然需要把用户选中的账号映射为真实 `account_id`。

## 账号信息展示规则

账号信息和发布账号是两类不同概念：

- **北斗账号信息**：昵称、手机号、用户 ID、邀请码、分成比例、收益、推广权限等。
- **发布账号授权**：TikTok、Facebook、Instagram、YouTube 等社媒账号是否已绑定，能否发布视频。

如果用户信息接口返回 ReelShort/Facebook 相关推广权限字段，对用户展示时使用中文语义：

```text
ReelShort 推广权限：已开通
Facebook 推广权限：未开通
```

不要只写：

```text
ReelShort：已开通
Facebook：未开通
```

否则容易被误解成社媒发布账号授权状态。

展示逻辑保持不变：接口返回这些可选字段就展示；接口没返回就不展示，不额外补“未返回”。

## 安装

### 本地开发安装

适合正在开发这个仓库时使用，会把当前工作区同步到本机真正生效的 OpenClaw 插件副本，并同步 skills 到 Codex 和 Claude Code：

```bash
cd /Users/xinyuliu/Desktop/work/barry-video
./scripts/install-local.sh
```

安装后会写入：

- OpenClaw 插件：`~/.openclaw/extensions/barry-video`
- OpenClaw skills：`~/.openclaw/skills`
- Codex skills：`~/.codex/skills`
- Claude Code skills：`~/.claude/skills`
- OpenClaw 配置：`~/.openclaw/openclaw.json`

### npm 安装

适合普通用户或新电脑：

```bash
npx -y barry-video install
```

也可以先安装包，再执行安装命令：

```bash
npm i -g barry-video
barry-video install
```

当前 CLI 支持：

```bash
barry-video install
barry-video login
barry-video auth
barry-video status
barry-video logout
barry-video mcp
barry-video backend <inbeidou_cli.py 参数...>
barry-video package [output.tgz]
barry-video smoke
```

可选环境变量：

```bash
export BARRY_VIDEO_BACKEND="$HOME/inbeidou_cli.py"
export INBEIDOU_TOKEN="your-token"
export BARRY_VIDEO_DEFAULT_ACCOUNT_IDS="109,108"
export BARRY_VIDEO_DEFAULT_PUBLISH_PLATFORM="FACEBOOK"
export CODEX_HOME="$HOME/.codex"
export CLAUDE_HOME="$HOME/.claude"
```

## 授权

## 接口环境

当前默认接口环境是 **测试环境**，用于开发和联调。正式环境配置仍然保留，可以通过环境变量切换。

测试环境域名：

```text
SCENTER：https://test-api-scenter.inbeidou.cn/agent/v1
ICENTER：https://test-api-icenter.inbeidou.cn/ai/v1
TOOL：https://test-api-tool.inbeidou.cn/ai/v1
CLAW：https://test-api-claw.inbeidou.cn
MANUS WS：wss://test-api-icenter.inbeidou.cn/ai/v1/ws/manus/chats
CLAW WS：wss://test-api-claw.inbeidou.cn/v1/claw/chat
```

切回正式环境：

```bash
export BARRY_VIDEO_API_ENV=prod
```

明确使用测试环境：

```bash
export BARRY_VIDEO_API_ENV=test
```

也可以单独覆盖某个服务地址：

```bash
export BARRY_VIDEO_SCENTER_API="https://test-api-scenter.inbeidou.cn/agent/v1"
export BARRY_VIDEO_ICENTER_API="https://test-api-icenter.inbeidou.cn/ai/v1"
export BARRY_VIDEO_TOOL_API="https://test-api-tool.inbeidou.cn/ai/v1"
export BARRY_VIDEO_CLAW_API="https://test-api-claw.inbeidou.cn"
export BARRY_VIDEO_WS_MANUS_CHATS="wss://test-api-icenter.inbeidou.cn/ai/v1/ws/manus/chats"
export BARRY_VIDEO_WS_CLAW_CHAT="wss://test-api-claw.inbeidou.cn/v1/claw/chat"
```

- 第 3 轮：`18:30`
- 每轮：`20` 条
- 平台：`Facebook`
- 如果前两轮累计成功已经达到 `40` 条，第 3 轮自动跳过

每天会额外生成 1 份汇总：

- `data/daily-loop/YYYY-MM-DD/scheduler.log`
- `/Users/xinyuliu/Downloads/AI Loop/测试总结/日常自动发布报告_YYYYMMDD.md`

可选环境变量：

```bash
export BARRY_LOOP_PLATFORM="FACEBOOK"
export BARRY_LOOP_COUNT="20"
export BARRY_LOOP_MIN_SUCCESS_TARGET="40"
export BARRY_LOOP_MAX_ROUNDS="3"
export BARRY_LOOP_ROUND1_AT="10:00"
export BARRY_LOOP_ROUND2_AT="14:00"
export BARRY_LOOP_ROUND3_AT="18:30"
export BARRY_LOOP_ALLOW_ACCOUNT_REUSE="0"
```

授权 token 会校验所属 API 环境。比如当前是测试环境，但本地缓存是正式环境 token，CLI 会认为 token 不可用并重新发起测试环境授权，避免串环境。

## 授权

Barry Video 的授权缓存文件是：

```text
~/.barry-video/auth_state.json
```

当前支持两种授权方式：主动授权和自动授权。

在终端里可以直接执行：

```bash
barry-video login
```

当本地没有可用 token 时，`barry-video backend ...` 也会自动发起同样的授权流程。

自动授权流程：

1. 用户执行需要登录态的命令，例如 `barry-video backend user --json`。
2. CLI 检查环境变量、`~/.barry-video/auth_state.json` 和 OpenClaw 配置里是否已有可用 token。
3. 如果 token 不存在或已过期，CLI 请求北斗授权接口生成授权链接。
4. 终端输出纯文本授权链接。
5. 用户打开链接并完成授权。
6. CLI 每 2 秒轮询一次授权结果，最多等待 5 分钟。
7. 授权成功后写入 `~/.barry-video/auth_state.json`。
8. CLI 继续执行用户原本的命令。

终端链接说明：

```text
请打开下面的授权链接完成北斗账号授权：
https://...
已开始轮询授权状态，最多等待 300 秒...
```

部分终端或 Agent 面板不会把 URL 渲染成可点击链接，所以这里保持纯文本输出。若不能点击，请复制链接到浏览器打开。

在 Agent 里也可以执行：

```text
/beidou-auth
```

授权状态会优先从下面位置读取：

- `~/.barry-video/auth_state.json`
- `~/.openclaw/openclaw.json` 中的 Barry Video 插件配置
- 环境变量 `INBEIDOU_TOKEN`、`BARRY_VIDEO_AUTH_TOKEN` 或 `BARRY_VIDEO_TOKEN`

检查或清理授权：

```bash
barry-video status
barry-video logout
```

如果要从未授权状态重新测试账号授权流程，可以先执行：

```bash
barry-video logout
barry-video backend user --json
```

## 通用 MCP 接入

Barry Video 内置标准 stdio MCP 服务，这是最通用的接入方式，不依赖某一个编辑器或 Agent 的专有插件机制。

启动服务：

```bash
barry-video mcp
```

源码模式启动：

```bash
node scripts/mcp-server.mjs
```

通用 MCP 配置示例：

```json
{
  "mcpServers": {
    "barry-video": {
      "command": "barry-video",
      "args": ["mcp"]
    }
  }
}
```

当前 MCP 工具包括：

```text
barry_video_user
barry_video_credit
barry_video_products
barry_video_languages
barry_video_publish_accounts
barry_video_novels
barry_video_novel_random
barry_video_novel_pipeline
barry_video_flywheel_round
barry_video_batch_drama
barry_video_local_pipeline
barry_video_backend
```

MCP 服务会优先使用当前 npm/插件包内置后端，避免误调用本机旧配置里的后端副本；如需强制指定后端，可用 `BARRY_VIDEO_BACKEND` 或 `BARRY_VIDEO_FLYWHEEL` 环境变量覆盖。授权信息从 `~/.barry-video/auth_state.json` 或环境变量读取。缺少 token 时，MCP 服务也会尝试复用同一套授权流程；实际授权链接能否直接在客户端里点击，取决于客户端是否支持把工具输出渲染为链接。

## 自然语言触发建议

在 Codex、Claude Code 或其他 Agent 中，可以这样问：

```text
查一下我的账号信息。
查一下我的账号信息，并用中文解释推广权限字段。
查一下我所有平台的发布账号，只显示平台和昵称。
目前支持哪些剪辑手法？用中文解释。
目前支持哪些去重手法？用中文解释。
帮我随机选一部剧，随机剪辑后发布到 TikTok，最后统计数据。
我有 10 个 Facebook 账号，随机选择 10 部剧，剪辑去重后分别发布。
剪辑 The Diagnosis of Heartbreak 第一集，去重后发布。
用本地下载里的一个测试视频剪辑后发布。
从小说库随机选一本小说，生成 TikTok 视频。
```

如果用户没有指定平台或账号，Agent 应该先查询账号并请用户选择，不应该直接发布。

## 仓库结构

```text
barry-video/
├── backend/
│   ├── inbeidou_cli.py
│   └── flywheel_cli.py
├── bin/
│   └── barry-video
├── conf/
├── data/
├── docs/
├── scripts/
│   ├── install-local.sh
│   ├── mcp-server.mjs
│   ├── package-release.sh
│   └── smoke-test.sh
├── skills/
├── index.ts
├── openclaw.plugin.json
├── package.json
└── README.md
```

## 测试

本地 smoke test：

```bash
cd /Users/xinyuliu/Desktop/work/barry-video
./scripts/smoke-test.sh
```

MCP 快速检查：

```bash
barry-video mcp
```

授权流程测试：

```bash
barry-video logout
barry-video backend user --json
```

实际发布、小说生成、AI 剪辑等操作可能消耗积分或发布真实内容，测试前应明确使用 dry-run，或确认要执行真实流程。

## 打包与发布

本地打包：

```bash
cd /Users/xinyuliu/Desktop/work/barry-video
./scripts/package-release.sh
```

发布到 npm：

```bash
npm login
npm publish --access public
```

如果包名、安装来源或 OpenClaw 安装策略变化，需要同步更新 [`package.json`](./package.json) 里的 `openclaw.install.npmSpec`。
