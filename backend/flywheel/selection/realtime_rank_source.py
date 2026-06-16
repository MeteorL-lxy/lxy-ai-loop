from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from inbeidou_cli import get_tasks, require_success

from .history_filter import normalize_title_token


GUANGDADA_API_BASE = (
    os.getenv("BARRY_GUANGDADA_API_BASE")
    or "https://test-api-ai-guangdada.inbeidou.cn"
).rstrip("/")
GUANGDADA_TOKEN = os.getenv("BARRY_GUANGDADA_TOKEN") or "9f4d7456-8932-4419-9b72-1d73b0a03b28"
SUPPORTED_REALTIME_APPS = {
    "kalos",
    "snackshort",
    "goodshort",
    "moboreels",
    "touchshort",
    "flickreels",
    "reelshort",
    "dramabox",
    "shortmax",
}
REALTIME_APP_ALIASES = {
    "goodshort": "goodshort",
    "good short": "goodshort",
    "snackshort": "snackshort",
    "snack short": "snackshort",
    "touchshort": "touchshort",
    "touch short": "touchshort",
    "flickreels": "flickreels",
    "flick reels": "flickreels",
    "freereels": "flickreels",
    "free reels": "flickreels",
    "moboreels": "moboreels",
    "mobo reels": "moboreels",
    "kalos": "kalos",
    "kalostv": "kalos",
    "kalos tv": "kalos",
    "reelshort": "reelshort",
    "reel short": "reelshort",
    "dramabox": "dramabox",
    "drama box": "dramabox",
    "shortmax": "shortmax",
    "short max": "shortmax",
}
RANKED_PLATFORM_MAP = {
    "TIKTOK": "tiktok",
    "FACEBOOK": "facebook",
    "INSTAGRAM": "instagram",
    "YOUTUBE": "youtube",
}
_ANCHOR_CACHE: dict[tuple[str, str, str], dict[str, Any] | None] = {}
_REALTIME_EXTERNAL_LOOKUP_FAIL_LIMIT = 3
ROOT_DIR = Path(__file__).resolve().parents[3]
REALTIME_CACHE_DIR = Path(
    os.getenv("BARRY_REALTIME_CACHE_DIR")
    or (ROOT_DIR / "runtime" / "realtime-rank-cache")
).expanduser()
CREATIVE_LIST_CACHE_DIR = Path(
    os.getenv("BARRY_CREATIVE_LIST_CACHE_DIR")
    or (ROOT_DIR / "runtime" / "creative-list-cache")
).expanduser()
CREATIVE_LIST_ROTATION_APPS = [
    "reelshort",
    "goodshort",
    "shortmax",
    "dramabox",
    "moboreels",
    "flickreels",
    "snackshort",
    "touchshort",
    "kalos",
]
REALTIME_RANK_LINES = {"realtime", "realtime_day", "realtime_single"}
GUANGDADA_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _priority_boost_env(name: str, default: float) -> float:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _realtime_matched_priority_boost() -> float:
    return _priority_boost_env("BARRY_REALTIME_MATCHED_PRIORITY_BOOST", 0.55)


def _realtime_external_priority_boost() -> float:
    return _priority_boost_env("BARRY_REALTIME_EXTERNAL_PRIORITY_BOOST", 0.9)


def fetch_realtime_rank_candidates(
    config,
    *,
    target_publish_platforms: list[str] | None = None,
    search: str = "",
    target_size: int = 30,
) -> list[dict[str, Any]]:
    if search.strip() or not config.realtime_rank_enabled:
        return []
    target_publish_platforms = target_publish_platforms or []
    if _hourly_realtime_cache_enabled():
        cached_payload = _load_realtime_candidate_hour_cache(target_publish_platforms=target_publish_platforms)
        if cached_payload is not None:
            if bool(cached_payload.get("exhausted")):
                return []
            cached = cached_payload.get("candidates")
            if isinstance(cached, list):
                return cached[: max(0, int(target_size or 0)) or len(cached)]
    try:
        records = _load_or_fetch_realtime_hour_records(
            config,
            target_publish_platforms=target_publish_platforms,
        )
        candidates = _build_realtime_candidates_from_records(
            config,
            records=records,
            target_publish_platforms=target_publish_platforms,
            target_size=target_size,
        )
        if _hourly_realtime_cache_enabled():
            _save_realtime_candidate_hour_cache(
                target_publish_platforms=target_publish_platforms,
                candidates=candidates,
                source_record_count=len(records),
            )
        return candidates
    except Exception:
        return []


def _load_or_fetch_realtime_hour_records(
    config,
    *,
    target_publish_platforms: list[str],
) -> list[dict[str, Any]]:
    if _hourly_realtime_cache_enabled():
        cached_records = _load_realtime_raw_hour_cache(target_publish_platforms=target_publish_platforms)
        if cached_records is not None:
            return cached_records
    request_payload = _build_realtime_request_payload(target_publish_platforms)
    response = _zing_post(
        "/api/zing/playlet/realtime-list",
        request_payload,
        timeout=config.realtime_rank_timeout_seconds,
    )
    records = _extract_realtime_records(response)
    if _hourly_realtime_cache_enabled():
        _save_realtime_raw_hour_cache(
            target_publish_platforms=target_publish_platforms,
            records=records,
        )
    return records


