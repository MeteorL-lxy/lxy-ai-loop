# Barry Video Spec

## 1. 文档目的

本文档沉淀 `barry-video` 的完整技术实现方案，回答四个核心问题：

1. 网站网页功能是如何被逆向、抽象并改造成 CLI 的。
2. CLI 是如何再被封装成 OpenClaw 可安装插件和 skills 的。
3. 为什么当前实现采用 `Python CLI + Node/OpenClaw plugin + Skills` 这三层结构。
4. 未来如果要把别的网站或别的网页工作流复制成同类产品，应该按什么步骤落地。

本文档既是当前项目的落地说明，也是后续复刻同类“网页能力产品化”的标准 spec。

## 2. 当前交付物总览

当前已经落地的交付物有两层。

第一层是底层可执行 CLI：

- 路径：`/Users/ming/inbeidou_cli.py`
- 作用：直接调用 Inbeidou 的 HTTP API / WebSocket，完成账号查询、积分、短剧列表、视频上传、智影解析、智能剪辑、视频翻译、作品下载、社媒发布等动作。

第二层是上层 OpenClaw 包：

- 路径：`/Users/ming/barry-video`
- npm 包名：`barry-video`
- GitHub 仓库：`https://github.com/a77ming/barry-video`
- npm 包地址：`https://www.npmjs.com/package/barry-video`
- 一行安装命令：`npx -y barry-video install`

最终交付的不是单一脚本，而是一套可分发、可安装、可被 AI 自动调用的产品化能力包。

## 3. 设计目标

这个项目的目标不是“写几个脚本替代点网页”，而是把网页背后的能力真正做成可复用的机器接口。目标包括：

- 把网站功能从“只能点页面使用”变成“可命令行调用”。
- 把命令行能力从“只能人手工执行”变成“AI 可以可靠调用的 tool”。
- 把零散命令组合成“自然语言可触发的 skills”。
- 把本地项目做成“可 GitHub 分发、可 npm 分发、可一行安装”的包。
- 保持和真实网页行为一致，而不是拍脑袋重写一套假逻辑。

## 4. 目标网站与能力边界

本项目涉及两个站点域：

1. `https://creator.inbeidou.cn/tool`
2. `https://publish.inbeidou.cn/publish/accounts`
3. `https://publish.inbeidou.cn/publish/release`

这些网页被拆成了下面几类能力。

### 4.1 Creator 工具站能力

| 网页能力 | 当前 CLI 命令 | 当前 OpenClaw Tool |
| --- | --- | --- |
| 用户信息 | `user` | `barry_video_user` |
| 积分余额 | `credit` | `barry_video_credit` |
| AI 产品与价格 | `products` | `barry_video_products` |
| 语言目录 | `languages` | `barry_video_languages` |
| 短剧列表 | `list` | `barry_video_dramas` |
| 媒资库列表 | `uploads list` | `barry_video_uploads_list` |
| 上传视频 | `uploads upload` | `barry_video_upload` |
| 删除媒资 | `uploads delete` | `barry_video_uploads_delete` |
| 智影解析 | `analyze run` | `barry_video_analyze` |
| 剪辑枚举 | `clip types` | `barry_video_clip_types` |
| 智能剪辑 | `clip create` | `barry_video_clip` |
| 翻译语言 | `translate languages` | `barry_video_translate_languages` |
| 翻译字体 | `translate fonts` | `barry_video_translate_fonts` |
| 翻译样式 | `translate styles` | `barry_video_translate_styles` |
| 视频翻译 | `translate create` | `barry_video_translate` |
| 我的作品列表 | `manus list` | `barry_video_manus_list` |
| 作品详情 | `manus detail` | `barry_video_manus_detail` |
| 下载作品 | `manus download` | `barry_video_download_manus` |
| 删除作品 | `manus delete` | `barry_video_manus_delete` |

### 4.2 Publish 站能力

| 网页能力 | 当前 CLI 命令 | 当前 OpenClaw Tool |
| --- | --- | --- |
| 已授权账号列表 | `publish accounts` | `barry_video_publish_accounts` |
| 发布用视频上传 | `publish upload` | 由 `barry_video_publish` 内部触发或单独 CLI 使用 |
| 创建发布任务 | `publish create` | `barry_video_publish` |
| 查询发布记录 | `publish records` | `barry_video_publish_records` |
| 删除发布任务 | `publish delete` | `barry_video_publish_delete` |
| 剪辑后直接发布 | 组合流程 | `barry_video_pipeline` |

### 4.3 已识别但当前未完全封装的网页行为

从发布站前端 bundle 中已经识别出以下网页行为：

- 获取社媒 OAuth 授权链接
- OAuth 回调处理
- 断开授权
- Facebook / YouTube 的公共主页或频道选择与确认

这些行为在前端代码中已经能看到真实接口，但当前版本 `barry-video@0.2.0` 主要完成的是“已授权账号使用、视频上传、发帖发布、记录查询”这条主链，尚未把整套账号授权管理完整暴露为 OpenClaw tools。

这部分已被识别为后续扩展点，而不是未知区域。

## 5. 总体架构

最终结构不是浏览器自动化，而是“网页逆向一次，运行时直连接口”。

