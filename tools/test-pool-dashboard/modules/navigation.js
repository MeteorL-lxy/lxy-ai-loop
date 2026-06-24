import { state } from "./state.js";

export const PAGES = ["home", "lines", "content", "trend", "pools", "rounds"];

export function setCurrentPage(page) {
  const nextPage = PAGES.includes(page) ? page : "home";
  state.currentPage = nextPage;
  document.querySelectorAll(".page-nav-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === nextPage);
  });
  document.querySelectorAll(".dashboard-page").forEach((pageNode) => {
    pageNode.classList.toggle("active", pageNode.dataset.page === nextPage);
  });
}

export function initNavigation(onChange) {
  document.querySelectorAll(".page-nav-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const nextPage = button.dataset.page || "home";
      if (nextPage === state.currentPage) return;
      setCurrentPage(nextPage);
      if (typeof onChange === "function") {
        onChange(nextPage);
      }
    });
  });
  setCurrentPage(state.currentPage || "home");
}
