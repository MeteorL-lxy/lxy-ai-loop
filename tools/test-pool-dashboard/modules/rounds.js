import { state } from "./state.js";
import { esc, fetchJson, fmtDateTime, fmtNum, lineLabel, modeLabel, qs, statusLabel, statusTone } from "./utils.js";

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
        <td>${esc(fmtDateTime(row.exported_at || row.day_key || "-"))}</td>
        <td>${esc(modeLabel(row.runtime_mode))}</td>
        <td>${esc(lineLabel(row.line_name))}</td>
        <td>${esc(row.round_name || "-")}</td>
        <td>${fmtNum(row.requested_count)}</td>
        <td>${fmtNum(row.success_count)}</td>
        <td>${fmtNum(row.failed_count)}</td>
        <td>${fmtNum(row.unsubmitted_count)}</td>
        <td><span class="status-pill ${esc(statusTone(row.status))}">${esc(statusLabel(row.status))}</span></td>
        <td class="note-cell">${esc(row.note || "-")}</td>
        <td><button class="ghost-btn detail-btn" data-archive="${esc(row.archive_key)}">查看</button></td>
      </tr>
    `).join("")
    : '<tr><td colspan="11">没有匹配到轮次</td></tr>';

  qs("rounds-page-info").textContent = `共 ${fmtNum(payload.total)} 条 · 当前第 ${state.page} 页`;
  document.querySelectorAll(".detail-btn").forEach((button) => {
    button.addEventListener("click", () => openRoundDetail(button.getAttribute("data-archive")));
  });
}

export async function openRoundDetail(archiveKey) {
  if (!archiveKey) return;
  const payload = await fetchJson(`./api/test-pool/round/${encodeURIComponent(archiveKey)}`);
  qs("drawer-title").textContent = payload.label || payload.round_name || "轮次详情";
  qs("drawer-subtitle").textContent = `${fmtDateTime(payload.exported_at)} ｜ ${lineLabel(payload.line_name)} ｜ ${modeLabel(payload.runtime_mode)}`;
  qs("detail-summary").innerHTML = [
    ["请求", fmtNum(payload.requested_count)],
    ["成功", fmtNum(payload.success_count)],
    ["失败", fmtNum(payload.failed_count)],
    ["未提交", fmtNum(payload.unsubmitted_count)],
    ["状态", statusLabel(payload.status)],
    ["账号池", payload.pool_name || "-"],
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
        <td>${esc(statusLabel(item.publish_status))}</td>
        <td>${esc(item.failure_reason || "-")}</td>
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
