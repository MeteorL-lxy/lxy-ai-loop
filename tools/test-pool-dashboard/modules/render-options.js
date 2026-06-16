import { esc, lineLabel, modeLabel, qs, statusLabel } from "./utils.js";

export function renderOptions(options) {
  const bindSelect = (id, values, formatter = (v) => v) => {
    const el = qs(id);
    const current = el.value;
    const first = el.querySelector("option")?.outerHTML || "";
    el.innerHTML = first + (values || []).map((value) => `<option value="${esc(value)}">${esc(formatter(value))}</option>`).join("");
    el.value = current;
  };
  bindSelect("day-filter", options.days || []);
  bindSelect("mode-filter", options.runtime_modes || [], modeLabel);
  bindSelect("line-filter", options.lines || [], lineLabel);
  bindSelect("status-filter", options.statuses || [], statusLabel);
}