def _build_realtime_candidates_from_records(
    config,
    *,
    records: list[dict[str, Any]],
    target_publish_platforms: list[str],
    target_size: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    external_lookup_failures = 0
    max_candidates = max(target_size, min(config.realtime_rank_max_candidates, max(target_size * 2, 10)))
    publish_platform = _preferred_publish_platform(target_publish_platforms)

    for record in records:
        try:
            title = str(record.get("playlet_search_name") or "").strip()
            if not title:
                continue
            inferred_app_id = _infer_app_id(record)
            official_match = _match_official_drama(title, inferred_app_id)
            record_candidates: list[dict[str, Any]] = []
            if inferred_app_id and config.realtime_rank_external_first:
                external_lookup_state = {"count": external_lookup_failures}
                record_candidates = _try_build_external_candidates(
                    record,
                    inferred_app_id=inferred_app_id,
                    official_match=official_match,
                    publish_platform=publish_platform,
                    timeout=config.realtime_rank_timeout_seconds,
                    external_lookup_failures_ref=external_lookup_state,
                )
                external_lookup_failures = int(external_lookup_state.get("count") or external_lookup_failures)
                for candidate in record_candidates:
                    candidate.pop("_external_lookup_failures", None)
            if not record_candidates and official_match and str(official_match.get("third_serial_id") or "").strip():
                record_candidates = [_build_matched_candidate(record, official_match)]
            if not record_candidates and inferred_app_id:
                external_lookup_state = {"count": external_lookup_failures}
                record_candidates = _try_build_external_candidates(
                    record,
                    inferred_app_id=inferred_app_id,
                    official_match=official_match,
                    publish_platform=publish_platform,
                    timeout=config.realtime_rank_timeout_seconds,
                    external_lookup_failures_ref=external_lookup_state,
                )
                external_lookup_failures = int(external_lookup_state.get("count") or external_lookup_failures)
                for candidate in record_candidates:
                    candidate.pop("_external_lookup_failures", None)
            if not record_candidates:
                continue
        except Exception:
            continue

        for candidate in record_candidates:
            dedupe_key = (
                str(candidate.get("candidate_fetch_source") or ""),
                str(
                    candidate.get("external_asset_key")
                    or candidate.get("external_video_url")
                    or candidate.get("serial_id")
                    or candidate.get("realtime_name_md5")
                    or ""
                ),
            )
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            candidates.append(candidate)
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break

    return candidates[:max_candidates]


def _try_build_external_candidates(
    record: dict[str, Any],
    *,
    inferred_app_id: str,
    official_match: dict[str, Any] | None,
    publish_platform: str,
    timeout: float,
    external_lookup_failures_ref: dict[str, int],
) -> list[dict[str, Any]]:
    current_failures = int(external_lookup_failures_ref.get("count") or 0)
    title = str(record.get("playlet_search_name") or "").strip() or inferred_app_id
    if current_failures >= _REALTIME_EXTERNAL_LOOKUP_FAIL_LIMIT:
        return []
    try:
        external_assets = _fetch_external_video_assets(
            str(record.get("name_md5") or "").strip(),
            timeout=_external_video_lookup_timeout(timeout),
        )
    except Exception as exc:
        external_lookup_failures_ref["count"] = current_failures + 1
        _log_realtime_skip(
            f"实时榜候选 {title} 获取 creative/list 失败，已跳过并继续下一条：{exc}"
        )
        return []
    if not external_assets:
        return []
    anchor = _find_anchor_drama(
        inferred_app_id,
        publish_platform=publish_platform,
        preferred_language=str((official_match or {}).get("language") or "").strip(),
    )
    if not anchor:
        return []
    candidates: list[dict[str, Any]] = []
    for external_asset in external_assets:
        video_url = str(external_asset.get("video_url") or "").strip()
        if not video_url:
            continue
        candidate = _build_external_candidate(
            record,
            inferred_app_id,
            video_url,
            anchor,
            official_match=official_match,
            duration_seconds=int(external_asset.get("duration_seconds") or 0),
            external_asset_key=str(external_asset.get("asset_key") or "").strip(),
            external_creative_ad_key=str(external_asset.get("creative_ad_key") or "").strip(),
        )
        candidate["_external_lookup_failures"] = int(external_lookup_failures_ref.get("count") or 0)
        candidates.append(candidate)
    return candidates


def _build_realtime_request_payload(target_publish_platforms: list[str]) -> dict[str, Any]:
    platforms = [
        mapped
        for mapped in (
            RANKED_PLATFORM_MAP.get(str(value).strip().upper())
            for value in target_publish_platforms
        )
        if mapped
    ]
    if not platforms:
        return {}
    return {"platform": ",".join(sorted(dict.fromkeys(platforms)))}


def _zing_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if GUANGDADA_TOKEN:
        headers["Authorization"] = f"Bearer {GUANGDADA_TOKEN}"
    return headers


def _is_retryable_guangdada_error(exc: requests.RequestException) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in GUANGDADA_RETRYABLE_STATUS_CODES:
        return True
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    text = str(exc or "").lower()
    return any(
        token in text
        for token in (
            "502",
            "503",
            "504",
            "timeout",
            "timed out",
            "connection aborted",
            "bad gateway",
        )
    )


def _guangdada_retry_attempts() -> int:
    return max(1, int(os.getenv("BARRY_GUANGDADA_RETRY_ATTEMPTS") or 4))


def _guangdada_retry_sleep_seconds(attempt: int) -> float:
    base = float(os.getenv("BARRY_GUANGDADA_RETRY_SLEEP_SECONDS") or 1.5)
    return min(6.0, max(0.5, base) * max(1.0, float(attempt)))


def _zing_post(path: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    request_timeout = max(15.0, float(timeout))
    max_attempts = _guangdada_retry_attempts()
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                f"{GUANGDADA_API_BASE}{path}",
                json=payload,
                headers=_zing_headers(),
                timeout=request_timeout,
            )
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_retryable_guangdada_error(exc):
                raise RuntimeError(f"实时剧目榜请求失败: {exc}") from exc
            _log_realtime_skip(
                f"广大大接口请求重试 {attempt}/{max_attempts - 1}：{path}，原因={exc}"
            )
            time.sleep(_guangdada_retry_sleep_seconds(attempt))
    else:
        raise RuntimeError(f"实时剧目榜请求失败: {last_exc}")
    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError(f"实时剧目榜返回非 JSON: {response.text[:200]}") from exc
    if str(body.get("id") or "").upper() != "SUCCESS":
        raise RuntimeError(f"实时剧目榜返回失败: {body.get('message') or body}")
    data = body.get("data")
    return data if isinstance(data, dict) else {"list": data if isinstance(data, list) else []}


def _extract_realtime_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("list", "playlet_list", "realtime_list"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [dict(item) for item in rows if isinstance(item, dict)]
    return []


def _hourly_realtime_cache_enabled() -> bool:
    line_name = _current_realtime_line_name()
    material_only = str(os.getenv("BARRY_LOOP_REALTIME_MATERIAL_ONLY") or "0").strip().lower()
    return line_name in REALTIME_RANK_LINES and material_only in {"1", "true", "yes", "on"}


def _current_realtime_line_name() -> str:
    return str(os.getenv("BARRY_LOOP_LINE_NAME") or "").strip().lower()


def _realtime_cache_hour_token() -> str:
    return datetime.now().strftime("%Y%m%d%H")


def _realtime_cache_platform_key(target_publish_platforms: list[str]) -> str:
    values = [str(value or "").strip().upper() for value in target_publish_platforms if str(value or "").strip()]
    if not values:
        return "ALL"
    return "_".join(sorted(dict.fromkeys(values)))


def _realtime_raw_cache_path(*, target_publish_platforms: list[str]) -> Path:
    hour = _realtime_cache_hour_token()
    platform_key = _realtime_cache_platform_key(target_publish_platforms)
    return REALTIME_CACHE_DIR / f"realtime_raw_{platform_key}_{hour}.json"


def _realtime_candidate_cache_path(*, target_publish_platforms: list[str]) -> Path:
    hour = _realtime_cache_hour_token()
    platform_key = _realtime_cache_platform_key(target_publish_platforms)
    line_name = _current_realtime_line_name() or "realtime"
    return REALTIME_CACHE_DIR / line_name / f"realtime_material_{platform_key}_{hour}.json"


def _lookup_cache_key(prefix: str, identity: str) -> str:
    digest = hashlib.sha1(str(identity or "").encode("utf-8")).hexdigest()[:16]
    normalized_prefix = str(prefix or "lookup").strip() or "lookup"
    return f"{normalized_prefix}_{digest}.json"


def _lookup_cache_path(cache_root: Path, *, prefix: str, identity: str) -> Path:
    return cache_root / "lookup-cache" / _lookup_cache_key(prefix, identity)


def _load_lookup_cache(
    cache_root: Path,
    *,
    prefix: str,
    identity: str,
) -> list[dict[str, Any]] | None:
    path = _lookup_cache_path(cache_root, prefix=prefix, identity=identity)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    expires_at = str(payload.get("expires_at") or "").strip()
    if expires_at:
        try:
            if datetime.now(timezone.utc) >= datetime.fromisoformat(expires_at):
                return None
        except ValueError:
            return None
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return None
    return [dict(item) for item in assets if isinstance(item, dict)]


def _save_lookup_cache(
    cache_root: Path,
    *,
    prefix: str,
    identity: str,
    assets: list[dict[str, Any]],
    ttl_seconds: int,
) -> None:
    ttl = max(30, int(ttl_seconds or 0))
    path = _lookup_cache_path(cache_root, prefix=prefix, identity=identity)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat(),
        "asset_count": len(assets),
        "assets": assets,
    }
    _atomic_write_json(path, payload)


def _load_realtime_raw_hour_cache(*, target_publish_platforms: list[str]) -> list[dict[str, Any]] | None:
    path = _realtime_raw_cache_path(target_publish_platforms=target_publish_platforms)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if str(payload.get("fetched_hour") or "") != _realtime_cache_hour_token():
        return None
    rows = payload.get("records")
    if not isinstance(rows, list):
        return None
    return [dict(item) for item in rows if isinstance(item, dict)]


def _save_realtime_raw_hour_cache(*, target_publish_platforms: list[str], records: list[dict[str, Any]]) -> None:
    path = _realtime_raw_cache_path(target_publish_platforms=target_publish_platforms)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_hour": _realtime_cache_hour_token(),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "platforms": [str(value or "").strip().upper() for value in target_publish_platforms if str(value or "").strip()],
        "record_count": len(records),
        "records": records,
    }
    _atomic_write_json(path, payload)


