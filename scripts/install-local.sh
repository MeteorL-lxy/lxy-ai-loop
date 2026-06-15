#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
EXTENSIONS_DIR="$OPENCLAW_HOME/extensions"
SKILLS_DIR="$OPENCLAW_HOME/skills"
CODEX_SKILLS_DIR="${CODEX_HOME:-$HOME/.codex}/skills"
CLAUDE_SKILLS_DIR="${CLAUDE_HOME:-$HOME/.claude}/skills"
PLUGIN_DIR="$EXTENSIONS_DIR/barry-video"
PLUGIN_BACKEND_DIR="$PLUGIN_DIR/backend"
PLUGIN_BACKEND="$PLUGIN_BACKEND_DIR/inbeidou_cli.py"
PLUGIN_FLYWHEEL_BACKEND="$PLUGIN_BACKEND_DIR/flywheel_cli.py"
SKILL_DIR="$SKILLS_DIR/barry-video"
CONFIG_FILE="$OPENCLAW_HOME/openclaw.json"
PYTHON_BIN="${BARRY_VIDEO_PYTHON:-python3}"
DOWNLOAD_DIR="${BARRY_VIDEO_DOWNLOAD_DIR:-$HOME/Desktop}"
AUTH_TOKEN="${BARRY_VIDEO_AUTH_TOKEN:-${BARRY_VIDEO_TOKEN:-${INBEIDOU_TOKEN:-}}}"
DEFAULT_ACCOUNT_IDS="${BARRY_VIDEO_DEFAULT_ACCOUNT_IDS:-}"
DEFAULT_TEAM_IDS="${BARRY_VIDEO_DEFAULT_TEAM_IDS:-}"
DEFAULT_PUBLISH_PLATFORM="${BARRY_VIDEO_DEFAULT_PUBLISH_PLATFORM:-FACEBOOK}"
DEFAULT_DRAMA_PLATFORM="${BARRY_VIDEO_DEFAULT_DRAMA_PLATFORM:-dramabox}"
DEFAULT_LANGUAGE="${BARRY_VIDEO_DEFAULT_LANGUAGE:-2}"
DEFAULT_DRAMA_ORDER="${BARRY_VIDEO_DEFAULT_DRAMA_ORDER:-publish_at}"
SOURCE_BACKEND=""
CONFIG_BACKEND_CLI=""
CONFIG_FLYWHEEL_CLI=""
while [ "$#" -gt 0 ]; do
  echo "Error: unknown install option: $1" >&2
  exit 1
done

