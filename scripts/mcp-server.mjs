#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT_DIR = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const PLUGIN_ID = "barry-video";
const SERVER_NAME = "barry-video-mcp";
const SERVER_VERSION = "0.1.0";
const DEFAULT_PROTOCOL_VERSION = "2024-11-05";
const AUTH_HOME = expandHome(process.env.BARRY_VIDEO_AUTH_HOME || "~/.barry-video");

const PUBLISH_PLATFORMS = ["TIKTOK", "FACEBOOK", "INSTAGRAM", "YOUTUBE"];

function expandHome(value) {
  if (!value || typeof value !== "string") return value;
  if (value === "~") return os.homedir();
  if (value.startsWith("~/")) return path.join(os.homedir(), value.slice(2));
  return value;
}

function readJson(file) {
  try {
    return JSON.parse(readFileSync(expandHome(file), "utf8"));
  } catch {
    return {};
  }
}

function pluginConfig() {
  const config = readJson(path.join(os.homedir(), ".openclaw", "openclaw.json"));
  return config?.plugins?.entries?.[PLUGIN_ID]?.config || {};
}

function expectedClawApiBase() {
  const env = String(process.env.BARRY_VIDEO_API_ENV || process.env.INBEIDOU_API_ENV || "test").trim().toLowerCase();
  if (process.env.BARRY_VIDEO_AUTH_API_BASE) return process.env.BARRY_VIDEO_AUTH_API_BASE.replace(/\/$/, "");
  if (process.env.BARRY_VIDEO_CLAW_API) return process.env.BARRY_VIDEO_CLAW_API.replace(/\/$/, "");
  if (env === "prod" || env === "production") return "https://api-claw.inbeidou.cn";
  return "https://test-api-claw.inbeidou.cn";
}

function resolvePythonBin() {
  return process.env.BARRY_VIDEO_PYTHON || pluginConfig().pythonBin || "python3";
}

function resolveBackendCli() {
  const config = pluginConfig();
  const candidates = [
    process.env.BARRY_VIDEO_BACKEND,
    path.join(ROOT_DIR, "backend", "inbeidou_cli.py"),
    config.backendCli,
    path.join(os.homedir(), ".openclaw", "extensions", "barry-video", "backend", "inbeidou_cli.py"),
    path.join(os.homedir(), "inbeidou_cli.py"),
  ].filter(Boolean).map(expandHome);
  return candidates.find((candidate) => existsSync(candidate)) || candidates[0];
}

function resolveFlywheelCli() {
  const config = pluginConfig();
  const candidates = [
    process.env.BARRY_VIDEO_FLYWHEEL,
    process.env.BARRY_VIDEO_FLYWHEEL_BACKEND,
    path.join(ROOT_DIR, "backend", "flywheel_cli.py"),
    config.flywheelCli,
    path.join(os.homedir(), ".openclaw", "extensions", "barry-video", "backend", "flywheel_cli.py"),
  ].filter(Boolean).map(expandHome);
  return candidates.find((candidate) => existsSync(candidate)) || candidates[0];
}

function resolveAuthToken() {
  const envToken = process.env.INBEIDOU_TOKEN || process.env.BARRY_VIDEO_AUTH_TOKEN || process.env.BARRY_VIDEO_TOKEN;
  if (envToken) return envToken;
  const authState = readJson(path.join(AUTH_HOME, "auth_state.json"));
  const expiredAt = Number(authState?.expired_at || 0);
  const cachedApiBase = String(authState?.api_base_url || "").replace(/\/$/, "");
  if (
    authState?.access_token
    && authState?.status === "success"
    && expiredAt > Date.now()
    && (!cachedApiBase || cachedApiBase === expectedClawApiBase())
  ) {
    return String(authState.access_token);
  }
  const configToken = pluginConfig().authToken;
  if (configToken) return String(configToken);

  const authCli = path.join(ROOT_DIR, "scripts", "auth-cli.mjs");
  if (!existsSync(authCli)) return "";
  const result = spawnSync(process.execPath, [authCli, "ensure", "--print-token"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "inherit"],
  });
  if (result.status !== 0) return "";
  return String(result.stdout || "").trim();
}

function addOption(args, flag, value) {
  if (value === undefined || value === null || value === "") return;
  args.push(flag, String(value));
}

function addFlag(args, enabled, flag) {
  if (enabled) args.push(flag);
}

function addRepeated(args, flag, values) {
  for (const value of Array.isArray(values) ? values : values ? [values] : []) {
    if (value !== undefined && value !== null && String(value).trim()) {
      args.push(flag, String(value));
    }
  }
}