def _load_realtime_candidate_hour_cache(*, target_publish_platforms: list[str]) -> dict[str, Any] | None:
    path = _realtime_candidate_cache_path(target_publish_platforms=target_publish_platforms)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if str(payload.get("fetched_hour") or "") != _realtime_cache_hour_token():
        return None
    candidates = payload.get("candidates")
    if candidates is not None and not isinstance(candidates, list):
        return None
    return payload


def _save_realtime_candidate_hour_cache(
    *,
    target_publish_platforms: list[str],
    candidates: list[dict[str, Any]],
    source_record_count: int,
    exhausted: bool = False,
    exhausted_reason: str = "",
) -> None:
    path = _realtime_candidate_cache_path(target_publish_platforms=target_publish_platforms)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_hour": _realtime_cache_hour_token(),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "line_name": _current_realtime_line_name() or "realtime",
        "platforms": [str(value or "").strip().upper() for value in target_publish_platforms if str(value or "").strip()],
        "source_record_count": max(0, int(source_record_count or 0)),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "exhausted": bool(exhausted),
        "exhausted_reason": str(exhausted_reason or "").strip(),
        "exhausted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if exhausted else "",
    }
    _atomic_write_json(path, payload)


def mark_realtime_hour_exhausted(reason: str, *, target_publish_platforms: list[str] | None = None) -> None:
    if not _hourly_realtime_cache_enabled():
        return
    platforms = target_publish_platforms or []
    path = _realtime_candidate_cache_path(target_publish_platforms=platforms)
    payload = _load_realtime_candidate_hour_cache(target_publish_platforms=platforms) or {
        "fetched_hour": _realtime_cache_hour_token(),
        "updated_at": "",
        "line_name": _current_realtime_line_name() or "realtime",
        "platforms": [str(value or "").strip().upper() for value in platforms if str(value or "").strip()],
        "source_record_count": 0,
        "candidate_count": 0,
        "candidates": [],
    }
    payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload["exhausted"] = True
    payload["exhausted_reason"] = str(reason or "").strip()
    payload["exhausted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, payload)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _normalize_timestamp(value: Any) -> str:
    try:
        raw = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if raw <= 0:
        return ""
    if raw > 10_000_000_000:
        raw = raw // 1000
    return datetime.fromtimestamp(raw, tz=timezone.utc).isoformat()


def _normalize_app_key(value: str) -> str:
    normalized = (value or "").strip().lower()
    for token in (" - ", " – ", " — ", "|", "·", "•", ":", "："):
        if token in normalized:
            normalized = normalized.split(token, 1)[0].strip()
    return normalized


def _bundle_to_app_key(value: str) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        return ""
    parts = [part for part in normalized.split(".") if part]
    if len(parts) >= 3 and parts[0] in {"com", "app", "net", "io"}:
        return parts[1].strip()
    if len(parts) >= 2:
        return parts[-2].strip()
    return normalized


def _resolve_app_alias(value: str) -> str:
    normalized = _normalize_app_key(value)
    if not normalized:
        return ""
    mapped = REALTIME_APP_ALIASES.get(normalized, normalized)
    return mapped if mapped in SUPPORTED_REALTIME_APPS else ""


def _infer_app_id(record: dict[str, Any]) -> str:
    advertisers = record.get("playlet_advertisers")
    if isinstance(advertisers, list):
        for advertiser in advertisers:
            if not isinstance(advertiser, dict):
                continue
            for value in (
                str(advertiser.get("advertiser_name") or ""),
                str(advertiser.get("advertiser_id") or ""),
                str(advertiser.get("domain") or ""),
            ):
                if not value:
                    continue
                for candidate in (value, _bundle_to_app_key(value)):
                    app_id = _resolve_app_alias(candidate)
                    if app_id:
                        return app_id
    app_id = _resolve_app_alias(str(record.get("playlet_search_name") or ""))
    if app_id:
        return app_id
    return ""


def _candidate_titles(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("title", "title_ch", "title_en"):
        normalized = str(row.get(key) or "").strip()
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _match_official_drama(title: str, app_id: str) -> dict[str, Any] | None:
    body = require_success(
        get_tasks(
            page=1,
            page_size=20,
            platform=app_id,
            language="",
            search=title,
            order="publish_at",
            task_type="1",
        ),
        f"实时榜匹配北斗剧库 {title}",
    )
    rows = body.get("data", []) if isinstance(body, dict) else []
    normalized_title = normalize_title_token(title)
    exact_matches: list[dict[str, Any]] = []
    loose_matches: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        titles = _candidate_titles(row)
        if any(normalize_title_token(candidate) == normalized_title for candidate in titles):
            exact_matches.append(dict(row))
        elif normalized_title and any(
            normalized_title in normalize_title_token(candidate) or normalize_title_token(candidate) in normalized_title
            for candidate in titles
            if normalize_title_token(candidate)
        ):
            loose_matches.append(dict(row))
    candidates = exact_matches or loose_matches
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            1 if str(item.get("app_id") or "").strip() == app_id else 0,
            1 if str(item.get("third_serial_id") or "").strip() else 0,
            str(item.get("publish_at") or ""),
        ),
        reverse=True,
    )
    return candidates[0]


