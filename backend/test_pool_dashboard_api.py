from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from inbeidou_cli import get_my_task_list, get_publish_analysis, get_publish_records, require_success
except ModuleNotFoundError:  # pragma: no cover - package import fallback
    from .inbeidou_cli import get_my_task_list, get_publish_analysis, get_publish_records, require_success

ROOT_DIR = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT_DIR / "runtime"
CONTINUOUS_ROOT = RUNTIME_ROOT / "continuous-loop"
REPORT_CONTINUOUS_ROOT = RUNTIME_ROOT / "reports" / "continuous-test-summary"
ACCOUNT_POOLS_PATH = ROOT_DIR / "conf" / "account_pools.json"
ANALYSIS_REPORT_DIR = Path("/Users/xinyuliu/Downloads/AI Loop/分析日报")
DAILY_TOP_HISTORY_CACHE_PATH = RUNTIME_ROOT / "dashboard-cache" / "daily_top_history.json"
SUMMARY_METRICS_CACHE_PATH = RUNTIME_ROOT / "dashboard-cache" / "summary_metrics.json"
TREND_ANALYZER_CACHE_PATH = RUNTIME_ROOT / "dashboard-cache" / "trend_analyzer.json"
LINE_CUMULATIVE_CACHE_PATH = RUNTIME_ROOT / "dashboard-cache" / "line_cumulative_totals.json"
TODAY_TOP_PLAY_CACHE_PATH = RUNTIME_ROOT / "dashboard-cache" / "today_top_play.json"
TREND_BASELINE_START = "2026-05-19"
TREND_BASELINE_END = "2026-06-08"
TREND_RUNNING_START = "2026-06-09"
DAILY_TOP_HISTORY_START = "2026-05-19"
AI_LOOP_REPORTING_SSH_HOST = os.getenv("AI_LOOP_REPORTING_SSH_HOST", "124.174.76.6").strip()
AI_LOOP_REPORTING_SSH_USER = os.getenv("AI_LOOP_REPORTING_SSH_USER", "root").strip()
AI_LOOP_REPORTING_SSH_PASSWORD = os.getenv("AI_LOOP_REPORTING_SSH_PASSWORD", "").strip()
AI_LOOP_REPORTING_P0_SUMMARY_PATH = os.getenv(
    "AI_LOOP_REPORTING_P0_SUMMARY_PATH",
    "/opt/ai-loop-dashboard/runtime/p0-summary.json",
).strip()
FIXED_BASELINE_CARD_VALUES = {
    "全体每日播放平均": 133755.048,
    "全体每日互动平均": 2886.143,
    "全体每日发布平均": 3789.619,
    "全体每日成功平均": 3057.524,
    "全体每日点击平均": 2832.667,
    "全体每日成功率均值": 76.83,
}

LINE_LABELS = {
    "ordinary": "ai-cut官剧池-夜间",
    "realtime": "实时榜素材ff池-夜间",
    "fbhot_test": "FB热度优先策略池-夜间",
    "realtime_day": "实时榜素材ff池-白天",
    "creative_list": "创意列表匹官剧ff池-夜间",
    "creative_list_day": "创意列表匹官剧ff池-白天",
    "realtime_single": "实时榜单素材单账号池-夜间",
    "yourchannel": "YourChannel 剧场线账号池-白天",
    "recent_order": "近月出单剧池-夜间",
    "stardusttv": "山海剧场线账号池-夜间",
    "tag_test": "打标账号剧测试池-夜间",
}

LINE_POOL_KEYS = {
    "realtime": "facebook_drama_realtime_pool",
    "realtime_day": "facebook_drama_realtime_day_pool",
    "realtime_single": "facebook_drama_realtime_single_pool",
    "creative_list": "facebook_drama_creative_list_pool",
    "creative_list_day": "facebook_drama_creative_list_day_pool",
    "ordinary": "facebook_drama_ordinary_pool",
    "fbhot_test": "facebook_drama_fbhot_test_pool",
    "yourchannel": "facebook_drama_yourchannel_pool",
    "recent_order": "facebook_drama_recent_order_pool",
    "stardusttv": "facebook_drama_stardusttv_pool",
    "tag_test": "facebook_drama_tag_test_pool",
}

ACCOUNT_GROUP_META = {
    "facebook_drama_realtime_pool": {
        "label": "实时榜素材ff池-夜间",
        "description": "实时榜素材ff夜间专用池，当前固定 30 个账号，承接实时榜外部素材发布。",
    },
    "facebook_drama_realtime_day_pool": {
        "label": "实时榜素材ff池-白天",
        "description": "实时榜素材ff白天专用池，按 10:00-18:00 手动窗口运行。",
    },
    "facebook_drama_realtime_single_pool": {
        "label": "实时榜单素材单账号池-夜间",
        "description": "实时榜单素材单账号夜间专用池，单素材绑定单账号连续消耗。",
    },
    "facebook_drama_creative_list_pool": {
        "label": "创意列表匹官剧ff池-夜间",
        "description": "创意列表匹官剧ff夜间专用池。",
    },
    "facebook_drama_creative_list_day_pool": {
        "label": "创意列表匹官剧ff池-白天",
        "description": "创意列表匹官剧ff白天专用池，按 10:00-18:00 手动窗口运行。",
    },
    "facebook_drama_ordinary_pool": {
        "label": "ai-cut官剧池-夜间",
        "description": "ai-cut官剧夜间专用池，主要承接官方短剧稳定补量。",
    },
    "facebook_drama_fbhot_test_pool": {
        "label": "FB热度优先策略池-夜间",
        "description": "FB 热测线实验池，用来测试热度优先策略。",
    },
    "facebook_drama_yourchannel_pool": {
        "label": "YourChannel 剧场线账号池-白天",
        "description": "YourChannel 剧场线白天专用池，使用白名单剧名和剧场发布策略。",
    },
    "facebook_drama_recent_order_pool": {
        "label": "近月出单剧池-夜间",
        "description": "近月出单剧夜间专用池，按表格轮转剧名并使用官方视频 FFmpeg 30 秒快切。",
    },
    "facebook_drama_stardusttv_pool": {
        "label": "山海剧场线账号池-夜间",
        "description": "山海剧场夜间专用池，从备用池拆出的 15 个账号按剧名表轮转，使用官方视频 FFmpeg 15-30 秒快切。",
    },
    "facebook_drama_tag_test_pool": {
        "label": "打标账号剧测试池-夜间",
        "description": "打标测试专用池，按剧表地区匹配同地区账号，使用 StardustTV 官方视频 FFmpeg 15-30 秒快切。",
    },
    "facebook_drama_reel_block_pool": {
        "label": "Reel 限制账号池",
        "description": "连续 5 次出现“不能发布 Reel 视频”后自动迁入，具体来源线路记录在 reel_publish_block_state 中。",
    },
    "facebook_novel_dedicated_10": {
        "label": "小说账号池",
        "description": "小说发布专用池，固定 10 个账号，不计入短剧线路。",
    },
    "facebook_drama_reserve_pool": {
        "label": "短剧备用池",
        "description": "备用池，保留还没分配到执行线的剩余账号。",
    },
    "facebook_drama_exception_pool": {
        "label": "异常账号池",
        "description": "短剧异常账号暂存池，需要人工复核后再决定是否恢复。",
    },
}

LINE_DISPLAY_NAMES = {
    "ordinary": "ai-cut官剧池-夜间",
    "realtime": "实时榜素材ff池-夜间",
    "realtime_day": "实时榜素材ff池-白天",
    "realtime_single": "实时榜单素材单账号池-夜间",
    "creative_list": "创意列表匹官剧ff池-夜间",
    "creative_list_day": "创意列表匹官剧ff池-白天",
    "fbhot_test": "FB热度优先策略池-夜间",
    "yourchannel": "YourChannel 剧场线账号池-白天",
    "recent_order": "近月出单剧池-夜间",
    "stardusttv": "山海剧场线账号池-夜间",
    "tag_test": "打标账号剧测试池-夜间",
}

FINAL_SUCCESS_PREFIXES = ("published",)
PROCESSING_TOKENS = (
    "processing",
    "pending",
    "submitting",
    "uploading",
    "uploaded",
    "clipping",
)
HEARTBEAT_RE = re.compile(r"^\[heartbeat\]\s+(?P<stage>.+)$")


@dataclass
class RoundArchive:
    archive_key: str
    day_key: str
    runtime_mode: str
    line_name: str
    round_name: str
    label: str
    platform: str
    pool_name: str
    requested_count: int
    planned_count: int
    success_count: int
    failed_count: int
    processing_count: int
    unsubmitted_count: int
    status: str
    status_label: str
    note: str
    exported_at: str
    export_dir: str
    report_markdown_path: str
    round_json_path: str
    summary_path: str
    log_snapshot_path: str
    account_pool_snapshot_path: str
    config_snapshot_path: str
    flywheel_config: str
    items: list[dict[str, Any]]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(str(value).strip() or default)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(str(value).strip() or default)
    except Exception:
        return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _line_display_name(line_name: Any, fallback: Any = "") -> str:
    key = _text(line_name)
    return LINE_DISPLAY_NAMES.get(key) or LINE_LABELS.get(key) or _text(fallback)


def _clean_publish_copy_text(text: Any) -> str:
    raw = _text(text)
    if not raw:
        return ""
    filtered: list[str] = []
    for line in [part.strip() for part in raw.splitlines() if part.strip()]:
        lowered = line.lower()
        if "http" in lowered and ("watch" in lowered or "👉" in line or "查看" in line or "觀看" in line or "ver" in lowered):
            continue
        if any(
            token in lowered
            for token in (
                "continue the story",
                "find the full series",
                "look up",
                "continúa la historia",
                "encuentra la serie completa",
                "busca la",
                "continuez l'histoire",
                "découvrez la série complète",
                "recherchez le",
            )
        ):
            continue
        if line.startswith("#"):
            continue
        filtered.append(line)
    return "\n".join(filtered[:6]) or raw


def _looks_like_stub_title(title: str) -> bool:
    normalized = _text(title)
    if not normalized:
        return True
    lowered = normalized.lower()
    if "http" in lowered:
        return True
    if "👉" in normalized and len(normalized) <= 16:
        return True
    return False


def _build_top_play_title(*, raw_title: Any, copy_text: str) -> str:
    title = _text(raw_title)
    if title and not _looks_like_stub_title(title):
        return title
    first_line = next((line.strip() for line in copy_text.splitlines() if line.strip()), "")
    if not first_line:
        return title or "未识别剧目"
    return first_line[:36] + ("..." if len(first_line) > 36 else "")


def _valid_publish_title(value: Any) -> str:
    title = _text(value)
    if not title or _looks_like_stub_title(title):
        return ""
    return title


def _line_clip_method(line_name: str) -> str:
    normalized = _text(line_name)
    if normalized in {"realtime", "realtime_day", "realtime_single", "creative_list", "creative_list_day", "fbhot_test"}:
        return "外部素材快切"
    if normalized == "ordinary":
        return "官方短剧补量"
    if normalized == "yourchannel":
        return "剧场白名单发布"
    if normalized == "recent_order":
        return "近月出单剧快切"
    if normalized == "stardusttv":
        return "StardustTV 官方快切"
    if normalized == "tag_test":
        return "打标地区匹配快切"
    return ""


def _parse_metric_number(value: Any) -> float | None:
    text = _text(value)
    if not text or text == "-":
        return None
    normalized = text.replace(",", "").replace("%", "").replace("¥", "").strip()
    try:
        return float(normalized)
    except Exception:
        return None


def _number_to_int(value: Any) -> int:
    parsed = _parse_metric_number(value)
    if parsed is None:
        return 0
    return int(round(parsed))


def _parse_markdown_table(text: str, heading: str) -> dict[str, str]:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return {}
    lines = text[start:].splitlines()[1:]
    rows: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if rows:
                break
            continue
        if stripped.startswith("## "):
            break
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if cells[0] in {"指标", "---"} or cells[1] == "---":
            continue
        rows[cells[0]] = cells[1]
    return rows


def _parse_markdown_bullets(text: str, heading: str) -> list[str]:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return []
    lines = text[start:].splitlines()[1:]
    bullets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if bullets:
                break
            continue
        if stripped.startswith("## "):
            break
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return bullets


def _json_load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _json_dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _today_key() -> str:
    return date.today().isoformat()


def _yesterday_key() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def _status_label(status: str) -> str:
    if status.startswith("published"):
        return "已提交"
    if status == "done":
        return "已完成"
    if status == "failed":
        return "失败"
    if status == "processing":
        return "处理中"
    if status == "blocked":
        return "阻塞"
    if status == "error":
        return "异常"
    return status or "-"


def _round_sort_key(path: Path) -> tuple[int, str]:
    stem = path.stem
    digits = "".join(ch for ch in stem if ch.isdigit())
    return (_safe_int(digits, 0), stem)


