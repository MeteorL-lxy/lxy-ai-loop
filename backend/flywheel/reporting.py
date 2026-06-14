from __future__ import annotations

import json
from typing import Any

from inbeidou_cli import format_seconds, format_size, get_publish_records, require_success


STATUS_ZH = {
    "WAITING": "等待处理",
    "PENDING": "待处理",
    "PROCESSING": "处理中",
    "QUEUED": "排队中",
    "SUBMITTED": "已提交",
    "SCHEDULED": "已入队待发布",
    "POSTED": "已发布",
    "SUCCESS": "成功",
    "DONE": "完成",
    "ERROR": "失败",
    "FAILED": "失败",
}
SUCCESSFUL_PUBLISH_STATUSES = {"POSTED", "SUCCESS", "DONE"}

DEDUP_ZH = {
    "common_deduplication": "通用去重",
    "apply_pip": "画中画去重",
    "apply_rotate": "旋转去重",
    "apply_scale": "缩放去重",
    "apply_flip": "镜像翻转去重",
    "apply_frame": "边框去重",
    "apply_special": "特效去重",
    "apply_speed": "变速去重",
    "apply_reduce_frame_rate": "降帧去重",
    "apply_mirror_pip": "镜像画中画去重",
}

CUT_TYPE_ZH = {
    "high_cut": "高燃卡点",
    "golden_three": "黄金三段式",
    "golden_clips": "黄金片段提取",
    "high_pre": "预告向高燃",
    "ai_cut_animation": "AI 自动剪辑",
    "ffmpeg_segment": "FFmpeg 分段快切",
}

LANGUAGE_ZH = {
    "1": "中文",
    "2": "英语",
    "3": "印尼语",
    "4": "西班牙语",
    "5": "法语",
    "6": "泰语",
    "7": "葡萄牙语",
    "8": "韩语",
    "9": "日语",
    "10": "阿拉伯语",
    "11": "德语",
    "12": "繁体中文",
    "13": "俄语",
    "14": "意大利语",
    "15": "菲律宾语",
    "16": "越南语",
}

PLATFORM_LABELS = {
    "TIKTOK": "TikTok",
    "FACEBOOK": "Facebook",
    "INSTAGRAM": "Instagram",
    "YOUTUBE": "YouTube",
}

APP_LABELS = {
    "reelshort": "ReelShort",
    "dramabox": "DramaBox",
    "shortmax": "ShortMax",
    "goodshort": "GoodShort",
    "kalos": "KalosTV",
    "kalostv": "KalosTV",
    "snackshort": "SnackShort",
    "touchshort": "TouchShort",
    "flickreels": "FlickReels",
    "sereal": "Sereal+",
    "moboreels": "MoboReels",
}

LOCAL_CLIP_STATUS_ZH = {
    "deleted": "已自动删除",
    "delete_failed": "删除失败",
}


