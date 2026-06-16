import { esc, fmtNum, qs } from "./utils.js";

export function renderAccountGroups(groups) {
  const tbody = qs("account-groups-tbody");
  tbody.innerHTML = groups.length
    ? groups.map((row) => `
      <tr>
        <td>
          <strong>${esc(row.label || row.key || "-")}</strong>
          <div class="sub-key">${esc(row.key || "-")}</div>
        </td>
        <td>${esc(row.description || "-")}</td>
        <td>${esc(row.platform || "-")}</td>
        <td>${fmtNum(row.count)}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="4">暂无账号池配置</td></tr>';
}
