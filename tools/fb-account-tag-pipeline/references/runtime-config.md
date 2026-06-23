# 运行配置

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `BEIDOU_LOGIN_CODE` | `951103` | 登录验证码 |
| `AI_ICENTER_BASE_URL` | `https://test-api-icenter.inbeidou.cn` | publish / analysis API |
| `LOOKBACK_DAYS` | `30` | 打标统计窗口（天）；`0`=全历史 |
| `AI_LOOP_MYSQL_HOST` | `124.174.76.6` | DB 导入主机 |
| `AI_LOOP_MYSQL_DATABASE` | `ai_loop` | DB 库名 |

## batch_tag_by_phones.py 参数

| 参数 | 说明 |
|------|------|
| `--phones` | 手机号列表文件（必填） |
| `--code` | 验证码 |
| `--outdir` | 输出目录 |
| `--skip-apify` | 跳过 Apify 主页爬取 |
| `--skip-db-import` | 跳过 MySQL upsert |
| `--days` | 统计窗口天数（默认 30；0=全历史） |
| `--no-restore-allocation` | 跑完后不恢复 `fb_account_allocation.json` |
| `--apify-full` | 全量 Apify（粉丝/资料完整度） |

## 合并表列

`agent_id` + `AUDIT_CSV_COLUMNS`（33 列中文），无 `phone` 列。

DB 英文表 34 列见 `scripts/export_account_tag_db.py` 的 `EXPORT_EN_COLUMNS`。

## DB 入库注意

`authorized_account_pool` 表 `phone` 字段若 NOT NULL 且无默认值，当前合并 CSV（无 phone）会导入失败。需改表、改 import 脚本，或导入前补 `phone` 列。
