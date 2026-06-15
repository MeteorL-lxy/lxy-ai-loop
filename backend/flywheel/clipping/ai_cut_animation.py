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
ENV_FILE = Path.home() / ".ai-beidou" / "state.env"
CREATE_PATH = "/openapi/v1/short-drama-clip-tasks"
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


class AiCutAnimationError(RuntimeError):
    """OpenAPI 调用异常。"""


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
        body = get_short_drama_clip_task(task_id, timeout=request_timeout)
        last_body = body
        status = str(body.get("status") or "").strip().lower()
        if status in FINAL_TASK_STATUSES and _clip_results_ready(body):
            return body
        time.sleep(max(1.0, float(poll_interval)))
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