def _status_zh(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return STATUS_ZH.get(raw.upper(), raw)


def _dedup_zh(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return DEDUP_ZH.get(raw, raw)


def _cut_type_zh(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return CUT_TYPE_ZH.get(raw, raw)


def _dedup_list_zh(values: Any) -> str:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        values = []
    return "、".join(_dedup_zh(str(value)) for value in values if str(value or "").strip())


def _language_zh(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return LANGUAGE_ZH.get(raw, raw)


def _platform_label(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return PLATFORM_LABELS.get(raw.upper(), raw)


def _app_label(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return APP_LABELS.get(raw.lower(), raw)


def _local_clip_status_zh(drama: dict[str, Any]) -> str:
    status = str(drama.get("local_clip_cleanup_status") or "").strip()
    if status:
        return LOCAL_CLIP_STATUS_ZH.get(status, status)
    path = str(drama.get("clipped_video_path") or "").strip()
    if path:
        return "已保留"
    return ""


def _video_info_from_clip_options(clip_options: dict[str, Any]) -> dict[str, Any]:
    normalized_output = clip_options.get("normalized_output")
    metadata = {}
    if isinstance(normalized_output, dict):
        metadata = dict(normalized_output.get("normalized") or {})
    width = int(metadata.get("screen_x") or 0)
    height = int(metadata.get("screen_y") or 0)
    duration = int(metadata.get("file_duration") or 0)
    size = int(metadata.get("file_size") or 0)
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


def _ai_cut_info_from_clip_options(clip_options: dict[str, Any]) -> dict[str, Any]:
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


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _stage_map(stages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for stage in stages:
        name = str(stage.get("stage") or stage.get("stage_name") or "")
        if name:
            mapping[name] = stage
    return mapping


def _extract_collect_preview(stage_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    collect = stage_map.get("collect") or {}
    preview = collect.get("preview")
    if isinstance(preview, list) and preview:
        first = preview[0]
        if isinstance(first, dict):
            return first
    return {}


def _extract_publish_preview(stage_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    publish = stage_map.get("publish") or {}
    preview = publish.get("preview")
    if isinstance(preview, list) and preview:
        for item in preview:
            if isinstance(item, dict) and str(item.get("status") or "").strip():
                return item
    return {}


def _refresh_publish_record(publish_record: dict[str, Any]) -> dict[str, Any]:
    task_id = str(publish_record.get("task_id") or "").strip()
    team_id = str(publish_record.get("team_id") or "").strip()
    platform = str(publish_record.get("social_type") or publish_record.get("platform") or "").strip()
    if not task_id or not team_id or not platform:
        return publish_record

    try:
        for page in range(1, 4):
            body = require_success(
                get_publish_records(page=page, page_size=100, social_type=platform),
                f"获取 {platform} 发布记录",
            )
            items = body.get("items") if isinstance(body.get("items"), list) else []
            if not items:
                break
            for item in items:
                if str(item.get("task_id") or "") == task_id and str(item.get("team_id") or "") == team_id:
                    return dict(item)
    except Exception:
        return publish_record
    return publish_record


def build_round_report_zh(
    *,
    round_id: int,
    status: str,
    stages: list[dict[str, Any]],
    live_refresh: bool = False,
) -> dict[str, Any]:
    stage_map = _stage_map(stages)
    collect_item = _extract_collect_preview(stage_map)
    publish_item = _extract_publish_preview(stage_map)
    drama = dict(collect_item.get("drama") or {})
    clip_options = _as_dict(drama.get("clip_options"))
    publish_record = dict(collect_item.get("publish_record") or {})
    if live_refresh and publish_record:
        publish_record = _refresh_publish_record(publish_record)

    match_stage = stage_map.get("match") or {}
    target_platforms = match_stage.get("target_platforms")
    publish_stage = stage_map.get("publish") or {}
    clip_stage = stage_map.get("clip") or {}
    publish_status_raw = str(publish_record.get("status") or publish_item.get("status") or "")
    publish_status_zh = _status_zh(publish_status_raw)
    video_info = _video_info_from_clip_options(clip_options)
    ai_cut_info = _ai_cut_info_from_clip_options(clip_options)
    clip_submit = _as_dict(clip_options.get("submit"))
    published_video = {
        "短剧": str(drama.get("title") or ""),
        "剧场": _app_label(str(drama.get("app_id") or "")),
        "语言": _language_zh(str(drama.get("language") or "")),
        "集数": int(drama.get("episode_number") or 0),
        "账号": str(publish_record.get("social_name") or ""),
        "剪辑手法": _cut_type_zh(str(clip_options.get("cut_type") or "")),
        "去重手法": _dedup_list_zh([drama.get("dedup_variant")] or []),
        "目标比例": str(clip_options.get("target_aspect_ratio") or ""),
        "输出时长参数": str(clip_options.get("duration") or ""),
        **ai_cut_info,
        **video_info,
        "剪辑作品ID": str(clip_submit.get("manus_id") or ""),
        "推广链接": str(drama.get("promotion_link") or ""),
        "推广口令": str(drama.get("promotion_code") or ""),
        "发布状态": publish_status_zh,
        "发布时间": str(publish_record.get("post_date") or ""),
        "平台帖子ID": str(publish_record.get("post_id") or ""),
        "播放量": int(collect_item.get("views") or 0),
        "点赞数": int(collect_item.get("likes") or 0),
        "评论数": int(collect_item.get("comments") or 0),
        "分享数": int(collect_item.get("shares") or 0),
        "本地成片状态": _local_clip_status_zh(drama),
        "本地成片路径": "",
    }
    published_success = publish_status_raw.upper() in SUCCESSFUL_PUBLISH_STATUSES

    report = {
        "轮次ID": round_id,
        "执行状态": _status_zh(status) or status,
        "发布平台": [_platform_label(item) for item in target_platforms] if isinstance(target_platforms, list) else [],
        "执行摘要": {
            "匹配到的发布计划数": int(match_stage.get("publish_plan_count") or 0),
            "实际剪辑数": int(clip_stage.get("executed_count") or 0),
            "实际发布数": int(publish_stage.get("executed_count") or 0),
        },
        "发布结果": {
            "最终状态": publish_status_zh,
            "任务ID": str(publish_record.get("task_id") or ""),
            "平台帖子ID": str(publish_record.get("post_id") or ""),
            "账号名称": str(publish_record.get("social_name") or ""),
            "发布时间": str(publish_record.get("post_date") or ""),
            "错误信息": str(publish_record.get("error_msg") or ""),
        },
        "统计数据": {
            "播放量": int(collect_item.get("views") or 0),
            "点赞数": int(collect_item.get("likes") or 0),
            "评论数": int(collect_item.get("comments") or 0),
            "分享数": int(collect_item.get("shares") or 0),
            "收入": float(collect_item.get("revenue") or 0.0),
        },
        "剧详情": {
            "剧名": str(drama.get("title") or ""),
            "剧场": _app_label(str(drama.get("app_id") or "")),
            "剧集任务ID": str(drama.get("task_id") or ""),
            "剧目序列ID": str(drama.get("serial_id") or ""),
            "语言": _language_zh(str(drama.get("language") or "")),
            "集数": int(drama.get("episode_number") or 0),
            "剪辑手法": _cut_type_zh(str(clip_options.get("cut_type") or "")),
            "去重手法": _dedup_zh(str(drama.get("dedup_variant") or "")),
            "目标比例": str(clip_options.get("target_aspect_ratio") or ""),
            "输出时长参数": str(clip_options.get("duration") or ""),
            **ai_cut_info,
            **video_info,
            "推广链接": str(drama.get("promotion_link") or ""),
            "推广口令": str(drama.get("promotion_code") or ""),
            "本地成片状态": _local_clip_status_zh(drama),
            "本地成片路径": "",
        },
        "发布成功视频": [published_video] if published_success else [],
    }
    return report


def build_round_user_summary_zh(report: dict[str, Any]) -> str:
    summary = report.get("执行摘要") if isinstance(report.get("执行摘要"), dict) else {}
    publish_result = report.get("发布结果") if isinstance(report.get("发布结果"), dict) else {}
    drama = report.get("剧详情") if isinstance(report.get("剧详情"), dict) else {}
    metrics = report.get("统计数据") if isinstance(report.get("统计数据"), dict) else {}

    lines = [
        (
            f"本轮飞轮任务已完成，状态 {report.get('执行状态')}。"
            f"匹配发布计划 {summary.get('匹配到的发布计划数', 0)} 条，"
            f"实际剪辑 {summary.get('实际剪辑数', 0)} 条，"
            f"实际发布 {summary.get('实际发布数', 0)} 条。"
        )
    ]
    if drama:
        lines.append(
            "，".join(
                part
                for part in [
                    f"本次短剧：《{drama.get('剧名') or ''}》",
                    f"剧场：{drama.get('剧场') or ''}",
                    f"语言：{drama.get('语言') or ''}",
                    f"集数：第 {drama.get('集数') or 0} 集" if drama.get("集数") is not None else "",
                    f"剪辑手法：{drama.get('剪辑手法') or ''}",
                    f"去重手法：{drama.get('去重手法') or ''}",
                ]
                if str(part).strip()
            )
            + "。"
        )
    if publish_result:
        lines.append(
            "，".join(
                part
                for part in [
                    f"发布账号：{publish_result.get('账号名称') or ''}",
                    f"最终状态：{publish_result.get('最终状态') or ''}",
                    f"发布时间：{publish_result.get('发布时间') or ''}",
                ]
                if str(part).strip()
            )
            + "。"
        )
    if metrics:
        lines.append(
            "，".join(
                part
                for part in [
                    f"播放 {metrics.get('播放量', 0)}",
                    f"点赞 {metrics.get('点赞数', 0)}",
                    f"评论 {metrics.get('评论数', 0)}",
                    f"分享 {metrics.get('分享数', 0)}",
                    f"收入 {metrics.get('收入', 0.0)}",
                ]
                if str(part).strip()
            )
            + "。"
        )
    return "\n".join(lines)


def parse_stage_rows(stage_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for row in stage_rows:
        item = dict(row)
        payload = item.get("result_payload")
        if isinstance(payload, str) and payload.strip():
            try:
                parsed_payload = json.loads(payload)
            except ValueError:
                parsed_payload = None
            if isinstance(parsed_payload, dict):
                item["parsed_result_payload"] = parsed_payload
        parsed.append(item)
    return parsed