```text
用户自然语言
    ->
OpenClaw Skill 路由
    ->
barry-video plugin 中的 tool
    ->
Node index.ts 参数组装 / 子进程调用
    ->
Python CLI inbeidou_cli.py
    ->
HTTP API / WebSocket
    ->
Inbeidou 后端
    ->
JSON 结果
    ->
tool 返回给模型
    ->
模型生成最终回答
```

这个架构有五个关键优点：

1. 不依赖网页 UI 运行，稳定性明显高于纯浏览器点击。
2. CLI 可单独测试，plugin 只做编排，不重复实现业务逻辑。
3. AI 工具调用需要结构化输出，所以 CLI 统一补了 `--json`。
4. skills 只负责“什么时候调用什么工具”，不承担业务实现。
5. GitHub / npm 分发的是完整产品包，不是零散脚本。

## 6. 为什么不是直接用浏览器自动化

这个项目的核心选择是：

- 逆向网页
- 抽取真实接口和参数
- 用 CLI 直连接口
- 再让 AI 调 CLI

而不是：

- 每次都让 AI 打开网页
- 点击按钮
- 填表单
- 上传文件
- 等页面状态变化

原因如下：

1. 网页自动化对 DOM、样式、前端版本非常脆弱。
2. 上传、轮询、作品状态查询这类动作，后端接口更稳定也更容易重试。
3. OpenClaw / tool use 最适合处理结构化参数和结构化结果，不适合长期靠页面文本解析。
4. CLI 更适合被脚本、CI、Agent、多轮工作流复用。

网页在这里只承担“信息源”和“逆向样本”的作用，不再是运行时依赖。

## 7. 从网页变 CLI 的标准方法论

这一节是整套方法的核心，可复用到其他网站。

### 7.1 第一步：拆页面，不拆代码

先把网页按“用户可感知动作”拆成最小能力单元，而不是先看代码。

例如本项目中，`publish/release` 页面不是一个动作，而是至少包含：

- 选择发布目标账号
- 输入帖文
- 上传视频
- 选择定时发布时间
- 提交发布任务

同样，`creator` 工具页也不是一个动作，而是：

- 上传媒资
- 获取 upload_id / window_id
- 做智影解析
- 做智能剪辑
- 做视频翻译
- 查询作品
- 下载作品

先拆页面动作，后面命令设计才不会失真。

### 7.2 第二步：抓真实接口，而不是猜接口

网页转 CLI 的关键不是看页面长什么样，而是看页面到底调用了什么。

本项目用了两类逆向输入：

1. 浏览器 DevTools 的 Network 请求
2. 前端打包后的 JS bundle 代码

已确认的发布页前端 API 函数包括：

- `getAuthorizedAccounts`
- `getPublishInfo`
- `uploadVideo`
- `publishPost`
- `getPublishRecord`
- `deletePost`
- `getOAuthAuthorizeUrl`
- `disconnectAccount`
- `getFacebookChannels`
- `confirmFacebookChannel`

这些函数在前端 bundle 中进一步对应到了真实接口路径：

- `GET /ai/v1/publish/team/social`
- `POST /ai/v1/publish/team/social`
- `DELETE /ai/v1/publish/team/social`
- `POST /ai/v1/publish/team/social/callback`
- `GET /ai/v1/publish/info`
- `POST /ai/v1/publish/team/upload`
- `GET /ai/v1/publish/team/post`
- `POST /ai/v1/publish/team/post`
- `DELETE /ai/v1/publish/team/post`
- `GET /ai/v1/publish/team/social/channel`
- `POST /ai/v1/publish/team/social/channel`

这些信息意味着 CLI 设计不需要猜“按钮点击后会发生什么”，而是能直接复现真实请求。

### 7.3 第三步：把前端约束转成 CLI 约束

网页不仅包含接口路径，还包含前端校验规则。CLI 如果不补这些规则，体验会很差。

本项目从网页逻辑中提取并落到了 CLI 中的规则包括：

- 发布视频大小不能超过 `1000MB`
- 定时发布时间至少晚于当前时间 `5 分钟`
- 定时发布时间不能超过 `31 天`
- Facebook / Instagram 发布时需要 `type=REEL`
- 一次发布只能选择同一平台的账号
- 账号状态异常或未绑定频道时不可发布

CLI 的价值不是把后端接口裸露出来，而是把前端已经存在的业务约束一起带过去。

### 7.4 第四步：设计“可组合”的命令面

网页通常是状态式、流程式的；CLI 更适合命令式、可组合的设计。

本项目采用的策略是：

- 一个页面拆成多个子命令
- 命令允许显式传参
- 同时保留最近一次状态，避免重复输入

典型例子是上传相关流程：

1. `uploads upload --file xxx.mp4`
2. CLI 自动得到 `upload_id`
3. CLI 自动轮询得到 `window_id`
4. 保存到 `~/.inbeidou_cli_state.json`
5. 后续 `analyze run` / `clip create` / `translate create` 可直接复用

这就是把网页上的“用户脑内状态”和“页面内状态”显式化成机器可复用状态。

### 7.5 第五步：给所有 AI 需要用到的命令补 `--json`

命令行给人看和给 AI 调用，输出要求完全不同。

人读输出可以是：

