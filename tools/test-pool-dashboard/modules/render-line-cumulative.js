import { esc, fmtDateTime, fmtMoney, fmtNum, qs } from "./utils.js";

export function renderLineCumulative(overview) {
  const payload = overview.line_cumulative || {};
  const node = qs("line-cumulative-block");
  const meta = qs("line-cumulative-meta");
  if (!node || !meta) return;

  meta.textContent = payload && payload.available
    ? `${payload.start_day || "-"} 至 ${payload.end_day || "-"} ｜ 缓存更新 ${fmtDateTime(payload.updated_at)}`
    : "从 2026-05-19 开始统计到今天的线路累计汇总";

  if (!payload || !payload.available) {
    node.innerHTML = `<div class="empty-state">${esc(payload?.note || "当前还没有可展示的线路累计汇总。")}</div>`;
    return;
  }

  const rows = (Array.isArray(payload.rows) ? payload.rows.slice() : []).sort((a, b) => {
    const viewDelta = Number(b?.view_total || 0) - Number(a?.view_total || 0);
    if (viewDelta !== 0) return viewDelta;
    const clickDelta = Number(b?.click_total || 0) - Number(a?.click_total || 0);
    if (clickDelta !== 0) return clickDelta;
    const incomeDelta = Number(b?.income_total || 0) - Number(a?.income_total || 0);
    if (incomeDelta !== 0) return incomeDelta;
    return String(a?.line_label || "").localeCompare(String(b?.line_label || ""), "zh-CN");
  });
  node.innerHTML = `
    ${payload.note ? `<div class="history-inline-note">${esc(payload.note)}</div>` : ""}
    <div class="table-wrap table-wrap-five-rows line-cumulative-wrap">
      <table class="data-table compact line-cumulative-table">
        <thead>
          <tr>
            <th>线路</th>
            <th>账号数</th>
            <th>累计播放</th>
            <th>累计点击</th>
            <th>累计总收益<br><span class="table-sub">分佣 + 广告 + 订单</span></th>
            <th>累计互动</th>
          </tr>
        </thead>
        <tbody>
          ${rows.length ? rows.map((row) => `
            <tr>
              <td><strong>${esc(row.line_label || "-")}</strong></td>
              <td>${fmtNum(row.account_count)}</td>
              <td>${fmtNum(row.view_total)}</td>
              <td>${fmtNum(row.click_total)}</td>
              <td>${fmtMoney(row.income_total)}<span class="table-sub">分佣 ${fmtMoney(row.share_income_total)} / 广告 ${fmtMoney(row.ad_income_total)} / 订单 ${fmtMoney(row.order_amount_total)}</span></td>
              <td>${fmtNum(row.interaction_total)}</td>
            </tr>
          `).join("") : `<tr><td colspan="6">暂无线路累计样本</td></tr>`}
        </tbody>
      </table>
    </div>
  `;
}
