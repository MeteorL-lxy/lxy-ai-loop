let layoutPromise = null;

export async function ensureLayoutLoaded() {
  if (document.getElementById("detail-drawer")) {
    return;
  }
  if (!layoutPromise) {
    layoutPromise = fetch("./partials/app-shell.html?v=20260617-1", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`加载布局失败: ${response.status}`);
        }
        return response.text();
      })
      .then((html) => {
        const root = document.getElementById("app-root");
        if (!root) {
          throw new Error("未找到 app-root 容器");
        }
        root.innerHTML = html;
      });
  }
  await layoutPromise;
}
