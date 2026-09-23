/* 顶部「⋯ 更多」菜单：宽屏把三项操作平铺，窄屏收成下拉。
 *
 * 背景（2026-09-23）：≤1340px 时 `.studio-header-actions` 以前整体 display:none，
 * 「框宽 / 功能编辑 / 打开 ComfyUI」没有任何入口；现在统一挂在 #studioMoreMenu 里，
 * 宽屏由脚本设 open=true（平铺，summary 用 CSS 隐藏），窄屏默认收起成下拉。
 */
(function () {
  "use strict";

  const WIDE_QUERY = "(min-width:1341px)";

  const byId = (id) => (typeof document === "undefined" ? null : document.getElementById(id));

  /** 宽屏平铺、窄屏下拉：只切 <details>.open，样式交给 CSS。 */
  function sync(menu, wide) {
    if (!menu) return null;
    menu.open = wide === true;
    return menu.open;
  }

  function install() {
    const menu = byId("studioMoreMenu");
    if (!menu) return false;
    const query = typeof window.matchMedia === "function" ? window.matchMedia(WIDE_QUERY) : null;
    const isWide = () => (query ? query.matches : true);
    sync(menu, isWide());
    if (query) {
      if (typeof query.addEventListener === "function") query.addEventListener("change", () => sync(menu, isWide()));
      else if (typeof query.addListener === "function") query.addListener(() => sync(menu, isWide()));
    }
    // 窄屏下拉：点其它地方或按 Esc 收起（宽屏是平铺，不受影响）。
    document.addEventListener("click", (event) => {
      if (!menu.open || isWide()) return;
      if (menu.contains(event.target)) return;
      menu.open = false;
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && menu.open && !isWide()) menu.open = false;
    });
    return true;
  }

  const testApi = { WIDE_QUERY, sync, install };

  window.EasyPanelHeaderMenu = testApi;
  if (typeof module !== "undefined" && module.exports) module.exports = testApi;

  if (typeof document === "undefined") return; // node 测试环境没有 DOM

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
})();
