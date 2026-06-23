# 字段规则（流水线版）

> 完整审阅文档：`skills/account-tag-audit/references/field-guide.md`

## 统计窗口

- 默认 **近 30 天**（`LOOKBACK_DAYS=30`）；`0` 为全历史
- analysis 热帖阈值：**>500** 播放；千播：**>1000**

## 合并表字段

| 字段 | 规则 |
|------|------|
| `agent_id` | 登录 uid；`67020404` 对应账号池 `2`，其余有 agent 为 `1` |
| 账号池 | `account_pool_label_for_agent(uid)` |
| 养号天数 | post-list 成功帖 **去重发帖天数**（`post_day_count`） |
| 首投剧类型 / 首投受众 | 默认空；仅 `account_tags_manual.json` 覆盖 |
| 互动反馈（ai汇总） | 默认空（自动互动率已关） |
| 最佳发帖时段 | 全历史；仅 >500 播放帖；格式 `7-8点50%（1800）`（占比为帖数占比） |
| 内容语种 / 剧场偏好 | >500 帖的剧名（播放量），降序 |
| 策略\|推荐日更条数 | 空 |
| tag | `区域\|超500语种\|播放量等级\|均播/帖`（无数据段省略） |

## 运行相关（post-list）

| 字段 | 来源 |
|------|------|
| 运行总数 / 运行成功 / 运行失败 | post-list 聚合 `runs_total` 等 |
| 有播放量帖数 / 总播放量 | analysis 按账号汇总 |
| Reels封禁 | blocklist + 最近 REEL 帖状态 |

## 对账

- CSV 行数 = 账号数（非帖子数）
- `views_match_platform=true` 时，账号「总播放量」求和 ≈ `platform_total_views_api`
- 后台漏斗「视频观看数」≈ `platform_total_views_api`（与发帖条数无关）
