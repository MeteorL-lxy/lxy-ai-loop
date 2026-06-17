from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "tools" / "test-pool-dashboard"

sys.path.insert(0, str(ROOT_DIR / "backend"))
from test_pool_dashboard_api import TestPoolDashboardService  # noqa: E402


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "TestPoolDashboard/1.0"

    @property
    def service(self) -> TestPoolDashboardService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/test-pool/"):
            self._handle_api(parsed)
            return
        self._serve_static(parsed.path)

    def _handle_api(self, parsed) -> None:
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/test-pool/overview":
                include_today_top_play = str(query.get("include_today_top_play", ["1"])[0]).strip().lower() not in {"0", "false", "no"}
                payload = self.service.get_overview(
                    days=int(query.get("days", ["30"])[0]),
                    include_today_top_play=include_today_top_play,
                )
            elif parsed.path == "/api/test-pool/realtime-overview":
                include_today_top_play = str(query.get("include_today_top_play", ["1"])[0]).strip().lower() not in {"0", "false", "no"}
                payload = self.service.get_realtime_overview(
                    days=int(query.get("days", ["30"])[0]),
                    include_today_top_play=include_today_top_play,
                )
            elif parsed.path == "/api/test-pool/loop-overview":
                payload = {
                    "loop_overview": self.service.get_loop_overview(),
                }
            elif parsed.path == "/api/test-pool/today-top-play":
                force = str(query.get("force", ["0"])[0]).strip().lower() in {"1", "true", "yes"}
                payload = self.service.get_today_top_play(force=force)
            elif parsed.path == "/api/test-pool/weekly-effect":
                force = str(query.get("force", ["0"])[0]).strip().lower() in {"1", "true", "yes"}
                payload = self.service.get_weekly_effect(
                    days=int(query.get("days", ["7"])[0]),
                    force=force,
                )
            elif parsed.path == "/api/test-pool/trends":
                payload = self.service.get_trends(days=int(query.get("days", ["30"])[0]))
            elif parsed.path == "/api/test-pool/trend-analyzer":
                refresh = str(query.get("refresh", ["0"])[0]).strip().lower() in {"1", "true", "yes"}
                payload = self.service.get_trend_analyzer(refresh=refresh)
            elif parsed.path == "/api/test-pool/daily-top-history":
                force = str(query.get("force", ["0"])[0]).strip().lower() in {"1", "true", "yes"}
                payload = self.service.get_daily_top_play_history(force=force)
            elif parsed.path == "/api/test-pool/options":
                payload = self.service.get_options()
            elif parsed.path == "/api/test-pool/rounds":
                payload = self.service.list_rounds(
                    day_key=str(query.get("day", [""])[0]),
                    runtime_mode=str(query.get("runtime_mode", [""])[0]),
                    line_name=str(query.get("line_name", [""])[0]),
                    status=str(query.get("status", [""])[0]),
                    search=str(query.get("search", [""])[0]),
                    limit=int(query.get("limit", ["100"])[0]),
                    offset=int(query.get("offset", ["0"])[0]),
                )
            elif parsed.path == "/api/test-pool/failures":
                payload = self.service.get_failures(limit=int(query.get("limit", ["50"])[0]))
            elif parsed.path == "/api/test-pool/accounts":
                payload = self.service.get_accounts(limit=int(query.get("limit", ["50"])[0]))
            elif parsed.path.startswith("/api/test-pool/round/"):
                archive_key = unquote(parsed.path.split("/api/test-pool/round/", 1)[1])
                payload = self.service.get_round_detail(archive_key)
            else:
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
        except KeyError:
            self._send_json({"error": "round not found"}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _serve_static(self, path: str) -> None:
        target = "index.html" if path in {"", "/"} else path.lstrip("/")
        file_path = (STATIC_DIR / target).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.exists() or not file_path.is_file():
            self._send_text("Not Found", status=HTTPStatus.NOT_FOUND)
            return
        mime, _ = mimetypes.guess_type(str(file_path))
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local test-pool dashboard server.")
    parser.add_argument("--host", default=os.getenv("TEST_POOL_DASHBOARD_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("TEST_POOL_DASHBOARD_PORT", "8765")))
    args = parser.parse_args()

    if not STATIC_DIR.exists():
        raise SystemExit(f"static dir not found: {STATIC_DIR}")

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    server.service = TestPoolDashboardService()  # type: ignore[attr-defined]
    print(
        json.dumps(
            {
                "status": "ok",
                "url": f"http://{args.host}:{args.port}",
                "db": str(server.service.db_path),  # type: ignore[attr-defined]
                "static_dir": str(STATIC_DIR),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
