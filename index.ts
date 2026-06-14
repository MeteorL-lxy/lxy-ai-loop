import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PLUGIN_ID = "barry-video";
const PLUGIN_NAME = "Barry Video";
const PLUGIN_ROOT = path.dirname(fileURLToPath(import.meta.url));
const PRIVATE_BACKEND = path.join(PLUGIN_ROOT, "backend", "inbeidou_cli.py");
const PRIVATE_FLYWHEEL_BACKEND = path.join(PLUGIN_ROOT, "backend", "flywheel_cli.py");
const PLATFORMS = ["TIKTOK", "FACEBOOK", "INSTAGRAM", "YOUTUBE"];
const PLATFORM_LABELS = {
  TIKTOK: "TikTok",
  FACEBOOK: "Facebook",
  INSTAGRAM: "Instagram",
  YOUTUBE: "YouTube"
};
const CUT_TYPES = ["high_cut", "golden_three", "golden_clips", "high_pre"];
const DEDUP_OPTIONS = [
  "common_deduplication",
  "apply_pip",
  "apply_rotate",
  "apply_scale",
  "apply_flip",
  "apply_frame",
  "apply_special",
  "apply_speed",
  "apply_reduce_frame_rate",
  "apply_mirror_pip"
];
const CLIP_METHOD_DETAILS = {
  high_cut: {
    code: "high_cut",
    name: "高燃卡点",
    summary: "围绕情绪高点和冲突点做强节奏混剪，适合短剧拉新和爆点预告。",
    bestFor: "强冲突、反转、情绪爆发类片段",
    cautions: "剧情交代会被压缩，不适合信息量很重的长铺垫片段。"
  },
  golden_three: {
    code: "golden_three",
    name: "黄金三段式",
    summary: "按起势、冲突、钩子三段组织内容，适合做结构清晰的短视频成片。",
    bestFor: "单集剧情完整、适合讲一个小闭环的素材",
    cautions: "如果原片爆点太少，三段结构会显得平。"
  },
  golden_clips: {
    code: "golden_clips",
    name: "黄金片段提取",
    summary: "优先抽取系统识别的高价值瞬间，适合快速测试多条短片。",
    bestFor: "先批量试爆点、快速出多个版本",
    cautions: "片段之间可能更碎，叙事连贯性较弱。"
  },
  high_pre: {
    code: "high_pre",
    name: "预告向高燃",
    summary: "更偏预告片表达，强调悬念、冲突和停留点。",
    bestFor: "拉点击、引导进入正片、做预告型投放",
    cautions: "适合作为预告，不一定适合完整剧情表达。"
  }
};
const DEDUP_METHOD_DETAILS = {
  common_deduplication: {
    code: "common_deduplication",
    name: "基础去重",
    summary: "做通用层面的轻度去重处理，是最稳妥的默认项。",
    bestFor: "几乎所有发布场景",
    cautions: "单独使用时差异化有限。"
  },
  apply_pip: {
    code: "apply_pip",
    name: "画中画去重",
    summary: "在画面中叠加辅助区域，改变画面布局。",
    bestFor: "需要快速拉开与原片视觉差异",
    cautions: "处理过重会影响观感。"
  },
  apply_rotate: {
    code: "apply_rotate",
    name: "旋转去重",
    summary: "对画面做轻微旋转或角度偏移。",
    bestFor: "搭配基础去重、小幅度差异化",
    cautions: "幅度过大容易影响观看舒适度。"
  },
  apply_scale: {
    code: "apply_scale",
    name: "缩放去重",
    summary: "通过轻微放大或缩小改变构图。",
    bestFor: "主体明显、边缘信息不重要的素材",
    cautions: "放大过多会损失边缘内容。"
  },
  apply_flip: {
    code: "apply_flip",
    name: "翻转去重",
    summary: "对画面做镜像翻转。",
    bestFor: "镜头语言不依赖左右方向的内容",
    cautions: "字幕、方向性元素可能会变得不自然。"
  },
  apply_frame: {
    code: "apply_frame",
    name: "边框去重",
    summary: "通过增加边框或包装层改变整体画面观感。",
    bestFor: "想做较明显外观差异时",
    cautions: "边框太重会显得像模板感很强的搬运。"
  },
  apply_special: {
    code: "apply_special",
    name: "特效去重",
    summary: "加入一些视觉特效来制造差异。",
    bestFor: "需要更强差异化测试的场景",
    cautions: "过度特效会降低短剧沉浸感。"
  },
  apply_speed: {
    code: "apply_speed",
    name: "变速去重",
    summary: "通过微调播放速度改变节奏和指纹。",
    bestFor: "情绪推进明确、对口型要求不高的片段",
    cautions: "人物说话和动作会更容易失真。"
  },
  apply_reduce_frame_rate: {
    code: "apply_reduce_frame_rate",
    name: "降帧去重",
    summary: "减少帧率来改变视频特征。",
    bestFor: "对流畅度要求不高的测试稿",
    cautions: "会牺牲一部分顺滑感。"
  },
  apply_mirror_pip: {
    code: "apply_mirror_pip",
    name: "镜像画中画",
    summary: "结合镜像和画中画做更强的版式差异。",
    bestFor: "需要明显视觉区分的重复投放",
    cautions: "属于较重的去重方式，观感要重点把控。"
  }
};
const CONFIG_SCHEMA = {
  type: "object",
  additionalProperties: false,
  properties: {
    pythonBin: {
      type: "string",
      default: "python3",
      description: "Python executable used to run the Inbeidou backend CLI."
    },
    backendCli: {
      type: "string",
      default: "~/inbeidou_cli.py",
      description: "Absolute path to the existing inbeidou_cli.py backend script."
    },
    flywheelCli: {
      type: "string",
      default: "",
      description: "Optional path to flywheel_cli.py for local video and automatic flywheel workflows."
    },
    authToken: {
      type: "string",
      default: "",
      description: "Optional Inbeidou token passed to the backend as INBEIDOU_TOKEN."
    },
    downloadDir: {
      type: "string",
      default: "~/Desktop",
      description: "Default output directory for downloaded clipped or translated videos."
    },
    defaultAccountIds: {
      type: "array",
      items: { type: "string" },
      default: [],
      description: "Legacy default publish account IDs. Natural-language publish flows require an explicit user-selected account."
    },
    defaultTeamIds: {
      type: "array",
      items: { type: "string" },
      default: [],
      description: "Legacy default publish team IDs. Natural-language publish flows require an explicit user-selected account or team."
    },
    defaultPublishPlatform: {
      type: "string",
      enum: PLATFORMS,
      default: "FACEBOOK",
      description: "Legacy default social platform. Natural-language publish flows require an explicit user-selected platform."
    },
    defaultDramaPlatform: {
      type: "string",
      default: "dramabox",
      description: "Default short drama platform when users ask for latest dramas."
    },
    defaultLanguage: {
      type: "string",
      default: "2",
      description: "Default language ID for short drama listing."
    },
    defaultDramaOrder: {
      type: "string",
      default: "publish_at",
      description: "Default sort field for short drama listing."
    }
  }
};

function expandHome(value) {
  if (typeof value !== "string" || value.length === 0) {
    return value;
  }
  if (value === "~") {
    return os.homedir();
  }
  if (value.startsWith("~/")) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}