def _format_mtime(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def _empty_unsubmitted_breakdown() -> dict[str, Any]:
    return {
        "total": 0,
        "missing_result_count": 0,
        "material_shortage_count": 0,
        "pending_publish_count": 0,
        "plan_gap_count": 0,
        "other_count": 0,
        "primary_reason_key": "",
        "primary_reason_label": "",
        "summary": "-",
    }


def _finalize_unsubmitted_breakdown(breakdown: dict[str, Any]) -> dict[str, Any]:
    counts = [
        ("missing_result_count", "整轮未产出结果", _safe_int(breakdown.get("missing_result_count"))),
        ("material_shortage_count", "素材/可用源不足", _safe_int(breakdown.get("material_shortage_count"))),
        ("pending_publish_count", "已生成但未拿到发布结果", _safe_int(breakdown.get("pending_publish_count"))),
        ("plan_gap_count", "计划槽位未生成任务", _safe_int(breakdown.get("plan_gap_count"))),
        ("other_count", "其他未提交", _safe_int(breakdown.get("other_count"))),
    ]
    nonzero = [(key, label, count) for key, label, count in counts if count > 0]
    if not nonzero:
        breakdown["summary"] = "-"
        breakdown["primary_reason_key"] = ""
        breakdown["primary_reason_label"] = ""
        return breakdown
    primary_key, primary_label, _ = max(nonzero, key=lambda row: row[2])
    breakdown["primary_reason_key"] = primary_key
    breakdown["primary_reason_label"] = primary_label
    breakdown["summary"] = " / ".join(f"{label} {count}" for _, label, count in nonzero)
    return breakdown


def _merge_unsubmitted_breakdown(target: dict[str, Any], part: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "total",
        "missing_result_count",
        "material_shortage_count",
        "pending_publish_count",
        "plan_gap_count",
        "other_count",
    ):
        target[key] = _safe_int(target.get(key)) + _safe_int(part.get(key))
    return _finalize_unsubmitted_breakdown(target)


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    drama = item.get("drama") if isinstance(item.get("drama"), dict) else {}
    account = item.get("account") if isinstance(item.get("account"), dict) else {}
    clip_options = item.get("clip_options") if isinstance(item.get("clip_options"), dict) else {}
    publish = item.get("publish") if isinstance(item.get("publish"), dict) else {}
    promotion = item.get("promotion") if isinstance(item.get("promotion"), dict) else {}
    error_text = _text(item.get("error") or publish.get("error") or item.get("failure_reason"))
    publish_status = _text(publish.get("status") or item.get("status"))
    title = _text(drama.get("title") or item.get("title"))
    return {
        "item_index": _safe_int(item.get("index")),
        "account_name": _text(account.get("name") or item.get("account_name")),
        "account_id": _text(account.get("account_id") or item.get("account_id")),
        "title": title,
        "app_id": _text(drama.get("app_id") or item.get("app_id")),
        "source_mode": _text(drama.get("source_mode") or item.get("source_mode") or drama.get("candidate_fetch_source")),
        "candidate_fetch_source": _text(drama.get("candidate_fetch_source") or item.get("candidate_fetch_source")),
        "clip_method": _text(clip_options.get("cut_type") or clip_options.get("provider") or item.get("clip_method")),
        "publish_status": publish_status,
        "failure_reason": error_text,
        "promotion_link": _text(promotion.get("promotion_link")),
    }


def _classify_item(flat_item: dict[str, Any]) -> str:
    status = _text(flat_item.get("publish_status")).lower()
    error = _text(flat_item.get("failure_reason"))
    if any(status.startswith(prefix) for prefix in FINAL_SUCCESS_PREFIXES):
        return "success"
    if status == "failed" or error:
        return "failed"
    if any(token in status for token in PROCESSING_TOKENS):
        return "processing"
    if status:
        return "processing"
    return "unsubmitted"


def _classify_unsubmitted_breakdown(archive: RoundArchive) -> dict[str, Any]:
    breakdown = _empty_unsubmitted_breakdown()
    total = archive.unsubmitted_count
    breakdown["total"] = total
    if total <= 0:
        return breakdown
    note_blob = f"{archive.note} {archive.status_label}".lower()
    if archive.success_count == 0 and archive.failed_count == 0 and archive.processing_count == 0:
        breakdown["missing_result_count"] = total
        return _finalize_unsubmitted_breakdown(breakdown)
    if any(token in note_blob for token in ["素材", "playable", "可下载", "资源不足"]):
        breakdown["material_shortage_count"] = total
        return _finalize_unsubmitted_breakdown(breakdown)
    if archive.processing_count > 0:
        breakdown["pending_publish_count"] = min(total, archive.processing_count)
    remaining = total - breakdown["pending_publish_count"]
    planned_gap = max(archive.planned_count - len(archive.items), 0)
    if remaining > 0 and planned_gap > 0:
        breakdown["plan_gap_count"] = min(remaining, planned_gap)
        remaining -= breakdown["plan_gap_count"]
    if remaining > 0:
        breakdown["other_count"] = remaining
    return _finalize_unsubmitted_breakdown(breakdown)


def _normalize_round_issue_text(reason: Any) -> str:
    text = _text(reason)
    if not text:
        return ""
    if "下载状态=success，剪辑状态=failed，错误=" in text:
        return "剪辑失败"
    if "查询剪辑任务失败" in text:
        return "剪辑任务查询失败"
    if "任务队列已满" in text:
        return "剪辑队列已满"
    if "下载状态=failed" in text or "尚未进入剪辑" in text:
        return "素材下载后未进入剪辑"
    if "HTTPSConnectionPool" in text or "Max retries exceeded" in text:
        return "上游接口超时"
    if "moov atom not found" in text or "Invalid data found" in text:
        return "素材文件损坏"
    if "探测视频信息失败" in text or "ffprobe 获取视频信息失败" in text:
        return "视频信息探测失败"
    if "查询开放API访问密钥失败" in text:
        return "ai-cut 密钥读取失败"
    if "查询任务失败" in text:
        return "ai-cut 任务查询失败"
    if "HTTP 500" in text:
        return "ai-cut 接口报错"
    if "未找到视频流" in text:
        return "视频流识别失败"
    if "文件不存在" in text:
        return "素材文件缺失"
    if "时长超限" in text:
        return "视频时长超限"
    if "分辨率错误" in text:
        return "分辨率不符合要求"
    if "post id is empty" in text:
        return "发布记录缺少 post id"
    return re.sub(r"\s+", " ", text).strip()[:80]


def _build_round_judgement(archive: RoundArchive) -> dict[str, str]:
    issue_counter: Counter[str] = Counter()
    for item in archive.items:
        normalized = _normalize_round_issue_text(item.get("failure_reason"))
        if normalized:
            issue_counter[normalized] += 1

    breakdown = _classify_unsubmitted_breakdown(archive)
    primary_issue = ""
    if issue_counter:
        issue_text, issue_count = issue_counter.most_common(1)[0]
        primary_issue = f"{issue_text}（{issue_count}条）"
    elif archive.unsubmitted_count > 0:
        primary_issue = breakdown.get("primary_reason_label") or "有未提交结果"
    elif archive.processing_count > 0:
        primary_issue = "还有结果未收敛"
    else:
        primary_issue = "本轮无明显异常"

    total_problem = archive.failed_count + archive.unsubmitted_count
    severe = (
        archive.status in {"failed", "blocked", "error"}
        or total_problem >= max(3, int(round(max(archive.requested_count, 1) * 0.3)))
    )
    if severe:
        return {
            "judgement_label": "明显异常",
            "judgement_tone": "error",
            "primary_issue": primary_issue,
        }
    if archive.failed_count > 0 or archive.unsubmitted_count > 0 or archive.processing_count > 0:
        return {
            "judgement_label": "轻微异常",
            "judgement_tone": "warn",
            "primary_issue": primary_issue,
        }
    return {
        "judgement_label": "正常",
        "judgement_tone": "done",
        "primary_issue": primary_issue,
    }


def _report_path(runtime_mode: str, day_key: str, line_name: str, round_name: str) -> Path | None:
    if runtime_mode != "continuous":
        return None
    base = REPORT_CONTINUOUS_ROOT / day_key / line_name / round_name
    if not base.exists():
        return None
    candidates = sorted(base.glob("*.md"))
    return candidates[0] if candidates else None


def _tail_lines(path: Path, limit: int = 300) -> list[str]:
    if not path.exists():
        return []
    queue: deque[str] = deque(maxlen=limit)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            queue.append(line.rstrip("\n"))
    return list(queue)


def _line_round_start_re(line_name: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\[(?P<ts>[^\]]+)\]\s+(?P<label>{re.escape(line_name)}-round(?P<round>\d+))\s+开始：(?P<details>.*)$"
    )


def _line_round_done_re(line_name: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\[(?P<ts>[^\]]+)\]\s+(?P<label>{re.escape(line_name)}-round(?P<round>\d+))\s+完成：成功\s+(?P<success>\d+)，失败\s+(?P<failed>\d+)，处理中\s+(?P<processing>\d+)，未提交\s+(?P<unsubmitted>\d+)。$"
    )


def _line_worker_exit_re(line_name: str) -> re.Pattern[str]:
    return re.compile(rf"^\[(?P<ts>[^\]]+)\]\s+line={re.escape(line_name)}\s+exited code=(?P<code>-?\d+);")


def _line_account_empty_re(line_name: str) -> re.Pattern[str]:
    return re.compile(rf"^\[(?P<ts>[^\]]+)\]\s+{re.escape(line_name)}\s+选账号失败：账号池\s+(?P<pool>\S+)\s+没有可用账号；")


def _line_target_stop_re(line_name: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\[(?P<ts>[^\]]+)\]\s+{re.escape(line_name)}\s+已达成账号目标并停止：账号池=(?P<pool>\S+)，账号日目标=(?P<target>\d+)，可用账号已全部达标。"
    )


def _line_waiting_realtime_re(line_name: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\[(?P<ts>[^\]]+)\]\s+{re.escape(line_name)}\s+等待上游\s+realtime：账号池=(?P<pool>\S+)，未达标账号=(?P<accounts>\d+)，剩余缺口=(?P<gap>\d+)；300s 后重试。"
    )


def _parse_live_line_runtime(line_name: str, *, day_key: str) -> dict[str, Any]:
    forever_log = CONTINUOUS_ROOT / f"forever_{line_name}.log"
    worker_log = CONTINUOUS_ROOT / day_key / line_name / "worker.log"
    forever_lines = _tail_lines(forever_log)
    worker_lines = _tail_lines(worker_log)

    start_re = _line_round_start_re(line_name)
    done_re = _line_round_done_re(line_name)
    exit_re = _line_worker_exit_re(line_name)
    empty_re = _line_account_empty_re(line_name)
    target_stop_re = _line_target_stop_re(line_name)
    waiting_realtime_re = _line_waiting_realtime_re(line_name)

    latest_start: tuple[str, str] | None = None
    latest_done: tuple[str, str] | None = None
    latest_exit: tuple[str, str] | None = None
    latest_empty: tuple[str, str] | None = None
    latest_target_stop: tuple[str, str] | None = None
    latest_waiting: tuple[str, str] | None = None

    for raw_line in forever_lines:
        match = start_re.match(raw_line)
        if match:
            latest_start = (match.group("ts"), match.group("label"))
            continue
        match = done_re.match(raw_line)
        if match:
            latest_done = (match.group("ts"), match.group("label"))
            continue
        match = exit_re.match(raw_line)
        if match:
            latest_exit = (match.group("ts"), match.group("code"))
            continue
        match = empty_re.match(raw_line)
        if match:
            latest_empty = (match.group("ts"), match.group("pool"))
            continue
        match = target_stop_re.match(raw_line)
        if match:
            latest_target_stop = (match.group("ts"), match.group("pool"))
            continue
        match = waiting_realtime_re.match(raw_line)
        if match:
            latest_waiting = (match.group("ts"), match.group("gap"))
            continue

    latest_heartbeat_stage = ""
    latest_heartbeat_at = ""
    latest_heartbeat_age_seconds: float | None = None
    if worker_log.exists():
        for raw_line in reversed(worker_lines):
            match = HEARTBEAT_RE.match(raw_line)
            if match:
                latest_heartbeat_stage = match.group("stage")
                worker_mtime = datetime.fromtimestamp(worker_log.stat().st_mtime)
                latest_heartbeat_at = worker_mtime.strftime("%Y-%m-%d %H:%M:%S")
                latest_heartbeat_age_seconds = max(
                    0.0,
                    (datetime.now() - worker_mtime).total_seconds(),
                )
                break

    is_active_round = False
    active_round_name = ""
    active_since = ""
    if latest_start:
        active_since, active_round_name = latest_start
        is_active_round = True
        if day_key and not active_since.startswith(day_key):
            is_active_round = False
        if latest_done and latest_done[1] == active_round_name and latest_done[0] >= active_since:
            is_active_round = False
        if latest_exit and latest_exit[0] >= active_since:
            is_active_round = False
        if latest_target_stop and latest_target_stop[0] >= active_since:
            is_active_round = False

    if is_active_round:
        if latest_heartbeat_age_seconds is not None and latest_heartbeat_age_seconds > 180:
            return {
                "is_running": False,
                "runtime_state": "阻塞",
                "last_update": latest_heartbeat_at or active_since,
                "latest_round": active_round_name,
                "live_stage": f"{latest_heartbeat_stage or '执行中'}；超过 3 分钟没有新心跳",
            }
        return {
            "is_running": True,
            "runtime_state": "运行中",
            "last_update": latest_heartbeat_at or active_since,
            "latest_round": active_round_name,
            "live_stage": latest_heartbeat_stage or "执行中",
        }

    if latest_target_stop:
        return {
            "is_running": False,
            "runtime_state": "已完成",
            "last_update": latest_target_stop[0],
            "latest_round": active_round_name,
            "live_stage": "",
        }

    if latest_waiting:
        return {
            "is_running": False,
            "runtime_state": "等待上游",
            "last_update": latest_waiting[0],
            "latest_round": active_round_name,
            "live_stage": "",
        }

    if latest_empty:
        return {
            "is_running": False,
            "runtime_state": "空闲",
            "last_update": latest_empty[0],
            "latest_round": active_round_name,
            "live_stage": "",
        }

    return {
        "is_running": False,
        "runtime_state": "",
        "last_update": "",
        "latest_round": active_round_name,
        "live_stage": latest_heartbeat_stage,
    }


