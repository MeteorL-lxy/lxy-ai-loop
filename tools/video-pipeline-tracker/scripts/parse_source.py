#!/usr/bin/env python3
"""
解析短视频批量发布任务的 Markdown 报告 / JSON 选剧缓存，
提取字段数据并映射到 video_pipeline_tracker schema，输出标准 JSON。

适用场景：
  1. 批量发布报告（Markdown 表格） → video_pipeline_tasks 字段
  2. 选剧缓存 JSON（novel_selection_cache.json） → video_pipeline_tasks 字段

用法：
  # 解析合并报告文件（多文件用 ===FILESTART===/===FILEEND=== 分隔）
  python parse_source.py reports.txt -p myproject -a 张三
  python parse_source.py reports.txt -p myproject -a 张三 --novel-cache novel_cache.json

  # 只解析选剧缓存
  python parse_source.py --novel-cache-only novel_cache.json -p myproject -a 张三

输出：标准 JSON 数组到 stdout，可直接 pipe 到 init_db.py import
"""

import re
import json
import sys
import argparse
import csv
import os
from collections import OrderedDict


def parse_time_str(s):
    """解析视频时长 01:09 -> 秒数；也支持纯秒数"""
    if not s or not s.strip():
        return None
    s = s.strip()
    parts = s.split(":")
    if len(parts) == 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_tasks_from_md_table(md_text):
    """从 Markdown 发布报告表格中提取任务列表"""
    tasks = []
    in_table = False
    header_pattern = re.compile(r'\|\s*序号\s*\|\s*账号\s*\|')
    # 通用表格行匹配：第一列为数字，后续任意列
    task_pattern = re.compile(
        r'^\|\s*(\d+)\s*\|'
        r'\s*(.*?)\s*\|'
        r'\s*(.*?)\s*\|'
        r'\s*(.*?)\s*\|'
        r'\s*(.*?)\s*\|'
        r'\s*(.*?)\s*\|'
        r'\s*(.*?)\s*\|'
        r'\s*(.*?)\s*\|'
        r'\s*(.*?)\s*\|'
        r'(.*?)\|'
    )

    for line in md_text.split('\n'):
        if header_pattern.search(line):
            in_table = True
            continue
        if in_table and line.strip().startswith('|---'):
            continue
        if in_table and line.strip() == '':
            in_table = False
            continue
        if in_table:
            m = task_pattern.match(line)
            if m:
                tasks.append({
                    "seq": m.group(1),
                    "account": m.group(2).strip(),
                    "drama": m.group(3).strip(),
                    "theater": m.group(4).strip(),
                    "lang": m.group(5).strip(),
                    "clip_method": m.group(6).strip(),
                    "dedup_method": m.group(7).strip(),
                    "duration": m.group(8).strip(),
                    "status": m.group(9).strip(),
                    "remark": m.group(10).strip(),
                })
    return tasks


def extract_md_meta(md_text):
    """提取 Markdown 报告的元信息"""
    meta = {}
    patterns = {
        'report_time':   r'\*{1,2}(?:生成|执行)时间\*{1,2}:\s*(.+)',
        'platform':      r'\*{1,2}目标平台\*{1,2}:\s*(.+)',
        'env':           r'\*{1,2}环境\*{1,2}:\s*(.+)',
    }
    for key, pat in patterns.items():
        m = re.search(pat, md_text)
        if m:
            meta[key] = m.group(1).strip()
    return meta


