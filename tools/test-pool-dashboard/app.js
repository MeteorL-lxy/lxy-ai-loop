import { state } from "./modules/state.js";
import { fetchJson, fmtDateTime, qs } from "./modules/utils.js";
import { renderOverall, renderToday } from "./modules/render-overview.js";
import { renderLineCards } from "./modules/render-lines.js";
import { renderTopPlay } from "./modules/render-top-play.js";
import { renderDailyTopHistory, renderHistory } from "./modules/render-history.js";
import { renderLineCumulative } from "./modules/render-line-cumulative.js";
import { renderAccountGroups } from "./modules/render-account-groups.js";
import { renderAccountHealth, renderAccountHealthDetails } from "./modules/render-account-health.js";
import { renderOptions } from "./modules/render-options.js";
import { closeDrawer, loadRounds } from "./modules/rounds.js";
import { ensureLayoutLoaded } from "./modules/layout.js";
import { initNavigation } from "./modules/navigation.js";

async function fetchRealtimeBundle({ refresh = false, loadOptions = false } = {}) {
  const requests = [
    fetchJson(`./api/test-pool/realtime-overview?days=30&include_today_top_play=0${refresh ? "&refresh=1" : ""}`),
    fetchJson(`./api/test-pool/failures?limit=80${refresh ? "&refresh=1" : ""}`),
  ];
  if (loadOptions && !state.optionsLoaded) {
    requests.push(fetchJson("./api/test-pool/options"));
  }
  const [overview, failures, options] = await Promise.all(requests);
  if (options) {
    renderOptions(options);
    state.optionsLoaded = true;
  }
  return { overview, failures };
}

function applyRealtimeBundle({ overview, failures }) {
  renderOverall(overview);
  renderToday(overview);
  renderLineCards(overview, failures);
  renderAccountGroups(overview.account_groups || []);
  qs("status-text").textContent = "已连接";
  qs("db-path").textContent = overview.db_path || qs("db-path").textContent || "-";
  qs("last-updated").textContent = fmtDateTime(overview.last_exported_at);
}

async function loadTopPlay({ force = false } = {}) {
  if (state.topPlayRefreshing) return;
  state.topPlayRefreshing = true;
  try {
    const payload = await fetchJson(`./api/test-pool/today-top-play${force ? "?force=1" : ""}`);
    renderTopPlay({ today_top_play: payload });
  } catch (error) {
    console.error(error);
  } finally {
    state.topPlayRefreshing = false;
  }
}

async function loadContentPanels({ refreshDailyHistory = false, refreshLineCumulative = false } = {}) {
  const [dailyTopHistory, lineCumulative] = await Promise.allSettled([
    fetchJson(`./api/test-pool/daily-top-history${refreshDailyHistory ? "?force=1" : ""}`),
    fetchJson(`./api/test-pool/line-cumulative${refreshLineCumulative ? "?force=1" : ""}`),
  ]);

  if (dailyTopHistory.status === "fulfilled") {
    renderDailyTopHistory({ daily_top_history: dailyTopHistory.value });
  } else {
    console.error(dailyTopHistory.reason);
  }

  if (lineCumulative.status === "fulfilled") {
    renderLineCumulative({ line_cumulative: lineCumulative.value });
  } else {
    console.error(lineCumulative.reason);
  }
}

async function loadTrendPanel({ refreshTrend = false } = {}) {
  try {
    const payload = await fetchJson(`./api/test-pool/trend-analyzer${refreshTrend ? "?refresh=1" : ""}`);
    renderHistory({ trend_analyzer: payload });
  } catch (error) {
    console.error(error);
  }
}

async function loadAccountHealth() {
  const payload = await fetchJson("./api/account-health/overview?scope=loop");
  renderAccountHealth(payload);
  qs("status-text").textContent = payload.available ? "已连接" : "配置待补";
  qs("mode-text").textContent = payload.source?.readonly ? "账号健康只读" : "本地服务";
  qs("db-path").textContent = payload.source?.database || qs("db-path").textContent || "-";
  qs("last-updated").textContent = fmtDateTime(payload.last_updated);
}