function runPython(script, args, { timeoutMs = 0 } = {}) {
  const pythonBin = resolvePythonBin();
  const authToken = resolveAuthToken();
  return new Promise((resolve, reject) => {
    const child = spawn(pythonBin, [script, ...args], {
      env: {
        ...process.env,
        ...(authToken ? { INBEIDOU_TOKEN: authToken } : {}),
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let timer = null;
    if (timeoutMs > 0) {
      timer = setTimeout(() => child.kill("SIGTERM"), timeoutMs);
    }
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (timer) clearTimeout(timer);
      if (code !== 0) {
        reject(new Error((stderr || stdout || `Command failed with code ${code}`).trim()));
        return;
      }
      resolve({ stdout: stdout.trim(), stderr: stderr.trim() });
    });
  });
}

function maybeJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function jsonText(payload) {
  return typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
}

function toolResult(payload, isError = false) {
  return {
    content: [{ type: "text", text: jsonText(payload) }],
    isError,
  };
}

async function runBackend(args, timeoutMs = 0) {
  const script = resolveBackendCli();
  if (!script || !existsSync(script)) {
    throw new Error(`Barry Video backend not found: ${script || "(empty)"}`);
  }
  const result = await runPython(script, args, { timeoutMs });
  return maybeJson(result.stdout);
}

async function runFlywheel(args, timeoutMs = 0) {
  const script = resolveFlywheelCli();
  if (!script || !existsSync(script)) {
    throw new Error(`Barry Video flywheel backend not found: ${script || "(empty)"}`);
  }
  const result = await runPython(script, args, { timeoutMs });
  return maybeJson(result.stdout);
}

function objectSchema(properties = {}, required = []) {
  return {
    type: "object",
    additionalProperties: false,
    properties,
    ...(required.length ? { required } : {}),
  };
}

const tools = [
  {
    name: "barry_video_user",
    description: "Get the current Inbeidou account profile.",
    inputSchema: objectSchema(),
    call: () => runBackend(["user", "--json"]),
  },
  {
    name: "barry_video_credit",
    description: "Get the current Inbeidou credit balance.",
    inputSchema: objectSchema(),
    call: () => runBackend(["credit", "--json"]),
  },
  {
    name: "barry_video_products",
    description: "List Inbeidou AI products and prices.",
    inputSchema: objectSchema(),
    call: () => runBackend(["products", "--json"]),
  },
  {
    name: "barry_video_languages",
    description: "List supported Inbeidou translation language catalogs.",
    inputSchema: objectSchema({
      type: { type: "string", enum: ["all", "speech", "target", "subtitle"] },
    }),
    call: (params = {}) => {
      const args = ["languages", "--json"];
      addOption(args, "--type", params.type);
      return runBackend(args);
    },
  },
  {
    name: "barry_video_publish_accounts",
    description: "List authorized social publish accounts. Show users only platform/account names; keep IDs internal for later execution.",
    inputSchema: objectSchema({
      platform: { type: "string", enum: PUBLISH_PLATFORMS },
      status: { type: "integer", enum: [0, 1, 2] },
    }),
    call: (params = {}) => {
      const args = ["publish", "accounts", "--json"];
      addOption(args, "--platform", params.platform);
      addOption(args, "--status", params.status);
      return runBackend(args);
    },
  },
  {
    name: "barry_video_novels",
    description: "List novels from the Inbeidou novel content library.",
    inputSchema: objectSchema({
      platform: { type: "string" },
      language: { type: "string" },
      search: { type: "string" },
      page: { type: "integer" },
      size: { type: "integer" },
      order: { type: "string" },
    }),
    call: (params = {}) => {
      const args = ["novels", "list", "--json"];
      addOption(args, "--platform", params.platform);
      addOption(args, "--language", params.language);
      addOption(args, "--search", params.search);
      addOption(args, "--page", params.page);
      addOption(args, "--size", params.size);
      addOption(args, "--order", params.order);
      return runBackend(args);
    },
  },
  {
    name: "barry_video_novel_random",
    description: "Randomly select a novel and fetch its free chapter text without generating a video.",
    inputSchema: objectSchema({
      platform: { type: "string" },
      language: { type: "string" },
      search: { type: "string" },
      page: { type: "integer" },
      size: { type: "integer" },
      order: { type: "string" },
      fullText: { type: "boolean" },
    }),
    call: (params = {}) => {
      const args = ["novels", "random", "--json"];
      addOption(args, "--platform", params.platform);
      addOption(args, "--language", params.language);
      addOption(args, "--search", params.search);
      addOption(args, "--page", params.page);
      addOption(args, "--size", params.size);
      addOption(args, "--order", params.order);
      addFlag(args, params.fullText, "--full-text");
      return runBackend(args);
    },
  },
  {
    name: "barry_video_novel_pipeline",
    description: "Novel workflow: random/search novel, fetch free chapter, generate a novel video with Vidu, and optionally publish to Facebook or TikTok.",
    inputSchema: objectSchema({
      mode: { type: "string", enum: ["random", "generate"] },
      taskId: { type: "string" },
      appId: { type: "string" },
      platform: { type: "string" },
      language: { type: "string" },
      search: { type: "string" },
      page: { type: "integer" },
      size: { type: "integer" },
      order: { type: "string" },
      prompt: { type: "string" },
      timeout: { type: "integer" },
      pollInterval: { type: "integer" },
      viduModel: { type: "string" },
      viduDuration: { type: "integer" },
      viduAspectRatio: { type: "string" },
      viduResolution: { type: "string" },
      viduOffPeak: { type: "boolean" },
      viduWatermark: { type: "boolean" },
      execute: { type: "boolean" },
      publish: { type: "boolean" },
      publishPlatform: { type: "string", enum: PUBLISH_PLATFORMS },
      accountPool: { type: "string" },
      count: { type: "integer" },
      accountIds: { type: "array", items: { type: "string" } },
      teamIds: { type: "array", items: { type: "string" } },
      text: { type: "string" },
      textFile: { type: "string" },
      fullText: { type: "boolean" },
    }),
    call: (params = {}) => {
      if (params.publish && !params.accountIds?.length && !params.teamIds?.length && !params.accountPool) {
        throw new Error("Novel publish requires explicit account ids, team ids, or a configured account pool. Call barry_video_publish_accounts first.");
      }
      const args = ["novels", params.mode === "generate" ? "generate" : "pipeline", "--json"];
      addOption(args, "--task-id", params.taskId);
      addOption(args, "--app-id", params.appId);
      addOption(args, "--platform", params.platform);
      addOption(args, "--language", params.language);
      addOption(args, "--search", params.search);
      addOption(args, "--page", params.page);
      addOption(args, "--size", params.size);
      addOption(args, "--order", params.order);
      addOption(args, "--prompt", params.prompt);
      addOption(args, "--timeout", params.timeout);
      addOption(args, "--poll-interval", params.pollInterval);
      addOption(args, "--vidu-model", params.viduModel);
      addOption(args, "--vidu-duration", params.viduDuration);
      addOption(args, "--vidu-aspect-ratio", params.viduAspectRatio);
      addOption(args, "--vidu-resolution", params.viduResolution);
      addFlag(args, params.viduOffPeak, "--vidu-off-peak");
      addFlag(args, params.viduWatermark, "--vidu-watermark");
      addFlag(args, params.execute, "--execute");
      addFlag(args, !params.execute, "--dry-run");
      addFlag(args, params.publish, "--publish");
      addOption(args, "--publish-platform", params.publishPlatform);
      addOption(args, "--account-pool", params.accountPool);
      addRepeated(args, "--account-id", params.accountIds);
      addRepeated(args, "--team-id", params.teamIds);
      addOption(args, "--count", params.count);
      addOption(args, "--text", params.text);
      addOption(args, "--text-file", params.textFile);
      addFlag(args, params.fullText, "--full-text");
      return runBackend(args, params.timeout ? (Number(params.timeout) + 30) * 1000 : 0);
    },
  },
  {
    name: "barry_video_batch_drama",
    description: "Batch short-drama orchestration: randomly select N dramas from the drama library, choose episodes with data, clip/deduplicate, publish one video per selected/resolved account, poll status, clean local output after successful publish, and return a Chinese per-account publishing detail summary. Requires a user-specified platform and account IDs resolved from the user's account choice, count, or deterministic selector.",
    inputSchema: objectSchema({
      execute: { type: "boolean" },
      count: { type: "integer" },
      platform: { type: "string", enum: PUBLISH_PLATFORMS },
      accountIds: { type: "array", items: { type: "string" } },
      teamIds: { type: "array", items: { type: "string" } },
      allowAccountReuse: { type: "boolean" },
      dramaPlatform: { type: "string" },
      language: { type: "string" },
      dramaOrder: { type: "string" },
      search: { type: "string" },
      episodeOrder: { type: "integer" },
      cutType: { type: "string" },
      duration: { type: "string" },
      outputCount: { type: "integer" },
      scriptCount: { type: "integer" },
      deduplication: { type: "array", items: { type: "string" } },
      watermark: { type: "string" },
      clipConcurrency: { type: "integer" },
      publishConcurrency: { type: "integer" },
      publishRetries: { type: "integer" },
      downloadDir: { type: "string" },
      keepOutput: { type: "boolean" },
      uploadTimeout: { type: "integer" },
      submitTimeout: { type: "integer" },
      timeout: { type: "integer" },
      pollInterval: { type: "number" },
      collectWaitSeconds: { type: "integer" },
      collectPollInterval: { type: "integer" },
    }, ["platform"]),
    call: (params = {}) => {
      const execute = params.execute !== false;
      if (!params.accountIds?.length && !params.teamIds?.length) {
        throw new Error("Batch drama publish requires resolved accountIds or teamIds. Call barry_video_publish_accounts first; ask the user only if the requested platform/count does not determine the account set.");
      }
      const args = ["run-batch-drama", execute ? "--execute" : "--dry-run", "--publish-platform", params.platform];
      addOption(args, "--count", params.count);
      addRepeated(args, "--account-id", params.accountIds);
      addRepeated(args, "--team-id", params.teamIds);
      addFlag(args, params.allowAccountReuse, "--allow-account-reuse");
      addOption(args, "--drama-platform", params.dramaPlatform);
      addOption(args, "--language", params.language);
      addOption(args, "--drama-order", params.dramaOrder);
      addOption(args, "--search", params.search);
      addOption(args, "--episode-order", params.episodeOrder);
      addOption(args, "--cut-type", params.cutType);
      addOption(args, "--duration", params.duration);
      addOption(args, "--output-count", params.outputCount);
      addOption(args, "--script-count", params.scriptCount);
      addRepeated(args, "--deduplication", params.deduplication);
      addOption(args, "--watermark", params.watermark);
      addOption(args, "--clip-concurrency", params.clipConcurrency);
      addOption(args, "--publish-concurrency", params.publishConcurrency);
      addOption(args, "--publish-retries", params.publishRetries);
      addOption(args, "--download-dir", params.downloadDir);
      addFlag(args, params.keepOutput, "--keep-output");
      addOption(args, "--upload-timeout", params.uploadTimeout);
      addOption(args, "--submit-timeout", params.submitTimeout);
      addOption(args, "--timeout", params.timeout);
      addOption(args, "--poll-interval", params.pollInterval);
      addOption(args, "--collect-wait-seconds", params.collectWaitSeconds);
      addOption(args, "--collect-poll-interval", params.collectPollInterval);
      return runFlywheel(args, params.timeout ? (Number(params.timeout) + 600) * 1000 : 0);
    },
  },
  {
    name: "barry_video_local_pipeline",
    description: "Upload a local video, smart clip, normalize to 9:16, publish, poll status, and clean output after success. Requires explicit user-selected platform and account/team.",
    inputSchema: objectSchema({
      file: { type: "string" },
      platform: { type: "string", enum: PUBLISH_PLATFORMS },
      accountIds: { type: "array", items: { type: "string" } },
      teamIds: { type: "array", items: { type: "string" } },
      text: { type: "string" },
      textFile: { type: "string" },
      scheduleAt: { type: "string" },
      cutType: { type: "string" },
      duration: { type: "string" },
      outputCount: { type: "integer" },
      scriptCount: { type: "integer" },
      deduplication: { type: "array", items: { type: "string" } },
      keepOutput: { type: "boolean" },
    }, ["file", "platform"]),
    call: (params = {}) => {
      if (!params.accountIds?.length && !params.teamIds?.length) {
        throw new Error("Local video publish requires a user-selected accountIds or teamIds.");
      }
      const args = ["run-local", "--file", params.file, "--publish-platform", params.platform];
      addRepeated(args, "--account-id", params.accountIds);
      addRepeated(args, "--team-id", params.teamIds);
      addOption(args, "--text", params.text);
      addOption(args, "--text-file", params.textFile);
      addOption(args, "--schedule-at", params.scheduleAt);
      addOption(args, "--cut-type", params.cutType);
      addOption(args, "--duration", params.duration);
      addOption(args, "--output-count", params.outputCount);
      addOption(args, "--script-count", params.scriptCount);
      addRepeated(args, "--deduplication", params.deduplication);
      addFlag(args, params.keepOutput, "--keep-output");
      return runFlywheel(args);
    },
  },
  {
    name: "barry_video_retry_failed_publish",
    description: "Retry the last failed publish tasks once after the user explicitly agrees.",
    inputSchema: objectSchema({
      publishConcurrency: { type: "integer" },
      collectWaitSeconds: { type: "integer" },
      collectPollInterval: { type: "integer" },
      keepOutput: { type: "boolean" },
    }),
    call: (params = {}) => {
      const args = ["retry-failed-publish"];
      addOption(args, "--publish-concurrency", params.publishConcurrency);
      addOption(args, "--collect-wait-seconds", params.collectWaitSeconds);
      addOption(args, "--collect-poll-interval", params.collectPollInterval);
      addFlag(args, params.keepOutput, "--keep-output");
      return runFlywheel(args);
    },
  },
  {
    name: "barry_video_discard_failed_publish_output",
    description: "Delete retained local clips for the last failed publish tasks after the user decides not to continue retrying.",
    inputSchema: objectSchema(),
    call: () => runFlywheel(["discard-failed-publish-output"]),
  },
  {
    name: "barry_video_failed_publish_paths",
    description: "Show retained local clip paths for the last failed publish tasks when the user explicitly asks for the paths.",
    inputSchema: objectSchema(),
    call: () => runFlywheel(["show-failed-publish-paths"]),
  },
  {
    name: "barry_video_backend",
    description: "Advanced fallback: run raw inbeidou_cli.py arguments from the installed Barry Video backend.",
    inputSchema: objectSchema({
      args: { type: "array", items: { type: "string" } },
    }, ["args"]),
    call: (params = {}) => runBackend(Array.isArray(params.args) ? params.args : []),
  },
];

const toolsByName = new Map(tools.map((tool) => [tool.name, tool]));

function sendMessage(message) {
  const body = JSON.stringify(message);
  process.stdout.write(`Content-Length: ${Buffer.byteLength(body, "utf8")}\r\n\r\n${body}`);
}

function sendResult(id, result) {
  sendMessage({ jsonrpc: "2.0", id, result });
}

function sendError(id, code, message, data) {
  sendMessage({
    jsonrpc: "2.0",
    id,
    error: { code, message, ...(data !== undefined ? { data } : {}) },
  });
}

async function handleRequest(request) {
  if (!request || request.jsonrpc !== "2.0") return;
  const { id, method, params = {} } = request;

  try {
    if (method === "initialize") {
      sendResult(id, {
        protocolVersion: params.protocolVersion || DEFAULT_PROTOCOL_VERSION,
        capabilities: { tools: {} },
        serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
      });
      return;
    }
    if (method === "notifications/initialized" || method?.startsWith("notifications/")) {
      return;
    }
    if (method === "tools/list") {
      sendResult(id, {
        tools: tools.map(({ call, ...definition }) => definition),
      });
      return;
    }
    if (method === "tools/call") {
      const tool = toolsByName.get(params.name);
      if (!tool) {
        sendError(id, -32602, `Unknown tool: ${params.name}`);
        return;
      }
      try {
        const payload = await tool.call(params.arguments || {});
        sendResult(id, toolResult(payload));
      } catch (error) {
        sendResult(id, toolResult(error?.message || String(error), true));
      }
      return;
    }
    if (method === "ping") {
      sendResult(id, {});
      return;
    }
    sendError(id, -32601, `Method not found: ${method}`);
  } catch (error) {
    sendError(id, -32603, error?.message || String(error));
  }
}

let buffer = Buffer.alloc(0);

function processBuffer() {
  while (true) {
    const headerEnd = buffer.indexOf("\r\n\r\n");
    if (headerEnd === -1) return;
    const header = buffer.slice(0, headerEnd).toString("utf8");
    const lengthLine = header.split("\r\n").find((line) => /^Content-Length:/i.test(line));
    if (!lengthLine) {
      buffer = buffer.slice(headerEnd + 4);
      continue;
    }
    const length = Number(lengthLine.split(":")[1].trim());
    const bodyStart = headerEnd + 4;
    const bodyEnd = bodyStart + length;
    if (buffer.length < bodyEnd) return;
    const body = buffer.slice(bodyStart, bodyEnd).toString("utf8");
    buffer = buffer.slice(bodyEnd);
    try {
      void handleRequest(JSON.parse(body));
    } catch (error) {
      sendError(null, -32700, error?.message || "Parse error");
    }
  }
}

process.stdin.on("data", (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  processBuffer();
});

process.stdin.on("end", () => {
  process.exit(0);
});