- 表格
- emoji
- 摘要文本

但 AI tool 调用必须优先使用结构化输出。

因此本项目对底层 CLI 做了一个关键改造：

- 原先偏文本展示的命令，统一补充了 `--json`
- OpenClaw tool 只走 JSON 输出通道
- CLI 仍保留原有易读文本输出，供人直接手工使用

这是把“脚本”升级成“可被 Agent 稳定编排的接口层”的关键一步。

## 8. 底层 CLI 设计：`/Users/ming/inbeidou_cli.py`

### 8.1 定位

`inbeidou_cli.py` 是整个系统的业务执行核心。它直接调用 Inbeidou 后端接口，不依赖 OpenClaw 才能工作。

这层的职责是：

- 处理认证
- 调接口
- 处理轮询
- 处理 WebSocket
- 管理最近一次状态
- 把业务动作做成稳定命令

### 8.2 运行时依赖

依赖主要有：

- `python3`
- `requests`
- `websocket-client`
- `ffprobe`

其中 `ffprobe` 负责读取本地视频的元数据，用于上传前补齐：

- 宽高
- 时长
- 文件大小
- 横竖屏方向

### 8.3 鉴权与基础地址

CLI 内部定义了四个核心常量：

- `SCENTER_API = https://api-scenter.inbeidou.cn/agent/v1`
- `ICENTER_API = https://api-icenter.inbeidou.cn/ai/v1`
- `TOOL_API = https://api-tool.inbeidou.cn/ai/v1`
- `WS_MANUS_CHATS = wss://api-icenter.inbeidou.cn/ai/v1/ws/manus/chats`

鉴权统一由 `auth_headers()` 处理，支持：

- 原始 `Authorization`
- `Bearer` 风格

当前实现会优先读取环境变量 `INBEIDOU_TOKEN`。

### 8.4 统一请求层

所有 HTTP 调用都经过 `api_request()`：

- 拼 URL
- 补鉴权头
- 选择 `params` / `json` / `data` / `files`
- 统一超时
- 统一解析 JSON
- 统一检查 HTTP 状态码

然后再由 `require_success()` 做业务层 `code == 0` 校验。

这让上层命令逻辑只需要关心业务，不需要每个命令重复写错误处理。

### 8.5 状态文件设计

CLI 使用状态文件：

- `~/.inbeidou_cli_state.json`

状态文件不是缓存装饰，而是工作流桥接器。它用来保存最近一次关键上下文，例如：

- `upload_id`
- `window_id`
- `manus_id`
- `media_url`
- `publish_file_url`
- 最近一次任务返回结果

这样可以支持下面这种链式操作：

```bash
python3 /Users/ming/inbeidou_cli.py uploads upload --file ~/Desktop/demo.mp4
python3 /Users/ming/inbeidou_cli.py analyze run
python3 /Users/ming/inbeidou_cli.py clip create --wait
python3 /Users/ming/inbeidou_cli.py manus download --id 12345 --output ~/Desktop
```

即使后续命令没显式传 `upload_id` / `window_id`，也可以从最近状态里回填。

### 8.6 命令树

当前 CLI 命令树如下：

```text
user
credit
products
languages
publish
  accounts
  upload
  create
  records
  delete
uploads
  list
  upload
  delete
analyze
  run
clip
  types
  create
translate
  languages
  fonts
  styles
  create
manus
  list
  detail
  download
  delete
list
```

### 8.7 CLI 与网页能力映射原则

设计时遵循了三个原则：

1. 页面上独立可执行的动作，尽量对应独立命令。
2. 一个命令只负责一个清晰的结果。
3. 如果页面是流程式的，CLI 就用“显式参数 + 状态复用”来还原。

## 9. 底层 CLI 的关键业务流

### 9.1 上传视频流

这是整个 creator 工具链的入口。

上传流程不是单个请求，而是两段式：

1. 先上传原始文件到 `TOOL_API /media/upload`
2. 再到 `ICENTER_API /manus/uploads` 轮询出 `window_id`

具体过程如下：

#### 9.1.1 本地文件探测

函数：`probe_video(file_path)`

职责：

- 校验文件存在
- 调用 `ffprobe`
- 读取宽高、时长、大小
- 判断横屏 / 竖屏 / 方屏

这一步是因为上传接口需要前端原本会提交的元数据，不能只传文件本身。

#### 9.1.2 原始媒资上传

函数：`upload_raw_media(file_path)`

接口：

- `POST https://api-tool.inbeidou.cn/ai/v1/media/upload`

上传时除了文件，还会带：

- `screen_x`
- `screen_y`
- `file_size`
- `file_duration`
- `orientation`

返回后保存：

- `upload_id`
- `media_url`
- `media_cover_url`
- `file_path`

#### 9.1.3 轮询 window_id

函数：`ensure_upload_window(upload_id)`

接口：

- `POST https://api-icenter.inbeidou.cn/ai/v1/manus/uploads`

目的：

- 将 `upload_id` 转成后续 AI 工具需要的 `window_id`

网页上这个状态通常由页面内部轮询完成；CLI 将其显式固化为一个函数。

#### 9.1.4 合成上传上下文

函数：`upload_video(file_path)`

它把上面两步拼成完整动作，并最终保存：