class TestPoolDashboardService:
    def __init__(self) -> None:
        self.runtime_root = RUNTIME_ROOT
        self.db_path = CONTINUOUS_ROOT
        self._cache_expires_at = 0.0
        self._cache: list[RoundArchive] = []
        self._remote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._background_refreshing: set[str] = set()

    def _scan_round_archives(self) -> list[RoundArchive]:
        now_ts = datetime.now().timestamp()
        if now_ts < self._cache_expires_at and self._cache:
            return self._cache

        rounds: list[RoundArchive] = []
        for json_path in sorted(CONTINUOUS_ROOT.glob("*/*/round*.json")):
            day_key = json_path.parent.parent.name
            line_name = json_path.parent.name
            round_name = json_path.stem
            payload = _json_load(json_path)
            raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
            items = [_flatten_item(item) for item in raw_items if isinstance(item, dict)]
            success_count = failed_count = processing_count = unsubmitted_count = 0
            for item in items:
                bucket = _classify_item(item)
                if bucket == "success":
                    success_count += 1
                elif bucket == "failed":
                    failed_count += 1
                elif bucket == "processing":
                    processing_count += 1
                else:
                    unsubmitted_count += 1
            requested_count = _safe_int(payload.get("requested_count"), len(items))
            if requested_count < len(items):
                requested_count = len(items)
            unresolved = success_count + failed_count + processing_count + unsubmitted_count
            if unresolved < requested_count:
                unsubmitted_count += requested_count - unresolved
            top_status = _text(payload.get("status")).lower() or "done"
            note = _text(payload.get("user_summary_zh")) or _text(payload.get("retry_prompt_zh"))
            status = "done" if top_status == "done" else ("processing" if processing_count > 0 else top_status)
            status_label = _status_label(status)
            report_path = _report_path("continuous", day_key, line_name, round_name)
            summary_path = json_path.with_suffix(".summary")
            rounds.append(
                RoundArchive(
                    archive_key=f"continuous:{day_key}:{line_name}:{round_name}",
                    day_key=day_key,
                    runtime_mode="continuous",
                    line_name=line_name,
                    round_name=round_name,
                    label=round_name,
                    platform=_text(payload.get("platform") or "FACEBOOK"),
                    pool_name=line_name,
                    requested_count=requested_count,
                    planned_count=requested_count,
                    success_count=success_count,
                    failed_count=failed_count,
                    processing_count=processing_count,
                    unsubmitted_count=unsubmitted_count,
                    status=status,
                    status_label=status_label,
                    note=note,
                    exported_at=_format_mtime(json_path),
                    export_dir=str(json_path.parent),
                    report_markdown_path=str(report_path) if report_path else "",
                    round_json_path=str(json_path),
                    summary_path=str(summary_path) if summary_path.exists() else "",
                    log_snapshot_path=str(json_path.parent / "worker.log") if (json_path.parent / "worker.log").exists() else "",
                    account_pool_snapshot_path="",
                    config_snapshot_path="",
                    flywheel_config="",
                    items=items,
                )
            )

        rounds.sort(key=lambda row: (row.day_key, row.line_name, _round_sort_key(Path(row.round_name))[0]), reverse=True)
        self._cache = rounds
        self._cache_expires_at = now_ts + 10
        return rounds

    def _filtered_rounds(self, *, days: int | None = None) -> list[RoundArchive]:
        rounds = self._scan_round_archives()
        if not days:
            return rounds
        cutoff = date.today() - timedelta(days=max(1, days) - 1)
        return [row for row in rounds if datetime.strptime(row.day_key, "%Y-%m-%d").date() >= cutoff]

    def _aggregate_line_rows(self, rounds: list[RoundArchive]) -> list[dict[str, Any]]:
        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rounds:
            key = (row.runtime_mode, row.line_name)
            bucket = buckets.setdefault(
                key,
                {
                    "runtime_mode": row.runtime_mode,
                    "line_name": row.line_name,
                    "round_count": 0,
                    "requested_count": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "processing_count": 0,
                    "unsubmitted_count": 0,
                },
            )
            bucket["round_count"] += 1
            bucket["requested_count"] += row.requested_count
            bucket["success_count"] += row.success_count
            bucket["failed_count"] += row.failed_count
            bucket["processing_count"] += row.processing_count
            bucket["unsubmitted_count"] += row.unsubmitted_count
        return sorted(buckets.values(), key=lambda item: (-item["requested_count"], item["line_name"]))

    def _load_account_groups(self) -> list[dict[str, Any]]:
        payload = _json_load(ACCOUNT_POOLS_PATH)
        if not isinstance(payload, dict):
            return []
        rows: list[dict[str, Any]] = []
        for key, raw in payload.items():
            if not isinstance(raw, dict):
                continue
            meta = ACCOUNT_GROUP_META.get(key, {})
            account_ids = raw.get("account_ids") if isinstance(raw.get("account_ids"), list) else []
            rows.append(
                {
                    "key": key,
                    "label": meta.get("label") or key,
                    "description": meta.get("description") or _text(raw.get("description")) or "-",
                    "platform": _text(raw.get("platform")) or "FACEBOOK",
                    "count": len(account_ids),
                    "account_ids": [str(item) for item in account_ids],
                }
            )
        rows.sort(key=lambda item: item["label"])
        return rows

    def _select_today_rounds(self) -> tuple[str, list[RoundArchive]]:
        rounds = self._scan_round_archives()
        today_key = date.today().isoformat()
        today_rounds = [row for row in rounds if row.day_key == today_key]
        if today_rounds:
            return today_key, today_rounds
        latest_day = max((row.day_key for row in rounds), default="")
        return latest_day, [row for row in rounds if row.day_key == latest_day]

    def _get_cached_remote(self, key: str) -> dict[str, Any] | None:
        cached = self._remote_cache.get(key)
        if not cached:
            return None
        expires_at, payload = cached
        if time.time() >= expires_at:
            self._remote_cache.pop(key, None)
            return None
        return payload

    def _set_cached_remote(self, key: str, ttl_seconds: int, payload: dict[str, Any]) -> dict[str, Any]:
        self._remote_cache[key] = (time.time() + max(1, ttl_seconds), payload)
        return payload

    def _load_ai_loop_reporting_summary(self, *, refresh: bool = False) -> dict[str, Any]:
        cache_key = "ai-loop-reporting-p0-summary"
        if refresh:
            self._remote_cache.pop(cache_key, None)
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            return cached

        if not AI_LOOP_REPORTING_SSH_PASSWORD:
            return {
                "available": False,
                "note": "未配置 AI_LOOP_REPORTING_SSH_PASSWORD，暂时不能读取 ai-loop-reporting 汇总。",
            }
        if not shutil.which("sshpass"):
            return {
                "available": False,
                "note": "本机缺少 sshpass，暂时不能读取 ai-loop-reporting 汇总。",
            }

        remote = f"{AI_LOOP_REPORTING_SSH_USER}@{AI_LOOP_REPORTING_SSH_HOST}"
        command = [
            "sshpass",
            "-e",
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=8",
            remote,
            f"cat {AI_LOOP_REPORTING_P0_SUMMARY_PATH}",
        ]
        env = dict(os.environ)
        env["SSHPASS"] = AI_LOOP_REPORTING_SSH_PASSWORD
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=25,
                env=env,
            )
            payload = json.loads(completed.stdout or "{}")
        except Exception as exc:
            return {
                "available": False,
                "note": f"读取 ai-loop-reporting 汇总失败：{exc}",
            }
        return self._set_cached_remote(cache_key, 300, payload if isinstance(payload, dict) else {})

    def _build_trend_analyzer_from_ai_loop_reporting(self, payload: dict[str, Any]) -> dict[str, Any]:
        owner_rows = payload.get("owner_day_rows") if isinstance(payload.get("owner_day_rows"), list) else []
        if not owner_rows:
            return {
                "available": False,
                "note": "ai-loop-reporting 汇总里还没有 owner_day_rows。",
            }

        latest_allowed_day = _yesterday_key()
        daily_map: dict[str, dict[str, Any]] = {}
        for row in owner_rows:
            if not isinstance(row, dict):
                continue
            day_key = _text(row.get("day"))
            if not day_key or day_key < TREND_BASELINE_START or day_key > latest_allowed_day:
                continue
            bucket = daily_map.setdefault(
                day_key,
                {
                    "day": day_key,
                    "publish_count": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "view_total": 0,
                    "click_total": 0,
                    "interaction_total": 0,
                },
            )
            bucket["publish_count"] += _safe_int(row.get("publish_actions"))
            bucket["success_count"] += _safe_int(row.get("success_videos"))
            bucket["failed_count"] += _safe_int(row.get("failed_videos"))
            bucket["view_total"] += _safe_int(row.get("views"))
            bucket["click_total"] += _safe_int(row.get("link_clicks"))
            bucket["interaction_total"] += (
                _safe_int(row.get("likes"))
                + _safe_int(row.get("comments"))
                + _safe_int(row.get("shares"))
            )

        rows = sorted(daily_map.values(), key=lambda item: _text(item.get("day")), reverse=True)
        if not rows:
            return {
                "available": False,
                "note": "ai-loop-reporting 汇总里还没有昨天以前的全体日样本。",
            }

        for row in rows:
            publish_count = _safe_int(row.get("publish_count"))
            success_count = _safe_int(row.get("success_count"))
            row["success_rate"] = round((success_count / publish_count) * 100, 2) if publish_count else 0.0

        latest = rows[0]
        previous = rows[1] if len(rows) > 1 else None
        baseline_rows = [
            row for row in rows
            if TREND_BASELINE_START <= _text(row.get("day")) <= TREND_BASELINE_END
        ] or list(rows)

        def avg(metric: str, bucket_rows: list[dict[str, Any]]) -> float:
            if not bucket_rows:
                return 0.0
            return sum(_safe_float(row.get(metric)) for row in bucket_rows) / len(bucket_rows)

        latest_day = _text(latest.get("day"))
        previous_day = _text(previous.get("day")) if previous else ""
        running_rows = [
            row for row in rows
            if TREND_RUNNING_START <= _text(row.get("day")) <= latest_day
        ] or list(rows)

        def compare_card(label: str, metric: str, kind: str = "integer") -> dict[str, Any]:
            current_value = _safe_float(latest.get(metric))
            previous_value = _safe_float(previous.get(metric)) if previous else 0.0
            delta = current_value - previous_value if previous else None
            delta_pct = None
            if previous and previous_value:
                delta_pct = (delta / previous_value) * 100
            note = f"前一天 {previous_day}: {previous_value:.2f}" if previous else "暂无前一天样本"
            return self._trend_metric_card(
                label=f"单日{label}对比",
                value=current_value,
                kind=kind,
                note=note,
                delta=delta,
                delta_pct=delta_pct,
            )

        baseline_cards = [
            self._trend_metric_card(
                label="全体每日播放平均",
                value=FIXED_BASELINE_CARD_VALUES["全体每日播放平均"],
                kind="number",
                note=f"基线 {TREND_BASELINE_START} 至 {TREND_BASELINE_END} · 样本 {len(baseline_rows)} 天",
            ),
            self._trend_metric_card(
                label="全体每日互动平均",
                value=FIXED_BASELINE_CARD_VALUES["全体每日互动平均"],
                kind="number",
                note="点赞 + 评论 + 分享",
            ),
            self._trend_metric_card(
                label="全体每日发布平均",
                value=FIXED_BASELINE_CARD_VALUES["全体每日发布平均"],
                kind="number",
                note="ai-loop-reporting 全体日汇总口径",
            ),
            self._trend_metric_card(
                label="全体每日成功平均",
                value=FIXED_BASELINE_CARD_VALUES["全体每日成功平均"],
                kind="number",
                note="当日发布成功数",
            ),
            self._trend_metric_card(
                label="全体每日点击平均",
                value=FIXED_BASELINE_CARD_VALUES["全体每日点击平均"],
                kind="number",
                note="推广链接点击次数",
            ),
            self._trend_metric_card(
                label="全体每日成功率均值",
                value=FIXED_BASELINE_CARD_VALUES["全体每日成功率均值"],
                kind="percent",
                note="成功数 / 发布数",
            ),
        ]
        compare_cards = [
            compare_card("播放", "view_total"),
            compare_card("互动", "interaction_total"),
            compare_card("发布", "publish_count"),
            compare_card("成功", "success_count"),
            compare_card("点击", "click_total"),
            compare_card("成功率", "success_rate", "percent"),
        ]
        running_label_suffix = latest_day or "前一天"
        running_average_title = (
            f"从 {TREND_RUNNING_START} 到 {latest_day} 的均值"
            if latest_day and latest_day >= TREND_RUNNING_START
            else f"从 {TREND_RUNNING_START} 到前一天的均值"
        )
        running_average_cards = [
            self._trend_metric_card(
                label=f"6月9号到{running_label_suffix}平均播放",
                value=avg("view_total", running_rows),
                kind="integer",
                note=f"{TREND_RUNNING_START} 至 {latest_day} · 样本 {len(running_rows)} 天",
            ),
            self._trend_metric_card(
                label=f"6月9号到{running_label_suffix}平均互动",
                value=avg("interaction_total", running_rows),
                kind="integer",
                note="点赞 + 评论 + 分享",
            ),
            self._trend_metric_card(
                label=f"6月9号到{running_label_suffix}平均发布",
                value=avg("publish_count", running_rows),
                kind="integer",
                note="ai-loop-reporting 全体日汇总口径",
            ),
            self._trend_metric_card(
                label=f"6月9号到{running_label_suffix}平均点击",
                value=avg("click_total", running_rows),
                kind="integer",
                note="推广链接点击次数",
            ),
        ]
        daily_rows = list(rows)
        return {
            "available": True,
            "source": "ai_loop_reporting_p0_summary",
            "baseline_start": TREND_BASELINE_START,
            "baseline_end": TREND_BASELINE_END,
            "baseline_days": len(baseline_rows),
            "latest_day": latest_day,
            "previous_day": previous_day,
            "latest_generated_at": _text(payload.get("generated_at")),
            "latest_summary": _text(payload.get("data_freshness", {}).get("policy") if isinstance(payload.get("data_freshness"), dict) else ""),
            "latest_file_name": "p0-summary.json",
            "latest_note": f"基于 ai-loop-reporting 全体汇总，统计截止 {latest_day}",
            "baseline_cards": baseline_cards,
            "compare_cards": compare_cards,
            "running_average_title": running_average_title,
            "running_average_cards": running_average_cards,
            "daily_rows": daily_rows,
        }

    def _fetch_publish_analysis_metrics(self, *, start_date: str = "", end_date: str = "") -> dict[str, Any]:
        cache_key = f"publish:{start_date}:{end_date}"
        ttl = 90 if start_date or end_date else 1800
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            return cached
        body = require_success(
            get_publish_analysis(
                page=1,
                page_size=1,
                social_type="FACEBOOK",
                start_date=start_date,
                end_date=end_date,
            ),
            "获取发布分析",
        )
        page = body.get("page") if isinstance(body.get("page"), dict) else {}
        payload = {
            "view_total": _safe_int(body.get("view")),
            "interaction_total": _safe_int(body.get("interaction")),
            "income_total": round(_safe_float(body.get("order_amount")), 2),
            "success_count": _safe_int(page.get("total_count")),
        }
        return self._set_cached_remote(cache_key, ttl, payload)

    def _fetch_publish_record_metrics(self, *, day_key: str) -> dict[str, Any]:
        cache_key = f"publish-records:{day_key}"
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            return cached
        today_start = f"{day_key} 00:00:00" if day_key else ""
        today_end = f"{day_key} 23:59:59" if day_key else ""
        page_size = 500
        page = 1
        rows: list[dict[str, Any]] = []
        total_count = 0
        while page <= 10:
            body = require_success(
                get_publish_records(
                    page=page,
                    page_size=page_size,
                    post_status=0,
                    social_type="FACEBOOK",
                    start_date=today_start,
                    end_date=today_end,
                ),
                "获取发布管理记录",
            )
            page_rows = body.get("items") if isinstance(body.get("items"), list) else []
            rows.extend(dict(item) for item in page_rows if isinstance(item, dict))
            total_count = _safe_int((body.get("page") or {}).get("total_count"))
            if not page_rows:
                break
            if total_count and len(rows) >= total_count:
                break
            page += 1

        success_statuses = {"POSTED", "SUCCESS", "DONE"}
        success_rows = [row for row in rows if _text(row.get("status")).upper() in success_statuses]
        success_accounts = {
            _text(row.get("social_id")) or _text(row.get("social_name"))
            for row in success_rows
            if _text(row.get("social_id")) or _text(row.get("social_name"))
        }
        success_titles = {
            _text(row.get("title"))
            for row in success_rows
            if _text(row.get("title"))
        }
        payload = {
            "requested_count": total_count or len(rows),
            "success_count": len(success_rows),
            "failed_count": max((total_count or len(rows)) - len(success_rows), 0),
            "success_accounts": len(success_accounts),
            "title_count": len(success_titles),
        }
        return self._set_cached_remote(cache_key, 90, payload)

    def _fetch_publish_error_count(self, *, day_key: str) -> int:
        cache_key = f"publish-records-error-count:{day_key}"
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            return _safe_int(cached.get("count"))

        today_start = f"{day_key} 00:00:00" if day_key else ""
        today_end = f"{day_key} 23:59:59" if day_key else ""
        body = require_success(
            get_publish_records(
                page=1,
                page_size=1,
                post_status=0,
                status="ERROR",
                social_type="FACEBOOK",
                start_date=today_start,
                end_date=today_end,
            ),
            "获取发布失败记录",
        )
        count = _safe_int((body.get("page") or {}).get("total_count"))
        self._set_cached_remote(cache_key, 90, {"count": count})
        return count

    def _fetch_all_my_task_rows(self, *, task_type: str = "1") -> list[dict[str, Any]]:
        cache_key = f"my-task-all:{task_type}"
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            rows = cached.get("rows")
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, dict)]

        page_size = 500
        page = 1
        rows: list[dict[str, Any]] = []
        total_count = 0
        while page <= 20:
            body = require_success(
                get_my_task_list(page=page, page_size=page_size, task_type=task_type),
                "获取我的短剧任务",
            )
            page_rows = body.get("data") if isinstance(body.get("data"), list) else []
            rows.extend(dict(item) for item in page_rows if isinstance(item, dict))
            total_count = _safe_int((body.get("page") or {}).get("total_count"))
            if not page_rows:
                break
            if total_count and len(rows) >= total_count:
                break
            page += 1
        self._set_cached_remote(cache_key, 600, {"rows": rows, "total_count": total_count or len(rows)})
        return rows

    def _aggregate_my_task_metrics(
        self,
        rows: list[dict[str, Any]],
        *,
        day_key: str = "",
        start_day: str = "",
        end_day: str = "",
    ) -> dict[str, Any]:
        click_total = 0
        share_total = 0.0
        ad_total = 0.0
        click_task_count = 0
        for row in rows:
            active_day = _text(row.get("actived_at"))[:10]
            if day_key and active_day != day_key:
                continue
            if start_day and active_day and active_day < start_day:
                continue
            if end_day and active_day and active_day > end_day:
                continue
            platform_rows = row.get("platform_list") if isinstance(row.get("platform_list"), list) else []
            facebook_row = next(
                (
                    item for item in platform_rows
                    if isinstance(item, dict) and _safe_int(item.get("platform")) == 2
                ),
                {},
            )
            # 点击口径按 /agent/v1/task/my_task 返回的当天任务 click_count 汇总，
            # 不再使用 platform_list 内部的 Facebook 子字段，避免看板值偏小。
            platform_click = _safe_int(row.get("click_count"))
            platform_share = round(_safe_float(facebook_row.get("share_amount")), 2)
            platform_ad = round(_safe_float(facebook_row.get("ad_amount")), 2)
            click_total += platform_click
            share_total += platform_share
            ad_total += platform_ad
            if platform_click > 0:
                click_task_count += 1
        return {
            "click_total": click_total,
            "income_total": round(share_total, 2),
            "ad_total": round(ad_total, 2),
            "click_task_count": click_task_count,
        }

    def _build_external_summary_metrics_payload(self, *, today_key: str) -> dict[str, Any]:
        today_start = f"{today_key} 00:00:00" if today_key else ""
        today_end = f"{today_key} 23:59:59" if today_key else ""
        metrics = {
            "overall_publish": {
                "view_total": 0,
                "interaction_total": 0,
                "income_total": 0.0,
                "success_count": 0,
            },
            "today_records": {
                "requested_count": 0,
                "success_count": 0,
                "failed_count": 0,
                "success_accounts": 0,
                "title_count": 0,
            },
            "today_publish": {
                "view_total": 0,
                "interaction_total": 0,
                "income_total": 0.0,
                "success_count": 0,
            },
            "overall_my_task": {
                "click_total": 0,
                "income_total": 0.0,
                "ad_total": 0.0,
                "click_task_count": 0,
            },
            "today_my_task": {
                "click_total": 0,
                "income_total": 0.0,
                "ad_total": 0.0,
                "click_task_count": 0,
            },
        }

        try:
            metrics["overall_publish"] = self._fetch_publish_analysis_metrics()
        except Exception:
            pass
        try:
            if today_key:
                metrics["today_records"] = self._fetch_publish_record_metrics(day_key=today_key)
        except Exception:
            pass
        try:
            if today_key:
                metrics["today_records"]["failed_count"] = self._fetch_publish_error_count(day_key=today_key)
        except Exception:
            pass
        try:
            if today_start and today_end:
                metrics["today_publish"] = self._fetch_publish_analysis_metrics(
                    start_date=today_start,
                    end_date=today_end,
                )
        except Exception:
            pass
        try:
            my_task_rows = self._fetch_all_my_task_rows(task_type="1")
            metrics["overall_my_task"] = self._aggregate_my_task_metrics(my_task_rows)
            metrics["overall_my_task_window"] = self._aggregate_my_task_metrics(
                my_task_rows,
                start_day=TREND_BASELINE_START,
                end_day=today_key,
            )
            metrics["today_my_task"] = self._aggregate_my_task_metrics(my_task_rows, day_key=today_key)
        except Exception:
            pass
        return metrics

    def _persist_summary_metrics(self, *, today_key: str, payload: dict[str, Any]) -> None:
        _json_dump(
            SUMMARY_METRICS_CACHE_PATH,
            {
                "today_key": today_key,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "payload": payload,
            },
        )

    def _refresh_external_summary_metrics_background(self, *, today_key: str, cache_key: str) -> None:
        try:
            payload = self._build_external_summary_metrics_payload(today_key=today_key)
            self._set_cached_remote(cache_key, 90, payload)
            self._persist_summary_metrics(today_key=today_key, payload=payload)
        except Exception:
            pass
        finally:
            self._background_refreshing.discard(cache_key)

    def _external_summary_metrics(self, *, today_key: str) -> dict[str, Any]:
        cache_key = f"dashboard-summary:{today_key}"
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            return cached

        persisted = _json_load(SUMMARY_METRICS_CACHE_PATH)
        persisted_key = _text(persisted.get("today_key"))
        persisted_payload = persisted.get("payload") if isinstance(persisted.get("payload"), dict) else {}
        persisted_updated_at = _text(persisted.get("updated_at"))
        if persisted_key == today_key and persisted_payload:
            self._set_cached_remote(cache_key, 90, persisted_payload)
            refresh_needed = True
            if persisted_updated_at:
                try:
                    age_seconds = max(
                        0.0,
                        (datetime.now() - datetime.fromisoformat(persisted_updated_at)).total_seconds(),
                    )
                    refresh_needed = age_seconds > 30
                except Exception:
                    refresh_needed = True
            if refresh_needed and cache_key not in self._background_refreshing:
                self._background_refreshing.add(cache_key)
                threading.Thread(
                    target=self._refresh_external_summary_metrics_background,
                    kwargs={"today_key": today_key, "cache_key": cache_key},
                    daemon=True,
                ).start()
            return persisted_payload

        payload = self._build_external_summary_metrics_payload(today_key=today_key)
        self._set_cached_remote(cache_key, 90, payload)
        self._persist_summary_metrics(today_key=today_key, payload=payload)
        return payload

    def _fetch_publish_analysis_items(self, *, day_key: str) -> dict[str, Any]:
        cache_key = f"publish-analysis-items:{day_key}"
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            return cached
        start_date = f"{day_key} 00:00:00" if day_key else ""
        end_date = f"{day_key} 23:59:59" if day_key else ""
        page_size = 100
        page = 1
        items: list[dict[str, Any]] = []
        total_count = 0
        summary_view = 0
        summary_interaction = 0
        while page <= 20:
            body = require_success(
                get_publish_analysis(
                    page=page,
                    page_size=page_size,
                    social_type="FACEBOOK",
                    start_date=start_date,
                    end_date=end_date,
                ),
                "获取今日播放分析明细",
            )
            page_rows = body.get("items") if isinstance(body.get("items"), list) else []
            if page == 1:
                total_count = _safe_int((body.get("page") or {}).get("total_count"))
                summary_view = _safe_int(body.get("view"))
                summary_interaction = _safe_int(body.get("interaction"))
            items.extend(dict(item) for item in page_rows if isinstance(item, dict))
            if not page_rows:
                break
            if total_count and len(items) >= total_count:
                break
            page += 1
        payload = {
            "items": items,
            "total_count": total_count or len(items),
            "view_total": summary_view,
            "interaction_total": summary_interaction,
        }
        return self._set_cached_remote(cache_key, 25, payload)

    def _build_account_line_map(self) -> dict[str, str]:
        account_line_map: dict[str, str] = {}
        for group in self._load_account_groups():
            group_key = _text(group.get("key"))
            line_name = next((key for key, pool_key in LINE_POOL_KEYS.items() if pool_key == group_key), "")
            if not line_name:
                continue
            for account_id in group.get("account_ids", []):
                normalized_id = _text(account_id)
                if normalized_id:
                    account_line_map[normalized_id] = line_name
        return account_line_map

    def _build_task_line_map(self, *, start_day: str = "", end_day: str = "") -> dict[str, dict[str, Any]]:
        cache_key = f"task-line-map:{start_day}:{end_day}"
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            rows = cached.get("rows")
            if isinstance(rows, dict):
                return {
                    _text(task_id): dict(item)
                    for task_id, item in rows.items()
                    if _text(task_id) and isinstance(item, dict)
                }

        task_line_map: dict[str, dict[str, Any]] = {}
        for path in sorted(CONTINUOUS_ROOT.rglob("tasks.json")):
            try:
                day_key = path.parents[2].name
            except Exception:
                day_key = ""
            if start_day and day_key and day_key < start_day:
                continue
            if end_day and day_key and day_key > end_day:
                continue
            payload = _json_load(path)
            rows = payload.get("rows") if isinstance(payload, dict) and isinstance(payload.get("rows"), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                task_id = _text(row.get("task_id"))
                clip_params = row.get("clip_params") if isinstance(row.get("clip_params"), dict) else {}
                line_name = _text(clip_params.get("line_name"))
                if not task_id or not line_name:
                    continue
                task_line_map[task_id] = {
                    "task_id": task_id,
                    "day_key": _text(row.get("date")) or day_key,
                    "line_name": line_name,
                    "line_label": _text(clip_params.get("line_label")) or LINE_DISPLAY_NAMES.get(line_name) or line_name,
                    "account_name": _text(row.get("douyin_t8_account") or row.get("account_name")),
                    "app_id": _text(clip_params.get("app_id")),
                    "drama_title": _text(row.get("drama_name")),
                    "round_name": _text(row.get("round_name")),
                }
        self._set_cached_remote(cache_key, 600, {"rows": task_line_map})
        return task_line_map

    def _parse_dashboard_dt(self, value: Any) -> datetime | None:
        text = _text(value)
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("T", " "))
        except Exception:
            return None

    def _infer_app_name_from_publish_item(self, item: dict[str, Any]) -> str:
        blob = " ".join(
            [
                _text(item.get("text")),
                _text(item.get("title")),
                _text(item.get("post_source")),
            ]
        ).lower()
        app_map = {
            "yourchannel_drama": "YourChannel",
            "yourchannel": "YourChannel",
            "stardusttv": "StardustTV",
            "stardust tv": "StardustTV",
            "touchshort": "TouchShort",
            "moboreels": "MoboReels",
            "goodshort": "GoodShort",
            "dramabox": "DramaBox",
            "shortmax": "ShortMax",
            "flickreels": "FlickReels",
            "kalostv": "KalosTV",
            "snackshort": "SnackShort",
        }
        for token, app_name in app_map.items():
            if token in blob:
                return app_name
        return ""

    def _get_publish_line_candidates(
        self,
        *,
        day_key: str,
        account_line_map: dict[str, str],
    ) -> list[dict[str, Any]]:
        cache_key = f"publish-line-candidates:{day_key}"
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            rows = cached.get("rows")
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, dict)]

        body = self._fetch_publish_analysis_items(day_key=day_key)
        items = body.get("items") if isinstance(body.get("items"), list) else []
        rows: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            social_id = _text(item.get("social_id"))
            line_name = account_line_map.get(social_id, "")
            if not line_name:
                continue
            rows.append(
                {
                    "line_name": line_name,
                    "line_label": LINE_DISPLAY_NAMES.get(line_name) or line_name,
                    "social_id": social_id,
                    "social_name": _text(item.get("social_name")),
                    "task_id": _text(item.get("task_id")),
                    "app_name": self._infer_app_name_from_publish_item(item),
                    "title": _text(item.get("title")),
                    "text": _text(item.get("text")),
                    "order_amount": round(_safe_float(item.get("order_amount")), 2),
                    "published_at": _text(item.get("post_date") or item.get("created_at")),
                }
            )
        self._set_cached_remote(cache_key, 600, {"rows": rows})
        return rows

    def _infer_task_line_from_publish_candidates(
        self,
        row: dict[str, Any],
        *,
        account_line_map: dict[str, str],
    ) -> dict[str, Any]:
        day_key = _text(row.get("actived_at"))[:10]
        app_name = _text(row.get("app_name"))
        if not day_key or not app_name:
            return {}

        candidates = self._get_publish_line_candidates(day_key=day_key, account_line_map=account_line_map)
        if not candidates:
            return {}

        active_dt = self._parse_dashboard_dt(row.get("actived_at"))
        if not active_dt:
            return {}

        title = _text(row.get("title") or row.get("title_en") or row.get("title_ch")).strip()
        title_lower = title.lower()
        share_income_total = round(_safe_float(row.get("share_amount")), 2)

        scored: list[tuple[int, int, float, dict[str, Any]]] = []
        for candidate in candidates:
            if _text(candidate.get("app_name")) != app_name:
                continue
            published_dt = self._parse_dashboard_dt(candidate.get("published_at"))
            if not published_dt:
                continue
            text_blob = " ".join([_text(candidate.get("title")), _text(candidate.get("text"))]).lower()
            title_hit = 1 if title_lower and title_lower in text_blob else 0
            income_hit = 1 if share_income_total > 0 and abs(_safe_float(candidate.get("order_amount")) - share_income_total) < 0.01 else 0
            delta_seconds = abs((published_dt - active_dt).total_seconds())
            scored.append((title_hit, income_hit, delta_seconds, candidate))

        if not scored:
            return {}

        scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
        best_title_hit, best_income_hit, best_delta, best_candidate = scored[0]
        second = scored[1] if len(scored) > 1 else None

        strict_limit_seconds = 2 * 60 * 60
        soft_limit_seconds = 6 * 60 * 60
        if best_title_hit <= 0 and best_income_hit <= 0 and best_delta > strict_limit_seconds:
            return {}
        if (best_title_hit > 0 or best_income_hit > 0) and best_delta > soft_limit_seconds:
            return {}

        if second is not None:
            second_title_hit, second_income_hit, second_delta, second_candidate = second
            same_confidence = (
                second_title_hit == best_title_hit
                and second_income_hit == best_income_hit
                and abs(second_delta - best_delta) < 60
                and _text(second_candidate.get("line_name")) != _text(best_candidate.get("line_name"))
            )
            if same_confidence:
                return {}

        return {
            "line_name": _text(best_candidate.get("line_name")),
            "line_label": _text(best_candidate.get("line_label")) or LINE_DISPLAY_NAMES.get(_text(best_candidate.get("line_name"))) or "",
            "social_id": _text(best_candidate.get("social_id")),
            "social_name": _text(best_candidate.get("social_name")),
            "matched_by": "publish_fallback",
        }

    def _extract_my_task_metrics(self, row: dict[str, Any]) -> dict[str, Any]:
        platform_rows = row.get("platform_list") if isinstance(row.get("platform_list"), list) else []

        def _sum_platform(field: str) -> float:
            total = 0.0
            for item in platform_rows:
                if isinstance(item, dict):
                    total += _safe_float(item.get(field))
            return total

        click_total = _safe_int(row.get("click_count"))
        if click_total <= 0:
            click_total = int(round(_sum_platform("click_count")))

        share_income_total = round(_safe_float(row.get("share_amount")), 2)
        if share_income_total <= 0:
            share_income_total = round(_sum_platform("share_amount"), 2)

        ad_income_total = round(_safe_float(row.get("ad_amount")), 2)
        if ad_income_total <= 0:
            ad_income_total = round(_sum_platform("ad_amount"), 2)

        order_amount_total = round(_safe_float(row.get("order_amount")), 2)
        if order_amount_total <= 0:
            order_amount_total = round(_sum_platform("order_amount"), 2)

        income_total = round(share_income_total + ad_income_total + order_amount_total, 2)
        return {
            "click_total": click_total,
            "share_income_total": share_income_total,
            "ad_income_total": ad_income_total,
            "order_amount_total": order_amount_total,
            "income_total": income_total,
        }

    def _resolve_my_task_line(
        self,
        row: dict[str, Any],
        *,
        task_line_map: dict[str, dict[str, Any]],
        account_line_map: dict[str, str],
        task_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if task_metrics is None:
            task_metrics = self._extract_my_task_metrics(row)

        task_id = _text(row.get("task_id"))
        task_line = task_line_map.get(task_id, {}) if task_id else {}
        line_name = _text(task_line.get("line_name"))
        if line_name:
            return task_line

        should_try_publish_fallback = (
            _safe_int(task_metrics.get("click_total")) > 0
            or _safe_float(task_metrics.get("income_total")) > 0
        )
        if not should_try_publish_fallback:
            return {}

        task_line = self._infer_task_line_from_publish_candidates(
            row,
            account_line_map=account_line_map,
        )
        return task_line if _text(task_line.get("line_name")) else {}

    def _rebuild_line_cumulative_from_seed_rows(
        self,
        *,
        start_day: str,
        end_day: str,
        seed_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        line_order = [
            "realtime_day",
            "yourchannel",
            "realtime",
            "recent_order",
            "stardusttv",
            "tag_test",
            "realtime_single",
            "ordinary",
            "fbhot_test",
            "creative_list_day",
            "creative_list",
        ]
        account_groups = self._load_account_groups()
        line_account_counts: dict[str, int] = {}
        for group in account_groups:
            group_key = _text(group.get("key"))
            mapped_line = next((key for key, pool_key in LINE_POOL_KEYS.items() if pool_key == group_key), "")
            if mapped_line:
                line_account_counts[mapped_line] = _safe_int(group.get("count"))

        def _new_bucket(line_name: str) -> dict[str, Any]:
            return {
                "line_name": line_name,
                "line_label": LINE_DISPLAY_NAMES.get(line_name) or line_name,
                "account_count": _safe_int(line_account_counts.get(line_name)),
                "post_count": 0,
                "view_total": 0,
                "click_total": 0,
                "income_total": 0.0,
                "interaction_total": 0,
                "like_total": 0,
                "comment_total": 0,
                "share_total": 0,
                "share_income_total": 0.0,
                "ad_income_total": 0.0,
                "order_amount_total": 0.0,
                "matched_task_count": 0,
                "unmatched_task_count": 0,
            }

        buckets: dict[str, dict[str, Any]] = {
            line_name: _new_bucket(line_name)
            for line_name in line_order
        }
        account_line_map = self._build_account_line_map()

        for row in seed_rows:
            if not isinstance(row, dict):
                continue
            line_name = _text(row.get("line_name"))
            if not line_name or line_name not in buckets:
                continue
            bucket = buckets[line_name]
            for key in ("post_count", "view_total", "interaction_total", "like_total", "comment_total", "share_total"):
                bucket[key] = _safe_int(row.get(key))

        my_task_rows = self._fetch_all_my_task_rows(task_type="1")
        task_line_map = self._build_task_line_map(start_day=start_day, end_day=end_day)
        exact_task_match_count = 0
        publish_fallback_match_count = 0
        unmatched_click_total = 0
        unmatched_income_total = 0.0
        for row in my_task_rows:
            day_key = _text(row.get("actived_at"))[:10]
            if not day_key or day_key < start_day or day_key > end_day:
                continue
            task_metrics = self._extract_my_task_metrics(row)
            task_line = self._resolve_my_task_line(
                row,
                task_line_map=task_line_map,
                account_line_map=account_line_map,
                task_metrics=task_metrics,
            )
            line_name = _text(task_line.get("line_name"))
            if not line_name or line_name not in buckets:
                unmatched_click_total += _safe_int(task_metrics.get("click_total"))
                unmatched_income_total = round(
                    unmatched_income_total + _safe_float(task_metrics.get("income_total")),
                    2,
                )
                continue
            bucket = buckets[line_name]
            bucket["click_total"] += _safe_int(task_metrics.get("click_total"))
            bucket["income_total"] = round(
                _safe_float(bucket.get("income_total"))
                + _safe_float(task_metrics.get("income_total")),
                2,
            )
            bucket["share_income_total"] = round(
                _safe_float(bucket.get("share_income_total"))
                + _safe_float(task_metrics.get("share_income_total")),
                2,
            )
            bucket["ad_income_total"] = round(
                _safe_float(bucket.get("ad_income_total"))
                + _safe_float(task_metrics.get("ad_income_total")),
                2,
            )
            bucket["order_amount_total"] = round(
                _safe_float(bucket.get("order_amount_total"))
                + _safe_float(task_metrics.get("order_amount_total")),
                2,
            )
            bucket["matched_task_count"] += 1
            if _text(task_line.get("matched_by")) == "publish_fallback":
                publish_fallback_match_count += 1
            else:
                exact_task_match_count += 1

        rows = []
        for line_name in line_order:
            bucket = dict(buckets[line_name])
            rows.append(
                {
                    **bucket,
                    "income_total": round(_safe_float(bucket.get("income_total")), 2),
                    "share_income_total": round(_safe_float(bucket.get("share_income_total")), 2),
                    "ad_income_total": round(_safe_float(bucket.get("ad_income_total")), 2),
                    "order_amount_total": round(_safe_float(bucket.get("order_amount_total")), 2),
                }
            )

        rows.sort(
            key=lambda row: (
                -_safe_int(row.get("view_total")),
                -_safe_int(row.get("click_total")),
                -_safe_float(row.get("income_total")),
                row.get("line_label") or "",
            )
        )

        unmatched_note = ""
        if unmatched_click_total > 0 or unmatched_income_total > 0:
            unmatched_note = (
                f" 另有未精确归线的任务数据未计入表格：点击 {unmatched_click_total}，"
                f"总收益 {round(unmatched_income_total, 2):.2f}。"
            )

        return {
            "available": True,
            "start_day": start_day,
            "end_day": end_day,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_rows": len(rows),
            "total_posts": sum(_safe_int(row.get("post_count")) for row in rows),
            "rows": rows,
            "note": (
                f"播放/互动沿用最近一次发布分析缓存；点击按任务总点击汇总（包含任务各平台点击，YourChannel 会算 TikTok 点击）；"
                f"收益按分佣+广告+订单汇总；点击/收益优先按归档 task_id 精确映射到线路后重算，"
                f"精确匹配 {exact_task_match_count} 条，发布账号兜底补映射 {publish_fallback_match_count} 条。"
                f"{unmatched_note}"
            ),
            "cache_version": 4,
        }

    def _load_analysis_report_rows(self) -> list[dict[str, Any]]:
        cache_key = "analysis-report-rows"
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            rows = cached.get("rows")
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, dict)]

        rows: list[dict[str, Any]] = []
        for path in sorted(ANALYSIS_REPORT_DIR.glob("发布数据分析日报_*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue

            generated_at = ""
            window_start = ""
            window_end = ""
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("**生成时间**:"):
                    generated_at = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("**统计窗口**:"):
                    window_value = stripped.split(":", 1)[1].strip()
                    if "至" in window_value:
                        parts = [part.strip() for part in window_value.split("至", 1)]
                        if len(parts) == 2:
                            window_start, window_end = parts

            overview = _parse_markdown_table(text, "总体概览")
            if not overview:
                continue
            report_day = window_end or window_start or path.stem[-8:]
            report_day = report_day.replace("/", "-").strip()
            publish_count = _number_to_int(overview.get("当日发布视频总数"))
            success_count = _number_to_int(overview.get("当日发布成功数"))
            rows.append(
                {
                    "file_name": path.name,
                    "generated_at": generated_at,
                    "window_start": window_start,
                    "window_end": window_end,
                    "report_day": report_day,
                    "publish_count": publish_count,
                    "success_count": success_count,
                    "failed_count": max(publish_count - success_count, 0),
                    "view_total": _number_to_int(overview.get("总播放量")),
                    "click_total": _number_to_int(overview.get("当日推广链接点击次数")),
                    "interaction_total": _number_to_int(overview.get("总互动量")),
                    "income_total": round(_safe_float(_parse_metric_number(overview.get("总收益"))), 2),
                    "like_total": _number_to_int(overview.get("点赞数")),
                    "comment_total": _number_to_int(overview.get("评论数")),
                    "share_total": _number_to_int(overview.get("分享数")),
                    "account_total": _number_to_int(overview.get("覆盖账号数")),
                    "success_rate": round((success_count / publish_count) * 100, 2) if publish_count else 0.0,
                    "overview": overview,
                    "summary_lines": _parse_markdown_bullets(text, "结论摘要"),
                }
            )
        rows.sort(key=lambda item: (_text(item.get("report_day")), _text(item.get("generated_at"))), reverse=True)
        self._set_cached_remote(cache_key, 300, {"rows": rows})
        return rows

    def _trend_metric_card(
        self,
        *,
        label: str,
        value: float,
        kind: str = "number",
        note: str = "",
        delta: float | None = None,
        delta_pct: float | None = None,
    ) -> dict[str, Any]:
        return {
            "label": label,
            "value": round(value, 3) if kind != "integer" else int(round(value)),
            "kind": kind,
            "note": note,
            "delta": None if delta is None else round(delta, 3),
            "delta_pct": None if delta_pct is None else round(delta_pct, 2),
        }

    def _build_overall_summary(self, rounds: list[RoundArchive]) -> dict[str, Any]:
        account_groups = self._load_account_groups()
        line_pool_keys = set(LINE_POOL_KEYS.values())
        total_unique_accounts = len(
            {
                account_id
                for row in account_groups
                for account_id in row.get("account_ids", [])
            }
        )
        used_pool_account_count = sum(
            _safe_int(row.get("count"))
            for row in account_groups
            if row.get("key") in line_pool_keys
        )
        reserve_accounts = next(
            (_safe_int(row.get("count")) for row in account_groups if row.get("key") == "facebook_drama_reserve_pool"),
            0,
        )
        today_key, today_rounds = self._select_today_rounds()
        today_metrics_day_key = date.today().isoformat()
        requested_today = sum(row.requested_count for row in today_rounds)
        success_today = sum(row.success_count for row in today_rounds)
        failed_today = sum(row.failed_count for row in today_rounds)
        processing_today = sum(row.processing_count for row in today_rounds)
        unsubmitted_today = sum(row.unsubmitted_count for row in today_rounds)
        success_accounts = set()
        failed_accounts = set()
        titles = set()
        for row in today_rounds:
            for item in row.items:
                if _classify_item(item) == "success":
                    if _text(item.get("account_name")):
                        success_accounts.add(_text(item.get("account_name")))
                    if _text(item.get("title")):
                        titles.add(_text(item.get("title")))
                elif _classify_item(item) == "failed" and _text(item.get("account_name")):
                    failed_accounts.add(_text(item.get("account_name")))

        external = self._external_summary_metrics(today_key=today_metrics_day_key)
        overall_publish = external.get("overall_publish") if isinstance(external.get("overall_publish"), dict) else {}
        today_records = external.get("today_records") if isinstance(external.get("today_records"), dict) else {}
        today_publish = external.get("today_publish") if isinstance(external.get("today_publish"), dict) else {}
        overall_my_task = external.get("overall_my_task") if isinstance(external.get("overall_my_task"), dict) else {}
        overall_my_task_window = external.get("overall_my_task_window") if isinstance(external.get("overall_my_task_window"), dict) else {}
        today_my_task = external.get("today_my_task") if isinstance(external.get("today_my_task"), dict) else {}
        requested_today_real = _safe_int(today_records.get("requested_count"), requested_today)
        success_today_real = _safe_int(today_publish.get("success_count"), _safe_int(today_records.get("success_count"), success_today))
        failed_today_real = _safe_int(today_records.get("failed_count"))
        if failed_today_real <= 0 and requested_today_real > 0:
            failed_today_real = max(0, requested_today_real - success_today_real)

        return {
            "summary_day_key": today_key,
            "today_metrics_day_key": today_metrics_day_key,
            "publish_account_total": total_unique_accounts,
            "used_pool_account_count": used_pool_account_count,
            "reserve_accounts": reserve_accounts,
            "total_line_count": len([key for key in LINE_POOL_KEYS if key != "novel"]),
            "overall_view_total": _safe_int(overall_publish.get("view_total")),
            "overall_click_total": _safe_int(overall_my_task_window.get("click_total"), _safe_int(overall_my_task.get("click_total"))),
            "overall_click_task_count": _safe_int(overall_my_task_window.get("click_task_count"), _safe_int(overall_my_task.get("click_task_count"))),
            "overall_interaction_total": _safe_int(overall_publish.get("interaction_total")),
            "overall_income_total": round(_safe_float(overall_my_task.get("income_total")), 2),
            "today_requested_count": requested_today_real,
            "today_success_count": success_today_real,
            "today_failed_count": failed_today_real,
            "today_processing_count": processing_today,
            "today_unsubmitted_count": unsubmitted_today,
            "today_success_rate": round((success_today_real / requested_today_real) * 100, 2) if requested_today_real else 0.0,
            "today_view_total": _safe_int(today_publish.get("view_total")),
            "today_interaction_total": _safe_int(today_publish.get("interaction_total")),
            "today_click_total": _safe_int(today_my_task.get("click_total")),
            "today_click_task_count": _safe_int(today_my_task.get("click_task_count")),
            "today_success_source": "publish_analysis+publish_records",
            "today_click_source": "my_task",
            "success_accounts_today": _safe_int(today_records.get("success_accounts"), len(success_accounts)),
            "failed_accounts_today": len(failed_accounts),
            "title_count_today": _safe_int(today_records.get("title_count"), len(titles)),
        }

    def get_loop_overview(self, *, refresh: bool = False) -> dict[str, Any]:
        today_key = date.today().isoformat()
        cache_key = f"loop-overview:{today_key}"
        if refresh:
            self._remote_cache.pop(cache_key, None)
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            return cached

        today_key, today_rounds = self._select_today_rounds()
        all_rounds = self._scan_round_archives()
        account_group_map = {row["key"]: row for row in self._load_account_groups()}
        today_by_line: dict[str, dict[str, int]] = defaultdict(lambda: {
            "requested_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "processing_count": 0,
            "unsubmitted_count": 0,
        })
        for row in today_rounds:
            bucket = today_by_line[row.line_name]
            bucket["requested_count"] += row.requested_count
            bucket["success_count"] += row.success_count
            bucket["failed_count"] += row.failed_count
            bucket["processing_count"] += row.processing_count
            bucket["unsubmitted_count"] += row.unsubmitted_count

        latest_by_line: dict[str, RoundArchive] = {}
        for row in all_rounds:
            latest_by_line.setdefault(row.line_name, row)

        line_names = list(dict.fromkeys(
            [*LINE_DISPLAY_NAMES.keys(), *latest_by_line.keys()]
        ))
        line_targets: list[dict[str, Any]] = []
        for line_name in line_names:
            latest = latest_by_line.get(line_name)
            stats = today_by_line.get(line_name, {})
            live_runtime = _parse_live_line_runtime(line_name, day_key=today_key)
            pool_key = LINE_POOL_KEYS.get(line_name, "")
            pool_row = account_group_map.get(pool_key, {})
            pool_size = _safe_int(pool_row.get("count"))
            requested_count = _safe_int(stats.get("requested_count"))
            success_count = _safe_int(stats.get("success_count"))
            failed_count = _safe_int(stats.get("failed_count"))
            processing_count = _safe_int(stats.get("processing_count"))
            unsubmitted_count = _safe_int(stats.get("unsubmitted_count"))
            target_total = max(pool_size * 10, requested_count)
            progress_pct = round((success_count / target_total) * 100, 2) if target_total else 0.0
            failure_total = failed_count + unsubmitted_count
            stability_pct = round(max(0.0, 100 - ((failure_total / max(requested_count, 1)) * 100)), 2) if requested_count else 0.0
            latest_is_today = bool(latest and latest.day_key == today_key)
            latest_is_processing_today = bool(
                latest_is_today
                and (latest.processing_count > 0 or latest.status == "processing")
            )
            is_running = bool(live_runtime.get("is_running")) or latest_is_processing_today
            runtime_state = _text(live_runtime.get("runtime_state"))
            if not runtime_state:
                if latest_is_today and latest:
                    runtime_state = latest.status_label
                elif latest:
                    runtime_state = "未运行"
                else:
                    runtime_state = "未运行"
            line_targets.append(
                {
                    "line_name": line_name,
                    "display_name": LINE_DISPLAY_NAMES.get(line_name) or LINE_LABELS.get(line_name) or line_name,
                    "pool_key": pool_key,
                    "pool_size": pool_size,
                    "today_key": today_key,
                    "target_total": target_total,
                    "requested_count": requested_count,
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "processing_count": processing_count,
                    "unsubmitted_count": unsubmitted_count,
                    "progress_pct": progress_pct,
                    "stability_pct": stability_pct,
                    "last_update": live_runtime.get("last_update") or (latest.exported_at if latest else ""),
                    "latest_round": live_runtime.get("latest_round") or (latest.round_name if latest else ""),
                    "runtime_state": runtime_state,
                    "note": latest.note if latest else "",
                    "live_stage": live_runtime.get("live_stage") or "",
                    "is_running": is_running,
                }
            )
        return self._set_cached_remote(cache_key, 20, {
            "today_key": today_key,
            "window_summary": {
                "night_range": "18:00-次日12:00",
                "day_range": "10:00-18:00",
            },
            "line_targets": line_targets,
        })

    def _build_today_top_play_payload(self, *, day_key: str) -> dict[str, Any]:
        analysis_payload = self._fetch_publish_analysis_items(day_key=day_key)
        raw_items = analysis_payload.get("items") if isinstance(analysis_payload.get("items"), list) else []
        total_count = _safe_int(analysis_payload.get("total_count"))
        total_view = _safe_int(analysis_payload.get("view_total"))
        account_line_map = self._build_account_line_map()
        items: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            account_id = _text(item.get("social_id"))
            line_name = account_line_map.get(account_id, "")
            raw_copy_text = _text(item.get("text"))
            title_copy_text = _clean_publish_copy_text(raw_copy_text)
            view_count = _safe_int(item.get("views"))
            like_count = _safe_int(item.get("likes"))
            comment_count = _safe_int(item.get("comments"))
            share_count = _safe_int(item.get("shares"))
            items.append(
                {
                    "title": _build_top_play_title(raw_title=item.get("title"), copy_text=title_copy_text),
                    "published_at": _text(item.get("post_date") or item.get("created_at")),
                    "created_at": _text(item.get("created_at")),
                    "account_name": _text(item.get("social_name")) or "未知账号",
                    "account_id": account_id,
                    "platform": _text(item.get("social_type") or "FACEBOOK") or "FACEBOOK",
                    "view_count": view_count,
                    "like_count": like_count,
                    "comment_count": comment_count,
                    "share_count": share_count,
                    "line_name": line_name,
                    "line_label": LINE_DISPLAY_NAMES.get(line_name) or "待识别线路",
                    "clip_method": _line_clip_method(line_name),
                    "copy_text": raw_copy_text or "-",
                }
            )

        positive_items = [item for item in items if _safe_int(item.get("view_count")) > 0]
        positive_items.sort(
            key=lambda item: (
                -_safe_int(item.get("view_count")),
                -(_safe_int(item.get("like_count")) + _safe_int(item.get("comment_count")) + _safe_int(item.get("share_count"))),
                _text(item.get("published_at")),
            )
        )
        if not positive_items:
            if total_count > 0:
                return {
                    "available": True,
                    "day_key": day_key,
                    "items": [],
                    "note": f"今天已回收到 {total_count} 条发布分析记录，但当前播放汇总还是 0，先不展示 Top 5。",
                }
            return {
                "available": True,
                "day_key": day_key,
                "items": [],
                "note": "今天还没有拉到可用的播放回收记录。",
            }
        return {
            "available": True,
            "day_key": day_key,
            "items": positive_items[:5],
            "note": f"今天共回收 {total_count or len(items)} 条记录，总播放 {total_view}。",
        }

    def _refresh_today_top_play_background(self, *, day_key: str, cache_key: str) -> None:
        try:
            payload = self._build_today_top_play_payload(day_key=day_key)
            self._set_cached_remote(cache_key, 30, payload)
            _json_dump(
                TODAY_TOP_PLAY_CACHE_PATH,
                {
                    "day_key": day_key,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "payload": payload,
                },
            )
        except Exception:
            pass
        finally:
            self._background_refreshing.discard(cache_key)

    def get_today_top_play(self, *, force: bool = False) -> dict[str, Any]:
        day_key = date.today().isoformat()
        cache_key = f"today-top-play:{day_key}"
        if force:
            self._remote_cache.pop(cache_key, None)
            self._remote_cache.pop(f"publish-analysis-items:{day_key}", None)

        cached = self._get_cached_remote(cache_key)
        if cached is not None and not force:
            return cached

        persisted = _json_load(TODAY_TOP_PLAY_CACHE_PATH)
        persisted_day_key = _text(persisted.get("day_key"))
        persisted_updated_at_raw = _text(persisted.get("updated_at"))
        persisted_payload = persisted.get("payload") if isinstance(persisted.get("payload"), dict) else {}
        try:
            persisted_updated_at = datetime.fromisoformat(persisted_updated_at_raw) if persisted_updated_at_raw else None
        except Exception:
            persisted_updated_at = None

        if not force and persisted_day_key == day_key and persisted_payload:
            self._set_cached_remote(cache_key, 30, persisted_payload)
            refresh_needed = True
            if persisted_updated_at:
                try:
                    refresh_needed = (datetime.now() - persisted_updated_at).total_seconds() > 30
                except Exception:
                    refresh_needed = True
            if refresh_needed and cache_key not in self._background_refreshing:
                self._background_refreshing.add(cache_key)
                threading.Thread(
                    target=self._refresh_today_top_play_background,
                    kwargs={"day_key": day_key, "cache_key": cache_key},
                    daemon=True,
                ).start()
            return persisted_payload

        try:
            payload = self._build_today_top_play_payload(day_key=day_key)
        except Exception as exc:
            return {
                "available": False,
                "day_key": day_key,
                "items": [],
                "note": f"今天的播放分析接口暂时没拿到数据：{exc}",
            }
        self._set_cached_remote(cache_key, 30, payload)
        _json_dump(
            TODAY_TOP_PLAY_CACHE_PATH,
            {
                "day_key": day_key,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "payload": payload,
            },
        )
        return payload

    def get_daily_top_play_history(self, *, start_day: str = DAILY_TOP_HISTORY_START, force: bool = False) -> dict[str, Any]:
        display_end_dt = date.today() - timedelta(days=1)
        display_end_day = display_end_dt.isoformat()
        cache_key = f"daily-top-play-history:{start_day}:{display_end_day}"

        persisted = _json_load(DAILY_TOP_HISTORY_CACHE_PATH)
        persisted_updated_at_raw = _text(persisted.get("updated_at"))
        persisted_display_end_day = _text(persisted.get("display_end_day"))
        persisted_payload = persisted.get("payload") if isinstance(persisted.get("payload"), dict) else {}
        try:
            persisted_updated_at = datetime.fromisoformat(persisted_updated_at_raw) if persisted_updated_at_raw else None
        except Exception:
            persisted_updated_at = None

        refresh_cutoff = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        needs_daily_refresh = (
            datetime.now() >= refresh_cutoff
            and (
                persisted_display_end_day != display_end_day
                or persisted_updated_at is None
                or persisted_updated_at < refresh_cutoff
            )
        )

        force_refresh = force or needs_daily_refresh
        if force_refresh:
            self._remote_cache.pop(cache_key, None)
        cached = self._get_cached_remote(cache_key)
        if cached is not None and not force_refresh:
            return cached
        if (
            not force_refresh
            and persisted_display_end_day == display_end_day
            and persisted_payload
        ):
            return self._set_cached_remote(cache_key, 300, persisted_payload)
        if (
            not force_refresh
            and persisted_payload
            and cache_key not in self._background_refreshing
        ):
            self._set_cached_remote(cache_key, 300, persisted_payload)
            self._background_refreshing.add(cache_key)
            threading.Thread(
                target=self._refresh_daily_top_play_history_background,
                kwargs={"start_day": start_day, "cache_key": cache_key},
                daemon=True,
            ).start()
            return persisted_payload

        persisted_rows = persisted.get("rows") if isinstance(persisted.get("rows"), dict) else {}
        cached_rows: dict[str, dict[str, Any]] = {
            _text(day_key): dict(row)
            for day_key, row in persisted_rows.items()
            if isinstance(row, dict)
        }
        cache_changed = False

        my_task_rows = self._fetch_all_my_task_rows(task_type="1")
        task_metrics_map: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        task_rows_by_day_app: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for row in my_task_rows:
            day_key = _text(row.get("actived_at"))[:10]
            if not day_key or day_key < start_day:
                continue
            task_id = _text(row.get("task_id"))
            if not task_id:
                continue
            platform_rows = row.get("platform_list") if isinstance(row.get("platform_list"), list) else []
            facebook_row = next(
                (
                    item for item in platform_rows
                    if isinstance(item, dict) and _safe_int(item.get("platform")) == 2
                ),
                {},
            )
            click_total = _safe_int(facebook_row.get("click_count"), _safe_int(row.get("click_count")))
            share_income_total = round(
                _safe_float(facebook_row.get("share_amount"), _safe_float(row.get("share_amount"))),
                2,
            )
            ad_income_total = round(
                _safe_float(facebook_row.get("ad_amount"), _safe_float(row.get("ad_amount"))),
                2,
            )
            order_amount = round(
                _safe_float(facebook_row.get("order_amount"), _safe_float(row.get("order_amount"))),
                2,
            )
            task_metrics_map[day_key][task_id] = {
                "click_total": click_total,
                "share_income_total": share_income_total,
                "ad_income_total": ad_income_total,
                "income_total": round(share_income_total, 2),
                "order_amount": order_amount,
                "drama_title": _text(row.get("title") or row.get("title_en") or row.get("title_ch")),
                "app_name": _text(row.get("app_name")),
                "actived_at": _text(row.get("actived_at")),
            }
            app_name = _text(row.get("app_name"))
            if app_name:
                task_rows_by_day_app[day_key][app_name].append(task_metrics_map[day_key][task_id])

        account_line_map = self._build_account_line_map()

        def _parse_dt(text: str) -> datetime | None:
            value = _text(text)
            if not value:
                return None
            try:
                return datetime.fromisoformat(value.replace("T", " "))
            except Exception:
                return None

        def _infer_app_name(item: dict[str, Any]) -> str:
            blob = " ".join(
                [
                    _text(item.get("text")),
                    _text(item.get("title")),
                    _text(item.get("post_source")),
                ]
            ).lower()
            app_map = {
                "yourchannel_drama": "YourChannel",
                "yourchannel": "YourChannel",
                "touchshort": "TouchShort",
                "moboreels": "MoboReels",
                "goodshort": "GoodShort",
                "dramabox": "DramaBox",
                "shortmax": "ShortMax",
                "flickreels": "FlickReels",
                "kalostv": "KalosTV",
                "snackshort": "SnackShort",
            }
            for token, app_name in app_map.items():
                if token in blob:
                    return app_name
            return ""

        def _find_nearest_task_match(day_key: str, item: dict[str, Any]) -> dict[str, Any]:
            app_name = _infer_app_name(item)
            if not app_name:
                return {}
            candidates = task_rows_by_day_app.get(day_key, {}).get(app_name, [])
            if not candidates:
                return {}
            published_dt = _parse_dt(_text(item.get("post_date") or item.get("created_at")))
            if not published_dt:
                return {}
            scored: list[tuple[float, dict[str, Any]]] = []
            for candidate in candidates:
                active_dt = _parse_dt(_text(candidate.get("actived_at")))
                if not active_dt:
                    continue
                delta_seconds = abs((published_dt - active_dt).total_seconds())
                scored.append((delta_seconds, candidate))
            if not scored:
                return {}
            scored.sort(key=lambda pair: pair[0])
            best_delta, best = scored[0]
            second_delta = scored[1][0] if len(scored) > 1 else None
            if best_delta > 15 * 60:
                return {}
            if second_delta is not None and abs(second_delta - best_delta) < 60:
                return {}
            return best

        def _sample_drama_title(item: dict[str, Any], matched_task: dict[str, Any]) -> str:
            title = _valid_publish_title(item.get("title"))
            if title:
                return title
            title = _text(matched_task.get("drama_title"))
            if title:
                return title
            return ""

        def _build_history_sample(day_key: str, item: dict[str, Any]) -> dict[str, Any]:
            task_id = _text(item.get("task_id"))
            matched_task = task_metrics_map.get(day_key, {}).get(task_id, {})
            matched_scope = "样本任务口径"
            if not matched_task:
                matched_task = _find_nearest_task_match(day_key, item)
                matched_scope = "近似匹配任务口径" if matched_task else "未匹配到样本任务"
            line_name = account_line_map.get(_text(item.get("social_id")), "")
            matched_by_task = bool(matched_task)
            return {
                "cache_version": 4,
                "day_key": day_key,
                "available": True,
                "task_id": task_id,
                "account_name": _text(item.get("social_name")) or "未知账号",
                "drama_title": _sample_drama_title(item, matched_task),
                "title": _valid_publish_title(item.get("title")),
                "platform": _text(item.get("social_type") or "FACEBOOK") or "FACEBOOK",
                "line_name": line_name,
                "line_label": LINE_DISPLAY_NAMES.get(line_name) or "待识别线路",
                "view_count": _safe_int(item.get("views")),
                "click_total": _safe_int(matched_task.get("click_total")),
                "income_total": round(_safe_float(matched_task.get("income_total")), 2),
                "share_income_total": round(_safe_float(matched_task.get("share_income_total")), 2),
                "ad_income_total": round(_safe_float(matched_task.get("ad_income_total")), 2),
                "order_amount": round(_safe_float(matched_task.get("order_amount")), 2),
                "like_count": _safe_int(item.get("likes")),
                "comment_count": _safe_int(item.get("comments")),
                "share_count": _safe_int(item.get("shares")),
                "interaction_total": (
                    _safe_int(item.get("likes"))
                    + _safe_int(item.get("comments"))
                    + _safe_int(item.get("shares"))
                ),
                "published_at": _text(item.get("post_date") or item.get("created_at")),
                "copy_text": _text(item.get("text")) or "-",
                "matched_task": matched_by_task,
                "metric_scope": matched_scope,
            }

        start_dt = date.fromisoformat(start_day)
        end_dt = display_end_dt
        rows: list[dict[str, Any]] = []
        backfill_limit = 9999 if force_refresh else 6
        backfill_used = 0
        pending_backfill_days = 0

        current = end_dt
        while current >= start_dt:
            day_key = current.isoformat()
            cached_row = cached_rows.get(day_key) if isinstance(cached_rows.get(day_key), dict) else {}
            use_cached = (
                not force_refresh
                and isinstance(cached_row, dict)
                and _safe_int(cached_row.get("cache_version")) >= 4
            )
            if use_cached:
                row_payload = dict(cached_row)
            else:
                if not force_refresh and backfill_used >= backfill_limit:
                    pending_backfill_days += 1
                    current -= timedelta(days=1)
                    continue
                backfill_used += 1
                analysis_payload = self._fetch_publish_analysis_items(day_key=day_key)
                raw_items = analysis_payload.get("items") if isinstance(analysis_payload.get("items"), list) else []
                items = [item for item in raw_items if isinstance(item, dict)]
                items.sort(
                    key=lambda item: (
                        -_safe_int(item.get("views")),
                        -(_safe_int(item.get("likes")) + _safe_int(item.get("comments")) + _safe_int(item.get("shares"))),
                        _text(item.get("post_date") or item.get("created_at")),
                    )
                )
                samples = [_build_history_sample(day_key, item) for item in items if isinstance(item, dict)]
                top_sample = next((sample for sample in samples if _safe_int(sample.get("view_count")) >= 0), None)
                if top_sample:
                    peak_click_sample = max(
                        samples,
                        key=lambda sample: (
                            _safe_int(sample.get("click_total")),
                            _safe_int(sample.get("view_count")),
                        ),
                    )
                    peak_income_sample = max(
                        samples,
                        key=lambda sample: (
                            _safe_float(sample.get("income_total")),
                            _safe_int(sample.get("view_count")),
                        ),
                    )
                    row_payload = {
                        **dict(top_sample),
                        "peak_click_sample": dict(peak_click_sample),
                        "peak_income_sample": dict(peak_income_sample),
                    }
                else:
                    row_payload = {
                        "cache_version": 4,
                        "day_key": day_key,
                        "available": False,
                    }
                cached_rows[day_key] = dict(row_payload)
                cache_changed = True
            if row_payload.get("available") and _safe_int(row_payload.get("view_count")) > 0:
                rows.append(row_payload)
            current -= timedelta(days=1)

        if cache_changed:
            _json_dump(
                DAILY_TOP_HISTORY_CACHE_PATH,
                {
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "display_end_day": display_end_day,
                    "rows": cached_rows,
                },
            )

        if not rows:
            payload = {
                "available": False,
                "start_day": start_day,
                "end_day": display_end_day,
                "note": f"从 {start_day} 到 {display_end_day} 还没有拉到可展示的最高播放样本。",
                "rows": [],
                "summary_cards": [],
            }
            _json_dump(
                DAILY_TOP_HISTORY_CACHE_PATH,
                {
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "display_end_day": display_end_day,
                    "rows": cached_rows,
                    "payload": payload,
                },
            )
            return self._set_cached_remote(cache_key, 120, payload)

        rows.sort(key=lambda item: _text(item.get("day_key")), reverse=True)
        peak_play = max(rows, key=lambda item: _safe_int(item.get("view_count")))
        peak_click = max(
            [
                item.get("peak_click_sample")
                if isinstance(item.get("peak_click_sample"), dict)
                else item
                for item in rows
            ],
            key=lambda item: _safe_int(item.get("click_total")),
        )
        peak_income = max(
            [
                item.get("peak_income_sample")
                if isinstance(item.get("peak_income_sample"), dict)
                else item
                for item in rows
            ],
            key=lambda item: _safe_float(item.get("income_total")),
        )

        def build_peak_note(item: dict[str, Any], metric_name: str) -> list[str]:
            lines = [
                f"日期：{_text(item.get('day_key')) or '-'}",
                f"线路：{_line_display_name(item.get('line_name'), item.get('line_label')) or '-'}",
                f"账号：{_text(item.get('account_name')) or '-'}",
            ]
            drama_title = _text(item.get("drama_title") or item.get("title"))
            if drama_title:
                lines.append(f"剧名：{drama_title}")
            scope = _text(item.get("metric_scope")) or "未匹配到样本任务"
            lines.append(f"{metric_name}来源：{scope}")
            return lines

        payload = {
            "available": True,
            "start_day": start_day,
            "end_day": display_end_day,
            "total_days": len(rows),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pending_backfill_days": pending_backfill_days,
            "summary_cards": [
                {
                    "label": "有样本天数",
                    "value": len(rows),
                    "kind": "integer",
                    "note": f"{start_day} 到 {display_end_day} 按天取播放最高的一条",
                },
                {
                    "label": "单日最高播放峰值",
                    "value": _safe_int(peak_play.get("view_count")),
                    "kind": "integer",
                    "note_lines": build_peak_note(peak_play, "播放"),
                },
                {
                    "label": "单日最高点击",
                    "value": _safe_int(peak_click.get("click_total")),
                    "kind": "integer",
                    "note_lines": build_peak_note(peak_click, "点击"),
                },
                {
                    "label": "单日最高收益",
                    "value": round(_safe_float(peak_income.get("income_total")), 2),
                    "kind": "money",
                    "note_lines": build_peak_note(peak_income, "收益"),
                },
            ],
            "rows": rows,
            "note": f"还有 {pending_backfill_days} 天历史样本待补拉。" if pending_backfill_days > 0 else "",
        }
        _json_dump(
            DAILY_TOP_HISTORY_CACHE_PATH,
            {
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "display_end_day": display_end_day,
                "rows": cached_rows,
                "payload": payload,
            },
        )
        return self._set_cached_remote(cache_key, 300, payload)

    def _refresh_daily_top_play_history_background(self, *, start_day: str, cache_key: str) -> None:
        try:
            payload = self.get_daily_top_play_history(start_day=start_day, force=True)
            self._set_cached_remote(cache_key, 300, payload)
        except Exception:
            pass
        finally:
            self._background_refreshing.discard(cache_key)

    def _build_line_cumulative_totals_payload(self, *, start_day: str, end_day: str) -> dict[str, Any]:
        line_order = [
            "realtime_day",
            "yourchannel",
            "realtime",
            "recent_order",
            "stardusttv",
            "tag_test",
            "realtime_single",
            "ordinary",
            "fbhot_test",
            "creative_list_day",
            "creative_list",
        ]
        account_groups = self._load_account_groups()
        account_line_map = self._build_account_line_map()
        line_account_counts: dict[str, int] = {}
        for group in account_groups:
            group_key = _text(group.get("key"))
            mapped_line = next((key for key, pool_key in LINE_POOL_KEYS.items() if pool_key == group_key), "")
            if mapped_line:
                line_account_counts[mapped_line] = _safe_int(group.get("count"))

        def _new_bucket(line_name: str, *, label_override: str = "") -> dict[str, Any]:
            return {
                "line_name": line_name,
                "line_label": label_override or LINE_DISPLAY_NAMES.get(line_name) or "待识别线路",
                "account_count": _safe_int(line_account_counts.get(line_name)),
                "post_count": 0,
                "view_total": 0,
                "click_total": 0,
                "income_total": 0.0,
                "interaction_total": 0,
                "like_total": 0,
                "comment_total": 0,
                "share_total": 0,
                "share_income_total": 0.0,
                "ad_income_total": 0.0,
                "order_amount_total": 0.0,
                "matched_task_count": 0,
                "unmatched_task_count": 0,
            }

        buckets: dict[str, dict[str, Any]] = {
            line_name: _new_bucket(line_name)
            for line_name in line_order
        }

        my_task_rows = self._fetch_all_my_task_rows(task_type="1")
        task_line_map = self._build_task_line_map(start_day=start_day, end_day=end_day)
        exact_task_match_count = 0
        publish_fallback_match_count = 0
        unmatched_click_total = 0
        unmatched_income_total = 0.0
        for row in my_task_rows:
            day_key = _text(row.get("actived_at"))[:10]
            if not day_key or day_key < start_day or day_key > end_day:
                continue
            task_metrics = self._extract_my_task_metrics(row)
            task_line = self._resolve_my_task_line(
                row,
                task_line_map=task_line_map,
                account_line_map=account_line_map,
                task_metrics=task_metrics,
            )
            line_name = _text(task_line.get("line_name"))
            if not line_name or line_name not in buckets:
                unmatched_click_total += _safe_int(task_metrics.get("click_total"))
                unmatched_income_total = round(
                    unmatched_income_total + _safe_float(task_metrics.get("income_total")),
                    2,
                )
                continue
            bucket = buckets[line_name]
            bucket["click_total"] += _safe_int(task_metrics.get("click_total"))
            bucket["income_total"] = round(
                _safe_float(bucket.get("income_total"))
                + _safe_float(task_metrics.get("income_total")),
                2,
            )
            bucket["share_income_total"] = round(
                _safe_float(bucket.get("share_income_total"))
                + _safe_float(task_metrics.get("share_income_total")),
                2,
            )
            bucket["ad_income_total"] = round(
                _safe_float(bucket.get("ad_income_total"))
                + _safe_float(task_metrics.get("ad_income_total")),
                2,
            )
            bucket["order_amount_total"] = round(
                _safe_float(bucket.get("order_amount_total"))
                + _safe_float(task_metrics.get("order_amount_total")),
                2,
            )
            bucket["matched_task_count"] += 1
            if _text(task_line.get("matched_by")) == "publish_fallback":
                publish_fallback_match_count += 1
            else:
                exact_task_match_count += 1

        start_date = f"{start_day} 00:00:00"
        end_date = f"{end_day} 23:59:59"
        page_size = 200
        page = 1
        total_count = 0
        partial_note = ""
        while page <= 120:
            body: dict[str, Any] | None = None
            last_error: Exception | None = None
            for _attempt in range(3):
                try:
                    body = require_success(
                        get_publish_analysis(
                            page=page,
                            page_size=page_size,
                            social_type="FACEBOOK",
                            start_date=start_date,
                            end_date=end_date,
                        ),
                        "获取线路累计播放分析明细",
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    time.sleep(1.2)
            if body is None:
                if page > 1:
                    partial_note = f"发布分析在第 {page} 页后中断，本次先展示已成功拉到的累计结果。"
                    break
                raise last_error or RuntimeError("获取线路累计播放分析明细失败")
            page_rows = body.get("items") if isinstance(body.get("items"), list) else []
            total_count = _safe_int((body.get("page") or {}).get("total_count"))
            if not page_rows:
                break
            for item in page_rows:
                if not isinstance(item, dict):
                    continue
                day_key = _text(item.get("post_date") or item.get("created_at"))[:10]
                if not day_key or day_key < start_day or day_key > end_day:
                    continue
                line_name = account_line_map.get(_text(item.get("social_id")), "")
                if not line_name:
                    continue
                bucket = buckets.setdefault(line_name, _new_bucket(line_name))
                view_count = _safe_int(item.get("views"))
                like_count = _safe_int(item.get("likes"))
                comment_count = _safe_int(item.get("comments"))
                share_count = _safe_int(item.get("shares"))
                interaction_total = like_count + comment_count + share_count
                bucket["post_count"] += 1
                bucket["view_total"] += view_count
                bucket["interaction_total"] += interaction_total
                bucket["like_total"] += like_count
                bucket["comment_total"] += comment_count
                bucket["share_total"] += share_count
            if total_count and page * page_size >= total_count:
                break
            page += 1

        candidate_names = [line_name for line_name in line_order if line_name in buckets]

        rows = []
        for line_name in candidate_names:
            bucket = dict(buckets[line_name])
            rows.append(
                {
                    **bucket,
                    "income_total": round(_safe_float(bucket.get("income_total")), 2),
                    "share_income_total": round(_safe_float(bucket.get("share_income_total")), 2),
                    "ad_income_total": round(_safe_float(bucket.get("ad_income_total")), 2),
                    "order_amount_total": round(_safe_float(bucket.get("order_amount_total")), 2),
                }
            )

        rows.sort(
            key=lambda row: (
                -_safe_int(row.get("view_total")),
                -_safe_int(row.get("click_total")),
                -_safe_float(row.get("income_total")),
                row.get("line_label") or "",
            )
        )

        unmatched_note = ""
        if unmatched_click_total > 0 or unmatched_income_total > 0:
            unmatched_note = (
                f" 另有未精确归线的任务数据未计入表格：点击 {unmatched_click_total}，"
                f"总收益 {round(unmatched_income_total, 2):.2f}。"
            )

        return {
            "available": True,
            "start_day": start_day,
            "end_day": end_day,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_rows": len(rows),
            "total_posts": total_count,
            "rows": rows,
            "note": (
                (
                    f"只统计当前线路账号池里现有账号的数据；播放/互动按发布分析明细累计；"
                    f"点击按任务总点击汇总（包含任务各平台点击，YourChannel 会算 TikTok 点击）；"
                    f"收益按分佣+广告+订单汇总；"
                    f"点击/收益优先按归档 task_id 精确映射到线路后再汇总；"
                    f"精确匹配 {exact_task_match_count} 条，发布账号兜底补映射 {publish_fallback_match_count} 条。"
                    f"{unmatched_note} "
                    + partial_note
                ).strip()
                if partial_note
                else (
                    f"只统计当前线路账号池里现有账号的数据；播放/互动按发布分析明细累计；"
                    f"点击按任务总点击汇总（包含任务各平台点击，YourChannel 会算 TikTok 点击）；"
                    f"收益按分佣+广告+订单汇总；"
                    f"点击/收益优先按归档 task_id 精确映射到线路后再汇总；"
                    f"精确匹配 {exact_task_match_count} 条，发布账号兜底补映射 {publish_fallback_match_count} 条。"
                    f"{unmatched_note}"
                )
            ),
            "cache_version": 5,
        }

    def _refresh_line_cumulative_totals_background(self, *, start_day: str, end_day: str, cache_key: str) -> None:
        try:
            payload = self._build_line_cumulative_totals_payload(start_day=start_day, end_day=end_day)
            self._set_cached_remote(cache_key, 600, payload)
            _json_dump(
                LINE_CUMULATIVE_CACHE_PATH,
                {
                    "start_day": start_day,
                    "end_day": end_day,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "payload": payload,
                },
            )
        except Exception:
            pass
        finally:
            self._background_refreshing.discard(cache_key)

    def get_line_cumulative_totals(self, *, start_day: str = DAILY_TOP_HISTORY_START, force: bool = False) -> dict[str, Any]:
        end_day = _today_key()
        cache_key = f"line-cumulative:{start_day}:{end_day}"
        if force:
            self._remote_cache.pop(cache_key, None)

        cached = self._get_cached_remote(cache_key)
        if cached is not None and not force:
            return cached

        persisted = _json_load(LINE_CUMULATIVE_CACHE_PATH)
        persisted_start_day = _text(persisted.get("start_day"))
        persisted_end_day = _text(persisted.get("end_day"))
        persisted_payload = persisted.get("payload") if isinstance(persisted.get("payload"), dict) else {}
        persisted_rows = persisted_payload.get("rows") if isinstance(persisted_payload.get("rows"), list) else []
        persisted_cache_version = _safe_int(persisted_payload.get("cache_version"))
        has_legacy_unmapped = any(
            isinstance(row, dict) and _text(row.get("line_name")) == "unmapped"
            for row in persisted_rows
        )
        persisted_updated_at_raw = _text(persisted.get("updated_at"))
        try:
            persisted_updated_at = datetime.fromisoformat(persisted_updated_at_raw) if persisted_updated_at_raw else None
        except Exception:
            persisted_updated_at = None

        if (
            not force
            and persisted_start_day == start_day
            and persisted_payload
            and not has_legacy_unmapped
        ):
            self._set_cached_remote(cache_key, 600, persisted_payload)
            refresh_needed = persisted_cache_version < 5
            if persisted_end_day != end_day:
                refresh_needed = True
            if persisted_updated_at:
                try:
                    refresh_needed = refresh_needed or (datetime.now() - persisted_updated_at).total_seconds() > 600
                except Exception:
                    refresh_needed = True
            if refresh_needed and cache_key not in self._background_refreshing:
                self._background_refreshing.add(cache_key)
                threading.Thread(
                    target=self._refresh_line_cumulative_totals_background,
                    kwargs={"start_day": start_day, "end_day": end_day, "cache_key": cache_key},
                    daemon=True,
                ).start()
            return persisted_payload

        payload = self._build_line_cumulative_totals_payload(start_day=start_day, end_day=end_day)
        self._set_cached_remote(cache_key, 600, payload)
        _json_dump(
            LINE_CUMULATIVE_CACHE_PATH,
            {
                "start_day": start_day,
                "end_day": end_day,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "payload": payload,
            },
        )
        return payload

    def get_weekly_effect(self, *, days: int = 7, force: bool = False) -> dict[str, Any]:
        return {
            "available": False,
            "days": days,
            "top_accounts": [],
            "top_titles": [],
        }

    def get_trend_analyzer(self, *, refresh: bool = False) -> dict[str, Any]:
        display_end_day = _yesterday_key()
        cache_key = f"trend-analyzer:{display_end_day}"
        persisted = _json_load(TREND_ANALYZER_CACHE_PATH)
        persisted_updated_at_raw = _text(persisted.get("updated_at"))
        persisted_display_end_day = _text(persisted.get("display_end_day"))
        persisted_payload = persisted.get("payload") if isinstance(persisted.get("payload"), dict) else {}
        try:
            persisted_updated_at = datetime.fromisoformat(persisted_updated_at_raw) if persisted_updated_at_raw else None
        except Exception:
            persisted_updated_at = None

        refresh_cutoff = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        needs_daily_refresh = (
            datetime.now() >= refresh_cutoff
            and (
                persisted_display_end_day != display_end_day
                or persisted_updated_at is None
                or persisted_updated_at < refresh_cutoff
            )
        )
        force_refresh = refresh or needs_daily_refresh

        if force_refresh:
            self._remote_cache.pop(cache_key, None)
            self._remote_cache.pop("analysis-report-rows", None)
            self._remote_cache.pop("ai-loop-reporting-p0-summary", None)
        cached = self._get_cached_remote(cache_key)
        if cached is not None and not force_refresh:
            return cached
        if (
            not force_refresh
            and persisted_display_end_day == display_end_day
            and persisted_payload
        ):
            return self._set_cached_remote(cache_key, 300, persisted_payload)

        remote_payload = self._load_ai_loop_reporting_summary(refresh=refresh)
        if remote_payload.get("available") is not False:
            remote_trend = self._build_trend_analyzer_from_ai_loop_reporting(remote_payload)
            if remote_trend.get("available"):
                _json_dump(
                    TREND_ANALYZER_CACHE_PATH,
                    {
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                        "display_end_day": display_end_day,
                        "payload": remote_trend,
                    },
                )
                return self._set_cached_remote(cache_key, 300, remote_trend)

        if (
            persisted_payload
            and _text(persisted_payload.get("source")) == "ai_loop_reporting_p0_summary"
        ):
            stale_payload = dict(persisted_payload)
            remote_note = _text(remote_payload.get("note"))
            stale_payload["latest_note"] = (
                f"{_text(stale_payload.get('latest_note'))}；ai-loop-reporting 本次刷新失败，"
                f"暂时展示上次成功缓存。{remote_note}"
            ).strip("；")
            stale_payload["cache_warning"] = remote_note or "ai-loop-reporting 本次刷新失败，暂时展示上次成功缓存。"
            return self._set_cached_remote(cache_key, 300, stale_payload)

        if (
            persisted_display_end_day == display_end_day
            and persisted_payload
        ):
            return self._set_cached_remote(cache_key, 300, persisted_payload)

        rows = self._load_analysis_report_rows()
        if not rows:
            return {
                "available": False,
                "note": _text(remote_payload.get("note")) or "当前还没有可解析的分析日报文件。",
            }

        latest = rows[0]
        previous = rows[1] if len(rows) > 1 else None
        baseline_rows = [
            row for row in rows
            if TREND_BASELINE_START <= _text(row.get("report_day")) <= TREND_BASELINE_END
        ]
        if not baseline_rows:
            baseline_rows = list(rows)

        def avg(metric: str, bucket_rows: list[dict[str, Any]]) -> float:
            if not bucket_rows:
                return 0.0
            return sum(_safe_float(row.get(metric)) for row in bucket_rows) / len(bucket_rows)

        latest_day = _text(latest.get("report_day"))
        previous_day = _text(previous.get("report_day")) if previous else ""
        running_rows = [
            row for row in rows
            if TREND_RUNNING_START <= _text(row.get("report_day")) <= latest_day
        ]
        if not running_rows:
            running_rows = list(rows)

        def compare_card(label: str, metric: str, kind: str = "integer") -> dict[str, Any]:
            current_value = _safe_float(latest.get(metric))
            previous_value = _safe_float(previous.get(metric)) if previous else 0.0
            delta = current_value - previous_value if previous else None
            delta_pct = None
            if previous and previous_value:
                delta_pct = (delta / previous_value) * 100
            note = f"前一天 {previous_day}: {previous_value:.2f}" if previous else "暂无前一天样本"
            return self._trend_metric_card(
                label=f"单日{label}对比",
                value=current_value,
                kind=kind,
                note=note,
                delta=delta,
                delta_pct=delta_pct,
            )

        baseline_cards = [
            self._trend_metric_card(
                label="全体每日播放平均",
                value=FIXED_BASELINE_CARD_VALUES["全体每日播放平均"],
                kind="number",
                note=f"基线 {TREND_BASELINE_START} 至 {TREND_BASELINE_END} · 样本 {len(baseline_rows)} 天",
            ),
            self._trend_metric_card(
                label="全体每日互动平均",
                value=FIXED_BASELINE_CARD_VALUES["全体每日互动平均"],
                kind="number",
                note="点赞 + 评论 + 分享",
            ),
            self._trend_metric_card(
                label="全体每日发布平均",
                value=FIXED_BASELINE_CARD_VALUES["全体每日发布平均"],
                kind="number",
                note="分析日报总体概览口径",
            ),
            self._trend_metric_card(
                label="全体每日成功平均",
                value=FIXED_BASELINE_CARD_VALUES["全体每日成功平均"],
                kind="number",
                note="当日发布成功数",
            ),
            self._trend_metric_card(
                label="全体每日点击平均",
                value=FIXED_BASELINE_CARD_VALUES["全体每日点击平均"],
                kind="number",
                note="推广链接点击次数",
            ),
            self._trend_metric_card(
                label="全体每日成功率均值",
                value=FIXED_BASELINE_CARD_VALUES["全体每日成功率均值"],
                kind="percent",
                note="成功数 / 发布数",
            ),
        ]
        compare_cards = [
            compare_card("播放", "view_total"),
            compare_card("互动", "interaction_total"),
            compare_card("发布", "publish_count"),
            compare_card("成功", "success_count"),
            compare_card("点击", "click_total"),
            compare_card("成功率", "success_rate", "percent"),
        ]
        has_running_window = bool(latest_day and latest_day >= TREND_RUNNING_START)
        running_average_title = (
            f"从 {TREND_RUNNING_START} 到 {latest_day} 的均值"
            if has_running_window
            else f"从 {TREND_RUNNING_START} 到前一天的均值"
        )
        if has_running_window:
            running_label_suffix = latest_day or "前一天"
            running_average_cards = [
                self._trend_metric_card(
                    label=f"6月9号到{running_label_suffix}平均播放",
                    value=avg("view_total", running_rows),
                    kind="integer",
                    note=f"{TREND_RUNNING_START} 至 {latest_day} · 样本 {len(running_rows)} 天",
                ),
                self._trend_metric_card(
                    label=f"6月9号到{running_label_suffix}平均互动",
                    value=avg("interaction_total", running_rows),
                    kind="integer",
                    note="点赞 + 评论 + 分享",
                ),
                self._trend_metric_card(
                    label=f"6月9号到{running_label_suffix}平均发布",
                    value=avg("publish_count", running_rows),
                    kind="integer",
                    note="总体概览日报口径",
                ),
                self._trend_metric_card(
                    label=f"6月9号到{running_label_suffix}平均点击",
                    value=avg("click_total", running_rows),
                    kind="integer",
                    note="推广链接点击次数",
                ),
            ]
        else:
            running_average_cards = []
        daily_rows = [
            {
                "day": _text(row.get("report_day")),
                "publish_count": _safe_int(row.get("publish_count")),
                "success_count": _safe_int(row.get("success_count")),
                "failed_count": _safe_int(row.get("failed_count")),
                "view_total": _safe_int(row.get("view_total")),
                "click_total": _safe_int(row.get("click_total")),
                "interaction_total": _safe_int(row.get("interaction_total")),
                "success_rate": round(_safe_float(row.get("success_rate")), 2),
            }
            for row in rows
        ]
        return {
            "available": True,
            "source": "analysis_daily_markdown",
            "baseline_start": TREND_BASELINE_START,
            "baseline_end": TREND_BASELINE_END,
            "baseline_days": len(baseline_rows),
            "latest_day": latest_day,
            "previous_day": previous_day,
            "latest_generated_at": _text(latest.get("generated_at")),
            "latest_summary": (_text(latest.get("summary_lines")[0]) if latest.get("summary_lines") else ""),
            "latest_file_name": _text(latest.get("file_name")),
            "latest_note": f"最新日报生成于 {latest.get('generated_at') or '-'}，统计的是 {latest_day} 的数据",
            "baseline_cards": baseline_cards,
            "compare_cards": compare_cards,
            "running_average_title": running_average_title,
            "running_average_cards": running_average_cards,
            "daily_rows": daily_rows,
            "running_average_note": (
                f"当前本地日报只统计到 {latest_day}，6月9号之后的全体均值需要 ai-loop-reporting 汇总。"
                if not has_running_window
                else ""
            ),
        }

    def get_overview(self, *, days: int = 30, include_today_top_play: bool = True) -> dict[str, Any]:
        rounds = self._filtered_rounds(days=days)
        requested = sum(row.requested_count for row in rounds)
        success = sum(row.success_count for row in rounds)
        failed = sum(row.failed_count for row in rounds)
        processing = sum(row.processing_count for row in rounds)
        unsubmitted = sum(row.unsubmitted_count for row in rounds)
        all_days = sorted({row.day_key for row in rounds}, reverse=True)
        last_exported_at = max((row.exported_at for row in rounds if row.exported_at), default="")
        breakdown = _empty_unsubmitted_breakdown()
        for row in rounds:
            _merge_unsubmitted_breakdown(breakdown, _classify_unsubmitted_breakdown(row))
        lines = self._aggregate_line_rows(rounds)
        top_problem_rounds = sorted(
            [
                {
                    "archive_key": row.archive_key,
                    "day_key": row.day_key,
                    "runtime_mode": row.runtime_mode,
                    "line_name": row.line_name,
                    "round_name": row.round_name,
                    "label": row.label,
                    "success_count": row.success_count,
                    "failed_count": row.failed_count,
                    "unsubmitted_count": row.unsubmitted_count,
                    "status": row.status,
                    "note": row.note,
                    "unsubmitted_breakdown": _classify_unsubmitted_breakdown(row),
                    "unsubmitted_summary": _classify_unsubmitted_breakdown(row).get("summary") or "-",
                }
                for row in rounds
                if row.failed_count > 0 or row.unsubmitted_count > 0 or row.processing_count > 0 or row.status != "done"
            ],
            key=lambda item: (-(item["failed_count"] + item["unsubmitted_count"] + 0.5 * item.get("processing_count", 0)), item["day_key"]),
        )[:8]
        failure_counter: Counter[str] = Counter()
        for row in rounds:
            for item in row.items:
                reason = _text(item.get("failure_reason"))
                if reason:
                    failure_counter[reason] += 1
        top_failures = [
            {"failure_reason": reason, "count": count}
            for reason, count in failure_counter.most_common(8)
        ]
        overall_summary = self._build_overall_summary(rounds)
        account_groups = self._load_account_groups()
        loop_overview = self.get_loop_overview(refresh=False)
        historical_daily_report = {
            "available": False,
            "note": "当前本地没有可直接展示的分析日报汇总。",
        }
        today_top_play = self.get_today_top_play(force=False) if include_today_top_play else None
        return {
            "db_path": str(self.runtime_root),
            "window_days": days,
            "last_exported_at": last_exported_at,
            "kpis": {
                "round_count": len(rounds),
                "item_count": requested,
                "requested_count": requested,
                "success_count": success,
                "failed_count": failed,
                "processing_count": processing,
                "unsubmitted_count": unsubmitted,
                "day_count": len(all_days),
                "success_rate": round((success / requested) * 100, 2) if requested else 0.0,
            },
            "lines": lines,
            "unsubmitted_breakdown": breakdown,
            "top_failures": top_failures,
            "top_problem_rounds": top_problem_rounds,
            "overall_summary": overall_summary,
            "account_groups": account_groups,
            "loop_overview": loop_overview,
            "historical_daily_report": historical_daily_report,
            "trend_analyzer": self.get_trend_analyzer(refresh=False),
            "today_top_play": today_top_play,
            "daily_top_history": self.get_daily_top_play_history(force=False),
        }

    def get_realtime_overview(self, *, days: int = 30, include_today_top_play: bool = True, refresh: bool = False) -> dict[str, Any]:
        cache_key = f"realtime-overview:{days}:{int(include_today_top_play)}:{date.today().isoformat()}"
        if refresh:
            self._remote_cache.pop(cache_key, None)
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            return cached

        rounds = self._filtered_rounds(days=days)
        last_exported_at = max((row.exported_at for row in rounds if row.exported_at), default="")
        overall_summary = self._build_overall_summary(rounds)
        loop_overview = self.get_loop_overview(refresh=refresh)
        today_top_play = self.get_today_top_play(force=False) if include_today_top_play else None
        account_groups = self._load_account_groups()
        requested = sum(row.requested_count for row in rounds)
        success = sum(row.success_count for row in rounds)
        failed = sum(row.failed_count for row in rounds)
        processing = sum(row.processing_count for row in rounds)
        unsubmitted = sum(row.unsubmitted_count for row in rounds)
        all_days = sorted({row.day_key for row in rounds}, reverse=True)
        return self._set_cached_remote(cache_key, 20, {
            "db_path": str(self.runtime_root),
            "window_days": days,
            "last_exported_at": last_exported_at,
            "kpis": {
                "round_count": len(rounds),
                "requested_count": requested,
                "success_count": success,
                "failed_count": failed,
                "processing_count": processing,
                "unsubmitted_count": unsubmitted,
                "day_count": len(all_days),
                "success_rate": round((success / requested) * 100, 2) if requested else 0.0,
            },
            "overall_summary": overall_summary,
            "loop_overview": loop_overview,
            "today_top_play": today_top_play,
            "account_groups": account_groups,
        })

    def get_trends(self, *, days: int = 30) -> dict[str, Any]:
        rounds = self._filtered_rounds(days=days)
        by_day: dict[str, dict[str, Any]] = {}
        for row in rounds:
            bucket = by_day.setdefault(
                row.day_key,
                {
                    "day_key": row.day_key,
                    "requested_count": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "processing_count": 0,
                    "unsubmitted_count": 0,
                },
            )
            bucket["requested_count"] += row.requested_count
            bucket["success_count"] += row.success_count
            bucket["failed_count"] += row.failed_count
            bucket["processing_count"] += row.processing_count
            bucket["unsubmitted_count"] += row.unsubmitted_count
        daily = []
        for day_key in sorted(by_day.keys()):
            row = by_day[day_key]
            breakdown = _empty_unsubmitted_breakdown()
            for archive in rounds:
                if archive.day_key == day_key:
                    _merge_unsubmitted_breakdown(breakdown, _classify_unsubmitted_breakdown(archive))
            row["unsubmitted_breakdown"] = breakdown
            row["unsubmitted_summary"] = breakdown.get("summary") or "-"
            daily.append(row)
        return {"days": days, "daily": daily, "by_line": []}

    def get_failures(self, *, limit: int = 50, refresh: bool = False) -> dict[str, Any]:
        cache_key = f"failures:{limit}:{date.today().isoformat()}"
        if refresh:
            self._remote_cache.pop(cache_key, None)
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            return cached

        rounds = self._scan_round_archives()
        failure_counter: Counter[str] = Counter()
        recent_failed: list[dict[str, Any]] = []
        for row in rounds:
            for item in row.items:
                reason = _text(item.get("failure_reason"))
                status = _text(item.get("publish_status"))
                if reason:
                    failure_counter[reason] += 1
                if reason or status == "failed":
                    recent_failed.append(
                        {
                            "archive_key": row.archive_key,
                            "day_key": row.day_key,
                            "exported_at": row.exported_at,
                            "runtime_mode": row.runtime_mode,
                            "line_name": row.line_name,
                            "round_name": row.round_name,
                            "item_index": item.get("item_index"),
                            "account_name": item.get("account_name"),
                            "title": item.get("title"),
                            "app_id": item.get("app_id"),
                            "failure_reason": reason,
                            "publish_status": status,
                        }
                    )
        top_reasons = [{"failure_reason": reason, "count": count} for reason, count in failure_counter.most_common(limit)]
        return self._set_cached_remote(cache_key, 20, {"top_reasons": top_reasons, "recent_failed": recent_failed[:limit]})

    def get_accounts(self, *, limit: int = 50) -> dict[str, Any]:
        buckets: dict[str, dict[str, Any]] = {}
        for row in self._scan_round_archives():
            for item in row.items:
                name = _text(item.get("account_name")) or "-"
                bucket = buckets.setdefault(
                    name,
                    {
                        "account_name": name,
                        "account_id": _text(item.get("account_id")),
                        "total_tasks": 0,
                        "success_count": 0,
                        "failed_count": 0,
                        "round_count": 0,
                    },
                )
                bucket["total_tasks"] += 1
                bucket["round_count"] += 1
                kind = _classify_item(item)
                if kind == "success":
                    bucket["success_count"] += 1
                elif kind == "failed":
                    bucket["failed_count"] += 1
        rows = sorted(buckets.values(), key=lambda item: (-item["total_tasks"], item["account_name"]))[:limit]
        for row in rows:
            row["success_rate"] = round((row["success_count"] / row["total_tasks"]) * 100, 2) if row["total_tasks"] else 0.0
        return {"items": rows}

    def list_rounds(
        self,
        *,
        day_key: str = "",
        runtime_mode: str = "",
        line_name: str = "",
        status: str = "",
        search: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        rows = self._scan_round_archives()
        def match(row: RoundArchive) -> bool:
            blob = " ".join([row.archive_key, row.label, row.round_name, row.note, row.pool_name]).lower()
            if day_key and row.day_key != day_key:
                return False
            if runtime_mode and row.runtime_mode != runtime_mode:
                return False
            if line_name and row.line_name != line_name:
                return False
            if status and row.status != status:
                return False
            if search and search.lower() not in blob:
                return False
            return True
        filtered = [row for row in rows if match(row)]
        total = len(filtered)
        limit = max(1, min(500, int(limit or 100)))
        offset = max(0, int(offset or 0))
        page = filtered[offset : offset + limit]
        items = []
        for row in page:
            breakdown = _classify_unsubmitted_breakdown(row)
            judgement = _build_round_judgement(row)
            items.append(
                {
                    "archive_key": row.archive_key,
                    "day_key": row.day_key,
                    "runtime_mode": row.runtime_mode,
                    "line_name": row.line_name,
                    "round_name": row.round_name,
                    "label": row.label,
                    "platform": row.platform,
                    "pool_name": row.pool_name,
                    "requested_count": row.requested_count,
                    "planned_count": row.planned_count,
                    "success_count": row.success_count,
                    "failed_count": row.failed_count,
                    "processing_count": row.processing_count,
                    "unsubmitted_count": row.unsubmitted_count,
                    "status": row.status,
                    "status_label": row.status_label,
                    "note": row.note,
                    "report_markdown_path": row.report_markdown_path,
                    "export_dir": row.export_dir,
                    "exported_at": row.exported_at,
                    "round_json_path": row.round_json_path,
                    "summary_path": row.summary_path,
                    "log_snapshot_path": row.log_snapshot_path,
                    "account_pool_snapshot_path": row.account_pool_snapshot_path,
                    "config_snapshot_path": row.config_snapshot_path,
                    "flywheel_config": row.flywheel_config,
                    "unsubmitted_breakdown": breakdown,
                    "unsubmitted_summary": breakdown.get("summary") or "-",
                    "judgement_label": judgement["judgement_label"],
                    "judgement_tone": judgement["judgement_tone"],
                    "primary_issue": judgement["primary_issue"],
                }
            )
        return {"total": total, "limit": limit, "offset": offset, "items": items}

    def get_options(self) -> dict[str, Any]:
        rows = self._scan_round_archives()
        return {
            "days": sorted({row.day_key for row in rows}, reverse=True),
            "runtime_modes": sorted({row.runtime_mode for row in rows}),
            "lines": sorted({row.line_name for row in rows}),
            "statuses": sorted({row.status for row in rows}),
        }

    def get_round_detail(self, archive_key: str) -> dict[str, Any]:
        archive = next((row for row in self._scan_round_archives() if row.archive_key == archive_key), None)
        if archive is None:
            raise KeyError(archive_key)
        breakdown = _classify_unsubmitted_breakdown(archive)
        excerpt = {
            "success_videos": [
                {"账号": item.get("account_name"), "剧目": item.get("title"), "状态": item.get("publish_status")}
                for item in archive.items
                if _classify_item(item) == "success"
            ][:6],
            "failed_tasks": [
                {"账号": item.get("account_name"), "剧目": item.get("title"), "失败": item.get("failure_reason")}
                for item in archive.items
                if _classify_item(item) == "failed"
            ][:6],
        }
        archive_data = {
            "archive_key": archive.archive_key,
            "day_key": archive.day_key,
            "runtime_mode": archive.runtime_mode,
            "line_name": archive.line_name,
            "round_name": archive.round_name,
            "label": archive.label,
            "platform": archive.platform,
            "pool_name": archive.pool_name,
            "requested_count": archive.requested_count,
            "planned_count": archive.planned_count,
            "success_count": archive.success_count,
            "failed_count": archive.failed_count,
            "processing_count": archive.processing_count,
            "unsubmitted_count": archive.unsubmitted_count,
            "status": archive.status,
            "status_label": archive.status_label,
            "note": archive.note,
            "report_markdown_path": archive.report_markdown_path,
            "export_dir": archive.export_dir,
            "exported_at": archive.exported_at,
            "round_json_path": archive.round_json_path,
            "summary_path": archive.summary_path,
            "log_snapshot_path": archive.log_snapshot_path,
            "account_pool_snapshot_path": archive.account_pool_snapshot_path,
            "config_snapshot_path": archive.config_snapshot_path,
            "flywheel_config": archive.flywheel_config,
        }
        return {
            "archive": archive_data,
            "items": archive.items,
            "unsubmitted_breakdown": breakdown,
            "report_excerpt": excerpt,
        }
