from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
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

LINE_LABELS = {
    "ordinary": "普通池",
    "realtime": "实时榜",
    "fbhot_test": "FB 热度加权",
    "realtime_day": "白天实时榜",
    "creative_list": "创意列表映射",
    "creative_list_day": "白天创意列表映射",
    "realtime_single": "实时榜定账号",
    "yourchannel": "YourChannel",
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
}

ACCOUNT_GROUP_META = {
    "facebook_drama_realtime_pool": {
        "label": "实时榜账号池",
        "description": "夜间实时榜线专用池，当前固定 30 个账号，承接实时榜外部素材发布。",
    },
    "facebook_drama_realtime_day_pool": {
        "label": "白天实时榜账号池",
        "description": "白天实时榜线专用池，按 12:00-18:00 手动窗口运行。",
    },
    "facebook_drama_realtime_single_pool": {
        "label": "实时榜定账号池",
        "description": "夜间定账号实时榜线，单素材绑定单账号连续消耗。",
    },
    "facebook_drama_creative_list_pool": {
        "label": "创意列表映射账号池",
        "description": "夜间创意列表外部素材映射线专用池。",
    },
    "facebook_drama_creative_list_day_pool": {
        "label": "白天创意列表映射账号池",
        "description": "白天创意列表外部素材映射线专用池，按 12:00-18:00 手动窗口运行。",
    },
    "facebook_drama_ordinary_pool": {
        "label": "普通池账号池",
        "description": "普通池线专用池，主要承接官方短剧稳定补量。",
    },
    "facebook_drama_fbhot_test_pool": {
        "label": "热测线账号池",
        "description": "FB 热测线实验池，用来测试热度优先策略。",
    },
    "facebook_drama_yourchannel_pool": {
        "label": "YourChannel 剧场线账号池",
        "description": "YourChannel 剧场线专用池，使用白名单剧名和剧场发布策略。",
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
    "ordinary": "普通池线",
    "realtime": "实时榜线",
    "realtime_day": "白天实时榜线",
    "realtime_single": "夜间实时榜定账号线",
    "creative_list": "创意列表外部素材映射线",
    "creative_list_day": "白天创意列表外部素材映射线",
    "fbhot_test": "FB 热度加权线",
    "yourchannel": "YourChannel 剧场线",
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


def _json_load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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


def _report_path(runtime_mode: str, day_key: str, line_name: str, round_name: str) -> Path | None:
    if runtime_mode != "continuous":
        return None
    base = REPORT_CONTINUOUS_ROOT / day_key / line_name / round_name
    if not base.exists():
        return None
    candidates = sorted(base.glob("*.md"))
    return candidates[0] if candidates else None


class TestPoolDashboardService:
    def __init__(self) -> None:
        self.runtime_root = RUNTIME_ROOT
        self.db_path = CONTINUOUS_ROOT
        self._cache_expires_at = 0.0
        self._cache: list[RoundArchive] = []
        self._remote_cache: dict[str, tuple[float, dict[str, Any]]] = {}

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

    def _fetch_publish_analysis_metrics(self, *, start_date: str = "", end_date: str = "") -> dict[str, Any]:
        cache_key = f"publish:{start_date}:{end_date}"
        ttl = 25 if start_date or end_date else 1800
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
        return self._set_cached_remote(cache_key, 25, payload)

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

    def _aggregate_my_task_metrics(self, rows: list[dict[str, Any]], *, day_key: str = "") -> dict[str, Any]:
        click_total = 0
        share_total = 0.0
        ad_total = 0.0
        click_task_count = 0
        for row in rows:
            active_day = _text(row.get("actived_at"))[:10]
            if day_key and active_day != day_key:
                continue
            platform_rows = row.get("platform_list") if isinstance(row.get("platform_list"), list) else []
            facebook_row = next(
                (
                    item for item in platform_rows
                    if isinstance(item, dict) and _safe_int(item.get("platform")) == 2
                ),
                {},
            )
            platform_click = _safe_int(facebook_row.get("click_count"))
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

    def _external_summary_metrics(self, *, today_key: str) -> dict[str, Any]:
        cache_key = f"dashboard-summary:{today_key}"
        cached = self._get_cached_remote(cache_key)
        if cached is not None:
            return cached

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
            metrics["today_my_task"] = self._aggregate_my_task_metrics(my_task_rows, day_key=today_key)
        except Exception:
            pass
        return self._set_cached_remote(cache_key, 25, metrics)

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
        today_my_task = external.get("today_my_task") if isinstance(external.get("today_my_task"), dict) else {}
        requested_today_real = _safe_int(today_records.get("requested_count"), requested_today)
        success_today_real = _safe_int(today_publish.get("success_count"), _safe_int(today_records.get("success_count"), success_today))
        failed_today_real = max(0, requested_today_real - success_today_real)

        return {
            "summary_day_key": today_key,
            "today_metrics_day_key": today_metrics_day_key,
            "publish_account_total": total_unique_accounts,
            "used_pool_account_count": used_pool_account_count,
            "reserve_accounts": reserve_accounts,
            "total_line_count": len([key for key in LINE_POOL_KEYS if key != "novel"]),
            "overall_view_total": _safe_int(overall_publish.get("view_total")),
            "overall_click_total": _safe_int(overall_my_task.get("click_total")),
            "overall_click_task_count": _safe_int(overall_my_task.get("click_task_count")),
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

    def get_loop_overview(self) -> dict[str, Any]:
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
                    "last_update": latest.exported_at if latest else "",
                    "latest_round": latest.round_name if latest else "",
                    "runtime_state": latest.status_label if latest else "未运行",
                    "note": latest.note if latest else "",
                    "is_running": bool(latest and (latest.processing_count > 0 or latest.status == "processing")),
                }
            )
        return {
            "today_key": today_key,
            "window_summary": {
                "night_range": "18:00-次日12:00",
                "day_range": "12:00-18:00",
            },
            "line_targets": line_targets,
        }

    def get_today_top_play(self, *, force: bool = False) -> dict[str, Any]:
        today_key, _ = self._select_today_rounds()
        return {
            "available": False,
            "day_key": today_key,
            "items": [],
            "note": "当前这份本地归档里没有播放回收明细，先保留板块结构。",
        }

    def get_weekly_effect(self, *, days: int = 7, force: bool = False) -> dict[str, Any]:
        return {
            "available": False,
            "days": days,
            "top_accounts": [],
            "top_titles": [],
        }

    def get_trend_analyzer(self, *, refresh: bool = False) -> dict[str, Any]:
        return {
            "available": False,
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
        loop_overview = self.get_loop_overview()
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
        }

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

    def get_failures(self, *, limit: int = 50) -> dict[str, Any]:
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
        return {"top_reasons": top_reasons, "recent_failed": recent_failed[:limit]}

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
