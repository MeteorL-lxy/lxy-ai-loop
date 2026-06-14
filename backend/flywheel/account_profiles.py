from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .reporting import _language_zh
from .selection.history_filter import build_cross_app_title_history_key


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _existing_state_roots(root: Path) -> list[Path]:
    values = [
        root / "data" / "daily-loop",
        root / "runtime" / "daily-loop",
    ]
    seen: set[Path] = set()
    roots: list[Path] = []
    for item in values:
        resolved = item.resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def _profile_path(root: Path) -> Path:
    return root / "conf" / "account_audience_profiles.json"


def _load_manual_profiles(root: Path) -> dict[str, dict[str, Any]]:
    path = _profile_path(root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    accounts = payload.get("accounts") if isinstance(payload, dict) else {}
    if not isinstance(accounts, dict):
        return {}
    return {str(key).strip(): dict(value) for key, value in accounts.items() if str(key).strip() and isinstance(value, dict)}


def _recent_cutoff(recent_days: int) -> str:
    return (datetime.now() - timedelta(days=max(0, int(recent_days)))).strftime("%Y-%m-%d")


def _normalize_language_label(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = str(_language_zh(raw) or raw).strip()
    if normalized.isdigit():
        return ""
    return normalized


def _iter_recent_round_payloads(root: Path, *, recent_days: int) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    cutoff = _recent_cutoff(recent_days)
    for state_root in _existing_state_roots(root):
        for day_dir in sorted(state_root.glob("*")):
            if not day_dir.is_dir():
                continue
            day_text = day_dir.name.strip()
            if len(day_text) >= 10 and day_text[:10] < cutoff:
                continue
            for json_path in sorted(day_dir.glob("round*.json")):
                try:
                    payload = json.loads(json_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(payload, dict):
                    payloads.append(payload)
    return payloads


def build_account_assignment_profiles(*, recent_days: int = 14) -> dict[str, dict[str, Any]]:
    root = _project_root()
    manual_profiles = _load_manual_profiles(root)
    payloads = _iter_recent_round_payloads(root, recent_days=recent_days)

    language_scores: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    recent_serial_ids: dict[str, set[str]] = defaultdict(set)
    recent_title_keys: dict[str, set[str]] = defaultdict(set)

    for payload in payloads:
        report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
        rows = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
        item_map: dict[int, dict[str, Any]] = {}
        for item in payload.get("items") or []:
            index = int(item.get("index") or 0)
            if index > 0 and isinstance(item, dict):
                item_map[index] = item

        for row in rows:
            if not isinstance(row, dict):
                continue
            account_name = str(row.get("账号") or "").strip()
            if not account_name:
                continue
            index = int(row.get("序号") or 0)
            item = item_map.get(index, {})
            account = item.get("account") if isinstance(item.get("account"), dict) else {}
            account_id = str(account.get("account_id") or "").strip()
            keys = [account_name]
            if account_id:
                keys.append(account_id)

            if str(row.get("发布情况") or "").strip() == "发布成功":
                language = _normalize_language_label(row.get("语言"))
                weight = max(1.0, float(row.get("播放量") or 0))
                if language:
                    for key in keys:
                        language_scores[key][language] += weight

                serial_id = str(row.get("短剧ID") or "").strip()
                title = str(row.get("短剧") or "").strip()
                title_key = build_cross_app_title_history_key(title)
                for key in keys:
                    if serial_id:
                        recent_serial_ids[key].add(serial_id)
                    if title_key:
                        recent_title_keys[key].add(title_key)

    profiles: dict[str, dict[str, Any]] = {}
    for key in set(language_scores) | set(recent_serial_ids) | set(recent_title_keys) | set(manual_profiles):
        scored = language_scores.get(key) or {}
        preferred_languages = [
            language
            for language, _ in sorted(scored.items(), key=lambda item: (-float(item[1]), str(item[0])))
            if str(language).strip()
        ][:2]
        profile = {
            "preferred_languages": preferred_languages,
            "recent_serial_ids": sorted(recent_serial_ids.get(key) or []),
            "recent_title_keys": sorted(recent_title_keys.get(key) or []),
        }
        manual = manual_profiles.get(key) or {}
        if isinstance(manual.get("preferred_languages"), list):
            merged = []
            for value in [*manual.get("preferred_languages"), *preferred_languages]:
                normalized = _normalize_language_label(value)
                if normalized and normalized not in merged:
                    merged.append(normalized)
            profile["preferred_languages"] = merged[:3]
        if isinstance(manual.get("blocked_languages"), list):
            profile["blocked_languages"] = [
                normalized
                for normalized in (_normalize_language_label(value) for value in manual.get("blocked_languages"))
                if normalized
            ]
        if manual.get("region"):
            profile["region"] = str(manual.get("region") or "").strip()
        profiles[key] = profile
    return profiles
