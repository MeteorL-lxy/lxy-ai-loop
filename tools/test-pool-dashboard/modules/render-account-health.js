import { esc, fmtDateTime, fmtNum, fmtPct, qs, statusTone } from "./utils.js";

let latestPayload = null;

function healthMetric(label, value, note, tone = "plain") {
  return `
    <article class="metric-card ${esc(tone)}">
      <div class="metric-label">${esc(label)}</div>
      <div class="metric-value">${esc(value)}</div>
      <div class="metric-note">${esc(note || "-")}</div>
    </article>
  `;
}

function rowMatchesFilter(row, filter) {
  if (filter === "idle") return row.is_idle && row.can_publish_reels;
  if (filter === "active") return Number(row.today_tasks || 0) > 0;
  if (filter === "reels_blocked") return !row.can_publish_reels;
  if (filter === "abnormal") return ["授权异常", "发布异常", "不能发Reels"].includes(row.health_status);
  return true;
}

function rowMatchesSearch(row, keyword) {
  if (!keyword) return true;
  const haystack = [
    row.id,
    row.agent_id,
    row.social_name,
    row.auth_status,
    row.health_status,
    row.latest_error,
    ...(row.pool_labels || []),
  ].join(" ").toLowerCase();
  return haystack.includes(keyword.toLowerCase());
}

function sortAccounts(rows) {
  const priority = {
    "不能发Reels": 1,
    "授权异常": 2,
    "发布异常": 3,
    "闲置可用": 4,
    "正常在用": 5,
    "可用未发": 6,
  };
  return [...rows].sort((a, b) => {
    const pa = priority[a.health_status] || 99;
    const pb = priority[b.health_status] || 99;
    if (pa !== pb) return pa - pb;
    return Number(b.today_tasks || 0) - Number(a.today_tasks || 0);
  });
}

function renderSummary(payload) {
  const summary = payload.summary || {};
  const cards = [
    ["账号总数", fmtNum(summary.total_accounts), payload.scope_label || "当前范围", "plain"],
    ["正常授权", fmtNum(summary.normal_auth_accounts), `异常授权 ${fmtNum(summary.auth_abnormal_accounts)}`, "good"],
    ["可用账号", fmtNum(summary.available_accounts), "正常授权且未命中 Reels 限制", "good"],
    ["今日在用", fmtNum(summary.active_today_accounts), `未发 ${fmtNum(summary.no_today_accounts)}`, "running"],
    ["今日任务", fmtNum(summary.today_tasks), `成功 ${fmtNum(summary.today_success)} / 失败 ${fmtNum(summary.today_failed)}`, "plain"],
    ["今日成功率", fmtPct(summary.today_success_rate), `处理中 ${fmtNum(summary.today_running)}`, "good"],
    ["闲置可用", fmtNum(summary.idle_available_accounts), `7天无任务 ${fmtNum(summary.idle_accounts)}`, "idle"],
    ["不能发 Reels", fmtNum(summary.reels_blocked_accounts), `发布异常 ${fmtNum(summary.publish_abnormal_accounts)}`, summary.reels_blocked_accounts ? "error" : "good"],
  ];
  qs("account-health-grid").innerHTML = cards.map(([label, value, note, tone]) => healthMetric(label, value, note, tone)).join("");
  qs("account-health-meta").textContent = `${payload.scope_label || "-"} ｜ ${fmtDateTime(payload.last_updated)}`;
}

function renderTopErrors(payload) {
  const rows = payload.top_errors || [];
  qs("account-error-list").innerHTML = rows.length
    ? rows.map((row) => `
      <div class="reason-item">
        <strong>${esc(row.reason || "-")}</strong>
        <span>${fmtNum(row.count)} 个账号最近命中过</span>
      </div>
    `).join("")
    : '<div class="empty-state">当前没有最近失败原因。</div>';
}

function renderPoolSummary(payload) {
  const rows = payload.pool_summary || [];
  qs("account-pool-health-tbody").innerHTML = rows.length
    ? rows.map((row) => `
      <tr>
        <td>
          <strong>${esc(row.label || row.key || "-")}</strong>
          <div class="sub-key">${esc(row.key || "-")}</div>
        </td>
        <td>${fmtNum(row.accounts)}</td>
        <td>${fmtNum(row.active_today)}</td>
        <td>${fmtNum(row.idle)}</td>
        <td>${fmtNum(row.reels_blocked)}</td>
        <td>${fmtNum(row.today_tasks)}</td>
        <td>${fmtPct(row.today_success_rate)}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="7">暂无账号池健康数据</td></tr>';
}

export function renderAccountHealthDetails() {
  if (!latestPayload) return;
  const filter = qs("account-health-filter")?.value || "all";
  const keyword = qs("account-health-search")?.value.trim() || "";
  const rows = sortAccounts(latestPayload.accounts || [])
    .filter((row) => rowMatchesFilter(row, filter))
    .filter((row) => rowMatchesSearch(row, keyword));
  const visibleRows = rows.slice(0, 260);
  qs("account-health-tbody").innerHTML = visibleRows.length
    ? visibleRows.map((row) => {
      const tone = row.health_tone || statusTone(row.latest_status);
      const reelsText = row.can_publish_reels
        ? "可发"
        : `不可发${row.reels_blocked_at ? `｜${fmtDateTime(row.reels_blocked_at)}` : ""}`;
      return `
        <tr>
          <td>
            <strong>${esc(row.social_name || "-")}</strong>
            <div class="sub-key">social_id ${esc(row.id)} ｜ agent ${esc(row.agent_id || "-")}</div>
          </td>
          <td>${esc((row.pool_labels || []).join(" / ") || "未分池")}</td>
          <td><span class="status-pill ${esc(tone)}">${esc(row.health_status || "-")}</span></td>
          <td>
            <strong>${fmtNum(row.today_tasks)}</strong>
            <div class="sub-key">成功 ${fmtNum(row.today_success)} / 失败 ${fmtNum(row.today_failed)}</div>
          </td>
          <td>
            <strong>${fmtNum(row.seven_tasks)}</strong>
            <div class="sub-key">成功率 ${fmtPct(row.seven_success_rate)}</div>
          </td>
          <td>${row.is_idle ? "是" : "否"}</td>
          <td>${esc(reelsText)}</td>
          <td>
            <strong>${esc(row.latest_status || "-")}</strong>
            <div class="sub-key">${esc(fmtDateTime(row.latest_post_at))}</div>
            ${row.latest_error ? `<div class="issue-inline">${esc(row.latest_error)}</div>` : ""}
          </td>
          <td>${esc(row.recommendation || "-")}</td>
        </tr>
      `;
    }).join("")
    : '<tr><td colspan="9">没有符合筛选条件的账号。</td></tr>';
}

export function renderAccountHealth(payload) {
  latestPayload = payload;
  if (!payload.available) {
    qs("account-health-grid").innerHTML = healthMetric("账号健康不可用", "配置待补", payload.error || "请检查数据库连接配置", "error");
    qs("account-health-meta").textContent = fmtDateTime(payload.last_updated);
    qs("account-error-list").innerHTML = '<div class="empty-state">账号健康 API 暂不可用。</div>';
    qs("account-pool-health-tbody").innerHTML = '<tr><td colspan="7">账号健康 API 暂不可用</td></tr>';
    qs("account-health-tbody").innerHTML = '<tr><td colspan="9">账号健康 API 暂不可用</td></tr>';
    return;
  }
  renderSummary(payload);
  renderTopErrors(payload);
  renderPoolSummary(payload);
  renderAccountHealthDetails();
}
