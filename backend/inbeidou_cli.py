#!/usr/bin/env python3
"""
北斗智影 AI 创作者中心 CLI

已支持:
- user: 用户信息
- credit: 积分余额
- products: AI 工具/产品列表
- languages: 翻译语言
- publish: 矩阵发布
- uploads: 媒资库管理
- analyze: 智影解析
- clip: 智能剪辑
- translate: 视频翻译
- manus: 我的作品
- list: 短剧列表
- detail: 短剧详情/推广链接
- episodes: 短剧剧集列表/取集入库
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import mimetypes
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from typing import Dict, Optional, Tuple
from threading import Lock, local
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests
from websocket import create_connection
from websocket._exceptions import WebSocketException, WebSocketTimeoutException

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from flywheel.feishu_cards import build_novel_test_feishu_card


API_ENV = os.getenv("BARRY_VIDEO_API_ENV") or os.getenv("INBEIDOU_API_ENV") or "test"
API_ENV = API_ENV.strip().lower()

API_ENVIRONMENTS = {
    "prod": {
        "scenter": "https://api-scenter.inbeidou.cn",
        "icenter": "https://api-icenter.inbeidou.cn",
        "tool": "https://api-tool.inbeidou.cn",
        "claw": "https://api-claw.inbeidou.cn",
        "ws_icenter": "wss://api-icenter.inbeidou.cn",
        "ws_claw": "wss://api-claw.inbeidou.cn",
    },
    "production": {
        "scenter": "https://api-scenter.inbeidou.cn",
        "icenter": "https://api-icenter.inbeidou.cn",
        "tool": "https://api-tool.inbeidou.cn",
        "claw": "https://api-claw.inbeidou.cn",
        "ws_icenter": "wss://api-icenter.inbeidou.cn",
        "ws_claw": "wss://api-claw.inbeidou.cn",
    },
    "test": {
        "scenter": "https://test-api-scenter.inbeidou.cn",
        "icenter": "https://test-api-icenter.inbeidou.cn",
        "tool": "https://test-api-tool.inbeidou.cn",
        "claw": "https://test-api-claw.inbeidou.cn",
        "ws_icenter": "wss://test-api-icenter.inbeidou.cn",
        "ws_claw": "wss://test-api-claw.inbeidou.cn",
    },
}

API_BASES = API_ENVIRONMENTS.get(API_ENV, API_ENVIRONMENTS["test"])

SCENTER_API = os.getenv("BARRY_VIDEO_SCENTER_API") or f"{API_BASES['scenter']}/agent/v1"
ICENTER_API = os.getenv("BARRY_VIDEO_ICENTER_API") or f"{API_BASES['icenter']}/ai/v1"
TOOL_API = os.getenv("BARRY_VIDEO_TOOL_API") or f"{API_BASES['tool']}/ai/v1"
CLAW_API = os.getenv("BARRY_VIDEO_CLAW_API") or API_BASES["claw"]
WS_MANUS_CHATS = os.getenv("BARRY_VIDEO_WS_MANUS_CHATS") or f"{API_BASES['ws_icenter']}/ai/v1/ws/manus/chats"
WS_CLAW_CHAT = os.getenv("BARRY_VIDEO_WS_CLAW_CHAT") or f"{API_BASES['ws_claw']}/v1/claw/chat"

DEFAULT_TIMEOUT = 60
DEFAULT_POLL_INTERVAL = 3
DEFAULT_TASK_TIMEOUT = 1800
DEFAULT_MANUS_MEDIA_TIMEOUT = max(
    15,
    min(600, int(os.getenv("BARRY_VIDEO_MANUS_MEDIA_TIMEOUT", "120") or 120)),
)
DEFAULT_MANUS_MEDIA_POLL_INTERVAL = max(
    1.0,
    min(30.0, float(os.getenv("BARRY_VIDEO_MANUS_MEDIA_POLL_INTERVAL", "3") or 3.0)),
)
DEFAULT_NOVEL_SEGMENT_TASK_TIMEOUT = max(
    180,
    min(1200, int(os.getenv("BARRY_VIDEO_NOVEL_SEGMENT_TIMEOUT", "480") or 480)),
)
DEFAULT_VIDU_REQUEST_RETRIES = 3
DEFAULT_NOVEL_PUBLISH_FOLLOWUP_DELAY = max(
    60,
    min(3600, int(os.getenv("BARRY_VIDEO_NOVEL_PUBLISH_FOLLOWUP_DELAY", "1800") or 1800)),
)
DEFAULT_NOVEL_VIDU_CONCURRENCY = max(1, min(20, int(os.getenv("BARRY_VIDEO_NOVEL_VIDU_CONCURRENCY", "2") or 2)))
DEFAULT_NOVEL_BATCH_CONCURRENCY = max(1, min(20, int(os.getenv("BARRY_VIDEO_NOVEL_BATCH_CONCURRENCY", "3") or 3)))
DEFAULT_NOVEL_CHAPTER_RETRIES = max(1, min(5, int(os.getenv("BARRY_VIDEO_NOVEL_CHAPTER_RETRIES", "3") or 3)))


def _resolve_path_env(name: str, default: str) -> Path:
    return Path(os.getenv(name) or default).expanduser()


AUTH_HOME = _resolve_path_env("BARRY_VIDEO_AUTH_HOME", "~/.barry-video")
STATE_FILE = _resolve_path_env(
    "BARRY_VIDEO_STATE_FILE",
    str(AUTH_HOME / "inbeidou_cli_state.json") if os.getenv("BARRY_VIDEO_AUTH_HOME") else "~/.inbeidou_cli_state.json",
)
AUTH_STATE_FILE = _resolve_path_env("BARRY_VIDEO_AUTH_STATE_FILE", str(AUTH_HOME / "auth_state.json"))
VIDU_AUTH_FILE = _resolve_path_env("BARRY_VIDEO_VIDU_AUTH_FILE", str(AUTH_HOME / "vidu_auth.json"))
NOVEL_SELECTION_CACHE_FILE = _resolve_path_env(
    "BARRY_VIDEO_NOVEL_SELECTION_CACHE_FILE",
    str(AUTH_HOME / "novel_selection_cache.json"),
)
DEFAULT_FEISHU_ENV_FILE = str(AUTH_HOME / "feishu.env")
DEFAULT_NOVEL_DOWNLOAD_DIR = _resolve_path_env(
    "BARRY_VIDEO_NOVEL_DOWNLOAD_DIR",
    str(Path.home() / "Downloads" / "barry-video-novels"),
)
DEFAULT_NOVEL_TMP_DIR = _resolve_path_env(
    "BARRY_VIDEO_NOVEL_TMP_DIR",
    str(Path(tempfile.gettempdir()) / "barry-video-novels"),
)
DEFAULT_NOVEL_WORK_DIR = _resolve_path_env(
    "BARRY_VIDEO_NOVEL_WORK_DIR",
    str(Path(tempfile.gettempdir()) / "barry-video-novels-work"),
)
ACCOUNT_POOL_FILE = Path(__file__).resolve().parents[1] / "conf" / "account_pools.json"
VIDU_API_BASE = os.getenv("BARRY_VIDEO_VIDU_API") or "https://api.vidu.cn/ent/v2"
PROJECT_ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_DELETE_ALLOWED_ROOTS = (
    PROJECT_ROOT_DIR / "data",
    PROJECT_ROOT_DIR / "runtime",
    DEFAULT_NOVEL_DOWNLOAD_DIR,
    DEFAULT_NOVEL_TMP_DIR,
    DEFAULT_NOVEL_WORK_DIR,
)
PROJECT_DELETE_PROTECTED_NAMES = {
    ".git",
    "backend",
    "bin",
    "conf",
    "docs",
    "ops",
    "scripts",
    "skills",
    "tools",
}


def _is_relative_to_path(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_cleanup_target(path: Path) -> tuple[bool, str]:
    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        return False, f"path resolve failed: {exc}"
    if resolved == PROJECT_ROOT_DIR or PROJECT_ROOT_DIR in resolved.parents:
        rel = resolved.relative_to(PROJECT_ROOT_DIR)
        if rel.parts and rel.parts[0] in PROJECT_DELETE_PROTECTED_NAMES:
            return False, "refuse to delete project source/config directory"
        if not any(_is_relative_to_path(resolved, root.resolve()) for root in PROJECT_DELETE_ALLOWED_ROOTS):
            return False, "refuse to delete project file outside artifact roots"
    if resolved in {Path.home().resolve(), Path(tempfile.gettempdir()).resolve()}:
        return False, "refuse to delete home or temp root"
    return True, ""

PLATFORMS = {
    "dramabox": "DramaBox",
    "flareflow": "FlareFlow",
    "shortmax": "ShortMax",
    "flickreels": "FlickReels",
    "reelshort": "ReelShort",
    "goodshort": "GoodShort",
    "moboreels": "MoboReels",
    "kalos": "KalosTV",
    "snackshort": "SnackShort",
    "touchshort": "TouchShort",
    "dreameshort": "DreameShort",
    "honeyreels": "HoneyReels",
    "pancake": "Pancake",
    "starshort": "StarShort",
    "sereal": "Sereal+",
    "dramasnacker": "DramaSnacker(H5)",
    "playlet": "Playlet",
}
NOVEL_PLATFORMS = {
    "novelshort": "NovelShort",
    "novelmaster": "NovelMaster",
    "realnovel": "RealNovel",
    "goodnovel": "GoodNovel",
    "myfiction": "MyFiction",
    "motonovel": "MotoNovel",
    "novellia": "NovelLia",
    "snackshort_novel": "SnackShort",
    "literie": "Literie",
    "webfic": "Webfic",
    "moboreader": "MoboReader",
}

PROMOTION_PLATFORMS = {
    1: "TikTok",
    2: "Facebook",
    3: "Instagram",
    4: "YouTube",
}
PROMOTION_PLATFORM_NAMES = {name.lower(): platform_id for platform_id, name in PROMOTION_PLATFORMS.items()}

HIGH_CUT_TASK_KEY = "high"
TRANSLATE_TASK_KEY = "trans"
RUNNING_STATUSES = {"loading", "pending", "processing", "executing"}
HIGH_CUT_CHOICES = ["high_cut", "golden_three", "golden_clips", "high_pre"]
DEDUPLICATION_CHOICES = [
    "common_deduplication",
    "apply_pip",
    "apply_rotate",
    "apply_scale",
    "apply_flip",
    "apply_frame",
    "apply_special",
    "apply_speed",
    "apply_reduce_frame_rate",
    "apply_mirror_pip",
]
DEFAULT_DEDUPLICATION = ["common_deduplication", "apply_pip"]
NOVEL_VIDEO_GENERATORS = ["vidu"]
NOVEL_ACCOUNT_POOLS = [
    "facebook_novel_dedicated_10",
]
DEFAULT_NOVEL_FACEBOOK_ACCOUNT_POOL = "facebook_novel_dedicated_10"
DEFAULT_NOVEL_GENERATOR = "vidu"
DEFAULT_NOVEL_VIDEO_MODEL = "viduq3-turbo"
DEFAULT_NOVEL_IMAGE_MODEL = "viduq2"
DEFAULT_NOVEL_VIDU_DURATION = 0
DEFAULT_NOVEL_VIDU_RESOLUTION = "540p"
NOVEL_VIDU_VIDEO_MODELS = ["viduq3-pro-fast", "viduq3-turbo", "viduq3-pro"]
VIDU_MODELS = ["viduq3-turbo", "viduq3-mix", "viduq3", "viduq3-pro-fast", "viduq3-pro", "viduq2-pro", "viduq2", "viduq1", "vidu2.0"]
VIDU_ASPECT_RATIOS = ["16:9", "9:16", "3:4", "4:3", "1:1"]
VIDU_RESOLUTIONS = ["540p", "720p", "1080p"]
NOVEL_SEGMENT_COUNT_RANGE = (5, 6)
NOVEL_SEGMENT_DURATION_RANGE = (4, 5)
NOVEL_TOTAL_DURATION_RANGE = (180, 180)
NOVEL_MAX_TOTAL_DURATION = 210
NOVEL_GENERATION_CHAIN_VIDU_IMAGE = "vidu_image_chain"
NOVEL_GENERATION_CHAINS = [NOVEL_GENERATION_CHAIN_VIDU_IMAGE]
NOVEL_BATCH_TARGET_SUCCESS_RATE = 0.9
NOVEL_BATCH_MAX_RETRIES_PER_ACCOUNT = 3
VIDU_AUDIT_ERROR_CODES = {
    "AuditSubmitIllegal",
    "TaskPromptPolicyViolation",
    "CreationPolicyViolation",
    "PhotoAuditNotPass",
    "AuditFailed",
}
NOVEL_AUDIT_DROP_PATTERNS = [
    ("sexual_violence", r"(?i)\b(rape|raped|sexual assault|molest(?:ed)?|incest|underage sex|child abuse)\b|强暴|强奸|性侵|迷奸|乱伦|未成年"),
    ("self_harm", r"(?i)\b(suicide|self-harm|self harm|kill myself|cut myself)\b|自杀|自残|割腕|寻死"),
    ("graphic_violence", r"(?i)\b(dismember|decapitat(?:e|ed|ion)|corpse|gore|behead(?:ed)?|exploding head)\b|肢解|砍头|爆头|尸体|碎尸"),
]
NOVEL_AUDIT_SOFTEN_REPLACEMENTS = [
    (r"(?i)\b(kill|killed|killing|murder|murdered|slaughter|execute)\b", "defeat"),
    (r"(?i)\b(stab(?:bed)?|knife|gun|shoot(?:ing|s)?|bleed(?:ing)?|bloody|blood)\b", "danger"),
    (r"(?i)\b(torture|abuse|beating|beat(?:en|ing)?)\b", "conflict"),
    (r"(?i)\b(drug(?:ged|ging)?|poison(?:ed|ing)?)\b", "scheme"),
    (r"(?i)\b(mistress|lover|affair|cheat(?:ing|ed)?|adultery)\b", "relationship conflict"),
    (r"(?i)\b(pregnan(?:t|cy)|belly|due soon|appointment|hormones)\b", "family situation"),
    (r"(?i)\b(kiss(?:ed|ing)?|seduce(?:d|ing)?|sneak(?:ing)? around)\b", "emotional tension"),
    (r"杀死|杀了|谋杀|屠杀|刺死|捅死|鲜血|流血|血腥|尸体|遗体", "击败"),
    (r"虐待|折磨|毒打|暴打|下毒|投毒", "冲突"),
    (r"出轨|小三|情妇|偷情|外遇|怀孕|孕肚|约会|激吻", "情感冲突"),
    (r"床上|做爱|亲热|暧昧缠绵", "感情纠葛"),
]

DEFAULT_TRANSLATE_CONFIG = {
    "source_language": "zh",
    "target_language": "en",
    "need_speech_translate": True,
    "subtitle_type": "double",
    "subtitle_y": 60,
    "font": "Alibaba PuHuiTi",
    "font_size": 22,
    "font_color": "#ffffff",
    "alignment": "Center",
    "font_face_bold": False,
    "font_face_underline": False,
    "font_face_italic": False,
    "font_color_opacity": 100,
    "effect_color_style": "",
    "shadow": False,
    "shadow_shift": 3,
    "shadow_x_bord": 1,
    "shadow_y_bord": 1,
    "shadow_opacity": 80,
    "outline": False,
    "outline_board": 3,
}

DEFAULT_HIGH_CUT_CONFIG = {
    "cut_duration": "auto",
    "output_count": 1,
    "cut_type": "high_cut",
    "script_count": 1,
    "watermark": "",
}

PUBLISH_SOCIAL_TYPES = ["TIKTOK", "FACEBOOK", "INSTAGRAM", "YOUTUBE"]
PUBLISH_SOCIAL_NAMES = {
    "TIKTOK": "TikTok",
    "FACEBOOK": "Facebook",
    "INSTAGRAM": "Instagram",
    "YOUTUBE": "YouTube",
}
PUBLISH_TO_PROMOTION_PLATFORM = {
    "TIKTOK": 1,
    "FACEBOOK": 2,
    "INSTAGRAM": 3,
    "YOUTUBE": 4,
}
PUBLISH_ACCOUNT_STATUSES = {
    0: "正常授权中",
    1: "授权已失效",
    2: "未绑定公共主页/频道",
}
PUBLISH_POST_STATUS_VALUE = {
    "published": 0,
    "scheduled": 1,
}
PUBLISH_MAX_UPLOAD_SIZE = 1000 * 1024 * 1024
RUNNING_PUBLISH_STATUSES = {"WAITING", "PENDING", "PROCESSING", "QUEUED", "SUBMITTED", "SCHEDULED"}
SUCCESSFUL_PUBLISH_STATUSES = {"POSTED", "SUCCESS", "DONE"}
FINAL_FAILURE_PUBLISH_STATUSES = {"ERROR", "FAILED"}
NOVEL_PUBLISH_SETTLE_TIMEOUT_REASON = "发布状态确认超时，请稍后手动复核发布记录。"
NOVEL_PUBLISH_IN_PROGRESS_REASON = "发布任务仍在处理中，请稍后手动复核发布记录。"
NOVEL_PUBLISH_DEFAULT_WAIT_SECONDS = 900
NOVEL_PUBLISH_PLATFORM_WAIT_SECONDS = {
    "TIKTOK": 900,
    "FACEBOOK": 600,
    "INSTAGRAM": 600,
    "YOUTUBE": 600,
}
DEFAULT_TEST_SUMMARY_DIR = "/Users/xinyuliu/Downloads/AI Loop/测试总结"
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
_FEISHU_ENV_LOADED = False


class InbeidouError(RuntimeError):
    """通用 CLI 异常。"""


def load_json_file(path):
    """读取 JSON 文件，不存在或格式非法时返回空字典。"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(data):
    """保存最近一次上传/任务上下文，便于后续命令复用。"""
    payload = load_json_file(STATE_FILE)
    payload.update(data)
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_feishu_env_once() -> None:
    global _FEISHU_ENV_LOADED
    if _FEISHU_ENV_LOADED:
        return
    _FEISHU_ENV_LOADED = True
    env_file = Path(os.getenv("BARRY_FEISHU_ENV_FILE") or DEFAULT_FEISHU_ENV_FILE).expanduser()
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _env_truthy_with_default(name: str, *, default: bool) -> bool:
    _load_feishu_env_once()
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _novel_feishu_push_enabled() -> bool:
    return _env_truthy_with_default("BARRY_FEISHU_NOVEL_PUSH", default=_env_truthy_with_default("BARRY_FEISHU_TEST_PUSH", default=True))


def _novel_test_summary_dir() -> Path:
    _load_feishu_env_once()
    return Path(os.getenv("BARRY_VIDEO_TEST_SUMMARY_DIR") or DEFAULT_TEST_SUMMARY_DIR).expanduser()


def _feishu_app_id() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_FEISHU_APP_ID") or "").strip()


def _feishu_app_secret() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_FEISHU_APP_SECRET") or "").strip()


def _feishu_target_open_id() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_FEISHU_TARGET_OPEN_ID") or "").strip()


def _feishu_target_user_id() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_FEISHU_TARGET_USER_ID") or "").strip()


def _feishu_target_email() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_FEISHU_TARGET_EMAIL") or "").strip()


def _feishu_timeout_seconds() -> int:
    _load_feishu_env_once()
    raw = str(os.getenv("BARRY_FEISHU_TIMEOUT") or "30").strip()
    try:
        return max(5, int(raw))
    except ValueError:
        return 30


def _feishu_post(path: str, payload: dict, *, tenant_token: str = "") -> dict:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if tenant_token:
        headers["Authorization"] = f"Bearer {tenant_token}"
    response = requests.post(
        f"{FEISHU_API_BASE}{path}",
        headers=headers,
        json=payload,
        timeout=_feishu_timeout_seconds(),
    )
    raw_text = response.text
    try:
        body = response.json()
    except ValueError:
        body = {"code": response.status_code, "msg": raw_text}
    if response.status_code >= 400:
        raise RuntimeError(f"飞书接口 HTTP {response.status_code}: {body}")
    if int(body.get("code", 0)) != 0:
        raise RuntimeError(f"飞书接口失败: {body.get('msg') or body}")
    data = body.get("data")
    return data if isinstance(data, dict) else body


def _feishu_get_tenant_access_token() -> str:
    app_id = _feishu_app_id()
    app_secret = _feishu_app_secret()
    if not app_id or not app_secret:
        raise RuntimeError("缺少飞书应用凭证，请设置 BARRY_FEISHU_APP_ID / BARRY_FEISHU_APP_SECRET")
    data = _feishu_post(
        "/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
    )
    token = str(data.get("tenant_access_token") or "").strip()
    if not token:
        raise RuntimeError("飞书 tenant_access_token 为空")
    return token


def _feishu_receive_target() -> tuple[str, str]:
    email = _feishu_target_email()
    if email:
        return "email", email
    open_id = _feishu_target_open_id()
    if open_id:
        return "open_id", open_id
    user_id = _feishu_target_user_id()
    if user_id:
        return "user_id", user_id
    raise RuntimeError("缺少飞书接收人，请设置 BARRY_FEISHU_TARGET_EMAIL、BARRY_FEISHU_TARGET_OPEN_ID 或 BARRY_FEISHU_TARGET_USER_ID")


