from __future__ import annotations

from datetime import datetime
from typing import Callable


def _feishu_plain_text(value: object) -> dict[str, object]:
    return {"tag": "plain_text", "content": str(value if value not in (None, "") else "-")}


def _feishu_lark_md(value: object) -> dict[str, object]:
    return {"tag": "lark_md", "content": str(value if value not in (None, "") else "-")}


def _day_label(value: object) -> str:
    text = str(value if value not in (None, "") else "").strip()
    if not text:
        return "-"
    for separator in (" 至 ", "到", "~", "～"):
        if separator in text:
            text = text.split(separator, 1)[0].strip()
            break
    return text[:10] if len(text) >= 10 else text


def _push_title(base_title: str, payload: dict[str, object]) -> str:
    pushed_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    round_label = str(payload.get("round_label") or "").strip()
    parts = [base_title, pushed_at]
    if round_label:
        parts.append(round_label)
    return "｜".join(parts)


def _feishu_section_title(title: str) -> dict[str, object]:
    return {
        "tag": "div",
        "text": _feishu_lark_md(f"**{title}**"),
    }


def _feishu_markdown_block(content: str) -> dict[str, object]:
    return {"tag": "div", "text": _feishu_lark_md(content.strip() or "-")}


def _feishu_rule() -> dict[str, object]:
    return {"tag": "hr"}


def _column_cell(
    text: object,
    *,
    weight: int = 1,
    bold: bool = False,
    header: bool = False,
) -> dict[str, object]:
    value = str(text if text not in (None, "") else "-")
    if bold:
        value = f"**{value}**"
    return {
        "tag": "column",
        "width": "weighted",
        "weight": weight,
        "vertical_align": "top",
        "elements": [
            {
                "tag": "div",
                "text": _feishu_lark_md(value),
            }
        ],
        "background_style": "grey" if header else "default",
    }


def _column_table(
    title: str,
    headers: list[str],
    rows: list[list[object]],
    *,
    weights: list[int] | None = None,
    empty_text: str = "暂无",
    max_rows: int | None = None,
) -> list[dict[str, object]]:
    normalized_weights = list(weights or [1] * len(headers))
    if len(normalized_weights) < len(headers):
        normalized_weights.extend([1] * (len(headers) - len(normalized_weights)))
    body_rows = rows[: max_rows or len(rows)]
    elements: list[dict[str, object]] = [_feishu_section_title(title)]
    if not body_rows:
        elements.append(_feishu_markdown_block(f"- {empty_text}"))
        return elements
    elements.append(
        {
            "tag": "column_set",
            "flex_mode": "stretch",
            "background_style": "grey",
            "columns": [
                _column_cell(header, weight=normalized_weights[index], bold=True, header=True)
                for index, header in enumerate(headers)
            ],
        }
    )
    elements.append(_feishu_rule())
    for row_index, row in enumerate(body_rows):
        padded = list(row[: len(headers)])
        if len(padded) < len(headers):
            padded.extend(["-"] * (len(headers) - len(padded)))
        elements.append(
            {
                "tag": "column_set",
                "flex_mode": "stretch",
                "columns": [
                    _column_cell(padded[index], weight=normalized_weights[index])
                    for index in range(len(headers))
                ],
            }
        )
        if row_index != len(body_rows) - 1:
            elements.append(_feishu_rule())
    return elements


def _bullet_block(title: str, items: list[str], *, limit: int | None = None) -> list[dict[str, object]]:
    elements: list[dict[str, object]] = [_feishu_section_title(title)]
    chosen = items[: limit or len(items)]
    if not chosen:
        elements.append(_feishu_markdown_block("- 暂无"))
        return elements
    elements.append(_feishu_markdown_block("\n".join(f"- {item}" for item in chosen)))
    return elements


def _safe_int(value: object) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(str(value).strip())
    except Exception:
        return 0


def _analysis_failure_summary_items(report: dict[str, object]) -> list[str]:
    summary_items = report.get("失败情况总结")
    if isinstance(summary_items, list):
        normalized = [str(item).strip() for item in summary_items if str(item).strip()]
        if normalized:
            return normalized
    items: list[str] = []
    for label, overview in [
        ("短剧", report.get("短剧总体概览") if isinstance(report.get("短剧总体概览"), dict) else {}),
        ("小说", report.get("小说总体概览") if isinstance(report.get("小说总体概览"), dict) else {}),
    ]:
        publish_failed = _safe_int(overview.get("发布失败条数"))
        upload_failed = _safe_int(overview.get("上传失败条数"))
        failed_accounts = _safe_int(overview.get("失败账号数"))
        if publish_failed <= 0 and upload_failed <= 0 and failed_accounts <= 0:
            continue
        items.append(
            f"{label}侧有失败情况：发布失败 {publish_failed} 条，上传失败 {upload_failed} 条，涉及失败账号 {failed_accounts} 个。"
        )
    return items


