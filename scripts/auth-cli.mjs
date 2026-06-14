#!/usr/bin/env node

import path from "node:path";
import process from "node:process";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const ROOT_DIR = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const OPENCLAW_HOME = expandHome(process.env.OPENCLAW_HOME || "~/.openclaw");
const OPENCLAW_CONFIG_FILE = path.join(OPENCLAW_HOME, "openclaw.json");
const AUTH_HOME = expandHome(process.env.BARRY_VIDEO_AUTH_HOME || "~/.barry-video");
const AUTH_STATE_FILE = path.join(AUTH_HOME, "auth_state.json");
const PLUGIN_ID = "barry-video";
const API_ENV = String(process.env.BARRY_VIDEO_API_ENV || process.env.INBEIDOU_API_ENV || "test").trim().toLowerCase();
const AUTH_API_BASES = {
  prod: "https://api-claw.inbeidou.cn",
  production: "https://api-claw.inbeidou.cn",
  test: "https://test-api-claw.inbeidou.cn",
};
const AUTH_API_BASE = process.env.BARRY_VIDEO_AUTH_API_BASE || process.env.BARRY_VIDEO_CLAW_API || AUTH_API_BASES[API_ENV] || AUTH_API_BASES.test;
const AUTH_LINK_DOMAIN = AUTH_API_BASE;
const POLL_INTERVAL_MS = Number(process.env.BARRY_VIDEO_AUTH_POLL_INTERVAL_MS || 2000);
const POLL_TIMEOUT_MS = Number(process.env.BARRY_VIDEO_AUTH_POLL_TIMEOUT_MS || 5 * 60 * 1000);

function expandHome(value) {
  if (!value) return value;
  if (value === "~") return process.env.HOME || value;
  if (value.startsWith("~/")) return path.join(process.env.HOME || "", value.slice(2));
  return value;
}

function printUsage(stderr = false) {
  const stream = stderr ? process.stderr : process.stdout;
  stream.write(
    [
      "Usage:",
      "  barry-video login",
      "  barry-video auth",
      "  barry-video status",
      "  barry-video logout",
    ].join("\n") + "\n"
  );
}

async function readJson(filePath) {
  try {
    const text = await readFile(filePath, "utf8");
    return JSON.parse(text);
  } catch (error) {
    if (error && error.code === "ENOENT") return {};
    if (error instanceof SyntaxError) throw new Error(`Invalid JSON file: ${filePath}`);
    throw error;
  }
}

async function writeJsonAtomic(filePath, data) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const tmpFile = `${filePath}.${process.pid}.tmp`;
  await writeFile(tmpFile, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  await rename(tmpFile, filePath);
}

function isValidAuthState(authState) {
  const token = String(authState?.access_token || "").trim();
  const expiredAt = Number(authState?.expired_at || 0);
  const cachedApiBase = String(authState?.api_base_url || "").replace(/\/$/, "");
  return Boolean(
    token
    && authState?.status === "success"
    && expiredAt
    && expiredAt > Date.now()
    && (!cachedApiBase || cachedApiBase === AUTH_API_BASE.replace(/\/$/, ""))
  );
}

function redactAuthState(authState) {
  const cachedApiBase = String(authState.api_base_url || "").replace(/\/$/, "");
  const currentApiBase = AUTH_API_BASE.replace(/\/$/, "");
  return {
    api_base_url: authState.api_base_url,
    current_api_base: AUTH_API_BASE,
    authorization_link_domain: authState.authorization_link_domain,
    cache_file: AUTH_STATE_FILE,
    token_present: Boolean(authState.access_token),
    status: authState.status || "unknown",
    token_expired: authState.expired_at ? Number(authState.expired_at) <= Date.now() : null,
    environment_mismatch: Boolean(cachedApiBase && cachedApiBase !== currentApiBase),
    expired_at: authState.expired_at,
    agent_id: authState.agent_id,
    authorize_time: authState.authorize_time,
    updated_at: authState.updated_at,
    request_payload: authState.request_payload,
  };
}

function outputJson(payload) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function apiJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`接口返回非 JSON: HTTP ${response.status}, body=${text.slice(0, 300)}`);
  }
  if (!response.ok) {
    throw new Error(`接口请求失败: HTTP ${response.status}, code=${payload.code}, msg=${payload.msg || payload.message || ""}`);
  }
  return payload;
}

function getResponseBody(payload) {
  return payload?.body ?? payload?.data ?? payload?.result ?? {};
}