- `upload_id`
- `window_id`
- `agent_id`
- `manus_id`
- `manus_status`

这就是为什么后续剪辑、翻译、解析都能直接接在上传后面。

### 9.2 智影解析流

命令：

```bash
python3 /Users/ming/inbeidou_cli.py analyze run --file /path/to/video.mp4
```

内部流程：

1. 先通过 `resolve_media_context()` 拿到 `upload_id` / `window_id`
2. 调 `POST /manus/vision/analyze_v3`
3. 轮询直到 `status` 脱离运行态
4. 返回结构化解析结果

运行态状态集合定义为：

- `loading`
- `pending`
- `processing`
- `executing`

解析结果会被 `describe_analysis()` 做友好显示，也支持 `--json` 直接返回原始 body。

### 9.3 智能剪辑流

命令：

```bash
python3 /Users/ming/inbeidou_cli.py clip create --file /path/to/video.mp4 --wait --json
```

当前剪辑能力的关键点是：

- 不是纯 HTTP 接口
- 而是通过 WebSocket 提交任务

#### 9.3.1 剪辑枚举

剪辑类型枚举来自：

- `GET /mp/enum`

CLI 中固定可选值包括：

- `high_cut`
- `golden_three`
- `golden_clips`
- `high_pre`

去重策略枚举包括：

- `common_deduplication`
- `apply_pip`
- `apply_rotate`
- `apply_scale`
- `apply_flip`
- `apply_frame`
- `apply_special`
- `apply_speed`
- `apply_reduce_frame_rate`
- `apply_mirror_pip`

#### 9.3.2 前端参数还原

函数：`build_high_cut_params(args)`

这一步的目标不是“发一个差不多的请求”，而是尽量还原网页前端真实提交逻辑。

默认参数包括：

- `cut_duration=auto`
- `output_count=1`
- `cut_type=high_cut`
- `script_count=1`
- `watermark=""`

默认启用的去重策略：

- `common_deduplication`
- `apply_pip`

#### 9.3.3 WebSocket 提交

函数：`submit_ws_tasks(window_id, upload_ids, tasks, merge_video=False)`

连接地址：

- `wss://api-icenter.inbeidou.cn/ai/v1/ws/manus/chats`

提交 payload 关键字段包括：

- `upload_ids`
- `window_id`
- `msg_type=card`
- `token`
- `merge_video`
- `tasks`

其中剪辑任务会以：

- `{"key": "high", "params": ...}`

的形式提交。

#### 9.3.4 等待成片

如果命令带 `--wait`，则继续轮询：

- `GET /manus/{manus_id}`

直到作品状态完成，然后可进一步下载。

### 9.4 视频翻译流

命令：

```bash
python3 /Users/ming/inbeidou_cli.py translate create --file /path/to/video.mp4 --lang en --wait --json
```

翻译流与剪辑流类似，也需要：

- `upload_id`
- `window_id`
- WebSocket 提交
- `manus` 轮询

但区别在于参数构造更复杂。

#### 9.4.1 翻译目录能力

CLI 先提供三个只读目录命令：

- `translate languages`
- `translate fonts`
- `translate styles`

对应接口：

- `GET /translation/languages`
- `GET /translation/fonts`
- `GET /translation/effect_color_styles`

#### 9.4.2 翻译配置还原

函数：`build_translate_params(args)`

这个函数专门负责把前端 UI 字段还原成后端真正需要的参数。

例如：

- `alignment` 被转换成 `subtitle_x`
- `subtitle_y` 从百分比换算成 0 到 1 之间的值
- `font_opacity` 从 0 到 100 转成字符串比例
- `shadow` / `outline` 与 `effect_color_style` 互斥时做条件转换

默认配置包括：

- `source_language=zh`
- `target_language=en`
- `need_speech_translate=True`
- `subtitle_type=double`
- `font=Alibaba PuHuiTi`
- `font_size=22`
- `font_color=#ffffff`
- `alignment=Center`

这部分如果不还原前端逻辑，CLI 的输出会和网页不一致。

#### 9.4.3 提交任务

翻译任务会通过 WebSocket 以：

- `{"key": "trans", "params": ...}`

的形式提交。

### 9.5 作品流

命令包括：

- `manus list`
- `manus detail`
- `manus download`
- `manus delete`

作品下载逻辑做了三件事：

1. 通过作品详情找首个输出视频 URL
2. 创建安全文件名
3. 下载到目标目录

下载后的本地路径可以直接继续用于发布。

### 9.6 发布流

发布链路来自 `publish.inbeidou.cn` 页面。

#### 9.6.1 账号列表

命令：

```bash
python3 /Users/ming/inbeidou_cli.py publish accounts --platform FACEBOOK --json
```

接口：

- `GET /publish/team/social`

返回后可按：

- 平台
- 账号状态

进行筛选。

#### 9.6.2 发布视频上传

命令：

```bash
python3 /Users/ming/inbeidou_cli.py publish upload --file /path/to/video.mp4 --json
```

接口：

- `POST /publish/team/upload`

这个上传与 creator 工具链用的媒资上传不是同一条链。

它直接返回发布所需的：

- `file_url`
- `ext`
- `mime`
- `file_size`

并保存到状态文件，供 `publish create` 复用。

