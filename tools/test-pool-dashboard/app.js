const state = {
  autoRefreshMs: 30000,
  refreshing: false,
  realtimeRefreshing: false,
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
  realtime_day: "选素材：白天实时榜外部素材优先，先补当天榜单命中。\n如何剪辑：优先走外部素材快切，压缩成能快速发出的短视频。\n如何发布：白天手动窗口 12:00-18:00 内补量，重点看回收速度。",
  creative_list_day: "选素材：从创意列表外部素材里挑能映射到真实任务的素材，优先承接白天补量。\n如何剪辑：先取外部素材，再按映射任务做快切和时长归一。\n如何发布：白天 12:00-18:00 手动窗口发，先看命中和回收。",
  yourchannel: "选素材：只用白名单剧名，不混入其他实验素材。\n如何剪辑：直接按白名单剧目文案，走固定剧场发布节奏。\n如何发布：优先发 YourChannel 剧场，重点看剧目命中和账号达标率。",
  realtime: "选素材：优先吃夜间实时榜外部素材，先看榜单里能直接跑的热剧。\n如何剪辑：外部素材优先快切，强调首屏节奏和快速出片。\n如何发布：夜间 18:00-次日12:00 连续补量，重点看播放回收和链接点击。",
  realtime_single: "选素材：夜间实时榜里挑可连续消耗的素材，固定绑定到单账号。\n如何剪辑：同一素材反复试不同切法，方便观察单账号反馈。\n如何发布：按单账号连续发，适合看定向试跑和极值表现。",
  creative_list: "选素材：创意列表外部素材先映射到真实任务，再筛能直接转发的版本。\n如何剪辑：优先走外部素材快切，保留创意素材的强钩子片段。\n如何发布：夜间稳定补量，重点看映射成功率和播放回收。",
  ordinary: "选素材：官方短剧素材优先，承接夜间稳定补量和底盘出量。\n如何剪辑：按官方短剧正常剪辑逻辑发，重点保证稳定产出。\n如何发布：夜间持续补量，优先补足账号目标，不追求极端热度。",
  fbhot_test: "选素材：偏热测素材，专门看 FB 热度优先策略是否值得放大。\n如何剪辑：强调首屏冲突和热点片段，方便测试热度反馈。\n如何发布：以实验为主，不直接代表主线，看点击、播放和收益反馈。",
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
      [...bucket.values()].sort((a, b) => String(b.timeText).localeCompare(String(a.timeText)))
    );
  });
  return normalizedMap;
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
    const strategyText = String(LINE_STRATEGIES[row.line_name] || row.pool_key || "-");
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
            <div class="line-block-text">${esc(strategyText)}</div>
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
        ${item.clip_method ? `<span class="line-chip">${esc(item.clip_method)}</span>` : ""}
      </div>
      <div class="top-play-copy-title">正文</div>
      <div class="top-play-copy">${esc(item.copy_text || item.description || "-")}</div>
    </article>
  `).join("");
}

function renderDailyTopHistory(overview) {
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
        <div class="history-sample-label">${esc(card.label || "-")}</div>
        <div class="history-sample-value">${esc(fmtTrendValue(card.value, card.kind))}</div>
        ${note}
        ${metaRows}
      </article>
    `;
  }).join("");

  const rows = payload.rows || [];
  node.innerHTML = `
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
    const runningAverageTitle = payload.latest_day
      ? `从 2026-06-09 到 ${payload.latest_day} 的均值`
      : "从 2026-06-09 到前一天的均值";

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
        <h3>最近日报时间线</h3>
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
  if (state.refreshing || state.realtimeRefreshing) return;
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
    renderDailyTopHistory(overview);
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

async function refreshRealtimePanels() {
  if (state.refreshing || state.realtimeRefreshing) return;
  state.realtimeRefreshing = true;
  qs("status-text").textContent = "刷新中";
  try {
    const [overview, failures] = await Promise.all([
      fetchJson("./api/test-pool/realtime-overview?days=30"),
      fetchJson("./api/test-pool/failures?limit=80"),
    ]);

    renderToday(overview);
    renderLineCards(overview, failures);
    renderTopPlay(overview);

    qs("status-text").textContent = "已连接";
    qs("db-path").textContent = overview.db_path || qs("db-path").textContent || "-";
    qs("last-updated").textContent = fmtDateTime(overview.last_exported_at);
  } catch (error) {
    showError(error);
  } finally {
    state.realtimeRefreshing = false;
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
  refreshRealtimePanels().catch((error) => console.error(error));
}, state.autoRefreshMs);
