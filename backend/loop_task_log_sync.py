from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pymysql


DEFAULT_TABLE_NAME = "barry_loop_task_log"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return 0


def _optional_duration(value: Any) -> float | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        number = float(raw)
    except Exception:
        return None
    if number <= 0:
        return None
    return round(number, 3)


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({"repr": repr(value)}, ensure_ascii=False)


def _truthy(value: Any) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "on"}


def _now_string() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _path_business_date(path: Path | None) -> str:
    if path:
        for part in reversed(path.parts):
            if len(part) == 10 and part[4] == "-" and part[7] == "-":
                return part
    return datetime.now().strftime("%Y-%m-%d")


def _line_name_from_path(path: Path | None) -> str:
    if not path:
        return ""
    parts = list(path.parts)
    for idx, part in enumerate(parts):
        if len(part) == 10 and part[4] == "-" and part[7] == "-" and idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _round_name_from_path(path: Path | None) -> str:
    if not path:
        return ""
    name = path.name
    if name.endswith(".progress.json"):
        return name[: -len(".progress.json")]
    if name.endswith(".json"):
        return name[: -len(".json")]
    return path.stem


def _serialize_datetime(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
    return text if len(text) >= 16 else None


def _publish_status_from_record(record: dict[str, Any], item: dict[str, Any], detail: dict[str, Any]) -> str:
    status = _text(record.get("status")).upper()
    if status in {"SUCCESS", "PUBLISHED", "POSTED", "DONE"}:
        return "success"
    if status in {"WAITING", "PROCESSING", "RUNNING", "REVIEWING", "PENDING"}:
        return "reviewing"
    if status in {"ERROR", "FAILED", "CANCELLED"}:
        return "failed"
    detail_status = _text(detail.get("发布情况") or detail.get("状态"))
    if detail_status in {"发布成功", "success", "成功"}:
        return "success"
    if detail_status in {"处理中", "reviewing", "processing", "running"}:
        return "reviewing"
    if detail_status:
        return "failed"
    item_status = _text(item.get("status")).lower()
    if item_status in {"published", "success"}:
        return "success"
    if item_status in {"published_submitted", "publishing", "published_waiting_settle", "processing", "running"}:
        return "reviewing"
    if item_status in {"failed", "error"}:
        return "failed"
    return ""


def _task_status(item: dict[str, Any], publish_status: str, progress_stage: str) -> str:
    item_status = _text(item.get("status")).lower()
    if publish_status == "success":
        return "success"
    if publish_status == "failed":
        return "failed"
    if publish_status == "reviewing":
        return "publishing"
    if item_status in {"clipped"}:
        return "clip_done"
    if item_status in {"failed", "error"}:
        return "failed"
    if progress_stage in {"after_clip"}:
        return "clip_done"
    if progress_stage in {"after_publish", "before_settle"}:
        return "publishing"
    if item.get("clip"):
        return "clipping"
    return "selected"


def _fail_stage(item: dict[str, Any], detail: dict[str, Any], publish_status: str) -> str:
    clip = item.get("clip") if isinstance(item.get("clip"), dict) else {}
    if _text(clip.get("error")):
        return "clip"
    reason = _text(detail.get("失败原因") or detail.get("错误") or item.get("error"))
    reason_lower = reason.lower()
    if "upload" in reason_lower or "上传" in reason:
        return "upload"
    if "publish" in reason_lower or "发布" in reason:
        return "publish"
    if "review" in reason_lower or "审核" in reason:
        return "review"
    if publish_status == "failed":
        return "publish"
    return ""


def _report_detail_rows(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
    output: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        index = _int(row.get("序号"))
        if index > 0:
            output[index] = row
    return output


def _publish_records_by_task_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        task_id = _text(record.get("task_id"))
        if task_id:
            output[task_id] = record
    return output


def _first_publish_task(item: dict[str, Any]) -> dict[str, Any]:
    publish = item.get("publish") if isinstance(item.get("publish"), dict) else {}
    tasks = publish.get("tasks") if isinstance(publish.get("tasks"), list) else []
    for task in tasks:
        if isinstance(task, dict):
            return task
    return {}


def _stable_task_uid(
    *,
    loop_name: str,
    task_uid_prefix: str,
    business_date: str,
    line_name: str,
    round_name: str,
    index: int,
    account: dict[str, Any],
    drama: dict[str, Any],
    episode: dict[str, Any],
) -> str:
    seed = {
        "loop_name": loop_name,
        "date": business_date,
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
    task_uid = f"{loop_name}:{business_date}:{line_name}:{round_name}:{index}:{digest}"
    if task_uid_prefix:
        return f"{task_uid_prefix}{task_uid}"
    return task_uid


def _merge_first(existing: dict[str, Any], key: str, new_value: Any) -> Any:
    return existing.get(key) or new_value


def _merge_last(existing: dict[str, Any], key: str, new_value: Any) -> Any:
    return new_value or existing.get(key)


def _build_context(
    *,
    payload_path: Path | None,
    override: dict[str, Any] | None = None,
) -> dict[str, str]:
    override = override or {}
    loop_name = _text(override.get("loop_name") or os.getenv("BARRY_LOOP_TASK_LOG_LOOP_NAME"))
    if not loop_name:
        raise RuntimeError("缺少 loop_name：请显式设置 BARRY_LOOP_TASK_LOG_LOOP_NAME 或通过参数传 --loop-name")
    return {
        "loop_name": loop_name,
        "runtime_mode": _text(override.get("runtime_mode") or os.getenv("BARRY_LOOP_RUNTIME_MODE") or "continuous"),
        "business_date": _text(override.get("business_date")) or _path_business_date(payload_path),
        "line_name": _text(override.get("line_name") or os.getenv("BARRY_LOOP_LINE_NAME")) or _line_name_from_path(payload_path),
        "round_name": _text(override.get("round_name") or os.getenv("BARRY_LOOP_ROUND_NAME")) or _round_name_from_path(payload_path),
        "pool_name": _text(override.get("pool_name") or os.getenv("BARRY_LOOP_ACCOUNT_POOL")),
        "platform": _text(override.get("platform") or os.getenv("BARRY_LOOP_PLATFORM") or "FACEBOOK"),
        "task_uid_prefix": _text(override.get("task_uid_prefix") or os.getenv("BARRY_LOOP_TASK_LOG_TASK_UID_PREFIX")),
    }


def _normalize_rows(
    payload: dict[str, Any],
    *,
    payload_path: Path | None,
    source: str,
    override: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = _build_context(payload_path=payload_path, override=override)
    line_name = context["line_name"]
    round_name = context["round_name"]
    if not line_name or not round_name:
        return []
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    detail_by_index = _report_detail_rows(report)
    records = payload.get("publish_records") if isinstance(payload.get("publish_records"), list) else []
    records_by_task_id = _publish_records_by_task_id(records)
    progress_stage = _text(payload.get("progress_stage") or source)
    progress_written_at = _serialize_datetime(payload.get("progress_written_at")) or _now_string()
    rows: list[dict[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        index = _int(item.get("index"))
        if index <= 0:
            continue
        detail = detail_by_index.get(index, {})
        drama = item.get("drama") if isinstance(item.get("drama"), dict) else {}
        episode = item.get("episode") if isinstance(item.get("episode"), dict) else {}
        account = item.get("account") if isinstance(item.get("account"), dict) else {}
        clip = item.get("clip") if isinstance(item.get("clip"), dict) else {}
        promotion = item.get("promotion") if isinstance(item.get("promotion"), dict) else {}
        publish = item.get("publish") if isinstance(item.get("publish"), dict) else {}
        publish_task = _first_publish_task(item)
        record = records_by_task_id.get(_text(publish_task.get("task_id")), {})
        publish_status = _publish_status_from_record(record, item, detail)
        clip_metadata = clip.get("publish_ready_metadata") if isinstance(clip.get("publish_ready_metadata"), dict) else {}
        downloaded_metadata = clip.get("downloaded_metadata") if isinstance(clip.get("downloaded_metadata"), dict) else {}
        clip_stage_timings = item.get("clip_stage_timings") if isinstance(item.get("clip_stage_timings"), dict) else {}
        drama_language = _text(detail.get("语言") or drama.get("language"))
        select_started_at = _serialize_datetime(item.get("select_started_at"))
        select_finished_at = _serialize_datetime(item.get("select_finished_at"))
        clip_started_at = _serialize_datetime(item.get("clip_started_at"))
        clip_finished_at = _serialize_datetime(item.get("clip_finished_at"))
        upload_started_at = _serialize_datetime(item.get("upload_started_at"))
        upload_finished_at = _serialize_datetime(item.get("upload_finished_at"))
        publish_started_at = _serialize_datetime(item.get("publish_started_at"))
        publish_submitted_at = _serialize_datetime(item.get("publish_submitted_at")) or _serialize_datetime(record.get("created_at"))
        publish_finished_at = _serialize_datetime(item.get("publish_finished_at")) or _serialize_datetime(record.get("updated_at"))
        publish_success_at = None
        if publish_status == "success":
            publish_success_at = (
                _serialize_datetime(item.get("publish_success_at"))
                or _serialize_datetime(record.get("updated_at"))
                or publish_submitted_at
            )
        settle_finished_at = _serialize_datetime(item.get("settle_finished_at"))
        last_event_at = progress_written_at
        row = {
            "task_uid": _stable_task_uid(
                loop_name=context["loop_name"],
                task_uid_prefix=context["task_uid_prefix"],
                business_date=context["business_date"],
                line_name=line_name,
                round_name=round_name,
                index=index,
                account=account,
                drama=drama,
                episode=episode,
            ),
            "biz_date": context["business_date"],
            "loop_name": context["loop_name"],
            "runtime_mode": context["runtime_mode"],
            "content_type": "short_drama",
            "line_name": line_name,
            "round_name": round_name,
            "pool_name": context["pool_name"],
            "task_index": index,
            "task_status": _task_status(item, publish_status, progress_stage),
            "progress_stage": progress_stage,
            "status_label": _text(detail.get("发布情况") or detail.get("状态") or publish_status or item.get("status")),
            "remark": _text(detail.get("失败原因") or item.get("error")),
            "platform": _text(account.get("platform") or context["platform"]),
            "account_name": _text(detail.get("账号") or account.get("name")),
            "account_id": _text(account.get("account_id") or record.get("social_id")),
            "team_id": _text(account.get("team_id") or record.get("team_id")),
            "channel_id": _text(account.get("channel_id")),
            "drama_title": _text(detail.get("短剧") or drama.get("title")),
            "serial_id": _text(drama.get("serial_id")),
            "app_id": _text(drama.get("app_id") or drama.get("source_platform")),
            "theater": _text(detail.get("剧场") or drama.get("source_platform") or drama.get("app_id")),
            "language": drama_language,
            "episode_order": _int(detail.get("集数") or episode.get("episode_order")),
            "episode_id": _text(episode.get("episode_id")),
            "material_source": _text(drama.get("source_mode") or detail.get("素材来源") or drama.get("candidate_fetch_source") or "official"),
            "candidate_source": _text(drama.get("candidate_fetch_source") or detail.get("素材来源")),
            "selection_reason": _text(episode.get("reason") or drama.get("candidate_fetch_source")),
            "source_reused": 1 if bool(drama.get("source_reused")) else 0,
            "source_video_path": _text(clip.get("source_clip_path") or drama.get("cached_source_path")),
            "source_video_url": _text(clip.get("media_url") or drama.get("external_video_url") or episode.get("play_url")),
            "output_video_path": _text(clip.get("publish_ready_file") or clip.get("downloaded_file")),
            "output_duration_sec": round(
                max(
                    _number(item.get("output_duration_sec")),
                    _number(clip_metadata.get("file_duration")),
                    _number(downloaded_metadata.get("file_duration")),
                ),
                3,
            ),
            "output_size_mb": round(
                max(
                    _number(item.get("output_size_mb")),
                    _number(clip_metadata.get("file_size")) / 1024 / 1024,
                    _number(downloaded_metadata.get("file_size")) / 1024 / 1024,
                ),
                3,
            ),
            "output_resolution": (
                f"{_int(clip_metadata.get('screen_x'))}x{_int(clip_metadata.get('screen_y'))}"
                if _int(clip_metadata.get("screen_x")) > 0 and _int(clip_metadata.get("screen_y")) > 0
                else _text(detail.get("视频分辨率"))
            ),
            "output_ratio": _text(item.get("output_ratio") or clip_metadata.get("orientation")),
            "clip_method": _text(detail.get("剪辑手法") or ((clip.get("task") or {}).get("key") if isinstance(clip.get("task"), dict) else "") or clip.get("execution_provider")),
            "dedup_method": _text(detail.get("去重手法") or item.get("dedup_method")),
            "clip_provider": _text(clip.get("execution_provider")),
            "manus_id": _text(clip.get("manus_id")),
            "source_upload_id": _text(clip.get("source_upload_id")),
            "source_window_id": _text(clip.get("source_window_id")),
            "promotion_link": _text(promotion.get("promotion_link")),
            "promotion_code": _text(promotion.get("promotion_code")),
            "caption": _text(promotion.get("caption")),
            "publish_task_id": _text(publish_task.get("task_id") or record.get("task_id")),
            "social_post_id": _text(record.get("post_id") or publish.get("post_id")),
            "publish_status": publish_status,
            "publish_attempt_count": max(len(item.get("publish_attempts") or []), _int(item.get("publish_attempt_count"))),
            "publish_retry_count": _int(item.get("publish_retry_count")),
            "select_started_at": select_started_at,
            "select_finished_at": select_finished_at,
            "clip_started_at": clip_started_at,
            "clip_finished_at": clip_finished_at,
            "upload_started_at": upload_started_at,
            "upload_finished_at": upload_finished_at,
            "publish_started_at": publish_started_at,
            "publish_submitted_at": publish_submitted_at,
            "publish_finished_at": publish_finished_at,
            "publish_success_at": publish_success_at,
            "settle_finished_at": settle_finished_at,
            "last_event_at": last_event_at,
            "select_elapsed_sec": _optional_duration(item.get("select_elapsed_sec")),
            "clip_elapsed_sec": _optional_duration(clip_stage_timings.get("total")),
            "upload_elapsed_sec": _optional_duration(item.get("upload_elapsed_sec")),
            "publish_elapsed_sec": _optional_duration(item.get("publish_elapsed_sec")),
            "settle_elapsed_sec": _optional_duration(item.get("settle_elapsed_sec")),
            "total_elapsed_sec": _optional_duration(item.get("total_elapsed_sec")),
            "play_count": _int(record.get("views")),
            "like_count": _int(record.get("likes")),
            "comment_count": _int(record.get("comments")),
            "share_count": _int(record.get("shares")),
            "fail_stage": _fail_stage(item, detail, publish_status),
            "fail_reason": _text(detail.get("失败原因") or record.get("error_msg") or item.get("error") or clip.get("error")),
            "error_text": _text(item.get("error") or clip.get("error") or record.get("error_msg")),
            "data_note": (
                "时间字段仅写任务级真实值；拿不到真实任务时间或耗时时留空，不使用批次统一时间或 0 占位。"
            ),
            "timeline_json": _json_dumps(
                {
                    "progress_stage": progress_stage,
                    "progress_written_at": progress_written_at,
                    "publish_attempts": item.get("publish_attempts") or [],
                }
            ),
            "raw_item_json": _json_dumps(item),
            "raw_report_json": _json_dumps(detail),
            "raw_publish_json": _json_dumps({"publish": publish, "record": record}),
            "extra_json": _json_dumps(
                {
                    "payload_status": _text(payload.get("status")),
                    "payload_source": source,
                    "payload_path": str(payload_path) if payload_path else "",
                    "report_status_settle_note": _text(report.get("状态收敛说明")),
                    "selection_summary": payload.get("selection_summary") if isinstance(payload.get("selection_summary"), dict) else {},
                }
            ),
        }
        rows.append(row)
    return rows


UPSERT_COLUMNS = [
    "task_uid",
    "biz_date",
    "loop_name",
    "runtime_mode",
    "content_type",
    "line_name",
    "round_name",
    "pool_name",
    "task_index",
    "task_status",
    "progress_stage",
    "status_label",
    "remark",
    "platform",
    "account_name",
    "account_id",
    "team_id",
    "channel_id",
    "drama_title",
    "serial_id",
    "app_id",
    "theater",
    "language",
    "episode_order",
    "episode_id",
    "material_source",
    "candidate_source",
    "selection_reason",
    "source_reused",
    "source_video_path",
    "source_video_url",
    "output_video_path",
    "output_duration_sec",
    "output_size_mb",
    "output_resolution",
    "output_ratio",
    "clip_method",
    "dedup_method",
    "clip_provider",
    "manus_id",
    "source_upload_id",
    "source_window_id",
    "promotion_link",
    "promotion_code",
    "caption",
    "publish_task_id",
    "social_post_id",
    "publish_status",
    "publish_attempt_count",
    "publish_retry_count",
    "select_started_at",
    "select_finished_at",
    "clip_started_at",
    "clip_finished_at",
    "upload_started_at",
    "upload_finished_at",
    "publish_started_at",
    "publish_submitted_at",
    "publish_finished_at",
    "publish_success_at",
    "settle_finished_at",
    "last_event_at",
    "select_elapsed_sec",
    "clip_elapsed_sec",
    "upload_elapsed_sec",
    "publish_elapsed_sec",
    "settle_elapsed_sec",
    "total_elapsed_sec",
    "play_count",
    "like_count",
    "comment_count",
    "share_count",
    "fail_stage",
    "fail_reason",
    "error_text",
    "data_note",
    "timeline_json",
    "raw_item_json",
    "raw_report_json",
    "raw_publish_json",
    "extra_json",
]

FIRST_TIME_COLUMNS = {
    "select_started_at",
    "select_finished_at",
    "clip_started_at",
    "clip_finished_at",
    "upload_started_at",
    "upload_finished_at",
    "publish_started_at",
    "publish_submitted_at",
    "publish_finished_at",
    "publish_success_at",
}

LAST_TIME_COLUMNS = {"settle_finished_at", "last_event_at"}


def _db_enabled() -> bool:
    if _truthy(os.getenv("BARRY_LOOP_TASK_LOG_ENABLED", "0")):
        return True
    return bool(_text(os.getenv("BARRY_LOOP_TASK_LOG_DB_HOST")) and _text(os.getenv("BARRY_LOOP_TASK_LOG_DB_PASSWORD")))


def _db_config() -> dict[str, Any]:
    return {
        "host": _text(os.getenv("BARRY_LOOP_TASK_LOG_DB_HOST")),
        "port": _int(os.getenv("BARRY_LOOP_TASK_LOG_DB_PORT") or 3306) or 3306,
        "user": _text(os.getenv("BARRY_LOOP_TASK_LOG_DB_USER") or "prod_rw"),
        "password": _text(os.getenv("BARRY_LOOP_TASK_LOG_DB_PASSWORD")),
        "database": _text(os.getenv("BARRY_LOOP_TASK_LOG_DB_NAME") or "center"),
        "table": _text(os.getenv("BARRY_LOOP_TASK_LOG_TABLE") or DEFAULT_TABLE_NAME),
        "connect_timeout": _int(os.getenv("BARRY_LOOP_TASK_LOG_DB_CONNECT_TIMEOUT") or 10) or 10,
    }


def _select_existing_rows(cursor: pymysql.cursors.Cursor, *, table: str, task_uids: list[str]) -> dict[str, dict[str, Any]]:
    if not task_uids:
        return {}
    placeholders = ",".join(["%s"] * len(task_uids))
    cursor.execute(
        f"SELECT task_uid, {', '.join(sorted(FIRST_TIME_COLUMNS | LAST_TIME_COLUMNS))} FROM {table} WHERE task_uid IN ({placeholders})",
        task_uids,
    )
    rows = cursor.fetchall() or []
    return {str(row.get("task_uid")): row for row in rows if isinstance(row, dict)}


def _merge_existing_row(existing: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    for key in FIRST_TIME_COLUMNS:
        merged[key] = _merge_first(existing, key, merged.get(key))
    for key in LAST_TIME_COLUMNS:
        merged[key] = _merge_last(existing, key, merged.get(key))
    return merged


def _upsert_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"ok": True, "inserted_or_updated": 0}
    config = _db_config()
    missing = [key for key in ("host", "user", "password", "database", "table") if not _text(config.get(key))]
    if missing:
        raise RuntimeError(f"缺少数据库配置: {', '.join(missing)}")
    table = str(config["table"])
    conn = pymysql.connect(
        host=str(config["host"]),
        port=int(config["port"]),
        user=str(config["user"]),
        password=str(config["password"]),
        database=str(config["database"]),
        charset="utf8mb4",
        connect_timeout=int(config["connect_timeout"]),
        read_timeout=max(20, int(config["connect_timeout"]) * 2),
        write_timeout=max(20, int(config["connect_timeout"]) * 2),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        with conn.cursor() as cursor:
            existing_by_uid = _select_existing_rows(cursor, table=table, task_uids=[str(row["task_uid"]) for row in rows])
            merged_rows = [_merge_existing_row(existing_by_uid.get(str(row["task_uid"]), {}), row) for row in rows]
            columns_sql = ", ".join(UPSERT_COLUMNS)
            value_sql = ", ".join(["%s"] * len(UPSERT_COLUMNS))
            update_sql = ", ".join([f"{column}=%s" for column in UPSERT_COLUMNS if column != "task_uid"])
            sql = (
                f"INSERT INTO {table} ({columns_sql}) VALUES ({value_sql}) "
                f"ON DUPLICATE KEY UPDATE {update_sql}"
            )
            for row in merged_rows:
                insert_values = [row.get(column) for column in UPSERT_COLUMNS]
                update_values = [row.get(column) for column in UPSERT_COLUMNS if column != "task_uid"]
                cursor.execute(sql, insert_values + update_values)
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "inserted_or_updated": len(rows)}


def sync_payload(
    payload: dict[str, Any],
    *,
    payload_path: str | Path | None = None,
    source: str = "manual",
    override: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    path_obj = Path(payload_path).expanduser() if payload_path else None
    rows = _normalize_rows(payload, payload_path=path_obj, source=source, override=override)
    summary = {
        "ok": True,
        "enabled": _db_enabled(),
        "row_count": len(rows),
        "source": source,
        "payload_path": str(path_obj) if path_obj else "",
        "sample_task_uid": rows[0]["task_uid"] if rows else "",
        "line_name": rows[0]["line_name"] if rows else _text((override or {}).get("line_name")),
        "round_name": rows[0]["round_name"] if rows else _text((override or {}).get("round_name")),
    }
    if dry_run or not _db_enabled():
        summary["dry_run"] = dry_run
        summary["sample_row"] = rows[0] if rows else {}
        return summary
    result = _upsert_rows(rows)
    return {**summary, **result}


def maybe_sync_payload(
    payload: dict[str, Any],
    *,
    payload_path: str | Path | None = None,
    source: str,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _db_enabled():
        return {"ok": True, "enabled": False, "row_count": 0, "source": source}
    return sync_payload(payload, payload_path=payload_path, source=source, override=override, dry_run=False)


def _load_payload(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("payload 必须是 JSON 对象")
    return data


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="同步 loop payload 到 barry_loop_task_log")
    parser.add_argument("--payload", required=True, help="round.json 或 progress.json 路径")
    parser.add_argument("--source", default="manual", help="来源标记，如 progress/final/manual")
    parser.add_argument("--line-name", default="", help="手动覆盖 line_name")
    parser.add_argument("--round-name", default="", help="手动覆盖 round_name")
    parser.add_argument("--pool-name", default="", help="手动覆盖 pool_name")
    parser.add_argument("--business-date", default="", help="手动覆盖 biz_date")
    parser.add_argument("--runtime-mode", default="", help="手动覆盖 runtime_mode")
    parser.add_argument("--loop-name", default="", help="手动覆盖 loop_name")
    parser.add_argument("--task-uid-prefix", default="", help="给 task_uid 加前缀，适合 smoke 测试")
    parser.add_argument("--dry-run", action="store_true", help="只解析并打印样例，不写库")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    payload_path = Path(args.payload).expanduser()
    payload = _load_payload(payload_path)
    override = {
        "line_name": args.line_name,
        "round_name": args.round_name,
        "pool_name": args.pool_name,
        "business_date": args.business_date,
        "runtime_mode": args.runtime_mode,
        "loop_name": args.loop_name,
        "task_uid_prefix": args.task_uid_prefix,
    }
    result = sync_payload(
        payload,
        payload_path=payload_path,
        source=args.source,
        override=override,
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