#### 9.6.3 构建发布 payload

函数：`build_publish_payload(args)`

内部处理了三类问题：

1. 发布目标解析
2. 文案来源解析
3. 发布时间解析

发布目标支持两种输入：

- `--account-id`
- `--team-id`

如果传账号 ID，CLI 会先去查账号列表，再自动找到对应：

- `team_id`
- `social_type`

如果传团队 ID，则要求同时知道平台。

发布时间通过 `parse_schedule_at()` 校验：

- 格式必须合法
- 至少晚于当前 5 分钟
- 最多 31 天

#### 9.6.4 创建发布任务

命令：

```bash
python3 /Users/ming/inbeidou_cli.py publish create --account-id 109 --text "文案" --file /path/to/video.mp4 --json
```

接口：

- `POST /publish/team/post`

支持两种发布状态：

- 立即发布 `published`
- 定时发布 `scheduled`

Facebook / Instagram 会自动补：

- `type=REEL`

#### 9.6.5 发布记录

命令：

```bash
python3 /Users/ming/inbeidou_cli.py publish records --post-status published --json
```

接口：

- `GET /publish/team/post`

#### 9.6.6 删除发布任务

命令：

```bash
python3 /Users/ming/inbeidou_cli.py publish delete --team-id xxx --task-id yyy --json
```

接口：

- `DELETE /publish/team/post`

### 9.7 短剧发现流

命令：

```bash
python3 /Users/ming/inbeidou_cli.py list --platform dramabox --size 10 --json
```

接口：

- `GET /task/page`

这部分实现了“最新 Dramabox 新剧选一个”这类自然语言需求的底层数据源。

平台映射包括：

- `dramabox`
- `shortmax`
- `reelshort`
- `flickreels`
- `flareflow`
- 以及多个其它短剧平台

## 10. 为什么要给 CLI 加 `--json`

这是整个包能被 AI 稳定调用的前提。

如果没有 `--json`：

- AI 只能从人类可读文本里解析
- 表格格式稍变就会出错
- tool 输出不稳定

因此本次改造把原本只适合人看的命令补成了双模式输出：

- 默认模式：适合人在终端直接看
- `--json`：适合 OpenClaw tool 读取

重点补齐了 `--json` 的命令包括：

- `user`
- `credit`
- `products`
- `languages`
- `list`
- `uploads list`
- `uploads delete`
- `manus list`
- `manus download`
- `manus delete`
- `publish accounts`
- `publish records`
- `publish delete`

其他原本已能天然返回结构化结果的命令也统一纳入了 JSON 化约定。

## 11. OpenClaw 插件层设计：`/Users/ming/barry-video`

### 11.1 为什么再包一层 Node Plugin

虽然 Python CLI 已经能做事，但 OpenClaw 插件仍然必要，原因有三：

1. OpenClaw 需要一个标准 plugin 入口来注册 tools。
2. OpenClaw 插件可以声明配置 schema，方便给不同机器设置不同默认值。
3. skills 与 tools 的分发更适合 npm / GitHub 包结构。

所以最终采用：

- Python 负责业务
- Node 负责 OpenClaw 对接

这是职责清晰、迭代成本最低的方案。

### 11.2 包目录结构

当前目录结构如下：

```text
barry-video/
├── README.md
├── package.json
├── openclaw.plugin.json
├── index.ts
├── bin/
│   └── barry-video
├── scripts/
│   ├── install-local.sh
│   ├── package-release.sh
│   └── smoke-test.sh
└── skills/
    ├── barry-account/
    ├── barry-drama/
    ├── barry-media/
    ├── barry-publish/
    └── barry-video/
```

### 11.3 `package.json` 的作用

`package.json` 负责定义：

- npm 包名：`barry-video`
- 版本：`0.2.0`
- OpenClaw 扩展入口：`./index.ts`
- 安装入口：`bin/barry-video`
- 本地安装脚本
- 打包脚本
- smoke test 脚本

关键字段：

- `openclaw.extensions`
- `openclaw.install.npmSpec`
- `bin`
- `files`
- `publishConfig.access=public`

这让它不仅是一个 JS 包，也是一个 OpenClaw 可识别安装包。

### 11.4 `openclaw.plugin.json` 的作用

这个文件负责告诉 OpenClaw：

- plugin ID 是什么
- skills 在哪里
- plugin 支持哪些配置项

当前配置项包括：

- `pythonBin`
- `backendCli`
- `downloadDir`
- `defaultAccountIds`
- `defaultTeamIds`
- `defaultPublishPlatform`
- `defaultDramaPlatform`
- `defaultLanguage`
- `defaultDramaOrder`

这一步很重要，因为它把原本写死在脚本里的默认行为，提升成了可安装后的运行时配置。

从 `0.2.2` 开始，npm 包本身也会直接携带一份不含硬编码 token 的 `backend/inbeidou_cli.py`。安装器优先复制当前机器上已有的本地 backend 快照；如果找不到本地源文件，则退回到包内自带 backend。这样 OpenClaw 后续即使换了工作目录、用户目录或原始脚本路径，也不会因为找不到最初的绝对路径而直接失效。

### 11.5 `index.ts` 的职责

`index.ts` 是插件真正的执行入口，核心职责是：

