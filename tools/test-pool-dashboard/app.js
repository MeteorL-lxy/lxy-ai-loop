const state = {
  autoRefreshMs: 30000,
  refreshing: false,
  optionsLoaded: false,
  roundsLoaded: false,
  page: 1,
  pageSize: 50,
  filters: {
    day: "",
    runtime_mode: "",
    line_name: "",
    status: "",
    search: "",
  },
};

const LINE_ORDER = [
  "realtime_day",
  "creative_list_day",
  "yourchannel",
  "realtime",
  "realtime_single",
  "creative_list",
  "ordinary",
  "fbhot_test",
];

const LINE_LABELS = {
  ordinary: "普通池线",
  realtime: "实时榜线",
  realtime_day: "白天实时榜线",
  realtime_single: "夜间实时榜定账号线",
  creative_list: "创意列表外部素材映射线",
  creative_list_day: "白天创意列表外部素材映射线",
  fbhot_test: "FB 热度加权线",
  yourchannel: "YourChannel 剧场线",
};

const LINE_STRATEGIES = {
  realtime_day: "白天手动线，优先发实时榜外部素材，窗口是 12:00-18:00。",
  creative_list_day: "白天手动线，承接创意列表外部素材映射，窗口是 12:00-18:00。",
  yourchannel: "白天剧场线，只发白名单剧名，走 YourChannel 剧场发布策略。",
  realtime: "夜间实时榜线，优先吃实时榜外部素材，重点看榜单命中和回收。",
  realtime_single: "夜间定账号线，单素材绑定单账号连续消耗，适合做更细的定向试跑。",
  creative_list: "夜间创意映射线，承接外部素材映射到真实任务发布。",
  ordinary: "夜间补量线，主要承接官方短剧稳定补量，保证底盘持续出量。",
  fbhot_test: "夜间热测线，用来测试 FB 热度优先策略，不直接代表主线表现。",
};