expand_home() {
  local value="$1"
  if [[ "$value" == "~" ]]; then
    printf '%s\n' "$HOME"
    return
  fi
  if [[ "$value" == ~/* ]]; then
    printf '%s/%s\n' "$HOME" "${value#~/}"
    return
  fi
  printf '%s\n' "$value"
}

for candidate in "${BARRY_VIDEO_BACKEND:-}" "$HOME/inbeidou_cli.py" "/Users/ming/inbeidou_cli.py"; do
  [ -n "$candidate" ] || continue
  candidate="$(expand_home "$candidate")"
  if [ -f "$candidate" ]; then
    SOURCE_BACKEND="$candidate"
    break
  fi
done

mkdir -p "$EXTENSIONS_DIR" "$SKILLS_DIR" "$CODEX_SKILLS_DIR" "$CLAUDE_SKILLS_DIR"

for required_path in backend scripts conf skills openclaw.plugin.json; do
  if [ ! -e "$ROOT_DIR/$required_path" ]; then
    echo "Error: workspace looks incomplete, missing $required_path; aborting install-local sync." >&2
    exit 2
  fi
done

SOURCE_FILE_COUNT="$(find "$ROOT_DIR" \
  -path "$ROOT_DIR/.git" -prune -o \
  -path "$ROOT_DIR/data" -prune -o \
  -path "$ROOT_DIR/runtime" -prune -o \
  -path "$ROOT_DIR/logs" -prune -o \
  -type f -print | wc -l | tr -d ' ')"
if [ "${SOURCE_FILE_COUNT:-0}" -lt 60 ]; then
  echo "Error: workspace has only ${SOURCE_FILE_COUNT:-0} source files; refusing rsync --delete to plugin copy." >&2
  exit 2
fi

rsync -a --delete \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude '*.tgz' \
  "$ROOT_DIR/" "$PLUGIN_DIR/"

mkdir -p "$PLUGIN_BACKEND_DIR"
if [ -n "$SOURCE_BACKEND" ]; then
  cp "$SOURCE_BACKEND" "$PLUGIN_BACKEND"
  chmod 0644 "$PLUGIN_BACKEND"
  CONFIG_BACKEND_CLI="$PLUGIN_BACKEND"
else
  CONFIG_BACKEND_CLI="$PLUGIN_BACKEND"
  if [ -f "$PLUGIN_BACKEND" ]; then
    echo "Using bundled Barry Video backend: $PLUGIN_BACKEND"
  else
    echo "Warning: no local or bundled inbeidou_cli.py backend found during install." >&2
    echo "Expected one of:" >&2
    echo "  - \$BARRY_VIDEO_BACKEND" >&2
    echo "  - $HOME/inbeidou_cli.py" >&2
    echo "  - /Users/ming/inbeidou_cli.py" >&2
  fi
fi
CONFIG_FLYWHEEL_CLI="$PLUGIN_FLYWHEEL_BACKEND"
if [ ! -f "$PLUGIN_FLYWHEEL_BACKEND" ]; then
  echo "Warning: bundled flywheel_cli.py backend not found during install: $PLUGIN_FLYWHEEL_BACKEND" >&2
fi

for skill_path in "$ROOT_DIR"/skills/*; do
  [ -d "$skill_path" ] || continue
  skill_name="$(basename "$skill_path")"
  rm -rf "$SKILLS_DIR/$skill_name"
  cp -R "$skill_path" "$SKILLS_DIR/$skill_name"
  rm -rf "$CODEX_SKILLS_DIR/$skill_name"
  cp -R "$skill_path" "$CODEX_SKILLS_DIR/$skill_name"
  rm -rf "$CLAUDE_SKILLS_DIR/$skill_name"
  cp -R "$skill_path" "$CLAUDE_SKILLS_DIR/$skill_name"
done

python3 - "$CONFIG_FILE" "$PLUGIN_DIR" "$SKILLS_DIR" "$CONFIG_BACKEND_CLI" "$CONFIG_FLYWHEEL_CLI" "$PYTHON_BIN" "$DOWNLOAD_DIR" "$AUTH_TOKEN" "$DEFAULT_ACCOUNT_IDS" "$DEFAULT_TEAM_IDS" "$DEFAULT_PUBLISH_PLATFORM" "$DEFAULT_DRAMA_PLATFORM" "$DEFAULT_LANGUAGE" "$DEFAULT_DRAMA_ORDER" <<'PY'
import json
import pathlib
import sys

config_file = pathlib.Path(sys.argv[1]).expanduser()
plugin_dir = str(pathlib.Path(sys.argv[2]).expanduser().resolve())
skills_dir = str(pathlib.Path(sys.argv[3]).expanduser().resolve())
backend_cli = str(pathlib.Path(sys.argv[4]).expanduser())
flywheel_cli = str(pathlib.Path(sys.argv[5]).expanduser())
python_bin = sys.argv[6]
download_dir = str(pathlib.Path(sys.argv[7]).expanduser())
auth_token = sys.argv[8]
default_account_ids = [item.strip() for item in sys.argv[9].split(",") if item.strip()]
default_team_ids = [item.strip() for item in sys.argv[10].split(",") if item.strip()]
default_publish_platform = sys.argv[11]
default_drama_platform = sys.argv[12]
default_language = sys.argv[13]
default_drama_order = sys.argv[14]

config_file.parent.mkdir(parents=True, exist_ok=True)
if config_file.exists():
    data = json.loads(config_file.read_text(encoding="utf-8"))
else:
    data = {}

skills = data.setdefault("skills", {})
skills_load = skills.setdefault("load", {})
extra_dirs = skills_load.setdefault("extraDirs", [])
if skills_dir not in extra_dirs:
    extra_dirs.append(skills_dir)
skills_entries = skills.setdefault("entries", {})
skills_entries.setdefault("barry-video", {})["enabled"] = True

plugins = data.setdefault("plugins", {})
plugins["enabled"] = True
plugin_allow = plugins.setdefault("allow", [])
if "barry-video" not in plugin_allow:
    plugin_allow.append("barry-video")
plugin_load = plugins.setdefault("load", {})
plugin_paths = plugin_load.setdefault("paths", [])
if plugin_dir not in plugin_paths:
    plugin_paths.append(plugin_dir)
plugin_entries = plugins.setdefault("entries", {})
plugin_entry = plugin_entries.setdefault("barry-video", {})
plugin_entry["enabled"] = True
plugin_config = plugin_entry.setdefault("config", {})
plugin_config["backendCli"] = backend_cli
plugin_config["flywheelCli"] = flywheel_cli
plugin_config.setdefault("pythonBin", python_bin)
plugin_config.setdefault("downloadDir", download_dir)
if auth_token:
    plugin_config["authToken"] = auth_token
plugin_config.setdefault("defaultAccountIds", default_account_ids)
plugin_config.setdefault("defaultTeamIds", default_team_ids)
plugin_config.setdefault("defaultPublishPlatform", default_publish_platform)
plugin_config.setdefault("defaultDramaPlatform", default_drama_platform)
plugin_config.setdefault("defaultLanguage", default_language)
plugin_config.setdefault("defaultDramaOrder", default_drama_order)

agents = data.setdefault("agents", {})
defaults = agents.setdefault("defaults", {})
tools = defaults.setdefault("tools", {})
tool_allow = tools.setdefault("allow", [])
if "barry-video" not in tool_allow:
    tool_allow.append("barry-video")

config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "Installed Barry Video plugin into: $PLUGIN_DIR"
echo "Installed Barry Video skills into: $SKILLS_DIR"
echo "Installed Barry Video skills into: $CODEX_SKILLS_DIR (Codex)"
echo "Installed Barry Video skills into: $CLAUDE_SKILLS_DIR (Claude Code)"
echo "Updated OpenClaw config: $CONFIG_FILE"
if [ -f "$PLUGIN_BACKEND" ]; then
  echo "Installed Barry Video private backend into: $PLUGIN_BACKEND"
fi
if [ -f "$PLUGIN_FLYWHEEL_BACKEND" ]; then
  echo "Installed Barry Video flywheel backend into: $PLUGIN_FLYWHEEL_BACKEND"
fi
echo "Run '/beidou-auth' in your agent to authorize."
