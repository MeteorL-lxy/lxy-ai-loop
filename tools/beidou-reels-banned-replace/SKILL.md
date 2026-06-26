---
name: beidou-reels-banned-replace
description: Beidou loop helper for detecting Facebook accounts that cannot publish REEL videos from each loop run's Beidou post records, summarizing affected social_ids, and triggering Beidou automatic replacement from the public account pool. Use when a loop run should self-heal accounts that failed with "账号不能发布reel视频" or an equivalent cannot-publish-reel error.
---

# Beidou REEL Banned Replace

Use this tool after each Barry Video continuous-loop round, or when reviewing loop failures. It detects Facebook `social_ids` that failed with a clear cannot-publish-REEL error, summarizes them, and calls the Beidou inner API:

```http
POST /ai/v1/publish/team/social/reels-banned/replace
```

The API owns the database update: it marks the passed accounts as REEL-banned and assigns replacement accounts from the public pool. This skill must not directly edit the database.

## Current Barry Video Loop Usage

The local Barry Video loop auto-runs this tool from `scripts/run-drama-line-worker.py` after a round JSON is written:

```bash
python tools/beidou-reels-banned-replace/scripts/reels_banned_replace.py \
  --loop-root /Users/xinyuliu/Desktop/work/barry-video \
  --round-json runtime/continuous-loop/YYYY-MM-DD/LINE/roundN.json
```

This is enabled by default with:

```bash
BARRY_LOOP_REELS_BANNED_REPLACE=1
BARRY_LOOP_REELS_BANNED_RECONCILE=1
```

For a safe local smoke test without calling Beidou:

```bash
python tools/beidou-reels-banned-replace/scripts/reels_banned_replace.py \
  --loop-root /Users/xinyuliu/Desktop/work/barry-video \
  --round-json runtime/continuous-loop/YYYY-MM-DD/LINE/roundN.json \
  --detect-only
```

For a dry run that prints the replacement payload but does not write:

```bash
python tools/beidou-reels-banned-replace/scripts/reels_banned_replace.py \
  --loop-root /Users/xinyuliu/Desktop/work/barry-video \
  --round-json runtime/continuous-loop/YYYY-MM-DD/LINE/roundN.json \
  --dry-run
```

Round JSON events are deduplicated in `runtime/account-flags/reels_banned_replace_state.json`, so the same failed publish row is not repeatedly sent to Beidou.

## Manual / Legacy Usage

Automatically detect the latest loop run and call the replacement API:

```bash
python skills/beidou-reels-banned-replace/scripts/reels_banned_replace.py --auto-detect
```

Preview detected accounts without calling the replacement API:

```bash
python skills/beidou-reels-banned-replace/scripts/reels_banned_replace.py --auto-detect --detect-only
```

Manual reporting is still supported:

```bash
python skills/beidou-reels-banned-replace/scripts/reels_banned_replace.py --social-ids 11,12,13
```

The replacement request sends:

```json
{"social_ids":[11,12,13]}
```

## Configuration

Resolve API config in this order:

1. CLI flags: `--base-url`, `--token`, `--loop-root`.
2. Environment variables: `AI_ICENTER_BASE_URL`, `AI_BEIDOU_TOKEN`.
3. Current loop auth client: `backend/inbeidou_cli.py`, used when no explicit token is provided.
4. Current loop config: `runtime/loop_config.json`, fields `beidou.icenter_base_url` and `beidou.token`.
5. Default base URL: `https://api-icenter.inbeidou.cn`.

Do not print the full token. The script never includes the token in normal output.

The script forces direct Beidou requests by default so stale local proxy settings do not break loop automation. Use `--use-env-proxy` only when the current machine must access Beidou through `HTTP_PROXY` or `HTTPS_PROXY`.

## Detection Workflow

1. Prefer explicit `--round-json` or `--round-dir` from `runtime/continuous-loop/YYYY-MM-DD/{line}/roundN.json`.
2. Read `report_zh` rows and map failed rows back to the round item/account.
3. Detect only clear REEL capability errors, such as `账号不能发布reel视频`, `不能发布reel`, or `cannot publish reel`.
4. Exclude material/media failures such as height/width errors, ffmpeg errors, upload errors, invalid URLs, timeouts, or remote video read failures.
5. Deduplicate and sort the affected `social_ids`.
6. Call the replacement API with the summarized IDs.
7. Mark successful round events as processed, then optionally run `scripts/reconcile-account-pools.py --write` from the worker so replacement accounts can be picked up.

The old Beidou post-list auto-detect path still exists for manual recovery via `--auto-detect`, but the current loop integration should use round JSON detection.

## Script Behavior

The script:

- Deduplicates and sorts IDs.
- With `--round-json` or `--round-dir`, detects cannot-publish-REEL accounts from current continuous-loop result JSON.
- With `--auto-detect`, queries Beidou post records and summarizes cannot-publish-REEL accounts from a time window.
- Calls `POST /ai/v1/publish/team/social/reels-banned/replace`.
- Treats HTTP failures or non-zero response `code` as errors.
- Supports `--detect-only` to inspect detected IDs without calling replacement.
- Supports `--dry-run` to print the request target and payload without writing anything.

## Examples

Report three accounts manually:

```bash
python skills/beidou-reels-banned-replace/scripts/reels_banned_replace.py --social-ids 1044 1049 1050
```

Preview the latest loop detection:

```bash
python skills/beidou-reels-banned-replace/scripts/reels_banned_replace.py --auto-detect --detect-only
```

Detect errors in the last 12 hours instead of using latest loop start:

```bash
python skills/beidou-reels-banned-replace/scripts/reels_banned_replace.py --auto-detect --since-hours 12
```

Detect in an explicit time window:

```bash
python skills/beidou-reels-banned-replace/scripts/reels_banned_replace.py \
  --auto-detect \
  --since "2026-06-24 08:00:00" \
  --end "2026-06-24 12:00:00"
```

Use a specific test host:

```bash
python skills/beidou-reels-banned-replace/scripts/reels_banned_replace.py \
  --base-url https://test-api-icenter.inbeidou.cn \
  --auto-detect
```