- 读取 plugin 配置
- 解析默认值
- 组装 CLI 参数
- 启动 Python 子进程
- 解析 JSON 输出
- 把结果按 OpenClaw tool 格式返回

它不直接重写业务，而是做“桥接层”。

### 11.6 `index.ts` 的关键模块

#### 11.6.1 配置解析

关键函数：

- `getPluginConfig()`
- `getRuntimeDefaults()`
- `resolvePythonBin()`
- `resolveBackendCli()`
- `resolveDownloadDir()`

作用是：

- 先取 OpenClaw 配置
- 再取环境变量
- 最后退回默认值

例如 `backendCli` 的候选顺序包括：

- `BARRY_VIDEO_BACKEND`
- plugin config 的 `backendCli`
- `~/inbeidou_cli.py`
- `/Users/ming/inbeidou_cli.py`

#### 11.6.2 CLI 调用层

关键函数：

- `runBackend()`
- `runJsonTool()`

`runBackend()` 负责：

- `spawn` Python 进程
- 收集 stdout / stderr
- 处理超时
- 非零退出码时报错

`runJsonTool()` 则在此基础上：

- 尝试把 stdout 解析成 JSON
- 封装成 OpenClaw 的 tool response

#### 11.6.3 参数构造层

关键函数包括：

- `buildClipArgs()`
- `buildTranslateArgs()`
- `buildPublishArgs()`
- `buildDramaArgs()`
- `buildUploadListArgs()`
- `buildManusListArgs()`

这一层的价值是把 AI 传入的 tool 参数，严格映射到底层 CLI 参数。

例如：

- AI 传 `targetLang`
- Node 层转成 `--lang`
- CLI 再转成后端参数

这种分层避免模型直接拼 shell 命令造成不稳定。

#### 11.6.4 Tool 注册层

`registerJsonTool()` 用于批量注册标准 JSON tool。

其后由 `registerBarryTools()` 注册全部工具。

### 11.7 当前已注册 tools 列表

当前 `index.ts` 注册的工具如下：

- `barry_video_user`
- `barry_video_credit`
- `barry_video_products`
- `barry_video_languages`
- `barry_video_dramas`
- `barry_video_publish_accounts`
- `barry_video_uploads_list`
- `barry_video_upload`
- `barry_video_uploads_delete`
- `barry_video_analyze`
- `barry_video_clip_types`
- `barry_video_clip`
- `barry_video_translate_languages`
- `barry_video_translate_fonts`
- `barry_video_translate_styles`
- `barry_video_translate`
- `barry_video_manus_list`
- `barry_video_manus_detail`
- `barry_video_download_manus`
- `barry_video_manus_delete`
- `barry_video_publish`
- `barry_video_publish_records`
- `barry_video_publish_delete`
- `barry_video_pipeline`
- `barry_video_cli_passthrough`

### 11.8 为什么需要 `barry_video_pipeline`

单个 tool 能力足够细，但用户自然语言经常是链式的，例如：

- “把这个视频智能剪辑了，然后直接发布到 Facebook”

如果每次都依赖模型自己串多个 tool，也能做，但稳定性略差。

所以单独做了一个组合型工具：

- `barry_video_pipeline`

它内部做三步：

1. 调 `clip create --wait`
2. 调 `manus download`
3. 调 `publish create`

这样就把“多轮工作流”变成了“一个显式复合动作”。

### 11.9 为什么需要 `barry_video_cli_passthrough`

这是故意保留的逃生口。

目的：

- 当底层 CLI 新增了命令，但 plugin 还没来得及注册专用 tool 时，仍然可以直接透传使用。

这降低了 plugin 与 backend CLI 的耦合风险，也让扩展期更平滑。

## 12. Skills 设计：让 AI 知道什么时候该调什么

### 12.1 skills 不等于 tools

这里必须严格区分：

- Tool：真正执行动作
- Skill：告诉模型什么时候用哪个 tool、按什么习惯路由

`barry-video` 既包含 tools，也包含 skills。

### 12.2 为什么不是只做一个 skill

虽然有总 skill `barry-video`，但仍然拆了多个子 skill：

- `barry-account`
- `barry-drama`
- `barry-media`
- `barry-publish`
- `barry-video`

这样做的原因是：

1. 触发条件更明确
2. 大模型路由更稳定
3. 更像 `openclaw-lark` 的组织方式
4. 每个 skill 的说明更聚焦

### 12.3 各 skill 的职责

#### `barry-account`

负责：

- 当前账号信息
- 积分余额
- AI 工具价格
- 语言目录

典型触发：

- “我的积分是多少”
- “我是谁”
- “北斗有哪些产品和价格”

#### `barry-drama`

负责：

- Dramabox / ShortMax 等短剧发现

典型触发：

- “最新 dramabox 的新剧选一个”
- “查 shortmax 最近的剧”

#### `barry-media`

负责：

- 视频上传
- 解析
- 智能剪辑
- 视频翻译
- 作品管理

典型触发：

- “上传这个视频”
- “分析这个视频”
- “把这个视频翻译成英语”

#### `barry-publish`

负责：

- 列出发布账号
- 创建发布任务
- 查询发布记录
- 删除发布任务
- 剪辑后直接发布