def map_task_to_pipeline_record(t, report_date, platform, prefix, assignee, assignee_map=None):
    """将一条 Markdown 任务映射为 video_pipeline_tasks 字段记录"""
    raw_status = t.get('status', '')
    resolved_assignee, assignee_source = resolve_assignee(
        assignee,
        assignee_map,
        assignee=t.get('assignee'),
        owner=t.get('owner'),
        uid=t.get('uid'),
        account=t.get('account'),
        social_name=t.get('account'),
    )

    # 发布状态映射
    status_map = [
        ('成功', 'success'),
        ('失败', 'failed'),
        ('未提交', 'failed'),
        ('处理中', 'reviewing'),
        ('待执行', 'pending'),
    ]
    pub_status = 'pending'
    for kw, st in status_map:
        if kw in raw_status:
            pub_status = st
            break

    # 失败原因 & 阶段
    fail_reason = None
    fail_stage = None
    if '未提交' in raw_status:
        fail_reason = t.get('remark') or '素材未提交'
        fail_stage = 'upload'
    elif pub_status == 'failed':
        fail_reason = t.get('remark') or '发布失败'
        fail_stage = 'publish'

    record = OrderedDict([
        ("task_id", f"{prefix}_{t.get('seq','')}"),
        ("date", report_date[:10] if report_date else None),
        ("short_link_publish_time", report_date),
        ("assignee", resolved_assignee),
        ("assignee_source", assignee_source),
        ("uid", t.get('uid') or ''),
        ("social_account_id", t.get('social_account_id') or ''),
        ("douyin_t8_account", t.get('account') or '未知账号'),
        ("channel_id", (platform or 'unknown').lower()),

        ("account_type", "enterprise"),
        ("clip_tool", "auto"),
        ("drama_name", t.get('drama', '')),
        ("drama_timestamp", None),

        ("clip_params", json.dumps({
            "method": t.get('clip_method', ''),
            "dedup": t.get('dedup_method', ''),
        }, ensure_ascii=False)),
        ("output_duration_sec", parse_time_str(t.get('duration'))),

        ("publish_status", pub_status),
        ("fail_stage", fail_stage),
        ("publish_fail_reason", fail_reason),
        ("update_time", report_date),
    ])
    return record


def parse_reports_file(filepath, prefix, assignee, assignee_map=None):
    """解析多文件合并的 raw_reports.txt"""
    all_tasks = []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"✗ 文件不存在: {filepath}", file=sys.stderr)
        return all_tasks

    sections = re.split(r'===FILESTART===\s*(.+?)\s*===', content)
    reports = {}
    i = 1
    while i < len(sections) - 1:
        fname = sections[i].strip()
        body = sections[i+1]
        body = re.sub(r'===FILEEND===.*', '', body, flags=re.DOTALL).strip()
        reports[fname] = body
        i += 2

    for fname, body in reports.items():
        meta = extract_md_meta(body)
        tasks = parse_tasks_from_md_table(body)
        if not tasks:
            continue

        report_date = meta.get('report_time', 'unknown')
        platform = meta.get('platform', 'unknown')
        # 提取报告日期前缀用于唯一 task_id
        date_prefix = re.sub(r'[^0-9]', '', (report_date or 'unknown')[:10])

        for t in tasks:
            rec = map_task_to_pipeline_record(t, report_date, platform, prefix, assignee, assignee_map)
            # 确保 task_id 跨文件唯一：前缀_日期_序号
            rec['task_id'] = f"{prefix}_{date_prefix}_{t.get('seq','')}"
            all_tasks.append(rec)

    return all_tasks


def parse_novel_cache(filepath, prefix, assignee, assignee_map=None):
    """解析选剧缓存 JSON"""
    tasks = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            cache = json.load(f)
    except FileNotFoundError:
        print(f"✗ 文件不存在: {filepath}", file=sys.stderr)
        return tasks
    except json.JSONDecodeError as e:
        print(f"✗ JSON 解析失败 ({filepath}): {e}", file=sys.stderr)
        return tasks

    for item in cache.get('recent', []):
        resolved_assignee, assignee_source = resolve_assignee(
            assignee,
            assignee_map,
            assignee=item.get('assignee'),
            owner=item.get('owner'),
            uid=item.get('uid'),
            team_id=item.get('team_id'),
            social_account_id=item.get('social_account_id'),
            account=item.get('account') or item.get('account_name'),
            social_name=item.get('social_name'),
        )
        record = OrderedDict([
            ("task_id", f"{prefix}_novel_{item.get('task_id','')}"),
            ("date", (item.get('cached_at','') or '')[:10]),
            ("assignee", resolved_assignee),
            ("assignee_source", assignee_source),
            ("uid", item.get('uid', '')),
            ("social_account_id", item.get('social_account_id', '')),
            ("drama_name", item.get('title', '')),
            ("account_type", item.get('app_id', '')),
            ("drama_timestamp", item.get('cached_at', '')),
            ("channel_id", item.get('app_id', '')),
            ("publish_status", "pending"),
            ("update_time", item.get('cached_at', '')),
        ])
        tasks.append(record)
    return tasks


