import { LINE_LABELS } from "./state.js";

const LINE_NAME_REWRITES = [
  ["白天创意列表外部素材映射线", "创意列表匹官剧ff池-白天"],
  ["夜间实时榜定账号线", "实时榜单素材单账号池-夜间"],
  ["创意列表外部素材映射线", "创意列表匹官剧ff池-夜间"],
  ["白天实时榜线", "实时榜素材ff池-白天"],
  ["YourChannel 剧场线", "YourChannel 剧场线账号池-白天"],
  ["FB 热度加权线", "FB热度优先策略池-夜间"],
  ["近月出单剧线", "近月出单剧池-夜间"],
  ["夜间 StardustTV 剧场线", "山海剧场线账号池-夜间"],
  ["StardustTV 剧场线", "山海剧场线账号池-夜间"],
  ["普通池线", "ai-cut官剧池-夜间"],
  ["实时榜线", "实时榜素材ff池-夜间"],
];

export function qs(id) {
  return document.getElementById(id);
}

export function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function fmtNum(value) {
  const num = Number(value || 0);
  return Number.isFinite(num) ? num.toLocaleString("zh-CN") : "-";
}

export function fmtMoney(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "¥0";
  return `¥${num.toLocaleString("zh-CN", {
    minimumFractionDigits: num % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  })}`;
}

export function metricDisplay(value, { money = false, missing = false } = {}) {
  if (missing) return "待接入";
  return money ? fmtMoney(value) : fmtNum(value);
}

export function fmtPct(value) {
  const num = Number(value || 0);
  return `${num.toFixed(2)}%`;
}

export function fmtDateTime(value) {
  const text = String(value || "").trim();
  if (!text) return "-";
  return text.replace("T", " ");
}

export function modeLabel(value) {
  const map = {
    continuous: "常驻",
    continuous_dual_line: "常驻双线",
    nightly_rounds: "夜间轮次",
    daily: "夜间轮次",
    novel: "小说流程",
  };
  return map[String(value || "").trim()] || value || "-";
}

export function lineLabel(value) {
  return LINE_LABELS[String(value || "").trim()] || value || "-";
}

export function rewriteLineNames(value) {
  let text = String(value ?? "");
  if (!text) return text;
  for (const [source, target] of LINE_NAME_REWRITES) {
    text = text.split(source).join(target);
  }
  return text;
}

export function statusLabel(value) {
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

export function statusTone(value) {
  const key = String(value || "").trim();
  if (["processing", "处理中", "运行中"].includes(key)) return "running";
  if (key.startsWith("published") || ["done", "已完成"].includes(key)) return "done";
  if (["failed", "blocked", "error", "失败", "阻塞", "异常"].includes(key)) return "error";
  return "idle";
}

export function isDayLine(lineName) {
  return ["realtime_day", "creative_list_day", "yourchannel"].includes(String(lineName || "").trim());
}

export function rangeLabel(lineName) {
  return isDayLine(lineName) ? "10:00-18:00" : "18:00-次日12:00";
}

export function metricCard(item) {
  return `
    <article class="metric-card ${esc(item.tone || "plain")}">
      <div class="metric-label">${esc(item.label)}</div>
      <div class="metric-value">${esc(item.value)}</div>
      <div class="metric-note">${esc(item.note || "-")}</div>
    </article>
  `;
}

export function normalizeIssue(reason, title = "") {
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

export function isMeaningfulIssue(reason) {
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

export function scoreGrade(score) {
  if (score >= 85) return "A";
  if (score >= 65) return "B";
  if (score >= 45) return "C";
  return "D";
}

export function computeLineScore(row) {
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

export async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

export function fmtTrendValue(value, kind = "number") {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "-";
  if (kind === "money") return fmtMoney(num);
  if (kind === "percent") return `${num.toFixed(2)}%`;
  if (kind === "integer") return fmtNum(Math.round(num));
  return num.toLocaleString("zh-CN", { maximumFractionDigits: 3 });
}
