#!/usr/bin/env python3
"""Summarize video_pipeline_tasks metrics from the dashboard API or a JSON file."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_API_BASE = os.getenv("AI_LOOP_DASHBOARD_API", "http://124.174.76.6")

FIELD_LABELS = {
    "date": "日期",
    "short_link_publish_time": "矩阵的发布时间",
    "assignee": "负责人（人员）",
    "task_id": "task_id",
    "douyin_t8_account": "FB账号昵称",
    "channel_id": "channel_id",
    "account_type": "账号类型",
    "clip_tool": "剪辑工具",
    "drama_name": "选剧名称",
    "drama_timestamp": "选剧时间戳",
    "preview_duration_sec": "原视频时长(s)",
    "preview_size_mb": "原视频大小(MB)",
    "material_source": "素材来源",
    "clip_start_time": "剪辑开始时间",
    "clip_end_time": "剪辑结束时间",
    "clip_duration_sec": "剪辑耗时(s)",
    "clip_params": "剪辑参数",
    "output_duration_sec": "产物时长(s)",
    "output_size_mb": "产物文件大小(MB)",
    "output_quality": "产物清晰度/码率",
    "upload_start_time": "上传开始时间",
    "upload_end_time": "上传结束时间",
    "upload_duration_sec": "上传耗时(s)",
    "upload_retry_count": "上传重试次数",
    "publish_req_start_time": "发布请求开始时间",
    "publish_req_end_time": "发布请求结束时间",
    "publish_duration_sec": "发布耗时(s)",
    "social_post_id": "social_post_id",
    "publish_status": "发布状态",
    "fail_stage": "失败阶段",
    "publish_fail_reason": "发布失败原因",
    "retry_count": "重试次数",
    "update_time": "更新时间(执行完成时间)",
    "clip_fail_reason": "剪辑失败原因",
}

NUMERIC_FIELDS = {
    "preview_duration_sec",
    "preview_size_mb",
    "clip_duration_sec",
    "output_duration_sec",
    "output_size_mb",
    "upload_duration_sec",
    "upload_retry_count",
    "publish_duration_sec",
    "retry_count",
}


def text(value: Any) -> str:
    return str(value or "").strip()


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def rate(numerator: int | float, denominator: int | float) -> float:
    return round((float(numerator) / float(denominator) * 100), 2) if denominator else 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = (len(values) - 1) * p
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return round(values[int(index)], 3)
    return round(values[lower] * (upper - index) + values[upper] * (index - lower), 3)


def numeric_summary(values: list[Any]) -> dict[str, Any]:
    nums = [v for v in (to_float(value) for value in values) if v is not None]
    if not nums:
        return {"count": 0, "avg": 0, "min": 0, "p50": 0, "p90": 0, "max": 0}
    return {
        "count": len(nums),
        "avg": round(sum(nums) / len(nums), 3),
        "min": round(min(nums), 3),
        "p50": percentile(nums, 0.5),
        "p90": percentile(nums, 0.9),
        "max": round(max(nums), 3),
    }


def parse_jsonish(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    raw = text(value)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def extract_strategy_context(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    params = parse_jsonish(row.get("clip_params"))
    context = params.get("strategy_context")
    if isinstance(context, dict):
        return {str(k): v for k, v in context.items() if isinstance(v, dict)}
    # Steven historical rows have AB group but not exact strategy codes.
    if row.get("ab_group"):
        return {
            "clip": {
                "strategy_type": "clip",
                "strategy_code": text(row.get("ab_group")),
                "strategy_name": "A/B 剪辑实验",
            }
        }
    return {}


def fetch_table(api_base: str, table: str, *, page_size: int, max_rows: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        limit = min(page_size, max_rows - len(rows)) if max_rows else page_size
        if limit <= 0:
            break
        query = urllib.parse.urlencode({"limit": limit, "offset": offset})
        url = f"{api_base.rstrip('/')}/api/table/{urllib.parse.quote(table)}?{query}"
        with urllib.request.urlopen(url, timeout=90) as resp:
            payload = json.load(resp)
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error") or payload)
        batch = [row for row in payload.get("rows") or [] if isinstance(row, dict)]
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += len(batch)
        if max_rows and len(rows) >= max_rows:
            break
    return rows


def load_input(path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        rows = data["rows"]
    elif isinstance(data, list):
        rows = data
    else:
        raise SystemExit("input JSON must be a list or {'rows': [...]}")
    return [row for row in rows if isinstance(row, dict)]


def in_range(row: dict[str, Any], date_from: str, date_to: str) -> bool:
    value = text(row.get("date") or row.get("short_link_publish_time") or row.get("update_time"))
    day = value[:10]
    if date_from and day < date_from:
        return False
    if date_to and day > date_to:
        return False
    return True


def filter_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if args.owner and text(row.get("assignee")) != args.owner:
            continue
        if args.loop_name:
            params = parse_jsonish(row.get("clip_params"))
            loop_name = text(params.get("loop_name"))
            if not loop_name:
                loop_name = "steven-jiao-ai-loop" if text(row.get("task_id")).startswith("steven_jiao:") else ""
            if loop_name != args.loop_name:
                continue
        if args.date_from or args.date_to:
            if not in_range(row, args.date_from, args.date_to):
                continue
        out.append(row)
    return out


def status_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counter = Counter(text(row.get("publish_status")) or "unknown" for row in rows)
    total = len(rows)
    success = counter.get("success", 0)
    failed = counter.get("failed", 0)
    reviewing = counter.get("reviewing", 0)
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "reviewing": reviewing,
        "other": total - success - failed - reviewing,
        "success_rate": rate(success, total),
        "failed_rate": rate(failed, total),
        "status_distribution": dict(counter.most_common()),
    }


def group_metrics(rows: list[dict[str, Any]], field: str, top: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = text(row.get(field)) or "unknown"
        groups[key].append(row)
    output = []
    for key, items in groups.items():
        metrics = status_metrics(items)
        output.append({"key": key, **metrics})
    output.sort(key=lambda item: (item["total"], item["success"], -item["failed"]), reverse=True)
    return output[:top]


def strategy_metrics(rows: list[dict[str, Any]], top: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        context = extract_strategy_context(row)
        for strategy_type, item in context.items():
            code = text(item.get("strategy_code"))
            if not code:
                continue
            name = text(item.get("strategy_name")) or code
            groups[(strategy_type, code, name)].append(row)
    output = []
    for (strategy_type, code, name), items in groups.items():
        output.append({
            "strategy_type": strategy_type,
            "strategy_code": code,
            "strategy_name": name,
            **status_metrics(items),
        })
    output.sort(key=lambda item: (item["total"], item["success_rate"], item["success"]), reverse=True)
    return output[:top]


def completeness(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = len(rows)
    output = []
    for field, label in FIELD_LABELS.items():
        filled = sum(1 for row in rows if has_value(row.get(field)))
        output.append({
            "field": field,
            "label": label,
            "filled": filled,
            "missing": total - filled,
            "filled_rate": rate(filled, total),
        })
    output.sort(key=lambda item: (item["filled_rate"], item["field"]))
    return output


def build_summary(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    filtered = filter_rows(rows, args)
    numeric = {field: numeric_summary([row.get(field) for row in filtered]) for field in sorted(NUMERIC_FIELDS)}
    fail_reason_rows = [row for row in filtered if text(row.get("publish_fail_reason"))]
    fail_stage_rows = [row for row in filtered if text(row.get("fail_stage"))]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": args.input or f"{args.api_base.rstrip('/')}/api/table/video_pipeline_tasks",
        "filters": {
            "owner": args.owner,
            "loop_name": args.loop_name,
            "date_from": args.date_from,
            "date_to": args.date_to,
        },
        "rows_loaded": len(rows),
        "rows_matched": len(filtered),
        "overall": status_metrics(filtered),
        "field_completeness": completeness(filtered),
        "numeric_metrics": numeric,
        "by_owner": group_metrics(filtered, "assignee", args.top),
        "by_account": group_metrics(filtered, "douyin_t8_account", args.top),
        "by_ab_group": group_metrics(filtered, "ab_group", args.top),
        "by_fail_stage": group_metrics(fail_stage_rows, "fail_stage", args.top),
        "fail_reasons": [
            {"reason": reason, "count": count}
            for reason, count in Counter(text(row.get("publish_fail_reason")) for row in fail_reason_rows).most_common(args.top)
        ],
        "by_strategy": strategy_metrics(filtered, args.top),
    }


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def render_markdown(summary: dict[str, Any]) -> str:
    overall = summary["overall"]
    lines = [
        f"# Video Pipeline 统计报告",
        "",
        f"- 生成时间：{summary['generated_at']}",
        f"- 读取行数：{summary['rows_loaded']}",
        f"- 命中行数：{summary['rows_matched']}",
        f"- 成功率：{overall['success_rate']}%（成功 {overall['success']} / 总数 {overall['total']}）",
        f"- 失败率：{overall['failed_rate']}%（失败 {overall['failed']}）",
        "",
        "## 字段完整度最低项",
        md_table(
            ["字段", "中文名", "有值", "缺失", "完整率"],
            [[item["field"], item["label"], item["filled"], item["missing"], f"{item['filled_rate']}%"] for item in summary["field_completeness"][:12]],
        ),
        "",
        "## 负责人 Top",
        md_table(
            ["负责人", "总数", "成功", "失败", "成功率"],
            [[item["key"], item["total"], item["success"], item["failed"], f"{item['success_rate']}%"] for item in summary["by_owner"]],
        ),
        "",
        "## 策略 Top",
        md_table(
            ["类型", "策略", "名称", "总数", "成功", "失败", "成功率"],
            [[item["strategy_type"], item["strategy_code"], item["strategy_name"], item["total"], item["success"], item["failed"], f"{item['success_rate']}%"] for item in summary["by_strategy"]],
        ),
        "",
        "## 失败原因 Top",
        md_table(
            ["失败原因", "次数"],
            [[item["reason"], item["count"]] for item in summary["fail_reasons"]],
        ),
        "",
        "## 耗时/数值指标",
        md_table(
            ["字段", "数量", "平均", "P50", "P90", "最大"],
            [[field, metric["count"], metric["avg"], metric["p50"], metric["p90"], metric["max"]] for field, metric in summary["numeric_metrics"].items()],
        ),
    ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize video_pipeline_tasks field completeness and business metrics")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--input", default="", help="Optional JSON file instead of API")
    parser.add_argument("--owner", default="")
    parser.add_argument("--loop-name", default="")
    parser.add_argument("--date-from", default="")
    parser.add_argument("--date-to", default="")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-rows", type=int, default=100000)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("-o", "--output", default="")
    args = parser.parse_args()

    rows = load_input(args.input) if args.input else fetch_table(args.api_base, "video_pipeline_tasks", page_size=args.page_size, max_rows=args.max_rows)
    summary = build_summary(rows, args)
    content = json.dumps(summary, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else render_markdown(summary)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(content, encoding="utf-8")
    sys.stdout.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