function normalizeList(value) {
  if (value === undefined || value === null || value === "") {
    return [];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => normalizeList(item));
  }
  if (typeof value === "string") {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [String(value)];
}

function getPluginConfig(api) {
  const entries = api?.config?.plugins?.entries || {};
  const entry = entries[PLUGIN_ID] || {};
  const config = entry.config || {};
  return config && typeof config === "object" ? config : {};
}

function getRuntimeDefaults(api) {
  const config = getPluginConfig(api);
  return {
    defaultAccountIds: normalizeList(config.defaultAccountIds),
    defaultTeamIds: normalizeList(config.defaultTeamIds),
    defaultPublishPlatform: config.defaultPublishPlatform || "FACEBOOK",
    defaultDramaPlatform: config.defaultDramaPlatform || "dramabox",
    defaultLanguage: String(config.defaultLanguage || "2"),
    defaultDramaOrder: config.defaultDramaOrder || "publish_at"
  };
}

function resolvePythonBin(api) {
  const config = getPluginConfig(api);
  return config.pythonBin || process.env.BARRY_VIDEO_PYTHON || "python3";
}

function readBeidouAuthToken() {
  const authStatePath = path.join(os.homedir(), ".barry-video", "auth_state.json");
  try {
    const raw = readFileSync(authStatePath, "utf8");
    const state = JSON.parse(raw);
    if (
      state.access_token &&
      state.status === "success" &&
      state.expired_at &&
      state.expired_at > Date.now()
    ) {
      return state.access_token;
    }
  } catch {
    // no valid beidou auth state
  }
  return "";
}

function resolveAuthToken(api) {
  const config = getPluginConfig(api);
  return (
    config.authToken ||
    process.env.BARRY_VIDEO_AUTH_TOKEN ||
    process.env.BARRY_VIDEO_TOKEN ||
    process.env.INBEIDOU_TOKEN ||
    readBeidouAuthToken() ||
    ""
  );
}

function resolveBackendCli(api) {
  const config = getPluginConfig(api);
  const candidates = [
    expandHome(process.env.BARRY_VIDEO_BACKEND || ""),
    PRIVATE_BACKEND,
    expandHome(config.backendCli || ""),
    path.join(os.homedir(), "inbeidou_cli.py"),
    "/Users/ming/inbeidou_cli.py"
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return candidates[0] || "";
}

function resolveFlywheelCli(api) {
  const config = getPluginConfig(api);
  const candidates = [
    expandHome(process.env.BARRY_VIDEO_FLYWHEEL || ""),
    expandHome(process.env.BARRY_VIDEO_FLYWHEEL_BACKEND || ""),
    PRIVATE_FLYWHEEL_BACKEND,
    expandHome(config.flywheelCli || "")
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return candidates[0] || "";
}

function resolveDownloadDir(api, overrideDir) {
  const config = getPluginConfig(api);
  return expandHome(overrideDir || config.downloadDir || path.join(os.homedir(), "Desktop"));
}

function addOption(args, flag, value) {
  if (value !== undefined && value !== null && value !== "") {
    args.push(flag, String(value));
  }
}

function addFlag(args, enabled, flag) {
  if (enabled) {
    args.push(flag);
  }
}

function addRepeatedOptions(args, flag, values) {
  for (const value of normalizeList(values)) {
    args.push(flag, String(value));
  }
}

function maybeParseJson(text) {
  const raw = String(text || "").trim();
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function requireAny(params, keys, message) {
  const found = keys.some((key) => params[key] !== undefined && params[key] !== null && params[key] !== "");
  if (!found) {
    throw new Error(message);
  }
}

function requireNonEmptyList(values, message) {
  if (normalizeList(values).length === 0) {
    throw new Error(message);
  }
}

function toolResponse(title, payload, command) {
  const parts = [title];
  if (command) {
    parts.push(`command: ${command}`);
  }
  if (payload !== undefined && payload !== null) {
    if (typeof payload === "string") {
      parts.push(payload.trim());
    } else {
      parts.push(JSON.stringify(payload, null, 2));
    }
  }
  return {
    content: [
      {
        type: "text",
        text: parts.filter(Boolean).join("\n\n")
      }
    ]
  };
}

function explainClipMethods(params = {}) {
  const includeClip = params.category !== "deduplication";
  const includeDedup = params.category !== "clip";
  const clipMethods = Object.values(CLIP_METHOD_DETAILS);
  const dedupMethods = Object.values(DEDUP_METHOD_DETAILS);
  const recommended = {
    dramaDefaultClip: CLIP_METHOD_DETAILS.high_cut,
    dramaDefaultDedup: [
      DEDUP_METHOD_DETAILS.common_deduplication,
      DEDUP_METHOD_DETAILS.apply_pip
    ]
  };
  return {
    summary: "以下是面向用户可解释的剪辑手法与去重手法说明。",
    clipMethods: includeClip ? clipMethods : [],
    deduplicationMethods: includeDedup ? dedupMethods : [],
    recommended
  };
}

function platformLabel(value) {
  const key = String(value || "").trim().toUpperCase();
  return PLATFORM_LABELS[key] || String(value || "").trim();
}

function accountDisplayName(account = {}) {
  const channels = Array.isArray(account.channels) ? account.channels : [];
  return (
    String(account.social_name || "").trim()
    || String(channels[0]?.name || "").trim()
    || `${platformLabel(account.type)} 账号`
  );
}

function formatPublishAccountChoices(payload) {
  const accounts = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.items)
      ? payload.items
      : [];
  const choices = accounts.map((account, index) => {
    const platform = String(account.type || account.platform || "").trim().toUpperCase();
    const name = accountDisplayName(account);
    return {
      序号: index + 1,
      平台: platformLabel(platform),
      账号: name
    };
  });
  const internalMap = accounts.map((account, index) => {
    const platform = String(account.type || account.platform || "").trim().toUpperCase();
    return {
      choiceNumber: index + 1,
      choiceLabel: `${platformLabel(platform)}：${accountDisplayName(account)}`,
      platform,
      accountIds: account.id ? [String(account.id)] : [],
      teamIds: account.team_id ? [String(account.team_id)] : []
    };
  });
  return {
    展示给用户: choices,
    用户提示: "请选择要发布到哪个平台账号，例如：发布到 TikTok 的 meteor_l0。",
    internal_use_only: {
      note: "For tool execution only. Do not show accountIds or teamIds to the user.",
      publishTargets: internalMap
    }
  };
}

async function runBackend(api, cliArgs, options = {}) {
  const pythonBin = resolvePythonBin(api);
  const backendCli = resolveBackendCli(api);
  const authToken = resolveAuthToken(api);

  if (!backendCli) {
    throw new Error("Barry Video backend is not configured. Set plugins.entries['barry-video'].config.backendCli.");
  }
  if (!existsSync(backendCli)) {
    throw new Error(`Barry Video backend does not exist: ${backendCli}`);
  }

  const commandArgs = [backendCli, ...cliArgs];
  const command = [pythonBin, ...commandArgs].join(" ");

  return await new Promise((resolve, reject) => {
    const child = spawn(pythonBin, commandArgs, {
      env: {
        ...process.env,
        ...(authToken ? { INBEIDOU_TOKEN: authToken } : {})
      },
      stdio: ["ignore", "pipe", "pipe"]
    });

    let stdout = "";
    let stderr = "";
    let settled = false;
    let timer = null;

    if (options.timeoutMs && Number(options.timeoutMs) > 0) {
      timer = setTimeout(() => {
        child.kill("SIGTERM");
      }, Number(options.timeoutMs));
    }

    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });

    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });

    child.on("error", (error) => {
      if (timer) {
        clearTimeout(timer);
      }
      if (!settled) {
        settled = true;
        reject(error);
      }
    });

    child.on("close", (code) => {
      if (timer) {
        clearTimeout(timer);
      }
      if (settled) {
        return;
      }
      settled = true;
      if (code !== 0) {
        reject(new Error(`Command failed (${code}): ${command}\n${stderr || stdout}`.trim()));
        return;
      }
      resolve({
        command,
        stdout: stdout.trim(),
        stderr: stderr.trim()
      });
    });
  });
}

