#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' "$ROOT_DIR/package.json")"
OUTPUT="${1:-$HOME/Desktop/barry-video-openclaw-${VERSION}.tgz}"

mkdir -p "$(dirname "$OUTPUT")"
tar -czf "$OUTPUT" -C "$(dirname "$ROOT_DIR")" "$(basename "$ROOT_DIR")"

echo "$OUTPUT"