async function loadCurrentPage(page = state.currentPage, { force = false } = {}) {
  switch (page) {
    case "home": {
      const { overview, failures } = await fetchRealtimeBundle({
        refresh: force,
        loadOptions: true,
      });
      applyRealtimeBundle({ overview, failures });
      await loadTopPlay({ force });
      state.pageLoaded.home = true;
      break;
    }
    case "accounts":
      await loadAccountHealth();
      state.pageLoaded.accounts = true;
      break;
    case "lines": {
      const { overview, failures } = await fetchRealtimeBundle({
        refresh: force,
        loadOptions: true,
      });
      applyRealtimeBundle({ overview, failures });
      state.pageLoaded.lines = true;
      break;
    }
    case "content":
      await loadContentPanels({
        refreshDailyHistory: force,
        refreshLineCumulative: force,
      });
      state.pageLoaded.content = true;
      break;
    case "trend":
      await loadTrendPanel({ refreshTrend: force });
      state.pageLoaded.trend = true;
      break;
    case "pools": {
      const { overview } = await fetchRealtimeBundle({
        refresh: force,
        loadOptions: false,
      });
      renderAccountGroups(overview.account_groups || []);
      qs("status-text").textContent = "已连接";
      qs("db-path").textContent = overview.db_path || qs("db-path").textContent || "-";
      qs("last-updated").textContent = fmtDateTime(overview.last_exported_at);
      state.pageLoaded.pools = true;
      break;
    }
    case "rounds":
      if (!state.optionsLoaded || force) {
        const options = await fetchJson("./api/test-pool/options");
        renderOptions(options);
        state.optionsLoaded = true;
      }
      await loadRounds();
      state.pageLoaded.rounds = true;
      break;
    default:
      break;
  }
}

async function refreshRealtimePanels() {
  if (state.refreshing || state.realtimeRefreshing) return;
  state.realtimeRefreshing = true;
  qs("status-text").textContent = "刷新中";
  try {
    if (state.currentPage === "home") {
      const { overview, failures } = await fetchRealtimeBundle({ refresh: false, loadOptions: false });
      applyRealtimeBundle({ overview, failures });
      await loadTopPlay();
    } else if (state.currentPage === "lines") {
      const { overview, failures } = await fetchRealtimeBundle({ refresh: false, loadOptions: false });
      applyRealtimeBundle({ overview, failures });
    } else if (state.currentPage === "pools") {
      const { overview } = await fetchRealtimeBundle({ refresh: false, loadOptions: false });
      renderAccountGroups(overview.account_groups || []);
      qs("status-text").textContent = "已连接";
      qs("db-path").textContent = overview.db_path || qs("db-path").textContent || "-";
      qs("last-updated").textContent = fmtDateTime(overview.last_exported_at);
    } else if (state.currentPage === "accounts") {
      await loadAccountHealth();
    } else {
      qs("status-text").textContent = "已连接";
    }
  } catch (error) {
    showError(error);
  } finally {
    state.realtimeRefreshing = false;
  }
}

async function refreshAll({ force = false } = {}) {
  if (state.refreshing || state.realtimeRefreshing) return;
  state.refreshing = true;
  qs("status-text").textContent = "刷新中";
  try {
    await loadCurrentPage(state.currentPage, { force });
  } catch (error) {
    showError(error);
  } finally {
    state.refreshing = false;
  }
}

function bindEvents() {
  initNavigation((page) => {
    if (!state.pageLoaded[page]) {
      loadCurrentPage(page, { force: false }).catch(showError);
    }
  });

  qs("refresh-btn").addEventListener("click", () => {
    refreshAll({ force: true }).catch((error) => console.error(error));
  });

  qs("account-health-filter").addEventListener("change", renderAccountHealthDetails);
  qs("account-health-search").addEventListener("input", renderAccountHealthDetails);

  qs("search-btn").addEventListener("click", () => {
    state.page = 1;
    state.filters.day = qs("day-filter").value;
    state.filters.runtime_mode = qs("mode-filter").value;
    state.filters.line_name = qs("line-filter").value;
    state.filters.status = qs("status-filter").value;
    state.filters.search = qs("search-input").value.trim();
    loadRounds().catch(showError);
  });

  qs("page-size-select").addEventListener("change", (event) => {
    state.pageSize = Number(event.target.value || 50);
    state.page = 1;
    loadRounds().catch(showError);
  });

  qs("prev-page-btn").addEventListener("click", () => {
    if (state.page <= 1) return;
    state.page -= 1;
    loadRounds().catch(showError);
  });

  qs("next-page-btn").addEventListener("click", () => {
    state.page += 1;
    loadRounds().catch(showError);
  });

  qs("drawer-close").addEventListener("click", closeDrawer);
  qs("drawer-mask").addEventListener("click", closeDrawer);
}

function showError(error) {
  console.error(error);
  qs("status-text").textContent = "加载失败";
}

async function bootstrap() {
  await ensureLayoutLoaded();
  bindEvents();
  await refreshAll({ force: false });
  window.setInterval(() => {
    refreshRealtimePanels().catch((error) => console.error(error));
  }, state.autoRefreshMs);
}

bootstrap().catch((error) => console.error(error));