async function runFlywheelBackend(api, cliArgs, options = {}) {
  const pythonBin = resolvePythonBin(api);
  const flywheelCli = resolveFlywheelCli(api);
  const authToken = resolveAuthToken(api);

  if (!flywheelCli) {
    throw new Error("Barry Video flywheel backend is not configured. Set plugins.entries['barry-video'].config.flywheelCli.");
  }
  if (!existsSync(flywheelCli)) {
    throw new Error(`Barry Video flywheel backend does not exist: ${flywheelCli}`);
  }

  const commandArgs = [flywheelCli, ...cliArgs];
  const command = [pythonBin, ...commandArgs].join(" ");

  return await new Promise((resolve, reject) => {
    const child = spawn(pythonBin, commandArgs, {
      env: {
        ...process.env,
        ...(authToken ? { INBEIDOU_TOKEN: authToken } : {})
      },
      stdio: ["ignore", "pipe", "pipe"]
    });

    let stdout = "";
    let stderr = "";
    let settled = false;
    let timer = null;

    if (options.timeoutMs && Number(options.timeoutMs) > 0) {
      timer = setTimeout(() => {
        child.kill("SIGTERM");
      }, Number(options.timeoutMs));
    }

    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });

    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });

    child.on("error", (error) => {
      if (timer) {
        clearTimeout(timer);
      }
      if (!settled) {
        settled = true;
        reject(error);
      }
    });

    child.on("close", (code) => {
      if (timer) {
        clearTimeout(timer);
      }
      if (settled) {
        return;
      }
      settled = true;
      if (code !== 0) {
        reject(new Error(`Command failed (${code}): ${command}\n${stderr || stdout}`.trim()));
        return;
      }
      resolve({
        command,
        stdout: stdout.trim(),
        stderr: stderr.trim()
      });
    });
  });
}

async function runJsonTool(api, title, cliArgs, options = {}) {
  const result = await runBackend(api, cliArgs, options);
  const payload = maybeParseJson(result.stdout);
  return toolResponse(title, payload ?? result.stdout, result.command);
}

function buildClipArgs(params) {
  requireMediaSource(params, "clip");
  const args = ["clip", "create"];
  addOption(args, "--file", params.file);
  addOption(args, "--upload-id", params.uploadId);
  addOption(args, "--window-id", params.windowId);
  addDramaSourceOptions(args, params);
  addOption(args, "--cut-type", params.cutType);
  addOption(args, "--duration", params.duration);
  addOption(args, "--output-count", params.outputCount);
  addOption(args, "--script-count", params.scriptCount);
  for (const value of normalizeList(params.deduplication)) {
    args.push("--deduplication", value);
  }
  addOption(args, "--watermark", params.watermark);
  addFlag(args, params.mergeVideo, "--merge-video");
  addFlag(args, params.wait !== false, "--wait");
  addOption(args, "--upload-timeout", params.uploadTimeout);
  addOption(args, "--submit-timeout", params.submitTimeout);
  addOption(args, "--timeout", params.timeout);
  addOption(args, "--poll-interval", params.pollInterval);
  args.push("--json");
  return args;
}

function buildTranslateArgs(params) {
  requireMediaSource(params, "translate");
  if (!params.targetLang) {
    throw new Error("translate requires targetLang");
  }
  const args = ["translate", "create"];
  addOption(args, "--file", params.file);
  addOption(args, "--upload-id", params.uploadId);
  addOption(args, "--window-id", params.windowId);
  addDramaSourceOptions(args, params);
  addOption(args, "--source-lang", params.sourceLang);
  addOption(args, "--lang", params.targetLang);
  addOption(args, "--subtitle-type", params.subtitleType);
  addFlag(args, params.noSpeechTranslate, "--no-speech-translate");
  addOption(args, "--font", params.font);
  addOption(args, "--font-size", params.fontSize);
  addOption(args, "--font-color", params.fontColor);
  addOption(args, "--font-opacity", params.fontOpacity);
  addOption(args, "--subtitle-y", params.subtitleY);
  addOption(args, "--alignment", params.alignment);
  addOption(args, "--effect-style", params.effectStyle);
  addFlag(args, params.bold, "--bold");
  addFlag(args, params.underline, "--underline");
  addFlag(args, params.italic, "--italic");
  addFlag(args, params.shadow, "--shadow");
  addOption(args, "--shadow-shift", params.shadowShift);
  addOption(args, "--shadow-x-bord", params.shadowXBord);
  addOption(args, "--shadow-y-bord", params.shadowYBord);
  addOption(args, "--shadow-opacity", params.shadowOpacity);
  addFlag(args, params.outline, "--outline");
  addOption(args, "--outline-board", params.outlineBoard);
  addFlag(args, params.mergeVideo, "--merge-video");
  addFlag(args, params.wait !== false, "--wait");
  addOption(args, "--upload-timeout", params.uploadTimeout);
  addOption(args, "--submit-timeout", params.submitTimeout);
  addOption(args, "--timeout", params.timeout);
  addOption(args, "--poll-interval", params.pollInterval);
  args.push("--json");
  return args;
}

function resolvePublishTargets(api, params) {
  const accountIds = normalizeList(params.accountIds);
  const teamIds = normalizeList(params.teamIds);
  return { accountIds, teamIds };
}

function requireExplicitPublishChoice(params = {}, action = "publish") {
  const accountIds = normalizeList(params.accountIds);
  const teamIds = normalizeList(params.teamIds);
  if (!params.platform) {
    throw new Error(`${action} requires an explicit platform selected by the user. Call barry_video_publish_accounts first, list the available platforms/accounts, and ask the user which one to use.`);
  }
  if (accountIds.length === 0 && teamIds.length === 0) {
    throw new Error(`${action} requires an explicit accountIds or teamIds selected by the user. Call barry_video_publish_accounts first, list the available platforms/accounts, and ask the user which account to use.`);
  }
}