function qs(id) {
  return document.getElementById(id);
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtNum(value) {
  const num = Number(value || 0);
  return Number.isFinite(num) ? num.toLocaleString("zh-CN") : "-";
}

function fmtMoney(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "¥0";
  return `¥${num.toLocaleString("zh-CN", { minimumFractionDigits: num % 1 === 0 ? 0 : 2, maximumFractionDigits: 2 })}`;
}

function metricDisplay(value, { money = false, missing = false } = {}) {
  if (missing) return "待接入";
  return money ? fmtMoney(value) : fmtNum(value);
}

function fmtPct(value) {
  const num = Number(value || 0);
  return `${num.toFixed(2)}%`;
}

function fmtDateTime(value) {
  const text = String(value || "").trim();
  if (!text) return "-";
  return text.replace("T", " ");
}

function modeLabel(value) {
  const map = {
    continuous: "常驻",
    continuous_dual_line: "常驻双线",
    nightly_rounds: "夜间轮次",
    daily: "夜间轮次",
    novel: "小说流程",
  };
  return map[String(value || "").trim()] || value || "-";
}

function lineLabel(value) {
  return LINE_LABELS[String(value || "").trim()] || value || "-";
}

function statusLabel(value) {
  const key = String(value || "").trim();
  if (key.startsWith("published")) return "已提交";
  const map = {
    done: "已完成",
    failed: "失败",
    blocked: "阻塞",
    error: "异常",
    processing: "运行中",
    "未运行": "未运行",
    "未开始": "未运行",
    "处理中": "运行中",
    "已完成": "已完成",
    "失败": "失败",
    "阻塞": "阻塞",
    "异常": "异常",
  };
  return map[key] || key || "-";
}

function statusTone(value) {
  const key = String(value || "").trim();
  if (["processing", "处理中", "运行中"].includes(key)) return "running";
  if (key.startsWith("published") || ["done", "已完成"].includes(key)) return "done";
  if (["failed", "blocked", "error", "失败", "阻塞", "异常"].includes(key)) return "error";
  return "idle";
}

function isDayLine(lineName) {
  return ["realtime_day", "creative_list_day", "yourchannel"].includes(String(lineName || "").trim());
}

function rangeLabel(lineName) {
  return isDayLine(lineName) ? "12:00-18:00" : "18:00-次日12:00";
}

function metricCard(item) {
  return `
    <article class="metric-card ${esc(item.tone || "plain")}">
      <div class="metric-label">${esc(item.label)}</div>
      <div class="metric-value">${esc(item.value)}</div>
      <div class="metric-note">${esc(item.note || "-")}</div>
    </article>
  `;
}

function normalizeIssue(reason, title = "") {
  let text = String(reason || "").trim();
  if (!text) return "";
  if (title && text.startsWith(title)) {
    text = text.slice(title.length).replace(/^[:：,\s-]+/, "");
  }
  if (text.includes("下载状态=success，剪辑状态=failed，错误=")) {
    text = `剪辑失败：${text.split("下载状态=success，剪辑状态=failed，错误=")[1] || ""}`.trim();
  }
  if (text.includes("查询剪辑任务失败")) return "剪辑任务查询失败";
  if (text.includes("任务队列已满")) return "剪辑队列已满";
  if (text.includes("下载状态=failed") || text.includes("尚未进入剪辑")) return "素材下载后未进入剪辑";
  if (text.includes("HTTPSConnectionPool") || text.includes("Max retries exceeded")) return "上游接口超时";
  if (text.includes("moov atom not found") || text.includes("Invalid data found")) return "素材文件损坏";
  if (text.includes("探测视频信息失败") || text.includes("ffprobe 获取视频信息失败")) return "剪辑失败，视频信息探测没有通过";
  if (text.includes("查询开放API访问密钥失败")) return "ai-cut 密钥读取失败";
  if (text.includes("查询任务失败")) return "ai-cut 任务查询失败";
  if (text.includes("HTTP 500")) return "ai-cut 接口报错";
  if (text.includes("未找到视频流")) return "视频流识别失败，无法上传";
  if (text.includes("文件不存在")) return "素材文件缺失";
  if (text.includes("时长超限")) return "视频时长超限";
  if (text.includes("分辨率错误")) return "分辨率不符合要求";
  if (text.includes("post id is empty")) return "发布记录缺少 post id";
  return text.replace(/\s+/g, " ").slice(0, 80);
}

function isMeaningfulIssue(reason) {
  const text = String(reason || "").trim().toLowerCase();
  if (!text) return false;
  const ignored = [
    "processing",
    "pending",
    "submitting",
    "uploading",
    "uploaded",
    "处理中",
    "发布中",
    "等待发布",
    "发布成功",
  ];
  return !ignored.some((token) => text.includes(token));
}

function scoreGrade(score) {
  if (score >= 85) return "A";
  if (score >= 65) return "B";
  if (score >= 45) return "C";
  return "D";
}

function computeLineScore(row) {
  const progress = Number(row.progress_pct || 0);
  const stability = Number(row.stability_pct || 0);
  const requested = Number(row.requested_count || 0);
  const success = Number(row.success_count || 0);
  const failed = Number(row.failed_count || 0);
  const unsubmitted = Number(row.unsubmitted_count || 0);
  let score = 0;

  if (requested === 0 && success === 0 && failed === 0 && unsubmitted === 0) {
    score = row.is_running ? 18 : 14;
  } else {
    score = progress * 0.72 + stability * 0.28;
    if (row.is_running) score += 6;
    score -= Math.min(12, failed * 1.5 + unsubmitted);
  }

  score = Math.max(0, Math.min(100, score));
  return {
    value: score,
    text: score.toFixed(score >= 20 ? 1 : 0),
    grade: scoreGrade(score),
  };
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

function renderOverall(overview) {
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

function renderToday(overview) {
  const summary = overview.overall_summary || {};
  const requested = Number(summary.today_requested_count || 0);
  const success = Number(summary.today_success_count || 0);
  const failed = Math.max(0, requested - success);
  const todayKey = summary.today_metrics_day_key || summary.summary_day_key || "-";
  const todayViewMissing = Number(summary.today_view_total || 0) === 0;
  const todayClickMissing = Number(summary.today_click_total || 0) === 0;
  const todayInteractionMissing = Number(summary.today_interaction_total || 0) === 0;
  const items = [
    { label: "今日发起数", value: fmtNum(requested), note: `统计日期 ${todayKey}`, tone: "blue" },
    { label: "今日成功数", value: fmtNum(success), note: `成功账号 ${fmtNum(summary.success_accounts_today)}`, tone: "green" },
    { label: "今日失败数", value: fmtNum(failed), note: "按发起数减成功数计算", tone: "plain" },
    { label: "今日成功率", value: fmtPct(summary.today_success_rate), note: `剧目数 ${fmtNum(summary.title_count_today)}`, tone: "green" },
    { label: "今日播放量", value: metricDisplay(summary.today_view_total, { missing: todayViewMissing }), note: todayViewMissing ? "今日播放回收待接入" : "Facebook 今日播放", tone: "plain" },
    { label: "今日点击数", value: metricDisplay(summary.today_click_total, { missing: todayClickMissing }), note: todayClickMissing ? "今日点击回收待接入" : "今日推广链接点击", tone: "blue" },
    { label: "今日互动量", value: metricDisplay(summary.today_interaction_total, { missing: todayInteractionMissing }), note: todayInteractionMissing ? "今日互动回收待接入" : "点赞 + 评论 + 分享", tone: "plain" },
  ];
  qs("today-meta").textContent = `每30秒自动刷新一次 最后更新 ${fmtDateTime(overview.last_exported_at)}`;
  qs("today-grid").innerHTML = items.map(metricCard).join("");
}

function buildIssueMap(overview, failures) {
  const todayKey = overview?.overall_summary?.summary_day_key || "";
  const recentFailed = failures?.recent_failed || [];
  const issueMap = new Map();

  recentFailed.forEach((item) => {
    if (todayKey && item.day_key !== todayKey) return;
    const lineName = String(item.line_name || "").trim();
    const normalized = normalizeIssue(item.failure_reason || item.publish_status, item.title || "");
    if (!lineName || !isMeaningfulIssue(normalized)) return;
    const list = issueMap.get(lineName) || [];
    const timeText = fmtDateTime(item.exported_at || item.day_key || todayKey);
    const key = `${timeText}-${normalized}`;
    if (!list.some((row) => row.key === key)) {
      list.push({ key, timeText, text: normalized });
    }
    issueMap.set(lineName, list);
  });

  return issueMap;
}

function sortedLines(rows) {
  const orderMap = new Map(LINE_ORDER.map((name, index) => [name, index]));
  return [...rows].sort((a, b) => {
    const aIndex = orderMap.has(a.line_name) ? orderMap.get(a.line_name) : 999;
    const bIndex = orderMap.has(b.line_name) ? orderMap.get(b.line_name) : 999;
    return aIndex - bIndex;
  });
}

function renderLineCards(overview, failures) {
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
    const issueHtml = issues.length
      ? `<div class="issue-list">${issues.slice(0, 3).map((item) => `
          <div class="issue-item">
            <span class="issue-time">${esc(item.timeText)}</span>
            <span>${esc(item.text)}</span>
          </div>
        `).join("")}</div>`
      : `<div class="line-block-text">今天暂时没有明确问题，先继续看实时状态。</div>`;

    return `
      <article class="line-card">
        <div class="line-card-head">
          <div>
            <div class="line-title-row">
              <h3>${esc(row.display_name || lineLabel(row.line_name))}</h3>
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
            <div class="line-block-text">${esc(LINE_STRATEGIES[row.line_name] || row.pool_key || "-")}</div>
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

function renderTopPlay(overview) {
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
        <span class="line-chip">${esc(item.account_name || "-")}</span>
        ${item.clip_method ? `<span class="line-chip">${esc(item.clip_method)}</span>` : ""}
      </div>
      <div class="top-play-copy-title">正文</div>
      <div class="top-play-copy">${esc(item.copy_text || item.description || "-")}</div>
    </article>
  `).join("");
}

function fmtTrendValue(value, kind = "number") {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "-";
  if (kind === "money") return fmtMoney(num);
  if (kind === "percent") return `${num.toFixed(2)}%`;
  if (kind === "integer") return fmtNum(Math.round(num));
  return num.toLocaleString("zh-CN", { maximumFractionDigits: 3 });
}

function renderHistory(overview) {
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
        <h3>从 5 月 19 号到最新一天的均值</h3>
        <div class="history-card-grid compact">
          ${(payload.running_average_cards || []).map(renderCard).join("")}
        </div>
      </section>

      <section class="history-section">
        <h3>最近日报时间线</h3>
        <div class="table-wrap">
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

function renderAccountGroups(groups) {
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

function renderOptions(options) {
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

function roundsQuery() {
  const params = new URLSearchParams();
  params.set("limit", String(state.pageSize));
  params.set("offset", String((state.page - 1) * state.pageSize));
  Object.entries(state.filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return params.toString();
}

function renderRounds(payload) {
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

async function openRoundDetail(archiveKey) {
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

function closeDrawer() {
  qs("detail-drawer").classList.remove("open");
  qs("detail-drawer").setAttribute("aria-hidden", "true");
}

async function loadRounds() {
  const payload = await fetchJson(`./api/test-pool/rounds?${roundsQuery()}`);
  renderRounds(payload);
  state.roundsLoaded = true;
}

async function refreshAll({ forceRounds = false } = {}) {
  if (state.refreshing) return;
  state.refreshing = true;
  qs("status-text").textContent = "刷新中";
  try {
    const requests = [
      fetchJson("./api/test-pool/overview?days=30"),
      fetchJson("./api/test-pool/failures?limit=80"),
    ];
    if (!state.optionsLoaded) {
      requests.push(fetchJson("./api/test-pool/options"));
    }
    const responses = await Promise.all(requests);
    const [overview, failures, options] = responses;

    renderOverall(overview);
    renderToday(overview);
    renderLineCards(overview, failures);
    renderTopPlay(overview);
    renderHistory(overview);
    renderAccountGroups(overview.account_groups || []);

    if (options) {
      renderOptions(options);
      state.optionsLoaded = true;
    }

    const roundsPanel = qs("rounds-panel");
    if (forceRounds || roundsPanel.open || state.roundsLoaded) {
      await loadRounds();
    }

    qs("status-text").textContent = "已连接";
    qs("db-path").textContent = overview.db_path || "-";
    qs("last-updated").textContent = fmtDateTime(overview.last_exported_at);
  } catch (error) {
    showError(error);
  } finally {
    state.refreshing = false;
  }
}

function bindEvents() {
  qs("refresh-btn").addEventListener("click", () => {
    refreshAll({ forceRounds: qs("rounds-panel").open }).catch((error) => console.error(error));
  });

  qs("search-btn").addEventListener("click", () => {
    state.page = 1;
    state.filters.day = qs("day-filter").value;
    state.filters.runtime_mode = qs("mode-filter").value;
    state.filters.line_name = qs("line-filter").value;
    state.filters.status = qs("status-filter").value;
    state.filters.search = qs("search-input").value.trim();
    loadRounds().catch(showError);
  });

  qs("page-size-select").addEventListener("change", (event) => {
    state.pageSize = Number(event.target.value || 50);
    state.page = 1;
    loadRounds().catch(showError);
  });

  qs("prev-page-btn").addEventListener("click", () => {
    if (state.page <= 1) return;
    state.page -= 1;
    loadRounds().catch(showError);
  });

  qs("next-page-btn").addEventListener("click", () => {
    state.page += 1;
    loadRounds().catch(showError);
  });

  qs("rounds-panel").addEventListener("toggle", (event) => {
    if (event.currentTarget.open && !state.roundsLoaded) {
      loadRounds().catch(showError);
    }
  });

  qs("drawer-close").addEventListener("click", closeDrawer);
  qs("drawer-mask").addEventListener("click", closeDrawer);
}

function showError(error) {
  console.error(error);
  qs("status-text").textContent = "加载失败";
}

bindEvents();
refreshAll().catch((error) => console.error(error));
window.setInterval(() => {
  refreshAll().catch((error) => console.error(error));
}, state.autoRefreshMs);
