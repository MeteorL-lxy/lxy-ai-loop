from __future__ import annotations

import random
from typing import Any

from inbeidou_cli import get_tasks, require_success

from ..config import FlywheelConfig
from ..scoring.dimensions import parse_tags
from .fb_heat_signal import apply_fb_heat_signal, load_fb_heat_signal
from .realtime_rank_source import fetch_realtime_rank_candidates


def extract_third_serial_id(item: dict[str, Any]) -> str:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    return str(
        item.get("third_serial_id")
        or item.get("thirdSerialId")
        or raw.get("third_serial_id")
        or raw.get("thirdSerialId")
        or ""
    ).strip()


def normalize_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "serial_id": item.get("serial_id"),
        "task_id": item.get("task_id"),
        "app_id": item.get("app_id"),
        "title": item.get("title") or item.get("title_ch") or item.get("title_en") or "",
        "language": str(item.get("language") or ""),
        "third_serial_id": extract_third_serial_id(item),
        "tag_list": parse_tags(item.get("tag")),
    }


def _eligible_for_clipping(config: FlywheelConfig, item: dict[str, Any]) -> bool:
    if str(item.get("source_mode") or "").strip() == "external_video":
        return bool(str(item.get("external_video_url") or "").strip())
    if not config.require_third_serial_id:
        return True
    return bool(extract_third_serial_id(item))


def resolve_candidate_languages(config: FlywheelConfig, *, language: str | None = None) -> tuple[str, list[str]]:
    if language is not None and str(language).strip():
        normalized = str(language).strip()
        return "single", [normalized]

    mode = config.candidate_language_mode
    languages = []
    seen: set[str] = set()
    for item in config.candidate_languages:
        normalized = str(item).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            languages.append(normalized)

    if not languages:
        languages = [config.default_language]

    if mode == "all":
        return mode, []
    if mode == "random":
        return mode, [random.choice(languages)]
    if mode == "mixed":
        return mode, languages
    return "single", [config.default_language]


def _fetch_candidates_for_language(
    *,
    config: FlywheelConfig,
    platform: str,
    language: str,
    order: str,
    search: str,
    page: int,
) -> tuple[list[dict[str, Any]], int, int]:
    result = get_tasks(
        page=page,
        page_size=config.candidate_page_size,
        platform=platform,
        language=language,
        search=search,
        order=order,
    )
    body = require_success(result, f"获取飞轮候选剧列表 language={language}")
    rows = body.get("data", [])
    page_info = body.get("page", {})
    total_count = int(page_info.get("total_count") or 0)
    total_pages = max(1, (total_count + config.candidate_page_size - 1) // config.candidate_page_size) if total_count else page
    return rows, page, total_pages


def _cross_language_signature(item: dict[str, Any]) -> tuple[str, ...] | None:
    signature = (
        str(item.get("app_id") or "").strip(),
        str(item.get("publish_at") or "").strip(),
        str(item.get("episode_count") or "").strip(),
        str(item.get("locked_point") or "").strip(),
        str(item.get("start_charge_point") or "").strip(),
        str(item.get("target_count") or "").strip(),
        str(item.get("share_rate") or "").strip(),
        str(item.get("sort_tag") or "").strip(),
        str(item.get("finish_status") or "").strip(),
        str(item.get("task_type") or "").strip(),
    )
    if not signature[0] or not signature[1]:
        return None
    if not any(signature[index] for index in (2, 3, 4, 5, 6)):
        return None
    return signature


def _representative_rank(item: dict[str, Any], *, preferred_language: str) -> tuple[int, float, float, float, str, str]:
    language = str(item.get("language") or "").strip()
    promoter_number = float(item.get("promoter_number") or 0.0)
    promoter_base = float(item.get("promoter_base") or 0.0)
    share_rate = float(item.get("share_rate") or 0.0)
    publish_at = str(item.get("publish_at") or "")
    serial_id = str(item.get("serial_id") or "")
    return (
        1 if preferred_language and language == preferred_language else 0,
        promoter_number,
        promoter_base,
        share_rate,
        publish_at,
        serial_id,
    )


def dedupe_cross_language_candidates(config: FlywheelConfig, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, tuple[str, ...] | int], list[dict[str, Any]]] = {}
    ordered_keys: list[tuple[str, tuple[str, ...] | int]] = []

    for index, item in enumerate(candidates):
        signature = _cross_language_signature(item)
        group_key: tuple[str, tuple[str, ...] | int]
        if signature is None:
            group_key = ("item", index)
        else:
            group_key = ("signature", signature)
        if group_key not in groups:
            groups[group_key] = []
            ordered_keys.append(group_key)
        groups[group_key].append(item)

    deduped: list[dict[str, Any]] = []
    preferred_language = str(config.default_language or "").strip()

    for group_key in ordered_keys:
        items = groups[group_key]
        languages = sorted({str(item.get("language") or "").strip() for item in items if str(item.get("language") or "").strip()})
        serial_ids = [str(item.get("serial_id") or "") for item in items if str(item.get("serial_id") or "").strip()]
        task_ids = [str(item.get("task_id") or "") for item in items if str(item.get("task_id") or "").strip()]

        if group_key[0] == "signature" and len(items) > 1 and len(languages) > 1:
            representative = max(items, key=lambda item: _representative_rank(item, preferred_language=preferred_language))
            merged = dict(representative)
            merged["candidate_deduped_across_languages"] = True
            merged["candidate_variant_count"] = len(items)
            merged["candidate_variant_languages"] = languages
            merged["candidate_variant_serial_ids"] = serial_ids
            merged["candidate_variant_task_ids"] = task_ids
            merged["candidate_group_signature"] = list(group_key[1]) if isinstance(group_key[1], tuple) else []
            deduped.append(merged)
            continue

        for item in items:
            passthrough = dict(item)
            passthrough["candidate_deduped_across_languages"] = False
            passthrough["candidate_variant_count"] = 1
            passthrough["candidate_variant_languages"] = [str(item.get("language") or "").strip()] if str(item.get("language") or "").strip() else []
            passthrough["candidate_variant_serial_ids"] = [str(item.get("serial_id") or "")] if str(item.get("serial_id") or "").strip() else []
            passthrough["candidate_variant_task_ids"] = [str(item.get("task_id") or "")] if str(item.get("task_id") or "").strip() else []
            passthrough["candidate_group_signature"] = list(group_key[1]) if group_key[0] == "signature" and isinstance(group_key[1], tuple) else []
            deduped.append(passthrough)

    return deduped


