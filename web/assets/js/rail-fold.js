/* 左侧「快捷工具」抽屉的折叠层：每个 details[data-rail-fold] 都能折叠 + 记忆状态 + 被调用时自动展开。
 *
 * 约定：
 *   - index.html 里给每块加 `data-rail-fold`（default 折叠），本脚本负责恢复/持久化开合状态
 *     （localStorage easyPanelRailFoldV1），并让「结果类」操作（读 DeepSeek 回答 / 读图还原 /
 *     打开透明蒙版编辑）自动展开对应面板，避免“点了按钮却看不到结果”；
 *   - 透明背景面板由 model-advanced.js 动态移进 #railTransparentMount，所以这里额外监听
 *     抽屉的新增节点，后到的折叠块也能拿到同样的行为。
 */
(function () {
  "use strict";

  const FOLD_STORAGE_KEY = "easyPanelRailFoldV1";

  const byId = (id) => (typeof document === "undefined" ? null : document.getElementById(id));

  /* ---------- 状态（可被 node 测试直接调用） ---------- */

  const memoryStore = {};

  function readStored(key) {
    try {
      return localStorage.getItem(key);
    } catch (_error) {
      return Object.prototype.hasOwnProperty.call(memoryStore, key) ? memoryStore[key] : null;
    }
  }

  function writeStored(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (_error) {
      memoryStore[key] = value;
    }
  }

  function readFoldState() {
    const raw = readStored(FOLD_STORAGE_KEY);
    if (!raw) return {};
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return {};
      const clean = {};
      Object.keys(parsed).forEach((key) => {
        if (key && typeof parsed[key] === "boolean") clean[key] = parsed[key];
      });
      return clean;
    } catch (_error) {
      return {};
    }
  }

  function writeFoldState(state) {
    const clean = {};
    Object.keys(state || {}).forEach((key) => {
      if (key) clean[key] = state[key] === true;
    });
    writeStored(FOLD_STORAGE_KEY, JSON.stringify(clean));
    return clean;
  }

  /** 记住某一块的展开状态（id 为空的自定义块用 data-fold-key 兜底）。 */
  function rememberFold(node, open) {
    const key = (node && (node.id || node.dataset?.foldKey)) || "";
    if (!key) return;
    const state = readFoldState();
    state[key] = open === true;
    writeFoldState(state);
  }

  /* ---------- 页面行为 ---------- */

  let installQueued = false;
  let observer = null;

  function foldNodes(root) {
    const scope = root || (typeof document === "undefined" ? null : document);
    if (!scope || typeof scope.querySelectorAll !== "function") return [];
    return Array.from(scope.querySelectorAll("details[data-rail-fold]"));
  }

  function applyFoldState(node, state) {
    const key = node.id || node.dataset?.foldKey || "";
    if (!key) return;
    if (typeof state[key] === "boolean") node.open = state[key];
    else node.open = false; // 默认折叠：抽屉只保留一行摘要
  }

  /** 展开包含该元素的所有 <details>（含折叠层），并滚到可见位置。 */
  function reveal(target) {
    const node = typeof target === "string" ? byId(target) : target;
    if (!node) return null;
    const panel = node.matches?.("details[data-rail-fold]") ? node : node.closest?.("details[data-rail-fold]") || node;
    let current = panel;
    while (current && current.tagName === "DETAILS") {
      if (!current.open) {
        current.open = true;
        if (current.dataset && current.dataset.railFold !== undefined) rememberFold(current, true);
      }
      current = current.parentElement?.closest?.("details") || null;
    }
    if (typeof panel.scrollIntoView === "function") {
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    return panel;
  }

  function updateCustomFeatureState() {
    const badge = byId("customFeatureState");
    if (!badge) return;
    const list = byId("customFeatureList");
    const count = list
      ? Array.from(list.children).filter((item) => !item.hidden && item.getAttribute?.("aria-hidden") !== "true").length
      : 0;
    badge.textContent = count ? `${count} 项快捷入口` : "快捷入口";
  }

  function updateImageReadState() {
    const badge = byId("imageReadState");
    if (!badge) return;
    const result = (byId("imgReadResult")?.textContent || "").trim();
    const preview = (byId("imgReadPreview")?.textContent || "").trim();
    badge.textContent = result || preview ? "已读取参数" : "上传或选输出图";
  }

  /** 服务端队列计数（“排队中 0 · 执行中 1 · 已完成 12 …”）→ 折叠摘要短标签。 */
  function summarizeTaskCounts(text) {
    const raw = String(text || "").trim();
    if (!raw || raw === "读取中…") return "读取中…";
    const pick = (label) => {
      const match = new RegExp(label + "\\s*(\\d+)").exec(raw);
      return match ? Number(match[1]) : 0;
    };
    const parts = [];
    const running = pick("执行中");
    const pending = pick("排队中");
    const failed = pick("失败");
    if (running) parts.push(`执行中 ${running}`);
    if (pending) parts.push(`排队 ${pending}`);
    if (failed) parts.push(`失败 ${failed}`);
    return parts.length ? parts.join(" · ") : "空闲";
  }

  function updateTaskQueueState() {
    const badge = byId("taskQueueSummary");
    if (!badge) return;
    badge.textContent = summarizeTaskCounts(byId("taskQueueServerCounts")?.textContent);
  }

  /** 队列计数是其它脚本按 id 写入的：监听它刷新折叠摘要。 */
  function observeTaskCounts() {
    const source = byId("taskQueueServerCounts");
    if (!source || typeof MutationObserver === "undefined" || source.dataset.railTaskBound === "1") return;
    source.dataset.railTaskBound = "1";
    new MutationObserver(() => updateTaskQueueState()).observe(source, {
      childList: true, characterData: true, subtree: true,
    });
    updateTaskQueueState();
  }

  function bindNode(node) {
    if (node.dataset.railFoldBound === "1") return;
    node.dataset.railFoldBound = "1";
    node.addEventListener("toggle", () => rememberFold(node, node.open));
  }

  function install() {
    const nodes = foldNodes();
    if (!nodes.length) return false;
    const state = readFoldState();
    nodes.forEach((node) => {
      applyFoldState(node, state);
      bindNode(node);
    });
    updateCustomFeatureState();
    updateImageReadState();
    updateTaskQueueState();
    observeTaskCounts();
    observeRail();
    return true;
  }

  function queueInstall() {
    if (installQueued) return;
    installQueued = true;
    const run = () => {
      installQueued = false;
      install();
    };
    if (typeof window.setTimeout === "function") window.setTimeout(run, 0);
    else run();
  }

  /** 透明背景等面板是动态移进抽屉的：新节点出现时补一次折叠状态与监听。 */
  function observeRail() {
    if (observer || typeof MutationObserver === "undefined") return;
    const rail = document.querySelector(".studio-left");
    if (!rail) return;
    observer = new MutationObserver(() => queueInstall());
    observer.observe(rail, { childList: true, subtree: true });
  }

  function wrapGlobal(name, after) {
    const original = window[name];
    if (typeof original !== "function" || original.__railFoldWrapped) return false;
    const wrapped = function () {
      const result = original.apply(this, arguments);
      try {
        after();
      } catch (_error) {
        /* 折叠层只是显示层，不影响主流程 */
      }
      return result;
    };
    wrapped.__railFoldWrapped = true;
    window[name] = wrapped;
    return true;
  }

  function wireAutoReveal() {
    // 结果出现在这些面板里：先展开再执行，避免“点了按钮看不到结果”。
    wrapGlobal("openDeepSeekWeb", () => reveal("translationCard"));
    wrapGlobal("readDeepSeekClipboard", () => reveal("translationCard"));
    wrapGlobal("convertChinese", () => reveal("translationCard"));
    wrapGlobal("copyDeepSeekInstructionManually", () => reveal("translationCard"));
    wrapGlobal("readImageInfo", () => setTimeout(updateImageReadState, 0));
    wrapGlobal("readOutputImage", () => setTimeout(updateImageReadState, 0));
    wrapGlobal("openTransparentMaskEditor", () => reveal("transparentOutputPanel"));
  }

  const testApi = {
    FOLD_STORAGE_KEY,
    readFoldState,
    writeFoldState,
    rememberFold,
    foldNodes,
    applyFoldState,
    summarizeTaskCounts,
    reveal,
    install,
  };

  window.EasyPanelRailFold = testApi;
  window.easyPanelRevealRail = reveal;
  if (typeof module !== "undefined" && module.exports) module.exports = testApi;

  if (typeof document === "undefined") return; // node 测试环境没有 DOM

  function boot() {
    install();
    wireAutoReveal();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
