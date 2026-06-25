from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


BASE_URL_ENV = "AI_ANIMATION_BASE_URL"
ACCESS_KEY_ENV = "AI_ANIMATION_ACCESS_KEY"
SECRET_KEY_ENV = "AI_ANIMATION_SECRET_KEY"
ADMIN_BASE_URL_ENV = "AI_ANIMATION_ADMIN_API_BASE_URL"
ADMIN_BEARER_TOKEN_ENV = "AI_ANIMATION_ADMIN_BEARER_TOKEN"
ENV_FILE = Path.home() / ".ai-beidou" / "state.env"
CREATE_PATH = "/openapi/v1/short-drama-clip-tasks"
AUTO_CLIP_TASKS_PATH = "/api/short-drama-auto-clip/tasks"
FREE_VIDEO_TASKS_PATH = "/api/short-drama-free-video/tasks"
FINAL_TASK_STATUSES = {"success", "failed", "cancelled"}
FINAL_CLIP_STATUSES = {"success", "failed", "cancelled"}
SEGMENT_SUCCESS_STATUS = "success"
DEFAULT_TEMPLATE_ID = max(0, int(os.getenv("BARRY_AI_ANIMATION_TEMPLATE_ID", "1") or 1))
DEFAULT_SEGMENT_SECONDS = max(5, int(os.getenv("BARRY_AI_ANIMATION_SEGMENT_SECONDS", "25") or 25))
DEFAULT_SEGMENT_MAX_SECONDS = max(
    DEFAULT_SEGMENT_SECONDS,
    int(os.getenv("BARRY_AI_ANIMATION_SEGMENT_MAX_SECONDS", "40") or 40),
)
DEFAULT_PROCESS_CONCURRENCY = max(1, int(os.getenv("BARRY_AI_ANIMATION_PROCESS_CONCURRENCY", "20") or 20))
DEFAULT_MAX_TOTAL_DURATION_SECONDS = max(
    0,
    int(os.getenv("BARRY_AI_ANIMATION_MAX_TOTAL_DURATION_SECONDS", "1200") or 1200),
)
DEFAULT_MAX_EPISODES_PER_SERIAL = max(
    0,
    int(os.getenv("BARRY_AI_ANIMATION_MAX_EPISODES_PER_SERIAL", "15") or 15),
)
DEFAULT_SOURCE = str(os.getenv("BARRY_AI_ANIMATION_SOURCE", "auto_clip") or "auto_clip").strip() or "auto_clip"
DEFAULT_REQUEST_TIMEOUT = max(10, int(os.getenv("BARRY_AI_ANIMATION_REQUEST_TIMEOUT", "60") or 60))
DEFAULT_DOWNLOAD_TIMEOUT = max(30, int(os.getenv("BARRY_AI_ANIMATION_DOWNLOAD_TIMEOUT", "120") or 120))
DEFAULT_MIN_TASK_TIMEOUT = max(0, int(os.getenv("BARRY_AI_ANIMATION_MIN_TASK_TIMEOUT", "0") or 0))


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


DEFAULT_AUTO_CLIP_ENABLED = _env_flag("BARRY_AI_ANIMATION_AUTO_CLIP_ENABLED", True)
DEFAULT_USE_AUTO_MIGRATION = _env_flag("BARRY_AI_ANIMATION_USE_AUTO_MIGRATION", False)
DEFAULT_SYNC_MATERIAL_AGENT_ID = max(
    0,
    int(os.getenv("BARRY_AI_ANIMATION_SYNC_MATERIAL_AGENT_ID", "0") or 0),
)
DEFAULT_SYNC_MATERIAL_CATEGORY_ID = max(
    0,
    int(os.getenv("BARRY_AI_ANIMATION_SYNC_MATERIAL_CATEGORY_ID", "0") or 0),
)
ADMIN_RUNNING_STATUSES = {
    "queued",
    "queue",
    "execute",
    "executing",
    "running",
    "processing",
    "pending",
    "waiting",
    "in_progress",
    "download_running",
    "clip_running",
    "执行中",
    "进行中",
}
ADMIN_SUCCESS_STATUSES = {
    "success",
    "done",
    "completed",
    "finished",
    "all_success",
    "全部成功",
    "成功",
    "完成",
}
ADMIN_FAILED_STATUSES = {
    "failed",
    "failure",
    "error",
    "cancelled",
    "canceled",
    "skipped",
    "partial_failed",
    "all_failed",
    "下载失败",
    "剪辑失败",
    "失败",
    "全部失败",
    "已跳过",
    "跳过",
}


