from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
ACCOUNT_POOLS_PATH = ROOT_DIR / "conf" / "account_pools.json"
DEFAULT_REELS_BLOCK_ERROR = "账号不能发布reel视频"
SUCCESS_STATUSES = {"POSTED", "SUCCESS", "DONE"}
RUNNING_STATUSES = {"WAITING", "PENDING", "PROCESSING", "QUEUED", "SUBMITTED", "SCHEDULED", "DRAFT"}
FAILURE_STATUSES = {"ERROR", "FAILED"}


for candidate in (ROOT_DIR / "runtime" / "dashboard-deps", Path("/tmp/codex-pymysql")):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:  # Optional dependency: the dashboard stays up and shows a config error if missing.
    import pymysql  # type: ignore
except Exception:  # pragma: no cover - depends on local runtime
    pymysql = None  # type: ignore


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(str(value).strip() or default))
    except Exception:
        return default


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(part / total * 100, 2)


def _now() -> datetime:
    return datetime.now()


def _dt_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return _text(value)


def _pool_label(key: str, description: str = "") -> str:
    friendly = {
        "facebook_drama_realtime_pool": "实时榜素材ff池-夜间",
        "facebook_drama_realtime_day_pool": "实时榜素材ff池-白天",
        "facebook_drama_realtime_single_pool": "实时榜单素材单账号池-夜间",
        "facebook_drama_creative_list_pool": "创意列表匹官剧ff池-夜间",
        "facebook_drama_creative_list_day_pool": "创意列表匹官剧ff池-白天",
        "facebook_drama_ordinary_pool": "ai-cut官剧池-夜间",
        "facebook_drama_fbhot_test_pool": "FB热度优先策略池-夜间",
        "facebook_drama_yourchannel_pool": "YourChannel 剧场线账号池-白天",
        "facebook_drama_recent_order_pool": "近月出单剧池-夜间",
        "facebook_drama_stardusttv_pool": "山海剧场线账号池-夜间",
        "facebook_drama_tag_test_pool": "打标账号剧测试池",
        "facebook_drama_reel_block_pool": "Reel限制账号池",
        "facebook_drama_exception_pool": "异常账号池",
        "facebook_drama_reserve_pool": "短剧备用池",
        "facebook_novel_dedicated_10": "小说账号池",
    }
    return friendly.get(key) or description or key