def _extract_external_video_duration_seconds(row: dict[str, Any], resource: dict[str, Any]) -> int:
    for value in (
        resource.get("duration"),
        resource.get("video_duration"),
        resource.get("file_duration"),
        resource.get("play_time"),
        row.get("duration"),
        row.get("video_duration"),
        row.get("file_duration"),
        row.get("play_time"),
    ):
        try:
            seconds = int(float(value or 0))
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return seconds
    return 0


def _estimate_external_output_count(duration_seconds: int) -> int:
    seconds = max(0, int(duration_seconds or 0))
    if seconds <= 0:
        return 1
    if seconds >= 240:
        return 3
    if seconds >= 120:
        return 2
    return 1


def _build_external_asset_key(*, name_md5: str, creative_ad_key: str, resource_index: int, video_url: str) -> str:
    ad_key = str(creative_ad_key or "").strip()
    if ad_key:
        return f"{ad_key}:{max(0, int(resource_index or 0))}"
    digest = hashlib.sha1(video_url.encode("utf-8")).hexdigest()[:12]
    prefix = str(name_md5 or "").strip() or "realtime"
    return f"{prefix}:{digest}"


def _fetch_external_video_assets(name_md5: str, *, timeout: float) -> list[dict[str, Any]]:
    if not name_md5:
        return []
    cached_assets = _load_lookup_cache(
        REALTIME_CACHE_DIR,
        prefix="external-assets",
        identity=name_md5,
    )
    if cached_assets is not None:
        return cached_assets
    payload = {
        "app_type": 2,
        "page": 1,
        "page_size": 10,
        "duplicate_removal": 1,
        "is_theater": 1,
        "sort_field": "-impression",
        "playlet_md5": name_md5,
    }
    response = _zing_post("/api/zing/creative/list", payload, timeout=timeout)
    rows = response.get("creative_list") if isinstance(response.get("creative_list"), list) else []
    assets: list[dict[str, Any]] = []
    seen_video_urls: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        resource_urls = row.get("resource_urls")
        if not isinstance(resource_urls, list):
            continue
        creative_ad_key = str(row.get("ad_key") or "").strip()
        for resource_index, resource in enumerate(resource_urls):
            if not isinstance(resource, dict):
                continue
            video_url = str(resource.get("video_url") or "").strip()
            if not video_url or video_url in seen_video_urls:
                continue
            seen_video_urls.add(video_url)
            assets.append(
                {
                    "video_url": video_url,
                    "duration_seconds": _extract_external_video_duration_seconds(row, resource),
                    "creative_ad_key": creative_ad_key,
                    "asset_key": _build_external_asset_key(
                        name_md5=name_md5,
                        creative_ad_key=creative_ad_key,
                        resource_index=resource_index,
                        video_url=video_url,
                    ),
                }
            )
    _save_lookup_cache(
        REALTIME_CACHE_DIR,
        prefix="external-assets",
        identity=name_md5,
        assets=assets,
        ttl_seconds=3600 if assets else 600,
    )
    return assets


