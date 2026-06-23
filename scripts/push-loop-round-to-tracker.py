#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
TRACKER_PUSH_SCRIPT = ROOT_DIR / "tools" / "video-pipeline-tracker" / "scripts" / "push_loop_result.py"

LINE_LABELS = {
    "realtime": "实时榜线",
    "realtime_single": "实时榜定账号线",
    "realtime_day": "白天实时榜线",
    "creative_list": "创意列表映射线",
    "creative_list_day": "白天创意列表映射线",
    "ordinary": "普通池线",
    "fbhot_test": "FB 热测线",
    "yourchannel": "YourChannel 线",
    "recent_order": "近月出单剧线",
    "stardusttv": "StardustTV 线",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _business_date_from_path(path: Path) -> str:
    for part in reversed(path.parts):
        if len(part) == 10 and part[4] == "-" and part[7] == "-":
            return part
    return datetime.now().strftime("%Y-%m-%d")


def _stable_task_id(
    *,
    loop_name: str,
    date: str,
    line_name: str,
    round_name: str,
    index: int,
    account: dict[str, Any],
    drama: dict[str, Any],
    episode: dict[str, Any],
) -> str:
    seed = {
        "loop_name": loop_name,
        "date": date,
        "line_name": line_name,
        "round_name": round_name,
        "index": index,
        "account_id": _text(account.get("account_id")),
        "team_id": _text(account.get("team_id")),
        "drama_task_id": _text(drama.get("task_id")),
        "serial_id": _text(drama.get("serial_id")),
        "episode_order": _text(episode.get("episode_order")),
    }
    digest = hashlib.sha1(json.dumps(seed, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"{loop_name}:{date}:{line_name}:{round_name}:{index}:{digest}"


def _publish_status(item: dict[str, Any], detail: dict[str, Any]) -> str:
    outcome = _text(detail.get("发布情况") or detail.get("状态") or item.get("publish_status"))
    if outcome in {"发布成功", "success", "成功"}:
        return "success"
    if outcome in {"处理中", "processing", "running", "reviewing"}:
        return "reviewing"
    if outcome in {"未提交", "pending"}:
        return "cancelled"
    if outcome:
        return "failed"
    status = _text(item.get("status"))
    if status in {"published", "success"}:
        return "success"
    if status in {"processing", "running", "reviewing"}:
        return "reviewing"
    if status in {"failed", "error"}:
        return "failed"
    return "cancelled"


def _fail_stage(item: dict[str, Any], detail: dict[str, Any]) -> str:
    reason = _text(detail.get("失败原因") or detail.get("错误"))
    clip = item.get("clip") if isinstance(item.get("clip"), dict) else {}
    if _text(clip.get("error")):
      return "clip"
    if "上传" in reason or "upload" in reason.lower():
        return "upload"
    if "发布" in reason or "publish" in reason.lower():
        return "publish"
    if "审核" in reason or "review" in reason.lower():
        return "review"
    return ""


def _duration_seconds(item: dict[str, Any], clip: dict[str, Any]) -> float:
    for candidate in (
        item.get("output_duration_sec"),
        clip.get("output_duration_sec"),
        ((clip.get("publish_ready_metadata") or {}).get("file_duration") if isinstance(clip.get("publish_ready_metadata"), dict) else 0),
        ((clip.get("downloaded_metadata") or {}).get("file_duration") if isinstance(clip.get("downloaded_metadata"), dict) else 0),
    ):
        value = _number(candidate)
        if value > 0:
            return value
    return 0.0


def _size_mb(item: dict[str, Any], clip: dict[str, Any]) -> float:
    for candidate in (
        item.get("output_size_mb"),
        ((clip.get("publish_ready_metadata") or {}).get("size_mb") if isinstance(clip.get("publish_ready_metadata"), dict) else 0),
        ((clip.get("downloaded_metadata") or {}).get("size_mb") if isinstance(clip.get("downloaded_metadata"), dict) else 0),
    ):
        value = _number(candidate)
        if value > 0:
            return value
    return 0.0


def _clip_status(item: dict[str, Any], detail: dict[str, Any]) -> str:
    status = _publish_status(item, detail)
    clip = item.get("clip") if isinstance(item.get("clip"), dict) else {}
    error = _text(clip.get("error") or detail.get("失败原因") or detail.get("错误"))
    if status in {"success", "reviewing"} or _duration_seconds(item, clip) > 0:
        return "completed"
    if "queued" in error.lower() or "排队" in error:
        return "queued"
    if _text(clip.get("task_id") or clip.get("external_task_id")) and not error:
        return "clipping"
    if error:
        return "failed"
    return "pending"


def _normalize_rows(
    payload: dict[str, Any],
    *,
    owner: str,
    uid: str,
    loop_name: str,
    round_name: str,
    line_name: str,
    business_date: str,
    daily_target: int | None,
    publish_start_time: str,
    publish_interval_seconds: int | None,
) -> list[dict[str, Any]]:
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    detail_rows = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
    detail_by_index = {
        int(row.get("序号") or 0): dict(row)
        for row in detail_rows
        if isinstance(row, dict) and int(row.get("序号") or 0) > 0
    }
    rows: list[dict[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        index = int(item.get("index") or 0)
        detail = detail_by_index.get(index, {})
        drama = item.get("drama") if isinstance(item.get("drama"), dict) else {}
        episode = item.get("episode") if isinstance(item.get("episode"), dict) else {}
        account = item.get("account") if isinstance(item.get("account"), dict) else {}
        clip = item.get("clip") if isinstance(item.get("clip"), dict) else {}
        promotion = item.get("promotion") if isinstance(item.get("promotion"), dict) else {}
        publish = item.get("publish") if isinstance(item.get("publish"), dict) else {}
        team_id = _text(account.get("team_id") or account.get("channel_id"))
        internal_account_id = _text(account.get("account_id"))
        clip_status = _clip_status(item, detail)
        publish_status = _publish_status(item, detail)
        row = {
            "date": business_date,
            "assignee": owner,
            "assignee_source": "skill_owner",
            "uid": uid,
            "task_id": _stable_task_id(
                loop_name=loop_name,
                date=business_date,
                line_name=line_name,
                round_name=round_name,
                index=index,
                account=account,
                drama=drama,
                episode=episode,
            ),
            "douyin_t8_account": _text(account.get("name")),
            "social_account_id": team_id or internal_account_id,
            "channel_id": team_id,
            "account_type": "personal",
            "clip_tool": _text((clip.get("task") or {}).get("key") if isinstance(clip.get("task"), dict) else "") or _text(clip.get("execution_provider")) or "auto",
            "drama_name": _text(drama.get("title")),
            "drama_timestamp": _text(payload.get("started_at") or payload.get("created_at") or payload.get("start_time")),
            "preview_duration_sec": _number(episode.get("duration") or drama.get("external_video_duration_seconds")),
            "preview_size_mb": 0,
            "material_source": _text(drama.get("source_mode") or "official"),
            "clip_status": clip_status,
            "clip_last_status": _text(clip.get("last_status") or clip.get("status")),
            "clip_start_time": "",
            "clip_end_time": "",
            "clip_duration_sec": 0,
            "clip_params": {
                "line_name": line_name,
                "line_label": LINE_LABELS.get(line_name, line_name),
                "app_id": _text(drama.get("app_id") or drama.get("source_platform")),
                "serial_id": _text(drama.get("serial_id")),
                "source_task_id": _text(drama.get("task_id") or item.get("task_id")),
                "publish_account_id": internal_account_id,
                "team_id": team_id,
                "episode_order": int(episode.get("episode_order") or 0),
                "promotion_link": _text(promotion.get("link")),
            },
            "output_duration_sec": _duration_seconds(item, clip),
            "output_size_mb": _size_mb(item, clip),
            "output_quality": _text(((clip.get("publish_ready_metadata") or {}).get("resolution")) if isinstance(clip.get("publish_ready_metadata"), dict) else ""),
            "upload_start_time": "",
            "upload_end_time": "",
            "upload_duration_sec": 0,
            "upload_retry_count": int(item.get("upload_retry_count") or 0),
            "publish_req_start_time": "",
            "publish_req_end_time": "",
            "publish_schedule_start_time": publish_start_time,
            "publish_interval_sec": publish_interval_seconds or 0,
            "publish_duration_sec": 0,
            "social_post_id": _text(publish.get("post_id") or item.get("post_id")),
            "publish_status": publish_status,
            "fail_stage": _fail_stage(item, detail),
            "publish_fail_reason": _text(detail.get("失败原因") or detail.get("错误") or item.get("error")),
            "retry_count": int(item.get("retry_count") or 0),
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "clip_fail_reason": _text(clip.get("error")),
            "round_name": round_name,
            "ab_group": "",
            "loop_name": loop_name,
        }
        if daily_target is not None:
            row["daily_publish_target"] = daily_target
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Barry loop round json and push to video pipeline tracker")
    parser.add_argument("--round-json", required=True)
    parser.add_argument("--strategy-context", default="")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--uid", default="")
    parser.add_argument("--loop-name", required=True)
    parser.add_argument("--round-name", required=True)
    parser.add_argument("--line-name", required=True)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--daily-target", type=int, default=None)
    parser.add_argument("--publish-start-time", default="")
    parser.add_argument("--publish-interval-seconds", type=int, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    round_path = Path(args.round_json).resolve()
    payload = _read_json(round_path)
    business_date = _business_date_from_path(round_path)
    rows = _normalize_rows(
        payload,
        owner=args.owner,
        uid=args.uid,
        loop_name=args.loop_name,
        round_name=args.round_name,
        line_name=args.line_name,
        business_date=business_date,
        daily_target=args.daily_target,
        publish_start_time=args.publish_start_time,
        publish_interval_seconds=args.publish_interval_seconds,
    )
    output_path = Path(args.output).resolve() if args.output else round_path.with_suffix(".tracker.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cmd = [
        sys.executable,
        str(TRACKER_PUSH_SCRIPT),
        "--api-base",
        args.api_base,
        "--tasks",
        str(output_path),
        "--owner",
        args.owner,
        "--uid",
        args.uid,
        "--loop-name",
        args.loop_name,
        "--round-name",
        args.round_name,
        "--event-title",
        f"{LINE_LABELS.get(args.line_name, args.line_name)}结果回写",
        "--event-detail",
        f"{LINE_LABELS.get(args.line_name, args.line_name)} {args.round_name} 回写 {len(rows)} 条任务结果",
    ]
    if args.daily_target is not None:
        cmd.extend(["--daily-target", str(args.daily_target)])
    if args.publish_start_time:
        cmd.extend(["--publish-start-time", args.publish_start_time])
    if args.publish_interval_seconds is not None:
        cmd.extend(["--publish-interval-seconds", str(args.publish_interval_seconds)])
    if args.strategy_context:
        cmd.extend(["--strategy-context", args.strategy_context])
    if args.execute:
        cmd.append("--execute")
    result = subprocess.run(cmd, cwd=str(ROOT_DIR), text=True, check=False)
    return int(result.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
