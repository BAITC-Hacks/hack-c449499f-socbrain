// SOCBrain — общая вкладочная логика (используется и в "Настройках",
// и там, где ещё понадобятся вкладки). Без бэкенда — чистый UI-переключатель.

document.addEventListener("DOMContentLoaded", () => {
  const tabs = document.querySelectorAll("[data-tab-target]");
  if (!tabs.length) return;

  tabs.forEach((tab) => {
    tab.addEventListener("click", (e) => {
      e.preventDefault();
      const targetId = tab.getAttribute("data-tab-target");
      const group = tab.closest("nav, .settings-nav, .tabs") || document;

      group.querySelectorAll("[data-tab-target]").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(`[data-tab-step]`).forEach((s) => s.classList.remove("active"));

      tab.classList.add("active");
      const step = document.querySelector(`[data-tab-step="${targetId}"]`);
      if (step) step.classList.add("active");
    });
  });
});