def _feishu_send_text_message(tenant_token: str, *, receive_id_type: str, receive_id: str, text: str) -> dict:
    return _feishu_post(
        f"/im/v1/messages?receive_id_type={receive_id_type}",
        {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        tenant_token=tenant_token,
    )


def _feishu_send_interactive_message(tenant_token: str, *, receive_id_type: str, receive_id: str, card: dict) -> dict:
    return _feishu_post(
        f"/im/v1/messages?receive_id_type={receive_id_type}",
        {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        },
        tenant_token=tenant_token,
    )


def load_state():
    """读取最近一次上下文。"""
    return load_json_file(STATE_FILE)


def load_auth_state():
    """读取授权缓存，并校验当前 API 环境是否匹配。"""
    payload = load_json_file(AUTH_STATE_FILE)

    if payload.get("status") != "success":
        return {}
    cached_api_base = str(payload.get("api_base_url") or "").rstrip("/")
    if cached_api_base and cached_api_base != CLAW_API.rstrip("/"):
        return {}
    if not payload.get("expired_at") or int(payload["expired_at"]) <= int(time.time() * 1000):
        return {}
    return payload


def load_auth_token():
    """优先从环境变量，其次从 beidou-auth 缓存读取 token。"""
    token = os.getenv("INBEIDOU_TOKEN", "").strip()
    if token:
        return token

    payload = load_auth_state()
    if not payload:
        return ""
    return str(payload.get("access_token", "")).strip()


def load_vidu_auth_state():
    """读取官方 Vidu 授权缓存。"""
    return load_json_file(VIDU_AUTH_FILE)


def load_vidu_api_key():
    """优先从环境变量，其次从本地 Vidu 缓存读取 API key。"""
    for env_name in ("BARRY_VIDEO_VIDU_API_KEY", "VIDU_API_KEY"):
        value = str(os.getenv(env_name) or "").strip()
        if value:
            return value
    payload = load_vidu_auth_state()
    return str(payload.get("api_key") or "").strip()


def load_novel_selection_cache():
    """读取已选小说缓存，避免自然语言二次执行时丢失 app_id。"""
    payload = load_json_file(NOVEL_SELECTION_CACHE_FILE)
    return payload if isinstance(payload, dict) else {}


def save_novel_selection_cache(payload):
    """保存已选小说缓存。"""
    NOVEL_SELECTION_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    NOVEL_SELECTION_CACHE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def remember_selected_novel(novel: dict):
    """缓存最近选中的小说定位信息，便于后续只带 task_id 也能稳定复用。"""
    task_id = str((novel or {}).get("task_id") or "").strip()
    app_id = str((novel or {}).get("app_id") or "").strip()
    if not task_id or not app_id:
        return
    cache = load_novel_selection_cache()
    item = {
        "task_id": task_id,
        "app_id": app_id,
        "title": str((novel or {}).get("title") or "").strip(),
        "title_ch": str((novel or {}).get("title_ch") or "").strip(),
        "cached_at": datetime.now().isoformat(timespec="seconds"),
    }
    recent = cache.get("recent") if isinstance(cache.get("recent"), list) else []
    recent = [entry for entry in recent if str((entry or {}).get("task_id") or "").strip() != task_id]
    recent.insert(0, item)
    cache["recent"] = recent[:50]
    mapping = cache.get("by_task_id") if isinstance(cache.get("by_task_id"), dict) else {}
    mapping[task_id] = item
    cache["by_task_id"] = mapping
    save_novel_selection_cache(cache)


def cached_novel_locator(task_id: str) -> dict:
    cache = load_novel_selection_cache()
    mapping = cache.get("by_task_id") if isinstance(cache.get("by_task_id"), dict) else {}
    item = mapping.get(str(task_id or "").strip()) if mapping else None
    return item if isinstance(item, dict) else {}


def load_account_pools():
    """读取本地账号池配置。"""
    payload = load_json_file(ACCOUNT_POOL_FILE)
    return payload if isinstance(payload, dict) else {}


_CURRENT_AGENT_ID = ""


def resolve_current_agent_id():
    """解析当前登录用户的 agent_id，优先使用本地授权缓存。"""
    global _CURRENT_AGENT_ID

    override = os.getenv("INBEIDOU_AGENT_ID", "").strip()
    if override:
        return override

    if _CURRENT_AGENT_ID:
        return _CURRENT_AGENT_ID

    payload = load_auth_state()
    agent_id = str(payload.get("agent_id") or "").strip()
    if agent_id:
        _CURRENT_AGENT_ID = agent_id
        return agent_id

    body = require_success(get_user_info(), "获取用户信息")
    agent_id = str(body.get("agent_id") or "").strip()
    if not agent_id:
        raise InbeidouError("无法解析当前 agent_id，请重新授权后再试")
    _CURRENT_AGENT_ID = agent_id
    return agent_id


def auth_headers(auth_style="raw"):
    """按站点生成鉴权头。"""
    token = load_auth_token()
    if not token:
        raise InbeidouError(f"缺少 TOKEN，请设置 INBEIDOU_TOKEN 或完成 {AUTH_STATE_FILE} 授权")
    if auth_style == "bearer":
        token = f"Bearer {token}"
    return {"Authorization": token}


def api_request(
    base_url,
    path,
    method="GET",
    params=None,
    json_data=None,
    data=None,
    files=None,
    extra_headers=None,
    auth_style="raw",
    timeout=DEFAULT_TIMEOUT,
):
    """统一 HTTP 请求。"""
    url = f"{base_url}{path}"
    headers = auth_headers(auth_style=auth_style)
    if json_data is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)

    try:
        response = requests.request(
            method=method,
            url=url,
            params=params,
            json=json_data,
            data=data,
            files=files,
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise InbeidouError(f"请求失败: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise InbeidouError(
            f"接口返回非 JSON: HTTP {response.status_code}, body={response.text[:300]}"
        ) from exc

    if response.status_code >= 400:
        raise InbeidouError(
            f"接口请求失败: HTTP {response.status_code}, code={payload.get('code')}, msg={payload.get('msg')}"
        )
    return payload


def vidu_request(path, method="GET", params=None, json_data=None, timeout=DEFAULT_TIMEOUT):
    """统一官方 Vidu HTTP 请求。"""
    api_key = load_vidu_api_key()
    if not api_key:
        raise InbeidouError(
            "缺少 Vidu API key，请设置 BARRY_VIDEO_VIDU_API_KEY / VIDU_API_KEY，"
            f"或写入 {VIDU_AUTH_FILE}"
        )
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{VIDU_API_BASE.rstrip('/')}{path}"
    max_retries = max(
        0,
        min(
            8,
            int(os.getenv("BARRY_VIDEO_VIDU_REQUEST_RETRIES", DEFAULT_VIDU_REQUEST_RETRIES) or DEFAULT_VIDU_REQUEST_RETRIES),
        ),
    )
    last_exception = None
    for attempt in range(1, max_retries + 2):
        try:
            response = requests.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_exception = exc
            message = str(exc).lower()
            retryable = any(
                token in message
                for token in [
                    "read timed out",
                    "connect timeout",
                    "connection aborted",
                    "connection reset",
                    "temporarily unavailable",
                    "proxyerror",
                ]
            )
            if retryable and attempt <= max_retries:
                time.sleep(min(8, attempt * 2))
                continue
            raise InbeidouError(f"Vidu 请求失败: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            if response.status_code >= 500 and attempt <= max_retries:
                time.sleep(min(8, attempt * 2))
                continue
            raise InbeidouError(
                f"Vidu 返回非 JSON: HTTP {response.status_code}, body={response.text[:300]}"
            ) from exc

        if response.status_code >= 400:
            error_message = payload.get("message") or payload.get("msg") or payload.get("error") or payload
            retryable = response.status_code in {429, 500, 502, 503, 504}
            if retryable and attempt <= max_retries:
                time.sleep(min(8, attempt * 2))
                continue
            raise InbeidouError(f"Vidu 接口失败: HTTP {response.status_code}, msg={error_message}")
        return payload

    if last_exception is not None:
        raise InbeidouError(f"Vidu 请求失败: {last_exception}") from last_exception
    raise InbeidouError("Vidu 请求失败: 未知错误")


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _remote_suffix(url, fallback=".bin"):
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return fallback
    suffix = Path(parsed.path).suffix.lower()
    return suffix or fallback


_NOVEL_OUTPUT_CONTEXT = local()


def _safe_output_name(value: str, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").strip()).strip("_")
    return cleaned[:64] or fallback


def _begin_novel_output_round(title: str) -> tuple[str, str, str]:
    run_date = datetime.now().strftime("%Y-%m-%d")
    run_id = f"round_{datetime.now().strftime('%H%M%S')}_{int(time.time() * 1000) % 100000:05d}"
    novel_dir = _safe_output_name(title, "novel")
    _set_novel_output_run(run_date=run_date, novel_dir=novel_dir, run_id=run_id)
    return run_date, novel_dir, run_id


def _set_novel_output_run(*, run_date: str, novel_dir: str, run_id: str) -> tuple[str, str, str]:
    _NOVEL_OUTPUT_CONTEXT.run_date = str(run_date or "").strip()
    _NOVEL_OUTPUT_CONTEXT.novel_dir = _safe_output_name(novel_dir, "novel")
    _NOVEL_OUTPUT_CONTEXT.run_id = str(run_id or "").strip()
    return _NOVEL_OUTPUT_CONTEXT.run_date, _NOVEL_OUTPUT_CONTEXT.novel_dir, _NOVEL_OUTPUT_CONTEXT.run_id


def _ensure_novel_output_run() -> tuple[str, str, str]:
    run_date = getattr(_NOVEL_OUTPUT_CONTEXT, "run_date", "")
    run_id = getattr(_NOVEL_OUTPUT_CONTEXT, "run_id", "")
    novel_dir = getattr(_NOVEL_OUTPUT_CONTEXT, "novel_dir", "")
    if not run_date:
        run_date = datetime.now().strftime("%Y-%m-%d")
        _NOVEL_OUTPUT_CONTEXT.run_date = run_date
    if not run_id:
        run_id = f"round_{datetime.now().strftime('%H%M%S')}_{int(time.time() * 1000) % 100000:05d}"
        _NOVEL_OUTPUT_CONTEXT.run_id = run_id
    if not novel_dir:
        novel_dir = "novel"
        _NOVEL_OUTPUT_CONTEXT.novel_dir = novel_dir
    return run_date, novel_dir, run_id


def _novel_output_root() -> Path:
    if not _novel_persist_outputs_enabled():
        return _novel_work_root()
    downloads_dir = DEFAULT_NOVEL_DOWNLOAD_DIR
    try:
        downloads_dir.mkdir(parents=True, exist_ok=True)
        return downloads_dir
    except OSError:
        temp_dir = DEFAULT_NOVEL_TMP_DIR
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir


def _novel_work_root() -> Path:
    temp_dir = DEFAULT_NOVEL_WORK_DIR
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _novel_persist_outputs_enabled() -> bool:
    override = str(os.getenv("BARRY_VIDEO_NOVEL_PERSIST_OUTPUTS", "") or "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    return True


def _novel_output_dir(category: str) -> Path:
    run_date, novel_dir, run_id = _ensure_novel_output_run()
    target_dir = _novel_output_root() / run_date / novel_dir / _safe_output_name(category, "misc")
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def _novel_work_dir(category: str) -> Path:
    run_date, novel_dir, run_id = _ensure_novel_output_run()
    target_dir = _novel_work_root() / run_date / novel_dir / run_id / _safe_output_name(category, "misc")
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def _novel_cleanup_after_publish_enabled() -> bool:
    value = str(os.getenv("BARRY_NOVEL_DELETE_LOCAL_OUTPUT_AFTER_PUBLISH", "") or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return not _novel_persist_outputs_enabled()


def _cleanup_novel_generated_files(video_result: dict) -> dict[str, object]:
    data = video_result.get("data") if isinstance(video_result.get("data"), dict) else {}
    cleanup_paths: list[str] = []
    for key in ("local_video_file", "local_cover_file"):
        value = str(data.get(key) or "").strip()
        if value:
            cleanup_paths.append(value)
    for segment in data.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        for key in ("local_video_file", "local_source_video_file"):
            value = str(segment.get(key) or "").strip()
            if value:
                cleanup_paths.append(value)
        image_generation = segment.get("image_generation") if isinstance(segment.get("image_generation"), dict) else {}
        image_file = str(image_generation.get("local_image_file") or "").strip()
        if image_file:
            cleanup_paths.append(image_file)
    deleted_paths: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    for raw_path in cleanup_paths:
        path = str(raw_path or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            target = Path(path).expanduser().resolve()
            allowed, reason = _validate_cleanup_target(target)
            if not allowed:
                errors.append(f"{path}: {reason}")
                continue
            if target.exists():
                target.unlink()
                deleted_paths.append(str(target))
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    cleanup_dirs: list[Path] = []
    output_root = str(data.get("output_root_dir") or "").strip()
    output_run_date = str(data.get("output_run_date") or "").strip()
    output_novel_dir = str(data.get("output_novel_dir") or "").strip()
    if output_root and output_run_date and output_novel_dir:
        cleanup_dirs.append(Path(output_root).expanduser() / output_run_date / output_novel_dir)
        cleanup_dirs.append(Path(output_root).expanduser() / output_run_date)
    for directory in cleanup_dirs:
        try:
            allowed, _reason = _validate_cleanup_target(directory)
            if not allowed:
                continue
            if directory.exists() and directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            pass
    return {
        "enabled": True,
        "deleted_paths": deleted_paths,
        "deleted_count": len(deleted_paths),
        "errors": errors,
    }


def _maybe_cleanup_novel_outputs_after_publish(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return payload
    if not _novel_cleanup_after_publish_enabled():
        return payload
    if str(payload.get("publish_status") or "") != "published":
        return payload
    existing_cleanup = payload.get("cleanup") if isinstance(payload.get("cleanup"), dict) else {}
    if existing_cleanup.get("enabled"):
        return payload
    video = payload.get("video") if isinstance(payload.get("video"), dict) else {}
    if not video:
        return payload
    payload["cleanup"] = _cleanup_novel_generated_files(video)
    return payload


def _download_remote_file(
    url: str,
    *,
    stem: str,
    suffix: str,
    timeout: int = 120,
    category: str = "assets",
    use_work_dir: bool = False,
) -> str:
    remote_url = str(url or "").strip()
    if not remote_url:
        raise InbeidouError("远程文件 URL 为空，无法下载")
    temp_dir = _novel_work_dir(category) if use_work_dir else _novel_output_dir(category)
    safe_stem = "".join(ch if ch.isalnum() else "_" for ch in (stem or "novel_asset"))[:64].strip("_") or "novel_asset"
    target = temp_dir / f"{safe_stem}{suffix}"
    try:
        with requests.get(remote_url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with open(target, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
    except Exception as exc:
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
        raise InbeidouError(f"下载远程文件失败: {exc}") from exc
    if not target.exists() or target.stat().st_size <= 0:
        raise InbeidouError(f"下载远程文件失败: {remote_url}")
    return str(target)


def _file_to_data_url(file_path: str) -> str:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise InbeidouError(f"文件不存在: {path}")
    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type:
        mime_type = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _split_novel_sentences(text: str) -> list[str]:
    compact = " ".join(str(text or "").split())
    if not compact:
        return []
    pieces = re.split(r"(?<=[.!?。！？])\s+", compact)
    return [piece.strip() for piece in pieces if piece and piece.strip()]


def _segment_novel_text(text: str, *, segment_count: int) -> list[str]:
    compact = " ".join(str(text or "").split())
    if not compact:
        raise InbeidouError("小说章节内容为空，无法分段生成视频")
    sentences = _split_novel_sentences(compact)
    target_count = max(1, int(segment_count or 1))
    segments: list[str] = []
    if len(sentences) >= target_count:
        base = len(sentences) // target_count
        extra = len(sentences) % target_count
        cursor = 0
        for index in range(target_count):
            take = base + (1 if index < extra else 0)
            block = " ".join(sentences[cursor : cursor + take]).strip()
            cursor += take
            if block:
                segments.append(_sanitize_prompt_excerpt(block, limit=1200))
    else:
        chunk_size = max(180, math.ceil(len(compact) / target_count))
        for start in range(0, len(compact), chunk_size):
            block = compact[start : start + chunk_size].strip()
            if block:
                segments.append(_sanitize_prompt_excerpt(block, limit=1200))
        while len(segments) < target_count and segments:
            segments.append(segments[-1])
    return segments[:target_count]


def _sanitize_novel_segment_text(text: str, *, stronger: bool = False, limit: int = 1200) -> dict:
    original = _sanitize_prompt_excerpt(text, limit=limit)
    if not original:
        return {"text": "", "original": "", "changed": False, "dropped_labels": [], "replacements_applied": []}
    dropped_labels = set()
    sentences = _split_novel_sentences(original) or [original]
    kept_sentences = []
    for sentence in sentences:
        matched_labels = [label for label, pattern in NOVEL_AUDIT_DROP_PATTERNS if re.search(pattern, sentence)]
        if matched_labels and stronger:
            dropped_labels.update(matched_labels)
            continue
        if matched_labels:
            dropped_labels.update(matched_labels)
        kept_sentences.append(sentence)
    working = " ".join(kept_sentences).strip()
    if not working and not stronger:
        working = original
    replacements_applied = []
    for pattern, replacement in NOVEL_AUDIT_SOFTEN_REPLACEMENTS:
        updated = re.sub(pattern, replacement, working)
        if updated != working:
            replacements_applied.append(replacement)
            working = updated
    working = re.sub(r"\s+", " ", working).strip()
    if stronger:
        working = re.sub(r"[\"'`“”‘’]{2,}", "\"", working).strip()
    working = _sanitize_prompt_excerpt(working or (original if not stronger else ""), limit=limit)
    return {
        "text": working,
        "original": original,
        "changed": working != original,
        "dropped_labels": sorted(dropped_labels),
        "replacements_applied": replacements_applied,
    }


def _novel_safe_fallback_prompt(title: str, segment_index: int, prompt_info: dict, *, limit: int = 400) -> str:
    safe_title = re.sub(r"[_]+", " ", str(title or "").strip())
    safe_title = re.sub(r"(?i)\b(mistress|mafia|fake heir|revenge|regret|barren wife)\b", "", safe_title).strip(" -_")
    pieces = []
    if safe_title:
        pieces.append(f"A cinematic emotional scene inspired by the novel {safe_title}.")
    else:
        pieces.append("A cinematic emotional scene inspired by an adult relationship novel.")
    if prompt_info.get("dropped_labels"):
        pieces.append("Focus on facial expressions, elegant clothing, indoor or city settings, and dramatic atmosphere.")
    if prompt_info.get("replacements_applied"):
        pieces.append("Keep the scene tense and emotional, but avoid explicit, graphic, or violent details.")
    pieces.append("Show adult characters, natural poses, rich lighting, clean composition, and safe storytelling.")
    return _sanitize_prompt_excerpt(" ".join(pieces), limit=limit)


def _build_novel_visual_prompt(title: str, segment_index: int, segment_text: str, *, stronger: bool = False, limit: int = 900) -> tuple[str, dict]:
    stripped = re.sub(r"[\"“”][^\"“”]{1,260}[\"“”]", " ", str(segment_text or ""))
    stripped = re.sub(
        r"(?i)\b(said|replied|asked|whispered|shouted|called|demanded|murmured|cried)\b[^.!?]{0,120}",
        " emotional exchange ",
        stripped,
    )
    stripped = re.sub(r"\s+", " ", stripped).strip()
    prompt_info = _sanitize_novel_segment_text(stripped, stronger=True, limit=min(limit, 700))
    visual_excerpt = prompt_info["text"] or ""
    safe_title = re.sub(r"[_]+", " ", str(title or "").strip())
    safe_title = re.sub(r"(?i)\b(mistress|mafia|fake heir|revenge|regret|barren wife|pregnant)\b", "", safe_title).strip(" -_")
    pieces = [
        "A cinematic still frame from an adult relationship drama.",
        "Realistic style, expressive faces, elegant wardrobe, modern indoor or city setting, dramatic but safe atmosphere.",
        "Adult characters only, no explicit intimacy, no pregnancy focus, no medical scene, no violence, no minors.",
    ]
    if safe_title:
        pieces.append(f"Inspired by the novel {safe_title}.")
    if visual_excerpt:
        pieces.append(f"Scene inspiration: {visual_excerpt}")
    if prompt_info.get("dropped_labels"):
        pieces.append("Keep the moment emotionally tense but visually restrained and platform-safe.")
    if stronger:
        pieces.append("Use restrained body language, clean composition, medium shot framing, and safe storytelling only.")
    prompt = _sanitize_prompt_excerpt(" ".join(pieces), limit=limit)
    if not prompt:
        prompt = _novel_safe_fallback_prompt(title, segment_index, prompt_info, limit=limit)
    return prompt, prompt_info


def _poll_vidu_task_creations(task_id: str, *, timeout: int, poll_interval: int) -> dict:
    deadline = time.time() + timeout
    last_body = {}
    while time.time() < deadline:
        last_body = vidu_request(f"/tasks/{task_id}/creations", method="GET", timeout=DEFAULT_TIMEOUT)
        state = str(last_body.get("state") or "").strip().lower()
        if state in {"success", "failed"}:
            return last_body
        time.sleep(max(1, poll_interval))
    raise InbeidouError(f"等待 Vidu 任务超时: task_id={task_id}")


def _first_vidu_creation(body: dict) -> dict:
    creations = body.get("creations") if isinstance(body.get("creations"), list) else []
    return creations[0] if creations else {}


def _submit_vidu_reference2image_segment(
    *,
    title: str,
    segment_index: int,
    segment_text: str,
    generation_chain: str,
    aspect_ratio: str,
    timeout: int,
    poll_interval: int,
    debug_context: dict,
) -> dict:
    attempts = [
        _build_novel_visual_prompt(title, segment_index, segment_text, stronger=False, limit=900),
        _build_novel_visual_prompt(title, segment_index, segment_text, stronger=True, limit=700),
    ]
    last_error = None
    last_body = {}
    body = {}
    task_id = ""
    prompt = ""
    prompt_info = {}
    for attempt_index, (attempt_prompt, attempt_prompt_info) in enumerate(attempts, start=1):
        prompt = attempt_prompt
        prompt_info = attempt_prompt_info
        request_payload = {
            "model": DEFAULT_NOVEL_IMAGE_MODEL,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
        }
        try:
            body = vidu_request("/reference2image", method="POST", json_data=request_payload, timeout=DEFAULT_TIMEOUT)
        except Exception as exc:
            last_error = exc
            if attempt_index >= len(attempts):
                debug_file = _write_novel_debug_manifest(
                    f"{title}_seg_{segment_index}_image_submit_failed",
                    {
                        "title": title,
                        "segment_index": segment_index,
                        "generation_chain": generation_chain,
                        "provider": "vidu",
                        "generation_mode": "reference2image",
                        "model": DEFAULT_NOVEL_IMAGE_MODEL,
                        "aspect_ratio": aspect_ratio,
                        "prompt_info": prompt_info,
                        "debug_context": debug_context,
                        "error": str(exc),
                        "attempt": attempt_index,
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    },
                )
                raise InbeidouError(f"Vidu 小说分镜图提交失败: {exc}；调试文件: {debug_file}") from exc
            continue
        task_id = str(body.get("task_id") or "").strip()
        if not task_id:
            raise InbeidouError(f"Vidu 创建分镜图任务未返回 task_id: {json.dumps(body, ensure_ascii=False)}")
        last_body = _poll_vidu_task_creations(task_id, timeout=timeout, poll_interval=poll_interval)
        state = str(last_body.get("state") or "").strip().lower()
        if state == "success":
            break
        err_code = str(last_body.get("err_code") or "").strip()
        last_error = InbeidouError(err_code or state or "reference2image failed")
        if attempt_index < len(attempts) and err_code in VIDU_AUDIT_ERROR_CODES:
            continue
        debug_file = _write_novel_debug_manifest(
            f"{title}_seg_{segment_index}_image_failed",
            {
                "title": title,
                "segment_index": segment_index,
                "generation_chain": generation_chain,
                "provider": "vidu",
                "generation_mode": "reference2image",
                "model": DEFAULT_NOVEL_IMAGE_MODEL,
                "task_id": task_id,
                "aspect_ratio": aspect_ratio,
                "prompt_info": prompt_info,
                "debug_context": debug_context,
                "vidu_response": body,
                "creations_response": last_body,
                "attempt": attempt_index,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        raise InbeidouError(
            f"Vidu 小说分镜图生成失败: {last_body.get('err_code') or last_body.get('state') or last_body}；调试文件: {debug_file}"
        )
    else:
        raise InbeidouError(f"Vidu 小说分镜图生成失败: {last_error}")

    first = _first_vidu_creation(last_body)
    image_url = str(first.get("url") or "").strip()
    local_image_file = _download_remote_file(
        image_url,
        stem=f"{title}_seg_{segment_index}_image",
        suffix=_remote_suffix(image_url, fallback=".png"),
        timeout=120,
        category="图片",
        use_work_dir=True,
    )
    return {
        "segment_index": segment_index,
        "provider": "vidu",
        "generation_mode": "reference2image",
        "model": DEFAULT_NOVEL_IMAGE_MODEL,
        "task_id": task_id,
        "image_url": image_url,
        "local_image_file": local_image_file,
        "prompt": prompt,
        "video_prompt": prompt,
        "prompt_info": prompt_info,
        "state": state,
    }


def _submit_vidu_img2video_segment(
    *,
    title: str,
    segment_index: int,
    segment_text: str,
    image_result: dict,
    generation_chain: str,
    model: str,
    duration: int,
    aspect_ratio: str,
    resolution: str,
    off_peak: bool,
    watermark: bool,
    timeout: int,
    poll_interval: int,
    debug_context: dict,
) -> dict:
    prompt_info = image_result.get("prompt_info") if isinstance(image_result.get("prompt_info"), dict) else _sanitize_novel_segment_text(segment_text, stronger=True, limit=1200)
    prompt = str(image_result.get("video_prompt") or "").strip() or _build_novel_visual_prompt(title, segment_index, segment_text, stronger=True, limit=900)[0]
    local_image_file = str(image_result.get("local_image_file") or "").strip()
    if not local_image_file:
        raise InbeidouError(f"《{title}》第 {segment_index} 段缺少分镜图，无法生成视频")
    resolved_model = str(model or "").strip() or DEFAULT_NOVEL_VIDEO_MODEL
    if resolved_model not in NOVEL_VIDU_VIDEO_MODELS:
        raise InbeidouError(
            f"小说图生视频模型仅支持 {', '.join(NOVEL_VIDU_VIDEO_MODELS)}，当前收到: {resolved_model}"
        )
    image_data_url = _file_to_data_url(local_image_file)
    request_payload = {
        "model": resolved_model,
        "images": [image_data_url],
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "audio": True,
        "off_peak": bool(off_peak),
        "watermark": bool(watermark),
    }
    try:
        body = vidu_request("/img2video", method="POST", json_data=request_payload, timeout=DEFAULT_TIMEOUT)
    except Exception as exc:
        debug_file = _write_novel_debug_manifest(
            f"{title}_seg_{segment_index}_video_submit_failed",
            {
                "title": title,
                "segment_index": segment_index,
                "generation_chain": generation_chain,
                "provider": "vidu",
                "generation_mode": "img2video",
                "requested_model": model,
                "duration": duration,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "prompt_info": prompt_info,
                "image_result": image_result,
                "debug_context": debug_context,
                "error": str(exc),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        raise InbeidouError(f"Vidu 小说分段视频提交失败: {exc}；调试文件: {debug_file}") from exc
    task_id = str(body.get("task_id") or "").strip()
    if not task_id:
        raise InbeidouError(f"Vidu 创建分段视频任务未返回 task_id: {json.dumps(body, ensure_ascii=False)}")
    last_body = _poll_vidu_task_creations(task_id, timeout=timeout, poll_interval=poll_interval)
    state = str(last_body.get("state") or "").strip().lower()
    if state != "success":
        debug_file = _write_novel_debug_manifest(
            f"{title}_seg_{segment_index}_video_failed",
            {
                "title": title,
                "segment_index": segment_index,
                "generation_chain": generation_chain,
                "provider": "vidu",
                "generation_mode": "img2video",
                "requested_model": model,
                "task_id": task_id,
                "duration": duration,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "prompt_info": prompt_info,
                "image_result": image_result,
                "debug_context": debug_context,
                "vidu_response": body,
                "creations_response": last_body,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        raise InbeidouError(
            f"Vidu 小说分段视频生成失败: {last_body.get('err_code') or last_body.get('state') or last_body}；调试文件: {debug_file}"
        )
    first = _first_vidu_creation(last_body)
    video_url = str(first.get("url") or "").strip()
    local_video_file = _download_novel_publish_video(
        video_url,
        f"{title}_seg_{segment_index}",
        task_id=task_id,
        category="分段",
    )
    normalized_video_file = _normalize_novel_video_segment(
        local_video_file,
        title=title,
        segment_index=segment_index,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
    )
    return {
        "segment_index": segment_index,
        "generation_chain": generation_chain,
        "provider": "vidu",
        "model": resolved_model,
        "requested_model": model,
        "duration": duration,
        "prompt": prompt,
        "prompt_info": prompt_info,
        "task_id": task_id,
        "video_url": video_url,
        "cover_url": "",
        "local_video_file": normalized_video_file,
        "local_source_video_file": local_video_file,
        "credits": body.get("credits"),
        "state": state,
        "image_generation": image_result,
    }

def _write_novel_debug_manifest(name: str, payload: dict) -> str:
    target_dir = _novel_work_dir("清单")
    safe_name = _safe_output_name(name, "novel_debug")
    target = target_dir / f"{safe_name}_{int(time.time() * 1000)}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def _novel_target_dimensions(aspect_ratio: str, resolution: str) -> tuple[int, int]:
    ratio = str(aspect_ratio or "9:16").strip()
    res = str(resolution or "720p").strip().lower()
    if ratio == "9:16":
        return {"540p": (540, 960), "720p": (720, 1280), "1080p": (1080, 1920)}.get(res, (720, 1280))
    if ratio == "16:9":
        return {"540p": (960, 540), "720p": (1280, 720), "1080p": (1920, 1080)}.get(res, (1280, 720))
    if ratio == "3:4":
        return {"540p": (540, 720), "720p": (720, 960), "1080p": (1080, 1440)}.get(res, (720, 960))
    if ratio == "4:3":
        return {"540p": (720, 540), "720p": (960, 720), "1080p": (1440, 1080)}.get(res, (960, 720))
    return {"540p": (540, 540), "720p": (720, 720), "1080p": (1080, 1080)}.get(res, (720, 720))


def _normalize_novel_video_segment(file_path: str, *, title: str, segment_index: int, aspect_ratio: str, resolution: str) -> str:
    source = Path(file_path).expanduser().resolve()
    if not source.exists():
        raise InbeidouError(f"分段视频不存在: {source}")
    width, height = _novel_target_dimensions(aspect_ratio, resolution)
    safe_title = "".join(ch if ch.isalnum() else "_" for ch in (title or "novel_segment"))[:48].strip("_") or "novel_segment"
    target_dir = _novel_output_dir("分段")
    output_file = target_dir / f"{safe_title}_seg_{segment_index}.mp4"
    try:
        probe = probe_video(str(source))
    except Exception:
        probe = {}
    if int(probe.get("width") or 0) == width and int(probe.get("height") or 0) == height:
        try:
            command = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,codec_name,r_frame_rate,pix_fmt,sample_rate",
                "-of",
                "json",
                str(source),
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            payload = json.loads(result.stdout)
            streams = payload.get("streams", [])
            video_stream = next((item for item in streams if item.get("codec_type") == "video"), {})
            audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), {})
            fps = str(video_stream.get("r_frame_rate") or "").strip()
            codec_name = str(video_stream.get("codec_name") or "").strip().lower()
            pix_fmt = str(video_stream.get("pix_fmt") or "").strip().lower()
            audio_codec = str(audio_stream.get("codec_name") or "").strip().lower()
            audio_sample_rate = str(audio_stream.get("sample_rate") or "").strip()
            if (
                fps in {"24/1", "24"}
                and codec_name == "h264"
                and pix_fmt in {"yuv420p", "yuvj420p"}
                and (not audio_stream or (audio_codec == "aac" and audio_sample_rate == "48000"))
            ):
                shutil.copy2(source, output_file)
                return str(output_file)
        except Exception:
            pass
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,fps=24,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(output_file),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise InbeidouError("系统未安装 ffmpeg，无法统一小说分段尺寸") from exc
    except subprocess.CalledProcessError as exc:
        raise InbeidouError(f"ffmpeg 统一小说分段尺寸失败: {exc.stderr.strip()}") from exc
    if not output_file.exists() or output_file.stat().st_size <= 0:
        raise InbeidouError("统一后的小说分段文件为空")
    return str(output_file)


def _concat_novel_video_segments(video_files: list[str], *, title: str) -> str:
    valid_files = [str(Path(file_path).expanduser().resolve()) for file_path in (video_files or []) if str(file_path).strip()]
    if not valid_files:
        raise InbeidouError("缺少可拼接的小说视频分段")
    if len(valid_files) == 1:
        source = Path(valid_files[0]).expanduser().resolve()
        temp_dir = _novel_output_dir("成片")
        safe_title = "".join(ch if ch.isalnum() else "_" for ch in (title or "novel_story"))[:48].strip("_") or "novel_story"
        output_file = temp_dir / f"{safe_title}.mp4"
        shutil.copy2(source, output_file)
        return str(output_file)
    temp_dir = _novel_output_dir("成片")
    safe_title = "".join(ch if ch.isalnum() else "_" for ch in (title or "novel_story"))[:48].strip("_") or "novel_story"
    list_file = _novel_work_dir("清单") / f"{safe_title}_segments.txt"
    output_file = temp_dir / f"{safe_title}.mp4"
    lines = []
    for file_path in valid_files:
        escaped = file_path.replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_file.write_text("\n".join(lines), encoding="utf-8")
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_file),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise InbeidouError("系统未安装 ffmpeg，无法拼接小说分段视频") from exc
    except subprocess.CalledProcessError as exc:
        raise InbeidouError(f"ffmpeg 拼接小说分段视频失败: {exc.stderr.strip()}") from exc
    if not output_file.exists() or output_file.stat().st_size <= 0:
        raise InbeidouError("ffmpeg 拼接后的小说成片为空")
    return str(output_file)


def _extend_novel_video_to_duration(file_path: str, *, title: str, target_duration: int = 180) -> tuple[str, dict]:
    """Loop the light Vidu source locally to a publish-ready 180s vertical MP4."""
    source = Path(file_path).expanduser().resolve()
    if not source.exists() or source.stat().st_size <= 0:
        raise InbeidouError("小说成片源文件为空，无法拉长到 180 秒")
    target_seconds = max(30, min(NOVEL_MAX_TOTAL_DURATION, int(target_duration or 180)))
    try:
        source_probe = probe_video(str(source))
    except Exception:
        source_probe = {}
    source_duration = int(source_probe.get("file_duration") or 0)
    temp_dir = _novel_output_dir("成片")
    safe_title = "".join(ch if ch.isalnum() else "_" for ch in (title or "novel_story"))[:48].strip("_") or "novel_story"
    output_file = temp_dir / f"{safe_title}_180s.mp4"
    command = [
        "ffmpeg",
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(source),
        "-t",
        str(target_seconds),
        "-vf",
        "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,fps=24,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(output_file),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise InbeidouError("系统未安装 ffmpeg，无法生成 180 秒小说成片") from exc
    except subprocess.CalledProcessError as exc:
        raise InbeidouError(f"ffmpeg 生成 180 秒小说成片失败: {exc.stderr.strip()}") from exc
    if not output_file.exists() or output_file.stat().st_size <= 0:
        raise InbeidouError("180 秒小说成片为空")
    final_probe = probe_video(str(output_file))
    return str(output_file), {
        "source_file": str(source),
        "source_duration": source_duration,
        "target_duration": target_seconds,
        "final_duration": final_probe.get("file_duration"),
        "final_width": final_probe.get("screen_x"),
        "final_height": final_probe.get("screen_y"),
        "method": "local_loop_to_180s",
    }


def require_success(result, action):
    """校验接口返回 code=0。"""
    if result.get("code") != 0:
        raise InbeidouError(f"{action}失败: {result.get('msg')}")
    return result.get("body")


def require_body_dict(body, action):
    """接口 code=0 但 body 为空时，统一转成业务错误。"""
    if not isinstance(body, dict):
        raise InbeidouError(f"{action}失败: 返回体为空")
    return body


def pretty_print_json(data):
    """输出 JSON。"""
    print(json.dumps(data, ensure_ascii=False, indent=2))


def format_size(size):
    """格式化文件大小。"""
    size = int(size or 0)
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}MB"
    return f"{size / 1024 / 1024 / 1024:.2f}GB"


def format_seconds(seconds):
    """秒数转 mm:ss / hh:mm:ss。"""
    seconds = int(round(float(seconds or 0)))
    hour, rem = divmod(seconds, 3600)
    minute, second = divmod(rem, 60)
    if hour:
        return f"{hour:02d}:{minute:02d}:{second:02d}"
    return f"{minute:02d}:{second:02d}"


def format_drama(item):
    """格式化短剧信息。"""
    is_hot = "🔥" if item.get("tag") == "hot" or item.get("hot_content") else ""
    is_new = "🆕" if "最新" in str(item.get("hot_content", "")) else ""
    platform_name = PLATFORMS.get(str(item.get("app_id", "")), f"平台{item.get('app_id', '')}")
    lang = "英文" if str(item.get("language")) == "2" else f"语言{item.get('language', '')}"

    print(f"\n{'=' * 60}")
    print(f"📺 {item.get('title', '未知标题')}")
    print(f"{'=' * 60}")
    print(f"   英文名: {item.get('third_serial_id', 'N/A')}")
    print(f"   平台: {platform_name} {is_hot}{is_new}")
    print(f"   语言: {lang}")
    print(f"   集数: {item.get('episode_count', 0)} 集")
    print(f"   推广人数: {item.get('promoter_number', 0)} 人")
    print(f"   分佣比例: {item.get('share_rate', 0)}%")
    print(f"   发布时间: {item.get('publish_at', 'N/A')}")
    print(f"   任务ID: {item.get('task_id', 'N/A')}")


def format_novel(item):
    """格式化小说信息。"""
    platform_name = NOVEL_PLATFORMS.get(
        str(item.get("app_id", "")),
        PLATFORMS.get(str(item.get("app_id", "")), f"平台{item.get('app_id', '')}"),
    )
    lang = "英文" if str(item.get("language")) == "2" else f"语言{item.get('language', '')}"

    print(f"\n{'=' * 60}")
    print(f"📖 {item.get('title', '未知标题')}")
    print(f"{'=' * 60}")
    print(f"   平台: {platform_name}")
    print(f"   语言: {lang}")
    print(f"   分佣比例: {item.get('share_rate', 0)}%")
    print(f"   发布时间: {item.get('publish_at', 'N/A')}")
    print(f"   task_id: {item.get('task_id', 'N/A')}")
    print(f"   app_id: {item.get('app_id', 'N/A')}")


def task_summary(item):
    return {
        "title": item.get("title") or item.get("title_ch") or "",
        "task_id": item.get("task_id"),
        "serial_id": item.get("serial_id"),
        "app_id": item.get("app_id"),
        "task_type": item.get("task_type"),
        "language": item.get("language"),
        "share_rate": item.get("share_rate"),
        "publish_at": item.get("publish_at"),
        "cover": item.get("cover") or "",
        "description": item.get("description") or item.get("description_en") or "",
    }


def normalize_novel_platform_filter(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.upper() in PUBLISH_SOCIAL_TYPES:
        return ""
    return raw


def normalize_promotion_platform(value):
    raw = str(value).strip()
    if not raw:
        raise InbeidouError("推广平台不能为空")
    if raw.isdigit():
        platform_id = int(raw)
    else:
        platform_id = PROMOTION_PLATFORM_NAMES.get(raw.lower())
    if platform_id not in PROMOTION_PLATFORMS:
        choices = ", ".join(f"{platform_id}:{name}" for platform_id, name in PROMOTION_PLATFORMS.items())
        raise InbeidouError(f"不支持的推广平台: {value}，可选 {choices}")
    return platform_id


def normalize_promotion_platforms(values, include_all=False):
    if include_all or not values:
        return list(PROMOTION_PLATFORMS.keys())
    ordered = []
    seen = set()
    for value in values:
        platform_id = normalize_promotion_platform(value)
        if platform_id not in seen:
            seen.add(platform_id)
            ordered.append(platform_id)
    return ordered


def resolve_task_for_detail(args):
    task_id = getattr(args, "task_id", "")
    platform = getattr(args, "platform", "") or getattr(args, "drama_platform", "")
    language = getattr(args, "language", "") or getattr(args, "drama_language", "2")
    order = getattr(args, "order", "") or getattr(args, "drama_order", "publish_at")
    task_type = getattr(args, "task_type", "") or getattr(args, "drama_task_type", "1")
    search = getattr(args, "search", "")
    size = max(1, int(getattr(args, "size", None) or getattr(args, "search_size", 10) or 10))

    if task_id:
        body = require_success(
            get_task_info(task_id=task_id, app_id=platform, task_type=task_type),
            "获取短剧详情",
        )
        return body

    if not search:
        raise InbeidouError("detail 至少需要 --task-id 或 --search")

        body = require_success(
            get_tasks(
                page=1,
                page_size=size,
                platform=platform,
                language=language,
                search=search,
                order=order,
                task_type=task_type,
            ),
            "搜索短剧",
        )
    items = body.get("data", [])
    if not items:
        raise InbeidouError(f"未找到短剧: {search}")

    keyword = search.strip().lower()
    exact = next((item for item in items if str(item.get("title", "")).strip().lower() == keyword), None)
    return exact or items[0]


def list_novel_tasks(page=1, page_size=15, platform="", language="", search="", order="publish_at"):
    return get_tasks(
        page=page,
        page_size=page_size,
        platform=platform,
        language=language,
        search=search,
        order=order,
        task_type="2",
    )


def resolve_novel(args):
    excluded_task_ids = {
        str(task_id).strip()
        for task_id in (getattr(args, "exclude_task_ids", None) or [])
        if str(task_id).strip()
    }

    if getattr(args, "task_id", ""):
        app_id = getattr(args, "app_id", "") or normalize_novel_platform_filter(getattr(args, "platform", ""))
        if not app_id:
            cached = cached_novel_locator(str(args.task_id))
            app_id = str(cached.get("app_id") or "").strip()
        last_error = None
        body = None
        for candidate_app_id in [app_id, ""]:
            if body:
                break
            try:
                body = require_body_dict(
                    require_success(
                        get_task_info(task_id=args.task_id, app_id=candidate_app_id, task_type="2"),
                        "获取小说详情",
                    ),
                    "获取小说详情",
                )
            except Exception as exc:
                last_error = exc
        if body is None:
            cached = cached_novel_locator(str(args.task_id))
            cached_title = str(cached.get("title_ch") or cached.get("title") or "").strip()
            if cached_title:
                search_args = argparse.Namespace(
                    task_id="",
                    app_id=str(cached.get("app_id") or "").strip(),
                    platform=str(cached.get("app_id") or "").strip(),
                    language="",
                    search=cached_title,
                    page=1,
                    size=max(15, int(getattr(args, "size", 15) or 15)),
                    order=getattr(args, "order", "publish_at"),
                    exclude_task_ids=list(excluded_task_ids),
                )
                return resolve_novel(search_args)
            if last_error:
                raise last_error
            raise InbeidouError("获取小说详情失败")
        if excluded_task_ids and str(body.get("task_id") or "").strip() in excluded_task_ids:
            raise InbeidouError("指定小说已在当前批次中使用，请更换小说")
        remember_selected_novel(body)
        return body

    search = str(getattr(args, "search", "") or "").strip()
    if search:
        body = require_body_dict(
            require_success(
                list_novel_tasks(
                    page=1,
                    page_size=max(1, int(getattr(args, "size", 10) or 10), len(excluded_task_ids) + 1),
                    platform=normalize_novel_platform_filter(getattr(args, "platform", "")),
                    language=getattr(args, "language", ""),
                    search=search,
                    order=getattr(args, "order", "publish_at"),
                ),
                "搜索小说",
            ),
            "搜索小说",
        )
        items = [
            item
            for item in (body.get("data", []) or [])
            if str(item.get("task_id") or "").strip() not in excluded_task_ids
        ]
        if not items:
            raise InbeidouError(f"未找到小说: {search}")
        keyword = search.lower()
        exact = next((item for item in items if str(item.get("title", "")).strip().lower() == keyword), None)
        selected = exact or items[0]
        body = require_body_dict(
            require_success(
                get_task_info(task_id=selected.get("task_id"), app_id=selected.get("app_id"), task_type="2"),
                "获取小说详情",
            ),
            "获取小说详情",
        )
        remember_selected_novel(body)
        return body

    body = require_body_dict(
        require_success(
            list_novel_tasks(
                page=max(1, int(getattr(args, "page", 1) or 1)),
                page_size=max(1, int(getattr(args, "size", 15) or 15), len(excluded_task_ids) + 5),
                platform=normalize_novel_platform_filter(getattr(args, "platform", "")),
                language=getattr(args, "language", ""),
                search="",
                order=getattr(args, "order", "publish_at"),
            ),
            "获取小说库",
        ),
        "获取小说库",
    )
    items = [
        item
        for item in (body.get("data", []) or [])
        if str(item.get("task_id") or "").strip() not in excluded_task_ids
    ]
    if not items:
        raise InbeidouError("当前条件下没有可选小说")
    selected = random.choice(items)
    body = require_body_dict(
        require_success(
            get_task_info(task_id=selected.get("task_id"), app_id=selected.get("app_id"), task_type="2"),
            "获取小说详情",
        ),
        "获取小说详情",
    )
    remember_selected_novel(body)
    return body


def submit_vidu_novel_video_task(
    *,
    title,
    chapter,
    prompt,
    publish_platform="FACEBOOK",
    generation_chain=NOVEL_GENERATION_CHAIN_VIDU_IMAGE,
    model=DEFAULT_NOVEL_VIDEO_MODEL,
    duration=5,
    aspect_ratio="9:16",
    resolution="720p",
    off_peak=False,
    watermark=False,
    timeout=DEFAULT_TASK_TIMEOUT,
    poll_interval=DEFAULT_POLL_INTERVAL,
):
    """通过官方 Vidu 生图 + 图生视频链路生成多段视频并拼接成完整成片。"""
    generation_chain = NOVEL_GENERATION_CHAIN_VIDU_IMAGE
    folder_title = (
        str((chapter.get("novel") or {}).get("title_ch") or "").strip()
        or str((chapter.get("novel") or {}).get("title") or "").strip()
        or str(title or "").strip()
        or "小说"
    )
    _begin_novel_output_round(folder_title)
    run_date, novel_dir, run_id = _ensure_novel_output_run()
    segment_count = random.randint(*NOVEL_SEGMENT_COUNT_RANGE)
    segments = _segment_novel_text(chapter.get("text") or prompt or "", segment_count=segment_count)
    concurrency = max(1, min(100, int(os.getenv("BARRY_VIDEO_NOVEL_VIDU_CONCURRENCY", DEFAULT_NOVEL_VIDU_CONCURRENCY) or DEFAULT_NOVEL_VIDU_CONCURRENCY)))
    segment_timeout = max(120, min(int(timeout or DEFAULT_TASK_TIMEOUT), DEFAULT_NOVEL_SEGMENT_TASK_TIMEOUT))
    requested_duration = int(duration or 0)
    if requested_duration > 0:
        segment_duration = requested_duration
        target_total_duration = min(NOVEL_MAX_TOTAL_DURATION, segment_count * segment_duration)
    else:
        target_total_duration = min(NOVEL_MAX_TOTAL_DURATION, random.randint(*NOVEL_TOTAL_DURATION_RANGE))
        segment_duration = random.randint(*NOVEL_SEGMENT_DURATION_RANGE)
    def _generate_one_segment(index, segment_text):
        _set_novel_output_run(run_date=run_date, novel_dir=novel_dir, run_id=run_id)
        selected_model = str(model or "").strip() or DEFAULT_NOVEL_VIDEO_MODEL
        debug_context = {
            "selected_generation_mode": "reference2image_img2video",
            "video_provider": "vidu",
            "output_round_id": run_id,
        }
        image_result = _submit_vidu_reference2image_segment(
            title=title,
            segment_index=index,
            segment_text=segment_text,
            generation_chain=NOVEL_GENERATION_CHAIN_VIDU_IMAGE,
            aspect_ratio=aspect_ratio,
            timeout=segment_timeout,
            poll_interval=poll_interval,
            debug_context=debug_context,
        )
        segment_result = _submit_vidu_img2video_segment(
            title=title,
            segment_index=index,
            segment_text=segment_text,
            image_result=image_result,
            generation_chain=NOVEL_GENERATION_CHAIN_VIDU_IMAGE,
            model=selected_model,
            duration=segment_duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            off_peak=off_peak,
            watermark=watermark,
            timeout=segment_timeout,
            poll_interval=poll_interval,
            debug_context=debug_context,
        )
        segment_result["generation_mode"] = "reference2image_img2video"
        return index, segment_result

    if concurrency == 1 or len(segments) <= 1:
        ordered_results = []
        for index, segment_text in enumerate(segments, start=1):
            _, segment_result = _generate_one_segment(index, segment_text)
            ordered_results.append((index, segment_result))
    else:
        ordered_results = []
        max_workers = min(concurrency, len(segments))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_generate_one_segment, index, segment_text): index
                for index, segment_text in enumerate(segments, start=1)
            }
            for future in as_completed(futures):
                ordered_results.append(future.result())
        ordered_results.sort(key=lambda item: item[0])

    segment_results: list[dict] = []
    local_segment_files: list[str] = []
    for _, segment_result in ordered_results:
        local_segment_files.append(segment_result["local_video_file"])
        segment_results.append(segment_result)

    stitched_local_video = _concat_novel_video_segments(local_segment_files, title=title)
    final_local_video, final_extension = _extend_novel_video_to_duration(
        stitched_local_video,
        title=title,
        target_duration=target_total_duration,
    )
    total_duration = sum(float(item.get("duration") or 0) for item in segment_results)
    last_segment = segment_results[-1] if segment_results else {}
    return {
        "generator": "vidu",
        "task_id": str(last_segment.get("task_id") or ""),
        "state": "success",
        "done": True,
        "data": {
            "video_url": str(last_segment.get("video_url") or ""),
            "cover_url": str(last_segment.get("cover_url") or ""),
            "watermarked_url": "",
            "task_id": str(last_segment.get("task_id") or ""),
            "credits": [item.get("credits") for item in segment_results],
            "state": "success",
            "local_video_file": final_local_video,
            "source_stitched_video_file": stitched_local_video,
            "local_cover_file": "",
            "cover_source_url": "",
            "output_root_dir": str(_novel_output_root()),
            "output_run_date": _ensure_novel_output_run()[0],
            "output_novel_dir": _ensure_novel_output_run()[1],
            "output_round_id": _ensure_novel_output_run()[2],
            "generation_chain": generation_chain,
            "segments": segment_results,
            "segment_count": len(segment_results),
            "total_duration": total_duration,
            "target_total_duration": target_total_duration,
            "final_duration": final_extension.get("final_duration"),
            "final_extension": final_extension,
            "segment_duration": segment_duration,
            "concurrency": concurrency,
            "segment_timeout": segment_timeout,
            "generation_modes": [item.get("generation_mode") for item in segment_results],
            "models": [item.get("model") for item in segment_results],
            "video_provider": "vidu",
        },
        "raw": segment_results,
        "content": prompt,
    }


def submit_novel_video_task(
    *,
    generator,
    title,
    novel_text,
    publish_platform,
    generation_chain=NOVEL_GENERATION_CHAIN_VIDU_IMAGE,
    app_id,
    task_id,
    prompt,
    chapter=None,
    timeout=DEFAULT_TASK_TIMEOUT,
    poll_interval=DEFAULT_POLL_INTERVAL,
    vidu_model=DEFAULT_NOVEL_VIDEO_MODEL,
    vidu_duration=DEFAULT_NOVEL_VIDU_DURATION,
    vidu_aspect_ratio="9:16",
    vidu_resolution=DEFAULT_NOVEL_VIDU_RESOLUTION,
    vidu_off_peak=False,
    vidu_watermark=False,
):
    """小说视频生成统一走官方 Vidu。"""
    if generator and generator != "vidu":
        raise InbeidouError("小说视频生成已统一切换到官方 Vidu，不再支持其他生成器")
    video_result = submit_vidu_novel_video_task(
        title=title,
        chapter=chapter or {},
        prompt=prompt,
        publish_platform=publish_platform,
        generation_chain=generation_chain,
        model=vidu_model,
        duration=vidu_duration,
        aspect_ratio=vidu_aspect_ratio,
        resolution=vidu_resolution,
        off_peak=vidu_off_peak,
        watermark=vidu_watermark,
        timeout=timeout,
        poll_interval=poll_interval,
    )
    data = video_result.get("data") if isinstance(video_result.get("data"), dict) else {}
    if isinstance(data, dict) and not str(data.get("local_video_file") or "").strip():
        cached_local_video = _download_novel_publish_video(
            str(data.get("video_url") or "").strip(),
            title,
            task_id=str(data.get("task_id") or video_result.get("task_id") or "").strip(),
            category="成片",
        )
        merged_data = dict(data)
        merged_data["local_video_file"] = cached_local_video
        merged_result = dict(video_result)
        merged_result["data"] = merged_data
        return merged_result
    return video_result


def resolve_drama_locator(args, require_app=False):
    if getattr(args, "task_id", None) or getattr(args, "search", None):
        item = resolve_task_for_detail(args)
        return {
            "task_id": item.get("task_id"),
            "task_type": item.get("task_type") or getattr(args, "drama_task_type", "1"),
            "title": item.get("title") or item.get("title_ch") or "",
            "serial_id": item.get("serial_id"),
            "app_id": item.get("app_id"),
            "episode_count": item.get("episode_count"),
            "target_count": item.get("target_count"),
        }

    serial_id = getattr(args, "serial_id", None)
    if not serial_id:
        raise InbeidouError("请传 --task-id、--search，或同时传 --serial-id/--app-id")

    locator = {
        "task_id": "",
        "task_type": getattr(args, "drama_task_type", "1"),
        "title": "",
        "serial_id": int(serial_id),
        "app_id": getattr(args, "app_id", None),
        "episode_count": None,
        "target_count": None,
    }
    if require_app and not locator["app_id"]:
        raise InbeidouError("使用 --serial-id 取剧集素材时还需要传 --app-id")
    return locator


def describe_episode_rows(rows):
    print(f"\n🎞️ 短剧剧集 (共 {len(rows)} 集)")
    print("=" * 108)
    print(f"{'集数':<8} {'episode_id':<12} {'时长':<10} {'play_url'}")
    print("-" * 108)
    for item in rows:
        duration = item.get("duration") or item.get("file_duration") or 0
        play_url = item.get("play_url") or item.get("mp4_OD") or ""
        print(
            f"{str(item.get('episode_order') or item.get('episode_id') or item.get('sequence') or ''):<8} "
            f"{str(item.get('id', '')):<12} "
            f"{format_seconds(duration):<10} "
            f"{play_url}"
        )


def poll_sketch_upload(serial_id, episode_order, app_id, timeout=300, poll_interval=DEFAULT_POLL_INTERVAL):
    deadline = time.time() + timeout
    last_rows = []
    while True:
        body = require_success(
            sketch_upload(serial_id=serial_id, episode_orders=[episode_order], app_id=app_id),
            "上传短剧集数素材",
        )
        rows = body if isinstance(body, list) else []
        last_rows = rows
        ready_rows = []
        for row in rows:
            status = str(row.get("status") or "").lower()
            if status in {"error", "failed"}:
                raise InbeidouError(f"短剧素材处理失败: {json.dumps(row, ensure_ascii=False)}")
            if row.get("id") and status in {"", "success", "done", "finished"}:
                ready_rows.append(row)
        if rows and len(ready_rows) == len(rows):
            return ready_rows
        if time.time() >= deadline:
            raise InbeidouError(f"等待短剧素材就绪超时: {json.dumps(last_rows, ensure_ascii=False)}")
        time.sleep(poll_interval)


def _is_retryable_source_prepare_error(exc: Exception) -> bool:
    message = str(exc or "").strip().lower()
    if not message:
        return False
    retryable_patterns = [
        "等待短剧素材就绪超时",
        "等待 window_id 超时",
        "ssl",
        "connection reset",
        "connection aborted",
        "connection refused",
        "timed out",
        "read timed out",
        "remote end closed connection",
        "temporarily unavailable",
        "请求失败:",
    ]
    return any(pattern in message for pattern in retryable_patterns)


def _source_prepare_retry_sleep(attempt: int) -> None:
    if attempt <= 0:
        return
    if attempt == 1:
        delay = 3
    elif attempt == 2:
        delay = 8
    else:
        delay = 15
    time.sleep(delay)


def resolve_drama_episode_context(args):
    episode_order = getattr(args, "episode_order", None)
    if episode_order is None:
        raise InbeidouError("缺少剧集参数，请传 --episode-order")

    locator = resolve_drama_locator(args, require_app=True)
    upload_timeout = getattr(args, "upload_timeout", 300)
    poll_interval = getattr(args, "poll_interval", DEFAULT_POLL_INTERVAL)
    retry_count = max(0, int(getattr(args, "source_prepare_retry_count", 0) or 0))
    persist_state = bool(getattr(args, "persist_state", True))
    last_error: Optional[Exception] = None

    for attempt in range(1, retry_count + 2):
        try:
            episode_rows = require_success(
                get_episode_list(serial_id=locator["serial_id"]),
                "获取短剧剧集列表",
            )
            episode_meta = next(
                (
                    item
                    for item in (episode_rows if isinstance(episode_rows, list) else [])
                    if int(item.get("episode_id") or item.get("episode_order") or item.get("sequence") or 0) == int(episode_order)
                ),
                {},
            )
            sketch_rows = poll_sketch_upload(
                serial_id=locator["serial_id"],
                episode_order=episode_order,
                app_id=locator["app_id"],
                timeout=upload_timeout,
                poll_interval=poll_interval,
            )
            first_row = sketch_rows[0]
            upload_id = first_row.get("id")
            if not upload_id:
                raise InbeidouError(f"短剧素材返回缺少 upload_id: {json.dumps(first_row, ensure_ascii=False)}")

            window_body = ensure_upload_window(
                upload_id,
                timeout=upload_timeout,
                poll_interval=poll_interval,
            )
            context = {
                "source_type": "drama_episode",
                "task_id": locator.get("task_id"),
                "task_type": locator.get("task_type"),
                "title": locator.get("title"),
                "serial_id": int(locator["serial_id"]),
                "app_id": str(locator["app_id"]),
                "episode_order": int(episode_order),
                "episode_id": first_row.get("episode_id") or episode_meta.get("episode_id"),
                "target_id": first_row.get("target_id"),
                "upload_id": int(upload_id),
                "window_id": int(window_body.get("window_id")),
                "window_status": window_body.get("status"),
                "agent_id": window_body.get("agent_id"),
                "manus_id": window_body.get("manus_id"),
                "manus_status": window_body.get("manus_status"),
                "media_url": first_row.get("play_url") or episode_meta.get("play_url") or "",
                "filename": f"{locator.get('title') or 'drama'}-E{int(episode_order):02d}",
            }
            if persist_state:
                save_state(context)
            return context
        except InbeidouError as exc:
            last_error = exc
            if attempt > retry_count or not _is_retryable_source_prepare_error(exc):
                break
            _source_prepare_retry_sleep(attempt)

    if last_error is None:
        raise InbeidouError("短剧素材准备失败，未知错误")
    if retry_count > 0 and _is_retryable_source_prepare_error(last_error):
        raise InbeidouError(f"{last_error}（素材阶段已重试 {retry_count} 次）")
    raise last_error


def build_promotion_link_entry(platform_id, payload):
    codes = payload.get("codes", []) if isinstance(payload.get("codes"), list) else []
    return {
        "platform_id": platform_id,
        "platform_name": PROMOTION_PLATFORMS.get(platform_id, f"平台{platform_id}"),
        "atr_id": payload.get("atr_id"),
        "title": payload.get("title", ""),
        "description": payload.get("description", ""),
        "app_link": payload.get("app_link", ""),
        "serial_link": payload.get("serial_link", ""),
        "tiktok_dramago_link": payload.get("tiktok_dramago_link", ""),
        "tiktok_url": payload.get("tiktok_url", ""),
        "code": payload.get("code", ""),
        "promote_code_content": payload.get("promote_code_content", ""),
        "codes": codes,
    }


def probe_video(file_path):
    """用 ffprobe 读取上传所需的视频元数据。"""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise InbeidouError(f"文件不存在: {path}")
    if not path.is_file():
        raise InbeidouError(f"不是有效文件: {path}")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=width,height:format=duration,size",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise InbeidouError("系统未安装 ffprobe，无法探测视频元数据") from exc
    except subprocess.CalledProcessError as exc:
        raise InbeidouError(f"ffprobe 执行失败: {exc.stderr.strip()}") from exc

    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise InbeidouError("ffprobe 输出解析失败") from exc

    streams = payload.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("width") and stream.get("height")), None)
    if not video_stream:
        raise InbeidouError("未找到视频流，无法上传")

    width = int(video_stream.get("width"))
    height = int(video_stream.get("height"))
    duration_raw = float(payload.get("format", {}).get("duration") or 0)
    file_size = int(payload.get("format", {}).get("size") or path.stat().st_size)

    if height > width:
        orientation = "vertical"
    elif width > height:
        orientation = "horizontal"
    else:
        orientation = "square"

    return {
        "path": str(path),
        "filename": path.name,
        "screen_x": width,
        "screen_y": height,
        "file_size": file_size,
        "file_duration": max(1, math.ceil(duration_raw)),
        "orientation": orientation,
    }


def get_user_info():
    return api_request(SCENTER_API, "/user/info", auth_style="bearer")


def get_credit():
    return api_request(SCENTER_API, "/credit/total", auth_style="bearer")


def get_products():
    return api_request(ICENTER_API, "/product/list")


def get_translation_languages():
    return api_request(ICENTER_API, "/translation/languages")


def get_translation_fonts():
    return api_request(ICENTER_API, "/translation/fonts")


def get_translation_effect_styles():
    return api_request(ICENTER_API, "/translation/effect_color_styles")


def get_tasks(page=1, page_size=15, platform="", language="2", search="", order="publish_at", task_type="1"):
    params = {
        "task_type": str(task_type or "1"),
        "page_num": page,
        "page_size": page_size,
        "order_field": order,
        "order_dir": "desc",
        "agent_id": resolve_current_agent_id(),
    }
    if str(language or "").strip():
        params["language"] = str(language).strip()
    if str(search or "").strip():
        params["search_title"] = str(search).strip()
    if platform:
        params["app_id"] = platform
    return api_request(SCENTER_API, "/task/page", params=params, auth_style="bearer")


def get_task_info(task_id, app_id="", task_type="1"):
    params = {"task_id": task_id}
    if app_id:
        params["app_id"] = app_id
    if task_type:
        params["task_type"] = task_type
    return api_request(SCENTER_API, "/task/info", params=params, auth_style="bearer")


def get_creator_enum(task_type="1", agent_id=""):
    params = {"task_type": int(task_type or 1)}
    if str(agent_id or "").strip():
        params["agent_id"] = str(agent_id).strip()
    return api_request(SCENTER_API, "/enum", params=params, auth_style="bearer")


def get_my_task_list(
    page=1,
    page_size=10,
    task_type="1",
    keyword="",
    app_id="",
    order_field="",
    order_dir="",
    language="",
):
    params = {
        "page_num": int(page),
        "page_size": int(page_size),
        "task_type": int(task_type or 1),
    }
    if keyword:
        params["keyword"] = str(keyword)
    if app_id:
        params["app_id"] = str(app_id)
    if order_field:
        params["order_field"] = str(order_field)
    if order_dir:
        params["order_dir"] = str(order_dir)
    if str(language or "").strip():
        params["language"] = str(language).strip()
    return api_request(SCENTER_API, "/task/my_task", params=params, auth_style="bearer")


def get_income_aggregation(
    *,
    start_time="",
    end_time="",
    task_type=0,
    app_id="",
    share_type=0,
    language=0,
    serial_name="",
    order_type=0,
    platform=0,
):
    params = {
        "start_time": start_time,
        "end_time": end_time,
        "task_type": task_type,
        "app_id": app_id,
        "share_type": share_type,
        "language": language,
        "serial_name": serial_name,
        "order_type": order_type,
        "platform": platform,
    }
    return api_request(SCENTER_API, "/sett/order/new_aggregation", params=params, auth_style="bearer")


def get_income_click_aggregation(
    *,
    start_time="",
    end_time="",
    task_type=0,
    app_id="",
    share_type=0,
    language=0,
    serial_name="",
    order_type=0,
    platform=0,
    need_group=1,
):
    params = {
        "start_time": start_time,
        "end_time": end_time,
        "task_type": task_type,
        "app_id": app_id,
        "share_type": share_type,
        "language": language,
        "serial_name": serial_name,
        "order_type": order_type,
        "platform": platform,
        "need_group": need_group,
    }
    return api_request(SCENTER_API, "/sett/order/new_aggregation_click", params=params, auth_style="bearer")


def get_novel_chapter(task_id, app_id):
    return api_request(
        ICENTER_API,
        "/chat/novel/text",
        params={"task_id": str(task_id), "app_id": str(app_id)},
    )


def get_novel_quota():
    return api_request(ICENTER_API, "/chat/novel")


def receive_task(task_id, task_type="1", platform=2):
    """复用 creator task-detail 页点击推广平台按钮时的真实接口。"""
    payload = {
        "task_id": int(task_id),
        "task_type": int(task_type),
        "platform": int(platform),
    }
    return api_request(SCENTER_API, "/task/receive", method="POST", json_data=payload, auth_style="bearer")


def active_task(atr_id):
    """复用 creator task-detail 页复制推广文案后的任务激活接口。"""
    return api_request(
        SCENTER_API,
        "/task/active",
        method="POST",
        data={"atr_id": str(atr_id)},
        extra_headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth_style="bearer",
    )


def get_episode_info(serial_id, episode_order, app_id, need_play=1, task_type="1"):
    params = {
        "serial_id": int(serial_id),
        "episode_order": int(episode_order),
        "need_play": int(need_play),
        "app_id": str(app_id),
    }
    if task_type:
        params["task_type"] = str(task_type)
    return api_request(SCENTER_API, "/episode/info", params=params, auth_style="bearer")


def get_episode_list(serial_id, episode_orders="", start=None, end=None, need_play=1, video_type=""):
    del episode_orders, start, end, need_play, video_type
    return api_request(ICENTER_API, "/sketch/list", params={"serial_id": int(serial_id)})


def sketch_upload(serial_id, episode_orders, app_id):
    payload = {
        "serial_id": int(serial_id),
        "episode_order": [int(value) for value in episode_orders],
        "app_id": str(app_id),
    }
    return api_request(ICENTER_API, "/sketch/upload", method="POST", json_data=payload)


def get_uploads(page=1, page_size=10):
    return api_request(ICENTER_API, "/uploads", params={"page_num": page, "page_size": page_size})


def delete_upload(file_id):
    return api_request(ICENTER_API, f"/uploads/{file_id}", method="DELETE")


def get_manus(page=1, page_size=40, source="manus", task_name=""):
    params = {
        "page_num": page,
        "page_size": page_size,
        "source": source,
        "task_name": task_name,
    }
    return api_request(ICENTER_API, "/manus", params=params)


def get_manus_detail(manus_id):
    return api_request(ICENTER_API, f"/manus/{manus_id}")


def delete_manus(manus_id):
    return api_request(ICENTER_API, "/manus/delete", method="POST", json_data={"manus_ids": [int(manus_id)]})


def get_clip_types():
    return api_request(ICENTER_API, "/mp/enum")


def get_publish_accounts():
    return api_request(ICENTER_API, "/publish/team/social", auth_style="bearer")


def upload_publish_file(file_path):
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise InbeidouError(f"文件不存在: {path}")
    if not path.is_file():
        raise InbeidouError(f"不是有效文件: {path}")
    if path.stat().st_size > PUBLISH_MAX_UPLOAD_SIZE:
        raise InbeidouError("发布视频大小不能超过 1000MB")

    with open(path, "rb") as handle:
        result = api_request(
            ICENTER_API,
            "/publish/team/upload",
            method="POST",
            files={"file": (path.name, handle, "video/mp4")},
            auth_style="bearer",
            timeout=120,
        )
    body = require_success(result, "上传发布视频")
    context = {
        "publish_local_file": str(path),
        "publish_file_url": body.get("url"),
        "publish_upload_ext": body.get("ext"),
        "publish_upload_mime": body.get("mime"),
        "publish_upload_size": body.get("file_size"),
    }
    save_state(context)
    return context


def get_publish_records(
    page=1,
    page_size=10,
    post_status=None,
    status="",
    social_type="",
    social_id="",
    start_date="",
    end_date="",
):
    params = {
        "page_num": page,
        "page_size": page_size,
    }
    if post_status is not None:
        params["post_status"] = int(post_status)
    if status:
        params["status"] = status
    if social_type:
        params["type"] = normalize_publish_platform(social_type)
    if social_id:
        params["social_id"] = social_id
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return api_request(ICENTER_API, "/publish/team/post", params=params, auth_style="bearer")


def get_publish_analysis(
    page=1,
    page_size=10,
    social_type="",
    social_id="",
    start_date="",
    end_date="",
):
    params = {
        "page_num": page,
        "page_size": page_size,
    }
    if social_type:
        params["social_type"] = normalize_publish_platform(social_type)
    if social_id:
        params["social_id"] = social_id
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return api_request(ICENTER_API, "/publish/analysis", params=params, auth_style="bearer")


def create_publish_post(payload):
    return api_request(
        ICENTER_API,
        "/publish/team/post",
        method="POST",
        json_data=payload,
        auth_style="bearer",
    )


def delete_publish_post(post_id="", team_id="", task_id=""):
    return api_request(
        ICENTER_API,
        "/publish/team/post",
        method="DELETE",
        params={"post_id": post_id, "team_id": team_id, "task_id": task_id},
        auth_style="bearer",
    )


def upload_raw_media(file_path):
    """上传媒资原文件到 api-tool。"""
    video = probe_video(file_path)
    with open(video["path"], "rb") as handle:
        result = api_request(
            TOOL_API,
            "/media/upload",
            method="POST",
            data={
                "screen_x": str(video["screen_x"]),
                "screen_y": str(video["screen_y"]),
                "file_size": str(video["file_size"]),
                "file_duration": str(video["file_duration"]),
                "orientation": video["orientation"],
            },
            files={"file": (video["filename"], handle, "video/mp4")},
        )
    body = require_success(result, "上传视频")
    context = {
        "local_file": video["path"],
        "filename": video["filename"],
        "screen_x": video["screen_x"],
        "screen_y": video["screen_y"],
        "file_size": video["file_size"],
        "file_duration": video["file_duration"],
        "orientation": video["orientation"],
        "upload_id": body.get("upload_id"),
        "media_url": body.get("media_url"),
        "media_cover_url": body.get("media_cover_url"),
        "file_path": body.get("file_path"),
    }
    return context


def ensure_upload_window(upload_id, timeout=300, poll_interval=DEFAULT_POLL_INTERVAL):
    """根据 upload_id 创建/轮询 window_id。"""
    deadline = time.time() + timeout
    last_body = None

    while True:
        result = api_request(
            ICENTER_API,
            "/manus/uploads",
            method="POST",
            json_data={"upload_ids": [int(upload_id)]},
        )
        body = require_success(result, "获取上传 window")
        last_body = body
        status = body.get("status")
        window_id = body.get("window_id") or 0

        if status not in RUNNING_STATUSES and window_id:
            return body
        if time.time() >= deadline:
            raise InbeidouError(
                f"等待 window_id 超时: upload_id={upload_id}, status={status}, last={json.dumps(last_body, ensure_ascii=False)}"
            )
        time.sleep(poll_interval)


def upload_video(file_path, timeout=300, poll_interval=DEFAULT_POLL_INTERVAL):
    """完整上传链路: 上传原视频 -> 轮询 window_id。"""
    context = upload_raw_media(file_path)
    window_body = ensure_upload_window(
        context["upload_id"],
        timeout=timeout,
        poll_interval=poll_interval,
    )
    context.update(
        {
            "window_id": window_body.get("window_id"),
            "window_status": window_body.get("status"),
            "agent_id": window_body.get("agent_id"),
            "manus_id": window_body.get("manus_id"),
            "manus_status": window_body.get("manus_status"),
        }
    )
    save_state(context)
    return context


def resolve_media_context(args):
    """优先从参数获取媒资上下文；缺省则回退到最近一次上传。"""
    if getattr(args, "file", None):
        return upload_video(
            args.file,
            timeout=getattr(args, "upload_timeout", 300),
            poll_interval=getattr(args, "poll_interval", DEFAULT_POLL_INTERVAL),
        )

    if (
        getattr(args, "episode_order", None) is not None
        or getattr(args, "serial_id", None)
        or getattr(args, "task_id", None)
        or getattr(args, "search", None)
    ):
        return resolve_drama_episode_context(args)

    state = load_state()
    upload_id = getattr(args, "upload_id", None) or state.get("upload_id")
    if not upload_id:
        raise InbeidouError("缺少媒资参数，请传 --file、--upload-id，或短剧剧集来源参数")

    window_id = getattr(args, "window_id", None)
    if not window_id:
        if str(state.get("upload_id")) == str(upload_id):
            window_id = state.get("window_id")
        if not window_id:
            window_body = ensure_upload_window(
                upload_id,
                timeout=getattr(args, "upload_timeout", 300),
                poll_interval=getattr(args, "poll_interval", DEFAULT_POLL_INTERVAL),
            )
            window_id = window_body.get("window_id")

    context = {
        "upload_id": int(upload_id),
        "window_id": int(window_id),
        "local_file": state.get("local_file"),
        "filename": state.get("filename"),
        "media_url": state.get("media_url"),
        "media_cover_url": state.get("media_cover_url"),
    }
    save_state(context)
    return context


def normalize_publish_platform(value):
    if not value:
        return ""
    platform = str(value).strip().upper()
    if platform not in PUBLISH_SOCIAL_TYPES:
        raise InbeidouError(
            f"不支持的平台: {value}，可选值: {', '.join(PUBLISH_SOCIAL_TYPES)}"
        )
    return platform


def split_cli_values(values):
    items = []
    for value in values or []:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                items.append(part)
    return items


def resolve_account_pool(name):
    pool_name = str(name or "").strip()
    if not pool_name:
        return {}
    pools = load_account_pools()
    pool = pools.get(pool_name)
    if not isinstance(pool, dict):
        raise InbeidouError(
            f"未找到账号池: {pool_name}，可选值: {', '.join(sorted(pools.keys()) or NOVEL_ACCOUNT_POOLS)}"
        )
    return pool


def split_pool_account_ids(pool):
    return [str(item).strip() for item in pool.get("account_ids") or [] if str(item).strip()]


def resolve_novel_generator(args):
    value = str(getattr(args, "generator", "") or "").strip().lower()
    if value and value != "vidu":
        raise InbeidouError("小说视频生成已统一切换到官方 Vidu，不再支持其他生成器")
    return DEFAULT_NOVEL_GENERATOR


def resolve_novel_publish_platform(args):
    platform = normalize_publish_platform(getattr(args, "publish_platform", ""))
    if platform:
        return platform
    return "FACEBOOK"


def _sanitize_prompt_excerpt(text, limit=700):
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def build_vidu_prompt(chapter, user_prompt=""):
    prompt = str(user_prompt or "").strip()
    if prompt:
        return prompt
    chapter_text = str(chapter.get("text") or chapter.get("text_preview") or "").strip()
    return _sanitize_prompt_excerpt(chapter_text)


def parse_schedule_at(value):
    if not value:
        return None
    raw = value.strip()
    formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]
    for pattern in formats:
        try:
            parsed = datetime.strptime(raw, pattern)
            break
        except ValueError:
            parsed = None
    if parsed is None:
        raise InbeidouError("定时发布时间格式错误，请使用 'YYYY-MM-DD HH:MM' 或 'YYYY-MM-DD HH:MM:SS'")

    min_time = datetime.now() + timedelta(minutes=5)
    max_time = datetime.now() + timedelta(days=31)
    if parsed < min_time:
        raise InbeidouError("定时发布时间至少需要晚于当前时间 5 分钟")
    if parsed > max_time:
        raise InbeidouError("定时发布时间不能超过 31 天")
    return parsed.strftime("%Y-%m-%d %H:%M:00")


def get_publish_text(args):
    if getattr(args, "text", None):
        return args.text.strip()
    if getattr(args, "text_file", None):
        path = Path(args.text_file).expanduser().resolve()
        if not path.exists():
            raise InbeidouError(f"文案文件不存在: {path}")
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    raise InbeidouError("缺少帖子内容，请传 --text 或 --text-file")


def resolve_publish_file_url(args):
    if getattr(args, "file", None):
        return upload_publish_file(args.file)["publish_file_url"]
    if getattr(args, "file_url", None):
        return args.file_url.strip()

    state = load_state()
    file_url = state.get("publish_file_url")
    if not file_url:
        raise InbeidouError("缺少发布视频，请传 --file、--file-url，或先执行 publish upload")
    return file_url


def resolve_publish_targets(args):
    account_ids = split_cli_values(getattr(args, "account_id", None))
    team_ids = split_cli_values(getattr(args, "team_id", None))
    account_pool_name = str(getattr(args, "account_pool", "") or "").strip()

    if account_pool_name and not account_ids and not team_ids:
        pool = resolve_account_pool(account_pool_name)
        account_ids = split_pool_account_ids(pool)
        pool_platform = normalize_publish_platform(pool.get("platform"))
        requested_platform = normalize_publish_platform(getattr(args, "platform", ""))
        if requested_platform and pool_platform and requested_platform != pool_platform:
            raise InbeidouError(
                f"账号池 {account_pool_name} 的平台是 {pool_platform}，与当前发布平台 {requested_platform} 不一致"
            )
        if not getattr(args, "platform", None):
            setattr(args, "platform", pool_platform)

    if account_ids:
        accounts = require_success(get_publish_accounts(), "获取发布账号列表")
        selected = [account for account in accounts if str(account.get("id")) in set(account_ids)]
        found_ids = {str(account.get("id")) for account in selected}
        missing = [account_id for account_id in account_ids if account_id not in found_ids]
        if missing:
            raise InbeidouError(f"未找到账号 ID: {', '.join(missing)}")

        invalid = [
            account
            for account in selected
            if account.get("status") != 0 or not account.get("team_id")
        ]
        if invalid:
            raise InbeidouError(
                "选择的账号包含不可发布项: "
                + ", ".join(str(account.get("id")) for account in invalid)
            )

        social_types = {account.get("type") for account in selected}
        if len(social_types) != 1:
            raise InbeidouError("一次发布只能选择同一平台的账号")

        return {
            "social_type": next(iter(social_types)),
            "team_ids": [account.get("team_id") for account in selected],
            "accounts": selected,
        }

    if team_ids:
        social_type = normalize_publish_platform(getattr(args, "platform", ""))
        return {
            "social_type": social_type,
            "team_ids": team_ids,
            "accounts": [],
        }

    raise InbeidouError("请传 --account-id 或 --team-id 指定发布目标")


def build_publish_payload(args):
    target = resolve_publish_targets(args)
    file_url = resolve_publish_file_url(args)
    text = get_publish_text(args)
    post_date = parse_schedule_at(getattr(args, "schedule_at", None))

    payload = {
        "team_id": ",".join(target["team_ids"]),
        "text": text,
        "file_url": file_url,
        "post_status": PUBLISH_POST_STATUS_VALUE["scheduled" if post_date else "published"],
        "social_type": target["social_type"],
    }
    if post_date:
        payload["post_date"] = post_date
    if target["social_type"] in {"FACEBOOK", "INSTAGRAM"}:
        payload["type"] = "REEL"

    return payload, target


def resolve_publish_record_social_id(args):
    social_id = str(getattr(args, "social_id", "") or "").strip()
    if social_id:
        return social_id
    account_ids = split_cli_values(getattr(args, "account_id", None))
    if not account_ids:
        return ""
    if len(account_ids) != 1:
        raise InbeidouError("查看发布记录时，--account-id 目前只支持传单个账号")
    account_id = account_ids[0]
    accounts = require_success(get_publish_accounts(), "获取发布账号列表")
    matched = next((item for item in accounts if str(item.get("id") or "") == account_id), None)
    if not matched:
        raise InbeidouError(f"未找到账号 ID: {account_id}")
    resolved = str(
        matched.get("social_id")
        or matched.get("social_account_id")
        or matched.get("socialId")
        or ""
    ).strip()
    if not resolved:
        raise InbeidouError(f"账号 {account_id} 缺少 social_id，暂时无法按账号筛选发布记录")
    return resolved


def describe_publish_accounts(accounts):
    print(f"\n📣 已授权发布账号 (共 {len(accounts)} 个)")
    print("=" * 140)
    print(
        f"{'ID':<6} {'平台':<12} {'昵称':<28} {'状态':<18} {'team_id':<38} {'频道'}"
    )
    print("-" * 140)
    for account in accounts:
        channel_names = ",".join(channel.get("name", "") for channel in account.get("channels", [])[:2])
        status = PUBLISH_ACCOUNT_STATUSES.get(account.get("status"), str(account.get("status")))
        print(
            f"{str(account.get('id')):<6} "
            f"{PUBLISH_SOCIAL_NAMES.get(account.get('type'), account.get('type', '')):<12} "
            f"{str(account.get('social_name', ''))[:26]:<28} "
            f"{status:<18} "
            f"{str(account.get('team_id', '')):<38} "
            f"{channel_names}"
        )


def describe_publish_records(body):
    items = body.get("items", [])
    total = body.get("page", {}).get("total_count", 0)
    print(f"\n🗂️ 发布记录 (共 {total} 条)")
    print("=" * 150)
    print(
        f"{'ID':<6} {'平台':<12} {'账号':<24} {'状态':<12} {'发布时间':<20} {'team_id':<38} {'task_id'}"
    )
    print("-" * 150)
    for item in items:
        print(
            f"{str(item.get('id', '')):<6} "
            f"{PUBLISH_SOCIAL_NAMES.get(item.get('social_type'), item.get('social_type', '')):<12} "
            f"{str(item.get('social_name', ''))[:22]:<24} "
            f"{str(item.get('status', '')):<12} "
            f"{str(item.get('post_date', '')):<20} "
            f"{str(item.get('team_id', '')):<38} "
            f"{str(item.get('task_id', ''))}"
        )


def describe_publish_analysis(body):
    items = body.get("items") if isinstance(body.get("items"), list) else []
    total = int((body.get("page") or {}).get("total_count") or len(items) or 0)
    print(f"\n📈 发布数据分析 (共 {total} 条)")
    print("=" * 150)
    print(
        f"{'平台':<12} {'账号':<24} {'播放':<10} {'点赞':<10} {'评论':<10} {'分享':<10} {'收益':<12} {'发布时间'}"
    )
    print("-" * 150)
    for item in items:
        print(
            f"{PUBLISH_SOCIAL_NAMES.get(item.get('social_type'), item.get('social_type', '')):<12} "
            f"{str(item.get('social_name', ''))[:22]:<24} "
            f"{str(item.get('views', 0)):<10} "
            f"{str(item.get('likes', 0)):<10} "
            f"{str(item.get('comments', 0)):<10} "
            f"{str(item.get('shares', 0)):<10} "
            f"{str(item.get('order_amount', 0)):<12} "
            f"{str(item.get('post_date', ''))}"
        )
    print("-" * 150)
    print(
        "汇总: "
        f"播放 {body.get('view', 0)} | "
        f"互动 {body.get('interaction', 0)} | "
        f"收益 {body.get('order_amount', 0)}"
    )


def analyze_video(upload_id, window_id, timeout=600, poll_interval=DEFAULT_POLL_INTERVAL):
    """智影解析轮询。"""
    deadline = time.time() + timeout
    last_body = None

    while True:
        result = api_request(
            ICENTER_API,
            "/manus/vision/analyze_v3",
            method="POST",
            json_data={"window_id": int(window_id), "upload_ids": [int(upload_id)]},
        )
        body = require_success(result, "智影解析")
        last_body = body
        if body.get("status") not in RUNNING_STATUSES:
            save_state({"last_analysis": body})
            return body
        if time.time() >= deadline:
            raise InbeidouError(f"等待智影解析超时: {json.dumps(last_body, ensure_ascii=False)}")
        time.sleep(poll_interval)


def describe_analysis(body):
    """友好打印解析结果摘要。"""
    duration_map = body.get("file_duration", {})
    duration = next(iter(duration_map.values()), 0)
    print("\n🧠 智影解析")
    print("=" * 80)
    print(f"   window_id: {body.get('window_id')}")
    print(f"   upload_ids: {body.get('upload_ids')}")
    print(f"   时长: {format_seconds(duration)}")
    print(f"   状态: {body.get('status')}")

    sections = [
        ("golden_seconds", "🎯 黄金片段"),
        ("excitement", "✨ 亮点解析"),
        ("importance", "📚 剧情解析"),
        ("twist", "🪝 结尾悬念"),
    ]
    for key, title in sections:
        items = body.get(key, {}).get("items_v3", [])
        if not items:
            continue
        print(f"\n{title}")
        print("-" * 80)
        for item in items[:5]:
            content = item.get("content") or "(无文案)"
            print(f"   [{item.get('timestamp')}] score={item.get('score')}  {content}")

    emotional = body.get("emotional", {}).get("items_v3", [])
    if emotional:
        peak = max(emotional, key=lambda item: item.get("score", 0))
        print("\n📈 情绪峰值")
        print("-" * 80)
        print(
            f"   [{peak.get('timestamp')}] score={peak.get('score')} play_time={peak.get('play_time')}"
        )


def build_high_cut_params(args):
    """按前端真实逻辑构造高燃剪辑参数。"""
    deduplication = args.deduplication or DEFAULT_DEDUPLICATION
    params = {
        "watermark": args.watermark or "",
        "cut_duration": args.duration,
        "output_count": 1,
        "cut_type": args.cut_type,
        "script_count": 1,
    }
    for key in deduplication:
        params[key] = True
    return params


def alignment_to_subtitle_x(alignment):
    """前端字幕对齐 -> subtitle_x。"""
    if alignment == "Right":
        return 0.9999
    if alignment == "Left":
        return 0
    return 0.5


def build_translate_params(args):
    """按前端真实逻辑构造翻译参数。"""
    config = dict(DEFAULT_TRANSLATE_CONFIG)
    config.update(
        {
            "source_language": args.source_lang,
            "target_language": args.target_lang,
            "need_speech_translate": not args.no_speech_translate,
            "subtitle_type": args.subtitle_type,
            "subtitle_y": args.subtitle_y,
            "font": args.font,
            "font_size": args.font_size,
            "font_color": args.font_color,
            "alignment": args.alignment,
            "font_face_bold": args.bold,
            "font_face_underline": args.underline,
            "font_face_italic": args.italic,
            "font_color_opacity": args.font_opacity,
            "effect_color_style": args.effect_style or "",
            "shadow": args.shadow,
            "shadow_shift": args.shadow_shift,
            "shadow_x_bord": args.shadow_x_bord,
            "shadow_y_bord": args.shadow_y_bord,
            "shadow_opacity": args.shadow_opacity,
            "outline": args.outline,
            "outline_board": args.outline_board,
        }
    )

    subtitle_y = 0.99 if config["subtitle_y"] >= 100 else config["subtitle_y"] / 100
    params = {
        "source_language": config["source_language"],
        "target_language": config["target_language"],
        "need_speech_translate": config["need_speech_translate"],
        "subtitle_type": config["subtitle_type"],
        "subtitle_x": alignment_to_subtitle_x(config["alignment"]),
        "subtitle_y": subtitle_y,
        "font": config["font"],
        "font_size": config["font_size"],
        "font_color": config["font_color"],
        "alignment": config["alignment"],
        "font_face_bold": config["font_face_bold"],
        "font_face_underline": config["font_face_underline"],
        "font_face_italic": config["font_face_italic"],
        "font_color_opacity": str(config["font_color_opacity"] / 100),
        "effect_color_style": config["effect_color_style"],
        "ocr_area_x": -1,
        "ocr_area_y": -1,
        "ocr_area_width": -1,
        "ocr_area_height": -1,
    }

    if not config["effect_color_style"] and config["shadow"]:
        params.update(
            {
                "shadow_shift": config["shadow_shift"] / 30,
                "shadow_x_bord": config["shadow_x_bord"] / 30,
                "shadow_y_bord": config["shadow_y_bord"] / 30,
                "shadow_opacity": str(config["shadow_opacity"] / 100),
            }
        )
    else:
        params.update(
            {
                "shadow_shift": -1,
                "shadow_x_bord": -1,
                "shadow_y_bord": -1,
                "shadow_opacity": "",
            }
        )

    if not config["effect_color_style"] and config["outline"]:
        params["outline_board"] = config["outline_board"]
    else:
        params["outline_board"] = -1

    return params


def submit_ws_tasks(window_id, upload_ids, tasks, merge_video=False, timeout=90):
    """通过前端同款 websocket 提交智能任务。"""
    payload = {
        "question": "",
        "upload_ids": [int(upload_id) for upload_id in upload_ids],
        "window_id": int(window_id),
        "msg_type": "card",
        "token": load_auth_token(),
        "merge_video": bool(merge_video),
        "tasks": tasks,
    }

    try:
        ws = create_connection(WS_MANUS_CHATS, timeout=timeout)
    except Exception as exc:
        raise InbeidouError(f"建立 WebSocket 连接失败: {exc}") from exc

    try:
        ws.send(json.dumps(payload, ensure_ascii=False))
        deadline = time.time() + timeout
        last_message = None

        while time.time() < deadline:
            try:
                message = ws.recv()
            except WebSocketTimeoutException:
                continue
            if message == "pong":
                continue
            try:
                data = json.loads(message)
            except ValueError:
                continue
            last_message = data
            if data.get("msg_type") == "error":
                raise InbeidouError(f"任务提交失败: {data.get('body') or data.get('msg_type')}")
            if data.get("is_end"):
                return data

        raise InbeidouError(f"等待任务受理超时: {json.dumps(last_message, ensure_ascii=False)}")
    except WebSocketException as exc:
        raise InbeidouError(f"WebSocket 任务提交异常: {exc}") from exc
    finally:
        try:
            ws.close()
        except Exception:
            pass


def wait_for_manus(manus_id, timeout=DEFAULT_TASK_TIMEOUT, poll_interval=DEFAULT_POLL_INTERVAL):
    """轮询 manus 直到完成。"""
    deadline = time.time() + timeout
    last_body = None

    while True:
        result = get_manus_detail(manus_id)
        body = require_success(result, "查询作品详情")
        last_body = body
        status = body.get("status")
        if status not in RUNNING_STATUSES:
            save_state({"last_manus_id": manus_id, "last_manus_status": status})
            return body
        if time.time() >= deadline:
            timeout_context = build_manus_timeout_context(manus_id, status, last_body)
            save_state(
                {
                    "last_manus_id": manus_id,
                    "last_manus_status": status,
                    "last_manus_timeout_detail": timeout_context,
                }
            )
            raise InbeidouError(
                f"等待作品生成超时: {json.dumps(timeout_context, ensure_ascii=False)}"
            )
        time.sleep(poll_interval)


def build_manus_timeout_context(manus_id, status, last_body):
    """保留作品轮询超时时接口最后一次返回的关键信息，方便定位后端原因。"""
    body = dict(last_body or {})
    media = body.get("media") if isinstance(body.get("media"), list) else []
    error_fields = {}
    for key in (
        "msg",
        "message",
        "error",
        "error_msg",
        "fail_reason",
        "reason",
        "remark",
        "task_name",
        "history_id",
        "window_id",
        "created_time",
        "updated_time",
    ):
        value = body.get(key)
        if value not in (None, ""):
            error_fields[key] = value
    return {
        "manus_id": str(manus_id or body.get("id") or ""),
        "status": str(status or body.get("status") or ""),
        "接口最后返回摘要": error_fields,
        "输出视频数量": len(media),
        "是否有 video_url": bool(body.get("video_url")),
        "接口返回字段": sorted(str(key) for key in body.keys()),
    }


def first_output_media_url(body):
    """取作品详情中的首个输出视频 URL。"""
    media = body.get("media") or []
    if media:
        return media[0].get("media_url")
    return body.get("video_url")


def describe_manus(body):
    """打印作品详情。"""
    print("\n🎬 作品详情")
    print("=" * 80)
    print(f"   manus_id: {body.get('id')}")
    print(f"   task_name: {body.get('task_name')}")
    print(f"   status: {body.get('status')}")
    print(f"   history_id: {body.get('history_id')}")
    print(f"   window_id: {body.get('window_id')}")
    print(f"   created_time: {body.get('created_time')}")
    media = body.get("media") or []
    if media:
        print(f"   输出数量: {len(media)}")
        for idx, item in enumerate(media, start=1):
            print(f"   输出{idx}: {item.get('media_url')}")
    elif body.get("video_url"):
        print(f"   视频URL: {body.get('video_url')}")
    if body.get("cover_url"):
        print(f"   封面: {body.get('cover_url')}")


def download_manus(manus_id, output_dir="."):
    """下载作品视频。"""
    deadline = time.time() + max(1.0, float(DEFAULT_MANUS_MEDIA_TIMEOUT))
    last_body = {}
    media_url = ""
    while True:
        result = get_manus_detail(manus_id)
        body = require_success(result, "获取作品详情")
        last_body = body
        media_url = first_output_media_url(body)
        if media_url:
            break
        if time.time() >= deadline:
            status = str(body.get("status") or "").strip() or "unknown"
            title = str(body.get("task_name") or body.get("title") or manus_id).strip() or str(manus_id)
            raise InbeidouError(
                f"作品暂无可下载视频（等待 {int(DEFAULT_MANUS_MEDIA_TIMEOUT)}s 后仍未就绪，status={status}，title={title}）"
            )
        time.sleep(max(1.0, float(DEFAULT_MANUS_MEDIA_POLL_INTERVAL)))

    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    title = last_body.get("task_name") or last_body.get("title") or f"manus_{manus_id}"
    safe_title = "".join(ch for ch in title if ch not in '\\/:*?"<>|').strip() or f"manus_{manus_id}"
    target = output_path / f"{safe_title}.mp4"
    if target.exists():
        target = output_path / f"{safe_title}_manus_{manus_id}.mp4"

    try:
        response = requests.get(media_url, timeout=120)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise InbeidouError(f"下载失败: {exc}") from exc

    target.write_bytes(response.content)
    return str(target)


def filter_languages_payload(data, view_type):
    if view_type == "speech":
        return {"speech_source_language": data.get("speech_source_language", [])}
    if view_type == "target":
        return {"speech_target_language": data.get("speech_target_language", [])}
    if view_type == "subtitle":
        return {
            "subtitle_source_language": data.get("subtitle_source_language", []),
            "subtitle_target_language": data.get("subtitle_target_language", []),
        }
    return data


def cmd_user(args):
    body = require_success(get_user_info(), "获取用户信息")
    if getattr(args, "json", False):
        pretty_print_json(body)
        return
    print("\n👤 用户信息")
    print("=" * 40)
    print(f"   用户ID: {body.get('agent_id')}")
    print(f"   昵称: {body.get('nickname')}")
    print(f"   手机: {body.get('phone')}")
    print(f"   邀请码: {body.get('invite_code')}")
    print(f"   分佣比例: {body.get('share_rate')}%")
    print(f"   总收入: ¥{body.get('total_income')}")


def cmd_credit(args):
    body = require_success(get_credit(), "获取积分余额")
    if getattr(args, "json", False):
        pretty_print_json(body)
        return
    print("\n💰 积分余额")
    print("=" * 40)
    print(f"   总积分: {body.get('total')}")
    print(f"   购买积分: {body.get('buy')}")
    print(f"   赠送积分: {body.get('gift')}")
    print(f"   VIP积分: {body.get('vip')}")


def cmd_products(args):
    products = require_success(get_products(), "获取产品列表")
    if getattr(args, "json", False):
        pretty_print_json(products)
        return
    print("\n🛠️ AI工具/产品")
    print("=" * 80)
    print(f"{'ID':<4} {'名称':<35} {'原价':<10} {'折扣价'}")
    print("-" * 80)
    for product in products:
        print(
            f"{product.get('id'):<4} {product.get('name'):<35} {product.get('credit'):<10} {product.get('discount_credit')}"
        )


def cmd_languages(args):
    data = require_success(get_translation_languages(), "获取翻译语言")
    if getattr(args, "json", False):
        pretty_print_json(filter_languages_payload(data, args.type))
        return

    if args.type in ("all", "speech"):
        print("\n🎤 语音支持语言")
        print("-" * 40)
        for lang in data.get("speech_source_language", []):
            print(f"   {lang.get('code'):<10} {lang.get('name')}")

    if args.type in ("all", "target"):
        print("\n🎯 目标语言")
        print("-" * 40)
        for lang in data.get("speech_target_language", []):
            print(f"   {lang.get('code'):<10} {lang.get('name')}")

    if args.type in ("all", "subtitle"):
        print("\n📝 字幕语言")
        print("-" * 40)
        print("   源语言:")
        for lang in data.get("subtitle_source_language", []):
            print(f"      {lang.get('code'):<10} {lang.get('name')}")
        print("   目标语言:")
        for lang in data.get("subtitle_target_language", []):
            print(f"      {lang.get('code'):<10} {lang.get('name')}")


def cmd_publish(args):
    if args.action == "accounts":
        accounts = require_success(get_publish_accounts(), "获取发布账号列表")
        if args.platform:
            platform = normalize_publish_platform(args.platform)
            accounts = [account for account in accounts if account.get("type") == platform]
        if args.status is not None:
            accounts = [account for account in accounts if int(account.get("status", -1)) == args.status]
        if args.json:
            pretty_print_json(accounts)
            return
        describe_publish_accounts(accounts)
        return

    if args.action == "upload":
        context = upload_publish_file(args.file)
        if args.json:
            pretty_print_json(context)
            return
        print("\n📤 发布视频上传成功")
        print("=" * 80)
        print(f"   文件: {context.get('publish_local_file')}")
        print(f"   file_url: {context.get('publish_file_url')}")
        print(f"   size: {format_size(context.get('publish_upload_size'))}")
        print(f"   mime: {context.get('publish_upload_mime')}")
        return

    if args.action == "create":
        payload, target = build_publish_payload(args)
        if args.dry_run:
            pretty_print_json({"payload": payload, "target": target})
            return

        body = require_success(create_publish_post(payload), "发布帖子")
        tasks = body.get("tasks", [])
        save_state({"last_publish_payload": payload, "last_publish_tasks": tasks})

        if args.json:
            pretty_print_json({"payload": payload, "tasks": tasks})
            return

        print("\n🚀 发布任务已提交")
        print("=" * 80)
        print(f"   平台: {PUBLISH_SOCIAL_NAMES.get(payload.get('social_type'), payload.get('social_type'))}")
        print(f"   team_id: {payload.get('team_id')}")
        print(f"   post_status: {'scheduled' if payload.get('post_status') == 1 else 'published'}")
        if payload.get("post_date"):
            print(f"   post_date: {payload.get('post_date')}")
        for index, task in enumerate(tasks, start=1):
            print(
                f"   任务{index}: team_id={task.get('team_id')} task_id={task.get('task_id')} "
                f"status={task.get('status')} message={task.get('message')}"
            )
        return

    if args.action == "records":
        post_status = PUBLISH_POST_STATUS_VALUE[args.post_status]
        social_id = resolve_publish_record_social_id(args)
        body = require_success(
            get_publish_records(
                page=args.page,
                page_size=args.size,
                post_status=post_status,
                status=args.status,
                social_type=args.platform,
                social_id=social_id,
            ),
            "获取发布记录",
        )
        if args.json:
            pretty_print_json(body)
            return
        describe_publish_records(body)
        return

    if args.action == "analysis":
        body = require_success(
            get_publish_analysis(
                page=args.page,
                page_size=args.size,
                social_type=args.platform,
                social_id=args.social_id,
                start_date=args.start_date,
                end_date=args.end_date,
            ),
            "获取发布数据分析",
        )
        if args.json:
            pretty_print_json(body)
            return
        describe_publish_analysis(body)
        return

    if args.action == "delete":
        require_success(
            delete_publish_post(
                post_id=args.post_id or "",
                team_id=args.team_id,
                task_id=args.task_id,
            ),
            "删除发布记录",
        )
        if getattr(args, "json", False):
            pretty_print_json(
                {
                    "success": True,
                    "team_id": args.team_id,
                    "task_id": args.task_id,
                    "post_id": args.post_id or "",
                }
            )
            return
        print("删除成功!")


def _chapter_payload(novel):
    last_error = None
    for attempt in range(1, DEFAULT_NOVEL_CHAPTER_RETRIES + 1):
        try:
            body = require_success(
                get_novel_chapter(task_id=novel.get("task_id"), app_id=novel.get("app_id")),
                "获取小说章节",
            )
            break
        except Exception as exc:
            last_error = exc
            if attempt >= DEFAULT_NOVEL_CHAPTER_RETRIES:
                raise
            time.sleep(min(3 * attempt, 8))
    else:
        raise last_error or InbeidouError("获取小说章节失败")
    text = str(body.get("text") or "")
    return {
        "text": text,
        "text_length": len(text),
        "text_preview": text[:500],
        "timbre": body.get("timbre") or [],
        "novel": dict(novel or {}),
    }


def _promotion_text_from_result(result):
    data = result.get("data") or {}
    links = data.get("promotion_links") if isinstance(data.get("promotion_links"), list) else []
    if len(links) == 1:
        link = links[0]
        return str(link.get("promote_code_content") or link.get("description") or "").strip()
    for link in links:
        if str(link.get("platform") or "").lower() in {"1", "tiktok", "tik tok"}:
            return str(link.get("promote_code_content") or link.get("description") or "").strip()
    return str(data.get("content") or result.get("content") or "").strip()


def _compose_promotion_caption(base_text: str, promotion_link: str) -> str:
    text = str(base_text or "").strip()
    link = str(promotion_link or "").strip()
    if text and link:
        if link in text:
            return text
        return f"{text}\n{link}"
    return text or link


def _normalize_frontend_promotion_text(raw_text: str) -> str:
    text = str(raw_text or "")
    return (
        text.replace("<br />", "\n")
        .replace("<br/>", "\n")
        .replace("<br>", "\n")
        .strip()
    )


def _inject_novel_promo_code(caption: str, promotion_code: str) -> str:
    text = str(caption or "").strip()
    code = str(promotion_code or "").strip()
    if not text or not code:
        return text
    updated = re.sub(r"X{4,}", code, text, count=1)
    if updated != text:
        return updated
    updated = re.sub(r"x{4,}", code, text, count=1)
    return updated


def _novel_promotion_caption(novel: dict, publish_platform: str) -> dict[str, str]:
    promotion_platform = PUBLISH_TO_PROMOTION_PLATFORM.get(str(publish_platform or "").upper())
    title = str(novel.get("title") or novel.get("title_ch") or "小说").strip()
    if not promotion_platform:
        return {"caption": title, "promotion_link": "", "promotion_code": "", "title": title, "description": ""}
    payload = require_success(
        receive_task(
            task_id=novel.get("task_id"),
            task_type=novel.get("task_type") or "2",
            platform=promotion_platform,
        ),
        f"获取 {PROMOTION_PLATFORMS[promotion_platform]} 推广链接",
    )
    atr_id = payload.get("atr_id")
    if atr_id:
        require_success(
            active_task(atr_id),
            f"激活 {PROMOTION_PLATFORMS[promotion_platform]} 推广任务",
        )
    link_entry = build_promotion_link_entry(promotion_platform, payload)
    promotion_link = (
        str(link_entry.get("serial_link") or "").strip()
        or str(link_entry.get("app_link") or "").strip()
        or str(link_entry.get("tiktok_url") or "").strip()
    )
    if not promotion_link:
        raise InbeidouError(f"《{title}》未拿到可发布推广链接")
    promote_code_content = _normalize_frontend_promotion_text(
        str(link_entry.get("promote_code_content") or "")
    )
    description = _normalize_frontend_promotion_text(str(link_entry.get("description") or ""))
    caption = promote_code_content or description
    if not caption:
        raise InbeidouError(f"《{title}》未拿到可发布推广文案")
    promotion_code = str(link_entry.get("code") or "").strip()
    final_caption = _inject_novel_promo_code(caption, promotion_code)
    return {
        "raw_caption": caption,
        "title": str(link_entry.get("title") or title).strip(),
        "caption": final_caption,
        "promotion_link": promotion_link,
        "promotion_code": promotion_code,
        "promote_code_content": promote_code_content,
        "description": description,
    }


def _download_novel_publish_video(video_url: str, title: str = "", task_id: str = "", *, category: str = "分段") -> str:
    initial_url = str(video_url or "").strip()
    if not initial_url:
        raise InbeidouError("小说视频结果没有 video_url，无法下载发布视频")
    temp_dir = _novel_work_dir(category)
    safe_title = "".join(ch if ch.isalnum() else "_" for ch in (title or "novel_video"))[:48].strip("_") or "novel_video"
    target = temp_dir / f"{safe_title}.mp4"
    attempted_urls = []
    candidate_urls = [initial_url]
    last_error = ""
    for candidate_url in candidate_urls:
        attempted_urls.append(candidate_url)
        try:
            if target.exists():
                target.unlink()
            with requests.get(candidate_url, stream=True, timeout=120) as response:
                response.raise_for_status()
                with open(target, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            if target.exists() and target.stat().st_size > 0:
                return str(target)
            last_error = "文件为空"
        except Exception as exc:
            last_error = str(exc)
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                pass
    if not target.exists() or target.stat().st_size <= 0:
        raise InbeidouError(
            f"下载小说发布视频失败: {last_error or '文件为空'}"
            + (f"；已尝试刷新 Vidu 生成物链接" if len(candidate_urls) > 1 else "")
        )
    return str(target)


def _find_publish_record(*, platform: str, team_id: str, task_id: str) -> dict:
    if not platform or not team_id or not task_id:
        return {}
    for page in range(1, 4):
        body = require_success(
            get_publish_records(page=page, page_size=100, social_type=platform),
            f"获取 {platform} 发布记录",
        )
        items = body.get("items") if isinstance(body.get("items"), list) else []
        if not items:
            return {}
        for item in items:
            if str(item.get("team_id") or "") == team_id and str(item.get("task_id") or "") == task_id:
                return dict(item)
    return {}


def _poll_publish_records(*, platform: str, tasks: list[dict], wait_seconds: int, poll_interval: int) -> list[dict]:
    deadline = time.time() + max(0, int(wait_seconds))
    records: list[dict] = []
    while True:
        records = [
            _find_publish_record(
                platform=platform,
                team_id=str(task.get("team_id") or ""),
                task_id=str(task.get("task_id") or ""),
            )
            for task in tasks
        ]
        statuses = [
            str(record.get("status") or task.get("status") or "").upper()
            for record, task in zip(records, tasks)
            if str(record.get("status") or task.get("status") or "").strip()
        ]
        if statuses and not any(status in RUNNING_PUBLISH_STATUSES for status in statuses):
            return records
        if time.time() >= deadline:
            return records
        time.sleep(max(1, int(poll_interval)))


def _novel_publish_failure_reason(records: list[dict], tasks: list[dict]) -> str:
    for record in records:
        message = str(record.get("error_msg") or record.get("message") or "").strip()
        if message:
            return message
    for task in tasks:
        message = str(task.get("message") or "").strip()
        if message and str(task.get("status") or "").upper() in FINAL_FAILURE_PUBLISH_STATUSES:
            return message
    return ""


def _default_novel_publish_wait_seconds(args, platform: str) -> int:
    explicit_value = getattr(args, "collect_wait_seconds", None)
    if explicit_value not in (None, ""):
        try:
            return max(0, int(explicit_value))
        except (TypeError, ValueError):
            pass
    return 0


def _settle_novel_publish(args, publish_payload: dict) -> dict:
    payload = publish_payload.get("payload") if isinstance(publish_payload.get("payload"), dict) else {}
    target = publish_payload.get("target") if isinstance(publish_payload.get("target"), dict) else {}
    result = publish_payload.get("result") if isinstance(publish_payload.get("result"), dict) else {}
    tasks = result.get("tasks") if isinstance(result.get("tasks"), list) else []
    platform = str(payload.get("social_type") or "").upper()
    wait_seconds = _default_novel_publish_wait_seconds(args, platform)
    poll_interval = int(getattr(args, "collect_poll_interval", 15) or 15)
    records = _poll_publish_records(
        platform=platform,
        tasks=tasks,
        wait_seconds=wait_seconds,
        poll_interval=poll_interval,
    ) if tasks else []

    statuses = [
        str(record.get("status") or task.get("status") or "").upper()
        for record, task in zip(records, tasks)
        if str(record.get("status") or task.get("status") or "").strip()
    ]
    account_names = [
        str(record.get("social_name") or "").strip()
        for record in records
        if str(record.get("social_name") or "").strip()
    ]
    if not account_names:
        account_names = [
            str(account.get("social_name") or account.get("name") or "").strip()
            for account in (target.get("accounts") or [])
            if str(account.get("social_name") or account.get("name") or "").strip()
        ]

    final_status = "submitted"
    final_status_zh = "已提交发布任务"
    if any(status in SUCCESSFUL_PUBLISH_STATUSES for status in statuses):
        final_status = "published"
        final_status_zh = "发布成功"
    elif statuses and any(status in FINAL_FAILURE_PUBLISH_STATUSES for status in statuses):
        final_status = "failed"
        final_status_zh = "发布失败"
    elif tasks:
        final_status = "submitted"
        final_status_zh = "已提交发布任务"

    failure_reason = _novel_publish_failure_reason(records, tasks)
    if tasks and (not statuses or any(status in RUNNING_PUBLISH_STATUSES for status in statuses)):
        final_status = "submitted"
        final_status_zh = "发布处理中"
        failure_reason = failure_reason or NOVEL_PUBLISH_IN_PROGRESS_REASON

    return {
        **publish_payload,
        "tasks": tasks,
        "records": records,
        "final_status": final_status,
        "final_status_zh": final_status_zh,
        "failure_reason": failure_reason,
        "account_names": account_names,
        "record_statuses": statuses,
        "post_ids": [str(record.get("post_id") or "") for record in records if str(record.get("post_id") or "").strip()],
        "post_dates": [str(record.get("post_date") or "") for record in records if str(record.get("post_date") or "").strip()],
    }


def _publish_novel_video(args, result, novel=None, promotion=None):
    account_ids = split_cli_values(getattr(args, "account_id", None))
    team_ids = split_cli_values(getattr(args, "team_id", None))
    account_pool = str(getattr(args, "account_pool", "") or "").strip()
    publish_platform = resolve_novel_publish_platform(args)
    if publish_platform == "FACEBOOK" and not account_ids and not team_ids and not account_pool:
        account_pool = DEFAULT_NOVEL_FACEBOOK_ACCOUNT_POOL
    if not account_ids and not team_ids and not account_pool:
        accounts = require_success(get_publish_accounts(), "获取发布账号")
        choices = [
            {
                "序号": index + 1,
                "平台": PUBLISH_SOCIAL_NAMES.get(str(account.get("type") or ""), str(account.get("type") or "")),
                "账号": account.get("social_name") or str(account.get("type") or "账号"),
            }
            for index, account in enumerate(accounts)
            if str(account.get("type") or "").upper() == publish_platform and int(account.get("status") or 0) == 0
        ]
        raise InbeidouError(
            f"小说视频发布到 {PUBLISH_SOCIAL_NAMES.get(publish_platform, publish_platform)} 前必须先选择账号"
            f"{'或账号池' if account_pool else ''}: "
            + json.dumps(choices, ensure_ascii=False)
        )

    data = result.get("data") or {}
    video_url = str(data.get("video_url") or "").strip()
    local_video_file = str(data.get("local_video_file") or "").strip()
    if not video_url and not local_video_file:
        raise InbeidouError("小说视频结果没有 video_url，无法发布")
    novel = dict(novel or {})
    novel_title = str(novel.get("title") or getattr(args, "search", "") or "novel_video")
    task_id = str(data.get("task_id") or result.get("task_id") or "").strip()
    if local_video_file:
        local_video_file = str(Path(local_video_file).expanduser().resolve())
    else:
        local_video_file = _download_novel_publish_video(video_url, novel_title, task_id=task_id)
    promotion = dict(promotion or {})
    default_text = str(promotion.get("caption") or "").strip()
    if not str(getattr(args, "text", "") or "").strip() and not default_text:
        raise InbeidouError("详情页未返回可发布推广文案")
    text = str(getattr(args, "text", "") or "").strip() or default_text
    publish_args = argparse.Namespace(
        account_id=account_ids,
        team_id=team_ids,
        account_pool=account_pool,
        platform=publish_platform,
        text=text,
        text_file=getattr(args, "text_file", None),
        file=local_video_file,
        file_url="",
        schedule_at=None,
    )
    payload, target = build_publish_payload(publish_args)
    body = require_success(create_publish_post(payload), "发布小说视频")
    return {
        "payload": payload,
        "target": target,
        "result": body,
        "local_video_file": local_video_file,
        "source_video_url": video_url,
        "promotion": promotion,
    }


def _resolve_novel_publish_target_accounts(args, publish_platform):
    account_pool = str(getattr(args, "account_pool", "") or "").strip()
    if publish_platform == "FACEBOOK" and not account_pool and not getattr(args, "account_id", None) and not getattr(args, "team_id", None):
        account_pool = DEFAULT_NOVEL_FACEBOOK_ACCOUNT_POOL
    target_args = argparse.Namespace(
        account_id=getattr(args, "account_id", None),
        team_id=getattr(args, "team_id", None),
        account_pool=account_pool,
        platform=publish_platform,
    )
    target = resolve_publish_targets(target_args)
    accounts = target.get("accounts") or []
    if accounts:
        return target["social_type"], accounts
    team_ids = target.get("team_ids") or []
    return target["social_type"], [{"team_id": value} for value in team_ids]


def _build_novel_item_args(args, *, account=None):
    account_id = str(account.get("id") or "").strip() if isinstance(account, dict) else ""
    team_id = str(account.get("team_id") or "").strip() if isinstance(account, dict) else ""
    generation_chain = NOVEL_GENERATION_CHAIN_VIDU_IMAGE
    return argparse.Namespace(
        action=args.action,
        task_id=getattr(args, "task_id", ""),
        app_id=getattr(args, "app_id", ""),
        platform=getattr(args, "platform", ""),
        language=getattr(args, "language", ""),
        search=getattr(args, "search", ""),
        page=getattr(args, "page", 1),
        size=getattr(args, "size", 15),
        order=getattr(args, "order", "publish_at"),
        full_text=getattr(args, "full_text", False),
        generator=getattr(args, "generator", ""),
        prompt=getattr(args, "prompt", ""),
        timeout=getattr(args, "timeout", DEFAULT_TASK_TIMEOUT),
        poll_interval=getattr(args, "poll_interval", DEFAULT_POLL_INTERVAL),
        vidu_model=getattr(args, "vidu_model", DEFAULT_NOVEL_VIDEO_MODEL),
        vidu_duration=getattr(args, "vidu_duration", DEFAULT_NOVEL_VIDU_DURATION),
        vidu_aspect_ratio=getattr(args, "vidu_aspect_ratio", "9:16"),
        vidu_resolution=getattr(args, "vidu_resolution", DEFAULT_NOVEL_VIDU_RESOLUTION),
        vidu_off_peak=getattr(args, "vidu_off_peak", False),
        vidu_watermark=getattr(args, "vidu_watermark", False),
        generation_chain=generation_chain,
        execute=getattr(args, "execute", False),
        publish=getattr(args, "publish", False),
        publish_platform=getattr(args, "publish_platform", ""),
        account_pool="",
        account_id=[account_id] if account_id else [],
        team_id=[team_id] if team_id else [],
        text=getattr(args, "text", ""),
        text_file=getattr(args, "text_file", None),
        exclude_task_ids=[],
    )


def _novel_batch_report_zh(items, publish_platform):
    total = len(items)
    generated = sum(1 for item in items if item.get("status") == "generated")
    dry_run = sum(1 for item in items if item.get("status") == "dry_run")
    published = sum(1 for item in items if item.get("publish_status") == "published")
    failed = sum(1 for item in items if item.get("status") == "failed")
    return {
        "目标平台": PUBLISH_SOCIAL_NAMES.get(publish_platform, publish_platform),
        "计划小说数": total,
        "已生成": generated,
        "dry_run": dry_run,
        "已发布": published,
        "失败": failed,
        "任务明细": items,
    }


def _novel_batch_user_summary_zh(report):
    lines = [
        f"本轮小说批量任务目标平台 {report.get('目标平台')}，计划 {report.get('计划小说数', 0)} 条，"
        f"已生成 {report.get('已生成', 0)} 条，已发布 {report.get('已发布', 0)} 条，失败 {report.get('失败', 0)} 条。"
    ]
    detail_rows = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
    if detail_rows:
        lines.append("任务明细：")
        for index, item in enumerate(detail_rows, start=1):
            account_label = str(item.get("account") or item.get("team_id") or "未指定账号")
            title = str(item.get("title") or "")
            status = str(item.get("publish_status") or item.get("status") or "")
            detail = f"{index}. {account_label} -> {title} -> {status}"
            if str(item.get("failure_reason") or "").strip():
                detail += f" ({item.get('failure_reason')})"
            lines.append(detail)
    return "\n".join(lines)


def _single_novel_user_summary_zh(payload: dict) -> str:
    novel = payload.get("novel") or {}
    title = str(novel.get("title") or novel.get("title_ch") or "小说")
    if payload.get("status") == "dry_run":
        generation = payload.get("generation") or {}
        return (
            f"已完成小说 dry-run：《{title}》已选定，"
            f"生成器 {generation.get('generator')}，"
            f"目标平台 {PUBLISH_SOCIAL_NAMES.get(generation.get('publish_platform'), generation.get('publish_platform'))}。"
        )
    if not payload.get("publish"):
        return f"小说视频已生成：《{title}》。"
    publish = payload.get("publish") or {}
    promotion = payload.get("promotion") if isinstance(payload.get("promotion"), dict) else {}
    account_names = "、".join(publish.get("account_names") or []) or "目标账号"
    status_zh = str(payload.get("publish_status_zh") or publish.get("final_status_zh") or "已提交发布任务")
    post_ids = "、".join(publish.get("post_ids") or [])
    failure_reason = str(publish.get("failure_reason") or "").strip()
    line = f"《{title}》已发布到 {account_names}，最终结果：{status_zh}。"
    if str(promotion.get("promotion_link") or "").strip():
        line += f" 推广链接：{promotion.get('promotion_link')}。"
    if post_ids:
        line += f" 帖子ID：{post_ids}。"
    if failure_reason:
        line += f" 原因：{failure_reason}"
    return line


def _novel_generation_chain_zh(value: str) -> str:
    mapping = {
        NOVEL_GENERATION_CHAIN_VIDU_IMAGE: "官方 Vidu 生图+图生视频",
    }
    return mapping.get(str(value or "").strip(), str(value or "").strip() or "-")


def _novel_duration_text(seconds_value) -> str:
    try:
        seconds = float(seconds_value or 0)
    except (TypeError, ValueError):
        seconds = 0
    return format_seconds(seconds) if seconds > 0 else "-"


def _single_novel_report_zh(payload: dict) -> dict:
    novel = payload.get("novel") if isinstance(payload.get("novel"), dict) else {}
    generation = payload.get("generation") if isinstance(payload.get("generation"), dict) else {}
    video_data = ((payload.get("video") or {}).get("data") if isinstance(payload.get("video"), dict) else {}) or {}
    publish = payload.get("publish") if isinstance(payload.get("publish"), dict) else {}
    account_names = "、".join(publish.get("account_names") or []) or "未指定账号"
    detail_row = {
        "序号": 1,
        "账号": account_names,
        "小说": str(novel.get("title") or novel.get("title_ch") or "小说"),
        "生成链路": _novel_generation_chain_zh(generation.get("generation_chain")),
        "段数": int(video_data.get("segment_count") or 0),
        "视频时长": _novel_duration_text(video_data.get("final_duration") or video_data.get("target_total_duration") or video_data.get("total_duration")),
        "发布状态": str(payload.get("publish_status_zh") or publish.get("final_status_zh") or payload.get("status") or "-"),
        "失败原因": str(publish.get("failure_reason") or ""),
        "推广链接": str(((payload.get("promotion") or {}).get("promotion_link")) or ""),
    }
    published = 1 if payload.get("publish_status") == "published" else 0
    failed = 1 if payload.get("status") == "failed" or payload.get("publish_status") == "failed" else 0
    generated = 1 if payload.get("status") in {"generated", "failed"} else 0
    return {
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "环境": "正式环境" if str(API_ENV or "").strip().lower() in {"prod", "production"} else "测试环境",
        "执行模式": "小说手动测试",
        "目标平台": PUBLISH_SOCIAL_NAMES.get(str(generation.get("publish_platform") or ""), str(generation.get("publish_platform") or "")),
        "计划小说数": 1,
        "已生成": generated,
        "已发布": published,
        "失败": failed,
        "任务明细": [detail_row],
    }


def _enrich_novel_batch_report(payload: dict) -> dict:
    report = dict(payload.get("report_zh") or {})
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    enriched_rows = []
    for index, item in enumerate(items, start=1):
        raw_payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        video_data = ((raw_payload.get("video") or {}).get("data") if isinstance(raw_payload.get("video"), dict) else {}) or {}
        enriched_rows.append(
            {
                "序号": index,
                "账号": str(item.get("account") or "未指定账号"),
                "小说": str(item.get("title") or ""),
                "生成链路": _novel_generation_chain_zh(item.get("generation_chain")),
                "段数": int(video_data.get("segment_count") or 0),
                "视频时长": _novel_duration_text(video_data.get("final_duration") or video_data.get("target_total_duration") or video_data.get("total_duration")),
                "发布状态": str(item.get("publish_status_zh") or item.get("publish_status") or item.get("status") or "-"),
                "失败原因": str(item.get("failure_reason") or item.get("error") or ""),
                "推广链接": str(item.get("promotion_link") or ""),
            }
        )
    report["生成时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report["环境"] = "正式环境" if str(API_ENV or "").strip().lower() in {"prod", "production"} else "测试环境"
    report["执行模式"] = "小说手动批量测试"
    report["任务明细"] = enriched_rows
    return report


def _novel_report_markdown(payload: dict) -> str:
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    generated_at = str(report.get("生成时间") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines = [
        f"# 小说测试报告（{generated_at}）",
        "",
        f"- 执行模式：{report.get('执行模式') or '小说手动测试'}",
        f"- 环境：{report.get('环境') or '-'}",
        f"- 目标平台：{report.get('目标平台') or '-'}",
        f"- 计划小说数：{report.get('计划小说数') or 0}",
        f"- 已生成：{report.get('已生成') or 0}",
        f"- 已发布：{report.get('已发布') or 0}",
        f"- 失败：{report.get('失败') or 0}",
        "",
        "## 执行总结",
        "",
    ]
    summary = str(payload.get("user_summary_zh") or "").strip()
    if summary:
        lines.extend(summary.splitlines())
    else:
        lines.append("- 暂无")
    rows = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
    lines.extend(["", "## 任务明细", ""])
    if rows:
        headers = ["序号", "账号", "小说", "生成链路", "段数", "视频时长", "发布状态", "失败原因", "推广链接"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in rows:
            lines.append(
                "| "
                + " | ".join(
                    str(row.get(key) if row.get(key) not in (None, "") else "-").replace("|", "\\|").replace("\n", "<br>")
                    for key in headers
                )
                + " |"
            )
    else:
        lines.append("- 暂无")
    return "\n".join(lines).rstrip() + "\n"


def _maybe_write_novel_test_summary(payload: dict) -> dict:
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    if not report:
        return {}
    existing_files = payload.get("test_report_files") if isinstance(payload.get("test_report_files"), dict) else {}
    existing_markdown = str(existing_files.get("markdown") or "").strip()
    if existing_markdown and Path(existing_markdown).expanduser().exists():
        return {"test_report_files": existing_files}
    report_dir = _novel_test_summary_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    date_key = datetime.now().strftime("%Y%m%d_%H%M%S")
    markdown_path = report_dir / f"小说测试报告_{date_key}.md"
    markdown_path.write_text(_novel_report_markdown(payload), encoding="utf-8")
    return {
        "test_report_files": {
            "directory": str(report_dir),
            "markdown": str(markdown_path),
        }
    }


def _novel_feishu_message_text(payload: dict) -> str:
    files = payload.get("test_report_files") if isinstance(payload.get("test_report_files"), dict) else {}
    markdown = str(files.get("markdown") or "").strip()
    if markdown:
        path = Path(markdown).expanduser()
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return _novel_report_markdown(payload).strip()


def _maybe_push_novel_feishu_test_report(payload: dict) -> dict:
    if not _novel_feishu_push_enabled():
        return {}
    if not isinstance(payload.get("test_report_files"), dict):
        return {}
    existing_push = payload.get("test_feishu_push") if isinstance(payload.get("test_feishu_push"), dict) else {}
    if str(existing_push.get("message_id") or "").strip():
        return {"test_feishu_push": existing_push}
    tenant_token = _feishu_get_tenant_access_token()
    receive_id_type, receive_id = _feishu_receive_target()
    push_mode = "interactive"
    try:
        message = _feishu_send_interactive_message(
            tenant_token,
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            card=build_novel_test_feishu_card(payload),
        )
    except Exception:
        push_mode = "text"
        message = _feishu_send_text_message(
            tenant_token,
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            text=_novel_feishu_message_text(payload),
        )
    return {
        "test_feishu_push": {
            "enabled": True,
            "mode": push_mode,
            "receive_id_type": receive_id_type,
            "receive_id": receive_id,
            "message_id": str(message.get("message_id") or ""),
        }
    }


def _schedule_novel_followup_report(payload: dict, *, delay_seconds: int = DEFAULT_NOVEL_PUBLISH_FOLLOWUP_DELAY) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("publish"), dict):
        return {}
    existing_followup = payload.get("followup_report") if isinstance(payload.get("followup_report"), dict) else {}
    if existing_followup.get("scheduled") and str(existing_followup.get("payload_file") or "").strip():
        return {"followup_report": existing_followup}
    followup_dir = _novel_work_dir("随访")
    payload_file = followup_dir / f"novel_followup_{int(time.time())}.json"
    payload_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "novels",
        "followup-report",
        "--payload-file",
        str(payload_file),
        "--delay-seconds",
        str(max(0, int(delay_seconds))),
    ]
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {
        "followup_report": {
            "scheduled": True,
            "delay_seconds": max(0, int(delay_seconds)),
            "payload_file": str(payload_file),
        }
    }


def _finalize_novel_payload(payload: dict) -> dict:
    try:
        files = _maybe_write_novel_test_summary(payload)
        if files:
            payload.update(files)
    except Exception as exc:
        payload["test_report_files"] = {"error": str(exc)}
    try:
        payload.update(_maybe_push_novel_feishu_test_report(payload))
    except Exception as exc:
        payload["test_feishu_push"] = {"enabled": True, "error": str(exc)}
    return payload


def _refresh_novel_publish_once(publish_payload: dict) -> dict:
    payload = publish_payload.get("payload") if isinstance(publish_payload.get("payload"), dict) else {}
    target = publish_payload.get("target") if isinstance(publish_payload.get("target"), dict) else {}
    result = publish_payload.get("result") if isinstance(publish_payload.get("result"), dict) else {}
    tasks = result.get("tasks") if isinstance(result.get("tasks"), list) else []
    platform = str(payload.get("social_type") or "").upper()
    records = _poll_publish_records(
        platform=platform,
        tasks=tasks,
        wait_seconds=0,
        poll_interval=1,
    ) if tasks else []
    statuses = [
        str(record.get("status") or task.get("status") or "").upper()
        for record, task in zip(records, tasks)
        if str(record.get("status") or task.get("status") or "").strip()
    ]
    account_names = [
        str(record.get("social_name") or "").strip()
        for record in records
        if str(record.get("social_name") or "").strip()
    ]
    if not account_names:
        account_names = [
            str(account.get("social_name") or account.get("name") or "").strip()
            for account in (target.get("accounts") or [])
            if str(account.get("social_name") or account.get("name") or "").strip()
        ]
    final_status = "submitted"
    final_status_zh = "发布处理中"
    if any(status in SUCCESSFUL_PUBLISH_STATUSES for status in statuses):
        final_status = "published"
        final_status_zh = "发布成功"
    elif statuses and any(status in FINAL_FAILURE_PUBLISH_STATUSES for status in statuses):
        final_status = "failed"
        final_status_zh = "发布失败"
    failure_reason = _novel_publish_failure_reason(records, tasks)
    if final_status == "submitted":
        failure_reason = failure_reason or NOVEL_PUBLISH_IN_PROGRESS_REASON
    return {
        **publish_payload,
        "tasks": tasks,
        "records": records,
        "final_status": final_status,
        "final_status_zh": final_status_zh,
        "failure_reason": failure_reason if final_status != "published" else "",
        "account_names": account_names,
        "record_statuses": statuses,
        "post_ids": [str(record.get("post_id") or "") for record in records if str(record.get("post_id") or "").strip()],
        "post_dates": [str(record.get("post_date") or "") for record in records if str(record.get("post_date") or "").strip()],
    }


def _run_novel_followup_report(payload_file: str, delay_seconds: int) -> dict:
    path = Path(payload_file).expanduser()
    payload = json.loads(path.read_text(encoding="utf-8"))
    existing_followup = payload.get("followup_report") if isinstance(payload.get("followup_report"), dict) else {}
    if existing_followup.get("completed_at"):
        return payload
    time.sleep(max(0, int(delay_seconds)))
    if isinstance(payload.get("publish"), dict):
        payload["publish"] = _refresh_novel_publish_once(payload["publish"])
        payload["publish_status"] = payload["publish"].get("final_status")
        payload["publish_status_zh"] = payload["publish"].get("final_status_zh")
    payload = _maybe_cleanup_novel_outputs_after_publish(payload)
    if payload.get("mode") == "batch_novel":
        payload["report_zh"] = _enrich_novel_batch_report(payload)
    else:
        payload["report_zh"] = _single_novel_report_zh(payload)
        payload["mode"] = payload.get("mode") or "novel_video"
    payload["user_summary_zh"] = _single_novel_user_summary_zh(payload) if payload.get("mode") == "novel_video" else _novel_batch_user_summary_zh(payload.get("report_zh") or {})
    payload = _finalize_novel_payload(payload)
    payload["followup_report"] = {
        **existing_followup,
        "scheduled": True,
        "delay_seconds": max(0, int(delay_seconds)),
        "payload_file": str(path),
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _run_single_novel_pipeline_with_novel(args, novel):
    chapter = _chapter_payload(novel)
    publish_platform = resolve_novel_publish_platform(args)
    generation_account = None
    if getattr(args, "publish", False):
        _, target_accounts = _resolve_novel_publish_target_accounts(args, publish_platform)
        generation_account = target_accounts[0] if target_accounts else None
    promotion = None
    if getattr(args, "publish", False):
        promotion = _novel_promotion_caption(novel, publish_platform)
    payload = {
        "novel": task_summary(novel),
        "chapter": {
            **chapter,
            **({} if getattr(args, "full_text", False) else {"text": ""}),
        },
    }
    if promotion:
        payload["promotion"] = promotion
    plan = _novel_generation_plan(args, novel, chapter, promotion=promotion, account=generation_account)
    payload["generation"] = {
        "generator": plan["generator"],
        "generation_chain": plan["generation_chain"],
        "publish_platform": plan["publish_platform"],
        "prompt": plan["prompt"],
        "text_length": len(plan["novel_text"]),
        "vidu_model": plan["vidu_model"],
        "vidu_duration": plan["vidu_duration"],
        "vidu_aspect_ratio": plan["vidu_aspect_ratio"],
        "vidu_resolution": plan["vidu_resolution"],
        "vidu_off_peak": plan["vidu_off_peak"],
        "vidu_watermark": plan["vidu_watermark"],
    }
    if not args.execute:
        payload["status"] = "dry_run"
        payload["message"] = "已选好小说并取到免费章节。传 --execute 才会真正生成小说视频。"
        return payload

    result = submit_novel_video_task(
        timeout=args.timeout,
        poll_interval=getattr(args, "poll_interval", DEFAULT_POLL_INTERVAL),
        **plan,
    )
    payload["status"] = "generated"
    payload["video"] = result
    if getattr(args, "publish", False):
        payload["publish"] = _settle_novel_publish(
            args,
            _publish_novel_video(args, result, novel=novel, promotion=payload.get("promotion")),
        )
        payload["publish_status"] = payload["publish"].get("final_status")
        payload["publish_status_zh"] = payload["publish"].get("final_status_zh")
        if payload["publish_status"] == "failed":
            payload["status"] = "failed"
        payload = _maybe_cleanup_novel_outputs_after_publish(payload)
    payload["user_summary_zh"] = _single_novel_user_summary_zh(payload)
    return payload


def _run_single_novel_pipeline(args):
    novel = resolve_novel(args)
    return _run_single_novel_pipeline_with_novel(args, novel)


def _run_batch_novel_pipeline(args):
    count = max(1, int(getattr(args, "count", 1) or 1))
    publish_platform = resolve_novel_publish_platform(args)
    target_accounts = []
    if getattr(args, "publish", False):
        _, target_accounts = _resolve_novel_publish_target_accounts(args, publish_platform)
        if not target_accounts:
            raise InbeidouError(
                f"未找到可用的 {PUBLISH_SOCIAL_NAMES.get(publish_platform, publish_platform)} 发布账号"
            )
    used_task_ids = []
    items = []
    target_success = max(1, math.ceil(count * NOVEL_BATCH_TARGET_SUCCESS_RATE)) if getattr(args, "publish", False) else count
    success_count = 0
    account_count = len(target_accounts)
    selection_lock = Lock()
    success_lock = Lock()
    batch_concurrency = max(1, min(count, int(os.getenv("BARRY_VIDEO_NOVEL_BATCH_CONCURRENCY", DEFAULT_NOVEL_BATCH_CONCURRENCY) or DEFAULT_NOVEL_BATCH_CONCURRENCY)))

    def _account_labels(account: Optional[Dict]) -> Tuple[str, str]:
        if not isinstance(account, dict):
            return "", ""
        account_name = str(account.get("social_name") or "")
        channels = account.get("channels") or []
        if channels and not account_name:
            account_name = str(channels[0].get("name") or "")
        return account_name, str(account.get("team_id") or "")

    def _item_succeeded(payload_or_item: dict) -> bool:
        if getattr(args, "publish", False):
            return str(payload_or_item.get("publish_status") or "") == "published"
        return str(payload_or_item.get("status") or "") == "generated"

    def _reserve_novel_for_attempt(item_args):
        with selection_lock:
            reserve_args = argparse.Namespace(**vars(item_args))
            reserve_args.exclude_task_ids = list(used_task_ids)
            novel = resolve_novel(reserve_args)
            task_id = str((novel or {}).get("task_id") or "").strip()
            if task_id and task_id not in used_task_ids:
                used_task_ids.append(task_id)
            return novel

    def _run_one_batch_item(index):
        account = target_accounts[index % account_count] if account_count else None
        account_name, team_id = _account_labels(account)
        final_item = None
        for attempt in range(1, NOVEL_BATCH_MAX_RETRIES_PER_ACCOUNT + 1):
            item_args = _build_novel_item_args(args, account=account)
            try:
                novel = _reserve_novel_for_attempt(item_args)
                payload = _run_single_novel_pipeline_with_novel(item_args, novel)
                final_item = {
                    "index": index + 1,
                    "attempt": attempt,
                    "title": (payload.get("novel") or {}).get("title") or "",
                    "task_id": (payload.get("novel") or {}).get("task_id"),
                    "platform": publish_platform,
                    "account": account_name,
                    "team_id": team_id,
                    "status": payload.get("status"),
                    "publish_status": payload.get("publish_status") or ("published" if payload.get("publish") else payload.get("status")),
                    "publish_status_zh": payload.get("publish_status_zh") or "",
                    "failure_reason": ((payload.get("publish") or {}).get("failure_reason") or ""),
                    "post_ids": ((payload.get("publish") or {}).get("post_ids") or []),
                    "post_dates": ((payload.get("publish") or {}).get("post_dates") or []),
                    "promotion_link": (((payload.get("promotion") or {}).get("promotion_link")) or ""),
                    "generator": (payload.get("generation") or {}).get("generator"),
                    "generation_chain": (payload.get("generation") or {}).get("generation_chain"),
                    "payload": payload,
                }
                if _item_succeeded(final_item):
                    with success_lock:
                        nonlocal success_count
                        success_count += 1
                    break
            except Exception as exc:
                final_item = {
                    "index": index + 1,
                    "attempt": attempt,
                    "title": "",
                    "task_id": "",
                    "platform": publish_platform,
                    "account": account_name,
                    "team_id": team_id,
                    "status": "failed",
                    "publish_status": "failed",
                    "generator": resolve_novel_generator(args),
                    "generation_chain": str(getattr(item_args, "generation_chain", "") or ""),
                    "error": str(exc),
                    "failure_reason": str(exc),
                }
        return final_item or {
            "index": index + 1,
            "attempt": 0,
            "title": "",
            "task_id": "",
            "platform": publish_platform,
            "account": account_name,
            "team_id": team_id,
            "status": "failed",
            "publish_status": "failed",
            "generator": resolve_novel_generator(args),
            "generation_chain": "",
            "error": "未生成结果",
            "failure_reason": "未生成结果",
        }

    ordered_results = []
    with ThreadPoolExecutor(max_workers=batch_concurrency) as executor:
        futures = {executor.submit(_run_one_batch_item, index): index for index in range(count)}
        for future in as_completed(futures):
            ordered_results.append((futures[future], future.result()))
    ordered_results.sort(key=lambda item: item[0])
    items.extend(result for _, result in ordered_results)

    report = _novel_batch_report_zh(items, publish_platform)
    report["目标成功率"] = f"{NOVEL_BATCH_TARGET_SUCCESS_RATE * 100:.0f}%"
    report["实际成功率"] = f"{(success_count / count * 100):.0f}%" if count > 0 else "0%"
    report["成功条数"] = success_count
    report["账号数"] = account_count
    if account_count > 0:
        report["平均每账号条数"] = math.ceil(count / account_count)
    return {
        "mode": "batch_novel",
        "count": count,
        "batch_concurrency": batch_concurrency,
        "publish_platform": publish_platform,
        "account_pool": getattr(args, "account_pool", ""),
        "items": items,
        "report_zh": report,
        "user_summary_zh": _novel_batch_user_summary_zh(report),
    }


def _novel_generation_plan(args, novel, chapter, promotion=None, account=None):
    title = novel.get("title") or novel.get("title_ch") or "小说"
    generator = resolve_novel_generator(args)
    publish_platform = resolve_novel_publish_platform(args)
    prompt = build_vidu_prompt(chapter, getattr(args, "prompt", ""))
    generation_chain = NOVEL_GENERATION_CHAIN_VIDU_IMAGE
    return {
        "title": title,
        "generator": generator,
        "generation_chain": generation_chain,
        "publish_platform": publish_platform,
        "novel_text": chapter.get("text") or "",
        "chapter": chapter,
        "app_id": novel.get("app_id"),
        "task_id": novel.get("task_id"),
        "prompt": prompt,
        "vidu_model": getattr(args, "vidu_model", DEFAULT_NOVEL_VIDEO_MODEL),
        "vidu_duration": int(getattr(args, "vidu_duration", DEFAULT_NOVEL_VIDU_DURATION) or 0),
        "vidu_aspect_ratio": getattr(args, "vidu_aspect_ratio", "9:16"),
        "vidu_resolution": getattr(args, "vidu_resolution", DEFAULT_NOVEL_VIDU_RESOLUTION),
        "vidu_off_peak": bool(getattr(args, "vidu_off_peak", False)),
        "vidu_watermark": bool(getattr(args, "vidu_watermark", False)),
    }


def cmd_novels(args):
    if args.action == "quota":
        body = require_success(get_novel_quota(), "获取小说生成额度")
        if args.json:
            pretty_print_json(body)
            return
        print("\n📖 小说生成额度")
        print("=" * 60)
        print(f"   今日已用: {body.get('novel_usage_count', 0)}")
        print(f"   积分总额: {body.get('credit_total', 0)}")
        print(f"   今日消耗: {body.get('consumed_credit_today', 0)}")
        return

    if args.action == "list":
        body = require_body_dict(
            require_success(
                list_novel_tasks(
                    page=args.page,
                    page_size=args.size,
                    platform=args.platform,
                    language=args.language,
                    search=args.search,
                    order=args.order,
                ),
                "获取小说库",
            ),
            "获取小说库",
        )
        if args.json:
            pretty_print_json(body)
            return
        items = body.get("data", [])
        total = (body.get("page") or {}).get("total_count", 0)
        print(f"\n共找到 {total} 本小说")
        for item in items:
            format_novel(item)
        return

    if args.action in {"random", "chapter", "generate", "pipeline"}:
        if args.action in {"random", "chapter"}:
            novel = resolve_novel(args)
            chapter = _chapter_payload(novel)
            payload = {
                "novel": task_summary(novel),
                "chapter": {
                    **chapter,
                    **({} if getattr(args, "full_text", False) else {"text": ""}),
                },
            }
            if args.json:
                pretty_print_json(payload)
                return
            format_novel(novel)
            print(f"\n章节内容长度: {chapter['text_length']} 字")
            print(f"章节预览: {chapter['text_preview']}")
            print(f"可选配音: {', '.join(item.get('name', '') for item in chapter.get('timbre', [])[:8])}")
            return

        count = max(1, int(getattr(args, "count", 1) or 1))
        if count > 1:
            payload = _run_batch_novel_pipeline(args)
            if getattr(args, "execute", False):
                if getattr(args, "publish", False):
                    payload.update(_schedule_novel_followup_report(payload))
                else:
                    payload["report_zh"] = _enrich_novel_batch_report(payload)
                    payload = _finalize_novel_payload(payload)
            if args.json:
                pretty_print_json(payload)
                return
            print(payload.get("user_summary_zh") or "")
            return

        payload = _run_single_novel_pipeline(args)
        if getattr(args, "execute", False):
            payload["mode"] = "novel_video"
            if getattr(args, "publish", False):
                payload.update(_schedule_novel_followup_report(payload))
            else:
                payload["report_zh"] = _single_novel_report_zh(payload)
                payload = _finalize_novel_payload(payload)
        if args.json:
            pretty_print_json(payload)
            return
        novel = payload.get("novel") or {}
        generation = payload.get("generation") or {}
        format_novel(novel)
        if payload.get("status") == "dry_run":
            print("\n已完成 dry-run：未生成视频、未发布。")
            print(f"生成器: {generation.get('generator')}")
            print(f"发布平台: {generation.get('publish_platform')}")
            print(f"章节长度: {generation.get('text_length')} 字")
            return
        video = payload.get("video") or {}
        video_url = (video.get("data") or {}).get("video_url") or ""
        print("\n小说视频生成完成")
        print(f"生成器: {generation.get('generator')}")
        print(f"视频: {video_url}")
        if getattr(args, "publish", False):
            print(payload.get("user_summary_zh") or "")
        return

    if args.action == "followup-report":
        payload = _run_novel_followup_report(args.payload_file, args.delay_seconds)
        if args.json:
            pretty_print_json(payload)
        return

    raise InbeidouError(f"不支持的 novels action: {args.action}")


def cmd_list(args):
    result = get_tasks(
        page=args.page,
        page_size=args.size,
        platform=args.platform,
        language=args.language,
        search=args.search,
        order=args.order,
    )
    body = require_success(result, "获取短剧列表")
    items = body.get("data", [])
    page_info = body.get("page", {})
    total = page_info.get("total_count", 0)

    if getattr(args, "json", False):
        pretty_print_json(body)
        return

    print(f"\n共找到 {total} 个短剧")
    if not items:
        print("暂无数据")
        return

    for item in items:
        format_drama(item)

    current = page_info.get("current_page", args.page)
    total_pages = max(1, math.ceil(total / args.size)) if args.size else 1
    print(f"\n{'=' * 60}")
    print(f"第 {current} / {total_pages} 页")


def cmd_detail(args):
    item = resolve_task_for_detail(args)
    promotion_links = []
    if not args.no_promotion_links:
        for platform_id in normalize_promotion_platforms(args.promote_platforms, include_all=args.all_promote_platforms):
            payload = require_success(
                receive_task(task_id=item["task_id"], task_type=item.get("task_type", args.task_type), platform=platform_id),
                f"获取 {PROMOTION_PLATFORMS[platform_id]} 推广链接",
            )
            promotion_links.append(build_promotion_link_entry(platform_id, payload))

    result = {
        **item,
        "promotion_links": promotion_links,
    }

    if getattr(args, "json", False):
        pretty_print_json(result)
        return

    format_drama(item)
    print(f"   serial_id: {item.get('serial_id', 'N/A')}")
    print(f"   third_serial_id: {item.get('third_serial_id', 'N/A')}")
    print("   简介:")
    print(f"   {item.get('description', '') or 'N/A'}")

    if args.no_promotion_links:
        return

    print(f"\n{'=' * 60}")
    print("推广链接")
    print(f"{'=' * 60}")
    if not promotion_links:
        print("暂无推广链接")
        return

    for entry in promotion_links:
        print(f"\n[{entry['platform_name']}]")
        print(f"  app_link: {entry.get('app_link') or 'N/A'}")
        print(f"  serial_link: {entry.get('serial_link') or 'N/A'}")
        print(f"  code: {entry.get('code') or 'N/A'}")
        if entry.get("tiktok_dramago_link"):
            print(f"  tiktok_dramago_link: {entry['tiktok_dramago_link']}")
        if entry.get("tiktok_url"):
            print(f"  tiktok_url: {entry['tiktok_url']}")
        if entry.get("promote_code_content"):
            print("  promote_code_content:")
            print(f"  {entry['promote_code_content']}")


def cmd_episodes(args):
    locator = resolve_drama_locator(args, require_app=(args.action == "fetch"))
    if args.action == "list":
        body = require_success(
            get_episode_list(
                serial_id=locator["serial_id"],
                episode_orders=args.episode_orders or "",
                start=args.start,
                end=args.end,
                need_play=1,
                video_type=args.video_type or "",
            ),
            "获取短剧剧集列表",
        )
        rows = body if isinstance(body, list) else []
        requested_orders = {
            int(part.strip())
            for part in (args.episode_orders or "").split(",")
            if part.strip().isdigit()
        }
        def row_order(item):
            return int(item.get("episode_order") or item.get("episode_id") or item.get("sequence") or 0)
        if requested_orders:
            rows = [item for item in rows if row_order(item) in requested_orders]
        if args.start is not None:
            rows = [item for item in rows if row_order(item) >= int(args.start)]
        if args.end is not None:
            rows = [item for item in rows if row_order(item) <= int(args.end)]
        result = {"task": locator, "episodes": rows}
        if getattr(args, "json", False):
            pretty_print_json(result)
            return
        if locator.get("title"):
            print(f"\n剧名: {locator['title']}")
        print(f"serial_id: {locator['serial_id']}")
        if not rows:
            print("暂无剧集数据")
            return
        describe_episode_rows(rows)
        return

    context = resolve_drama_episode_context(args)
    if getattr(args, "json", False):
        pretty_print_json(context)
        return
    print("\n✅ 短剧剧集素材已就绪")
    print("=" * 80)
    print(f"   标题: {context.get('title') or 'N/A'}")
    print(f"   第 {context.get('episode_order')} 集")
    print(f"   upload_id: {context.get('upload_id')}")
    print(f"   window_id: {context.get('window_id')}")
    print(f"   media_url: {context.get('media_url') or 'N/A'}")


def cmd_uploads(args):
    if args.action == "list":
        body = require_success(get_uploads(page=args.page, page_size=args.size), "获取媒资库列表")
        items = body.get("items", [])
        total = body.get("page", {}).get("total_count", 0)

        if getattr(args, "json", False):
            pretty_print_json(body)
            return

        print(f"\n📁 媒资库视频 (共 {total} 个)")
        print("=" * 110)
        print(f"{'ID':<8} {'文件名':<36} {'方向':<10} {'时长':<10} {'大小':<12} {'状态':<12} {'上传时间'}")
        print("-" * 110)
        for item in items:
            size_value = item.get("file_size") or item.get("size")
            print(
                f"{item.get('id', ''):<8} "
                f"{str(item.get('filename', '未知'))[:34]:<36} "
                f"{str(item.get('orientation', '')):<10} "
                f"{format_seconds(item.get('file_duration', 0)):<10} "
                f"{(format_size(size_value) if size_value else '-'): <12} "
                f"{str(item.get('status', '')):<12} "
                f"{str(item.get('created_at', ''))[:19]}"
            )

        total_pages = max(1, math.ceil(total / args.size)) if args.size else 1
        print(f"\n第 {args.page} / {total_pages} 页")
        return

    if args.action == "upload":
        context = upload_video(args.file, timeout=args.upload_timeout, poll_interval=args.poll_interval)
        if args.json:
            pretty_print_json(context)
            return

        print("\n✅ 上传成功")
        print("=" * 80)
        print(f"   文件: {context.get('local_file')}")
        print(f"   upload_id: {context.get('upload_id')}")
        print(f"   window_id: {context.get('window_id')}")
        print(f"   分辨率: {context.get('screen_x')}x{context.get('screen_y')}")
        print(f"   方向: {context.get('orientation')}")
        print(f"   时长: {format_seconds(context.get('file_duration'))}")
        print(f"   大小: {format_size(context.get('file_size'))}")
        print(f"   media_url: {context.get('media_url')}")
        return

    if args.action == "delete":
        require_success(delete_upload(args.file_id), "删除媒资")
        if getattr(args, "json", False):
            pretty_print_json({"success": True, "file_id": args.file_id})
            return
        print("删除成功!")


def cmd_analyze(args):
    context = resolve_media_context(args)
    body = analyze_video(
        upload_id=context["upload_id"],
        window_id=context["window_id"],
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )
    if args.json:
        pretty_print_json(body)
        return
    describe_analysis(body)


def cmd_clip(args):
    if args.action == "types":
        body = require_success(get_clip_types(), "获取剪辑类型")
        if args.json:
            pretty_print_json(body)
            return
        print("\n✂️ 剪辑枚举")
        print("=" * 60)
        for key, value in body.items():
            print(f"{key}: {value}")
        return

    context = resolve_media_context(args)
    task = {"key": HIGH_CUT_TASK_KEY, "params": build_high_cut_params(args)}
    submit = submit_ws_tasks(
        window_id=context["window_id"],
        upload_ids=[context["upload_id"]],
        tasks=[task],
        merge_video=args.merge_video,
        timeout=args.submit_timeout,
    )

    manus_id = submit.get("manus_id")
    save_state({"last_manus_id": manus_id, "last_clip_submit": submit})

    if args.json and not args.wait:
        pretty_print_json({"submit": submit, "context": context, "task": task})
        return

    print("\n🚀 智能剪辑任务已提交")
    print("=" * 80)
    print(f"   upload_id: {context.get('upload_id')}")
    print(f"   window_id: {context.get('window_id')}")
    print(f"   manus_id: {manus_id}")
    print(f"   history_id: {submit.get('history_id')}")
    print(f"   group_id: {submit.get('group_id')}")

    if not args.wait:
        return

    body = wait_for_manus(manus_id, timeout=args.timeout, poll_interval=args.poll_interval)
    if args.json:
        pretty_print_json(body)
        return
    describe_manus(body)


def cmd_translate(args):
    if args.action == "languages":
        body = require_success(get_translation_languages(), "获取翻译语言")
        if args.json:
            pretty_print_json(body)
            return
        print("\n🌐 支持的翻译语言")
        print("=" * 60)
        for lang in body.get("speech_target_language", []):
            print(f"   {lang.get('code'):<12} {lang.get('name')}")
        return

    if args.action == "fonts":
        body = require_success(get_translation_fonts(), "获取翻译字体")
        if args.json:
            pretty_print_json(body)
            return
        print("\n🔤 支持的翻译字体")
        print("=" * 60)
        for font in body.get("fonts", []):
            print(f"   {font.get('code'):<24} {font.get('name')}")
        return

    if args.action == "styles":
        body = require_success(get_translation_effect_styles(), "获取字幕效果样式")
        if args.json:
            pretty_print_json(body)
            return
        print("\n🎨 字幕效果样式")
        print("=" * 60)
        for style in body.get("effect_color_styles", []):
            print(f"   {style.get('code')}")
        return

    context = resolve_media_context(args)
    task = {"key": TRANSLATE_TASK_KEY, "params": build_translate_params(args)}
    submit = submit_ws_tasks(
        window_id=context["window_id"],
        upload_ids=[context["upload_id"]],
        tasks=[task],
        merge_video=args.merge_video,
        timeout=args.submit_timeout,
    )
    manus_id = submit.get("manus_id")
    save_state({"last_manus_id": manus_id, "last_translate_submit": submit})

    if args.json and not args.wait:
        pretty_print_json({"submit": submit, "context": context, "task": task})
        return

    print("\n🌍 视频翻译任务已提交")
    print("=" * 80)
    print(f"   upload_id: {context.get('upload_id')}")
    print(f"   window_id: {context.get('window_id')}")
    print(f"   manus_id: {manus_id}")
    print(f"   source_language: {args.source_lang}")
    print(f"   target_language: {args.target_lang}")
    print(f"   history_id: {submit.get('history_id')}")
    print(f"   group_id: {submit.get('group_id')}")

    if not args.wait:
        return

    body = wait_for_manus(manus_id, timeout=args.timeout, poll_interval=args.poll_interval)
    if args.json:
        pretty_print_json(body)
        return
    describe_manus(body)


def cmd_manus(args):
    if args.action == "list":
        body = require_success(
            get_manus(page=args.page, page_size=args.size, task_name=args.search),
            "获取作品列表",
        )
        items = body.get("items", [])
        total = body.get("total", 0)

        if getattr(args, "json", False):
            pretty_print_json(body)
            return

        print(f"\n🎬 我的作品 (共 {total} 个)")
        print("=" * 90)
        print(f"{'ID':<10} {'标题':<40} {'状态':<12} {'创建时间'}")
        print("-" * 90)
        for item in items:
            manus_id = item.get("manus_id", "")
            task_name = item.get("task_name", "")
            title = (item.get("title") or task_name or "")[:38]
            status = item.get("status", "未知")
            created_at = str(item.get("created_time", ""))[:19]
            print(f"{manus_id:<10} {title:<40} {status:<12} {created_at}")

        total_pages = max(1, math.ceil(total / args.size)) if args.size else 1
        print(f"\n第 {args.page} / {total_pages} 页")
        return

    if args.action == "detail":
        body = require_success(get_manus_detail(args.manus_id), "获取作品详情")
        if args.json:
            pretty_print_json(body)
            return
        describe_manus(body)
        return

    if args.action == "download":
        path = download_manus(args.manus_id, args.output or ".")
        if getattr(args, "json", False):
            pretty_print_json({"success": True, "manus_id": args.manus_id, "path": path})
            return
        print(f"下载成功: {path}")
        return

    if args.action == "delete":
        require_success(delete_manus(args.manus_id), "删除作品")
        if getattr(args, "json", False):
            pretty_print_json({"success": True, "manus_id": args.manus_id})
            return
        print("删除成功!")


def build_parser():
    parser = argparse.ArgumentParser(
        description="北斗智影 AI 创作者中心 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 inbeidou_cli.py publish accounts
  python3 inbeidou_cli.py publish upload --file /path/to/video.mp4
  python3 inbeidou_cli.py publish create --account-id 109 --text "文案" --file /path/to/video.mp4
  python3 inbeidou_cli.py uploads upload --file /path/to/video.mp4
  python3 inbeidou_cli.py analyze run --file /path/to/video.mp4
  python3 inbeidou_cli.py clip create --file /path/to/video.mp4 --wait
  python3 inbeidou_cli.py episodes fetch --task-id 123 --episode-order 1
  python3 inbeidou_cli.py clip create --search "Scandalous" --episode-order 1 --wait
  python3 inbeidou_cli.py novels random --json
  python3 inbeidou_cli.py novels pipeline --execute --json
  python3 inbeidou_cli.py translate create --upload-id 69458 --lang en --wait
  python3 inbeidou_cli.py manus detail --id 12345
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    user_parser = subparsers.add_parser("user", help="查看用户信息")
    user_parser.add_argument("--json", action="store_true", help="输出 JSON")

    credit_parser = subparsers.add_parser("credit", help="查看积分余额")
    credit_parser.add_argument("--json", action="store_true", help="输出 JSON")

    products_parser = subparsers.add_parser("products", help="查看 AI 工具/产品列表及价格")
    products_parser.add_argument("--json", action="store_true", help="输出 JSON")

    lang_parser = subparsers.add_parser("languages", help="查看支持的翻译语言")
    lang_parser.add_argument("--type", choices=["all", "speech", "target", "subtitle"], default="all")
    lang_parser.add_argument("--json", action="store_true", help="输出 JSON")

    novels_parser = subparsers.add_parser("novels", help="小说库/章节/小说视频生成")
    novels_subparsers = novels_parser.add_subparsers(dest="action", help="操作", required=True)

    novels_quota = novels_subparsers.add_parser("quota", help="查看小说生成额度")
    novels_quota.add_argument("--json", action="store_true", help="输出 JSON")

    novels_list = novels_subparsers.add_parser("list", help="查看小说库")
    novels_list.add_argument("-p", "--platform", type=str, default="", help="小说平台 app_id，如 novelmaster")
    novels_list.add_argument("-l", "--language", type=str, default="", help="语言 ID；默认全语言")
    novels_list.add_argument("-s", "--search", type=str, default="", help="搜索标题")
    novels_list.add_argument("--page", type=int, default=1, help="页码")
    novels_list.add_argument("--size", type=int, default=15, help="每页数量")
    novels_list.add_argument("--order", type=str, default="publish_at", help="排序字段")
    novels_list.add_argument("--json", action="store_true", help="输出 JSON")

    def add_novel_source_args(target):
        target.add_argument("--task-id", type=str, default="", help="小说任务 ID")
        target.add_argument("--app-id", type=str, default="", help="小说平台 app_id")
        target.add_argument("-p", "--platform", type=str, default="", help="小说平台筛选 app_id")
        target.add_argument("-l", "--language", type=str, default="", help="语言 ID；默认全语言")
        target.add_argument("-s", "--search", type=str, default="", help="按标题搜索小说")
        target.add_argument("--page", type=int, default=1, help="随机候选页码")
        target.add_argument("--size", type=int, default=15, help="随机/搜索候选数量")
        target.add_argument("--order", type=str, default="publish_at", help="排序字段")

    novels_random = novels_subparsers.add_parser("random", help="随机选择一本小说")
    add_novel_source_args(novels_random)
    novels_random.add_argument("--full-text", action="store_true", help="JSON 中包含完整章节文本")
    novels_random.add_argument("--json", action="store_true", help="输出 JSON")

    novels_chapter = novels_subparsers.add_parser("chapter", help="获取小说免费章节内容")
    add_novel_source_args(novels_chapter)
    novels_chapter.add_argument("--full-text", action="store_true", help="JSON 中包含完整章节文本")
    novels_chapter.add_argument("--json", action="store_true", help="输出 JSON")

    def add_novel_generate_args(target):
        add_novel_source_args(target)
        target.add_argument("--prompt", default="", help="覆盖章节内容作为统一提示词；默认直接使用章节内容")
        target.add_argument("--timeout", type=int, default=DEFAULT_TASK_TIMEOUT, help="等待生成超时秒数")
        target.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL, help="查询任务轮询秒数")
        target.add_argument("--vidu-model", choices=NOVEL_VIDU_VIDEO_MODELS, default=DEFAULT_NOVEL_VIDEO_MODEL, help=f"Vidu 图生视频模型；默认 {DEFAULT_NOVEL_VIDEO_MODEL}")
        target.add_argument("--vidu-duration", type=int, default=DEFAULT_NOVEL_VIDU_DURATION, help="单段 Vidu 视频时长；0 表示按小说链路自动拉长到约 3 分钟总时长")
        target.add_argument("--vidu-aspect-ratio", choices=VIDU_ASPECT_RATIOS, default="9:16", help="Vidu 视频比例")
        target.add_argument("--vidu-resolution", choices=VIDU_RESOLUTIONS, default=DEFAULT_NOVEL_VIDU_RESOLUTION, help=f"Vidu 分辨率，默认 {DEFAULT_NOVEL_VIDU_RESOLUTION}")
        target.add_argument("--vidu-off-peak", action="store_true", help="Vidu 是否使用错峰模式")
        target.add_argument("--vidu-watermark", action="store_true", help="Vidu 是否添加水印")
        mode = target.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", dest="execute", action="store_false", help="只选小说和取章节，不生成")
        mode.add_argument("--execute", dest="execute", action="store_true", help="真实生成小说视频")
        target.set_defaults(execute=False)
        target.add_argument("--publish", action="store_true", help="生成后发布到社媒账号")
        target.add_argument("--publish-platform", choices=PUBLISH_SOCIAL_TYPES, default="", help="发布平台；小说视频默认使用 Vidu，可发布到 Facebook 或 TikTok")
        target.add_argument("--account-pool", choices=NOVEL_ACCOUNT_POOLS, default="", help="预设账号池")
        target.add_argument("--account-id", action="append", default=[], help="发布账号 ID")
        target.add_argument("--team-id", action="append", default=[], help="发布 team_id")
        target.add_argument("--count", type=int, default=1, help="批量生成/发布数量；发布时默认一条小说对应一个账号")
        target.add_argument("--text", default="", help="覆盖发布文案；默认使用详情页对应平台推广文案")
        target.add_argument("--text-file", default=None, help="从文件读取发布文案")
        target.add_argument("--full-text", action="store_true", help="JSON 中包含完整章节文本")
        target.add_argument("--json", action="store_true", help="输出 JSON")

    novels_generate = novels_subparsers.add_parser("generate", help="按指定/搜索小说生成推广视频")
    add_novel_generate_args(novels_generate)

    novels_pipeline = novels_subparsers.add_parser("pipeline", help="随机小说 -> 免费章节 -> 小说视频 -> 可选 Facebook/TikTok 发布")
    add_novel_generate_args(novels_pipeline)

    novels_followup = novels_subparsers.add_parser("followup-report", help=argparse.SUPPRESS)
    novels_followup.add_argument("--payload-file", required=True, help=argparse.SUPPRESS)
    novels_followup.add_argument("--delay-seconds", type=int, default=DEFAULT_NOVEL_PUBLISH_FOLLOWUP_DELAY, help=argparse.SUPPRESS)
    novels_followup.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    publish_parser = subparsers.add_parser("publish", help="矩阵发布")
    publish_subparsers = publish_parser.add_subparsers(dest="action", help="操作", required=True)

    publish_accounts = publish_subparsers.add_parser("accounts", help="列出已授权发布账号")
    publish_accounts.add_argument("--platform", help=f"按平台筛选，可选: {', '.join(PUBLISH_SOCIAL_TYPES)}")
    publish_accounts.add_argument("--status", type=int, choices=[0, 1, 2], help="按账号状态筛选")
    publish_accounts.add_argument("--json", action="store_true", help="输出 JSON")

    publish_upload = publish_subparsers.add_parser("upload", help="上传发布视频")
    publish_upload.add_argument("--file", required=True, help="本地视频文件路径")
    publish_upload.add_argument("--json", action="store_true", help="输出 JSON")

    publish_create = publish_subparsers.add_parser("create", help="创建发布任务")
    publish_create.add_argument("--account-id", action="append", help="发布账号 ID，可重复或逗号分隔")
    publish_create.add_argument("--team-id", action="append", help="team_id，可重复或逗号分隔")
    publish_create.add_argument("--platform", help=f"使用 --team-id 时指定平台，可选: {', '.join(PUBLISH_SOCIAL_TYPES)}")
    publish_create.add_argument("--text", help="帖子内容")
    publish_create.add_argument("--text-file", help="从文件读取帖子内容")
    publish_create.add_argument("--file", help="本地视频文件路径；传入后会先上传")
    publish_create.add_argument("--file-url", help="已上传视频 URL")
    publish_create.add_argument("--schedule-at", help="定时发布时间，格式 YYYY-MM-DD HH:MM[:SS]")
    publish_create.add_argument("--dry-run", action="store_true", help="只输出请求 payload，不真正提交")
    publish_create.add_argument("--json", action="store_true", help="输出 JSON")

    publish_records = publish_subparsers.add_parser("records", help="查看发布记录")
    publish_records.add_argument("--post-status", choices=["published", "scheduled"], default="published")
    publish_records.add_argument("--platform", help=f"按平台筛选，可选: {', '.join(PUBLISH_SOCIAL_TYPES)}")
    publish_records.add_argument("--account-id", action="append", help="按账号 ID 筛选；内部会自动换成对应 social_id")
    publish_records.add_argument("--social-id", help="按 social_id 筛选")
    publish_records.add_argument("--status", default="", help="按任务状态筛选，如 WAITING/POSTED/ERROR")
    publish_records.add_argument("--page", type=int, default=1, help="页码")
    publish_records.add_argument("--size", type=int, default=10, help="每页数量")
    publish_records.add_argument("--json", action="store_true", help="输出 JSON")

    publish_analysis = publish_subparsers.add_parser("analysis", help="查看发布数据分析")
    publish_analysis.add_argument("--platform", help=f"按平台筛选，可选: {', '.join(PUBLISH_SOCIAL_TYPES)}")
    publish_analysis.add_argument("--social-id", help="按 social_id 筛选")
    publish_analysis.add_argument("--start-date", default="", help="开始时间，格式 YYYY-MM-DD HH:MM:SS")
    publish_analysis.add_argument("--end-date", default="", help="结束时间，格式 YYYY-MM-DD HH:MM:SS")
    publish_analysis.add_argument("--page", type=int, default=1, help="页码")
    publish_analysis.add_argument("--size", type=int, default=10, help="每页数量")
    publish_analysis.add_argument("--json", action="store_true", help="输出 JSON")

    publish_delete = publish_subparsers.add_parser("delete", help="删除发布记录/定时任务")
    publish_delete.add_argument("--team-id", required=True, help="team_id")
    publish_delete.add_argument("--task-id", required=True, help="task_id")
    publish_delete.add_argument("--post-id", default="", help="post_id，定时任务一般可留空")
    publish_delete.add_argument("--json", action="store_true", help="输出 JSON")

    uploads_parser = subparsers.add_parser("uploads", help="媒资库管理")
    uploads_subparsers = uploads_parser.add_subparsers(dest="action", help="操作", required=True)

    uploads_list = uploads_subparsers.add_parser("list", help="列出视频")
    uploads_list.add_argument("--page", type=int, default=1, help="页码")
    uploads_list.add_argument("--size", type=int, default=10, help="每页数量")
    uploads_list.add_argument("--json", action="store_true", help="输出 JSON")

    uploads_upload = uploads_subparsers.add_parser("upload", help="上传视频")
    uploads_upload.add_argument("--file", type=str, required=True, help="视频文件路径")
    uploads_upload.add_argument("--upload-timeout", type=int, default=300, help="等待 window_id 超时秒数")
    uploads_upload.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL, help="轮询间隔秒数")
    uploads_upload.add_argument("--json", action="store_true", help="输出 JSON")

    uploads_delete = uploads_subparsers.add_parser("delete", help="删除视频")
    uploads_delete.add_argument("--id", type=str, dest="file_id", required=True, help="文件 ID")
    uploads_delete.add_argument("--json", action="store_true", help="输出 JSON")

    analyze_parser = subparsers.add_parser("analyze", help="智影解析")
    analyze_subparsers = analyze_parser.add_subparsers(dest="action", help="操作", required=True)
    analyze_run = analyze_subparsers.add_parser("run", help="执行智影解析")
    analyze_run.add_argument("--file", type=str, help="本地视频路径；传入后会先上传")
    analyze_run.add_argument("--upload-id", type=int, help="已上传媒资 ID")
    analyze_run.add_argument("--window-id", type=int, help="对应 window_id，可省略自动补全")
    analyze_run.add_argument("--task-id", type=str, default="", help="短剧任务 ID")
    analyze_run.add_argument("-s", "--search", type=str, default="", help="按标题搜索短剧")
    analyze_run.add_argument("--serial-id", type=int, help="直接指定 serial_id")
    analyze_run.add_argument("--app-id", type=str, help="直接指定 app_id")
    analyze_run.add_argument("--episode-order", type=int, help="直接取短剧第 N 集作为输入")
    analyze_run.add_argument("--drama-platform", type=str, default="", help="短剧平台筛选")
    analyze_run.add_argument("--drama-language", type=str, default="2", help="短剧语言 ID")
    analyze_run.add_argument("--drama-order", type=str, default="publish_at", help="短剧搜索排序字段")
    analyze_run.add_argument("--drama-task-type", type=str, default="1", help="短剧任务类型")
    analyze_run.add_argument("--search-size", type=int, default=10, help="短剧搜索候选数量")
    analyze_run.add_argument("--upload-timeout", type=int, default=300, help="等待 window_id 超时秒数")
    analyze_run.add_argument("--timeout", type=int, default=600, help="等待解析结果超时秒数")
    analyze_run.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL, help="轮询间隔秒数")
    analyze_run.add_argument("--json", action="store_true", help="输出 JSON")

    clip_parser = subparsers.add_parser("clip", help="智能剪辑")
    clip_subparsers = clip_parser.add_subparsers(dest="action", help="操作", required=True)

    clip_types = clip_subparsers.add_parser("types", help="查看剪辑枚举")
    clip_types.add_argument("--json", action="store_true", help="输出 JSON")

    clip_create = clip_subparsers.add_parser("create", help="提交智能剪辑任务")
    clip_create.add_argument("--file", type=str, help="本地视频路径；传入后会先上传")
    clip_create.add_argument("--upload-id", type=int, help="已上传媒资 ID")
    clip_create.add_argument("--window-id", type=int, help="对应 window_id，可省略自动补全")
    clip_create.add_argument("--task-id", type=str, default="", help="短剧任务 ID")
    clip_create.add_argument("-s", "--search", type=str, default="", help="按标题搜索短剧")
    clip_create.add_argument("--serial-id", type=int, help="直接指定 serial_id")
    clip_create.add_argument("--app-id", type=str, help="直接指定 app_id")
    clip_create.add_argument("--episode-order", type=int, help="直接取短剧第 N 集作为输入")
    clip_create.add_argument("--drama-platform", type=str, default="", help="短剧平台筛选")
    clip_create.add_argument("--drama-language", type=str, default="2", help="短剧语言 ID")
    clip_create.add_argument("--drama-order", type=str, default="publish_at", help="短剧搜索排序字段")
    clip_create.add_argument("--drama-task-type", type=str, default="1", help="短剧任务类型")
    clip_create.add_argument("--search-size", type=int, default=10, help="短剧搜索候选数量")
    clip_create.add_argument("--cut-type", choices=HIGH_CUT_CHOICES, default=DEFAULT_HIGH_CUT_CONFIG["cut_type"])
    clip_create.add_argument("--duration", default=DEFAULT_HIGH_CUT_CONFIG["cut_duration"], help="输出时长，默认 auto")
    clip_create.add_argument("--output-count", type=int, default=DEFAULT_HIGH_CUT_CONFIG["output_count"])
    clip_create.add_argument("--script-count", type=int, default=DEFAULT_HIGH_CUT_CONFIG["script_count"])
    clip_create.add_argument(
        "--deduplication",
        nargs="*",
        choices=DEDUPLICATION_CHOICES,
        default=None,
        help="去重策略列表",
    )
    clip_create.add_argument("--watermark", default=DEFAULT_HIGH_CUT_CONFIG["watermark"], help="水印文案")
    clip_create.add_argument("--merge-video", action="store_true", help="合并多段视频")
    clip_create.add_argument("--wait", action="store_true", help="等待任务完成")
    clip_create.add_argument("--upload-timeout", type=int, default=300, help="等待 window_id 超时秒数")
    clip_create.add_argument("--submit-timeout", type=int, default=90, help="等待 websocket 受理超时秒数")
    clip_create.add_argument("--timeout", type=int, default=DEFAULT_TASK_TIMEOUT, help="等待成片超时秒数")
    clip_create.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL, help="轮询间隔秒数")
    clip_create.add_argument("--json", action="store_true", help="输出 JSON")

    translate_parser = subparsers.add_parser("translate", help="视频翻译")
    translate_subparsers = translate_parser.add_subparsers(dest="action", help="操作", required=True)

    translate_langs = translate_subparsers.add_parser("languages", help="查看支持的语言")
    translate_langs.add_argument("--json", action="store_true", help="输出 JSON")

    translate_fonts = translate_subparsers.add_parser("fonts", help="查看支持的字体")
    translate_fonts.add_argument("--json", action="store_true", help="输出 JSON")

    translate_styles = translate_subparsers.add_parser("styles", help="查看字幕效果样式")
    translate_styles.add_argument("--json", action="store_true", help="输出 JSON")

    translate_create = translate_subparsers.add_parser("create", help="提交视频翻译任务")
    translate_create.add_argument("--file", type=str, help="本地视频路径；传入后会先上传")
    translate_create.add_argument("--upload-id", type=int, help="已上传媒资 ID")
    translate_create.add_argument("--window-id", type=int, help="对应 window_id，可省略自动补全")
    translate_create.add_argument("--task-id", type=str, default="", help="短剧任务 ID")
    translate_create.add_argument("-s", "--search", type=str, default="", help="按标题搜索短剧")
    translate_create.add_argument("--serial-id", type=int, help="直接指定 serial_id")
    translate_create.add_argument("--app-id", type=str, help="直接指定 app_id")
    translate_create.add_argument("--episode-order", type=int, help="直接取短剧第 N 集作为输入")
    translate_create.add_argument("--drama-platform", type=str, default="", help="短剧平台筛选")
    translate_create.add_argument("--drama-language", type=str, default="2", help="短剧语言 ID")
    translate_create.add_argument("--drama-order", type=str, default="publish_at", help="短剧搜索排序字段")
    translate_create.add_argument("--drama-task-type", type=str, default="1", help="短剧任务类型")
    translate_create.add_argument("--search-size", type=int, default=10, help="短剧搜索候选数量")
    translate_create.add_argument("--source-lang", default=DEFAULT_TRANSLATE_CONFIG["source_language"], help="源语言代码")
    translate_create.add_argument("--lang", dest="target_lang", default=DEFAULT_TRANSLATE_CONFIG["target_language"], help="目标语言代码")
    translate_create.add_argument("--subtitle-type", choices=["double", "single"], default=DEFAULT_TRANSLATE_CONFIG["subtitle_type"])
    translate_create.add_argument("--no-speech-translate", action="store_true", help="关闭 AI 配音翻译")
    translate_create.add_argument("--font", default=DEFAULT_TRANSLATE_CONFIG["font"], help="字体 code")
    translate_create.add_argument("--font-size", type=int, default=DEFAULT_TRANSLATE_CONFIG["font_size"], help="字幕字号")
    translate_create.add_argument("--font-color", default=DEFAULT_TRANSLATE_CONFIG["font_color"], help="字幕颜色")
    translate_create.add_argument("--font-opacity", type=int, default=DEFAULT_TRANSLATE_CONFIG["font_color_opacity"], help="字幕透明度 0-100")
    translate_create.add_argument("--subtitle-y", type=float, default=DEFAULT_TRANSLATE_CONFIG["subtitle_y"], help="字幕纵向位置百分比 0-100")
    translate_create.add_argument("--alignment", choices=["Left", "Center", "Right"], default=DEFAULT_TRANSLATE_CONFIG["alignment"])
    translate_create.add_argument("--effect-style", default=DEFAULT_TRANSLATE_CONFIG["effect_color_style"], help="字幕效果样式 code")
    translate_create.add_argument("--bold", action="store_true", help="粗体")
    translate_create.add_argument("--underline", action="store_true", help="下划线")
    translate_create.add_argument("--italic", action="store_true", help="斜体")
    translate_create.add_argument("--shadow", action="store_true", help="启用阴影")
    translate_create.add_argument("--shadow-shift", type=float, default=DEFAULT_TRANSLATE_CONFIG["shadow_shift"])
    translate_create.add_argument("--shadow-x-bord", type=float, default=DEFAULT_TRANSLATE_CONFIG["shadow_x_bord"])
    translate_create.add_argument("--shadow-y-bord", type=float, default=DEFAULT_TRANSLATE_CONFIG["shadow_y_bord"])
    translate_create.add_argument("--shadow-opacity", type=int, default=DEFAULT_TRANSLATE_CONFIG["shadow_opacity"])
    translate_create.add_argument("--outline", action="store_true", help="启用描边")
    translate_create.add_argument("--outline-board", type=float, default=DEFAULT_TRANSLATE_CONFIG["outline_board"])
    translate_create.add_argument("--merge-video", action="store_true", help="合并多段视频")
    translate_create.add_argument("--wait", action="store_true", help="等待任务完成")
    translate_create.add_argument("--upload-timeout", type=int, default=300, help="等待 window_id 超时秒数")
    translate_create.add_argument("--submit-timeout", type=int, default=90, help="等待 websocket 受理超时秒数")
    translate_create.add_argument("--timeout", type=int, default=DEFAULT_TASK_TIMEOUT, help="等待成片超时秒数")
    translate_create.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL, help="轮询间隔秒数")
    translate_create.add_argument("--json", action="store_true", help="输出 JSON")

    manus_parser = subparsers.add_parser("manus", help="我的作品")
    manus_subparsers = manus_parser.add_subparsers(dest="action", help="操作", required=True)

    manus_list = manus_subparsers.add_parser("list", help="列出作品")
    manus_list.add_argument("--page", type=int, default=1, help="页码")
    manus_list.add_argument("--size", type=int, default=40, help="每页数量")
    manus_list.add_argument("--search", type=str, default="", help="搜索关键词")
    manus_list.add_argument("--json", action="store_true", help="输出 JSON")

    manus_detail = manus_subparsers.add_parser("detail", help="查看作品详情")
    manus_detail.add_argument("--id", type=str, dest="manus_id", required=True, help="作品 ID")
    manus_detail.add_argument("--json", action="store_true", help="输出 JSON")

    manus_download = manus_subparsers.add_parser("download", help="下载作品")
    manus_download.add_argument("--id", type=str, dest="manus_id", required=True, help="作品 ID")
    manus_download.add_argument("--output", type=str, default=".", help="下载目录")
    manus_download.add_argument("--json", action="store_true", help="输出 JSON")

    manus_delete = manus_subparsers.add_parser("delete", help="删除作品")
    manus_delete.add_argument("--id", type=str, dest="manus_id", required=True, help="作品 ID")
    manus_delete.add_argument("--json", action="store_true", help="输出 JSON")

    episodes_parser = subparsers.add_parser("episodes", help="短剧剧集列表/取集入库")
    episodes_subparsers = episodes_parser.add_subparsers(dest="action", help="操作", required=True)

    episodes_list = episodes_subparsers.add_parser("list", help="列出短剧剧集")
    episodes_list.add_argument("--task-id", type=str, default="", help="任务 ID")
    episodes_list.add_argument("-s", "--search", type=str, default="", help="按标题搜索并取首个匹配")
    episodes_list.add_argument("--serial-id", type=int, help="直接指定 serial_id")
    episodes_list.add_argument("--app-id", type=str, help="直接指定 app_id")
    episodes_list.add_argument("--drama-platform", type=str, default="", help="按短剧平台筛选，如 dramabox")
    episodes_list.add_argument("--drama-language", type=str, default="2", help="短剧语言 ID")
    episodes_list.add_argument("--drama-order", type=str, default="publish_at", help="短剧搜索排序字段")
    episodes_list.add_argument("--drama-task-type", type=str, default="1", help="短剧任务类型")
    episodes_list.add_argument("--search-size", type=int, default=10, help="搜索候选数量")
    episodes_list.add_argument("--episode-orders", type=str, default="", help="按逗号分隔的集数筛选，如 1,2,3")
    episodes_list.add_argument("--start", type=int, help="起始集数")
    episodes_list.add_argument("--end", type=int, help="结束集数")
    episodes_list.add_argument("--video-type", type=str, default="", help="视频类型筛选")
    episodes_list.add_argument("--json", action="store_true", help="输出 JSON")

    episodes_fetch = episodes_subparsers.add_parser("fetch", help="将短剧第 N 集转成可剪辑媒资")
    episodes_fetch.add_argument("--task-id", type=str, default="", help="任务 ID")
    episodes_fetch.add_argument("-s", "--search", type=str, default="", help="按标题搜索并取首个匹配")
    episodes_fetch.add_argument("--serial-id", type=int, help="直接指定 serial_id")
    episodes_fetch.add_argument("--app-id", type=str, help="直接指定 app_id")
    episodes_fetch.add_argument("--episode-order", type=int, required=True, help="第几集")
    episodes_fetch.add_argument("--drama-platform", type=str, default="", help="按短剧平台筛选，如 dramabox")
    episodes_fetch.add_argument("--drama-language", type=str, default="2", help="短剧语言 ID")
    episodes_fetch.add_argument("--drama-order", type=str, default="publish_at", help="短剧搜索排序字段")
    episodes_fetch.add_argument("--drama-task-type", type=str, default="1", help="短剧任务类型")
    episodes_fetch.add_argument("--search-size", type=int, default=10, help="搜索候选数量")
    episodes_fetch.add_argument("--upload-timeout", type=int, default=300, help="等待素材和 window_id 超时秒数")
    episodes_fetch.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL, help="轮询间隔秒数")
    episodes_fetch.add_argument("--json", action="store_true", help="输出 JSON")

    list_parser = subparsers.add_parser("list", help="查看短剧列表")
    list_parser.add_argument("-p", "--platform", type=str, default="", help="平台(dramabox, shortmax等)")
    list_parser.add_argument("-l", "--language", type=str, default="2", help="语言 ID")
    list_parser.add_argument("-s", "--search", type=str, default="", help="搜索标题")
    list_parser.add_argument("--page", type=int, default=1, help="页码")
    list_parser.add_argument("--size", type=int, default=15, help="每页数量")
    list_parser.add_argument("--order", type=str, default="publish_at", help="排序字段")
    list_parser.add_argument("--json", action="store_true", help="输出 JSON")

    detail_parser = subparsers.add_parser("detail", help="查看短剧详情并获取推广链接")
    detail_parser.add_argument("--task-id", type=str, default="", help="任务 ID")
    detail_parser.add_argument("-p", "--platform", type=str, default="", help="平台 app_id，如 reelshort")
    detail_parser.add_argument("-l", "--language", type=str, default="2", help="语言 ID")
    detail_parser.add_argument("-s", "--search", type=str, default="", help="按标题搜索并取首个匹配")
    detail_parser.add_argument("--size", type=int, default=10, help="搜索候选数量")
    detail_parser.add_argument("--order", type=str, default="publish_at", help="搜索排序字段")
    detail_parser.add_argument("--task-type", type=str, default="1", help="任务类型")
    detail_parser.add_argument(
        "--promote-platform",
        dest="promote_platforms",
        action="append",
        default=[],
        help="推广平台，支持 1/2/3/4 或 TikTok/Facebook/Instagram/YouTube，可重复传入",
    )
    detail_parser.add_argument("--all-promote-platforms", action="store_true", help="拉取全部平台推广链接")
    detail_parser.add_argument("--no-promotion-links", action="store_true", help="只看详情，不拉取推广链接")
    detail_parser.add_argument("--json", action="store_true", help="输出 JSON")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "user":
            cmd_user(args)
        elif args.command == "credit":
            cmd_credit(args)
        elif args.command == "products":
            cmd_products(args)
        elif args.command == "languages":
            cmd_languages(args)
        elif args.command == "novels":
            cmd_novels(args)
        elif args.command == "publish":
            cmd_publish(args)
        elif args.command == "uploads":
            cmd_uploads(args)
        elif args.command == "analyze":
            cmd_analyze(args)
        elif args.command == "clip":
            cmd_clip(args)
        elif args.command == "translate":
            cmd_translate(args)
        elif args.command == "manus":
            cmd_manus(args)
        elif args.command == "episodes":
            cmd_episodes(args)
        elif args.command == "list":
            cmd_list(args)
        elif args.command == "detail":
            cmd_detail(args)
        else:
            parser.print_help()
    except InbeidouError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