class AccountHealthDashboardService:
    def __init__(self) -> None:
        self.root_dir = ROOT_DIR
        self.account_pools_path = ACCOUNT_POOLS_PATH

    def get_overview(self, *, scope: str = "loop") -> dict[str, Any]:
        if pymysql is None:
            return {
                "available": False,
                "error": "本地缺少 pymysql，无法连接 MySQL。可安装到 runtime/dashboard-deps 后重试。",
                "last_updated": _dt_text(_now()),
            }

        scope = scope if scope in {"loop", "all"} else "loop"
        pool_map, pool_rows, loop_social_ids = self._load_pool_index()
        accounts = self._fetch_accounts(scope=scope, social_ids=loop_social_ids)
        account_ids = [str(row["id"]) for row in accounts]
        post_metrics = self._fetch_post_metrics(account_ids)
        latest_posts = self._fetch_latest_posts(account_ids, reel_only=False)
        latest_reels = self._fetch_latest_posts(account_ids, reel_only=True)

        rows = [
            self._build_account_row(
                account,
                pool_map=pool_map,
                post_metrics=post_metrics.get(str(account["id"]), {}),
                latest_post=latest_posts.get(str(account["id"]), {}),
                latest_reel=latest_reels.get(str(account["id"]), {}),
            )
            for account in accounts
        ]

        summary = self._build_summary(rows, pool_rows, scope)
        return {
            "available": True,
            "scope": scope,
            "scope_label": "我的 loop 账号池" if scope == "loop" else "全部 Facebook 账号",
            "last_updated": _dt_text(_now()),
            "source": {
                "database": os.getenv("AI_LOOP_DB_NAME", os.getenv("DB_NAME", "center")),
                "scope_account_count": len(account_ids),
                "account_pools": len(pool_rows),
                "readonly": True,
            },
            "summary": summary,
            "pool_summary": self._build_pool_summary(rows, pool_rows),
            "top_errors": self._build_top_errors(rows),
            "accounts": rows,
        }

    def _connect(self):
        host = os.getenv("AI_LOOP_DB_HOST") or os.getenv("DB_HOST")
        user = os.getenv("AI_LOOP_DB_USER") or os.getenv("DB_USER")
        password = os.getenv("AI_LOOP_DB_PASSWORD") or os.getenv("DB_PASSWORD")
        database = os.getenv("AI_LOOP_DB_NAME") or os.getenv("DB_NAME") or "center"
        if not host or not user or not password:
            raise RuntimeError("未配置数据库环境变量：需要 AI_LOOP_DB_HOST / AI_LOOP_DB_USER / AI_LOOP_DB_PASSWORD")
        return pymysql.connect(  # type: ignore[union-attr]
            host=host,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,  # type: ignore[union-attr]
            connect_timeout=8,
            read_timeout=35,
            write_timeout=10,
        )

    def _load_pool_index(self) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, Any]], list[str]]:
        try:
            payload = json.loads(self.account_pools_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        pool_map: dict[str, list[dict[str, str]]] = defaultdict(list)
        pool_rows: list[dict[str, Any]] = []
        for key, raw in payload.items() if isinstance(payload, dict) else []:
            if not isinstance(raw, dict):
                continue
            ids = [str(item).strip() for item in raw.get("account_ids") or [] if str(item).strip()]
            label = _pool_label(key, _text(raw.get("description")))
            row = {
                "key": key,
                "label": label,
                "description": _text(raw.get("description")),
                "platform": _text(raw.get("platform")) or "FACEBOOK",
                "count": len(ids),
            }
            pool_rows.append(row)
            for social_id in ids:
                pool_map[social_id].append({"key": key, "label": label})
        loop_social_ids = sorted(pool_map.keys(), key=lambda value: _safe_int(value))
        return pool_map, sorted(pool_rows, key=lambda row: row["label"]), loop_social_ids

    def _fetch_accounts(self, *, scope: str, social_ids: list[str]) -> list[dict[str, Any]]:
        where = ["type = 'FACEBOOK'", "deleted_at = 0"]
        params: list[Any] = []
        if scope == "loop":
            if not social_ids:
                return []
            where.append(f"id IN ({','.join(['%s'] * len(social_ids))})")
            params.extend(social_ids)
        sql = f"""
            SELECT id, agent_id, team_id, social_name, type, status, social_account_id, channel_id, created_at, updated_at
            FROM agent_team_social
            WHERE {' AND '.join(where)}
            ORDER BY agent_id ASC, id ASC
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]

    def _fetch_post_metrics(self, social_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not social_ids:
            return {}
        now = _now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        seven_start = now - timedelta(days=7)
        result: dict[str, dict[str, Any]] = {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                for chunk in self._chunks(social_ids, 800):
                    placeholders = ",".join(["%s"] * len(chunk))
                    sql = f"""
                        SELECT
                          social_id,
                          COUNT(CASE WHEN post_date >= %s AND post_date < %s THEN 1 END) AS today_tasks,
                          SUM(CASE WHEN post_date >= %s AND post_date < %s AND status IN ('POSTED','SUCCESS','DONE') THEN 1 ELSE 0 END) AS today_success,
                          SUM(CASE WHEN post_date >= %s AND post_date < %s AND status IN ('ERROR','FAILED') THEN 1 ELSE 0 END) AS today_failed,
                          SUM(CASE WHEN post_date >= %s AND post_date < %s AND status IN ('WAITING','PENDING','PROCESSING','QUEUED','SUBMITTED','SCHEDULED','DRAFT') THEN 1 ELSE 0 END) AS today_running,
                          COUNT(*) AS seven_tasks,
                          SUM(CASE WHEN status IN ('POSTED','SUCCESS','DONE') THEN 1 ELSE 0 END) AS seven_success,
                          SUM(CASE WHEN status IN ('ERROR','FAILED') THEN 1 ELSE 0 END) AS seven_failed,
                          SUM(CASE WHEN status IN ('WAITING','PENDING','PROCESSING','QUEUED','SUBMITTED','SCHEDULED','DRAFT') THEN 1 ELSE 0 END) AS seven_running,
                          MAX(post_date) AS latest_post_at
                        FROM agent_team_post
                        WHERE social_id IN ({placeholders})
                          AND type = 'REEL'
                          AND deleted_at IS NULL
                          AND post_date >= %s
                        GROUP BY social_id
                    """
                    params = [
                        today_start,
                        tomorrow_start,
                        today_start,
                        tomorrow_start,
                        today_start,
                        tomorrow_start,
                        today_start,
                        tomorrow_start,
                        *chunk,
                        seven_start,
                    ]
                    cur.execute(sql, params)
                    for row in cur.fetchall():
                        result[str(row["social_id"])] = dict(row)
        return result

    def _fetch_latest_posts(self, social_ids: list[str], *, reel_only: bool) -> dict[str, dict[str, Any]]:
        if not social_ids:
            return {}
        result: dict[str, dict[str, Any]] = {}
        type_clause = "AND type = 'REEL'" if reel_only else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                for chunk in self._chunks(social_ids, 800):
                    placeholders = ",".join(["%s"] * len(chunk))
                    sql = f"""
                        SELECT social_id, id, type, status, post_date, created_at, error_msg
                        FROM agent_team_post
                        WHERE social_id IN ({placeholders})
                          {type_clause}
                          AND deleted_at IS NULL
                        ORDER BY social_id ASC, post_date DESC, id DESC
                    """
                    cur.execute(sql, chunk)
                    for row in cur.fetchall():
                        social_id = str(row["social_id"])
                        if social_id not in result:
                            result[social_id] = dict(row)
        return result

    def _build_account_row(
        self,
        account: dict[str, Any],
        *,
        pool_map: dict[str, list[dict[str, str]]],
        post_metrics: dict[str, Any],
        latest_post: dict[str, Any],
        latest_reel: dict[str, Any],
    ) -> dict[str, Any]:
        social_id = str(account.get("id") or "")
        auth_normal = _safe_int(account.get("status")) == 0
        today_tasks = _safe_int(post_metrics.get("today_tasks"))
        today_success = _safe_int(post_metrics.get("today_success"))
        today_failed = _safe_int(post_metrics.get("today_failed"))
        today_running = _safe_int(post_metrics.get("today_running"))
        seven_tasks = _safe_int(post_metrics.get("seven_tasks"))
        seven_success = _safe_int(post_metrics.get("seven_success"))
        seven_failed = _safe_int(post_metrics.get("seven_failed"))
        latest_reel_status = _text(latest_reel.get("status")).upper()
        latest_reel_error = _text(latest_reel.get("error_msg"))
        reels_blocked = latest_reel_status in FAILURE_STATUSES and DEFAULT_REELS_BLOCK_ERROR in latest_reel_error
        latest_status = _text(latest_post.get("status")).upper()
        latest_error = _text(latest_post.get("error_msg"))
        latest_failed = latest_status in FAILURE_STATUSES
        is_idle = auth_normal and seven_tasks == 0

        if not auth_normal:
            health_status = "授权异常"
            health_tone = "error"
            recommendation = "先检查授权状态，暂不进入测试池。"
        elif reels_blocked:
            health_status = "不能发Reels"
            health_tone = "error"
            recommendation = "隔离到 Reels 限制池，避免继续消耗发布任务。"
        elif latest_failed:
            health_status = "发布异常"
            health_tone = "warn"
            recommendation = "观察最近失败原因，连续失败再隔离。"
        elif is_idle:
            health_status = "闲置可用"
            health_tone = "good"
            recommendation = "适合放入测试池。"
        elif today_tasks > 0:
            health_status = "正常在用"
            health_tone = "good"
            recommendation = "继续保留在当前线路。"
        else:
            health_status = "可用未发"
            health_tone = "idle"
            recommendation = "可用于当天补量或备用测试。"

        return {
            "id": social_id,
            "agent_id": _text(account.get("agent_id")),
            "team_id": _text(account.get("team_id")),
            "social_name": _text(account.get("social_name")) or f"Facebook账号 {social_id}",
            "auth_status": "正常授权" if auth_normal else "授权异常",
            "auth_status_raw": _safe_int(account.get("status")),
            "pool_labels": [row["label"] for row in pool_map.get(social_id, [])],
            "pool_keys": [row["key"] for row in pool_map.get(social_id, [])],
            "today_tasks": today_tasks,
            "today_success": today_success,
            "today_failed": today_failed,
            "today_running": today_running,
            "seven_tasks": seven_tasks,
            "seven_success": seven_success,
            "seven_failed": seven_failed,
            "seven_success_rate": _pct(seven_success, seven_tasks),
            "is_idle": is_idle,
            "can_publish_reels": not reels_blocked,
            "reels_blocked_at": _dt_text(latest_reel.get("post_date")) if reels_blocked else "",
            "latest_post_at": _dt_text(latest_post.get("post_date") or post_metrics.get("latest_post_at")),
            "latest_status": latest_status,
            "latest_error": latest_error,
            "health_status": health_status,
            "health_tone": health_tone,
            "recommendation": recommendation,
        }

    def _build_summary(self, rows: list[dict[str, Any]], pool_rows: list[dict[str, Any]], scope: str) -> dict[str, Any]:
        total = len(rows)
        normal_auth = sum(1 for row in rows if row["auth_status"] == "正常授权")
        auth_abnormal = total - normal_auth
        idle = sum(1 for row in rows if row["is_idle"])
        idle_available = sum(1 for row in rows if row["is_idle"] and row["can_publish_reels"])
        active_today = sum(1 for row in rows if row["today_tasks"] > 0)
        no_today = sum(1 for row in rows if row["auth_status"] == "正常授权" and row["today_tasks"] == 0)
        reels_blocked = sum(1 for row in rows if not row["can_publish_reels"])
        publish_abnormal = sum(1 for row in rows if row["health_status"] == "发布异常")
        today_tasks = sum(_safe_int(row["today_tasks"]) for row in rows)
        today_success = sum(_safe_int(row["today_success"]) for row in rows)
        today_failed = sum(_safe_int(row["today_failed"]) for row in rows)
        today_running = sum(_safe_int(row["today_running"]) for row in rows)
        seven_tasks = sum(_safe_int(row["seven_tasks"]) for row in rows)
        seven_success = sum(_safe_int(row["seven_success"]) for row in rows)
        seven_failed = sum(_safe_int(row["seven_failed"]) for row in rows)
        return {
            "scope": scope,
            "pool_count": len(pool_rows),
            "total_accounts": total,
            "normal_auth_accounts": normal_auth,
            "auth_abnormal_accounts": auth_abnormal,
            "available_accounts": sum(1 for row in rows if row["auth_status"] == "正常授权" and row["can_publish_reels"]),
            "active_today_accounts": active_today,
            "no_today_accounts": no_today,
            "idle_accounts": idle,
            "idle_available_accounts": idle_available,
            "reels_blocked_accounts": reels_blocked,
            "publish_abnormal_accounts": publish_abnormal,
            "today_tasks": today_tasks,
            "today_success": today_success,
            "today_failed": today_failed,
            "today_running": today_running,
            "today_success_rate": _pct(today_success, today_tasks),
            "seven_tasks": seven_tasks,
            "seven_success": seven_success,
            "seven_failed": seven_failed,
            "seven_success_rate": _pct(seven_success, seven_tasks),
        }

    def _build_pool_summary(self, rows: list[dict[str, Any]], pool_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows_by_pool: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            for key in row.get("pool_keys") or ["未分池"]:
                rows_by_pool[key].append(row)
        label_map = {row["key"]: row["label"] for row in pool_rows}
        result: list[dict[str, Any]] = []
        for key, pool_accounts in rows_by_pool.items():
            total = len(pool_accounts)
            today_tasks = sum(_safe_int(row["today_tasks"]) for row in pool_accounts)
            today_success = sum(_safe_int(row["today_success"]) for row in pool_accounts)
            result.append(
                {
                    "key": key,
                    "label": label_map.get(key) or key,
                    "accounts": total,
                    "active_today": sum(1 for row in pool_accounts if row["today_tasks"] > 0),
                    "idle": sum(1 for row in pool_accounts if row["is_idle"]),
                    "reels_blocked": sum(1 for row in pool_accounts if not row["can_publish_reels"]),
                    "today_tasks": today_tasks,
                    "today_success": today_success,
                    "today_success_rate": _pct(today_success, today_tasks),
                }
            )
        return sorted(result, key=lambda row: (-_safe_int(row["accounts"]), row["label"]))

    def _build_top_errors(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counter: Counter[str] = Counter()
        for row in rows:
            reason = _text(row.get("latest_error"))
            if reason:
                counter[reason] += 1
        return [{"reason": reason, "count": count} for reason, count in counter.most_common(8)]

    @staticmethod
    def _chunks(items: list[str], size: int):
        for index in range(0, len(items), size):
            yield items[index : index + size]