function buildPublishArgs(api, params) {
  requireExplicitPublishChoice(params, "publish");
  const { accountIds, teamIds } = resolvePublishTargets(api, params);

  const args = ["publish", "create", "--json"];
  addRepeatedOptions(args, "--account-id", accountIds);
  addRepeatedOptions(args, "--team-id", teamIds);
  addOption(args, "--platform", params.platform);
  addOption(args, "--text", params.text);
  addOption(args, "--text-file", params.textFile);
  addOption(args, "--file", params.file);
  addOption(args, "--file-url", params.fileUrl);
  addOption(args, "--schedule-at", params.scheduleAt);
  addFlag(args, params.dryRun, "--dry-run");
  return args;
}

function buildFlywheelLocalArgs(api, params = {}) {
  if (!params.file) {
    throw new Error("local video workflow requires file");
  }
  requireExplicitPublishChoice(params, "local video workflow");
  const accountIds = normalizeList(params.accountIds);
  const teamIds = normalizeList(params.teamIds);
  const args = ["run-local", "--file", params.file];
  addRepeatedOptions(args, "--account-id", accountIds);
  addRepeatedOptions(args, "--team-id", teamIds);
  addOption(args, "--publish-platform", params.platform);
  addOption(args, "--text", params.text);
  addOption(args, "--text-file", params.textFile);
  addOption(args, "--schedule-at", params.scheduleAt);
  addOption(args, "--download-dir", params.downloadDir);
  addFlag(args, params.keepOutput, "--keep-output");
  addOption(args, "--cut-type", params.cutType);
  addOption(args, "--duration", params.duration);
  addOption(args, "--output-count", params.outputCount);
  addOption(args, "--script-count", params.scriptCount);
  for (const value of normalizeList(params.deduplication)) {
    args.push("--deduplication", value);
  }
  addOption(args, "--watermark", params.watermark);
  addFlag(args, params.mergeVideo, "--merge-video");
  addOption(args, "--upload-timeout", params.uploadTimeout);
  addOption(args, "--submit-timeout", params.submitTimeout);
  addOption(args, "--timeout", params.timeout);
  addOption(args, "--poll-interval", params.pollInterval);
  addOption(args, "--collect-wait-seconds", params.collectWaitSeconds);
  addOption(args, "--collect-poll-interval", params.collectPollInterval);
  return args;
}

function buildFlywheelBatchDramaArgs(api, params = {}) {
  const accountIds = normalizeList(params.accountIds);
  const teamIds = normalizeList(params.teamIds);
  if (!params.platform) {
    throw new Error("batch drama workflow requires an explicit platform selected by the user.");
  }
  const allowFacebookDramaPoolAutoSelect =
    String(params.platform || "").toUpperCase() === "FACEBOOK" && accountIds.length === 0 && teamIds.length === 0;
  if (!allowFacebookDramaPoolAutoSelect && accountIds.length === 0 && teamIds.length === 0) {
    throw new Error("batch drama workflow requires explicit accountIds or teamIds selected by the user.");
  }
  const args = ["run-batch-drama", params.execute ? "--execute" : "--dry-run"];
  addOption(args, "--count", params.count);
  addRepeatedOptions(args, "--account-id", accountIds);
  addRepeatedOptions(args, "--team-id", teamIds);
  addOption(args, "--publish-platform", params.platform);
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
  for (const value of normalizeList(params.deduplication)) {
    args.push("--deduplication", value);
  }
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
  return args;
}

function hasDramaEpisodeSource(params = {}) {
  return ["taskId", "search", "serialId", "appId", "episodeOrder"].some(
    (key) => params[key] !== undefined && params[key] !== null && params[key] !== ""
  );
}

function requireMediaSource(params = {}, action = "tool") {
  if (params.file || params.uploadId) {
    return;
  }
  if (hasDramaEpisodeSource(params)) {
    if (params.episodeOrder === undefined || params.episodeOrder === null || params.episodeOrder === "") {
      throw new Error(`${action} drama source requires episodeOrder`);
    }
    if (!params.taskId && !params.search && !params.serialId) {
      throw new Error(`${action} drama source requires taskId, search, or serialId`);
    }
    if (params.serialId && !params.taskId && !params.search && !params.appId) {
      throw new Error(`${action} drama source with serialId requires appId`);
    }
    return;
  }
  throw new Error(`${action} requires file, uploadId, or drama episode source`);
}

function addDramaSourceOptions(args, params = {}) {
  addOption(args, "--task-id", params.taskId);
  addOption(args, "--search", params.search);
  addOption(args, "--serial-id", params.serialId);
  addOption(args, "--app-id", params.appId);
  addOption(args, "--episode-order", params.episodeOrder);
  addOption(args, "--drama-platform", params.dramaPlatform);
  addOption(args, "--drama-language", params.dramaLanguage);
  addOption(args, "--drama-order", params.dramaOrder);
  addOption(args, "--drama-task-type", params.dramaTaskType);
  addOption(args, "--search-size", params.searchSize);
}

function buildDramaArgs(api, params = {}) {
  const defaults = getRuntimeDefaults(api);
  const args = ["list"];
  addOption(args, "--platform", params.platform || defaults.defaultDramaPlatform);
  addOption(args, "--language", params.language || defaults.defaultLanguage);
  addOption(args, "--search", params.search);
  addOption(args, "--page", params.page);
  addOption(args, "--size", params.size);
  addOption(args, "--order", params.order || defaults.defaultDramaOrder);
  args.push("--json");
  return args;
}

function buildDramaDetailArgs(api, params = {}) {
  const defaults = getRuntimeDefaults(api);
  const args = ["detail"];
  addOption(args, "--task-id", params.taskId);
  addOption(args, "--platform", params.platform);
  addOption(args, "--language", params.language || defaults.defaultLanguage);
  addOption(args, "--search", params.search);
  addOption(args, "--size", params.size);
  addOption(args, "--order", params.order || defaults.defaultDramaOrder);
  addOption(args, "--task-type", params.taskType);
  addRepeatedOptions(args, "--promote-platform", params.promotionPlatforms);
  addFlag(args, params.allPromotionPlatforms, "--all-promote-platforms");
  addFlag(args, params.noPromotionLinks, "--no-promotion-links");
  args.push("--json");
  return args;
}

function addNovelSourceOptions(args, params = {}) {
  addOption(args, "--task-id", params.taskId);
  addOption(args, "--app-id", params.appId);
  addOption(args, "--platform", params.platform);
  addOption(args, "--language", params.language);
  addOption(args, "--search", params.search);
  addOption(args, "--page", params.page);
  addOption(args, "--size", params.size);
  addOption(args, "--order", params.order);
}

function buildNovelListArgs(params = {}) {
  const args = ["novels", "list"];
  addOption(args, "--platform", params.platform);
  addOption(args, "--language", params.language);
  addOption(args, "--search", params.search);
  addOption(args, "--page", params.page);
  addOption(args, "--size", params.size);
  addOption(args, "--order", params.order);
  args.push("--json");
  return args;
}

function buildNovelActionArgs(action, params = {}) {
  const args = ["novels", action];
  addNovelSourceOptions(args, params);
  addFlag(args, params.fullText, "--full-text");
  args.push("--json");
  return args;
}

