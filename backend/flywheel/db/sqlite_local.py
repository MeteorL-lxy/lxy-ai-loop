from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..selection.history_filter import build_title_history_key


class FlywheelSQLite:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self, schema_path: Path) -> None:
        with self.connect() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))
            self._ensure_column(conn, "account", "owner_agent_id", "ALTER TABLE account ADD COLUMN owner_agent_id TEXT")
            self._ensure_column(conn, "account", "publish_account_id", "ALTER TABLE account ADD COLUMN publish_account_id TEXT")
            self._ensure_column(conn, "account", "team_id", "ALTER TABLE account ADD COLUMN team_id TEXT")
            self._ensure_column(conn, "account", "social_name", "ALTER TABLE account ADD COLUMN social_name TEXT")
            self._ensure_column(conn, "account", "social_account_id", "ALTER TABLE account ADD COLUMN social_account_id TEXT")
            self._ensure_column(conn, "account", "channel_id", "ALTER TABLE account ADD COLUMN channel_id TEXT")
            self._ensure_column(conn, "drama_pick", "task_id", "ALTER TABLE drama_pick ADD COLUMN task_id TEXT")
            self._ensure_column(conn, "drama_pick", "title", "ALTER TABLE drama_pick ADD COLUMN title TEXT")
            self._ensure_column(conn, "drama_pick", "app_id", "ALTER TABLE drama_pick ADD COLUMN app_id TEXT")
            self._ensure_column(conn, "drama_pick", "language", "ALTER TABLE drama_pick ADD COLUMN language TEXT")
            self._ensure_column(conn, "drama_pick", "history_payload", "ALTER TABLE drama_pick ADD COLUMN history_payload TEXT")
            self._ensure_column(conn, "publish_plan", "agent_id", "ALTER TABLE publish_plan ADD COLUMN agent_id TEXT")
            self._ensure_column(conn, "publish_plan", "team_id", "ALTER TABLE publish_plan ADD COLUMN team_id TEXT")
            self._ensure_column(conn, "publish_plan", "promotion_link", "ALTER TABLE publish_plan ADD COLUMN promotion_link TEXT")
            self._ensure_column(conn, "publish_plan", "promotion_code", "ALTER TABLE publish_plan ADD COLUMN promotion_code TEXT")
            self._ensure_column(conn, "video_asset", "manus_id", "ALTER TABLE video_asset ADD COLUMN manus_id TEXT")
            self._ensure_column(conn, "video_asset", "source_upload_id", "ALTER TABLE video_asset ADD COLUMN source_upload_id TEXT")
            self._ensure_column(conn, "video_asset", "source_window_id", "ALTER TABLE video_asset ADD COLUMN source_window_id TEXT")
            self._ensure_column(conn, "video_asset", "media_url", "ALTER TABLE video_asset ADD COLUMN media_url TEXT")
            self._ensure_column(conn, "publish_record", "team_id", "ALTER TABLE publish_record ADD COLUMN team_id TEXT")
            self._ensure_column(conn, "publish_record", "task_id", "ALTER TABLE publish_record ADD COLUMN task_id TEXT")
            self._ensure_column(conn, "publish_record", "platform", "ALTER TABLE publish_record ADD COLUMN platform TEXT")
            self._ensure_column(conn, "publish_record", "raw_payload", "ALTER TABLE publish_record ADD COLUMN raw_payload TEXT")
            self._ensure_column(conn, "metrics_snapshot", "raw_payload", "ALTER TABLE metrics_snapshot ADD COLUMN raw_payload TEXT")
            conn.commit()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
        columns = {
            row["name"] if isinstance(row, sqlite3.Row) else row[1]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

    def create_round(self, *, dry_run: bool, config_snapshot: dict[str, Any], total_slots: int) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO round(status, dry_run, total_slots, config_snapshot)
                VALUES(?, ?, ?, ?)
                """,
                ("initialized", 1 if dry_run else 0, total_slots, json.dumps(config_snapshot, ensure_ascii=False)),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_round_status(
        self,
        round_id: int,
        *,
        status: str,
        summary: dict[str, Any] | None = None,
        error_log: str | None = None,
        finished: bool = False,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE round
                SET status = ?,
                    summary = COALESCE(?, summary),
                    error_log = COALESCE(?, error_log),
                    finished_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE finished_at END
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(summary, ensure_ascii=False) if summary is not None else None,
                    error_log,
                    1 if finished else 0,
                    round_id,
                ),
            )
            conn.commit()

    def create_stage_run(self, round_id: int, stage_name: str, status: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO round_stage(round_id, stage_name, status)
                VALUES(?, ?, ?)
                """,
                (round_id, stage_name, status),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_stage_run(
        self,
        stage_run_id: int,
        *,
        status: str,
        result_payload: dict[str, Any] | None = None,
        error_log: str | None = None,
        finished: bool = False,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE round_stage
                SET status = ?,
                    result_payload = COALESCE(?, result_payload),
                    error_log = COALESCE(?, error_log),
                    finished_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE finished_at END
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(result_payload, ensure_ascii=False) if result_payload is not None else None,
                    error_log,
                    1 if finished else 0,
                    stage_run_id,
                ),
            )
            conn.commit()

    def get_round(self, round_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM round WHERE id = ?", (round_id,)).fetchone()
            return row

    def get_round_stages(self, round_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM round_stage WHERE round_id = ? ORDER BY id ASC", (round_id,)
            ).fetchall()

    def count_rounds(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM round").fetchone()
            return int(row["count"] if row else 0)

    def count_drama_picks(self, serial_id: str | int | None) -> int:
        if serial_id in (None, ""):
            return 0
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM drama_pick WHERE serial_id = ?",
                (str(serial_id),),
            ).fetchone()
            return int(row["count"] if row else 0)

    def count_drama_picks_any(self, serial_ids: list[str | int] | tuple[str | int, ...]) -> int:
        normalized = [str(serial_id).strip() for serial_id in serial_ids if str(serial_id).strip()]
        if not normalized:
            return 0
        placeholders = ", ".join("?" for _ in normalized)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM drama_pick WHERE serial_id IN ({placeholders})",
                tuple(normalized),
            ).fetchone()
            return int(row["count"] if row else 0)

    def recent_drama_pick_serial_ids(
        self,
        *,
        before_round_id: int | None = None,
        recent_rounds: int = 0,
        recent_days: int = 0,
    ) -> set[str]:
        if recent_rounds <= 0 and recent_days <= 0:
            return set()
        base_clauses = ["dp.serial_id <> ''"]
        params: list[Any] = []
        if before_round_id is not None:
            base_clauses.append("dp.round_id < ?")
            params.append(int(before_round_id))
        recency_clauses: list[str] = []
        if recent_rounds > 0:
            recency_clauses.append(
                """
                dp.round_id IN (
                    SELECT id FROM round
                    WHERE (? IS NULL OR id < ?)
                    ORDER BY id DESC
                    LIMIT ?
                )
                """
            )
            params.extend([before_round_id, before_round_id, int(recent_rounds)])
        if recent_days > 0:
            recency_clauses.append("dp.created_at >= datetime('now', ?)")
            params.append(f"-{int(recent_days)} days")
        if recency_clauses:
            base_clauses.append("(" + " OR ".join(f"({clause.strip()})" for clause in recency_clauses) + ")")
        where = " AND ".join(f"({clause.strip()})" for clause in base_clauses)
        query = f"SELECT DISTINCT dp.serial_id FROM drama_pick dp WHERE {where}"
        with self.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return {str(row["serial_id"]).strip() for row in rows if str(row["serial_id"]).strip()}

    def recent_drama_pick_history_keys(
        self,
        *,
        before_round_id: int | None = None,
        recent_rounds: int = 0,
        recent_days: int = 0,
    ) -> set[str]:
        if recent_rounds <= 0 and recent_days <= 0:
            return set()
        base_clauses = ["dp.serial_id <> '' OR dp.title <> ''"]
        params: list[Any] = []
        if before_round_id is not None:
            base_clauses.append("dp.round_id < ?")
            params.append(int(before_round_id))
        recency_clauses: list[str] = []
        if recent_rounds > 0:
            recency_clauses.append(
                """
                dp.round_id IN (
                    SELECT id FROM round
                    WHERE (? IS NULL OR id < ?)
                    ORDER BY id DESC
                    LIMIT ?
                )
                """
            )
            params.extend([before_round_id, before_round_id, int(recent_rounds)])
        if recent_days > 0:
            recency_clauses.append("dp.created_at >= datetime('now', ?)")
            params.append(f"-{int(recent_days)} days")
        if recency_clauses:
            base_clauses.append("(" + " OR ".join(f"({clause.strip()})" for clause in recency_clauses) + ")")
        where = " AND ".join(f"({clause.strip()})" for clause in base_clauses)
        query = f"SELECT dp.serial_id, dp.title, dp.app_id, dp.history_payload FROM drama_pick dp WHERE {where}"
        with self.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        values: set[str] = set()
        for row in rows:
            serial_id = str(row["serial_id"] or "").strip()
            if serial_id:
                values.add(f"serial:{serial_id}")
            title_key = build_title_history_key(row["app_id"], row["title"])
            if title_key:
                values.add(title_key)
            try:
                payload = json.loads(row["history_payload"] or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                continue
            for payload_serial_id in payload.get("serial_ids") or []:
                normalized = str(payload_serial_id or "").strip()
                if normalized:
                    values.add(f"serial:{normalized}")
            for payload_title in payload.get("titles") or []:
                payload_title_key = build_title_history_key(row["app_id"], payload_title)
                if payload_title_key:
                    values.add(payload_title_key)
        return values

    def replace_candidate_scores(self, round_id: int, rows: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM candidate_score WHERE round_id = ?", (round_id,))
            conn.executemany(
                """
                INSERT INTO candidate_score(
                    round_id, serial_id, task_id, app_id, title, language, final_score, tier,
                    score_breakdown, raw_payload
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        round_id,
                        str(row.get("serial_id") or ""),
                        str(row.get("task_id") or ""),
                        str(row.get("app_id") or ""),
                        str(row.get("title") or ""),
                        str(row.get("language") or ""),
                        float(row.get("final_score") or 0.0),
                        row.get("tier"),
                        json.dumps(row.get("score_breakdown") or {}, ensure_ascii=False),
                        json.dumps(row.get("raw_payload") or {}, ensure_ascii=False),
                    )
                    for row in rows
                ],
            )
            conn.commit()

    def get_candidate_scores(self, round_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM candidate_score
                WHERE round_id = ?
                ORDER BY final_score DESC, id ASC
                """,
                (round_id,),
            ).fetchall()

    def import_accounts(self, rows: list[dict[str, Any]]) -> int:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO account(
                    agent_id, owner_agent_id, publish_account_id, team_id, platform, language, country,
                    provider, tier, daily_post_limit, status, social_name, social_account_id, channel_id, notes
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    owner_agent_id=excluded.owner_agent_id,
                    publish_account_id=excluded.publish_account_id,
                    team_id=excluded.team_id,
                    platform=excluded.platform,
                    language=excluded.language,
                    country=excluded.country,
                    provider=excluded.provider,
                    tier=excluded.tier,
                    daily_post_limit=excluded.daily_post_limit,
                    status=excluded.status,
                    social_name=excluded.social_name,
                    social_account_id=excluded.social_account_id,
                    channel_id=excluded.channel_id,
                    notes=excluded.notes
                """,
                [
                    (
                        str(row.get("agent_id") or ""),
                        str(row.get("owner_agent_id") or ""),
                        str(row.get("publish_account_id") or ""),
                        str(row.get("team_id") or ""),
                        str(row.get("platform") or ""),
                        str(row.get("language") or ""),
                        str(row.get("country") or ""),
                        str(row.get("provider") or "bundle_social"),
                        str(row.get("tier") or "new"),
                        int(row.get("daily_post_limit") or 3),
                        str(row.get("status") or "active"),
                        str(row.get("social_name") or ""),
                        str(row.get("social_account_id") or ""),
                        str(row.get("channel_id") or ""),
                        str(row.get("notes") or ""),
                    )
                    for row in rows
                ],
            )
            conn.commit()
            return len(rows)

    def replace_accounts(self, rows: list[dict[str, Any]]) -> int:
        with self.connect() as conn:
            conn.execute("DELETE FROM account")
            conn.commit()
        return self.import_accounts(rows)

    def list_accounts(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM account ORDER BY id ASC").fetchall()

    def replace_drama_picks(self, round_id: int, rows: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM drama_pick WHERE round_id = ?", (round_id,))
            conn.executemany(
                """
                INSERT INTO drama_pick(
                    round_id, serial_id, task_id, title, app_id, language, history_payload, tier, final_score, score_breakdown, ai_reason, slot_count, status
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        round_id,
                        str(row.get("serial_id") or ""),
                        str(row.get("task_id") or ""),
                        str(row.get("title") or ""),
                        str(row.get("app_id") or ""),
                        str(row.get("language") or ""),
                        json.dumps(row.get("history_payload") or {}, ensure_ascii=False),
                        str(row.get("tier") or ""),
                        float(row.get("final_score") or 0.0),
                        json.dumps(row.get("score_breakdown") or {}, ensure_ascii=False),
                        str(row.get("ai_reason") or ""),
                        int(row.get("slot_count") or 0),
                        str(row.get("status") or "picked"),
                    )
                    for row in rows
                ],
            )
            conn.commit()

    def get_drama_picks(self, round_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM drama_pick WHERE round_id = ? ORDER BY final_score DESC, id ASC",
                (round_id,),
            ).fetchall()

    def replace_publish_plans(self, round_id: int, rows: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM publish_plan WHERE round_id = ?", (round_id,))
            conn.executemany(
                """
                INSERT INTO publish_plan(
                    round_id, video_asset_id, account_id, agent_id, team_id, serial_id, platform,
                    promotion_link, promotion_code, caption, scheduled_at, status
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        round_id,
                        row.get("video_asset_id"),
                        str(row.get("account_id") or ""),
                        str(row.get("agent_id") or ""),
                        str(row.get("team_id") or ""),
                        str(row.get("serial_id") or ""),
                        str(row.get("platform") or ""),
                        str(row.get("promotion_link") or ""),
                        str(row.get("promotion_code") or ""),
                        str(row.get("caption") or ""),
                        row.get("scheduled_at"),
                        str(row.get("status") or "pending"),
                    )
                    for row in rows
                ],
            )
            conn.commit()

    def get_publish_plans(self, round_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM publish_plan WHERE round_id = ? ORDER BY id ASC",
                (round_id,),
            ).fetchall()

    def update_publish_plan_asset_links(self, round_id: int) -> int:
        with self.connect() as conn:
            assets = conn.execute(
                """
                SELECT va.id AS video_asset_id, dp.serial_id
                FROM video_asset va
                JOIN drama_pick dp ON dp.id = va.drama_pick_id
                WHERE va.round_id = ?
                ORDER BY va.id ASC
                """,
                (round_id,),
            ).fetchall()
            serial_to_asset_id: dict[str, int] = {}
            for row in assets:
                serial_id = str(row["serial_id"] or "")
                if serial_id and serial_id not in serial_to_asset_id:
                    serial_to_asset_id[serial_id] = int(row["video_asset_id"])

            updated = 0
            for serial_id, video_asset_id in serial_to_asset_id.items():
                cursor = conn.execute(
                    """
                    UPDATE publish_plan
                    SET video_asset_id = ?
                    WHERE round_id = ? AND serial_id = ?
                    """,
                    (video_asset_id, round_id, serial_id),
                )
                updated += int(cursor.rowcount or 0)
            conn.commit()
            return updated

    def replace_video_assets(self, round_id: int, rows: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM video_asset WHERE round_id = ?", (round_id,))
            conn.executemany(
                """
                INSERT INTO video_asset(
                    round_id, drama_pick_id, source_clip_path, episode_number, clipped_video_path,
                    manus_id, source_upload_id, source_window_id, media_url, dedup_variant, clip_options
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        round_id,
                        row.get("drama_pick_id"),
                        str(row.get("source_clip_path") or ""),
                        int(row.get("episode_number") or 0),
                        str(row.get("clipped_video_path") or ""),
                        str(row.get("manus_id") or ""),
                        str(row.get("source_upload_id") or ""),
                        str(row.get("source_window_id") or ""),
                        str(row.get("media_url") or ""),
                        str(row.get("dedup_variant") or ""),
                        json.dumps(row.get("clip_options") or {}, ensure_ascii=False),
                    )
                    for row in rows
                ],
            )
            conn.commit()

    def get_video_assets(self, round_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM video_asset WHERE round_id = ? ORDER BY id ASC",
                (round_id,),
            ).fetchall()

    def replace_publish_records(self, round_id: int, rows: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM publish_record
                WHERE publish_plan_id IN (
                    SELECT id FROM publish_plan WHERE round_id = ?
                )
                """,
                (round_id,),
            )
            conn.executemany(
                """
                INSERT INTO publish_record(
                    publish_plan_id, team_id, task_id, platform, platform_post_id, post_url,
                    published_at, status, raw_payload
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.get("publish_plan_id"),
                        str(row.get("team_id") or ""),
                        str(row.get("task_id") or ""),
                        str(row.get("platform") or ""),
                        str(row.get("platform_post_id") or ""),
                        str(row.get("post_url") or ""),
                        row.get("published_at"),
                        str(row.get("status") or ""),
                        json.dumps(row.get("raw_payload") or {}, ensure_ascii=False),
                    )
                    for row in rows
                ],
            )
            conn.commit()

    def get_publish_records(self, round_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT pr.*
                FROM publish_record pr
                JOIN publish_plan pp ON pp.id = pr.publish_plan_id
                WHERE pp.round_id = ?
                ORDER BY pr.id ASC
                """,
                (round_id,),
            ).fetchall()

    def replace_metrics_snapshots(self, round_id: int, rows: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM metrics_snapshot
                WHERE publish_record_id IN (
                    SELECT pr.id
                    FROM publish_record pr
                    JOIN publish_plan pp ON pp.id = pr.publish_plan_id
                    WHERE pp.round_id = ?
                )
                """,
                (round_id,),
            )
            conn.executemany(
                """
                INSERT INTO metrics_snapshot(
                    publish_record_id, snapshot_day, views, likes, comments, shares, revenue, raw_payload
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.get("publish_record_id"),
                        int(row.get("snapshot_day") or 0),
                        int(row.get("views") or 0),
                        int(row.get("likes") or 0),
                        int(row.get("comments") or 0),
                        int(row.get("shares") or 0),
                        float(row.get("revenue") or 0.0),
                        json.dumps(row.get("raw_payload") or {}, ensure_ascii=False),
                    )
                    for row in rows
                ],
            )
            conn.commit()

    def upsert_metrics_snapshots(self, rows: list[dict[str, Any]]) -> int:
        normalized_rows = [row for row in rows if row.get("publish_record_id") is not None]
        if not normalized_rows:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                DELETE FROM metrics_snapshot
                WHERE publish_record_id = ? AND snapshot_day = ?
                """,
                [
                    (
                        row.get("publish_record_id"),
                        int(row.get("snapshot_day") or 0),
                    )
                    for row in normalized_rows
                ],
            )
            conn.executemany(
                """
                INSERT INTO metrics_snapshot(
                    publish_record_id, snapshot_day, views, likes, comments, shares, revenue, raw_payload
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.get("publish_record_id"),
                        int(row.get("snapshot_day") or 0),
                        int(row.get("views") or 0),
                        int(row.get("likes") or 0),
                        int(row.get("comments") or 0),
                        int(row.get("shares") or 0),
                        float(row.get("revenue") or 0.0),
                        json.dumps(row.get("raw_payload") or {}, ensure_ascii=False),
                    )
                    for row in normalized_rows
                ],
            )
            conn.commit()
            return len(normalized_rows)

    def list_publish_analysis_context_rows(
        self,
        *,
        published_from: str = "",
        published_to: str = "",
        platform: str = "",
    ) -> list[sqlite3.Row]:
        clauses = ["1 = 1"]
        params: list[Any] = []
        normalized_platform = str(platform or "").strip().upper()
        if normalized_platform:
            clauses.append("UPPER(COALESCE(pr.platform, '')) = ?")
            params.append(normalized_platform)
        if str(published_from or "").strip():
            clauses.append("COALESCE(pr.published_at, pr.created_at) >= ?")
            params.append(str(published_from).strip())
        if str(published_to or "").strip():
            clauses.append("COALESCE(pr.published_at, pr.created_at) <= ?")
            params.append(str(published_to).strip())

        query = f"""
            SELECT
                pr.id AS publish_record_id,
                pr.team_id,
                pr.task_id,
                pr.platform,
                pr.platform_post_id,
                pr.post_url,
                pr.published_at,
                pr.status AS publish_status,
                pr.raw_payload AS publish_raw_payload,
                pp.id AS publish_plan_id,
                pp.round_id,
                pp.account_id,
                pp.agent_id,
                pp.serial_id,
                pp.caption,
                pp.promotion_link,
                pp.promotion_code,
                dp.title AS drama_title,
                dp.app_id AS drama_app_id,
                dp.language AS drama_language,
                a.social_name AS account_social_name
            FROM publish_record pr
            LEFT JOIN publish_plan pp ON pp.id = pr.publish_plan_id
            LEFT JOIN drama_pick dp
              ON dp.round_id = pp.round_id
             AND dp.serial_id = pp.serial_id
            LEFT JOIN account a
              ON a.publish_account_id = pp.account_id
            WHERE {' AND '.join(clauses)}
            ORDER BY pr.id DESC
        """
        with self.connect() as conn:
            return conn.execute(query, tuple(params)).fetchall()

    def append_learning_logs(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO learning_log(round_id, event_type, serial_id, payload)
                VALUES(?, ?, ?, ?)
                """,
                [
                    (
                        row.get("round_id"),
                        str(row.get("event_type") or ""),
                        str(row.get("serial_id") or ""),
                        json.dumps(row.get("payload") or {}, ensure_ascii=False),
                    )
                    for row in rows
                    if str(row.get("event_type") or "").strip()
                ],
            )
            conn.commit()
            return len(rows)

    def recent_learning_serial_ids(
        self,
        *,
        event_types: list[str] | tuple[str, ...],
        recent_days: int = 0,
        limit: int = 200,
    ) -> set[str]:
        normalized_types = [str(item).strip() for item in event_types if str(item).strip()]
        if not normalized_types:
            return set()
        clauses = [f"event_type IN ({', '.join('?' for _ in normalized_types)})", "serial_id <> ''"]
        params: list[Any] = [*normalized_types]
        if recent_days > 0:
            clauses.append("created_at >= datetime('now', ?)")
            params.append(f"-{int(recent_days)} days")
        params.append(max(1, int(limit)))
        query = f"""
            SELECT DISTINCT serial_id
            FROM learning_log
            WHERE {' AND '.join(f'({clause})' for clause in clauses)}
            ORDER BY id DESC
            LIMIT ?
        """
        with self.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return {str(row["serial_id"]).strip() for row in rows if str(row["serial_id"]).strip()}
