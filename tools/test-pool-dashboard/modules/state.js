export const state = {
  autoRefreshMs: 30000,
  refreshing: false,
  realtimeRefreshing: false,
  topPlayRefreshing: false,
  optionsLoaded: false,
  roundsLoaded: false,
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
  "creative_list_day",
  "yourchannel",
  "realtime",
  "realtime_single",
  "creative_list",
  "ordinary",
  "fbhot_test",
];

export const LINE_LABELS = {
  ordinary: "普通池线",
  realtime: "实时榜线",
  realtime_day: "白天实时榜线",
  realtime_single: "夜间实时榜定账号线",
  creative_list: "创意列表外部素材映射线",
  creative_list_day: "白天创意列表外部素材映射线",
  fbhot_test: "FB 热度加权线",
  yourchannel: "YourChannel 剧场线",
};

export const LINE_STRATEGIES = {
  realtime_day: "选素材：白天实时榜外部素材优先，先补当天榜单命中。\n如何剪辑：优先走外部素材快切，压缩成能快速发出的短视频。\n如何发布：白天手动窗口 12:00-18:00 内补量，重点看回收速度。",
  creative_list_day: "选素材：从创意列表外部素材里挑能映射到真实任务的素材，优先承接白天补量。\n如何剪辑：先取外部素材，再按映射任务做快切和时长归一。\n如何发布：白天 12:00-18:00 手动窗口发，先看命中和回收。",
  yourchannel: "选素材：只用白名单剧名，不混入其他实验素材。\n如何剪辑：直接按白名单剧目文案，走固定剧场发布节奏。\n如何发布：优先发 YourChannel 剧场，重点看剧目命中和账号达标率。",
  realtime: "选素材：优先吃夜间实时榜外部素材，先看榜单里能直接跑的热剧。\n如何剪辑：外部素材优先快切，强调首屏节奏和快速出片。\n如何发布：夜间 18:00-次日12:00 连续补量，重点看播放回收和链接点击。",
  realtime_single: "选素材：夜间实时榜里挑可连续消耗的素材，固定绑定到单账号。\n如何剪辑：同一素材反复试不同切法，方便观察单账号反馈。\n如何发布：按单账号连续发，适合看定向试跑和极值表现。",
  creative_list: "选素材：创意列表外部素材先映射到真实任务，再筛能直接转发的版本。\n如何剪辑：优先走外部素材快切，保留创意素材的强钩子片段。\n如何发布：夜间稳定补量，重点看映射成功率和播放回收。",
  ordinary: "选素材：官方短剧素材优先，承接夜间稳定补量和底盘出量。\n如何剪辑：按官方短剧正常剪辑逻辑发，重点保证稳定产出。\n如何发布：夜间持续补量，优先补足账号目标，不追求极端热度。",
  fbhot_test: "选素材：偏热测素材，专门看 FB 热度优先策略是否值得放大。\n如何剪辑：强调首屏冲突和热点片段，方便测试热度反馈。\n如何发布：以实验为主，不直接代表主线，看点击、播放和收益反馈。",
};
