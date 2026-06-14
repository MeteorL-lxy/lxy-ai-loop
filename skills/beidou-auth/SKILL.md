---
name: beidou-auth
description: Manage Beidou auth tokens for Barry Video APIs. Use when the current agent needs to handle `/beidou-auth` or `/beidou-auth status`, create and refresh tokens for the current Barry Video API environment. Default environment is test; set `BARRY_VIDEO_API_ENV=prod` for production.
---

# Beidou Auth

Manage a local auth cache for protected Barry Video APIs.

Core behavior:

1. Read cached auth state from a local JSON file
2. Reuse the token if it is present and not expired
3. If no valid token exists, create an auth URL and start authorization
4. Poll `/v1/claw/auth/check` every 2 seconds for up to 5 minutes
5. On success, overwrite the JSON cache with the new token
6. If any protected API returns `401`, re-authorize, replace the JSON file, and retry once

## Environment

Default environment is test unless `BARRY_VIDEO_API_ENV=prod` or `INBEIDOU_API_ENV=prod` is set.

Test:

- Authorization link domain: `https://test-api-claw.inbeidou.cn`
- Claw API base URL: `https://test-api-claw.inbeidou.cn`
- ICenter API base URL: `https://test-api-icenter.inbeidou.cn`
- SCenter API base URL: `https://test-api-scenter.inbeidou.cn`

Production:

- Authorization link domain: `https://api-claw.inbeidou.cn`
- Claw API base URL: `https://api-claw.inbeidou.cn`
- ICenter API base URL: `https://api-icenter.inbeidou.cn`
- SCenter API base URL: `https://api-scenter.inbeidou.cn`

Choose the API base by current agent family or system context:

- use the current environment's claw base URL when the current integration belongs to the claw side
- use the current environment's icenter base URL when the current integration belongs to the icenter side
- use the current environment's scenter base URL when the current integration belongs to the scenter side

Use the chosen API base URL for auth API calls and protected API calls.
Expect the returned authorization URL to point to the current environment's claw domain.

## Fixed Rules

- Always use the current environment's claw/icenter/scenter base URL as the API `api_base_url`
- Never ask the user to provide `api_base_url`
- Treat `/beidou-auth` as the command to load-or-start authorization
- Treat `/beidou-auth status` as the command to inspect cached auth state

## Commands

### `/beidou-auth`

Run this order:

1. Read the resolved `auth_state.json`
2. If it contains a valid token, return the cached state
3. Otherwise derive request parameters, create the auth URL, display it to the user, and continue background polling until success, failure, rejection, or timeout, then save the new token on success

### `/beidou-auth status`

Do not start a new auth flow by default.

Read the resolved `auth_state.json` and report:

- whether the file exists
- whether `access_token` exists
- whether the token appears expired
- `status`
- `expired_at` as a Unix timestamp in milliseconds
- `agent_id`
- `authorize_time`
- `updated_at`
- `request_payload`

If the file is missing, say that no cached authorization exists.
Also return the resolved cache path.

## Cache File

Do not hardcode any Codex-specific path.

Resolve the cache file path from the current agent runtime.

Use this order:

1. a host-provided writable state path for the current agent
2. the current agent's writable app-data or config directory
3. a writable workspace-local state directory for the current agent

Requirements:

- the filename remains `auth_state.json`
- the path is stable across runs for the same agent
- the path is writable by the current agent
- the path can distinguish different agent identities on the same machine

For barry-video, the resolved path is `~/.barry-video/auth_state.json`.

Expected JSON shape:

```json
{
  "api_base_url": "https://test-api-claw.inbeidou.cn",
  "authorization_link_domain": "https://test-api-claw.inbeidou.cn",
  "access_token": "<token>",
  "expired_at": 1777022400000,
  "code": "AuthCode1234",
  "status": "success",
  "agent_id": 1001,
  "authorize_time": "2026-04-20 12:00:00",
  "request_payload": {
    "client_id": "barry-video",
    "client_name": "Barry Video",
    "source": "openclaw",
    "channel": "mac cli",
    "model": "gpt-5",
    "agent": "claw",
    "version": "1.2.3",
    "platform": "openclaw野生版"
  },
  "updated_at": "2026-04-20T12:00:00+08:00"
}
```

`expired_at` is a Unix timestamp in milliseconds.

Treat the cache as unusable when:

- the file does not exist
- `access_token` is empty
- `status` is not `success`
- `expired_at` is missing
- `expired_at` is already in the past
- `api_base_url` belongs to a different environment than the current Barry Video API environment

Write the file atomically after every successful authorization refresh.
Always return the resolved cache path with responses that read or write the cache.

## Parameter Discovery

Before `POST /v1/claw/auth/authorize`, infer the request payload in this order:

1. system parameters or known agent-family identity
2. current repo name, docs, and recent files
3. existing auth examples, tests, or curl commands
4. current thread environment
5. recent user intent

Infer these fields:

- `client_id`
- `client_name`
- `source`
- `channel`
- `model`
- `agent`
- `version`
- `platform`

Rules:

- Prefer system parameters over generic project inference
- `client_id` is required for `POST /v1/claw/auth/authorize`
- `client_id` must be a unique identifier for the actual agent in use
- The uniqueness requirement applies to agents including but not limited to `openclaw`, Feishu agents, DingTalk agents, `hermes`, and similar agent families
- Never use a vague shared value for `client_id` if it cannot uniquely identify the current agent instance or agent identity
- If the system already exposes a stable unique agent identifier, use that directly for `client_id`
- If repeated authorization requests come from the same agent identity, keep using the same `client_id`
- Do not generate a new random or time-varying `client_id` for the same agent on each authorization attempt
- If the local auth cache already contains a previously successful `request_payload.client_id` for the same agent identity, reuse that value unless the real agent identity has changed
- If the client is `openclaw`, use the `openclaw` identity and metadata
- If the client is a Feishu-series agent, use that Feishu agent's identity and metadata
- If the client is a DingTalk-series agent, use that DingTalk agent's identity and metadata
- If the client is `hermes`, use the `hermes` identity and metadata
- Use project context for `version` or `model` only when system parameters do not already provide them
- Do not call `POST /v1/claw/auth/authorize` with an empty `client_id`
- If a reliable `client_id` cannot be resolved, stop and report that authorization creation is blocked
- Do not ask the user to hand-fill these values unless the flow is truly blocked

Fallback defaults:

- `client_id`: `barry-video`
- `source`: prefer `openclaw`
- `channel`: infer from `mac cli`, `feishu`, `dingtalk`, or `self-hosted agent`
- `agent`: prefer `claw`
- `client_name`: prefer the actual agent name; if it cannot be discovered, use `Barry Video`
- other missing fields may stay empty if no reliable source exists

Always return the final inferred `request_payload`.

## API Rules

Interpret API results by response `code`, not by HTTP status.

- `code == 0`: success
- `code == 10010`: auth code expired, missing, or already consumed
- `code == 1`: server-side failure
- any other non-zero code: surface the server message and stop unless the user explicitly wants retries

## Authorization Flow

### 1. Create Auth URL

Call:

```bash
curl -sS -X POST '<CHOSEN_PROD_BASE_URL>/v1/claw/auth/authorize' \
  -H 'Content-Type: application/json' \
  -d '<REQUEST_PAYLOAD_JSON>'
```

On success:

- read `body` as the authorization URL
- extract the `code`
- verify that the returned URL points to the current environment's claw domain when applicable
- display the authorization URL in the agent UI or response page so the user can click it and complete authorization
- start background polling immediately after the URL is shown
- do not wait for the user to send another message before polling

### 2. Poll Status

Call:

```bash
curl -sS '<CHOSEN_PROD_BASE_URL>/v1/claw/auth/check?code=<CODE>'
```

Polling policy:

- poll every `2 seconds`
- maximum duration `5 minutes`
- continue polling in the background after the authorization URL is displayed
- stop on `status == success`
- stop on `status == reject`
- stop on `status == fail`
- stop on `code == 10010`
- if 5 minutes elapse first, report `timeout`

Current normal states:

- `submitting`
- `success`

Treat `reject` or `fail` as terminal failure if the backend returns them.

### 3. Persist Success

When polling reaches `status=success`:

- save `access_token` immediately
- save `expired_at` immediately as the backend-returned Unix millisecond timestamp
- save `code`, `agent_id`, `authorize_time`, and `request_payload`
- overwrite the resolved cache file atomically

Important:

- `/v1/claw/auth/check` success is one-time consumable
- once success is returned, the backend may delete that auth code
- do not expect the same success payload to be fetchable again

## Using The Cached Token

For any other protected API under the chosen API base:

1. read the resolved cache file
2. load `access_token`
3. send:

```http
Authorization: <access_token>
```

If the call succeeds, keep using the current cache.

## Recovering From 401

If a protected API call returns `401`:

1. treat the cached token as invalid
2. start a fresh auth flow
3. replace the resolved cache file with the new successful result
4. retry the original API call once

If the retry still returns `401`, stop and report failure.

## Output Shape

For `/beidou-auth` or a refresh flow, return:

- `api_base_url`
- `authorization_link_domain`
- `cache_file`
- `token_source`
- `authorization_url` when a new flow was started
- `authorization_url_display: true` when a new flow was started
- `authorization_url_shown_to_user: true` when a new flow was started
- `code` when a new flow was started
- `request_payload`
- `polling_started: true` when a new flow was started
- `polling_mode: background` when a new flow was started
- `poll_interval`
- `poll_timeout`
- `access_token`
- `expired_at` as a Unix timestamp in milliseconds
- `agent_id` when present
- `authorize_time` when present
- `updated_at` when present
- `refreshed_after_401` when applicable

For `/beidou-auth status`, return:

- `api_base_url`
- `authorization_link_domain`
- `cache_file`
- `status`
- `token_present`
- `token_expired`
- `expired_at` as a Unix timestamp in milliseconds
- `agent_id` when present
- `authorize_time` when present
- `updated_at` when present
- `request_payload` when present

Prefer short command-style responses over long explanations.