function buildNovelPipelineArgs(params = {}) {
  const inferredPublishPlatform = params.publishPlatform || "FACEBOOK";
  const defaultAccountPool =
    params.publish && !params.accountPool && inferredPublishPlatform === "FACEBOOK"
      ? "facebook_novel_dedicated_10"
      : params.accountPool;
  if (params.publish) {
    const accountIds = normalizeList(params.accountIds);
    const teamIds = normalizeList(params.teamIds);
    if (accountIds.length === 0 && teamIds.length === 0 && !defaultAccountPool) {
      throw new Error("Novel publish requires explicit account ids, team ids, or a configured account pool. Call barry_video_publish_accounts first if you need to choose accounts.");
    }
  }
  const args = ["novels", params.mode === "generate" ? "generate" : "pipeline"];
  addNovelSourceOptions(args, params);
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
  addOption(args, "--account-pool", defaultAccountPool);
  addRepeatedOptions(args, "--account-id", normalizeList(params.accountIds));
  addRepeatedOptions(args, "--team-id", normalizeList(params.teamIds));
  addOption(args, "--count", params.count);
  addOption(args, "--text", params.text);
  addOption(args, "--text-file", params.textFile);
  addFlag(args, params.fullText, "--full-text");
  args.push("--json");
  return args;
}

function buildDramaEpisodeListArgs(api, params = {}) {
  const defaults = getRuntimeDefaults(api);
  const args = ["episodes", "list"];
  addOption(args, "--task-id", params.taskId);
  addOption(args, "--search", params.search);
  addOption(args, "--serial-id", params.serialId);
  addOption(args, "--app-id", params.appId);
  addOption(args, "--drama-platform", params.dramaPlatform);
  addOption(args, "--drama-language", params.dramaLanguage || defaults.defaultLanguage);
  addOption(args, "--drama-order", params.dramaOrder || defaults.defaultDramaOrder);
  addOption(args, "--drama-task-type", params.dramaTaskType);
  addOption(args, "--search-size", params.searchSize);
  addOption(args, "--episode-orders", params.episodeOrders);
  addOption(args, "--start", params.start);
  addOption(args, "--end", params.end);
  addOption(args, "--video-type", params.videoType);
  args.push("--json");
  return args;
}

function buildDramaEpisodeFetchArgs(api, params = {}) {
  const defaults = getRuntimeDefaults(api);
  if (params.episodeOrder === undefined || params.episodeOrder === null || params.episodeOrder === "") {
    throw new Error("drama episode fetch requires episodeOrder");
  }
  if (!params.taskId && !params.search && !params.serialId) {
    throw new Error("drama episode fetch requires taskId, search, or serialId");
  }
  if (params.serialId && !params.taskId && !params.search && !params.appId) {
    throw new Error("drama episode fetch with serialId requires appId");
  }
  const args = ["episodes", "fetch"];
  addOption(args, "--task-id", params.taskId);
  addOption(args, "--search", params.search);
  addOption(args, "--serial-id", params.serialId);
  addOption(args, "--app-id", params.appId);
  addOption(args, "--episode-order", params.episodeOrder);
  addOption(args, "--drama-platform", params.dramaPlatform);
  addOption(args, "--drama-language", params.dramaLanguage || defaults.defaultLanguage);
  addOption(args, "--drama-order", params.dramaOrder || defaults.defaultDramaOrder);
  addOption(args, "--drama-task-type", params.dramaTaskType);
  addOption(args, "--search-size", params.searchSize);
  addOption(args, "--upload-timeout", params.uploadTimeout);
  addOption(args, "--poll-interval", params.pollInterval);
  args.push("--json");
  return args;
}

function buildUploadListArgs(params = {}) {
  const args = ["uploads", "list", "--json"];
  addOption(args, "--page", params.page);
  addOption(args, "--size", params.size);
  return args;
}

function buildManusListArgs(params = {}) {
  const args = ["manus", "list", "--json"];
  addOption(args, "--page", params.page);
  addOption(args, "--size", params.size);
  addOption(args, "--search", params.search);
  return args;
}

function registerJsonTool(api, definition, argsBuilder) {
  api.registerTool({
    ...definition,
    async execute(_id, params = {}) {
      return await runJsonTool(api, definition.description, argsBuilder(params));
    }
  });
}