class AiCutAnimationError(RuntimeError):
    """OpenAPI 调用异常。"""


class AiCutTaskStillRunningError(AiCutAnimationError):
    """ai-cut task did not finish inside the local wait window, but is still non-terminal upstream."""

    def __init__(
        self,
        task_id: str,
        *,
        last_status: object = "",
        snapshots: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.task_id = str(task_id or "").strip()
        self.last_status = str(last_status or "").strip()
        self.snapshots = dict(snapshots or {})
        super().__init__(
            f"ai-cut 任务仍在执行，等待窗口到期: task_id={self.task_id}, last_status={self.last_status or 'unknown'}"
        )


def shared_env_file() -> Path:
    return ENV_FILE


def _unquote_dotenv_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


def read_dotenv(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    except OSError:
        return {}

    values: dict[str, str] = {}
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("export "):
            raw = raw[len("export ") :].strip()
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        values[key] = _unquote_dotenv_value(value)
    return values


def resolve_config_value(env_name: str) -> str:
    env_value = os.getenv(env_name, "").strip()
    if env_value:
        return env_value
    file_value = read_dotenv(shared_env_file()).get(env_name, "").strip()
    if file_value:
        return file_value
    raise AiCutAnimationError(f"缺少 {env_name}，请设置环境变量或写入 {shared_env_file()}")


def resolve_base_url() -> str:
    return resolve_config_value(BASE_URL_ENV).rstrip("/")


def resolve_access_key() -> str:
    return resolve_config_value(ACCESS_KEY_ENV)


def resolve_secret_key() -> str:
    return resolve_config_value(SECRET_KEY_ENV)


def resolve_optional_config_value(env_name: str) -> str:
    env_value = os.getenv(env_name, "").strip()
    if env_value:
        return env_value
    return read_dotenv(shared_env_file()).get(env_name, "").strip()


def resolve_admin_base_url() -> str:
    value = resolve_optional_config_value(ADMIN_BASE_URL_ENV)
    if value:
        return value.rstrip("/")
    try:
        return resolve_base_url()
    except AiCutAnimationError:
        return ""


def resolve_admin_bearer_token() -> str:
    return resolve_optional_config_value(ADMIN_BEARER_TOKEN_ENV)


def _body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _sign_request(method: str, path: str, timestamp: str, nonce: str, body: bytes, secret_key: str) -> str:
    canonical = "\n".join([method.upper(), path, timestamp, nonce, _body_hash(body)])
    return hmac.new(secret_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _build_auth_headers(method: str, path: str, body: bytes, access_key: str, secret_key: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    return {
        "X-Access-Key": access_key,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": _sign_request(method, path, timestamp, nonce, body, secret_key),
    }


def request_json(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> Any:
    base_url = resolve_base_url()
    access_key = resolve_access_key()
    secret_key = resolve_secret_key()
    body = b""
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    headers.update(_build_auth_headers(method, path, body, access_key, secret_key))
    try:
        response = requests.request(
            method=method.upper(),
            url=f"{base_url}{path}",
            headers=headers,
            data=body if payload is not None else None,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise AiCutAnimationError(f"ai-cut 请求失败: {exc}") from exc
    if response.status_code >= 400:
        raise AiCutAnimationError(f"ai-cut HTTP {response.status_code}: {response.text}")
    if not response.text.strip():
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise AiCutAnimationError(f"ai-cut 返回非 JSON: {response.text}") from exc


def request_admin_json(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> Any:
    base_url = resolve_admin_base_url()
    bearer_token = resolve_admin_bearer_token()
    if not base_url or not bearer_token:
        raise AiCutAnimationError("缺少 ai-cut 管理端访问配置")
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {bearer_token}",
    }
    try:
        response = requests.request(
            method=method.upper(),
            url=f"{base_url}{path}",
            headers=headers,
            params=params,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise AiCutAnimationError(f"ai-cut 管理端请求失败: {exc}") from exc
    if response.status_code >= 400:
        raise AiCutAnimationError(f"ai-cut 管理端 HTTP {response.status_code}: {response.text}")
    if not response.text.strip():
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise AiCutAnimationError(f"ai-cut 管理端返回非 JSON: {response.text}") from exc


def _is_admin_task_not_found_error(error: Exception) -> bool:
    message = str(error or "").lower()
    return any(
        marker in message
        for marker in (
            "任务不存在",
            "task not found",
            "not found",
            "http 404",
        )
    )


def _extract_admin_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("list", "rows", "items", "records", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]

    for key in ("data", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_admin_records(value)
            if nested:
                return nested
    return []


def _select_admin_record(records: list[dict[str, Any]], source_external_task_id: str) -> dict[str, Any] | None:
    normalized = str(source_external_task_id or "").strip()
    if not normalized:
        return None
    match_keys = (
        "source_external_task_id",
        "sourceTaskId",
        "source_task_id",
        "related_task_id",
        "relation_task_id",
        "associated_task_id",
        "external_task_id",
        "third_task_id",
        "task_id",
        "taskId",
    )
    for record in records:
        for key in match_keys:
            if str(record.get(key) or "").strip() == normalized:
                return dict(record)
    if len(records) == 1:
        return dict(records[0])
    return None


def _normalize_admin_status(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    return lowered or text


def _admin_record_status(record: dict[str, Any]) -> str:
    for key in ("status", "task_status", "download_status", "clip_status", "state"):
        status = _normalize_admin_status(record.get(key))
        if status:
            return status
    return ""


def _record_int(record: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = record.get(key)
        if value is None or value == "":
            continue
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            continue
    return None


def _admin_status_category(record: dict[str, Any]) -> str:
    status = _admin_record_status(record)
    if status in ADMIN_SUCCESS_STATUSES:
        return "success"
    if status in ADMIN_FAILED_STATUSES:
        return "failed"
    if status in ADMIN_RUNNING_STATUSES:
        return "running"

    success_count = _record_int(record, "success_count", "success_num", "success_total", "succeed_count")
    failed_count = _record_int(record, "failed_count", "fail_count", "error_count", "failed_num")
    skipped_count = _record_int(record, "skipped_count", "skip_count")
    total_count = _record_int(record, "total_count", "total_num", "count")

    if success_count and total_count and success_count >= total_count and not (failed_count or skipped_count):
        return "success"
    if (failed_count and failed_count > 0) or (skipped_count and skipped_count > 0):
        return "failed"
    return "running"


def _admin_record_reason(record: dict[str, Any]) -> str:
    for key in (
        "reason",
        "message",
        "error",
        "last_error",
        "error_message",
        "fail_reason",
        "failed_reason",
        "remark",
    ):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _admin_record_summary(task_kind: str, record: dict[str, Any]) -> str:
    label = "下载任务" if task_kind == "free_video" else "剪辑任务"
    status = _admin_record_status(record) or "unknown"
    reason = _admin_record_reason(record)
    if reason:
        return f"ai-cut {label}状态={status}，原因={reason}"
    return f"ai-cut {label}状态={status}"


def _query_admin_task_record(
    path: str,
    *,
    source_external_task_id: str,
    timeout: int,
) -> dict[str, Any] | None:
    normalized = str(source_external_task_id or "").strip()
    if not normalized:
        return None
    params = {
        "limit": 20,
        "offset": 0,
    }
    if path == FREE_VIDEO_TASKS_PATH:
        params["external_task_id"] = normalized
    else:
        params["source_external_task_id"] = normalized
    try:
        response = request_admin_json(
            "GET",
            path,
            params=params,
            timeout=timeout,
        )
    except AiCutAnimationError as exc:
        # The management UI has separate tables for download and auto-clip.
        # A missing row in one table is not a task failure; keep checking the
        # other table and the signed OpenAPI result.
        if _is_admin_task_not_found_error(exc):
            return None
        raise
    records = _extract_admin_records(response)
    return _select_admin_record(records, source_external_task_id)


def get_admin_task_snapshots(
    task_id: str,
    *,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> dict[str, dict[str, Any]]:
    normalized = str(task_id or "").strip()
    if not normalized:
        return {}
    snapshots: dict[str, dict[str, Any]] = {}
    try:
        free_video = _query_admin_task_record(
            FREE_VIDEO_TASKS_PATH,
            source_external_task_id=normalized,
            timeout=timeout,
        )
    except AiCutAnimationError:
        free_video = None
    if isinstance(free_video, dict):
        snapshots["free_video"] = free_video
    try:
        auto_clip = _query_admin_task_record(
            AUTO_CLIP_TASKS_PATH,
            source_external_task_id=normalized,
            timeout=timeout,
        )
    except AiCutAnimationError:
        auto_clip = None
    if isinstance(auto_clip, dict):
        snapshots["auto_clip"] = auto_clip
    return snapshots


def raise_if_admin_task_failed(
    task_id: str,
    *,
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> None:
    snapshots = get_admin_task_snapshots(task_id, timeout=request_timeout)
    free_video = snapshots.get("free_video")
    if isinstance(free_video, dict) and _admin_status_category(free_video) == "failed":
        raise AiCutAnimationError(
            f"ai-cut 任务已失败: task_id={task_id}, {_admin_record_summary('free_video', free_video)}"
        )
    auto_clip = snapshots.get("auto_clip")
    if isinstance(auto_clip, dict) and _admin_status_category(auto_clip) == "failed":
        raise AiCutAnimationError(
            f"ai-cut 任务已失败: task_id={task_id}, {_admin_record_summary('auto_clip', auto_clip)}"
        )


def _admin_task_still_running(snapshots: dict[str, dict[str, Any]]) -> bool:
    return any(
        isinstance(record, dict) and _admin_status_category(record) == "running"
        for record in (snapshots or {}).values()
    )


def _openapi_task_has_failed_child(body: dict[str, Any]) -> bool:
    serials = body.get("serials")
    if not isinstance(serials, list):
        return False
    for serial in serials:
        payload = serial if isinstance(serial, dict) else {}
        download_status = _normalize_admin_status(payload.get("download_status"))
        if download_status in ADMIN_FAILED_STATUSES:
            return True
        clip = payload.get("clip")
        if isinstance(clip, dict):
            clip_status = _normalize_admin_status(clip.get("status"))
            if clip_status in ADMIN_FAILED_STATUSES:
                return True
            segments = clip.get("segments")
            if isinstance(segments, list) and any(
                _normalize_admin_status((segment or {}).get("status")) in ADMIN_FAILED_STATUSES
                for segment in segments
                if isinstance(segment, dict)
            ):
                return True
    return False


def _openapi_task_still_running(body: dict[str, Any]) -> bool:
    status = _normalize_admin_status(body.get("status"))
    if status in ADMIN_RUNNING_STATUSES:
        return True
    if status and status not in FINAL_TASK_STATUSES:
        return True
    if _openapi_task_has_failed_child(body):
        return False
    return not _clip_results_ready(body)


def create_short_drama_clip_task(
    *,
    app_id: str,
    third_serial_ids: list[str],
    auto_clip_output_folder: str,
    download_output_folder: str | None = None,
    source: str = DEFAULT_SOURCE,
    max_episodes_per_serial: int = DEFAULT_MAX_EPISODES_PER_SERIAL,
    auto_clip_enabled: bool = DEFAULT_AUTO_CLIP_ENABLED,
    template_id: int = DEFAULT_TEMPLATE_ID,
    segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
    segment_max_seconds: int = DEFAULT_SEGMENT_MAX_SECONDS,
    process_concurrency: int = DEFAULT_PROCESS_CONCURRENCY,
    max_total_duration_seconds: int = DEFAULT_MAX_TOTAL_DURATION_SECONDS,
    use_auto_migration: bool = DEFAULT_USE_AUTO_MIGRATION,
    auto_clip_sync_material_agent_id: int = DEFAULT_SYNC_MATERIAL_AGENT_ID,
    auto_clip_sync_material_category_id: int = DEFAULT_SYNC_MATERIAL_CATEGORY_ID,
    force_download: bool = False,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "app_id": str(app_id or "").strip(),
        "third_serial_ids": [str(item).strip() for item in third_serial_ids if str(item).strip()],
        "auto_clip_output_folder": str(auto_clip_output_folder or "").strip(),
        "source": str(source or DEFAULT_SOURCE).strip() or DEFAULT_SOURCE,
        "max_episodes_per_serial": max(0, int(max_episodes_per_serial)),
        "auto_clip_enabled": bool(auto_clip_enabled),
        "template_id": int(template_id),
        "segment_seconds": int(segment_seconds),
        "segment_max_seconds": int(segment_max_seconds),
        "process_concurrency": max(1, int(process_concurrency)),
        "max_total_duration_seconds": max(0, int(max_total_duration_seconds)),
        "use_auto_migration": bool(use_auto_migration),
        "auto_clip_sync_material_agent_id": max(0, int(auto_clip_sync_material_agent_id)),
        "auto_clip_sync_material_category_id": max(0, int(auto_clip_sync_material_category_id)),
        "force_download": bool(force_download),
    }
    if download_output_folder:
        payload["download_output_folder"] = str(download_output_folder).strip()
    if not payload["app_id"]:
        raise AiCutAnimationError("ai-cut 创建任务失败: app_id 为空")
    if not payload["third_serial_ids"]:
        raise AiCutAnimationError("ai-cut 创建任务失败: third_serial_ids 为空")
    if len(payload["third_serial_ids"]) > 200:
        raise AiCutAnimationError("ai-cut 单次任务最多支持 200 个短剧 serial_id")
    response = request_json("POST", CREATE_PATH, payload=payload, timeout=timeout)
    return dict(response or {})


def get_short_drama_clip_task(task_id: str, *, timeout: int = DEFAULT_REQUEST_TIMEOUT) -> dict[str, Any]:
    normalized = str(task_id or "").strip()
    if not normalized:
        raise AiCutAnimationError("ai-cut 查询任务失败: task_id 为空")
    path = f"{CREATE_PATH}/{quote(normalized, safe='')}"
    response = request_json("GET", path, timeout=timeout)
    return dict(response or {})


def wait_for_short_drama_clip_task(
    task_id: str,
    *,
    timeout: int,
    poll_interval: float,
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> dict[str, Any]:
    deadline = time.time() + max(1, timeout)
    last_body: dict[str, Any] = {}
    while time.time() < deadline:
        raise_if_admin_task_failed(task_id, request_timeout=request_timeout)
        body = get_short_drama_clip_task(task_id, timeout=request_timeout)
        last_body = body
        raise_if_openapi_task_failed(body)
        status = str(body.get("status") or "").strip().lower()
        if status in FINAL_TASK_STATUSES and _clip_results_ready(body):
            return body
        time.sleep(max(1.0, float(poll_interval)))
    # Final recheck at the deadline boundary to avoid missing tasks that flip to
    # success immediately after the last queued poll.
    body = get_short_drama_clip_task(task_id, timeout=request_timeout)
    last_body = body
    raise_if_openapi_task_failed(body)
    status = str(body.get("status") or "").strip().lower()
    if status in FINAL_TASK_STATUSES and _clip_results_ready(body):
        return body
    snapshots = get_admin_task_snapshots(task_id, timeout=request_timeout)
    free_video = snapshots.get("free_video")
    if isinstance(free_video, dict) and _admin_status_category(free_video) == "failed":
        raise AiCutAnimationError(
            f"ai-cut 任务已失败: task_id={task_id}, {_admin_record_summary('free_video', free_video)}"
        )
    auto_clip = snapshots.get("auto_clip")
    if isinstance(auto_clip, dict) and _admin_status_category(auto_clip) == "failed":
        raise AiCutAnimationError(
            f"ai-cut 任务已失败: task_id={task_id}, {_admin_record_summary('auto_clip', auto_clip)}"
        )
    if _admin_task_still_running(snapshots) or _openapi_task_still_running(last_body):
        raise AiCutTaskStillRunningError(
            task_id,
            last_status=last_body.get("status"),
            snapshots=snapshots,
        )
    raise AiCutAnimationError(f"ai-cut 任务超时未完成: task_id={task_id}, last_status={last_body.get('status')}")


def _clip_results_ready(body: dict[str, Any]) -> bool:
    serials = body.get("serials")
    if not isinstance(serials, list) or not serials:
        return True
    for serial in serials:
        payload = serial if isinstance(serial, dict) else {}
        download_status = str(payload.get("download_status") or "").strip().lower()
        clip = payload.get("clip")
        if download_status in {"queued", "running"}:
            return False
        if isinstance(clip, dict):
            clip_status = str(clip.get("status") or "").strip().lower()
            if clip_status and clip_status not in FINAL_CLIP_STATUSES:
                return False
            if clip_status == "success":
                segments = clip.get("segments")
                if isinstance(segments, list) and any(
                    str((segment or {}).get("status") or "").strip().lower() == SEGMENT_SUCCESS_STATUS
                    and str((segment or {}).get("video_url") or "").strip()
                    for segment in segments
                ):
                    continue
                return False
        elif download_status == "success":
            return False
    return True


def raise_if_openapi_task_failed(body: dict[str, Any]) -> None:
    status = str(body.get("status") or "").strip().lower()
    serials = body.get("serials")
    if isinstance(serials, list):
        for serial in serials:
            payload = serial if isinstance(serial, dict) else {}
            download_status = str(payload.get("download_status") or "").strip().lower()
            clip = payload.get("clip")
            if download_status in {"failed", "skipped"} and not isinstance(clip, dict):
                raise AiCutAnimationError(describe_serial_failure(payload))
            if isinstance(clip, dict):
                clip_status = str(clip.get("status") or "").strip().lower()
                if clip_status in {"failed", "cancelled"}:
                    raise AiCutAnimationError(describe_serial_failure(payload))
    if status in {"failed", "cancelled"}:
        raise AiCutAnimationError(f"ai-cut 任务已失败: task_id={body.get('task_id')}, status={status}")


def choose_success_segment(serial_payload: dict[str, Any], *, preferred_episode_order: int) -> dict[str, Any] | None:
    clip = serial_payload.get("clip")
    if not isinstance(clip, dict):
        return None
    segments = clip.get("segments")
    if not isinstance(segments, list):
        return None
    successful = [dict(item) for item in segments if str(item.get("status") or "").strip().lower() == SEGMENT_SUCCESS_STATUS]
    if not successful:
        return None

    def sort_key(item: dict[str, Any]) -> tuple[int, float, int]:
        episode_order = int(item.get("episode_order") or 0)
        duration = float(item.get("duration") or 0.0)
        segment_index = int(item.get("segment_index") or 0)
        return (
            0 if episode_order == int(preferred_episode_order or 0) else 1,
            -duration,
            segment_index,
        )

    successful.sort(key=sort_key)
    return successful[0]


def wait_for_serial_success_segment(
    task_id: str,
    *,
    third_serial_id: str,
    preferred_episode_order: int,
    timeout: int,
    poll_interval: float,
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
    initial_task_body: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    deadline = time.time() + max(1, timeout)
    last_task_body = dict(initial_task_body or {})
    last_serial_payload: dict[str, Any] | None = None
    normalized_serial_id = str(third_serial_id or "").strip()
    if not normalized_serial_id:
        return last_task_body, None, None

    while time.time() < deadline:
        raise_if_admin_task_failed(task_id, request_timeout=request_timeout)
        if last_task_body:
            raise_if_openapi_task_failed(last_task_body)
        if last_task_body:
            for payload in (last_task_body.get("serials") or []):
                if str((payload or {}).get("third_serial_id") or "").strip() != normalized_serial_id:
                    continue
                last_serial_payload = dict(payload)
                chosen = choose_success_segment(last_serial_payload, preferred_episode_order=preferred_episode_order)
                if chosen:
                    return last_task_body, last_serial_payload, chosen
                clip = last_serial_payload.get("clip") if isinstance(last_serial_payload.get("clip"), dict) else {}
                clip_status = str((clip or {}).get("status") or "").strip().lower()
                download_status = str(last_serial_payload.get("download_status") or "").strip().lower()
                if clip_status in FINAL_CLIP_STATUSES:
                    return last_task_body, last_serial_payload, None
                if download_status in FINAL_TASK_STATUSES and not clip:
                    return last_task_body, last_serial_payload, None
                break
        time.sleep(max(1.0, float(poll_interval)))
        last_task_body = get_short_drama_clip_task(task_id, timeout=request_timeout)
        raise_if_openapi_task_failed(last_task_body)
    # Final recheck at the timeout boundary for the same reason as above.
    raise_if_admin_task_failed(task_id, request_timeout=request_timeout)
    last_task_body = get_short_drama_clip_task(task_id, timeout=request_timeout)
    raise_if_openapi_task_failed(last_task_body)
    for payload in (last_task_body.get("serials") or []):
        if str((payload or {}).get("third_serial_id") or "").strip() != normalized_serial_id:
            continue
        last_serial_payload = dict(payload)
        chosen = choose_success_segment(last_serial_payload, preferred_episode_order=preferred_episode_order)
        if chosen:
            return last_task_body, last_serial_payload, chosen
        break
    return last_task_body, last_serial_payload, None


def describe_serial_failure(serial_payload: dict[str, Any]) -> str:
    title = str(serial_payload.get("title") or serial_payload.get("third_serial_id") or "").strip()
    download_status = str(serial_payload.get("download_status") or "").strip()
    clip = serial_payload.get("clip")
    if not isinstance(clip, dict):
        if download_status:
            return f"{title} 下载状态={download_status or 'unknown'}，尚未进入剪辑"
        return f"{title} 尚未产出可用剪辑片段"
    clip_status = str(clip.get("status") or "").strip()
    segments = clip.get("segments")
    last_errors: list[str] = []
    if isinstance(segments, list):
        for item in segments:
            message = str((item or {}).get("last_error") or "").strip()
            if message:
                last_errors.append(message)
    error_text = "；".join(last_errors[:3])
    if error_text:
        return f"{title} 下载状态={download_status or 'unknown'}，剪辑状态={clip_status or 'unknown'}，错误={error_text}"
    return f"{title} 下载状态={download_status or 'unknown'}，剪辑状态={clip_status or 'unknown'}，没有成功片段"


def download_segment_video(
    video_url: str,
    *,
    output_path: str | Path,
    timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
) -> str:
    normalized_url = str(video_url or "").strip()
    if not normalized_url:
        raise AiCutAnimationError("ai-cut 下载失败: video_url 为空")
    target_path = Path(output_path).expanduser().resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(normalized_url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with target_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
    except requests.RequestException as exc:
        raise AiCutAnimationError(f"ai-cut 下载片段失败: {exc}") from exc
    return str(target_path)
