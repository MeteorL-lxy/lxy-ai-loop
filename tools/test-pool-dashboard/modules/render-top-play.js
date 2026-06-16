import { esc, fmtDateTime, fmtNum, lineLabel, qs } from "./utils.js";

export function renderTopPlay(overview) {
  const payload = overview.today_top_play || {};
  const items = payload.items || [];
  const grid = qs("top-play-grid");
  if (!items.length) {
    grid.innerHTML = `<div class="empty-state">${esc(payload.note || "今天还没有拉到播放回收，先不展示假数据。")}</div>`;
    return;
  }
  grid.innerHTML = items.slice(0, 5).map((item, index) => `
    <article class="top-play-card">
      <div class="top-rank">TOP ${index + 1}</div>
      <h3>${esc(item.title || "-")}</h3>
      <div class="top-play-meta">${esc(fmtDateTime(item.published_at || item.created_at || payload.day_key || "-"))} ｜ ${esc(item.account_name || "-")} ｜ ${esc(item.platform || "FACEBOOK")}</div>
      <div class="top-play-metrics">
        <div><span>播放</span><strong>${fmtNum(item.view_count)}</strong></div>
        <div><span>点赞</span><strong>${fmtNum(item.like_count)}</strong></div>
        <div><span>评论</span><strong>${fmtNum(item.comment_count)}</strong></div>
        <div><span>分享</span><strong>${fmtNum(item.share_count)}</strong></div>
      </div>
      <div class="tag-row">
        <span class="line-chip">${esc(item.line_label || lineLabel(item.line_name))}</span>
        ${item.clip_method ? `<span class="line-chip">${esc(item.clip_method)}</span>` : ""}
      </div>
      <div class="top-play-copy-title">发布文案</div>
      <div class="top-play-copy">${esc(item.copy_text || "-")}</div>
    </article>
  `).join("");
}