def fetch_candidates(
    config: FlywheelConfig,
    *,
    platform: str | None = None,
    language: str | None = None,
    languages: list[str] | None = None,
    language_mode_override: str | None = None,
    order: str | None = None,
    search: str = "",
    target_publish_platforms: list[str] | None = None,
) -> list[dict[str, Any]]:
    target_size = config.candidate_pool_size
    target_platform = platform if platform is not None else config.default_platform
    target_order = order if order is not None else config.default_order
    fb_heat_signal = load_fb_heat_signal()
    if languages is not None:
        language_mode = str(language_mode_override or ("mixed" if len(languages) > 1 else "single")).strip().lower() or "single"
        if language_mode == "all":
            target_languages = [""]
        else:
            target_languages = [str(item).strip() for item in languages if str(item).strip()]
    else:
        language_mode, target_languages = resolve_candidate_languages(config, language=language)
        if language_mode == "all":
            target_languages = [""]
    seen: set[tuple[str, str, str]] = set()
    candidates: list[dict[str, Any]] = []
    language_pages = {item: 1 for item in target_languages}
    active_languages = list(target_languages)
    deduped_candidates: list[dict[str, Any]] = []

    realtime_candidates = fetch_realtime_rank_candidates(
        config,
        target_publish_platforms=target_publish_platforms,
        search=search,
        target_size=target_size,
    )
    for row in realtime_candidates:
        normalized = apply_fb_heat_signal(normalize_candidate(row), fb_heat_signal)
        if target_platform and str(normalized.get("app_id") or "").strip() != str(target_platform).strip():
            continue
        if not _eligible_for_clipping(config, normalized):
            continue
        key = (
            str(normalized.get("serial_id") or ""),
            str(normalized.get("task_id") or ""),
            str(normalized.get("app_id") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized["candidate_language_mode"] = language_mode
        normalized["candidate_source_language"] = str(normalized.get("language") or "")
        candidates.append(normalized)

    if candidates:
        deduped_candidates = dedupe_cross_language_candidates(config, candidates)
        if len(deduped_candidates) >= target_size:
            return deduped_candidates[:target_size]

    while active_languages:
        progressed = False
        for current_language in list(active_languages):
            page = language_pages[current_language]
            rows, current_page, total_pages = _fetch_candidates_for_language(
                config=config,
                platform=target_platform,
                language=current_language,
                order=target_order,
                search=search,
                page=page,
            )
            if not rows:
                active_languages.remove(current_language)
                continue

            progressed = True
            for row in rows:
                normalized = apply_fb_heat_signal(normalize_candidate(row), fb_heat_signal)
                if not _eligible_for_clipping(config, normalized):
                    continue
                key = (
                    str(normalized.get("serial_id") or ""),
                    str(normalized.get("task_id") or ""),
                    str(normalized.get("app_id") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                normalized["candidate_language_mode"] = language_mode
                normalized["candidate_source_language"] = current_language or str(normalized.get("language") or "")
                candidates.append(normalized)

            deduped_candidates = dedupe_cross_language_candidates(config, candidates)
            if len(deduped_candidates) >= target_size:
                break
            if current_page >= total_pages:
                active_languages.remove(current_language)
            else:
                language_pages[current_language] = current_page + 1
        if not progressed:
            break
        if len(deduped_candidates) >= target_size:
            break

    if not deduped_candidates:
        deduped_candidates = dedupe_cross_language_candidates(config, candidates)
    return deduped_candidates[:target_size]
