import { metricCard, metricDisplay, fmtMoney, fmtNum, fmtPct, fmtDateTime, qs } from "./utils.js";

export function renderOverall(overview) {
  const summary = overview.overall_summary || {};
  const viewMissing = Number(summary.overall_view_total || 0) === 0;
  const clickMissing = Number(summary.overall_click_total || 0) === 0;
  const interactionMissing = Number(summary.overall_interaction_total || 0) === 0;
  const incomeMissing = Number(summary.overall_income_total || 0) === 0;
  const items = [
    { label: "总账号数", value: fmtNum(summary.publish_account_total), note: "账号池去重后总数", tone: "blue" },
    { label: "已使用账号数", value: fmtNum(summary.used_pool_account_count), note: "执行线账号池合计", tone: "green" },
    { label: "备用账号数", value: fmtNum(summary.reserve_accounts), note: "当前备用池数量", tone: "plain" },
    { label: "累计总播放量", value: metricDisplay(summary.overall_view_total, { missing: viewMissing }), note: viewMissing ? "真实播放累计待接入" : "Facebook 播放累计", tone: "blue" },
    { label: "累计总推广链接点击数", value: metricDisplay(summary.overall_click_total, { missing: clickMissing }), note: clickMissing ? "真实点击累计待接入" : "推广链接点击累计", tone: "plain" },
    { label: "累计总互动量", value: metricDisplay(summary.overall_interaction_total, { missing: interactionMissing }), note: interactionMissing ? "互动累计待接入" : "点赞 + 评论 + 分享", tone: "green" },
    { label: "总收益", value: metricDisplay(summary.overall_income_total, { money: true, missing: incomeMissing }), note: incomeMissing ? "真实收益累计待接入" : "累计分佣 / 广告收益", tone: "green" },
    { label: "总线路数", value: fmtNum(summary.total_line_count), note: "不含小说线", tone: "plain" },
  ];
  qs("overall-grid").innerHTML = items.map(metricCard).join("");
}

export function renderToday(overview) {
  const summary = overview.overall_summary || {};
  const requested = Number(summary.today_requested_count || 0);
  const success = Number(summary.today_success_count || 0);
  const failed = Number(summary.today_failed_count || 0);
  const todayKey = summary.today_metrics_day_key || summary.summary_day_key || "-";
  const todayViewMissing = Number(summary.today_view_total || 0) === 0;
  const todayClickMissing = Number(summary.today_click_total || 0) === 0;
  const todayInteractionMissing = Number(summary.today_interaction_total || 0) === 0;
  const items = [
    { label: "今日发起数", value: fmtNum(requested), note: `统计日期 ${todayKey}`, tone: "blue" },
    { label: "今日成功数", value: fmtNum(success), note: `成功账号 ${fmtNum(summary.success_accounts_today)}`, tone: "green" },
    { label: "今日失败数", value: fmtNum(failed), note: "发布管理 ERROR 口径", tone: "plain" },
    { label: "今日成功率", value: fmtPct(summary.today_success_rate), note: `剧目数 ${fmtNum(summary.title_count_today)}`, tone: "green" },
    { label: "今日播放量", value: metricDisplay(summary.today_view_total, { missing: todayViewMissing }), note: todayViewMissing ? "今日播放回收待接入" : "Facebook 今日播放", tone: "plain" },
    { label: "今日点击数", value: metricDisplay(summary.today_click_total, { missing: todayClickMissing }), note: todayClickMissing ? "今日点击回收待接入" : "今日推广链接点击", tone: "blue" },
    { label: "今日互动量", value: metricDisplay(summary.today_interaction_total, { missing: todayInteractionMissing }), note: todayInteractionMissing ? "今日互动回收待接入" : "点赞 + 评论 + 分享", tone: "plain" },
  ];
  qs("today-meta").textContent = `每30秒自动刷新一次 最后更新 ${fmtDateTime(overview.last_exported_at)}`;
  qs("today-grid").innerHTML = items.map(metricCard).join("");
}
