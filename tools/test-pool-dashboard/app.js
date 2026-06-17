import { state } from "./modules/state.js";
import { fetchJson, fmtDateTime, qs } from "./modules/utils.js";
import { renderOverall, renderToday } from "./modules/render-overview.js";
import { renderLineCards } from "./modules/render-lines.js";
import { renderTopPlay } from "./modules/render-top-play.js";
import { renderDailyTopHistory, renderHistory } from "./modules/render-history.js";
import { renderAccountGroups } from "./modules/render-account-groups.js";
import { renderOptions } from "./modules/render-options.js";
import { closeDrawer, loadRounds } from "./modules/rounds.js";

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

async function loadHeavyPanels({ refreshTrend = false, refreshDailyHistory = false } = {}) {
  try {
    const [trendAnalyzer, dailyTopHistory] = await Promise.all([
      fetchJson(`./api/test-pool/trend-analyzer${refreshTrend ? "?refresh=1" : ""}`),
      fetchJson(`./api/test-pool/daily-top-history${refreshDailyHistory ? "?force=1" : ""}`),
    ]);

    renderHistory({ trend_analyzer: trendAnalyzer });
    renderDailyTopHistory({ daily_top_history: dailyTopHistory });
  } catch (error) {
    console.error(error);
  }
}

async function refreshRealtimePanels() {
  if (state.refreshing || state.realtimeRefreshing) return;
  state.realtimeRefreshing = true;
  qs("status-text").textContent = "刷新中";
  try {
    const [overview, failures] = await Promise.all([
      fetchJson("./api/test-pool/realtime-overview?days=30&include_today_top_play=0"),
      fetchJson("./api/test-pool/failures?limit=80"),
    ]);

    renderOverall(overview);
    renderToday(overview);
    renderLineCards(overview, failures);
    renderAccountGroups(overview.account_groups || []);

    qs("status-text").textContent = "已连接";
    qs("db-path").textContent = overview.db_path || qs("db-path").textContent || "-";
    qs("last-updated").textContent = fmtDateTime(overview.last_exported_at);
  } catch (error) {
    showError(error);
  } finally {
    state.realtimeRefreshing = false;
  }

  loadTopPlay().catch((error) => console.error(error));
}

async function refreshAll({
  forceRounds = false,
  refreshTrend = false,
  refreshDailyHistory = false,
  forceTopPlay = false,
} = {}) {
  if (state.refreshing || state.realtimeRefreshing) return;
  state.refreshing = true;
  qs("status-text").textContent = "刷新中";
  try {
    const requests = [
      fetchJson("./api/test-pool/realtime-overview?days=30&include_today_top_play=0"),
      fetchJson("./api/test-pool/failures?limit=80"),
    ];
    if (!state.optionsLoaded) {
      requests.push(fetchJson("./api/test-pool/options"));
    }
    const responses = await Promise.all(requests);
    const [overview, failures, options] = responses;

    renderOverall(overview);
    renderToday(overview);
    renderLineCards(overview, failures);
    renderAccountGroups(overview.account_groups || []);

    if (options) {
      renderOptions(options);
      state.optionsLoaded = true;
    }

    const roundsPanel = qs("rounds-panel");
    if (forceRounds || roundsPanel.open || state.roundsLoaded) {
      await loadRounds();
    }

    qs("status-text").textContent = "已连接";
    qs("db-path").textContent = overview.db_path || "-";
    qs("last-updated").textContent = fmtDateTime(overview.last_exported_at);
  } catch (error) {
    showError(error);
  } finally {
    state.refreshing = false;
  }

  loadTopPlay({ force: forceTopPlay }).catch((error) => console.error(error));
  loadHeavyPanels({ refreshTrend, refreshDailyHistory }).catch((error) => console.error(error));
}

function bindEvents() {
  qs("refresh-btn").addEventListener("click", () => {
    refreshAll({
      forceRounds: qs("rounds-panel").open,
      forceTopPlay: true,
    }).catch((error) => console.error(error));
  });

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

  qs("rounds-panel").addEventListener("toggle", (event) => {
    if (event.currentTarget.open && !state.roundsLoaded) {
      loadRounds().catch(showError);
    }
  });

  qs("drawer-close").addEventListener("click", closeDrawer);
  qs("drawer-mask").addEventListener("click", closeDrawer);
}

function showError(error) {
  console.error(error);
  qs("status-text").textContent = "加载失败";
}

bindEvents();
refreshAll().catch((error) => console.error(error));
window.setInterval(() => {
  refreshRealtimePanels().catch((error) => console.error(error));
}, state.autoRefreshMs);
