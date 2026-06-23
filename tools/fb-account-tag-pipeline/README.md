# Facebook 账号打标流水线（独立包）

与 `ai-loop` 仓库解耦的 Cursor 技能包 + 启动器。运行时代码通过 **vendor 同步** 或 **AI_LOOP_ROOT** 指向 ai-loop。

## 目录结构

```text
fb-account-tag-pipeline/
├── README.md
├── SKILL.md                 # Cursor Agent 技能
├── .env.example             # 复制为 .env
├── config/
│   └── phones.txt           # 手机号列表（从 phones.example.txt 复制）
├── runs/                    # 默认打标输出
├── references/              # 字段、排错、配置说明
├── scripts/
│   ├── sync_from_ai_loop.py # 从 ai-loop 同步 vendor
│   ├── resolve_ai_loop_root.py
│   ├── run_batch.py         # 批量打标入口
│   └── merge_agent_into_main.py
└── vendor/ai-loop/          # 同步后的运行时代码（gitignore）
```

## 首次安装

```powershell
cd d:\桌面文件\fb-account-tag-pipeline

# 1. 配置环境
copy .env.example .env
# 编辑 .env：BEIDOU_LOGIN_CODE、AI_ICENTER_BASE_URL

# 2. 同步 ai-loop 运行时代码到 vendor（推荐，可脱离 ai-loop 路径）
python scripts/sync_from_ai_loop.py --source "d:\桌面文件\ai-loop"

# 3. 手机号列表
copy config\phones.example.txt config\phones.txt
```

同步后即使移动本文件夹，只要 `vendor/ai-loop` 在包内即可运行。

不跑 sync 时：在 `.env` 设置 `AI_LOOP_ROOT=d:\桌面文件\ai-loop`，直接引用原仓库。

## 运行

```powershell
# 批量打标（输出到 runs/latest/）
python scripts/run_batch.py

# 自定义参数（透传给 batch_tag_by_phones.py）
python scripts/run_batch.py --outdir d:\桌面文件\fb-account-tag-pipeline\runs\my_run --code 951103

# 替换主表某 agent 行
python scripts/merge_agent_into_main.py `
  --main d:\path\to\20260622.csv `
  --patch d:\path\to\rerun\20260622.csv `
  --agent-id 67020404
```

## 更新 vendor

ai-loop 脚本有更新时：

```powershell
python scripts/sync_from_ai_loop.py --source "d:\桌面文件\ai-loop"
```

## Cursor 技能

将本目录复制或链接到：

`%USERPROFILE%\.cursor\skills\fb-account-tag-pipeline\`

对话中说「按 fb-account-tag-pipeline 打标」即可。

## 依赖

- Python 3.10+
- 网络访问 iCenter 测试/生产 API
- MySQL 入库可选（`pymysql`）

## 与 ai-loop 内嵌技能的关系

- `ai-loop/skills/fb-account-tag-pipeline/`：仓库内副本（开发时同步）
- `d:\桌面文件\fb-account-tag-pipeline\`：**独立发行副本**（本目录）
