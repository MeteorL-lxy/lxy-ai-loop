let layoutPromise = null;

export async function ensureLayoutLoaded() {
  if (document.getElementById("detail-drawer")) {
    return;
  }
  if (!layoutPromise) {
    const partials = {
      shell: "./partials/shell.html?v=20260624-1",
      home: "./partials/pages/home.html?v=20260624-1",
      lines: "./partials/pages/lines.html?v=20260624-1",
      content: "./partials/pages/content.html?v=20260624-1",
      trend: "./partials/pages/trend.html?v=20260624-1",
      pools: "./partials/pages/pools.html?v=20260624-1",
      rounds: "./partials/pages/rounds.html?v=20260624-1",
    };

    const loadPartial = async (url) => {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`加载布局失败: ${response.status}`);
      }
      return response.text();
    };

    layoutPromise = loadPartial(partials.shell)
      .then(async (shellHtml) => {
        const root = document.getElementById("app-root");
        if (!root) {
          throw new Error("未找到 app-root 容器");
        }
        root.innerHTML = shellHtml;

        const [home, lines, content, trend, pools, rounds] = await Promise.all([
          loadPartial(partials.home),
          loadPartial(partials.lines),
          loadPartial(partials.content),
          loadPartial(partials.trend),
          loadPartial(partials.pools),
          loadPartial(partials.rounds),
        ]);

        document.getElementById("page-home-slot").innerHTML = home;
        document.getElementById("page-lines-slot").innerHTML = lines;
        document.getElementById("page-content-slot").innerHTML = content;
        document.getElementById("page-trend-slot").innerHTML = trend;
        document.getElementById("page-pools-slot").innerHTML = pools;
        document.getElementById("page-rounds-slot").innerHTML = rounds;
      });
  }
  await layoutPromise;
}
