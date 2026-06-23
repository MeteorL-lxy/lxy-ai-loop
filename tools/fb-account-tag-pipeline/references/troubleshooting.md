# 故障排查

## filtered=0（ID 未对齐）

**现象**：`fb=428 filtered=0`，该号 0 条进合并表。

**原因**：打标原始表的 `团队ID`/`账号ID` 与 social-list 白名单无交集。常见于**批量第一个号**时全局 allocation / post-list 状态未隔离，打出 `dual-path-test:*` 或旧池账号。

**处理**：
1. 单独重跑该手机号（独立 `--outdir`）
2. 确认 `filtered ≈ facebook_count`
3. 用 `merge_agent_into_main.py` 替换主表

## 播放量 CSV 远小于后台漏斗

**现象**：后台 1774 万观看，CSV「总播放量」求和仅几千。

**原因**：
- analysis 分页未拉全（`fetch_complete=false`，SSL 中断或未满页即停）
- 平台总数来自 API 第 1 页；按账号汇总依赖全部分页

**处理**：重跑该号直至 `fetch_complete=true`；核对 `account_sum_views` 接近 `platform_total_views_api`。

## 分页拉全

默认 `LOOKBACK_DAYS=30`，`MAX_ANALYSIS_PAGES=0`（无页数上限），在窗口内按 `total_count` 拉全。

若 `fetch_complete=false`，多为 API 报错或网络中断；查 `summary.json` / `*_timing.json` 中 `errors`。

仍要全历史时：`--days 0`（数据量大时耗时会明显增加）。

## post-list 与 analysis 完整性

跑完后检查 `per_phone/*_timing.json`：

```json
"post_list_meta": { "pages_fetched": 283, "fetch_complete": true }
```

以及 `per_phone/*.json` → `summary.fetch_complete`。

## 登录失败

验证码过期 → 更新 `--code` 或 `BEIDOU_LOGIN_CODE`。

## 常见误判

| 误解 | 实际 |
|------|------|
| `filtered=66` 表示删掉 66 条 | `filtered` = **保留**行数 |
| 1774 万 = 发帖条数 | 1774 万 = **播放量**；发帖看 `运行成功` / post-list |
| 全历史 = 一定拉全 | 默认近 30 天；`--days 0` 为全历史，仍受 API/网络影响 |
