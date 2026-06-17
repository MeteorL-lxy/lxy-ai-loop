import { esc, fmtDateTime, fmtMoney, fmtNum, fmtPct, fmtTrendValue, lineLabel, qs } from "./utils.js";

export function renderDailyTopHistory(overview) {
  const payload = overview.daily_top_history || {};
  const node = qs("daily-top-history-block");
  const meta = qs("daily-history-meta");
  meta.textContent = payload && payload.available
    ? `${payload.start_day || "-"} 至 ${payload.end_day || "-"} ｜ 缓存更新 ${fmtDateTime(payload.updated_at)}`
    : "从 2026-05-19 开始到昨天的每日最高播放样本";

  if (!payload || !payload.available) {
    node.innerHTML = `<div class="empty-state">${esc(payload?.note || "当前还没有可展示的每日最高播放样本。")}</div>`;
    return;
  }

  const summaryCards = (payload.summary_cards || []).map((card) => {
    const lines = Array.isArray(card.note_lines) ? card.note_lines : [];
    const note = card.note ? `<div class="history-sample-note">${esc(card.note)}</div>` : "";
    const metaRows = lines.length
      ? `<div class="history-sample-meta">${lines.map((line) => `<div class="history-sample-meta-row">${esc(line)}</div>`).join("")}</div>`
      : "";
    return `
      <article class="history-sample-card">
        <div class="history-sample-top">
          <div class="history-sample-label">${esc(card.label || "-")}</div>
          <div class="history-sample-value">${esc(fmtTrendValue(card.value, card.kind))}</div>
          ${note}
        </div>
        ${metaRows}
      </article>
    `;
  }).join("");

  const rows = payload.rows || [];
  node.innerHTML = `
    ${payload.note ? `<div class="history-inline-note">${esc(payload.note)}</div>` : ""}
    <div class="history-card-grid-sample">
      ${summaryCards}
    </div>
    <div class="table-wrap table-wrap-five-rows history-table-wrap">
      <table class="data-table daily-history-table">
        <colgroup>
          <col class="daily-col-day">
          <col class="daily-col-metric">
          <col class="daily-col-metric">
          <col class="daily-col-metric">
          <col class="daily-col-metric">
          <col class="daily-col-line">
          <col class="daily-col-copy">
          <col class="daily-col-publish">
        </colgroup>
        <thead>
          <tr>
            <th>日期</th>
            <th>播放</th>
            <th>点击</th>
            <th>收益</th>
            <th>互动</th>
            <th>线路 / 账号</th>
            <th>发布文案</th>
            <th>发布时间</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td>${esc(row.day_key || "-")}</td>
              <td><strong>${fmtNum(row.view_count)}</strong></td>
              <td>${fmtNum(row.click_total)}</td>
              <td>${fmtMoney(row.income_total)}</td>
              <td>
                ${fmtNum(row.interaction_total)}
                <div class="table-sub">${fmtNum(row.like_count)} / ${fmtNum(row.comment_count)} / ${fmtNum(row.share_count)}</div>
              </td>
              <td>
                <div>${esc(row.line_label || lineLabel(row.line_name))}</div>
                <div class="table-sub">${esc(row.account_name || "-")}</div>
              </td>
              <td>
                <div class="daily-copy-cell">
                  <div class="daily-copy-scroll">${esc(row.copy_text || "-")}</div>
                </div>
              </td>
              <td>
                <div>${esc(fmtDateTime(row.published_at))}</div>
                <div class="table-sub">${esc(row.metric_scope || "当天任务总口径")} · 点击 ${fmtNum(row.click_total)} · 收益 ${fmtMoney(row.income_total)}</div>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

export function renderHistory(overview) {
  const payload = overview.trend_analyzer || overview.historical_daily_report || {};
  const node = qs("history-block");
  if (payload && payload.available) {
    const renderCard = (card) => {
      const deltaLine = card.delta === null || card.delta === undefined
        ? ""
        : `<div class="history-delta ${Number(card.delta || 0) >= 0 ? "up" : "down"}">
            较前一天 ${Number(card.delta || 0) >= 0 ? "+" : ""}${fmtTrendValue(card.delta, card.kind)}
            ${card.delta_pct === null || card.delta_pct === undefined ? "" : ` · ${Number(card.delta_pct || 0) >= 0 ? "+" : ""}${card.delta_pct.toFixed(2)}%`}
          </div>`;
      return `
        <article class="history-metric-card">
          <div class="history-metric-label">${esc(card.label || "-")}</div>
          <div class="history-metric-value">${esc(fmtTrendValue(card.value, card.kind))}</div>
          ${deltaLine}
          <div class="history-metric-note">${esc(card.note || "-")}</div>
        </article>
      `;
    };

    const dailyRows = payload.daily_rows || [];
    const runningAverageTitle = payload.latest_day
      ? `从 2026-06-09 到 ${payload.latest_day} 的均值`
      : "从 2026-06-09 到前一天的均值";
    const dailyTimelineTitle = payload.latest_day
      ? `2026-05-19 到 ${payload.latest_day} 的每日全体汇总`
      : "2026-05-19 到前一天的每日全体汇总";

    node.innerHTML = `
      <div class="history-summary">
        <div class="history-summary-main">
          <strong>分析日报口径</strong>
          <span>固定基线 ${esc(payload.baseline_start || "-")} 至 ${esc(payload.baseline_end || "-")} · 最新统计 ${esc(payload.latest_day || "-")}</span>
        </div>
        <div class="history-summary-sub">${esc(payload.latest_note || "-")}</div>
        ${payload.latest_summary ? `<div class="history-summary-tip">${esc(payload.latest_summary)}</div>` : ""}
      </div>

      <section class="history-section">
        <h3>固定基线均值</h3>
        <div class="history-card-grid">
          ${(payload.baseline_cards || []).map(renderCard).join("")}
        </div>
      </section>

      <section class="history-section">
        <h3>最新一天对比前一天</h3>
        <div class="history-card-grid">
          ${(payload.compare_cards || []).map(renderCard).join("")}
        </div>
      </section>

      <section class="history-section">
        <h3>${esc(runningAverageTitle)}</h3>
        <div class="history-card-grid compact">
          ${(payload.running_average_cards || []).map(renderCard).join("")}
        </div>
      </section>

      <section class="history-section">
        <h3>${esc(dailyTimelineTitle)}</h3>
        <div class="table-wrap table-wrap-five-rows">
          <table class="data-table compact">
            <thead>
              <tr>
                <th>日期</th>
                <th>发布</th>
                <th>成功</th>
                <th>失败</th>
                <th>播放</th>
                <th>点击</th>
                <th>互动</th>
                <th>成功率</th>
              </tr>
            </thead>
            <tbody>
              ${dailyRows.length ? dailyRows.map((row) => `
                <tr>
                  <td>${esc(row.day || "-")}</td>
                  <td>${fmtNum(row.publish_count)}</td>
                  <td>${fmtNum(row.success_count)}</td>
                  <td>${fmtNum(row.failed_count)}</td>
                  <td>${fmtNum(row.view_total)}</td>
                  <td>${fmtNum(row.click_total)}</td>
                  <td>${fmtNum(row.interaction_total)}</td>
                  <td>${fmtPct(row.success_rate)}</td>
                </tr>
              `).join("") : '<tr><td colspan="8">暂无趋势样本</td></tr>'}
            </tbody>
          </table>
        </div>
      </section>
    `;
    return;
  }
  node.innerHTML = `<div class="empty-state">${esc(payload.note || "这部分沿用 ai-loop-reporting 的趋势逻辑，当前本地还没有接回。")}</div>`;
}