#### `barry-video`

这是总入口 skill，用来覆盖完整自然语言空间。

### 12.4 `references/intents.md` 的作用

`skills/barry-video/references/intents.md` 专门放常见意图映射，例如：

- “我的积分是多少” -> `barry_video_credit`
- “最新 dramabox 的新剧选一个” -> `barry_video_dramas`
- “把这个视频剪完直接发 Facebook” -> `barry_video_pipeline`

这属于典型的 progressive disclosure：

- skill 主体保持精简
- 细节意图映射放 reference 文件

### 12.5 `agents/openai.yaml` 与 `_meta.json`

这两个文件主要是 UI / 元数据补充，便于在技能列表中展示：

- `display_name`
- `short_description`
- `default_prompt`

## 13. 安装器设计

### 13.1 本地安装脚本

脚本：

- `scripts/install-local.sh`

职责：

1. 把 plugin 复制到 `~/.openclaw/extensions/barry-video`
2. 把 skills 复制到 `~/.openclaw/skills/*`
3. 把同一套 skills 复制到 `~/.codex/skills/*`
4. 把同一套 skills 复制到 `~/.claude/skills/*`
5. 优先把本机现成的 `inbeidou_cli.py` 复制到 `~/.openclaw/extensions/barry-video/backend/inbeidou_cli.py`
6. 如果本机不存在源 backend，则保留包内自带的 `backend/inbeidou_cli.py`
7. 更新 `~/.openclaw/openclaw.json`

### 13.2 安装时修改的 OpenClaw 配置

安装器会确保以下配置存在：

- `skills.load.extraDirs`
- `skills.entries["barry-video"].enabled`
- `plugins.enabled`
- `plugins.allow`
- `plugins.load.paths`
- `plugins.entries["barry-video"].enabled`
- `plugins.entries["barry-video"].config`
- `agents.defaults.tools.allow`

也就是说安装不是“把文件丢过去就完了”，而是会把 OpenClaw 的实际可用配置一并补好。

### 13.3 支持的环境变量

安装时支持通过环境变量覆盖默认值：

- `BARRY_VIDEO_BACKEND`
- `BARRY_VIDEO_PYTHON`
- `BARRY_VIDEO_DOWNLOAD_DIR`
- `BARRY_VIDEO_DEFAULT_ACCOUNT_IDS`
- `BARRY_VIDEO_DEFAULT_TEAM_IDS`
- `BARRY_VIDEO_DEFAULT_PUBLISH_PLATFORM`
- `BARRY_VIDEO_DEFAULT_DRAMA_PLATFORM`
- `BARRY_VIDEO_DEFAULT_LANGUAGE`
- `BARRY_VIDEO_DEFAULT_DRAMA_ORDER`

这使得同一个包在不同机器上不需要改源码就能工作。

从 `0.2.1` 起，即使没有显式设置 `BARRY_VIDEO_BACKEND`，安装器也会优先尝试以下候选路径并复制私有 backend：

- `$BARRY_VIDEO_BACKEND`
- `$HOME/inbeidou_cli.py`
- `/Users/ming/inbeidou_cli.py`

从 `0.2.2` 起，还支持通过以下环境变量把 token 注入到 OpenClaw 配置或运行环境：

- `INBEIDOU_TOKEN`
- `BARRY_VIDEO_AUTH_TOKEN`
- `BARRY_VIDEO_TOKEN`

### 13.4 `bin/barry-video` 的作用

命令入口支持：

```bash
barry-video install
barry-video backend <args...>
barry-video package [output.tgz]
barry-video smoke
```

这让包不仅能被 OpenClaw 安装，也能作为独立 CLI 入口使用。

## 14. 打包与分发

### 14.1 GitHub 分发

仓库：

- `https://github.com/a77ming/barry-video`

GitHub 分发的意义：

- 用户可以直接从仓库安装
- npm 不可用时有兜底方案
- 方便后续版本管理和 issue 管理

兜底安装命令：

```bash
npx -y github:a77ming/barry-video install
```

### 14.2 npm 分发

当前已成功发布：

- `barry-video@0.2.0`

安装命令：

```bash
npx -y barry-video install
```

### 14.3 npm 发布时的 2FA 关键点

这个项目实际发布过程中踩到的关键点是 npm 的两步验证。

如果账号开启的是：

- `auth-and-writes`

那么 `npm publish` 会要求：

- 当前认证器 6 位 OTP

或者使用：

- 带 `Bypass 2FA` 权限的 granular access token

本项目最终发布成功的方式是：

- 使用带 `Bypass 2FA` 权限的 npm token

这意味着未来如果你要继续自动化发包，推荐统一使用：

- granular token
- 且勾选 `Bypass two-factor authentication`

### 14.4 为什么 npm 分发很关键

因为一旦 npm 发布成功，OpenClaw 安装就可以变成一行命令：

```bash
npx -y barry-video install
```

这比让用户手动 clone 仓库、复制文件、改配置，要产品化得多。

## 15. 实际验证过的事项

当前已验证通过的内容包括：

