import { state } from "./state.js";
import { esc, fetchJson, fmtDateTime, fmtNum, lineLabel, modeLabel, qs, statusLabel, statusTone } from "./utils.js";

function resultSummary(row) {
  return `
    <div class="round-inline">
      <span class="round-result-main">成功 ${fmtNum(row.success_count)} / 失败 ${fmtNum(row.failed_count)} / 未提交 ${fmtNum(row.unsubmitted_count)}</span>
      <span class="table-sub-inline">请求 ${fmtNum(row.requested_count)}${Number(row.processing_count || 0) > 0 ? ` · 处理中 ${fmtNum(row.processing_count)}` : ""}</span>
    </div>
  `;
}

export function roundsQuery() {
  const params = new URLSearchParams();
  params.set("limit", String(state.pageSize));
  params.set("offset", String((state.page - 1) * state.pageSize));
  Object.entries(state.filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return params.toString();
}

export function renderRounds(payload) {
  const rows = payload.items || [];
  qs("rounds-tbody").innerHTML = rows.length
    ? rows.map((row) => `
      <tr>
        <td>
          <div class="round-inline">
            <span>${esc(fmtDateTime(row.exported_at || row.day_key || "-"))}</span>
            <span class="table-sub-inline">${esc(modeLabel(row.runtime_mode))}</span>
          </div>
        </td>
        <td>${esc(lineLabel(row.line_name))}</td>
        <td>
          <div class="round-inline">
            <span>${esc(row.round_name || "-")}</span>
            <span class="table-sub-inline">${esc(row.pool_name || "-")}</span>
          </div>
        </td>
        <td>${resultSummary(row)}</td>
        <td>
          <div class="round-judgement-cell round-inline">
            <span class="status-pill ${esc(row.judgement_tone || statusTone(row.status))}">${esc(row.judgement_label || statusLabel(row.status))}</span>
            <span class="table-sub-inline">状态 ${esc(statusLabel(row.status))}</span>
          </div>
        </td>
        <td class="note-cell">
          <div class="round-note-scroll">
            <div>${esc(row.primary_issue || "-")}</div>
            ${row.unsubmitted_summary && row.unsubmitted_summary !== "-" ? `<div class="table-sub">${esc(row.unsubmitted_summary)}</div>` : ""}
          </div>
        </td>
        <td><button class="ghost-btn detail-btn" data-archive="${esc(row.archive_key)}">查看</button></td>
      </tr>
    `).join("")
    : '<tr><td colspan="7">没有匹配到轮次</td></tr>';

  qs("rounds-page-info").textContent = `共 ${fmtNum(payload.total)} 条 · 当前第 ${state.page} 页`;
  document.querySelectorAll(".detail-btn").forEach((button) => {
    button.addEventListener("click", () => openRoundDetail(button.getAttribute("data-archive")));
  });
}

export async function openRoundDetail(archiveKey) {
  if (!archiveKey) return;
  const payload = await fetchJson(`./api/test-pool/round/${encodeURIComponent(archiveKey)}`);
  const archive = payload.archive || payload;
  qs("drawer-title").textContent = archive.label || archive.round_name || "轮次详情";
  qs("drawer-subtitle").textContent = `${fmtDateTime(archive.exported_at)} ｜ ${lineLabel(archive.line_name)} ｜ ${modeLabel(archive.runtime_mode)}`;
  qs("detail-summary").innerHTML = [
    ["请求", fmtNum(archive.requested_count)],
    ["成功", fmtNum(archive.success_count)],
    ["失败", fmtNum(archive.failed_count)],
    ["未提交", fmtNum(archive.unsubmitted_count)],
    ["状态", statusLabel(archive.status)],
    ["账号池", archive.pool_name || "-"],
  ].map(([label, value]) => `
    <div class="detail-card">
      <span>${esc(label)}</span>
      <strong>${esc(value)}</strong>
    </div>
  `).join("");

  const items = payload.items || [];
  qs("detail-items").innerHTML = items.length
    ? items.map((item) => `
      <tr>
        <td>${fmtNum(item.item_index)}</td>
        <td>${esc(item.account_name || "-")}</td>
        <td>${esc(item.title || "-")}</td>
        <td>${esc(item.source_mode || "-")}</td>
        <td>${esc(item.clip_method || "-")}</td>
        <td class="detail-status-cell">
          <span class="status-pill ${esc(statusTone(item.publish_status))}">${esc(statusLabel(item.publish_status))}</span>
        </td>
        <td>
          <div class="detail-failure-scroll">${esc(item.failure_reason || "-")}</div>
        </td>
      </tr>
    `).join("")
    : '<tr><td colspan="7">当前没有任务明细</td></tr>';
  qs("detail-drawer").classList.add("open");
  qs("detail-drawer").setAttribute("aria-hidden", "false");
}

export function closeDrawer() {
  qs("detail-drawer").classList.remove("open");
  qs("detail-drawer").setAttribute("aria-hidden", "true");
}

export async function loadRounds() {
  const payload = await fetchJson(`./api/test-pool/rounds?${roundsQuery()}`);
  renderRounds(payload);
  state.roundsLoaded = true;
}
