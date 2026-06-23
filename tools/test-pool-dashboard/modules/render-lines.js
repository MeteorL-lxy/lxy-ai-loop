import { LINE_ORDER, LINE_STRATEGIES } from "./state.js";
import {
  computeLineScore,
  esc,
  fmtDateTime,
  fmtNum,
  fmtPct,
  isMeaningfulIssue,
  lineLabel,
  normalizeIssue,
  qs,
  rangeLabel,
  rewriteLineNames,
  statusLabel,
  statusTone,
} from "./utils.js";

export function buildIssueMap(overview, failures) {
  const todayKey = overview?.overall_summary?.summary_day_key || "";
  const recentFailed = failures?.recent_failed || [];
  const issueMap = new Map();

  recentFailed.forEach((item) => {
    if (todayKey && item.day_key !== todayKey) return;
    const lineName = String(item.line_name || "").trim();
    const normalized = normalizeIssue(item.failure_reason || item.publish_status, item.title || "");
    if (!lineName || !isMeaningfulIssue(normalized)) return;
    const timeText = fmtDateTime(item.exported_at || item.day_key || todayKey);
    const bucket = issueMap.get(lineName) || new Map();
    const existing = bucket.get(normalized);
    if (existing) {
      existing.count += 1;
      if (timeText > existing.timeText) existing.timeText = timeText;
    } else {
      bucket.set(normalized, { text: normalized, timeText, count: 1 });
    }
    issueMap.set(lineName, bucket);
  });

  const normalizedMap = new Map();
  issueMap.forEach((bucket, lineName) => {
    normalizedMap.set(
      lineName,
      [...bucket.values()].sort((a, b) => String(b.timeText).localeCompare(String(a.timeText))),
    );
  });
  return normalizedMap;
}

export function sortedLines(rows) {
  const orderMap = new Map(LINE_ORDER.map((name, index) => [name, index]));
  return [...rows].sort((a, b) => {
    const aIndex = orderMap.has(a.line_name) ? orderMap.get(a.line_name) : 999;
    const bIndex = orderMap.has(b.line_name) ? orderMap.get(b.line_name) : 999;
    return aIndex - bIndex;
  });
}

export function renderLineCards(overview, failures) {
  const loop = overview.loop_overview || {};
  const rows = sortedLines((loop.line_targets || []).filter((row) => row.line_name !== "novel"));
  const issueMap = buildIssueMap(overview, failures);
  const container = qs("line-grid");

  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前没有可展示的线路数据。</div>';
    return;
  }

  container.innerHTML = rows.map((row) => {
    const score = computeLineScore(row);
    const progressPct = Math.max(0, Math.min(100, Number(row.progress_pct || 0)));
    const stabilityPct = Math.max(0, Math.min(100, Number(row.stability_pct || 0)));
    const statusText = row.is_running ? "运行中" : statusLabel(row.runtime_state);
    const remaining = Math.max(0, Number(row.target_total || 0) - Number(row.success_count || 0));
    const issues = issueMap.get(row.line_name) || [];
    const strategyText = String(LINE_STRATEGIES[row.line_name] || row.pool_key || "-");
    const strategyRows = strategyText
      .split("\n")
      .map((line) => String(line || "").trim())
      .filter(Boolean)
      .map((line) => {
        const [label, ...rest] = line.split("：");
        if (!rest.length) {
          return `<div class="strategy-row"><span class="strategy-v">${esc(line)}</span></div>`;
        }
        return `
          <div class="strategy-row">
            <span class="strategy-k">${esc(label)}：</span>
            <span class="strategy-v">${esc(rest.join("："))}</span>
          </div>
        `;
      })
      .join("");
    const issueHtml = issues.length
      ? `<div class="issue-list">${issues.slice(0, 3).map((item) => `
          <div class="issue-item">
            <span class="issue-time">${esc(item.timeText)}</span>
            <span class="issue-text">${esc(item.text)}${item.count > 1 ? `（${fmtNum(item.count)}次）` : ""}</span>
          </div>
        `).join("")}</div>`
      : `<div class="line-block-text">今天暂时没有明确问题，先继续看实时状态。</div>`;

    return `
      <article class="line-card">
        <div class="line-card-head">
          <div>
            <div class="line-title-row">
              <h3>${esc(lineLabel(row.line_name) || rewriteLineNames(row.display_name) || "-")}</h3>
              <span class="status-pill ${esc(statusTone(row.is_running ? "processing" : row.runtime_state))}">${esc(statusText)}</span>
            </div>
            <div class="line-meta-pills">
              <span class="meta-chip">测试时间范围 ${esc(rangeLabel(row.line_name))}</span>
              <span class="meta-chip">账号数量 ${fmtNum(row.pool_size)} 个</span>
              <span class="meta-chip">最近一轮时间 ${esc(fmtDateTime(row.last_update))}</span>
            </div>
          </div>
          <div class="score-box">
            <strong>${esc(score.text)}</strong>
            <span>${esc(score.grade)}</span>
          </div>
        </div>

        <div class="line-section-title">今日累计</div>
        <div class="line-stats">
          <div class="mini-stat"><span>成功</span><strong>${fmtNum(row.success_count)}</strong></div>
          <div class="mini-stat"><span>目标</span><strong>${fmtNum(row.target_total)}</strong></div>
          <div class="mini-stat"><span>还差</span><strong>${fmtNum(remaining)}</strong></div>
        </div>

        <div class="progress-block">
          <div class="progress-row">
            <span>今日进度</span>
            <div class="progress-bar"><i style="width:${progressPct}%;"></i></div>
            <strong>${fmtPct(progressPct)}</strong>
          </div>
          <div class="progress-row">
            <span>稳定性</span>
            <div class="progress-bar progress-bar-green"><i style="width:${stabilityPct}%;"></i></div>
            <strong>${fmtPct(stabilityPct)}</strong>
          </div>
        </div>

        <div class="line-bottom">
          <div class="line-block">
            <div class="line-block-title">线路策略</div>
            <div class="line-block-text strategy-block">${strategyRows}</div>
          </div>
          <div class="line-block">
            <div class="line-block-title">当天问题</div>
            ${issueHtml}
          </div>
        </div>
      </article>
    `;
  }).join("");
}