function extractCode(authorizationUrl, body) {
  if (body && typeof body === "object") {
    const directCode = body.code || body.auth_code || body.authCode;
    if (directCode) return String(directCode);
  }
  try {
    const url = new URL(String(authorizationUrl));
    return url.searchParams.get("code") || url.searchParams.get("auth_code") || "";
  } catch {
    return "";
  }
}

function extractSuccessBody(payload) {
  const body = getResponseBody(payload);
  if (body && typeof body === "object") return body;
  return payload && typeof payload === "object" ? payload : {};
}

function extractToken(body) {
  return String(body.access_token || body.token || body.auth_token || body.authToken || "").trim();
}

function extractExpiredAt(body) {
  const value = body.expired_at || body.expiredAt || body.expire_at || body.expireAt || body.expires_at || body.expiresAt;
  if (!value) return 0;
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) return 0;
  return numberValue < 10_000_000_000 ? numberValue * 1000 : numberValue;
}

async function buildRequestPayload() {
  const existing = await readJson(AUTH_STATE_FILE);
  const previousPayload = existing.request_payload || {};
  const packageJson = await readJson(path.join(ROOT_DIR, "package.json"));
  return {
    client_id: process.env.BARRY_VIDEO_AUTH_CLIENT_ID || previousPayload.client_id || "barry-video",
    client_name: process.env.BARRY_VIDEO_AUTH_CLIENT_NAME || previousPayload.client_name || "Barry Video",
    source: process.env.BARRY_VIDEO_AUTH_SOURCE || previousPayload.source || "openclaw",
    channel: process.env.BARRY_VIDEO_AUTH_CHANNEL || previousPayload.channel || "mac cli",
    model: process.env.BARRY_VIDEO_AUTH_MODEL || previousPayload.model || "",
    agent: process.env.BARRY_VIDEO_AUTH_AGENT || previousPayload.agent || "claw",
    version: process.env.BARRY_VIDEO_AUTH_VERSION || previousPayload.version || packageJson.version || "",
    platform: process.env.BARRY_VIDEO_AUTH_PLATFORM || previousPayload.platform || "openclaw野生版",
  };
}

async function createAuthorization() {
  const requestPayload = await buildRequestPayload();
  if (!requestPayload.client_id) {
    throw new Error("授权创建失败: client_id 为空");
  }

  const payload = await apiJson(`${AUTH_API_BASE}/v1/claw/auth/authorize`, {
    method: "POST",
    body: JSON.stringify(requestPayload),
  });
  if (payload.code !== 0) {
    throw new Error(`授权创建失败: code=${payload.code}, msg=${payload.msg || payload.message || ""}`);
  }

  const body = getResponseBody(payload);
  const authorizationUrl = typeof body === "string" ? body : body.authorization_url || body.authorizationUrl || body.url || "";
  if (!authorizationUrl) {
    throw new Error(`授权创建失败: 响应中没有授权链接，body=${JSON.stringify(body)}`);
  }

  const code = extractCode(authorizationUrl, body);
  if (!code) {
    throw new Error(`授权创建失败: 无法从授权链接中提取 code，url=${authorizationUrl}`);
  }

  return { authorizationUrl, code, requestPayload };
}

async function pollAuthorization({ code, requestPayload, authorizationUrl }) {
  const startedAt = Date.now();
  while (Date.now() - startedAt <= POLL_TIMEOUT_MS) {
    const payload = await apiJson(`${AUTH_API_BASE}/v1/claw/auth/check?code=${encodeURIComponent(code)}`);
    if (payload.code === 10010) {
      throw new Error("授权码已过期或已被消费，请重新发起授权");
    }
    if (payload.code !== 0) {
      throw new Error(`授权检查失败: code=${payload.code}, msg=${payload.msg || payload.message || ""}`);
    }

    const body = extractSuccessBody(payload);
    const status = String(body.status || payload.status || "").toLowerCase();
    if (status === "reject" || status === "fail" || status === "failed") {
      throw new Error(`授权失败: status=${status}`);
    }
    if (status === "success") {
      const accessToken = extractToken(body);
      const expiredAt = extractExpiredAt(body);
      if (!accessToken) {
        throw new Error(`授权成功但响应中没有 access_token: ${JSON.stringify(body)}`);
      }
      if (!expiredAt) {
        throw new Error(`授权成功但响应中没有 expired_at: ${JSON.stringify(body)}`);
      }

      const authState = {
        api_base_url: AUTH_API_BASE,
        authorization_link_domain: AUTH_LINK_DOMAIN,
        access_token: accessToken,
        expired_at: expiredAt,
        code,
        status: "success",
        agent_id: body.agent_id || body.agentId,
        authorize_time: body.authorize_time || body.authorizeTime,
        request_payload: requestPayload,
        authorization_url: authorizationUrl,
        updated_at: new Date().toISOString(),
      };
      await writeJsonAtomic(AUTH_STATE_FILE, authState);
      return authState;
    }

    await sleep(POLL_INTERVAL_MS);
  }
  throw new Error("授权等待超时，请重新发起授权");
}

