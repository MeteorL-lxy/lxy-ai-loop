#!/usr/bin/env python3
"""Report REEL-banned social IDs to Beidou and trigger replacement."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://api-icenter.inbeidou.cn"
ENDPOINT = "/ai/v1/publish/team/social/reels-banned/replace"
POST_LIST_ENDPOINT = "/ai/v1/publish/team/post"
INNER_ENDPOINT = "/publish/team/social/reels-banned/replace"
INNER_POST_LIST_ENDPOINT = "/publish/team/post"
DEFAULT_STATE_FILE = "runtime/account-flags/reels_banned_replace_state.json"
USE_ENV_PROXY = False
USE_REQUESTS_FALLBACK = True
INSECURE_TLS = False


def find_loop_root(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path.cwd())
    candidates.extend(Path.cwd().parents)
    script_path = Path(__file__).resolve()
    candidates.append(script_path.parents[3])
    candidates.extend(script_path.parents)

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / "runtime" / "loop_config.json").exists() or (resolved / "conf" / "account_pools.json").exists():
            return resolved
    return Path.cwd().resolve()


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise SystemExit(f"Failed to read config {path}: {exc}") from exc


def get_nested(data: dict[str, Any], dotted: str, default: str = "") -> str:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    if cur is None:
        return default
    return str(cur).strip()


def normalize_base_url(value: str | None, config: dict[str, Any]) -> str:
    base = (
        (value or "").strip()
        or os.getenv("AI_ICENTER_BASE_URL", "").strip()
        or get_nested(config, "beidou.icenter_base_url")
        or DEFAULT_BASE_URL
    )
    return base.rstrip("/")


def normalize_token(value: str | None, config: dict[str, Any]) -> str:
    token = (
        (value or "").strip()
        or os.getenv("AI_BEIDOU_TOKEN", "").strip()
        or get_nested(config, "beidou.token")
    )
    if not token:
        raise SystemExit("Missing token. Pass --token, set AI_BEIDOU_TOKEN, or configure runtime/loop_config.json beidou.token.")
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"


def normalize_token_optional(value: str | None, config: dict[str, Any]) -> str:
    token = (
        (value or "").strip()
        or os.getenv("AI_BEIDOU_TOKEN", "").strip()
        or get_nested(config, "beidou.token")
    )
    if not token:
        return ""
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"


def loop_api_request(loop_root: Path, method: str, inner_path: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None, timeout: int = 60) -> Any:
    backend = loop_root / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    try:
        from inbeidou_cli import ICENTER_API, api_request  # type: ignore
    except Exception as exc:
        raise SystemExit(f"Cannot import loop auth client from {backend}: {exc}") from exc
    return api_request(
        ICENTER_API,
        inner_path,
        method=method,
        params=query,
        json_data=body,
        auth_style="bearer",
        timeout=timeout,
    )


def install_no_proxy_opener() -> None:
    handlers = [urllib.request.ProxyHandler({}), urllib.request.HTTPHandler()]
    if hasattr(urllib.request, "HTTPSHandler"):
        handlers.append(urllib.request.HTTPSHandler())
    urllib.request.install_opener(urllib.request.build_opener(*handlers))


def parse_social_ids(values: list[str], ids_file: str | None, *, allow_empty: bool = False) -> list[int]:
    raw_parts: list[str] = []
    for value in values:
        raw_parts.extend(re.split(r"[\s,;]+", value.strip()))

    if ids_file:
        path = Path(ids_file)
        text = path.read_text(encoding="utf-8-sig").strip()
        if text:
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                raw_parts.extend(re.split(r"[\s,;]+", text))
            else:
                if isinstance(loaded, dict):
                    loaded = loaded.get("social_ids") or loaded.get("ids") or loaded.get("blocked_social_ids") or []
                if not isinstance(loaded, list):
                    raise SystemExit("--ids-file JSON must be a list or an object containing social_ids.")
                raw_parts.extend(str(item) for item in loaded)

    ids: set[int] = set()
    bad: list[str] = []
    for part in raw_parts:
        part = str(part).strip()
        if not part:
            continue
        if not re.fullmatch(r"\d+", part):
            bad.append(part)
            continue
        ids.add(int(part))
    if bad:
        raise SystemExit(f"Invalid social id values: {', '.join(bad[:10])}")
    if not ids and not allow_empty:
        raise SystemExit("No social IDs provided. Use --social-ids or --ids-file.")
    return sorted(ids)


def clean_query(params: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in params.items() if value not in (None, "")}


def request_json(method: str, base_url: str, token: str, path: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None, timeout: int = 60) -> Any:
    url = base_url + path
    query_params = clean_query(query or {})
    if query_params:
        url += "?" + urllib.parse.urlencode(query_params)
    data = None
    headers = {
        "Authorization": token,
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json;charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(raw)
        except Exception:
            parsed = raw
        raise SystemExit(json.dumps({"http_status": exc.code, "url": url, "response": parsed}, ensure_ascii=False, indent=2)) from exc
    except urllib.error.URLError as exc:
        if USE_REQUESTS_FALLBACK:
            return request_json_with_requests(method, url, token, body=body, timeout=timeout)
        raise SystemExit(json.dumps({"url": url, "error": str(exc)}, ensure_ascii=False, indent=2)) from exc


def request_replace(base_url: str, token: str, social_ids: list[int], timeout: int) -> Any:
    return request_json("POST", base_url, token, ENDPOINT, body={"social_ids": social_ids}, timeout=timeout)


def request_replace_loop_auth(loop_root: Path, social_ids: list[int], timeout: int) -> Any:
    return loop_api_request(loop_root, "POST", INNER_ENDPOINT, body={"social_ids": social_ids}, timeout=timeout)


def request_json_with_requests(method: str, url: str, token: str, *, body: dict[str, Any] | None = None, timeout: int = 60) -> Any:
    try:
        import requests  # type: ignore
    except Exception as exc:
        raise SystemExit(json.dumps({"url": url, "error": f"urllib failed and requests is unavailable: {exc}"}, ensure_ascii=False, indent=2)) from exc

    session = requests.Session()
    session.trust_env = USE_ENV_PROXY
    headers = {"Authorization": token, "Accept": "application/json"}
    kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout, "verify": not INSECURE_TLS}
    if body is not None:
        headers["Content-Type"] = "application/json;charset=utf-8"
        kwargs["json"] = body
    try:
        resp = session.request(method.upper(), url, **kwargs)
        raw = resp.text
        try:
            parsed: Any = resp.json() if raw else None
        except Exception:
            parsed = raw
        if resp.status_code >= 400:
            raise SystemExit(json.dumps({"http_status": resp.status_code, "url": url, "response": parsed}, ensure_ascii=False, indent=2))
        return parsed
    except Exception as exc:
        raise SystemExit(json.dumps({"url": url, "error": str(exc), "transport": "requests_fallback"}, ensure_ascii=False, indent=2)) from exc


def response_body(resp: Any) -> Any:
    return resp.get("body") if isinstance(resp, dict) and "body" in resp else resp


def body_items(resp: Any) -> list[Any]:
    body = response_body(resp)
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "items", "records"):
            if isinstance(data.get(key), list):
                return data[key]
    for key in ("list", "items", "records"):
        if isinstance(body.get(key), list):
            return body[key]
    return []


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    formats = (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%dT%H:%M:%S", 19),
        ("%Y-%m-%d", 10),
    )
    for fmt, width in formats:
        try:
            return datetime.strptime(text[:width], fmt)
        except ValueError:
            pass
    return None


def latest_loop_start(loop_root: Path) -> datetime | None:
    pointer = loop_root / "runtime" / "overnight_beidou_cap_runs" / "latest_run_dir.txt"
    try:
        run_dir = Path(pointer.read_text(encoding="utf-8-sig").strip())
    except Exception:
        return None
    if not run_dir.exists():
        return None
    logs = list(run_dir.glob("loop_run_*.log"))
    if not logs:
        return None
    latest = max(logs, key=lambda path: path.stat().st_mtime)
    try:
        with latest.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                ts = parse_time(str(row.get("ts") or ""))
                if ts:
                    return ts
    except OSError:
        return None
    return None


def post_account_id(post: dict[str, Any]) -> int | None:
    for key in ("social_id", "account_id", "team_social_id", "socialAccountId", "social_account_id"):
        value = post.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except Exception:
                pass
    for key in ("socialAccounts", "social_accounts", "accounts"):
        values = post.get(key)
        for row in values if isinstance(values, list) else []:
            if not isinstance(row, dict):
                continue
            for subkey in ("id", "social_id", "team_social_id", "account_id"):
                value = row.get(subkey)
                if value not in (None, ""):
                    try:
                        return int(value)
                    except Exception:
                        pass
    return None


def post_error_message(post: dict[str, Any]) -> str:
    return str(
        post.get("error_msg")
        or post.get("error")
        or post.get("message")
        or post.get("fail_reason")
        or post.get("failure_reason")
        or post.get("reason")
        or ""
    )


def post_status(post: dict[str, Any]) -> str:
    return str(post.get("status_name") or post.get("post_status_name") or post.get("status") or post.get("state") or "")


def is_reel_capability_error(text: str) -> bool:
    raw = str(text or "").strip()
    lower = raw.lower()
    if not raw:
        return False
    negative_hints = (
        "height",
        "width",
        "960",
        "540",
        "ffmpeg",
        "timeout",
        "timed out",
        "upload",
        "end of file",
        "opening input",
        "invalid url",
        "file_url",
    )
    if any(hint in lower for hint in negative_hints):
        return False
    if "账号不能发布reel视频" in raw:
        return True
    if "不能发布reel" in raw or "无法发布reel" in raw:
        return True
    if "cannot publish" in lower and "reel" in lower:
        return True
    if "can't publish" in lower and "reel" in lower:
        return True
    if "not allowed" in lower and "reel" in lower:
        return True
    return False


def load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    events = payload.get("processed_event_ids")
    payload["processed_event_ids"] = events if isinstance(events, list) else []
    payload["updated_at"] = str(payload.get("updated_at") or "")
    return payload


def save_state(path: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = datetime.now().strftime("%F %T")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def resolve_state_file(loop_root: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (loop_root / DEFAULT_STATE_FILE).resolve()


def round_event_id(*, round_json: Path, social_id: int, reason: str, post_id: Any) -> str:
    raw = "::".join([str(round_json.resolve()), str(social_id), str(reason or ""), str(post_id or "")])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _round_detail_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    rows: list[dict[str, Any]] = []
    for key in ("任务明细", "发布失败任务", "账号发布结果"):
        value = report.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    return rows


def _item_by_index(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    out: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index") or 0)
        except Exception:
            index = 0
        if index > 0:
            out[index] = item
    return out


def _account_from_item(item: dict[str, Any]) -> dict[str, Any]:
    account = item.get("account")
    return account if isinstance(account, dict) else {}


def _post_id_from_row(row: dict[str, Any]) -> Any:
    return row.get("平台帖子ID") or row.get("post_id") or row.get("任务ID") or row.get("task_id") or row.get("短剧ID")


def extract_round_reel_banned(round_json: Path) -> dict[str, Any]:
    try:
        payload = json.loads(round_json.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "source": str(round_json),
            "scanned_rows": 0,
            "matched_count": 0,
            "social_ids": [],
            "matches": [],
            "error": f"round json unreadable: {exc}",
        }
    items_by_index = _item_by_index(payload)
    matched: dict[int, dict[str, Any]] = {}
    scanned = 0
    for row in _round_detail_rows(payload):
        scanned += 1
        reason = str(row.get("失败原因") or row.get("错误") or row.get("error_msg") or "").strip()
        if not is_reel_capability_error(reason):
            continue
        try:
            index = int(row.get("序号") or row.get("index") or 0)
        except Exception:
            index = 0
        account = _account_from_item(items_by_index.get(index, {}))
        account_id = str(account.get("account_id") or row.get("账号ID") or row.get("social_id") or "").strip()
        if not account_id.isdigit():
            continue
        social_id = int(account_id)
        if social_id in matched:
            continue
        post_id = _post_id_from_row(row)
        matched[social_id] = {
            "social_id": social_id,
            "account_name": str(account.get("name") or row.get("账号") or "").strip(),
            "line_name": str(payload.get("line_name") or payload.get("line") or round_json.parent.name or ""),
            "round_name": str(payload.get("round_name") or round_json.stem or ""),
            "post_id": post_id,
            "status": str(row.get("发布情况") or row.get("发布状态") or ""),
            "error_msg": reason,
            "source": str(round_json),
            "event_id": round_event_id(round_json=round_json, social_id=social_id, reason=reason, post_id=post_id),
        }
    return {
        "source": str(round_json),
        "scanned_rows": scanned,
        "matched_count": len(matched),
        "social_ids": sorted(matched),
        "matches": [matched[key] for key in sorted(matched)],
    }


def detect_reel_banned_from_rounds(round_paths: list[Path]) -> dict[str, Any]:
    detections = [extract_round_reel_banned(path) for path in round_paths]
    merged: dict[int, dict[str, Any]] = {}
    scanned = 0
    errors: list[dict[str, str]] = []
    for detection in detections:
        scanned += int(detection.get("scanned_rows") or 0)
        if detection.get("error"):
            errors.append({"source": str(detection.get("source") or ""), "error": str(detection.get("error") or "")})
        for match in detection.get("matches") or []:
            if isinstance(match, dict):
                try:
                    social_id = int(match.get("social_id") or 0)
                except Exception:
                    social_id = 0
                if social_id and social_id not in merged:
                    merged[social_id] = match
    return {
        "source": "round_json",
        "round_files": [str(path) for path in round_paths],
        "scanned_rows": scanned,
        "matched_count": len(merged),
        "social_ids": sorted(merged),
        "matches": [merged[key] for key in sorted(merged)],
        "errors": errors,
    }


def filter_unprocessed_matches(detection: dict[str, Any], state_file: Path) -> tuple[list[int], list[dict[str, Any]], int]:
    state = load_state(state_file)
    processed = {str(item).strip() for item in state.get("processed_event_ids") or [] if str(item).strip()}
    matches = [item for item in (detection.get("matches") or []) if isinstance(item, dict)]
    pending = [item for item in matches if str(item.get("event_id") or "").strip() not in processed]
    social_ids = sorted({int(item["social_id"]) for item in pending if str(item.get("social_id") or "").isdigit()})
    return social_ids, pending, len(matches) - len(pending)


def mark_processed(state_file: Path, matches: list[dict[str, Any]], *, limit: int = 20000) -> None:
    if not matches:
        return
    state = load_state(state_file)
    processed = [str(item).strip() for item in state.get("processed_event_ids") or [] if str(item).strip()]
    seen = set(processed)
    for match in matches:
        event_id = str(match.get("event_id") or "").strip()
        if event_id and event_id not in seen:
            processed.append(event_id)
            seen.add(event_id)
    state["processed_event_ids"] = processed[-limit:]
    history = state.get("history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "at": datetime.now().strftime("%F %T"),
            "event_count": len(matches),
            "social_ids": sorted({int(item["social_id"]) for item in matches if str(item.get("social_id") or "").isdigit()}),
        }
    )
    state["history"] = history[-200:]
    save_state(state_file, state)


def detect_reel_banned_accounts(base_url: str, token: str, *, start: datetime, end: datetime, page_size: int, max_pages: int, timeout: int) -> dict[str, Any]:
    matched: dict[int, dict[str, Any]] = {}
    scanned = 0
    for page in range(1, max_pages + 1):
        resp = request_json(
            "GET",
            base_url,
            token,
            POST_LIST_ENDPOINT,
            query={
                "type": "FACEBOOK",
                "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
                "page_num": page,
                "page_size": page_size,
            },
            timeout=timeout,
        )
        rows = [row for row in body_items(resp) if isinstance(row, dict)]
        scanned += len(rows)
        for post in rows:
            error_msg = post_error_message(post)
            if not is_reel_capability_error(error_msg):
                continue
            account_id = post_account_id(post)
            if account_id is None:
                continue
            current = matched.get(account_id)
            post_id = post.get("id") or post.get("post_id") or post.get("task_id")
            row = {
                "social_id": account_id,
                "post_id": post_id,
                "status": post_status(post),
                "error_msg": error_msg,
            }
            if not current:
                matched[account_id] = row
        if len(rows) < page_size:
            break
    return {
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
        "scanned_posts": scanned,
        "matched_count": len(matched),
        "social_ids": sorted(matched),
        "matches": [matched[key] for key in sorted(matched)],
    }


def detect_reel_banned_accounts_loop_auth(loop_root: Path, *, start: datetime, end: datetime, page_size: int, max_pages: int, timeout: int) -> dict[str, Any]:
    matched: dict[int, dict[str, Any]] = {}
    scanned = 0
    for page in range(1, max_pages + 1):
        resp = loop_api_request(
            loop_root,
            "GET",
            INNER_POST_LIST_ENDPOINT,
            query={
                "type": "FACEBOOK",
                "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
                "page_num": page,
                "page_size": page_size,
            },
            timeout=timeout,
        )
        rows = [row for row in body_items(resp) if isinstance(row, dict)]
        scanned += len(rows)
        for post in rows:
            error_msg = post_error_message(post)
            if not is_reel_capability_error(error_msg):
                continue
            account_id = post_account_id(post)
            if account_id is None:
                continue
            current = matched.get(account_id)
            post_id = post.get("id") or post.get("post_id") or post.get("task_id")
            row = {
                "social_id": account_id,
                "post_id": post_id,
                "status": post_status(post),
                "error_msg": error_msg,
            }
            if not current:
                matched[account_id] = row
        if len(rows) < page_size:
            break
    return {
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
        "scanned_posts": scanned,
        "matched_count": len(matched),
        "social_ids": sorted(matched),
        "matches": [matched[key] for key in sorted(matched)],
        "auth": "loop",
    }


def response_code(resp: Any) -> int:
    if isinstance(resp, dict):
        value = resp.get("code")
        try:
            return int(value)
        except Exception:
            return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    global USE_ENV_PROXY, USE_REQUESTS_FALLBACK, INSECURE_TLS
    parser = argparse.ArgumentParser(description="Report REEL-banned social IDs to Beidou replacement API.")
    parser.add_argument("--social-ids", nargs="*", default=[], help="Social IDs, separated by spaces or commas.")
    parser.add_argument("--ids-file", default=None, help="TXT or JSON file containing IDs. JSON may be a list or {social_ids:[...]}.")
    parser.add_argument("--auto-detect", action="store_true", help="Detect REEL capability errors from Beidou post-list before calling replacement API.")
    parser.add_argument("--round-json", nargs="*", default=[], help="Detect REEL capability errors from local continuous-loop round JSON files.")
    parser.add_argument("--round-dir", default=None, help="Detect from all round*.json files in this local round directory.")
    parser.add_argument("--detect-only", action="store_true", help="Only detect and print matching social IDs; do not call replacement API.")
    parser.add_argument("--since", default=None, help="Detection start time: YYYY-MM-DD HH:mm:ss. Defaults to latest loop start, then --since-hours.")
    parser.add_argument("--end", default=None, help="Detection end time: YYYY-MM-DD HH:mm:ss. Defaults to now.")
    parser.add_argument("--since-hours", type=float, default=8, help="Fallback detection window when latest loop start is unavailable. Default: 8.")
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=30)
    parser.add_argument("--loop-root", default=None, help="Loop workspace root containing runtime/loop_config.json.")
    parser.add_argument("--base-url", default=None, help="iCenter base URL. Defaults to loop_config beidou.icenter_base_url.")
    parser.add_argument("--token", default=None, help="Beidou token. Defaults to loop_config beidou.token or AI_BEIDOU_TOKEN.")
    parser.add_argument("--state-file", default=None, help=f"Processed event state file. Default: {DEFAULT_STATE_FILE} under loop root.")
    parser.add_argument("--no-state", action="store_true", help="Do not filter or mark duplicate round-json replacement events.")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--use-env-proxy", action="store_true", help="Respect HTTP_PROXY/HTTPS_PROXY instead of forcing direct Beidou requests.")
    parser.add_argument("--no-requests-fallback", action="store_true", help="Disable fallback to the requests package when urllib fails.")
    parser.add_argument("--insecure-tls", action="store_true", help="Disable TLS certificate verification for requests fallback only.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload without calling the API.")
    args = parser.parse_args(argv)

    USE_ENV_PROXY = bool(args.use_env_proxy)
    USE_REQUESTS_FALLBACK = not bool(args.no_requests_fallback)
    INSECURE_TLS = bool(args.insecure_tls)
    loop_root = find_loop_root(args.loop_root)
    config = read_json(loop_root / "runtime" / "loop_config.json")
    social_ids = parse_social_ids(args.social_ids, args.ids_file, allow_empty=True)
    base_url = normalize_base_url(args.base_url, config)
    token = normalize_token_optional(args.token, config)
    if not args.use_env_proxy:
        install_no_proxy_opener()
    detection = None
    pending_matches: list[dict[str, Any]] = []
    skipped_duplicate_events = 0
    round_paths = [Path(value).expanduser().resolve() for value in args.round_json if str(value or "").strip()]
    if args.round_dir:
        round_dir = Path(args.round_dir).expanduser().resolve()
        round_paths.extend(sorted(round_dir.glob("round*.json")))
    if round_paths:
        detection = detect_reel_banned_from_rounds(round_paths)
        if args.no_state or args.detect_only or args.dry_run:
            pending_matches = [item for item in (detection.get("matches") or []) if isinstance(item, dict)]
            social_ids = sorted(set(social_ids) | set(detection["social_ids"]))
        else:
            state_file = resolve_state_file(loop_root, args.state_file)
            detected_ids, pending_matches, skipped_duplicate_events = filter_unprocessed_matches(detection, state_file)
            social_ids = sorted(set(social_ids) | set(detected_ids))
    if args.auto_detect or (not social_ids and not round_paths):
        end_dt = parse_time(args.end) or datetime.now()
        start_dt = parse_time(args.since) or latest_loop_start(loop_root) or (end_dt - timedelta(hours=max(0.1, args.since_hours)))
        if token:
            detection = detect_reel_banned_accounts(
                base_url,
                token,
                start=start_dt,
                end=end_dt,
                page_size=max(1, args.page_size),
                max_pages=max(1, args.max_pages),
                timeout=args.timeout,
            )
        else:
            detection = detect_reel_banned_accounts_loop_auth(
                loop_root,
                start=start_dt,
                end=end_dt,
                page_size=max(1, args.page_size),
                max_pages=max(1, args.max_pages),
                timeout=args.timeout,
            )
        social_ids = sorted(set(social_ids) | set(detection["social_ids"]))

    if not social_ids:
        print(json.dumps({
            "ok": True,
            "message": "no new reel capability error accounts detected",
            "detection": detection,
            "skipped_duplicate_events": skipped_duplicate_events,
        }, ensure_ascii=False, indent=2))
        return 0

    payload = {"social_ids": social_ids}

    if args.dry_run or args.detect_only:
        print(json.dumps({
            "dry_run": bool(args.dry_run),
            "detect_only": bool(args.detect_only),
            "url": base_url + ENDPOINT,
            "payload": payload,
            "count": len(social_ids),
            "detection": detection,
            "skipped_duplicate_events": skipped_duplicate_events,
        }, ensure_ascii=False, indent=2))
        return 0

    if token:
        resp = request_replace(base_url, token, social_ids, args.timeout)
        auth_source = "token"
    else:
        resp = request_replace_loop_auth(loop_root, social_ids, args.timeout)
        auth_source = "loop"
    code = response_code(resp)
    if code == 0 and pending_matches and not args.no_state:
        mark_processed(resolve_state_file(loop_root, args.state_file), pending_matches)
    output = {
        "ok": code == 0,
        "url": base_url + ENDPOINT,
        "count": len(social_ids),
        "social_ids": social_ids,
        "auth": auth_source,
        "detection": detection,
        "skipped_duplicate_events": skipped_duplicate_events,
        "response": resp,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if code == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
