/* Prompt 方言：数据库存 Danbooru 原形，插入时按模型方言转换。
 *
 * 规则与 easy_panel_app/prompt_dialect.py 一一对应（tests/test_prompt_dialect.py 做双端一致性校验）：
 *   - Anima：下划线转空格（long_hair → long hair），score_* 保留下划线，画师标签用 @name；
 *   - Illustrious / 光辉：默认原样（long_hair），可切空格方言做对照；
 *   - Krea 2：自然语言，空格方言；
 *   - LoRA 触发词永不自动转换（protect:true）。
 */
(function () {
  "use strict";

  const STORAGE_KEY = "easyPanelPromptDialect";
  const DIALECTS = {
    auto: "跟随模型（Anima 空格 / 其他原样）",
    space: "空格方言（下划线换空格）",
    canonical: "Danbooru 原样（保留下划线）",
  };
  const SPACE_FAMILIES = ["anima", "krea2"];
  const SCORE_RE = /^score_\d+(?:_up)?$/i;
  const ARTIST_PREFIX = "@";

  const byId = (id) => (typeof document === "undefined" ? null : document.getElementById(id));
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

  function family() {
    try {
      return String((window.modelFamilyClient && window.modelFamilyClient()) || "");
    } catch (_error) {
      return "";
    }
  }

  function currentDialect() {
    const stored = String(readStored(STORAGE_KEY) || "").toLowerCase();
    return Object.prototype.hasOwnProperty.call(DIALECTS, stored) ? stored : "auto";
  }

  function setDialect(value) {
    const choice = String(value || "").toLowerCase();
    if (!Object.prototype.hasOwnProperty.call(DIALECTS, choice)) return currentDialect();
    writeStored(STORAGE_KEY, choice);
    const select = typeof document !== "undefined" ? byId("promptDialect") : null;
    if (select) select.value = choice;
    updateHint();
    return choice;
  }

  function resolve(dialect) {
    const choice = String(dialect || currentDialect()).toLowerCase();
    if (choice === "space" || choice === "canonical") return choice;
    return SPACE_FAMILIES.indexOf(family()) >= 0 ? "space" : "canonical";
  }

  function classify(tag, kind) {
    const value = String(tag || "").trim();
    if (kind) return kind;
    if (!value) return "unknown";
    if (SCORE_RE.test(value)) return "score";
    if (value.charAt(0) === ARTIST_PREFIX) return "artist";
    return "general";
  }

  function formatTag(tag, options) {
    const opts = options || {};
    const value = String(tag || "").trim();
    if (!value) return "";
    if (opts.protect || classify(value, opts.kind) === "trigger") return value;
    const dialect = resolve(opts.dialect);
    if (dialect === "canonical") return value;
    if (SCORE_RE.test(value)) return value;
    const kind = classify(value, opts.kind);
    if (kind === "artist" || value.charAt(0) === ARTIST_PREFIX) {
      const body = value.charAt(0) === ARTIST_PREFIX ? value.slice(1) : value;
      return (ARTIST_PREFIX + body.replace(/_/g, " ")).trim();
    }
    return value.replace(/_/g, " ");
  }

  function formatTags(tags, options) {
    return (tags || []).map((tag) => formatTag(tag, options));
  }

  function describe(dialect) {
    const choice = String(dialect || currentDialect()).toLowerCase();
    const resolved = resolve(choice);
    if (choice === "space" || choice === "canonical") return DIALECTS[resolved] + "（手动指定）";
    const key = family();
    return DIALECTS[resolved] + (key ? `（按当前模型：${key}）` : "（按当前模型）");
  }

  /* ---------------------------------------------------------------- 界面 */

  function dialectOptions() {
    return Object.keys(DIALECTS).map((key) =>
      `<option value="${key}">${DIALECTS[key]}</option>`).join("");
  }

  function updateHint() {
    if (typeof document === "undefined") return;
    const hint = byId("promptDialectHint");
    if (!hint) return;
    const resolved = resolve();
    const sample = resolved === "space" ? "long hair / @artist name" : "long_hair";
    hint.textContent = `${describe()} · score_* 与 LoRA 触发词不转换 · 本模型写入示例：${sample}`;
  }

  function installUi() {
    if (typeof document === "undefined") return;
    const block = document.querySelector(".prompt-tag-search .tag-target");
    if (!block || byId("promptDialect")) return;
    const wrap = document.createElement("span");
    wrap.className = "prompt-dialect";
    wrap.innerHTML = `<select id="promptDialect" title="插入标签时的写法：数据库始终保存 Danbooru 原形，这里只决定写入 Prompt 的形式。">${dialectOptions()}</select>`;
    block.appendChild(wrap);
    const hint = document.createElement("div");
    hint.id = "promptDialectHint";
    hint.className = "small prompt-dialect-hint";
    block.parentElement.appendChild(hint);
    const select = byId("promptDialect");
    select.value = currentDialect();
    select.addEventListener("change", () => {
      setDialect(select.value);
      if (window.EasyPanelVisualTags && typeof window.EasyPanelVisualTags.refresh === "function") {
        window.EasyPanelVisualTags.refresh();
      }
    });
    updateHint();
  }

  function wrapModelChanged() {
    const original = window.modelChanged;
    if (typeof original !== "function" || original.__dialectWrapped) return;
    const wrapped = function () {
      const result = original.apply(this, arguments);
      try {
        updateHint();
      } catch (_error) { /* 提示更新失败不影响换模型 */ }
      return result;
    };
    wrapped.__dialectWrapped = true;
    window.modelChanged = wrapped;
  }

  const testApi = {
    STORAGE_KEY, DIALECTS, SPACE_FAMILIES,
    family, currentDialect, setDialect, resolve, classify, formatTag, formatTags, describe,
    updateHint, installUi,
  };
  window.EasyPanelDialect = testApi;
  if (typeof module !== "undefined" && module.exports) module.exports = testApi;

  if (typeof document === "undefined") return;   // node 测试环境没有 DOM

  function boot() {
    installUi();
    wrapModelChanged();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