def _external_video_lookup_timeout(timeout: float) -> float:
    try:
        value = float(timeout)
    except (TypeError, ValueError):
        value = 180.0
    return max(15.0, min(value, 180.0))


def _log_realtime_skip(message: str) -> None:
    print(f"[realtime-rank] {message}", file=sys.stderr, flush=True)


def _preferred_publish_platform(target_publish_platforms: list[str]) -> str:
    for value in target_publish_platforms:
        normalized = str(value or "").strip().upper()
        if normalized:
            return normalized
    return "FACEBOOK"


def _find_anchor_drama(app_id: str, *, publish_platform: str, preferred_language: str = "") -> dict[str, Any] | None:
    cache_key = (str(app_id or "").strip(), str(publish_platform or "").strip().upper(), str(preferred_language or "").strip())
    if cache_key in _ANCHOR_CACHE:
        return _ANCHOR_CACHE[cache_key]

    for language in [preferred_language, ""]:
        body = require_success(
            get_tasks(
                page=1,
                page_size=20,
                platform=app_id,
                language=language,
                search="",
                order="publish_at",
                task_type="1",
            ),
            f"获取实时榜锚点剧 {app_id}",
        )
        rows = body.get("data", []) if isinstance(body, dict) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_app_id = str(row.get("app_id") or "").strip()
            if row_app_id != app_id:
                continue
            if not str(row.get("task_id") or "").strip():
                continue
            anchor = {
                "task_id": str(row.get("task_id") or "").strip(),
                "serial_id": str(row.get("serial_id") or "").strip(),
                "app_id": row_app_id or app_id,
                "task_type": str(row.get("task_type") or "1").strip() or "1",
                "title": str(row.get("title") or "").strip(),
                "language": str(row.get("language") or "").strip(),
            }
            _ANCHOR_CACHE[cache_key] = anchor
            return anchor
    _ANCHOR_CACHE[cache_key] = None
    return None


def _base_realtime_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "tag": ",".join(str(item).strip() for item in (record.get("tags") or []) if str(item).strip()),
        "publish_at": _normalize_timestamp(record.get("last_seen") or record.get("created_at") or record.get("first_seen")),
        "promoter_number": int(record.get("creative_count") or 0),
        "target_count": int(record.get("new_creative_count") or 0),
        "weight": float(record.get("heat") or 0),
        "description": f"heat={record.get('heat') or 0}; impression={record.get('impression') or 0}",
        "realtime_name_md5": str(record.get("name_md5") or "").strip(),
        "realtime_heat": float(record.get("heat") or 0),
        "realtime_impression": int(record.get("impression") or 0),
        "candidate_source_platform": "guangdada_realtime",
    }