- `python3 /Users/ming/inbeidou_cli.py --help`
- `user / credit / products / list / uploads / publish accounts` 的 JSON 输出
- `./scripts/smoke-test.sh`
- `npm pack --dry-run`
- `npx --yes tsx /Users/ming/barry-video/index.ts`
- plugin 默认导出结构合法
- `npx -y github:a77ming/barry-video install`
- `npm publish --access public`
- `npm view barry-video`
- `npx -y barry-video install`

这意味着：

- backend CLI 可运行
- plugin 可注册
- skills 可加载
- GitHub 安装可用
- npm 安装可用

## 16. 当前方案的关键设计决策

### 16.1 复用现有 Python CLI，而不是在 `index.ts` 重写全部 API

原因：

- Python CLI 已经承载所有底层业务细节
- HTTP + WebSocket + 轮询逻辑写在 Python 更顺手
- Node 层保持轻量桥接，维护成本最低

### 16.2 优先走真实 API，而不是浏览器自动化

原因：

- 更稳定
- 更快
- 更适合结构化返回
- 更适合被 AI 编排

### 16.3 skill 和 tool 同时存在

原因：

- 没有 tool，AI 无法执行
- 没有 skill，AI 不知道什么时候该调用

### 16.4 组合流程单独做 pipeline

原因：

- 链式用户请求非常高频
- 复合动作交给模型临时拼接，稳定性不如显式 pipeline

## 17. 这套方法如何复制到别的网站

如果未来要把另一个网站也做成同类包，可以按下面流程走。

### 17.1 第 1 阶段：页面能力清单

先列：

- 页面有哪些动作
- 每个动作的输入
- 每个动作的输出
- 哪些动作需要登录态
- 哪些动作是同步的，哪些是异步的

### 17.2 第 2 阶段：接口发现

用 DevTools 和前端 bundle 把这些东西拿到：

- 请求 URL
- 请求方法
- Query / Body 结构
- 鉴权方式
- 前端校验规则
- 前端默认值
- 异步轮询方式
- WebSocket 消息结构

### 17.3 第 3 阶段：底层 CLI

先把每个动作做成 CLI 命令：

- 命令清晰
- 错误清晰
- 支持 JSON
- 支持状态复用

优先确保 CLI 单独就能工作，别一开始就直接做 Agent 插件。

### 17.4 第 4 阶段：上层 plugin

再做 OpenClaw plugin：

- 每个 CLI 命令映射一个 tool
- 公共默认值放 `configSchema`
- 需要的时候加组合型 tool

### 17.5 第 5 阶段：skills

最后补 skill：

- 一个总 skill
- 若干领域 skill
- reference 文件放意图映射

### 17.6 第 6 阶段：安装器与分发

补齐：

- `install-local.sh`
- `bin/<package>`
- `package.json`
- `openclaw.plugin.json`
- smoke test
- GitHub 发布
- npm 发布

这时产品才真正完成，而不是“本地某台电脑上能跑”。

## 18. 当前版本的风险与改进建议

### 18.1 令牌管理

当前 `inbeidou_cli.py` 内部存在 token 读取逻辑。生产化时建议：

- 彻底移除源码中的默认 token
- 强制只从环境变量或配置文件读取
- 避免凭证进入 Git 仓库

### 18.2 OAuth 账号管理尚未完全工具化

发布账号授权相关接口已经识别，但当前版本重点交付的是“发帖主链”，后续可补：

- 社媒 OAuth 授权
- 回调确认
- 断开授权
- Facebook 公共主页 / YouTube 频道选择

### 18.3 后端接口变更风险

由于本方案依赖真实站点接口，站点一旦改接口：

- CLI 需要同步更新
- plugin 和 skill 通常不需要大改

这也是分层设计的价值：变化集中在 backend CLI。

### 18.4 测试体系仍可继续加强

当前已有 smoke test，但还可以继续补：

- 参数映射测试
- JSON 输出契约测试
- publish dry-run 测试
- mock 接口回放测试

## 19. 当前版本的可安装与可用状态

当前状态可以定义为：

- 已完成 CLI 化
- 已完成 OpenClaw plugin 化
- 已完成 skills 化
- 已完成 GitHub 分发
- 已完成 npm 分发
- 已完成一行安装

当前可直接使用：

```bash
npx -y barry-video install
```

安装完成后，OpenClaw 可以直接处理类似请求：

- “我的积分是多少”
- “最新 dramabox 的新剧选一个”
- “把这个视频上传后做智能剪辑”
- “把这个视频翻译成英语”
- “把剪好的视频直接发到 Facebook”

## 20. 结论

这套实现的本质，不是“写了个脚本”，而是完成了下面这条完整产品链路：

```text
网页能力识别
    ->
前端接口逆向
    ->
底层 CLI 抽象
    ->
JSON 化
    ->
OpenClaw tool 封装
    ->
skill 路由设计
    ->
安装器
    ->
GitHub / npm 分发
```

`barry-video` 证明了一件事：

只要网页背后存在稳定接口，一个原本只能在浏览器里点来点去的工作流，就可以被沉淀成：

- 可脚本化的 CLI
- 可被 AI 自动调用的 tool 集
- 可自然语言触发的 skill 包
- 可一行安装的产品

这份 spec 就是当前项目的标准沉淀版本，后续扩展 OAuth 授权、更多发布平台策略、更多复合 workflow，都应继续沿用这套分层方法。
