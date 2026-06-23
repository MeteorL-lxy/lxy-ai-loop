from __future__ import annotations

import sys
import time


def bind(ctx):
    protected = set(globals().keys())
    for name, value in vars(ctx).items():
        if name.startswith("__"):
            continue
        if name in protected and callable(globals().get(name)):
            continue
        globals()[name] = value
    return sys.modules[__name__]


def _cut_type_zh(value: str) -> str:
    raw = str(value or "").strip()
    return CUT_TYPE_ZH.get(raw, raw)


def _line_name_zh(value: str) -> str:
    raw = str(value or "").strip()
    return {
        "realtime": "实时榜线",
        "ordinary": "普通池线",
        "stardusttv": "StardustTV 剧场线",
    }.get(raw, raw)


def _dedup_list_zh(values) -> str:
    return "、".join(_dedup_zh(str(value)) for value in (values or []))


def _unique_in_order(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _task_keys(tasks: list[dict]) -> set[tuple[str, str]]:
    return {
        (str(task.get("team_id") or ""), str(task.get("task_id") or ""))
        for task in tasks
        if str(task.get("team_id") or "") and str(task.get("task_id") or "")
    }


def _record_by_task_key(records: list[dict]) -> dict[tuple[str, str], dict]:
    return {
        (str(record.get("team_id") or ""), str(record.get("task_id") or "")): dict(record)
        for record in records
        if str(record.get("team_id") or "") and str(record.get("task_id") or "")
    }


def _item_publish_records(item: dict, records_by_key: dict[tuple[str, str], dict]) -> list[dict]:
    tasks = ((item.get("publish") or {}).get("tasks")) or []
    return [
        records_by_key[key]
        for key in _task_keys(tasks)
        if key in records_by_key
    ]


def _clip_video_info(item: dict) -> dict[str, object]:
    clip = item.get("clip") or {}
    metadata = dict(clip.get("publish_ready_metadata") or clip.get("downloaded_metadata") or {})
    width = int(metadata.get("screen_x") or 0)
    height = int(metadata.get("screen_y") or 0)
    duration = int(metadata.get("file_duration") or 0)
    size = int(metadata.get("file_size") or ((item.get("publish") or {}).get("upload") or {}).get("publish_upload_size") or 0)
    return {
        "视频时长": format_seconds(duration) if duration else "",
        "视频时长秒": duration,
        "视频分辨率": f"{width}x{height}" if width and height else "",
        "视频方向": {
            "vertical": "竖屏",
            "horizontal": "横屏",
            "square": "方形",
        }.get(str(metadata.get("orientation") or ""), str(metadata.get("orientation") or "")),
        "文件大小": format_size(size) if size else "",
    }


def _ai_cut_info(clip_options: dict) -> dict[str, object]:
    return {
        "AI剪辑模板": int(clip_options.get("template_id") or 0) or "",
        "AI最小分段秒数": int(clip_options.get("segment_seconds") or 0) or "",
        "AI最大分段秒数": int(clip_options.get("segment_max_seconds") or 0) or "",
        "AI处理并发数": int(clip_options.get("process_concurrency") or 0) or "",
        "AI累计处理时长上限秒": int(clip_options.get("max_total_duration_seconds") or 0) or "",
        "AI每剧最大处理集数": int(clip_options.get("max_episodes_per_serial") or 0) or "",
        "AI素材来源": str(clip_options.get("source") or "").strip(),
        "AI自动剪辑开关": "开启" if clip_options.get("auto_clip_enabled") else "",
        "AI自动迁移": "开启" if clip_options.get("use_auto_migration") else "",
    }


def _batch_item_publish_outcome(item: dict, records: list[dict], tasks: list[dict]) -> str:
    if str(item.get("status") or "").strip().lower() == "processing":
        return "发布处理中"
    statuses_raw = [str(record.get("status") or "").upper() for record in records if str(record.get("status") or "")] or [
        str(task.get("status") or "").upper() for task in tasks if str(task.get("status") or "")
    ]
    if any(status in SUCCESSFUL_PUBLISH_STATUSES for status in statuses_raw):
        return "发布成功"
    if any(status in RUNNING_PUBLISH_STATUSES for status in statuses_raw):
        return "发布处理中"
    if tasks:
        return "发布失败"
    if item.get("status") == "failed":
        return "未提交"
    return "未提交"


def _batch_item_failure_reason(item: dict, records: list[dict]) -> str:
    for record in records:
        message = str(record.get("error_msg") or record.get("message") or "").strip()
        if message:
            return message
    if str(item.get("error") or "").strip():
        return str(item.get("error") or "").strip()
    attempts = item.get("publish_attempts") if isinstance(item.get("publish_attempts"), list) else []
    for attempt in reversed(attempts):
        message = str((attempt or {}).get("error") or "").strip()
        if message:
            return message
    return ""


def _is_processing_publish_outcome(report: dict) -> bool:
    return str(report.get("发布情况") or "").strip() == "发布处理中"


def _is_success_publish_outcome(report: dict) -> bool:
    return str(report.get("发布情况") or "").strip() == "发布成功"


def _is_failed_publish_outcome(report: dict) -> bool:
    return str(report.get("发布情况") or "").strip() in {"发布失败", "未提交"}


def _publish_account_names(records: list[dict], target: dict, fallback_platform: str) -> list[str]:
    names = [
        str(record.get("social_name") or "").strip()
        for record in records
        if str(record.get("social_name") or "").strip()
    ]
    if names:
        return names
    accounts = target.get("accounts") if isinstance(target.get("accounts"), list) else []
    names = [
        str(account.get("social_name") or account.get("name") or "").strip()
        for account in accounts
        if str(account.get("social_name") or account.get("name") or "").strip()
    ]
    if names:
        return names
    team_ids = target.get("team_ids") if isinstance(target.get("team_ids"), list) else []
    return [f"{_platform_label(fallback_platform)} 账号" for _ in team_ids]


def _publish_item_report(item: dict, records_by_key: dict[tuple[str, str], dict], cleanup_deleted: set[str]) -> dict:
    drama = item.get("drama") or {}
    episode = item.get("episode") or {}
    account = item.get("account") or {}
    clip_options = item.get("clip_options") or {}
    clip = item.get("clip") or {}
    publish = item.get("publish") or {}
    records = _item_publish_records(item, records_by_key)
    statuses = [
        _status_zh(str(record.get("status") or ""))
        for record in records
        if str(record.get("status") or "")
    ] or [
        _status_zh(str(task.get("status") or ""))
        for task in (publish.get("tasks") or [])
        if str(task.get("status") or "")
    ]
    publish_ready_file = str(clip.get("publish_ready_file") or "")
    local_status = ""
    if publish_ready_file:
        local_status = "已自动删除" if publish_ready_file in cleanup_deleted else "已保留"
    video_info = _clip_video_info(item)
    ai_cut_info = _ai_cut_info(clip_options)
    publish_outcome = str(item.get("publish_final_outcome_override") or "").strip() or _batch_item_publish_outcome(
        item, records, publish.get("tasks") or []
    )
    failure_reason = str(item.get("publish_final_reason_override") or "").strip() or _batch_item_failure_reason(item, records)
    non_retryable_reason = _item_non_retryable_publish_reason(item, records_by_key)
    retry_advice = ""
    if non_retryable_reason:
        retry_advice = "不可自动重试，需要更换支持 Reel 的账号。"
    report = {
        "序号": item.get("index"),
        "线路": _line_name_zh(str(item.get("line_name") or item.get("line") or "")),
        "短剧": drama.get("title"),
        "短剧ID": str(drama.get("serial_id") or ""),
        "剧场": _app_label(str(drama.get("source_platform") or drama.get("app_id") or "")),
        "语言": _language_zh(str(drama.get("language") or "")),
        "候选来源": _candidate_source_label(drama),
        "候选分数": round(float(drama.get("candidate_final_score") or 0.0), 4),
        "集数": int((episode.get("episode_order") or 0)),
        "账号": account.get("name"),
        "平台": _platform_label(str(account.get("platform") or "")),
        "发布情况": publish_outcome,
        "剪辑手法": _cut_type_zh(str(clip_options.get("cut_type") or "")),
        "去重手法": _dedup_list_zh(clip_options.get("deduplication") or []),
        "目标比例": str(clip_options.get("target_aspect_ratio") or "9:16"),
        "输出时长参数": str(clip_options.get("duration") or ""),
        **ai_cut_info,
        "脚本数量": int(clip_options.get("script_count") or 1),
        "裂变数量": int(clip_options.get("output_count") or 1),
        **video_info,
        "剪辑作品ID": str(clip.get("manus_id") or ""),
        "推广链接": str((item.get("promotion") or {}).get("promotion_link") or ""),
        "推广口令": str((item.get("promotion") or {}).get("promotion_code") or ""),
        "发布状态": statuses,
        "发布时间": "、".join(str(record.get("post_date") or "") for record in records if str(record.get("post_date") or "")),
        "平台帖子ID": "、".join(str(record.get("post_id") or "") for record in records if str(record.get("post_id") or "")),
        "播放量": sum(int(record.get("views") or 0) for record in records),
        "点赞数": sum(int(record.get("likes") or 0) for record in records),
        "评论数": sum(int(record.get("comments") or 0) for record in records),
        "分享数": sum(int(record.get("shares") or 0) for record in records),
        "发布尝试次数": len(item.get("publish_attempts") or []),
        "是否可自动重试": "否" if non_retryable_reason else "是",
        "处理建议": retry_advice,
        "本地成片状态": local_status,
        "本地成片路径": "",
        "失败原因": failure_reason,
        "错误": item.get("error") or "",
    }
    source_path = str(item.get("source_path") or "").strip()
    if source_path:
        report["本地源视频"] = source_path
    return report


def _mark_processing_items_as_failed(
    *,
    items: list[dict],
    records: list[dict],
    cleanup_deleted: set[str],
    reason: str,
) -> None:
    records_by_key = _record_by_task_key(records)
    for item in items:
        preview = _publish_item_report(item, records_by_key, cleanup_deleted)
        if _is_processing_publish_outcome(preview):
            item["publish_final_outcome_override"] = "发布失败"
            item["publish_final_reason_override"] = reason
            if str(item.get("status") or "").strip() != "failed":
                item["status"] = "failed"


def _settle_publish_report_payload(
    payload: dict,
    *,
    platform: str,
    wait_seconds: int,
    poll_interval: int,
    settle_timeout_seconds: int,
    report_builder,
) -> dict:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    tasks = [
        task
        for item in items
        for task in (((item.get("publish") or {}).get("tasks")) or [])
    ]
    if not tasks:
        payload["report_zh"] = report_builder(payload)
        return payload

    cleanup = payload.get("cleanup") if isinstance(payload.get("cleanup"), dict) else {}
    cleanup_deleted = {str(path) for path in cleanup.get("deleted_paths", [])}
    deadline = time.time() + max(max(0, int(wait_seconds)), max(0, int(settle_timeout_seconds)))
    report = report_builder(payload)

    while int(report.get("发布处理中数") or 0) > 0 and time.time() < deadline:
        remaining = max(1, int(deadline - time.time()))
        refreshed_records = _poll_local_publish_records(
            platform=platform,
            tasks=tasks,
            wait_seconds=min(max(1, int(wait_seconds)), remaining),
            poll_interval=poll_interval,
        )
        payload["publish_records"] = refreshed_records
        report = report_builder(payload)

    if int(report.get("发布处理中数") or 0) > 0:
        _mark_processing_items_as_failed(
            items=items,
            records=payload.get("publish_records") if isinstance(payload.get("publish_records"), list) else [],
            cleanup_deleted=cleanup_deleted,
            reason=SETTLE_TIMEOUT_FAILURE_REASON,
        )
        report = report_builder(payload)
        report["状态收敛说明"] = "状态确认超时，剩余处理中任务已按失败处理后出报告。"
    else:
        report["状态收敛说明"] = "发布状态已收敛，正式报告生成时处理中为 0。"

    payload["report_zh"] = report
    return payload


def _local_report_zh(payload: dict) -> dict:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    records = payload.get("publish_records") if isinstance(payload.get("publish_records"), list) else []
    cleanup = payload.get("cleanup") if isinstance(payload.get("cleanup"), dict) else {}
    cleanup_deleted = {str(path) for path in cleanup.get("deleted_paths", [])}
    records_by_key = _record_by_task_key(records)
    item_reports = [_publish_item_report(item, records_by_key, cleanup_deleted) for item in items]
    success_reports = [
        report
        for item, report in zip(items, item_reports)
        if any(
            str(record.get("status") or "").upper() in SUCCESSFUL_PUBLISH_STATUSES
            for record in _item_publish_records(item, records_by_key)
        )
    ]
    platform = str(payload.get("platform") or "")
    account_names = [
        str(report.get("账号") or "").strip()
        for report in item_reports
        if str(report.get("账号") or "").strip()
    ]
    manus_ids = {
        str(((item.get("clip") or {}).get("manus_id") or "")).strip()
        for item in items
        if str(((item.get("clip") or {}).get("manus_id") or "")).strip()
    }
    return {
        "执行模式": "本地视频剪辑发布",
        "发布平台": _platform_label(platform),
        "发布账号": account_names,
        "剪辑成功数": len(manus_ids),
        "发布提交数": sum(len(((item.get("publish") or {}).get("tasks") or [])) for item in items),
        "发布成功数": len(success_reports),
        "发布处理中数": len([report for report in item_reports if _is_processing_publish_outcome(report)]),
        "发布成功视频": success_reports,
        "发布失败任务": [
            report
            for report in item_reports
            if _is_failed_publish_outcome(report)
        ],
        "任务明细": item_reports,
    }


def _retryable_batch_items(items: list[dict], records: list[dict]) -> list[dict]:
    records_by_key = _record_by_task_key(records)
    return [
        dict(item)
        for item in items
        if _item_should_retry_publish(item, records_by_key)
        and str(((item.get("clip") or {}).get("publish_ready_file") or "")).strip()
    ]


def _failed_publish_state_payload(*, mode: str, platform: str, items: list[dict], records: list[dict]) -> dict | None:
    retryable_items = _retryable_batch_items(items, records)
    if not retryable_items:
        return None
    return {
        "mode": mode,
        "platform": platform,
        "saved_at": int(time.time()),
        "items": retryable_items,
    }


def _failed_publish_prompt_zh(report: dict) -> str:
    failed_reports = report.get("发布失败任务") if isinstance(report.get("发布失败任务"), list) else []
    if not failed_reports:
        return ""
    max_attempts = max(
        [int(item.get("发布尝试次数") or 0) for item in failed_reports],
        default=0,
    )
    auto_retry_count = max(0, max_attempts - 1)
    retry_prefix = (
        f"还有 {len(failed_reports)} 条发布未成功。我已经自动重试 {auto_retry_count} 次，并保留了这些失败任务的本地成片。"
        if auto_retry_count > 0
        else f"还有 {len(failed_reports)} 条发布未成功。我已经自动保留这些失败任务的本地成片。"
    )
    return (
        retry_prefix
        + "如果你同意，我可以继续重试一次这些失败发布；如果你不继续，我可以删除这些保留成片。"
        "如果你想看成片路径，也可以直接问我。"
    )


def _failed_publish_suggestions_zh(report: dict) -> list[str]:
    failed_reports = report.get("发布失败任务") if isinstance(report.get("发布失败任务"), list) else []
    total = int(report.get("请求数量") or 0)
    success = int(report.get("发布成功数") or 0)
    processing = int(report.get("发布处理中数") or 0)
    if not failed_reports:
        if total > 0:
            return [f"本轮已成功跑通 {success}/{total} 条，建议先保持当前选剧与剪辑策略不变，等 24 小时后结合播放/点击数据再决定是否调策略。"]
        return ["本轮没有失败项，可继续沿用当前流程。"]

    non_retryable = [
        item for item in failed_reports if str(item.get("是否可自动重试") or "") == "否"
    ]
    retryable = [
        item for item in failed_reports if str(item.get("是否可自动重试") or "") != "否"
    ]
    unsupported_accounts = _unique_in_order(
        [
            str(item.get("账号") or "").strip()
            for item in non_retryable
            if "reel" in str(item.get("失败原因") or item.get("错误") or "").lower()
            or "账号不能发布reel" in str(item.get("失败原因") or item.get("错误") or "")
        ]
    )
    timeout_like = [
        item
        for item in failed_reports
        if any(
            token in str(item.get("失败原因") or item.get("错误") or "").lower()
            for token in ["timeout", "timed out", "connection aborted", "read timed out", "write operation timed out", "504"]
        )
        or any(
            token in str(item.get("失败原因") or item.get("错误") or "")
            for token in ["超时", "请求失败", "Connection aborted", "Read timed out", "write operation timed out"]
        )
    ]
    clipping_stage_like = [
        item
        for item in failed_reports
        if any(
            token in str(item.get("失败原因") or item.get("错误") or "").lower()
            for token in ["ai-cut", "ffprobe", "download_status", "skipped"]
        )
        or any(
            token in str(item.get("失败原因") or item.get("错误") or "")
            for token in ["剪辑", "素材", "下载状态", "上传短剧集数素材"]
        )
    ]
    publish_timeout_like = [item for item in timeout_like if item not in clipping_stage_like]
    publish_retryable = [item for item in retryable if item not in clipping_stage_like]
    suggestions: list[str] = []
    if unsupported_accounts:
        suggestions.append(
            "先从下一轮账号池里排除不支持 Reel 的账号："
            + "、".join(unsupported_accounts[:8])
            + (" 等" if len(unsupported_accounts) > 8 else "")
            + "，这类失败继续重试也不会成功。"
        )
    if clipping_stage_like:
        suggestions.append(
            f"有 {len(clipping_stage_like)} 条停在素材/剪辑阶段，尚未进入发布；不要走发布重试，优先换素材、重建 ai-cut 任务，或等 ai-cut/素材服务恢复后再跑。"
        )
    if publish_timeout_like:
        suggestions.append(
            f"对发布阶段超时/请求失败的 {len(publish_timeout_like)} 条，优先只做“发布重试”，不要重新剪辑；本地成片已保留，建议放在接口更稳定时段或降低发布并发后再补发。"
        )
    if processing > 0:
        suggestions.append(
            f"当前还有 {processing} 条处于处理中，先去发布记录确认最终状态；只有确认未成功后再补发，避免重复发帖。"
        )
    if publish_retryable:
        suggestions.append(
            f"本轮仍有 {len(publish_retryable)} 条发布阶段失败具备自动重试条件，建议先清掉账号能力问题，再只重试这些可重试任务。"
        )
    if total > 0:
        success_rate = success / total
        if success_rate < 0.6:
            if clipping_stage_like:
                suggestions.append("本轮主要问题更偏素材/剪辑链路，不是发布侧；优先处理 ai-cut 状态判定、素材可用性和剪辑服务稳定性。")
            elif len(non_retryable) >= len(timeout_like):
                suggestions.append("本轮主要问题更偏账号能力，不建议先改选剧或剪辑手法，先把账号池清洗干净再扩大批量。")
            else:
                suggestions.append("本轮主要问题更偏发布链路稳定性，下一轮建议降低发布并发或拆成更小批次，再观察成功率。")
        else:
            suggestions.append(f"本轮已有 {success}/{total} 条成功，主链路基本可用；下一轮建议先修失败链路，不必急着改选剧和剪辑策略。")
    return suggestions


def _failed_publish_paths_payload(state: dict) -> dict:
    items = state.get("items") if isinstance(state.get("items"), list) else []
    return {
        "待处理失败发布数": len(items),
        "成片路径": [
            {
                "账号": str((item.get("account") or {}).get("name") or ""),
                "平台": _platform_label(str((item.get("account") or {}).get("platform") or state.get("platform") or "")),
                "短剧": str((item.get("drama") or {}).get("title") or ""),
                "集数": int(((item.get("episode") or {}).get("episode_order") or 0)),
                "成片路径": str(((item.get("clip") or {}).get("publish_ready_file") or "")).strip(),
            }
            for item in items
            if str(((item.get("clip") or {}).get("publish_ready_file") or "")).strip()
        ],
    }


def _local_user_summary_zh(report: dict) -> str:
    lines = [
        _join_non_empty(
            [
                f"本地视频剪辑发布已完成，目标平台 {report.get('发布平台')}",
                f"剪辑成功 {report.get('剪辑成功数')} 条",
                f"发布成功 {report.get('发布成功数')} 条",
            ]
        )
        + "。",
    ]
    retry_prompt = _failed_publish_prompt_zh(report)
    if retry_prompt:
        lines.append(retry_prompt)
    return "\n".join(lines)