async function ensureAuth({ force = false, printToken = false, json = false } = {}) {
  if (!force) {
    const current = await readJson(AUTH_STATE_FILE);
    if (isValidAuthState(current)) {
      if (printToken) process.stdout.write(String(current.access_token));
      else if (json) outputJson(redactAuthState(current));
      else process.stdout.write(`Barry Video auth is ready: ${AUTH_STATE_FILE}\n`);
      return 0;
    }
  }

  const authorization = await createAuthorization();
  process.stderr.write("请打开下面的授权链接完成北斗账号授权：\n");
  process.stderr.write(`${authorization.authorizationUrl}\n`);
  process.stderr.write(`已开始轮询授权状态，最多等待 ${Math.round(POLL_TIMEOUT_MS / 1000)} 秒...\n`);

  const authState = await pollAuthorization(authorization);
  process.stderr.write(`授权成功，token 已写入: ${AUTH_STATE_FILE}\n`);

  if (printToken) process.stdout.write(String(authState.access_token));
  else if (json) outputJson(redactAuthState(authState));
  else process.stdout.write(`Barry Video auth is ready: ${AUTH_STATE_FILE}\n`);
  return 0;
}

async function showStatus() {
  const authState = await readJson(AUTH_STATE_FILE);
  if (!authState.access_token) {
    process.stdout.write("No saved Barry Video auth token was found.\n");
    process.stdout.write(`Checked: ${AUTH_STATE_FILE}\n`);
    return 1;
  }

  const status = redactAuthState(authState);
  process.stdout.write(`Auth file: ${AUTH_STATE_FILE}\n`);
  process.stdout.write(`Current API base: ${status.current_api_base}\n`);
  if (status.api_base_url) process.stdout.write(`Cached API base: ${status.api_base_url}\n`);
  process.stdout.write(`Token: ${status.token_present ? "present" : "missing"}\n`);
  process.stdout.write(`Status: ${status.status}\n`);
  process.stdout.write(`Expired: ${status.token_expired}\n`);
  process.stdout.write(`Environment mismatch: ${status.environment_mismatch}\n`);
  if (status.expired_at) process.stdout.write(`expired_at: ${status.expired_at}\n`);
  if (status.agent_id) process.stdout.write(`agent_id: ${status.agent_id}\n`);
  if (status.authorize_time) process.stdout.write(`authorize_time: ${status.authorize_time}\n`);
  if (status.updated_at) process.stdout.write(`updated_at: ${status.updated_at}\n`);
  return isValidAuthState(authState) ? 0 : 1;
}

async function logout() {
  await rm(AUTH_STATE_FILE, { force: true }).catch(() => {});

  const openclawConfig = await readJson(OPENCLAW_CONFIG_FILE);
  const pluginConfig = openclawConfig?.plugins?.entries?.[PLUGIN_ID]?.config;
  if (pluginConfig && Object.prototype.hasOwnProperty.call(pluginConfig, "authToken")) {
    delete pluginConfig.authToken;
    await writeJsonAtomic(OPENCLAW_CONFIG_FILE, openclawConfig);
  }

  process.stdout.write(`Cleared Barry Video auth from ${AUTH_STATE_FILE}\n`);
  return 0;
}

async function main() {
  const command = process.argv[2] || "help";
  const args = new Set(process.argv.slice(3));

  try {
    if (command === "logout") {
      process.exitCode = await logout();
      return;
    }

    if (command === "status") {
      process.exitCode = await showStatus();
      return;
    }

    if (command === "login" || command === "auth") {
      process.exitCode = await ensureAuth({ force: true, json: args.has("--json") });
      return;
    }

    if (command === "ensure") {
      process.exitCode = await ensureAuth({
        force: args.has("--force"),
        printToken: args.has("--print-token"),
        json: args.has("--json"),
      });
      return;
    }

    printUsage(command !== "help");
    process.exitCode = command === "help" ? 0 : 1;
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}

await main();