function registerBarryTools(api) {
  registerJsonTool(
    api,
    {
      name: "barry_video_user",
      description: "Get the current Inbeidou account profile.",
      parameters: { type: "object", additionalProperties: false, properties: {} }
    },
    () => ["user", "--json"]
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_credit",
      description: "Get the current Inbeidou credit balance.",
      parameters: { type: "object", additionalProperties: false, properties: {} }
    },
    () => ["credit", "--json"]
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_products",
      description: "List Inbeidou AI products and prices.",
      parameters: { type: "object", additionalProperties: false, properties: {} }
    },
    () => ["products", "--json"]
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_languages",
      description: "List supported Inbeidou translation language catalogs.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          type: { type: "string", enum: ["all", "speech", "target", "subtitle"] }
        }
      }
    },
    (params) => {
      const args = ["languages", "--json"];
      addOption(args, "--type", params.type);
      return args;
    }
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_dramas",
      description: "List short dramas from Dramabox, ShortMax, or other supported platforms.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          platform: { type: "string" },
          language: { type: "string" },
          search: { type: "string" },
          page: { type: "integer" },
          size: { type: "integer" },
          order: { type: "string" }
        }
      }
    },
    (params) => buildDramaArgs(api, params)
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_drama_detail",
      description: "Get short drama detail and promotion links from the task detail flow.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          taskId: { type: "string" },
          platform: { type: "string" },
          language: { type: "string" },
          search: { type: "string" },
          size: { type: "integer" },
          order: { type: "string" },
          taskType: { type: "string" },
          promotionPlatforms: {
            type: "array",
            items: { type: "string", enum: ["1", "2", "3", "4", "TikTok", "Facebook", "Instagram", "YouTube"] }
          },
          allPromotionPlatforms: { type: "boolean" },
          noPromotionLinks: { type: "boolean" }
        }
      }
    },
    (params) => buildDramaDetailArgs(api, params)
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_novel_quota",
      description: "Get the current user's novel video generation quota.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {}
      }
    },
    () => ["novels", "quota", "--json"]
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_novels",
      description: "List novels from the Inbeidou novel content library.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          platform: { type: "string" },
          language: { type: "string" },
          search: { type: "string" },
          page: { type: "integer" },
          size: { type: "integer" },
          order: { type: "string" }
        }
      }
    },
    (params) => buildNovelListArgs(params)
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_novel_random",
      description: "Randomly select a novel and fetch its free chapter text without generating a video.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          platform: { type: "string" },
          language: { type: "string" },
          search: { type: "string" },
          page: { type: "integer" },
          size: { type: "integer" },
          order: { type: "string" },
          fullText: { type: "boolean" }
        }
      }
    },
    (params) => buildNovelActionArgs("random", params)
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_novel_chapter",
      description: "Fetch the free chapter text and voice options for a selected novel.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          taskId: { type: "string" },
          appId: { type: "string" },
          platform: { type: "string" },
          language: { type: "string" },
          search: { type: "string" },
          page: { type: "integer" },
          size: { type: "integer" },
          order: { type: "string" },
          fullText: { type: "boolean" }
        }
      }
    },
    (params) => buildNovelActionArgs("chapter", params)
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_novel_pipeline",
      description: "Run the novel workflow: select/search a novel, fetch free chapter text, generate a novel video with Vidu, and optionally publish to Facebook or TikTok.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
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
          publishPlatform: { type: "string", enum: PLATFORMS },
          accountPool: { type: "string" },
          count: { type: "integer" },
          accountIds: {
            type: "array",
            items: { type: "string" }
          },
          teamIds: {
            type: "array",
            items: { type: "string" }
          },
          text: { type: "string" },
          textFile: { type: "string" },
          fullText: { type: "boolean" }
        }
      }
    },
    (params) => buildNovelPipelineArgs(params)
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_drama_episodes",
      description: "List episodes for a short drama by task, title search, or serial id.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          taskId: { type: "string" },
          search: { type: "string" },
          serialId: { type: "integer" },
          appId: { type: "string" },
          dramaPlatform: { type: "string" },
          dramaLanguage: { type: "string" },
          dramaOrder: { type: "string" },
          dramaTaskType: { type: "string" },
          searchSize: { type: "integer" },
          episodeOrders: { type: "string" },
          start: { type: "integer" },
          end: { type: "integer" },
          videoType: { type: "string" }
        }
      }
    },
    (params) => buildDramaEpisodeListArgs(api, params)
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_drama_episode_fetch",
      description: "Fetch episode N of a short drama and convert it into upload_id/window_id media context.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          taskId: { type: "string" },
          search: { type: "string" },
          serialId: { type: "integer" },
          appId: { type: "string" },
          episodeOrder: { type: "integer" },
          dramaPlatform: { type: "string" },
          dramaLanguage: { type: "string" },
          dramaOrder: { type: "string" },
          dramaTaskType: { type: "string" },
          searchSize: { type: "integer" },
          uploadTimeout: { type: "integer" },
          pollInterval: { type: "number" }
        },
        required: ["episodeOrder"]
      }
    },
    (params) => buildDramaEpisodeFetchArgs(api, params)
  );

  api.registerTool({
    name: "barry_video_publish_accounts",
    description: "List authorized social publish accounts for Facebook, Instagram, TikTok, or YouTube. Show users only platform and account name; use internal IDs only for later tool execution.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        platform: { type: "string", enum: PLATFORMS },
        status: { type: "integer", enum: [0, 1, 2] }
      }
    },
    async execute(_id, params = {}) {
      const args = ["publish", "accounts", "--json"];
      addOption(args, "--platform", params.platform);
      addOption(args, "--status", params.status);
      const result = await runBackend(api, args);
      const payload = maybeParseJson(result.stdout);
      return toolResponse(
        "可发布账号列表",
        formatPublishAccountChoices(payload ?? result.stdout),
        result.command
      );
    }
  });

  registerJsonTool(
    api,
    {
      name: "barry_video_uploads_list",
      description: "List videos in the Inbeidou media library.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          page: { type: "integer" },
          size: { type: "integer" }
        }
      }
    },
    (params) => buildUploadListArgs(params)
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_upload",
      description: "Upload a local video into the Inbeidou media library.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          file: { type: "string" },
          uploadTimeout: { type: "integer" },
          pollInterval: { type: "number" }
        },
        required: ["file"]
      }
    },
    (params) => {
      const args = ["uploads", "upload", "--file", params.file, "--json"];
      addOption(args, "--upload-timeout", params.uploadTimeout);
      addOption(args, "--poll-interval", params.pollInterval);
      return args;
    }
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_uploads_delete",
      description: "Delete a video from the Inbeidou media library.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          fileId: { type: "string" }
        },
        required: ["fileId"]
      }
    },
    (params) => ["uploads", "delete", "--id", params.fileId, "--json"]
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_analyze",
      description: "Run Inbeidou smart video analysis on a local file or uploaded asset.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          file: { type: "string" },
          uploadId: { type: "string" },
          windowId: { type: "string" },
          taskId: { type: "string" },
          search: { type: "string" },
          serialId: { type: "integer" },
          appId: { type: "string" },
          episodeOrder: { type: "integer" },
          dramaPlatform: { type: "string" },
          dramaLanguage: { type: "string" },
          dramaOrder: { type: "string" },
          dramaTaskType: { type: "string" },
          searchSize: { type: "integer" },
          uploadTimeout: { type: "integer" },
          timeout: { type: "integer" },
          pollInterval: { type: "number" }
        }
      }
    },
    (params) => {
      requireMediaSource(params, "analyze");
      const args = ["analyze", "run", "--json"];
      addOption(args, "--file", params.file);
      addOption(args, "--upload-id", params.uploadId);
      addOption(args, "--window-id", params.windowId);
      addDramaSourceOptions(args, params);
      addOption(args, "--upload-timeout", params.uploadTimeout);
      addOption(args, "--timeout", params.timeout);
      addOption(args, "--poll-interval", params.pollInterval);
      return args;
    }
  );

  api.registerTool({
    name: "barry_video_clip_types",
    description: "Explain supported smart clip types in user-friendly Chinese with parameter codes.",
    parameters: { type: "object", additionalProperties: false, properties: {} },
    async execute() {
      return toolResponse(
        "Explain supported smart clip types in user-friendly Chinese with parameter codes.",
        explainClipMethods({ category: "clip" })
      );
    }
  });

  api.registerTool({
    name: "barry_video_clip_method_guide",
    description: "Explain supported clipping methods and deduplication methods in user-friendly Chinese.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        category: { type: "string", enum: ["all", "clip", "deduplication"] }
      }
    },
    async execute(_id, params = {}) {
      const payload = explainClipMethods({ category: params.category || "all" });
      return toolResponse(
        "Explain supported clipping methods and deduplication methods in user-friendly Chinese.",
        payload
      );
    }
  });

  api.registerTool({
    name: "barry_video_deduplication_types",
    description: "Explain supported deduplication methods in user-friendly Chinese with parameter codes.",
    parameters: { type: "object", additionalProperties: false, properties: {} },
    async execute() {
      return toolResponse(
        "Explain supported deduplication methods in user-friendly Chinese with parameter codes.",
        explainClipMethods({ category: "deduplication" })
      );
    }
  });

  registerJsonTool(
    api,
    {
      name: "barry_video_clip",
      description: "Run Inbeidou smart clipping on a local file or uploaded asset.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          file: { type: "string" },
          uploadId: { type: "string" },
          windowId: { type: "string" },
          taskId: { type: "string" },
          search: { type: "string" },
          serialId: { type: "integer" },
          appId: { type: "string" },
          episodeOrder: { type: "integer" },
          dramaPlatform: { type: "string" },
          dramaLanguage: { type: "string" },
          dramaOrder: { type: "string" },
          dramaTaskType: { type: "string" },
          searchSize: { type: "integer" },
          cutType: { type: "string", enum: CUT_TYPES },
          duration: { type: "string" },
          outputCount: { type: "integer" },
          scriptCount: { type: "integer" },
          deduplication: {
            type: "array",
            items: { type: "string", enum: DEDUP_OPTIONS }
          },
          watermark: { type: "string" },
          mergeVideo: { type: "boolean" },
          wait: { type: "boolean" },
          uploadTimeout: { type: "integer" },
          submitTimeout: { type: "integer" },
          timeout: { type: "integer" },
          pollInterval: { type: "number" }
        }
      }
    },
    (params) => buildClipArgs(params)
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_translate_languages",
      description: "List supported translation languages for the translate workflow.",
      parameters: { type: "object", additionalProperties: false, properties: {} }
    },
    () => ["translate", "languages", "--json"]
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_translate_fonts",
      description: "List supported subtitle fonts for the translate workflow.",
      parameters: { type: "object", additionalProperties: false, properties: {} }
    },
    () => ["translate", "fonts", "--json"]
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_translate_styles",
      description: "List supported subtitle effect styles for the translate workflow.",
      parameters: { type: "object", additionalProperties: false, properties: {} }
    },
    () => ["translate", "styles", "--json"]
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_translate",
      description: "Run Inbeidou video translation on a local file or uploaded asset.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          file: { type: "string" },
          uploadId: { type: "string" },
          windowId: { type: "string" },
          taskId: { type: "string" },
          search: { type: "string" },
          serialId: { type: "integer" },
          appId: { type: "string" },
          episodeOrder: { type: "integer" },
          dramaPlatform: { type: "string" },
          dramaLanguage: { type: "string" },
          dramaOrder: { type: "string" },
          dramaTaskType: { type: "string" },
          searchSize: { type: "integer" },
          sourceLang: { type: "string" },
          targetLang: { type: "string" },
          subtitleType: { type: "string", enum: ["double", "single"] },
          noSpeechTranslate: { type: "boolean" },
          font: { type: "string" },
          fontSize: { type: "integer" },
          fontColor: { type: "string" },
          fontOpacity: { type: "integer" },
          subtitleY: { type: "number" },
          alignment: { type: "string", enum: ["Left", "Center", "Right"] },
          effectStyle: { type: "string" },
          bold: { type: "boolean" },
          underline: { type: "boolean" },
          italic: { type: "boolean" },
          shadow: { type: "boolean" },
          shadowShift: { type: "number" },
          shadowXBord: { type: "number" },
          shadowYBord: { type: "number" },
          shadowOpacity: { type: "integer" },
          outline: { type: "boolean" },
          outlineBoard: { type: "number" },
          mergeVideo: { type: "boolean" },
          wait: { type: "boolean" },
          uploadTimeout: { type: "integer" },
          submitTimeout: { type: "integer" },
          timeout: { type: "integer" },
          pollInterval: { type: "number" }
        },
        required: ["targetLang"]
      }
    },
    (params) => buildTranslateArgs(params)
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_manus_list",
      description: "List generated works in the Inbeidou manus library.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          page: { type: "integer" },
          size: { type: "integer" },
          search: { type: "string" }
        }
      }
    },
    (params) => buildManusListArgs(params)
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_manus_detail",
      description: "Get details for a generated Inbeidou work.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          manusId: { type: "string" }
        },
        required: ["manusId"]
      }
    },
    (params) => ["manus", "detail", "--id", params.manusId, "--json"]
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_download_manus",
      description: "Download a completed generated video to a local directory.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          manusId: { type: "string" },
          outputDir: { type: "string" }
        },
        required: ["manusId"]
      }
    },
    (params) => ["manus", "download", "--id", params.manusId, "--output", resolveDownloadDir(api, params.outputDir), "--json"]
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_manus_delete",
      description: "Delete a generated work from the manus library.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          manusId: { type: "string" }
        },
        required: ["manusId"]
      }
    },
    (params) => ["manus", "delete", "--id", params.manusId, "--json"]
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_publish",
      description: "Create a social publish task for Facebook, Instagram, TikTok, or YouTube. Requires a user-selected platform and accountIds/teamIds; if missing, list accounts and ask the user first.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          accountIds: {
            type: "array",
            items: { type: "string" }
          },
          teamIds: {
            type: "array",
            items: { type: "string" }
          },
          platform: { type: "string", enum: PLATFORMS },
          text: { type: "string" },
          textFile: { type: "string" },
          file: { type: "string" },
          fileUrl: { type: "string" },
          scheduleAt: { type: "string" },
          dryRun: { type: "boolean" }
        }
      }
    },
    (params) => {
      requireAny(params, ["file", "fileUrl"], "publish requires file or fileUrl");
      return buildPublishArgs(api, params);
    }
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_publish_records",
      description: "List social publish task records and statuses.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          postStatus: { type: "string", enum: ["published", "scheduled"] },
          platform: { type: "string", enum: PLATFORMS },
          socialId: { type: "string" },
          status: { type: "string" },
          page: { type: "integer" },
          size: { type: "integer" }
        }
      }
    },
    (params) => {
      const args = ["publish", "records", "--json"];
      addOption(args, "--post-status", params.postStatus);
      addOption(args, "--platform", params.platform);
      addOption(args, "--social-id", params.socialId);
      addOption(args, "--status", params.status);
      addOption(args, "--page", params.page);
      addOption(args, "--size", params.size);
      return args;
    }
  );

  registerJsonTool(
    api,
    {
      name: "barry_video_publish_delete",
      description: "Delete a publish record or scheduled task.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          teamId: { type: "string" },
          taskId: { type: "string" },
          postId: { type: "string" }
        },
        required: ["teamId", "taskId"]
      }
    },
    (params) => {
      const args = ["publish", "delete", "--team-id", params.teamId, "--task-id", params.taskId, "--json"];
      addOption(args, "--post-id", params.postId);
      return args;
    }
  );

  api.registerTool({
    name: "barry_video_local_pipeline",
    description: "Run the local-video workflow: upload a local file, smart clip, normalize to 9:16, publish, poll status, and clean generated output after success. Requires a user-selected platform and accountIds/teamIds; if missing, list accounts and ask first.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        file: { type: "string" },
        accountIds: {
          type: "array",
          items: { type: "string" }
        },
        teamIds: {
          type: "array",
          items: { type: "string" }
        },
        platform: { type: "string", enum: PLATFORMS },
        text: { type: "string" },
        textFile: { type: "string" },
        scheduleAt: { type: "string" },
        downloadDir: { type: "string" },
        keepOutput: { type: "boolean" },
        cutType: { type: "string", enum: CUT_TYPES },
        duration: { type: "string" },
        outputCount: { type: "integer" },
        scriptCount: { type: "integer" },
        deduplication: {
          type: "array",
          items: { type: "string", enum: DEDUP_OPTIONS }
        },
        watermark: { type: "string" },
        mergeVideo: { type: "boolean" },
        uploadTimeout: { type: "integer" },
        submitTimeout: { type: "integer" },
        timeout: { type: "integer" },
        pollInterval: { type: "number" },
        collectWaitSeconds: { type: "integer" },
        collectPollInterval: { type: "integer" }
      },
      required: ["file", "platform"]
    },
    async execute(_id, params) {
      const result = await runFlywheelBackend(api, buildFlywheelLocalArgs(api, params));
      const payload = maybeParseJson(result.stdout) ?? result.stdout;
      return toolResponse(
        "Run the local-video workflow: upload, clip, publish, poll status, and clean generated output.",
        payload,
        result.command
      );
    }
  });

  api.registerTool({
    name: "barry_video_batch_drama",
    description: "Run batch short-drama orchestration: randomly select N dramas, choose episodes with data, clip/deduplicate, publish one video per selected account, poll status, and clean generated output after success. Requires a user-selected platform and accountIds/teamIds; if missing, list accounts and ask first.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        execute: { type: "boolean" },
        count: { type: "integer" },
        accountIds: {
          type: "array",
          items: { type: "string" }
        },
        teamIds: {
          type: "array",
          items: { type: "string" }
        },
        platform: { type: "string", enum: PLATFORMS },
        allowAccountReuse: { type: "boolean" },
        dramaPlatform: { type: "string" },
        language: { type: "string" },
        dramaOrder: { type: "string" },
        search: { type: "string" },
        episodeOrder: { type: "integer" },
        cutType: { type: "string", enum: CUT_TYPES },
        duration: { type: "string" },
        outputCount: { type: "integer" },
        scriptCount: { type: "integer" },
        deduplication: {
          type: "array",
          items: { type: "string", enum: DEDUP_OPTIONS }
        },
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
        collectPollInterval: { type: "integer" }
      },
      required: ["platform"]
    },
    async execute(_id, params) {
      const result = await runFlywheelBackend(
        api,
        buildFlywheelBatchDramaArgs(api, params),
        { timeoutMs: params.timeout ? (Number(params.timeout) + 600) * 1000 : 0 }
      );
      const payload = maybeParseJson(result.stdout) ?? result.stdout;
      return toolResponse(
        "Run batch drama workflow: select dramas, clip, publish, poll status, and clean generated output.",
        payload,
        result.command
      );
    }
  });

  api.registerTool({
    name: "barry_video_retry_failed_publish",
    description: "Retry the last failed publish tasks once after the user explicitly agrees.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        publishConcurrency: { type: "integer" },
        collectWaitSeconds: { type: "integer" },
        collectPollInterval: { type: "integer" },
        keepOutput: { type: "boolean" }
      }
    },
    async execute(_id, params) {
      const args = ["retry-failed-publish"];
      addOption(args, "--publish-concurrency", params.publishConcurrency);
      addOption(args, "--collect-wait-seconds", params.collectWaitSeconds);
      addOption(args, "--collect-poll-interval", params.collectPollInterval);
      addFlag(args, params.keepOutput, "--keep-output");
      const result = await runFlywheelBackend(api, args);
      const payload = maybeParseJson(result.stdout) ?? result.stdout;
      return toolResponse(
        "Retry the last failed publish tasks once.",
        payload,
        result.command
      );
    }
  });

  api.registerTool({
    name: "barry_video_discard_failed_publish_output",
    description: "Delete retained local clips for the last failed publish tasks after the user decides not to continue retrying.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {}
    },
    async execute() {
      const result = await runFlywheelBackend(api, ["discard-failed-publish-output"]);
      const payload = maybeParseJson(result.stdout) ?? result.stdout;
      return toolResponse(
        "Delete retained local clips for the last failed publish tasks.",
        payload,
        result.command
      );
    }
  });

  api.registerTool({
    name: "barry_video_failed_publish_paths",
    description: "Show retained local clip paths for the last failed publish tasks when the user explicitly asks for the paths.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {}
    },
    async execute() {
      const result = await runFlywheelBackend(api, ["show-failed-publish-paths"]);
      const payload = maybeParseJson(result.stdout) ?? result.stdout;
      return toolResponse(
        "Show retained local clip paths for the last failed publish tasks.",
        payload,
        result.command
      );
    }
  });

  api.registerTool({
    name: "barry_video_pipeline",
    description: "Run a one-shot workflow: smart clip, download the result, then publish it to a social account. Requires a user-selected platform and accountIds/teamIds; if missing, list accounts and ask first.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        file: { type: "string" },
        taskId: { type: "string" },
        search: { type: "string" },
        serialId: { type: "integer" },
        appId: { type: "string" },
        episodeOrder: { type: "integer" },
        dramaPlatform: { type: "string" },
        dramaLanguage: { type: "string" },
        dramaOrder: { type: "string" },
        dramaTaskType: { type: "string" },
        searchSize: { type: "integer" },
        accountIds: {
          type: "array",
          items: { type: "string" }
        },
        teamIds: {
          type: "array",
          items: { type: "string" }
        },
        platform: { type: "string", enum: PLATFORMS },
        text: { type: "string" },
        textFile: { type: "string" },
        scheduleAt: { type: "string" },
        downloadDir: { type: "string" },
        cutType: { type: "string", enum: CUT_TYPES },
        duration: { type: "string" },
        outputCount: { type: "integer" },
        scriptCount: { type: "integer" },
        deduplication: {
          type: "array",
          items: { type: "string", enum: DEDUP_OPTIONS }
        },
        watermark: { type: "string" },
        mergeVideo: { type: "boolean" },
        uploadTimeout: { type: "integer" },
        submitTimeout: { type: "integer" },
        timeout: { type: "integer" },
        pollInterval: { type: "number" }
      }
    },
    async execute(_id, params) {
      const clipResult = await runBackend(api, buildClipArgs({ ...params, wait: true }));
      const clipBody = maybeParseJson(clipResult.stdout);
      const manusId = clipBody?.id || clipBody?.manus_id || clipBody?.manusId;

      if (!manusId) {
        throw new Error(`clip result did not include manus id: ${clipResult.stdout}`);
      }

      const downloadArgs = ["manus", "download", "--id", String(manusId), "--output", resolveDownloadDir(api, params.downloadDir), "--json"];
      const downloadResult = await runBackend(api, downloadArgs);
      const downloadBody = maybeParseJson(downloadResult.stdout);
      const downloadedFile = downloadBody?.path;

      if (!downloadedFile) {
        throw new Error(`download result did not include path: ${downloadResult.stdout}`);
      }

      const publishArgs = buildPublishArgs(api, { ...params, file: downloadedFile });
      const publishResult = await runBackend(api, publishArgs);
      const publishBody = maybeParseJson(publishResult.stdout) ?? publishResult.stdout;

      return toolResponse(
        "Run a one-shot workflow: smart clip, download the result, then publish it to a social account.",
        {
          clip: clipBody,
          download: downloadBody,
          publish: publishBody
        },
        `${clipResult.command}\n${downloadResult.command}\n${publishResult.command}`
      );
    }
  });

  api.registerTool({
    name: "barry_video_cli_passthrough",
    description: "Run raw inbeidou_cli.py arguments when no dedicated Barry Video tool exists.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        args: {
          type: "array",
          items: { type: "string" }
        }
      },
      required: ["args"]
    },
    async execute(_id, params) {
      requireNonEmptyList(params.args, "args is required");
      const result = await runBackend(api, normalizeList(params.args));
      return toolResponse("Run raw inbeidou_cli.py arguments when no dedicated Barry Video tool exists.", maybeParseJson(result.stdout) ?? result.stdout, result.command);
    }
  });
}

const plugin = {
  id: PLUGIN_ID,
  name: PLUGIN_NAME,
  description: "Barry's all-in-one Inbeidou creator plugin for account, drama, media, AI editing, and social publishing workflows.",
  configSchema: CONFIG_SCHEMA,
  register(api) {
    registerBarryTools(api);
  }
};

export default plugin;