# ─── Daily-loop JSON 解析 (含 team_id → 可关联 Excel 账号) ───

# cut_type / dedup 英文代码 → 中文名称映射
CUT_TYPE_MAP = {
    'high_pre': '预告向高燃',
    'golden_three': '黄金三段式',
    'golden_clips': '黄金片段提取',
    'high_cut': '高燃卡点',
}
DEDUP_MAP = {
    'common_deduplication': '通用去重',
    'apply_pip': '画中画去重',
    'apply_rotate': '旋转去重',
    'apply_scale': '缩放去重',
}


def normalize_key(value):
    """用于账号/team_id 映射的宽松 key 标准化。"""
    return str(value or '').strip()


def load_assignee_map(filepath):
    """
    加载人员映射表。

    支持 JSON：
      {
        "team_id": {"team_1": "焦千为"},
        "social_account_id": {"123": "黄梓鸣"},
        "account": {"账号简称": "唐欢"}
      }

    也支持 CSV，表头可包含：
      owner/assignee, team_id, social_account_id, account, social_name
    """
    maps = {
        "uid": {},
        "team_id": {},
        "social_account_id": {},
        "account": {},
        "social_name": {},
    }
    if not filepath:
        return maps

    try:
        if filepath.lower().endswith('.json'):
            with open(filepath, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            for key in maps:
                section = raw.get(key, {}) if isinstance(raw, dict) else {}
                if isinstance(section, dict):
                    maps[key].update({normalize_key(k): normalize_key(v) for k, v in section.items() if normalize_key(k) and normalize_key(v)})
            return maps

        with open(filepath, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                owner = normalize_key(row.get('owner') or row.get('assignee') or row.get('负责人') or row.get('领用人'))
                if not owner:
                    continue
                for key, aliases in {
                    "uid": ["uid", "UID", "用户ID"],
                    "team_id": ["team_id", "teamId"],
                    "social_account_id": ["social_account_id", "socialAccountId", "账号ID", "社媒账号ID"],
                    "account": ["account", "douyin_t8_account", "账号", "账号简称"],
                    "social_name": ["social_name", "socialName", "主页名称", "账号名称"],
                }.items():
                    for alias in aliases:
                        value = normalize_key(row.get(alias))
                        if value:
                            maps[key][value] = owner
        return maps
    except FileNotFoundError:
        print(f"✗ 人员映射表不存在: {filepath}", file=sys.stderr)
        return maps
    except Exception as e:
        print(f"✗ 人员映射表读取失败 ({filepath}): {e}", file=sys.stderr)
        return maps


def resolve_assignee(default_assignee, assignee_map=None, **keys):
    """
    负责人识别优先级：
      1. 记录内已有 assignee/owner；
      2. uid 映射；
      3. team_id 映射；
      4. social_account_id 映射；
      5. account / social_name 映射；
      6. CLI -a / 环境变量兜底；
      7. unknown。
    """
    explicit = normalize_key(keys.get('assignee') or keys.get('owner'))
    if explicit:
        return explicit, "record"

    assignee_map = assignee_map or {}
    for map_key in ("uid", "team_id", "social_account_id", "account", "social_name"):
        value = normalize_key(keys.get(map_key))
        if value and assignee_map.get(map_key, {}).get(value):
            return assignee_map[map_key][value], map_key

    fallback = normalize_key(default_assignee)
    if fallback and fallback != "unknown":
        return fallback, "fallback"
    return "unknown", "unresolved"


def parse_daily_loop_json(filepath, prefix, assignee, assignee_map=None):
    """解析 daily-loop JSON 文件（含 team_id, account 信息），输出 pipeline 记录"""
    tasks = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"✗ 文件不存在: {filepath}", file=sys.stderr)
        return tasks
    except json.JSONDecodeError as e:
        print(f"✗ JSON 解析失败 ({filepath}): {e}", file=sys.stderr)
        return tasks

    # data 是 [item, ...] 的数组
    if not isinstance(data, list):
        print(f"✗ JSON 格式错误: 期望数组，实际 {type(data).__name__}", file=sys.stderr)
        return tasks

    seq = 0
    for item in data:
        seq += 1

        # 支持两种格式：
        # A) 嵌套格式: {account: {...}, drama: {...}, clip_options: {...}}
        # B) 扁平格式: {date, drama, theater, cut_type, dedup, team_id, status}
        if 'account' in item:
            acct = item.get('account', {})
            drama = item.get('drama', {})
            clip = item.get('clip_options', {})
            publish = item.get('publish', {})
            error = item.get('error', {})
            social_name = acct.get('name', '')
            uid = acct.get('uid', '') or item.get('uid', '')
            team_id = acct.get('team_id', '')
            social_account_id = acct.get('social_account_id', '') or acct.get('id', '')
            cut_code = clip.get('cut_type', '')
            dedup_raw = clip.get('deduplication', '')
            output_duration = clip.get('duration', '')
            item_status = item.get('status', 'pending')
            drama_title = drama.get('title', '')
            theater = drama.get('app_id', '')
            scheduled_at = item.get('scheduled_at', '')
        else:
            # 扁平格式
            social_name = item.get('social_name', '') or ''
            uid = item.get('uid', '')
            team_id = item.get('team_id', '')
            social_account_id = item.get('social_account_id', '') or item.get('account_id', '')
            cut_code = item.get('cut_type', '')
            dedup_raw = item.get('dedup', '')
            output_duration = None  # flat format doesn't have duration
            item_status = item.get('status', 'pending')
            drama_title = item.get('drama', '')
            theater = item.get('theater', '')
            scheduled_at = ''
            publish = {}
            error = item.get('error', {})
            social_name = social_name or ''

        if isinstance(dedup_raw, list):
            dedup_raw = dedup_raw[0] if dedup_raw else ''
        dedup_cn = DEDUP_MAP.get(dedup_raw, dedup_raw)
        cut_cn = CUT_TYPE_MAP.get(cut_code, cut_code)

        # 视频时长
        if isinstance(output_duration, str) and output_duration.lower() in ('auto', ''):
            output_duration = None
        try:
            output_duration = float(output_duration) if output_duration else None
        except (ValueError, TypeError):
            output_duration = None

        # 发布状态映射
        status_map = {
            'done': 'success',
            'failed': 'failed',
            'processing': 'reviewing',
            'pending': 'pending',
            'published_submitted': 'reviewing',
        }
        publish_status = status_map.get(item_status, item_status)

        # 错误信息
        fail_reason = ''
        if isinstance(error, dict):
            fail_reason = error.get('message', '') or error.get('error', '')
        elif isinstance(error, str):
            fail_reason = error

        # 发布后 social_post_id
        post_id = ''
        if publish and isinstance(publish, dict):
            payload = publish.get('payload', {})
            if isinstance(payload, dict):
                post_id = payload.get('post_id', '')

        resolved_assignee, assignee_source = resolve_assignee(
            assignee,
            assignee_map,
            assignee=item.get('assignee'),
            owner=item.get('owner'),
            uid=uid,
            team_id=team_id,
            social_account_id=social_account_id,
            account=social_name,
            social_name=social_name,
        )

        rec = {
            'task_id': f"{prefix}_daily_{item.get('date', '')}_{seq}",
            'date': item.get('date', ''),
            'assignee': resolved_assignee,
            'assignee_source': assignee_source,
            'uid': uid,
            'social_account_id': social_account_id,
            'douyin_t8_account': social_name or 'Facebook 账号',
            'channel_id': '',
            'drama_name': drama_title,
            'clip_params': json.dumps({
                'method': cut_cn,
                'dedup': dedup_cn,
                'theater': theater,
                'source_cut_code': cut_code,
                'source_dedup_code': dedup_raw,
            }, ensure_ascii=False),
            'output_duration_sec': output_duration,
            'publish_status': publish_status,
            'social_post_id': post_id,
            'publish_fail_reason': fail_reason,
            'short_link_publish_time': scheduled_at,
            # hidden: 保留原始关联键，方便排查解析来源
            '_uid': uid,
            '_team_id': team_id,
            '_social_account_id': social_account_id,
        }
        tasks.append(rec)

    print(f"// daily-loop 解析完成: {len(tasks)} 条记录", file=sys.stderr)
    return tasks


def main():
    parser = argparse.ArgumentParser(
        description="解析短视频批量发布报告 / 选剧缓存，输出标准 pipeline JSON")
    parser.add_argument("reports_file", nargs="?", default=None,
                        help="合并后的 Markdown 报告文件")
    parser.add_argument("-p", "--prefix", default="task",
                        help="task_id 前缀（默认 task）")
    parser.add_argument("-a", "--assignee", default=os.getenv("VIDEO_PIPELINE_ASSIGNEE", "unknown"),
                        help="负责人名称兜底值；优先用记录内字段或 --assignee-map 映射（默认 VIDEO_PIPELINE_ASSIGNEE 或 unknown）")
    parser.add_argument("--assignee-map", default=None,
                        help="人员映射表 JSON/CSV，用 uid/team_id/social_account_id/account/social_name 自动反查负责人")
    parser.add_argument("--require-assignee", action="store_true",
                        help="严格模式：存在 assignee=unknown 的记录时失败退出，防止无负责人数据入库")
    parser.add_argument("--novel-cache", default=None,
                        help="选剧缓存 JSON 文件路径")
    parser.add_argument("--novel-cache-only", default=None,
                        help="只解析选剧缓存，不解析报告")
    parser.add_argument("--daily-loop", default=None,
                        help="daily-loop JSON 文件路径（含 team_id 可关联账号）")
    parser.add_argument("-o", "--output", default=None,
                        help="输出 JSON 文件路径（默认 stdout）")

    args = parser.parse_args()
    assignee_map = load_assignee_map(args.assignee_map)

    all_tasks = []

    if args.novel_cache_only:
        all_tasks = parse_novel_cache(args.novel_cache_only, args.prefix, args.assignee, assignee_map)
    elif args.daily_loop:
        all_tasks = parse_daily_loop_json(args.daily_loop, args.prefix, args.assignee, assignee_map)
    else:
        if args.reports_file:
            all_tasks = parse_reports_file(args.reports_file, args.prefix, args.assignee, assignee_map)
        if args.novel_cache:
            novel_tasks = parse_novel_cache(args.novel_cache, args.prefix, args.assignee, assignee_map)
            all_tasks.extend(novel_tasks)

    # 去重
    seen = set()
    unique = []
    for t in all_tasks:
        tid = t.get('task_id', '')
        if tid not in seen:
            seen.add(tid)
            unique.append(t)

    unresolved = [t for t in unique if t.get('assignee') == 'unknown']
    if unresolved:
        sample = ', '.join(t.get('task_id', '') for t in unresolved[:5])
        msg = f"⚠ {len(unresolved)} 条记录未识别负责人，示例 task_id: {sample}"
        if args.require_assignee:
            print(f"✗ {msg}", file=sys.stderr)
            sys.exit(2)
        print(msg, file=sys.stderr)

    output = json.dumps(unique, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"✓ 已输出 {len(unique)} 条记录到 {args.output}", file=sys.stderr)
    else:
        print(output)

    print(f"// 总计 {len(unique)} 条记录", file=sys.stderr)


if __name__ == '__main__':
    main()