def _metric_rank_block(
    title: str,
    rows: list[dict[str, object]],
    *,
    name_key: str = "名称",
    empty_text: str = "暂无",
    limit: int = 10,
) -> list[dict[str, object]]:
    elements: list[dict[str, object]] = [_feishu_section_title(title)]
    chosen = rows[:limit]
    if not chosen:
        elements.append(_feishu_markdown_block(f"- {empty_text}"))
        return elements
    lines: list[str] = []
    for item in chosen:
        name = str(item.get(name_key) or item.get("短剧") or "-").strip() or "-"
        posts = item.get("帖子数") or 0
        views = item.get("播放量") or 0
        interactions = item.get("互动量") or 0
        rate = item.get("互动率") or "0.00%"
        income = item.get("收益") or 0
        lines.append(
            f"{name}｜帖子 {posts}｜播放 {views}｜互动 {interactions}｜互动率 {rate}｜收益 {income}"
        )
    elements.append(_feishu_markdown_block("\n".join(f"- {line}" for line in lines)))
    return elements


def _markdown_escape_cell(value: object) -> str:
    text = str(value if value not in (None, "") else "-")
    return text.replace("|", "\\|").replace("\n", "<br>")


def _markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    if not headers:
        return ""
    lines = [
        "| " + " | ".join(_markdown_escape_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        padded = list(row[: len(headers)])
        if len(padded) < len(headers):
            padded.extend(["-"] * (len(headers) - len(padded)))
        lines.append("| " + " | ".join(_markdown_escape_cell(cell) for cell in padded) + " |")
    return "\n".join(lines)


def _markdown_section(title: str, body: str) -> dict[str, object]:
    content = f"## {title}\n\n{body}".strip()
    return {"tag": "markdown", "content": content}


def _table_component(
    columns: list[tuple[str, str, str, str]],
    rows: list[dict[str, object]],
    *,
    page_size: int = 20,
    row_height: str = "low",
    header_background_style: str | None = None,
) -> dict[str, object]:
    payload = {
        "tag": "table",
        "page_size": page_size,
        "row_height": row_height,
        "columns": [
            {
                "name": name,
                "display_name": display_name,
                "data_type": data_type,
                "width": width,
            }
            for name, display_name, data_type, width in columns
        ],
        "rows": rows,
    }
    if header_background_style:
        payload["header_style"] = {
            "background_style": header_background_style,
            "text_color": "default",
            "bold": True,
            "text_size": "normal",
        }
    return payload


def _normalize_table_rows(columns: list[tuple[str, str, str, str]], rows: list[list[object]]) -> list[dict[str, object]]:
    names = [name for name, _, _, _ in columns]
    normalized: list[dict[str, object]] = []
    for row in rows:
        padded = list(row[: len(names)])
        if len(padded) < len(names):
            padded.extend(["-"] * (len(names) - len(padded)))
        normalized.append({name: padded[index] for index, name in enumerate(names)})
    return normalized


def _table_section(
    title: str,
    columns: list[tuple[str, str, str, str]],
    rows: list[list[object]],
    *,
    empty_text: str = "暂无",
    page_size: int = 20,
    row_height: str = "low",
    header_background_style: str | None = None,
) -> list[dict[str, object]]:
    elements: list[dict[str, object]] = [_feishu_section_title(title)]
    if not rows:
        elements.append(_feishu_markdown_block(f"- {empty_text}"))
        return elements
    elements.append(
        _table_component(
            columns,
            _normalize_table_rows(columns, rows),
            page_size=page_size,
            row_height=row_height,
            header_background_style=header_background_style,
        )
    )
    return elements


def _feishu_pairs_table_rows(items: list[list[object]]) -> list[list[object]]:
    rows: list[list[object]] = []
    for index in range(0, len(items), 2):
        left = items[index] if index < len(items) else ["", ""]
        right = items[index + 1] if index + 1 < len(items) else ["", ""]
        rows.append(
            [
                left[0] if len(left) > 0 else "",
                left[1] if len(left) > 1 else "",
                right[0] if len(right) > 0 else "",
                right[1] if len(right) > 1 else "",
            ]
        )
    return rows


def build_test_feishu_card(
    payload: dict[str, object],
    *,
    report_environment_zh: Callable[[], str],
    reason_counter_rows: Callable[[list[dict]], list[tuple[int, str, int]]],
    failed_publish_suggestions_zh: Callable[[dict], list[str]],
) -> dict[str, object]:
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    platform = str(report.get("目标平台") or payload.get("platform") or "全部平台").strip() or "全部平台"
    title = "短剧批量发布报告"
    mode = str(payload.get("mode") or "").strip()
    if mode == "local_video":
        title = "本地视频剪辑发布报告"
    elif mode == "retry_failed_publish":
        title = "失败发布重试报告"
    elif mode == "run_round":
        title = "飞轮单轮测试报告"
    detail_reports = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
    realtime_matched_count = sum(
        1 for item in detail_reports if isinstance(item, dict) and str(item.get("候选来源") or "").strip() == "实时榜匹配"
    )
    realtime_external_count = sum(
        1 for item in detail_reports if isinstance(item, dict) and str(item.get("候选来源") or "").strip() == "实时榜外部素材"
    )
    summary_rows = _feishu_pairs_table_rows(
        [
            ["生成时间", report.get("生成时间") or payload.get("generated_at") or ""],
            ["目标平台", report.get("目标平台") or platform],
            ["环境", report_environment_zh()],
            ["执行轮次", "1 轮"],
            ["目标发布数", f"{report.get('请求数量') or 0} 条"],
            ["发布成功", f"{report.get('发布成功数') or 0} 条"],
            ["发布失败", f"{len(report.get('发布失败任务') or [])} 条"],
            ["发布处理中", f"{report.get('发布处理中数') or 0} 条"],
            ["实时榜匹配任务", f"{realtime_matched_count} 条"],
            ["实时榜外部素材任务", f"{realtime_external_count} 条"],
            ["实时榜外部素材命中", f"{report.get('实时榜外部素材数') or 0} 个素材"],
            ["实时榜外部素材填充槽位", f"{report.get('实时榜外部素材填充槽位数') or 0} 个账号槽位"],
            ["安全门槛拦截", f"{((report.get('安全门槛') or {}).get('拦截数') or 0)} 条"],
            ["安全门槛补位", f"{((report.get('安全门槛') or {}).get('补位成功数') or 0)} 条"],
        ]
    )
    overview_rows = [
        [left_key, left_value, right_key, right_value]
        for left_key, left_value, right_key, right_value in summary_rows
    ]
    detail_rows = [
        [
            item.get("序号"),
            item.get("线路") or "-",
            item.get("账号"),
            item.get("短剧"),
            item.get("候选来源") or "-",
            item.get("剧场"),
            item.get("语言"),
            item.get("剪辑手法"),
            item.get("去重手法"),
            item.get("视频时长"),
            item.get("发布情况"),
            item.get("失败原因") or item.get("错误") or "",
        ]
        for item in (report.get("任务明细") if isinstance(report.get("任务明细"), list) else [])
    ]
    failure_rows = [
        [reason, count]
        for _, reason, count in reason_counter_rows(
            report.get("发布失败任务") if isinstance(report.get("发布失败任务"), list) else []
        )
    ]
    safety_reject_rows = [
        [
            item.get("类型") or "",
            item.get("原槽位") or "",
            item.get("短剧") or "",
            item.get("剧场") or "",
            item.get("集数") or "",
            item.get("原因") or "",
            item.get("补位结果") or "",
        ]
        for item in ((((report.get("安全门槛") or {}).get("拦截明细")) if isinstance((report.get("安全门槛") or {}), dict) else []) or [])
        if isinstance(item, dict)
    ]
    suggestions = failed_publish_suggestions_zh(report)
    line_runs = report.get("线路汇总") if isinstance(report.get("线路汇总"), list) else []
    line_rows = [
        [
            item.get("线路") or item.get("line_label") or item.get("line_name") or "-",
            item.get("账号池") or item.get("pool_name") or "-",
            item.get("计划数") or item.get("requested_count") or 0,
            item.get("成功数") or item.get("success_count") or 0,
            item.get("失败数") or item.get("failed_count") or 0,
            item.get("未提交数") or item.get("unsubmitted_count") or 0,
        ]
        for item in line_runs
        if isinstance(item, dict)
    ]
    theater_rows = [
        [theater, count]
        for theater, count in (
            report.get("剧场分布").items() if isinstance(report.get("剧场分布"), dict) else []
        )
    ]
    key_points: list[str] = []
    success = int(report.get("发布成功数") or 0)
    failed = int(report.get("失败数") or 0)
    processing = int(report.get("发布处理中数") or 0)
    requested = int(report.get("请求数量") or 0)
    if requested > 0:
        success_rate = f"{(success / requested) * 100:.1f}%"
        key_points.append(f"本轮共请求 {requested} 条，成功 {success} 条，失败 {failed} 条，处理中 {processing} 条，成功率 {success_rate}。")
    if theater_rows:
        theater_text = "，".join(f"{row[0]} {row[1]} 条" for row in theater_rows[:3])
        key_points.append(f"本轮剧场分布：{theater_text}。")
    if safety_reject_rows:
        rejected = int(((report.get("安全门槛") or {}).get("拦截数") or 0))
        replaced = int(((report.get("安全门槛") or {}).get("补位成功数") or 0))
        key_points.append(f"安全门槛拦截 {rejected} 条，自动补位成功 {replaced} 条。")
    if realtime_matched_count or realtime_external_count:
        key_points.append(
            f"实时榜素材已用上：实时榜匹配 {realtime_matched_count} 条，实时榜外部素材 {realtime_external_count} 条；外部素材命中 {report.get('实时榜外部素材数') or 0} 个，填充 {report.get('实时榜外部素材填充槽位数') or 0} 个账号槽位。"
        )
    else:
        key_points.append("本轮未使用实时剧目榜素材。")
    if suggestions:
        key_points.extend([str(item) for item in suggestions[:3]])
    report_day = _day_label(report.get("生成时间") or payload.get("generated_at") or payload.get("date") or "")
    elements: list[dict[str, object]] = [
        _feishu_markdown_block(
            f"共 {requested} 条任务，成功 {success} 条，失败 {failed} 条，处理中 {processing} 条；"
            f"平台 **{platform}**，报告日期 {report_day}。"
        ),
        _feishu_rule(),
    ]
    elements.extend(
        _table_section(
            f"一、执行概览（{requested}条）",
            [
                ("left_key", "指标", "text", "auto"),
                ("left_value", "数值", "text", "auto"),
                ("right_key", "指标", "text", "auto"),
                ("right_value", "数值", "text", "auto"),
            ],
            overview_rows,
            page_size=16,
            header_background_style="grey",
        )
    )
    elements.extend(
        _table_section(
            f"二、任务明细（{len(detail_rows)}条）",
            [
                ("index", "序号", "number", "auto"),
                ("line", "线路", "text", "auto"),
                ("account", "账号", "text", "auto"),
                ("drama", "短剧", "text", "auto"),
                ("source", "素材来源", "text", "auto"),
                ("theater", "剧场", "text", "auto"),
                ("language", "语言", "text", "auto"),
                ("cut", "剪辑手法", "text", "auto"),
                ("dedup", "去重手法", "text", "auto"),
                ("duration", "视频时长", "text", "auto"),
                ("status", "发布状态", "text", "auto"),
                ("remark", "备注", "text", "auto"),
            ],
            detail_rows,
            page_size=15,
            header_background_style="grey",
        )
    )
    if line_rows:
        elements.extend(
            _table_section(
                f"线路汇总（{len(line_rows)}条）",
                [
                    ("line", "线路", "text", "auto"),
                    ("pool", "账号池", "text", "auto"),
                    ("planned", "计划数", "number", "auto"),
                    ("success", "成功", "number", "auto"),
                    ("failed", "失败", "number", "auto"),
                    ("unsubmitted", "未提交", "number", "auto"),
                ],
                line_rows,
                page_size=10,
                header_background_style="grey",
            )
        )
    if key_points:
        elements.extend(_bullet_block("要点", key_points, limit=5))
    elements.extend(
        _table_section(
            f"{'四' if line_rows else '三'}、安全门槛拦截明细（{len(safety_reject_rows)}条）",
            [
                ("type", "类型", "text", "auto"),
                ("slot", "原槽位", "number", "auto"),
                ("drama", "短剧", "text", "auto"),
                ("theater", "剧场", "text", "auto"),
                ("episode", "集数", "number", "auto"),
                ("reason", "原因", "text", "auto"),
                ("replace", "补位结果", "text", "auto"),
            ],
            safety_reject_rows,
            page_size=12,
            header_background_style="grey",
        )
    )
    elements.extend(
        _table_section(
            f"四、失败原因分析（{len(failure_rows)}项）",
            [
                ("reason", "失败原因", "text", "auto"),
                ("count", "次数", "number", "auto"),
            ],
            failure_rows,
            page_size=10,
            header_background_style="grey",
        )
    )
    elements.extend(
        _table_section(
            f"五、剧场分布（{len(theater_rows)}项）",
            [
                ("theater", "剧场", "text", "auto"),
                ("count", "数量", "number", "auto"),
            ],
            theater_rows,
            page_size=10,
            header_background_style="grey",
        )
    )
    if suggestions:
        elements.extend(_bullet_block("六、处理建议", [str(item) for item in suggestions[:5]]))
    elements.extend(
        _bullet_block(
            "本轮小结",
            [
                f"{title}已完成，本轮成功 {success} 条，失败 {failed} 条，处理中 {processing} 条。"
            ],
            limit=1,
        )
    )
    return {
        "config": {"wide_screen_mode": True, "width_mode": "fill", "enable_forward": True},
        "header": {
            "template": "wathet",
            "title": {
                "tag": "plain_text",
                "content": _push_title(title, payload),
            },
        },
        "elements": elements,
    }


def build_analysis_feishu_card(payload: dict[str, object], *, compact: bool = False) -> dict[str, object]:
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    summary = report.get("总体概览") if isinstance(report.get("总体概览"), dict) else {}
    drama_overview = report.get("短剧总体概览") if isinstance(report.get("短剧总体概览"), dict) else {}
    novel_overview = report.get("小说总体概览") if isinstance(report.get("小说总体概览"), dict) else {}
    drama_task_summary = report.get("短剧任务概览") if isinstance(report.get("短剧任务概览"), dict) else {}
    novel_task_summary = report.get("小说任务概览") if isinstance(report.get("小说任务概览"), dict) else {}
    account_rows = report.get("账号维度") if isinstance(report.get("账号维度"), list) else []
    platform_rows = report.get("平台维度") if isinstance(report.get("平台维度"), list) else []
    theater_rows = report.get("剧场维度") if isinstance(report.get("剧场维度"), list) else []
    my_task_overview = report.get("我的短剧任务概览") if isinstance(report.get("我的短剧任务概览"), dict) else {}
    my_novel_task_overview = report.get("我的小说任务概览") if isinstance(report.get("我的小说任务概览"), dict) else {}
    anomaly_rows = report.get("异常账号") if isinstance(report.get("异常账号"), list) else []
    failure_summary = _analysis_failure_summary_items(report)
    suggestions = report.get("建议") if isinstance(report.get("建议"), list) else []
    account_preview = account_rows[: (5 if compact else 6)]
    platform_preview = platform_rows[:3]
    theater_preview = theater_rows[: (5 if compact else 6)]
    window = report.get("统计窗口") or ""
    platform = report.get("目标平台") or "全部平台"
    report_day = _day_label(window or payload.get("generated_at") or payload.get("date") or "")
    title = "发布数据分析日报"
    overview_items = [
            ["统计窗口", window],
            ["目标平台", platform],
            ["当日发布视频总数", summary.get("当日发布视频总数") or 0],
            ["当日发布成功数", summary.get("当日发布成功数") or 0],
            ["短剧发布总数", drama_overview.get("当日发布视频总数") or 0],
            ["小说发布总数", novel_overview.get("当日发布视频总数") or 0],
            ["短剧发布成功", drama_overview.get("当日发布成功数") or 0],
            ["小说发布成功", novel_overview.get("当日发布成功数") or 0],
            ["短剧任务数", drama_overview.get("任务数") or 0],
            ["小说任务数", novel_overview.get("任务数") or 0],
            ["短剧发布失败条数", drama_overview.get("发布失败条数") or 0],
            ["小说发布失败条数", novel_overview.get("发布失败条数") or 0],
            ["短剧上传失败条数", drama_overview.get("上传失败条数") or 0],
            ["小说上传失败条数", novel_overview.get("上传失败条数") or 0],
            ["短剧覆盖账号", drama_overview.get("覆盖账号数") or 0],
            ["小说覆盖账号", novel_overview.get("覆盖账号数") or 0],
            ["短剧当日推广链接点击次数", drama_overview.get("当日推广链接点击次数") or 0],
            ["小说当日推广链接点击次数", novel_overview.get("当日推广链接点击次数") or 0],
            ["短剧订单数", drama_overview.get("订单数") or 0],
            ["小说订单数", novel_overview.get("订单数") or 0],
            ["短剧订单金额", drama_overview.get("订单金额") or 0],
            ["小说订单金额", novel_overview.get("订单金额") or 0],
            ["短剧广告金额", drama_overview.get("广告金额") or 0],
            ["小说广告金额", novel_overview.get("广告金额") or 0],
            ["短剧分佣金额", drama_overview.get("分佣金额") or 0],
            ["小说分佣金额", novel_overview.get("分佣金额") or 0],
            ["短剧总收益", drama_overview.get("总收益") or 0],
            ["小说总收益", novel_overview.get("总收益") or 0],
            ["短剧总播放量", drama_overview.get("总播放量") or 0],
            ["小说总播放量", novel_overview.get("总播放量") or 0],
            ["短剧点赞数", drama_overview.get("点赞数") or 0],
            ["小说点赞数", novel_overview.get("点赞数") or 0],
            ["短剧评论数", drama_overview.get("评论数") or 0],
            ["小说评论数", novel_overview.get("评论数") or 0],
            ["短剧分享数", drama_overview.get("分享数") or 0],
            ["小说分享数", novel_overview.get("分享数") or 0],
            ["短剧总互动量", drama_overview.get("总互动量") or 0],
            ["小说总互动量", novel_overview.get("总互动量") or 0],
            ["短剧整体互动率", drama_overview.get("整体互动率") or "0.00%"],
            ["小说整体互动率", novel_overview.get("整体互动率") or "0.00%"],
            ["短剧剪辑下载均耗", drama_overview.get("剪辑下载均耗") or "-"],
            ["小说剪辑下载均耗", novel_overview.get("剪辑下载均耗") or "-"],
            ["短剧输出片段均长", drama_overview.get("输出片段均长") or "-"],
            ["小说输出片段均长", novel_overview.get("输出片段均长") or "-"],
            ["短剧成片探测均长", drama_overview.get("成片探测均长") or "-"],
            ["小说成片探测均长", novel_overview.get("成片探测均长") or "-"],
            ["短剧失败账号数", drama_overview.get("失败账号数") or 0],
            ["小说失败账号数", novel_overview.get("失败账号数") or 0],
            ["短剧发布失败账号数", drama_overview.get("发布失败账号数") or 0],
            ["小说发布失败账号数", novel_overview.get("发布失败账号数") or 0],
            ["剧场/短剧匹配率", summary.get("剧场短剧匹配率") or "0.00%"],
            ["千次播放收益", summary.get("千次播放收益") or 0],
    ]
    if compact:
        overview_items = overview_items[:24]
    overview_rows = _feishu_pairs_table_rows(overview_items)
    overview_table_rows = [
        [left_key, left_value, right_key, right_value]
        for left_key, left_value, right_key, right_value in overview_rows
    ]
    def metric_table(rows: list[dict[str, object]]) -> list[list[object]]:
        return [
            [
                item.get("名称") or item.get("短剧") or "-",
                item.get("帖子数") or 0,
                item.get("播放量") or 0,
                item.get("互动量") or 0,
                item.get("互动率") or "0.00%",
                item.get("收益") or 0,
            ]
            for item in rows
        ]
    my_task_overview_rows = _feishu_pairs_table_rows(
        [
            ["任务总数", my_task_overview.get("任务总数") or 0],
            ["当前平台有数据任务数", my_task_overview.get("当前平台有数据任务数") or 0],
            ["有点击任务数", my_task_overview.get("有点击任务数") or 0],
            ["有订单任务数", my_task_overview.get("有订单任务数") or 0],
            ["当前平台累计推广链接点击次数", my_task_overview.get("当前平台累计点击") or 0],
            ["当前平台累计订单", my_task_overview.get("当前平台累计订单") or 0],
            ["当前平台累计充值金额", my_task_overview.get("当前平台累计充值金额") or 0],
            ["当前平台累计广告金额", my_task_overview.get("当前平台累计广告金额") or 0],
            ["当前平台累计分佣", my_task_overview.get("当前平台累计分佣") or 0],
            ["有点击任务占比", my_task_overview.get("有点击任务占比") or "-"],
        ]
    )
    my_novel_task_overview_rows = _feishu_pairs_table_rows(
        [
            ["任务总数", my_novel_task_overview.get("任务总数") or 0],
            ["当前平台有数据任务数", my_novel_task_overview.get("当前平台有数据任务数") or 0],
            ["有点击任务数", my_novel_task_overview.get("有点击任务数") or 0],
            ["有订单任务数", my_novel_task_overview.get("有订单任务数") or 0],
            ["当前平台累计推广链接点击次数", my_novel_task_overview.get("当前平台累计点击") or 0],
            ["当前平台累计订单", my_novel_task_overview.get("当前平台累计订单") or 0],
            ["当前平台累计充值金额", my_novel_task_overview.get("当前平台累计充值金额") or 0],
            ["当前平台累计广告金额", my_novel_task_overview.get("当前平台累计广告金额") or 0],
            ["当前平台累计分佣", my_novel_task_overview.get("当前平台累计分佣") or 0],
            ["有点击任务占比", my_novel_task_overview.get("有点击任务占比") or "-"],
        ]
    )
    anomaly_table = [
        [
            item.get("账号"),
            item.get("平台"),
            item.get("帖子数") or 0,
            item.get("播放量") or 0,
            item.get("收益") or 0,
            item.get("说明") or "-",
        ]
        for item in anomaly_rows
    ]
    drama_task_overview_rows = _feishu_pairs_table_rows(
        [
            ["任务数", drama_task_summary.get("任务数") or 0],
            ["有数据任务数", drama_task_summary.get("有数据任务数") or 0],
            ["有点击任务数", drama_task_summary.get("有点击任务数") or 0],
            ["点击数", drama_task_summary.get("点击数") or 0],
            ["订单数", drama_task_summary.get("订单数") or 0],
            ["订单金额", drama_task_summary.get("订单金额") or 0],
            ["广告金额", drama_task_summary.get("广告金额") or 0],
            ["分佣金额", drama_task_summary.get("分佣金额") or 0],
        ]
    )
    novel_task_overview_rows = _feishu_pairs_table_rows(
        [
            ["任务数", novel_task_summary.get("任务数") or 0],
            ["有数据任务数", novel_task_summary.get("有数据任务数") or 0],
            ["有点击任务数", novel_task_summary.get("有点击任务数") or 0],
            ["点击数", novel_task_summary.get("点击数") or 0],
            ["订单数", novel_task_summary.get("订单数") or 0],
            ["订单金额", novel_task_summary.get("订单金额") or 0],
            ["广告金额", novel_task_summary.get("广告金额") or 0],
            ["分佣金额", novel_task_summary.get("分佣金额") or 0],
        ]
    )
    key_points: list[str] = []
    if summary:
        key_points.append(
            f"统计窗口 {window}，发布总数 {summary.get('当日发布视频总数') or 0}，成功 {summary.get('当日发布成功数') or 0}，当日点击 {summary.get('当日推广链接点击次数') or summary.get('推广链接点击次数') or 0}。"
        )
        key_points.append(
            f"总播放量 {summary.get('总播放量') or 0}，点赞 {summary.get('点赞数') or 0}，评论 {summary.get('评论数') or 0}，分享 {summary.get('分享数') or 0}，总互动量 {summary.get('总互动量') or 0}，整体互动率 {summary.get('整体互动率') or '0.00%'}。"
        )
    if drama_task_summary:
        key_points.append(
            f"短剧任务：{drama_task_summary.get('任务数') or 0} 条，点击 {drama_task_summary.get('点击数') or 0}，订单 {drama_task_summary.get('订单数') or 0}，分佣 {drama_task_summary.get('分佣金额') or 0}。"
        )
    if novel_task_summary:
        key_points.append(
            f"小说任务：{novel_task_summary.get('任务数') or 0} 条，点击 {novel_task_summary.get('点击数') or 0}，订单 {novel_task_summary.get('订单数') or 0}，分佣 {novel_task_summary.get('分佣金额') or 0}。"
        )
    if suggestions and not compact:
        key_points.extend([str(item) for item in suggestions[:2]])
    elements: list[dict[str, object]] = [
        _feishu_markdown_block(
            f"{title}已完成，覆盖 {summary.get('覆盖账号数') or 0} 个账号，发布总数 {summary.get('当日发布视频总数') or 0} 条，"
            f"成功 {summary.get('当日发布成功数') or 0} 条；平台 **{platform}**，报告日期 {report_day}。"
        ),
        _feishu_rule(),
    ]
    elements.extend(
        _table_section(
            f"一、综合总体概览（1条）",
            [
                ("left_key", "指标", "text", "auto"),
                ("left_value", "数值", "text", "auto"),
                ("right_key", "指标", "text", "auto"),
                ("right_value", "数值", "text", "auto"),
            ],
            overview_table_rows,
            page_size=16,
        )
    )
    if not compact:
        elements.extend(_bullet_block("要点", key_points, limit=4))
    conclusion = str(report.get("结论摘要") or "").strip()
    if conclusion and not compact:
        elements.extend(_bullet_block("二、结论摘要", [line.strip(" -") for line in conclusion.splitlines() if line.strip()]))
    if failure_summary:
        elements.extend(_bullet_block("三、失败情况总结", failure_summary, limit=4))
    account_metric_rows = metric_table(account_preview)
    platform_metric_rows = [
        [
            item.get("名称") or "-",
            item.get("帖子数") or 0,
            item.get("播放量") or 0,
            item.get("互动量") or 0,
            item.get("互动率") or "0.00%",
            item.get("收益") or 0,
        ]
        for item in platform_preview
    ]
    theater_metric_rows = [
        [
            item.get("名称") or "-",
            item.get("帖子数") or 0,
            item.get("播放量") or 0,
            item.get("互动量") or 0,
            item.get("互动率") or "0.00%",
            item.get("收益") or 0,
        ]
        for item in theater_preview
    ]
    if account_metric_rows:
        elements.extend(
            _table_section(
                f"四、账号维度 Top{len(account_metric_rows)}",
                [
                    ("account", "账号", "text", "auto"),
                    ("posts", "帖子", "text", "auto"),
                    ("views", "播放", "text", "auto"),
                    ("interactions", "互动", "text", "auto"),
                    ("rate", "互动率", "text", "auto"),
                    ("income", "收益", "text", "auto"),
                ],
                account_metric_rows,
                page_size=6,
            )
        )
    if platform_metric_rows:
        elements.extend(
            _table_section(
                f"五、平台维度 Top{len(platform_metric_rows)}",
                [
                    ("platform", "平台", "text", "auto"),
                    ("posts", "帖子", "text", "auto"),
                    ("views", "播放", "text", "auto"),
                    ("interactions", "互动", "text", "auto"),
                    ("rate", "互动率", "text", "auto"),
                    ("income", "收益", "text", "auto"),
                ],
                platform_metric_rows,
                page_size=6,
            )
        )
    if theater_metric_rows:
        elements.extend(
            _table_section(
                f"六、剧场维度 Top{len(theater_metric_rows)}",
                [
                    ("theater", "剧场", "text", "auto"),
                    ("posts", "帖子", "text", "auto"),
                    ("views", "播放", "text", "auto"),
                    ("interactions", "互动", "text", "auto"),
                    ("rate", "互动率", "text", "auto"),
                    ("income", "收益", "text", "auto"),
                ],
                theater_metric_rows,
                page_size=6,
            )
        )
    drama_overview_items = [
        f"{left_key}：{left_value}｜{right_key}：{right_value}"
        for left_key, left_value, right_key, right_value in my_task_overview_rows
        if str(left_key).strip() or str(right_key).strip()
    ]
    if drama_overview_items:
        elements.extend(
            _table_section(
                "七、我的短剧任务历史概览",
                [
                    ("left_key", "指标", "text", "auto"),
                    ("left_value", "数值", "text", "auto"),
                    ("right_key", "指标", "text", "auto"),
                    ("right_value", "数值", "text", "auto"),
                ],
                [[a, b, c, d] for a, b, c, d in my_task_overview_rows],
                page_size=8,
            )
        )
    else:
        elements.extend(_bullet_block("七、我的短剧任务历史概览", []))
    novel_overview_items = [
        f"{left_key}：{left_value}｜{right_key}：{right_value}"
        for left_key, left_value, right_key, right_value in my_novel_task_overview_rows
        if str(left_key).strip() or str(right_key).strip()
    ]
    if novel_overview_items:
        elements.extend(
            _table_section(
                "八、我的小说任务历史概览",
                [
                    ("left_key", "指标", "text", "auto"),
                    ("left_value", "数值", "text", "auto"),
                    ("right_key", "指标", "text", "auto"),
                    ("right_value", "数值", "text", "auto"),
                ],
                [[a, b, c, d] for a, b, c, d in my_novel_task_overview_rows],
                page_size=8,
            )
        )
    else:
        elements.extend(_bullet_block("八、我的小说任务历史概览", []))
    if anomaly_rows:
        elements.extend(
            _column_table(
                f"九、异常账号（{len(anomaly_rows)}条）",
                ["账号", "平台", "帖子数", "播放量", "收益", "说明"],
                anomaly_table[:10],
                weights=[2, 1, 1, 1, 1, 3],
                max_rows=10,
            )
        )
    else:
        elements.extend(_bullet_block("九、异常账号（0条）", []))
    if suggestions and not compact:
        elements.extend(_bullet_block("十、策略建议", [str(item) for item in suggestions[:3]]))
    elements.extend(
        _bullet_block(
            "今日小结",
            [
                f"{platform} 发布数据分析已完成，覆盖账号 {summary.get('覆盖账号数') or 0} 个，总播放 {summary.get('总播放量') or 0}，总收益 {summary.get('总收益') or 0}。"
            ],
            limit=1,
        )
    )
    return {
        "config": {"wide_screen_mode": True, "width_mode": "fill", "enable_forward": True},
        "header": {
            "template": "wathet",
            "title": {
                "tag": "plain_text",
                "content": f"发布数据分析日报（{report_day}）",
            },
        },
        "elements": elements,
    }


def build_daily_loop_feishu_card(payload: dict[str, object]) -> dict[str, object]:
    report_day = str(payload.get("date") or "").strip() or "-"
    platform = str(payload.get("platform") or "全部平台").strip() or "全部平台"
    total_requested = int(payload.get("total_requested") or 0)
    total_success = int(payload.get("total_success") or 0)
    total_failed = int(payload.get("total_failed") or 0)
    total_unsubmitted = int(payload.get("total_unsubmitted") or 0)
    executed_rounds = int(payload.get("executed_rounds") or 0)
    target_range = str(payload.get("target_range") or "-").strip() or "-"
    strategy_text = str(payload.get("strategy_text") or "").strip()
    fuse_text = str(payload.get("fuse_text") or "").strip()
    round_rows = payload.get("round_rows") if isinstance(payload.get("round_rows"), list) else []
    conclusions = payload.get("conclusions") if isinstance(payload.get("conclusions"), list) else []
    failure_summary = payload.get("failure_summary") if isinstance(payload.get("failure_summary"), list) else []

    overview_rows = _feishu_pairs_table_rows(
        [
            ["报告日期", report_day],
            ["目标平台", platform],
            ["计划目标", target_range],
            ["已执行轮次", f"{executed_rounds} 轮"],
            ["累计请求发布数", f"{total_requested} 条"],
            ["累计发布成功", f"{total_success} 条"],
            ["累计发布失败", f"{total_failed} 条"],
            ["累计未提交", f"{total_unsubmitted} 条"],
        ]
    )
    overview_table_rows = [
        [left_key, left_value, right_key, right_value]
        for left_key, left_value, right_key, right_value in overview_rows
    ]

    round_table_rows: list[list[object]] = []
    for item in round_rows:
        if not isinstance(item, dict):
            continue
        round_table_rows.append(
            [
                item.get("label") or "-",
                item.get("status_label") or item.get("status") or "-",
                item.get("scheduled_time") or "-",
                item.get("requested_count") or 0,
                item.get("success_count") or 0,
                item.get("failed_count") or 0,
                item.get("unsubmitted_count") or 0,
                item.get("note") or "-",
            ]
        )

    key_points = [
        f"今日共执行 {executed_rounds} 轮，累计请求 {total_requested} 条，成功 {total_success} 条，失败 {total_failed} 条，未提交 {total_unsubmitted} 条。",
    ]
    if strategy_text:
        key_points.append(strategy_text)
    if fuse_text:
        key_points.append(fuse_text)

    elements: list[dict[str, object]] = [
        _feishu_markdown_block(
            f"短剧日常自动发布测试总结已生成；平台 **{platform}**，报告日期 {report_day}，累计成功 **{total_success}** 条。"
        ),
        _feishu_rule(),
    ]
    elements.extend(
        _table_section(
            "一、总体概览（1条）",
            [
                ("left_key", "指标", "text", "auto"),
                ("left_value", "数值", "text", "auto"),
                ("right_key", "指标", "text", "auto"),
                ("right_value", "数值", "text", "auto"),
            ],
            overview_table_rows,
            page_size=10,
            header_background_style="grey",
        )
    )
    elements.extend(_bullet_block("要点", key_points, limit=4))
    elements.extend(
        _column_table(
            f"二、各轮结果（{len(round_table_rows)}条）",
            ["轮次", "结果", "计划时间", "请求数", "成功", "失败", "未提交", "备注"],
            round_table_rows,
            weights=[2, 1, 2, 1, 1, 1, 1, 3],
            max_rows=20,
        )
    )
    if failure_summary:
        elements.extend(_bullet_block("三、失败情况总结", [str(item) for item in failure_summary[:5]], limit=5))
    if conclusions:
        title = "四、结论" if failure_summary else "三、结论"
        elements.extend(_bullet_block(title, [str(item) for item in conclusions[:5]]))
    elements.extend(
        _bullet_block(
            "今日小结",
            [f"{platform} 短剧日常自动发布完成，最终成功 {total_success} 条。"],
            limit=1,
        )
    )
    return {
        "config": {"wide_screen_mode": True, "width_mode": "fill", "enable_forward": True},
        "header": {
            "template": "wathet",
            "title": {
                "tag": "plain_text",
                "content": f"短剧日常自动发布测试总结（{report_day}）",
            },
        },
        "elements": elements,
    }
