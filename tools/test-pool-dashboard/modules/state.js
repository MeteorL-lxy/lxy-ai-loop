export const state = {
  autoRefreshMs: 30000,
  refreshing: false,
  realtimeRefreshing: false,
  topPlayRefreshing: false,
  optionsLoaded: false,
  roundsLoaded: false,
  currentPage: "home",
  page: 1,
  pageSize: 50,
  filters: {
    day: "",
    runtime_mode: "",
    line_name: "",
    status: "",
    search: "",
  },
};

export const LINE_ORDER = [
  "realtime_day",
  "yourchannel",
  "stardusttv",
  "tag_test",
  "realtime",
  "recent_order",
  "realtime_single",
  "ordinary",
  "fbhot_test",
  "creative_list_day",
  "creative_list",
];

export const LINE_LABELS = {
  ordinary: "ai-cut官剧池-夜间",
  realtime: "实时榜素材ff池-夜间",
  realtime_day: "实时榜素材ff池-白天",
  realtime_single: "实时榜单素材单账号池-夜间",
  creative_list: "创意列表匹官剧ff池-夜间",
  creative_list_day: "创意列表匹官剧ff池-白天",
  fbhot_test: "FB热度优先策略池-夜间",
  yourchannel: "YourChannel 剧场线账号池-白天",
  recent_order: "近月出单剧池-夜间",
  stardusttv: "山海剧场线账号池-夜间",
  tag_test: "打标账号剧测试池-夜间",
};

export const LINE_STRATEGIES = {
  realtime_day: "选素材：白天实时榜外部素材优先，先补当天榜单命中。\n如何剪辑：优先走外部素材快切，压缩成能快速发出的短视频。\n如何发布：白天手动窗口 10:00-18:00 内补量，重点看回收速度。",
  creative_list_day: "选素材：从创意列表外部素材里挑能映射到真实任务的素材，优先承接白天补量。\n如何剪辑：先取外部素材，再按映射任务做快切和时长归一。\n如何发布：白天 10:00-18:00 手动窗口发，先看命中和回收。",
  yourchannel: "选素材：只用白名单剧名，不混入其他实验素材。\n如何剪辑：直接按白名单剧目文案，走固定剧场发布节奏。\n如何发布：优先发 YourChannel 剧场，重点看剧目命中和账号达标率。",
  stardusttv: "选素材：按山海剧场剧名表轮转，优先用已经验证过能跑的剧目。\n如何剪辑：使用官方视频 FFmpeg 15-30 秒快切，先保稳定出片和首屏节奏。\n如何发布：夜间持续补量，重点看剧场命中、账号达标和播放回收。",
  tag_test: "选素材：按打标剧表 drama_title 轮转，只取美区和东南亚推荐地区，并固定查 StardustTV 官方剧库。\n如何剪辑：使用官方视频 FFmpeg 15-30 秒快切。\n如何发布：剧地区必须匹配账号地区，同一部剧绑定同一个账号；美区北京时间 06:30-13:30，东南亚北京时间 18:30-00:30。",
  realtime: "选素材：优先吃夜间实时榜外部素材，先看榜单里能直接跑的热剧。\n如何剪辑：外部素材优先快切，强调首屏节奏和快速出片。\n如何发布：夜间 18:00-次日12:00 连续补量，重点看播放回收和链接点击。",
  recent_order: "选素材：只吃近一个月真实出单剧表格里的剧名和剧场，按表格顺序轮转；全部跑完后再从头开始。\n如何剪辑：官方视频随机抽取可播剧集，再用 FFmpeg 切约 30 秒片段。\n如何发布：夜间补量线，重点看真实出单剧的稳定出量与账号达标率。",
  realtime_single: "选素材：夜间实时榜里挑可连续消耗的素材，固定绑定到单账号。\n如何剪辑：同一素材反复试不同切法，方便观察单账号反馈。\n如何发布：按单账号连续发，适合看定向试跑和极值表现。",
  creative_list: "选素材：创意列表外部素材先映射到真实任务，再筛能直接转发的版本。\n如何剪辑：优先走外部素材快切，保留创意素材的强钩子片段。\n如何发布：夜间稳定补量，重点看映射成功率和播放回收。",
  ordinary: "选素材：官方短剧素材优先，承接夜间稳定补量和底盘出量。\n如何剪辑：按官方短剧正常剪辑逻辑发，重点保证稳定产出。\n如何发布：夜间持续补量，优先补足账号目标，不追求极端热度。",
  fbhot_test: "选素材：偏热测素材，专门看 FB 热度优先策略是否值得放大。\n如何剪辑：强调首屏冲突和热点片段，方便测试热度反馈。\n如何发布：以实验为主，不直接代表主线，看点击、播放和收益反馈。",
};
