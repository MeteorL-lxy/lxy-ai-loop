---
name: barry-account
description: Use Barry Account when the user asks about the current Inbeidou account, credit balance, AI tool prices, or supported language catalogs.
---

# Barry Account

Use these tools:

- `barry_video_user`
- `barry_video_credit`
- `barry_video_products`
- `barry_video_languages`

When the user asks a direct factual question such as "我的积分是多少", answer from the tool result without extra workflow steps.

## User-facing account display

When presenting account profile fields to the user, keep the existing presence logic: only show optional fields that are present in the tool/API result, and do not invent missing fields.

Use Chinese labels for promotion capability fields:

- `ReelShort 推广权限：已开通/未开通`
- `Facebook 推广权限：已开通/未开通`

Do not label these simply as `ReelShort` or `Facebook`, because users may confuse them with publish-account authorization status.

## Fallback when tools are not exposed

If the `barry_video_*` tools are not directly available in the current agent session, do not search the user's current workspace for source files and do not depend on a development checkout such as `/Users/xinyuliu/Desktop/work/barry-video`.

Use the installed Barry Video CLI first:

```bash
barry-video backend user --json
barry-video backend credit --json
barry-video backend products --json
barry-video backend languages --json
```

If `barry-video` is not on `PATH`, use the installed plugin backend directly:

```bash
python3 ~/.openclaw/extensions/barry-video/backend/inbeidou_cli.py user --json
python3 ~/.openclaw/extensions/barry-video/backend/inbeidou_cli.py credit --json
python3 ~/.openclaw/extensions/barry-video/backend/inbeidou_cli.py products --json
python3 ~/.openclaw/extensions/barry-video/backend/inbeidou_cli.py languages --json
```

The backend reads auth from `~/.barry-video/auth_state.json` automatically. Prefer `barry-video backend ...` when available because it starts the authorization link + polling flow automatically if token is missing. If direct Python fallback returns an auth error, ask the user to run `/beidou-auth` or `barry-video login`.