def _build_matched_candidate(record: dict[str, Any], official_row: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(official_row)
    candidate.update(_base_realtime_fields(record))
    candidate["candidate_fetch_source"] = "realtime_rank_matched"
    candidate["candidate_priority_boost"] = _realtime_matched_priority_boost()
    candidate["source_mode"] = "official"
    return candidate


def _build_external_candidate(
    record: dict[str, Any],
    app_id: str,
    video_url: str,
    anchor: dict[str, Any],
    *,
    official_match: dict[str, Any] | None,
    duration_seconds: int,
    external_asset_key: str,
    external_creative_ad_key: str,
) -> dict[str, Any]:
    title = str(record.get("playlet_search_name") or "").strip()
    name_md5 = str(record.get("name_md5") or "").strip()
    matched_task_id = str((official_match or {}).get("task_id") or "").strip()
    matched_task_type = str((official_match or {}).get("task_type") or "1").strip() or "1"
    matched_language = str((official_match or {}).get("language") or "").strip()
    normalized_asset_key = str(external_asset_key or "").strip()
    serial_suffix = normalized_asset_key or hashlib.sha1(video_url.encode("utf-8")).hexdigest()[:12]
    base_serial = name_md5 or normalize_title_token(title) or "unknown"
    candidate = {
        "serial_id": f"realtime:{base_serial}:{serial_suffix}",
        "task_id": matched_task_id or str(anchor.get("task_id") or "").strip(),
        "task_type": matched_task_type if matched_task_id else (str(anchor.get("task_type") or "1").strip() or "1"),
        "app_id": app_id,
        "title": title,
        "title_ch": title,
        "title_en": title,
        "language": matched_language or str(anchor.get("language") or "").strip(),
        "third_serial_id": "",
        "external_video_url": video_url,
        "external_asset_key": normalized_asset_key,
        "external_creative_ad_key": str(external_creative_ad_key or "").strip(),
        "external_video_duration_seconds": max(0, int(duration_seconds or 0)),
        "external_estimated_output_count": _estimate_external_output_count(duration_seconds),
        "source_mode": "external_video",
        "candidate_fetch_source": "realtime_rank_external",
        "candidate_priority_boost": _realtime_external_priority_boost(),
        "promotion_anchor": anchor,
        "candidate_variant_count": 1,
        "candidate_variant_languages": [matched_language or str(anchor.get("language") or "").strip()] if (matched_language or str(anchor.get("language") or "").strip()) else [],
        "candidate_variant_serial_ids": [f"realtime:{base_serial}:{serial_suffix}"],
        "candidate_variant_task_ids": [matched_task_id] if matched_task_id else [],
        "external_keys": [
            key
            for key in (
                f"realtime_md5:{name_md5}" if name_md5 else "",
                f"realtime_asset:{normalized_asset_key}" if normalized_asset_key else "",
            )
            if key
        ],
        "matched_official_serial_id": str((official_match or {}).get("serial_id") or "").strip(),
        "matched_official_task_id": matched_task_id,
        "matched_official_task_type": matched_task_type if matched_task_id else "",
        "matched_official_language": matched_language,
    }
    candidate.update(_base_realtime_fields(record))
    return candidate


def fetch_creative_list_candidates(
    config,
    *,
    target_publish_platforms: list[str] | None = None,
    target_size: int = 30,
    line_name: str = "",
) -> list[dict[str, Any]]:
    publish_platform = _preferred_publish_platform(target_publish_platforms or [])
    desired_size = max(1, int(target_size or 0))
    collected: list[dict[str, Any]] = []
    exhausted_apps: set[str] = set()

    while len(collected) < desired_size and len(exhausted_apps) < len(CREATIVE_LIST_ROTATION_APPS):
        active_app_id = _creative_list_active_app_id(line_name=line_name)
        if not active_app_id:
            break
        if active_app_id in exhausted_apps:
            break

        while len(collected) < desired_size:
            batch_candidates, app_exhausted = _fetch_creative_list_candidates_for_app(
                config,
                publish_platform=publish_platform,
                target_size=max(desired_size - len(collected), 1),
                line_name=line_name,
                app_id=active_app_id,
            )
            if batch_candidates:
                collected.extend(batch_candidates)
            if app_exhausted:
                exhausted_apps.add(active_app_id)
                break
            if batch_candidates:
                continue

    if collected:
        return collected[:desired_size]
    _log_realtime_skip("创意列表整轮剧场已扫空：当前轮转内没有命中可下载外部素材。")
    return []


def _creative_list_state_path(*, line_name: str, app_id: str) -> Path:
    normalized_line = str(line_name or "creative_list").strip().lower() or "creative_list"
    normalized_app = str(app_id or "unknown").strip().lower() or "unknown"
    return CREATIVE_LIST_CACHE_DIR / normalized_line / f"{normalized_app}.json"


def _creative_list_rotation_path(*, line_name: str) -> Path:
    normalized_line = str(line_name or "creative_list").strip().lower() or "creative_list"
    return CREATIVE_LIST_CACHE_DIR / normalized_line / "rotation.json"


def _creative_list_cached_count(state: dict[str, Any]) -> int:
    try:
        return max(0, int(state.get("cached_candidate_count") or len(_creative_list_cached_candidates(state))))
    except Exception:
        return 0


def _creative_list_consumed_count(state: dict[str, Any]) -> int:
    try:
        return max(0, int(state.get("consumed_count") or len(_creative_list_consumed_serial_ids(line_name="", app_id="", state=state))))
    except Exception:
        return 0


def _creative_list_window_start_page(state: dict[str, Any]) -> int:
    try:
        return max(1, int(state.get("window_start_page") or 1))
    except Exception:
        return 1


def _creative_list_scan_completed(state: dict[str, Any]) -> bool:
    raw = state.get("scan_completed")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    cached_count = _creative_list_cached_count(state)
    consumed_count = _creative_list_consumed_count(state)
    return cached_count <= 0 and consumed_count >= 1000


def _creative_list_exhausted_app_ids(*, line_name: str) -> set[str]:
    exhausted: set[str] = set()
    for app_id in CREATIVE_LIST_ROTATION_APPS:
        state = _load_creative_list_state(line_name=line_name, app_id=app_id)
        if _creative_list_cached_count(state) <= 0 and _creative_list_scan_completed(state):
            exhausted.add(app_id)
    return exhausted


def _creative_list_active_app_id(*, line_name: str) -> str:
    normalized_line = str(line_name or "creative_list").strip().lower() or "creative_list"
    path = _creative_list_rotation_path(line_name=normalized_line)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    exhausted_apps = _creative_list_exhausted_app_ids(line_name=normalized_line)
    current_app_id = str(payload.get("current_app_id") or payload.get("last_app_id") or "").strip().lower()
    if current_app_id and current_app_id not in exhausted_apps:
        state = _load_creative_list_state(line_name=normalized_line, app_id=current_app_id)
        cached_count = _creative_list_cached_count(state)
        scan_completed = _creative_list_scan_completed(state)
        if cached_count > 0 or not scan_completed:
            return current_app_id
    index = int(payload.get("index") or 0)
    for offset in range(len(CREATIVE_LIST_ROTATION_APPS)):
        candidate_index = (index + offset) % len(CREATIVE_LIST_ROTATION_APPS)
        app_id = CREATIVE_LIST_ROTATION_APPS[candidate_index]
        if app_id in exhausted_apps:
            continue
        next_payload = {
            "index": candidate_index,
            "current_app_id": app_id,
            "last_app_id": app_id,
            "cycle_exhausted": False,
            "exhausted_apps": sorted(exhausted_apps),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        path.write_text(json.dumps(next_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return app_id
    next_payload = {
        "index": index,
        "current_app_id": "",
        "last_app_id": current_app_id,
        "cycle_exhausted": True,
        "exhausted_apps": sorted(exhausted_apps),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path.write_text(json.dumps(next_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ""


def _load_creative_list_state(*, line_name: str, app_id: str) -> dict[str, Any]:
    path = _creative_list_state_path(line_name=line_name, app_id=app_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    normalized = dict(payload)
    normalized["cached_candidate_count"] = _creative_list_cached_count(normalized)
    normalized["consumed_count"] = _creative_list_consumed_count(normalized)
    normalized["scan_completed"] = _creative_list_scan_completed(normalized)
    return normalized


def _creative_list_consumed_serial_ids(*, line_name: str, app_id: str, state: dict[str, Any] | None = None) -> set[str]:
    payload = state if isinstance(state, dict) else _load_creative_list_state(line_name=line_name, app_id=app_id)
    values = payload.get("consumed_serial_ids")
    if not isinstance(values, list):
        return set()
    return {str(item).strip() for item in values if str(item).strip()}


def _creative_list_cached_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    values = state.get("cached_candidates")
    if not isinstance(values, list):
        return []
    return [dict(item) for item in values if isinstance(item, dict)]


def _save_creative_list_state(
    *,
    line_name: str,
    app_id: str,
    consumed_serial_ids: set[str],
    cached_candidates: list[dict[str, Any]],
    scan_completed: bool,
    window_start_page: int = 1,
) -> None:
    path = _creative_list_state_path(line_name=line_name, app_id=app_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "app_id": app_id,
        "line_name": str(line_name or "creative_list").strip().lower() or "creative_list",
        "consumed_serial_ids": sorted(consumed_serial_ids),
        "consumed_count": len(consumed_serial_ids),
        "cached_candidates": cached_candidates,
        "cached_candidate_count": len(cached_candidates),
        "scan_completed": bool(scan_completed),
        "window_start_page": max(1, int(window_start_page or 1)),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fetch_creative_list_candidates_for_app(
    config,
    *,
    publish_platform: str,
    target_size: int,
    line_name: str,
    app_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    state = _load_creative_list_state(line_name=line_name, app_id=app_id)
    window_start_page = _creative_list_window_start_page(state)
    official_rows, reached_window_end = _fetch_creative_list_official_rows_window(
        app_id,
        limit=1000,
        page_start=window_start_page,
    )
    consumed = _creative_list_consumed_serial_ids(line_name=line_name, app_id=app_id, state=state)
    cached_candidates = _creative_list_cached_candidates(state)
    if len(cached_candidates) >= max(1, int(target_size or 0)):
        selected = cached_candidates[: max(1, int(target_size or 0))]
        remaining_cached = cached_candidates[len(selected) :]
        scan_completed = _creative_list_scan_completed(state)
        _save_creative_list_state(
            line_name=line_name,
            app_id=app_id,
            consumed_serial_ids=consumed,
            cached_candidates=remaining_cached,
            scan_completed=scan_completed,
            window_start_page=window_start_page,
        )
        return selected, scan_completed and not remaining_cached

    if not official_rows:
        _save_creative_list_state(
            line_name=line_name,
            app_id=app_id,
            consumed_serial_ids=consumed,
            cached_candidates=cached_candidates,
            scan_completed=True,
            window_start_page=window_start_page,
        )
        return cached_candidates[: max(1, int(target_size or 0))], True

    candidates: list[dict[str, Any]] = list(cached_candidates)
    timeout = _external_video_lookup_timeout(config.realtime_rank_timeout_seconds)
    pending_rows: list[dict[str, Any]] = []

    for row in official_rows:
        serial_id = str(row.get("serial_id") or "").strip()
        if not serial_id or serial_id in consumed:
            continue
        title = str(row.get("title") or row.get("title_ch") or row.get("title_en") or "").strip()
        if not title:
            continue
        pending_rows.append(row)

    remaining_rows = list(pending_rows)
    batch_size = max(1, min(int(os.getenv("BARRY_CREATIVE_LIST_SCAN_BATCH_SIZE") or 120), len(remaining_rows)))
    pending_rows = remaining_rows[:batch_size]
    has_more_rows = len(remaining_rows) > len(pending_rows)
    if not pending_rows:
        selected = candidates[: max(1, int(target_size or 0))]
        remaining_cached = candidates[len(selected) :]
        if not remaining_cached and not reached_window_end:
            next_window_start_page = window_start_page + 10
            _save_creative_list_state(
                line_name=line_name,
                app_id=app_id,
                consumed_serial_ids=set(),
                cached_candidates=[],
                scan_completed=False,
                window_start_page=next_window_start_page,
            )
            _log_realtime_skip(
                f"创意列表 {app_id} 当前 1000 部已扫空，切换到下一批 1000（起始页 {next_window_start_page}）。"
            )
            return selected, False
        _save_creative_list_state(
            line_name=line_name,
            app_id=app_id,
            consumed_serial_ids=consumed,
            cached_candidates=remaining_cached,
            scan_completed=True,
            window_start_page=window_start_page,
        )
        return selected, not remaining_cached

    def _lookup(row: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], str]:
        serial_id = str(row.get("serial_id") or "").strip()
        title = str(row.get("title") or row.get("title_ch") or row.get("title_en") or "").strip()
        try:
            assets = _search_creative_list_assets(
                title,
                publish_platform=publish_platform,
                timeout=timeout,
            )
            return serial_id, title, assets, ""
        except Exception as exc:
            return serial_id, title, [], str(exc)

    max_workers = max(1, min(int(os.getenv("BARRY_CREATIVE_LIST_LOOKUP_CONCURRENCY") or 4), 24))
    touched_serial_ids = [
        str(row.get("serial_id") or "").strip()
        for row in pending_rows
        if str(row.get("serial_id") or "").strip()
    ]
    rows_by_serial = {str(row.get("serial_id") or "").strip(): row for row in pending_rows}
    _log_realtime_skip(
        f"创意列表 {app_id} 本轮分批扫描 {len(pending_rows)} 部剧，"
        f"缓存候选={len(cached_candidates)}，并发={max_workers}，超时={int(timeout)}s"
    )
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_lookup, row): str(row.get("serial_id") or "").strip() for row in pending_rows}
        for future in as_completed(future_map):
            serial_id, title, assets, error = future.result()
            if error:
                _log_realtime_skip(f"创意列表匹配 {app_id} / {title} 失败，已跳过：{error}")
                continue
            if not assets:
                continue
            row = rows_by_serial.get(serial_id)
            if not row:
                continue
            first_asset = assets[0]
            candidates.append(
                _build_creative_list_candidate(
                    official_row=row,
                    app_id=app_id,
                    asset=first_asset,
                )
            )

    updated_consumed = consumed | {item for item in touched_serial_ids if item}
    selected = candidates[: max(1, int(target_size or 0))]
    remaining_cached = candidates[len(selected) :]
    scan_completed = not has_more_rows
    _save_creative_list_state(
        line_name=line_name,
        app_id=app_id,
        consumed_serial_ids=updated_consumed,
        cached_candidates=remaining_cached,
        scan_completed=scan_completed,
        window_start_page=window_start_page,
    )
    if scan_completed and not remaining_cached and not reached_window_end:
        next_window_start_page = window_start_page + 10
        _save_creative_list_state(
            line_name=line_name,
            app_id=app_id,
            consumed_serial_ids=set(),
            cached_candidates=[],
            scan_completed=False,
            window_start_page=next_window_start_page,
        )
        _log_realtime_skip(
            f"创意列表 {app_id} 当前 1000 部已扫空，切换到下一批 1000（起始页 {next_window_start_page}）。"
        )
        return selected, False
    return selected, scan_completed and not remaining_cached


def _fetch_creative_list_official_rows(app_id: str, *, limit: int) -> list[dict[str, Any]]:
    rows, _ = _fetch_creative_list_official_rows_window(app_id, limit=limit, page_start=1)
    return rows


def _fetch_creative_list_official_rows_window(app_id: str, *, limit: int, page_start: int) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    page = max(1, int(page_start or 1))
    page_size = 100
    window_pages = max(1, (max(1, int(limit or 1000)) + page_size - 1) // page_size)
    last_page = page + window_pages - 1
    reached_end = False
    while len(rows) < limit and page <= last_page:
        body = require_success(
            get_tasks(
                page=page,
                page_size=page_size,
                platform=app_id,
                language="",
                search="",
                order="publish_at",
                task_type="1",
            ),
            f"获取创意列表映射剧场 {app_id} 候选",
        )
        chunk = body.get("data", []) if isinstance(body, dict) else []
        normalized = [dict(item) for item in chunk if isinstance(item, dict)]
        if not normalized:
            reached_end = True
            break
        rows.extend(normalized)
        if len(normalized) < page_size:
            reached_end = True
            break
        page += 1
    return rows[:limit], reached_end


def _search_creative_list_assets(title: str, *, publish_platform: str, timeout: float) -> list[dict[str, Any]]:
    normalized_title = str(title or "").strip()
    normalized_platform = str(publish_platform or "FACEBOOK").strip().lower()
    cached_assets = _load_lookup_cache(
        CREATIVE_LIST_CACHE_DIR,
        prefix=f"creative-list-{normalized_platform}",
        identity=normalized_title,
    )
    if cached_assets is not None:
        return cached_assets
    now = datetime.now(timezone.utc)
    seen_begin = int((now - timedelta(days=365)).timestamp())
    seen_end = int(now.timestamp())
    payload = {
        "app_type": 2,
        "page": 1,
        "page_size": 20,
        "duplicate_removal": 1,
        "is_theater": 1,
        "platform": [normalized_platform],
        "keyword": [normalized_title],
        "seen_begin": seen_begin,
        "seen_end": seen_end,
        "sort_field": "-impression",
    }
    response = _zing_post("/api/zing/creative/list", payload, timeout=timeout)
    rows = response.get("creative_list") if isinstance(response.get("creative_list"), list) else []
    assets: list[dict[str, Any]] = []
    seen_video_urls: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        resource_urls = row.get("resource_urls")
        if not isinstance(resource_urls, list):
            continue
        creative_ad_key = str(row.get("ad_key") or "").strip()
        for resource_index, resource in enumerate(resource_urls):
            if not isinstance(resource, dict):
                continue
            video_url = str(resource.get("video_url") or "").strip()
            if not video_url or video_url in seen_video_urls:
                continue
            seen_video_urls.add(video_url)
            assets.append(
                {
                    "video_url": video_url,
                    "duration_seconds": _extract_external_video_duration_seconds(row, resource),
                    "creative_ad_key": creative_ad_key,
                    "asset_key": _build_external_asset_key(
                        name_md5=hashlib.md5(title.encode("utf-8")).hexdigest(),
                        creative_ad_key=creative_ad_key,
                        resource_index=resource_index,
                        video_url=video_url,
                    ),
                }
            )
    _save_lookup_cache(
        CREATIVE_LIST_CACHE_DIR,
        prefix=f"creative-list-{normalized_platform}",
        identity=normalized_title,
        assets=assets,
        ttl_seconds=3600 if assets else 900,
    )
    return assets


def _build_creative_list_candidate(
    *,
    official_row: dict[str, Any],
    app_id: str,
    asset: dict[str, Any],
) -> dict[str, Any]:
    title = str(official_row.get("title") or official_row.get("title_ch") or official_row.get("title_en") or "").strip()
    video_url = str(asset.get("video_url") or "").strip()
    duration_seconds = int(asset.get("duration_seconds") or 0)
    candidate = dict(official_row)
    candidate.update(
        {
            "serial_id": str(official_row.get("serial_id") or "").strip(),
            "task_id": str(official_row.get("task_id") or "").strip(),
            "task_type": str(official_row.get("task_type") or "1").strip() or "1",
            "app_id": app_id,
            "title": title,
            "title_ch": title or str(official_row.get("title_ch") or "").strip(),
            "title_en": title or str(official_row.get("title_en") or "").strip(),
            "source_mode": "external_video",
            "candidate_fetch_source": "creative_list_external",
            "candidate_source_platform": "guangdada_creative_list",
            "candidate_priority_boost": _realtime_external_priority_boost(),
            "external_video_url": video_url,
            "external_asset_key": str(asset.get("asset_key") or "").strip(),
            "external_creative_ad_key": str(asset.get("creative_ad_key") or "").strip(),
            "external_video_duration_seconds": max(0, duration_seconds),
            "external_estimated_output_count": _estimate_external_output_count(duration_seconds),
        }
    )
    return candidate
