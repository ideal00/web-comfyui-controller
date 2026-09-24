/* 🇨🇳 解析词条（Prompt Explainer）：把别人整段英文提示词拆成可理解、可删除、可恢复的词条。
 *
 * 定位不是「翻译功能」：英文永远是最终提示词，中文只是解释。
 *   ① 切分：逗号 / 分号 / 换行 = 一个词条（**不做单词级翻译**，短语整体翻）
 *   ② 保护：LoRA、score_*、人数标签、artist:name 这类结构 token 不送翻译，标 🔒
 *   ③ 翻译：EN→ZH 走后端 /api/argos-translate（批量一次请求 + 服务端缓存），
 *      前端再叠一层 localStorage 词条表（同一 tag 二次出现直接命中）
 *   ④ 编辑：点整行 = 保留/删除，实时把 serialize 结果写回原 textarea；
 *      「恢复原文」随时回到最初粘贴的那一版
 *
 * 与 prompt_dialect 严格隔离：这里只做「理解 / 删除」，不改写 canonical tag 写法。
 */
(function (global) {
  "use strict";

  const SECTION_FIELDS = Object.freeze([
    ["promptPose", "姿势"],
    ["promptExpression", "表情"],
    ["promptClothing", "服装与材质"],
    ["promptComposition", "构图与镜头"],
    ["promptScene", "场景"],
    ["promptLighting", "光线"],
    ["promptStyle", "画风与上色"],
    ["promptSubject", "人物与角色"],
    ["promptAppearance", "外貌"],
    ["promptNaturalLanguage", "自然语言"],
    ["prompt", "其他补充"],
  ]);
  const CACHE_KEY = "easyPanelPromptGlossaryV1";
  const MAX_BATCH = 32;
  const SPLIT = /[,，;；\n]+/;

  //: 结构 token：这些原样保留、标 🔒、不翻译（LoRA 被翻成「萝拉」这类事故就是这么来的）。
  const PROTECTED_PATTERNS = [
    /^<(?:lora|lyco|hypernet|loha)[^>]*>$/i,
    /^score_\d+(?:_up)?$/i,
    /^\d+\s*(?:girl|girls|boy|boys|other|others)$/i,
    /^(?:solo|multiple_girls|multiple_boys)$/i,
    /^(?:artist|character|series|copyright|studio|meta|rating)\s*:/i,
    /^@[\w.\-]+$/,
    /^v?\d+(?:\.\d+)*$/,
    /^:[a-z0-9<>]+$/,
    /^[-+*/=<>~^|]+$/,
  ];

  function text(value) {
    return String(value == null ? "" : value).trim();
  }

  function isProtectedToken(value) {
    const token = text(value);
    if (!token) return false;
    return PROTECTED_PATTERNS.some((pattern) => pattern.test(token));
  }

  function splitTokens(value) {
    return String(value == null ? "" : value)
      .split(SPLIT)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  /** 词条对象：英文原文 + 状态 + 中文解释（id 用于 DOM 定位，不参与序列化）。 */
  function parsePromptTokens(value) {
    let index = 0;
    return splitTokens(value).map((token) => ({
      id: `px${index++}`,
      text: token,
      enabled: true,
      protected: isProtectedToken(token),
      translation: "",
    }));
  }

  /** 只保留 enabled 的词条，重新用 ", " 拼回（顺带修掉多余逗号）。 */
  function serializeTokens(tokens) {
    return (Array.isArray(tokens) ? tokens : [])
      .filter((token) => token && token.enabled !== false && text(token.text))
      .map((token) => text(token.text))
      .join(", ");
  }

  /** 需要翻译的词条（保护 token 与已有解释的跳过）。 */
  function pendingTokens(tokens, cache) {
    const glossary = cache && typeof cache === "object" ? cache : {};
    return (Array.isArray(tokens) ? tokens : []).filter((token) => token
      && !token.protected && !text(token.translation) && !glossary[token.text.toLowerCase()]);
  }

  /** 把缓存里已有的解释回填到词条上。 */
  function applyGlossary(tokens, cache) {
    const glossary = cache && typeof cache === "object" ? cache : {};
    for (const token of Array.isArray(tokens) ? tokens : []) {
      if (token.translation) continue;
      const hit = glossary[String(token.text || "").toLowerCase()];
      if (hit) token.translation = String(hit);
    }
    return tokens;
  }

  /**
   * 面板自带词表（panel.js 的 chineseMap：中文 → 英文）的反向映射。
   * 常见 tag 直接拿到手写中文（looking at viewer → 看向观众），比通用机翻准；
   * 一个英文对应多个中文时取第一个（词表里越靠前的越常用）。
   */
  function reverseChineseMap() {
    let source = {};
    try {
      const map = chineseMap; // eslint-disable-line no-undef
      if (map && typeof map === "object") source = map;
    } catch (_) {
      source = {};
    }
    const reversed = {};
    for (const [zh, en] of Object.entries(source)) {
      const key = String(en || "").toLowerCase().trim();
      if (!key || reversed[key]) continue;
      reversed[key] = String(zh);
    }
    return reversed;
  }

  /** 先拿词表反查填一批，剩下的才交给离线机翻。 */
  function seedFromReverseMap(tokens, cache) {
    const glossaryMap = cache && typeof cache === "object" ? cache : {};
    const reversed = reverseChineseMap();
    let seeded = 0;
    for (const token of Array.isArray(tokens) ? tokens : []) {
      if (!token || token.protected || text(token.translation)) continue;
      const key = String(token.text || "").toLowerCase().trim();
      if (!key) continue;
      const label = glossaryMap[key] || reversed[key];
      if (!label) continue;
      token.translation = String(label);
      glossaryMap[key] = String(label);
      seeded += 1;
    }
    return seeded;
  }

  function statsFor(tokens) {
    const list = Array.isArray(tokens) ? tokens : [];
    return {
      total: list.length,
      kept: list.filter((token) => token.enabled !== false).length,
      removed: list.filter((token) => token.enabled === false).length,
      protectedCount: list.filter((token) => token.protected).length,
    };
  }

  function summaryText(tokens) {
    const stats = statsFor(tokens);
    return `已保留 ${stats.kept} / ${stats.total} 个词条` + (stats.protectedCount
      ? `（🔒 ${stats.protectedCount} 个结构词条不参与翻译）` : "");
  }

  const testApi = {
    SECTION_FIELDS,
    CACHE_KEY,
    PROTECTED_PATTERNS,
    isProtectedToken,
    splitTokens,
    parsePromptTokens,
    serializeTokens,
    pendingTokens,
    applyGlossary,
    reverseChineseMap,
    seedFromReverseMap,
    statsFor,
    summaryText,
  };
  global.EasyPanelPromptExplainer = testApi;
  if (typeof module !== "undefined" && module.exports) module.exports = testApi;
  if (typeof global.document === "undefined") return;

  const byId = (id) => global.document.getElementById(id);
  const esc = (value) => String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  const STYLE = `
dialog.prompt-explain{border:1px solid var(--line,#3a3a46);border-radius:12px;padding:12px;max-width:min(96vw,720px);background:#16161c;color:inherit}
dialog.prompt-explain::backdrop{background:rgba(0,0,0,.55)}
dialog.prompt-explain .px-head{display:flex;justify-content:space-between;align-items:center;gap:10px}
dialog.prompt-explain .px-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}
dialog.prompt-explain .px-list{margin-top:8px;max-height:48vh;overflow:auto;border:1px solid var(--line,#3a3a46);border-radius:10px}
dialog.prompt-explain .px-row{display:grid;grid-template-columns:22px minmax(0,1.2fr) minmax(0,1fr) 26px;gap:8px;align-items:center;padding:5px 8px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,.05);font-size:12.5px}
dialog.prompt-explain .px-row:last-child{border-bottom:0}
dialog.prompt-explain .px-row:hover{background:rgba(255,255,255,.04)}
dialog.prompt-explain .px-row.removed{color:var(--muted,#8b8b99);text-decoration:line-through}
dialog.prompt-explain .px-row.protected{cursor:default}
dialog.prompt-explain .px-mark{text-align:center}
dialog.prompt-explain .px-en{overflow-wrap:anywhere}
dialog.prompt-explain .px-zh{color:var(--muted,#9a9aa8);overflow-wrap:anywhere}
dialog.prompt-explain .px-row.removed .px-zh{text-decoration:none}
dialog.prompt-explain .px-retrans{border:0;background:transparent;color:inherit;cursor:pointer;font-size:13px;opacity:.65}
dialog.prompt-explain .px-empty{padding:10px;color:var(--muted,#9a9aa8)}
dialog.prompt-explain .px-foot{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}
`;

  let dialog = null;
  let state = { fieldId: SECTION_FIELDS[0][0], original: "", tokens: [], filter: "all", busy: false };
  let glossary = {};

  function injectStyle() {
    if (byId("promptExplainStyle")) return;
    const style = global.document.createElement("style");
    style.id = "promptExplainStyle";
    style.textContent = STYLE;
    global.document.head.appendChild(style);
  }

  function loadGlossary() {
    try {
      const raw = global.localStorage.getItem(CACHE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      glossary = parsed && typeof parsed === "object" ? parsed : {};
    } catch (_) {
      glossary = {};
    }
  }

  function saveGlossary() {
    try {
      const keys = Object.keys(glossary);
      if (keys.length > 800) {
        for (const key of keys.slice(0, keys.length - 800)) delete glossary[key];
      }
      global.localStorage.setItem(CACHE_KEY, JSON.stringify(glossary));
    } catch (_) {
      /* 隐私模式下写不进去也不影响本次使用 */
    }
  }

  function labelFor(fieldId) {
    const found = SECTION_FIELDS.find(([id]) => id === fieldId);
    return found ? found[1] : fieldId;
  }

  function fieldValue(fieldId) {
    const node = byId(fieldId);
    return node ? String(node.value || "") : "";
  }

  function writeField(value) {
    const node = byId(state.fieldId);
    if (!node) return false;
    node.value = value;
    if (typeof global.promptEditorChanged === "function") global.promptEditorChanged();
    return true;
  }

  function setStatus(message, error) {
    const node = byId("promptExplainStatus");
    if (!node) return;
    node.textContent = message;
    node.classList.toggle("diagnostic-error", !!error);
  }

  async function translatePending() {
    // 词表反查（本地手写中文）先填一批，剩下的才走批量离线翻译。
    seedFromReverseMap(state.tokens, glossary);
    const pending = pendingTokens(state.tokens, glossary);
    if (!pending.length) return 0;
    const texts = [...new Set(pending.map((token) => token.text))];
    // 后端一次最多 32 段；这里统一走 offline-translate 的分批接口，长提示词也不会撞上限。
    const batch = typeof global.easyPanelArgosBatch === "function"
      ? global.easyPanelArgosBatch
      : async (items) => {
        const response = await fetch("/api/argos-translate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ texts: items.slice(0, MAX_BATCH), from: "en", to: "zh" }),
        });
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        return data.texts || [];
      };
    const translations = await batch(texts, { from: "en", to: "zh" });
    texts.forEach((key, index) => {
      const translated = text(translations[index]);
      if (!key || !translated) return;
      glossary[key.toLowerCase()] = translated;
    });
    saveGlossary();
    applyGlossary(state.tokens, glossary);
    return texts.length;
  }

  function visibleTokens() {
    if (state.filter === "removed") {
      return state.tokens.filter((token) => token.enabled === false);
    }
    if (state.filter === "kept") {
      return state.tokens.filter((token) => token.enabled !== false);
    }
    return state.tokens;
  }

  function renderList() {
    const list = dialog && dialog.querySelector('[data-px="list"]');
    if (!list) return;
    const rows = visibleTokens();
    if (!rows.length) {
      list.innerHTML = `<div class="px-empty">${state.tokens.length
        ? "当前筛选下没有词条。" : "这个分区没有可解析的英文词条。"}</div>`;
      return;
    }
    list.innerHTML = rows.map((token) => {
      const index = state.tokens.indexOf(token);
      const mark = token.protected ? "🔒" : (token.enabled === false ? "✕" : "✓");
      const classes = ["px-row"];
      if (token.enabled === false) classes.push("removed");
      if (token.protected) classes.push("protected");
      return `<div class="${classes.join(" ")}" data-px="row" data-index="${index}">
        <span class="px-mark">${mark}</span>
        <span class="px-en">${esc(token.text)}</span>
        <span class="px-zh">${esc(token.translation || (token.protected ? "结构词条，原样保留" : "…"))}</span>
        <button class="px-retrans" type="button" data-px="retrans" data-index="${index}" title="重新翻译">↻</button>
      </div>`;
    }).join("");
  }

  function renderSummary() {
    const summary = dialog && dialog.querySelector('[data-px="summary"]');
    if (summary) summary.textContent = summaryText(state.tokens);
    const filter = dialog && dialog.querySelector('[data-px="filter"]');
    if (filter) {
      filter.textContent = state.filter === "removed" ? "显示全部"
        : (state.filter === "kept" ? "仅看已保留" : "仅看已删除");
    }
  }

  function render() {
    if (!dialog) return;
    renderList();
    renderSummary();
  }

  function buildDialog() {
    dialog = global.document.createElement("dialog");
    dialog.id = "promptExplainDialog";
    dialog.className = "hires-compare prompt-explain";
    dialog.innerHTML = `
      <div class="px-head"><b>🇨🇳 解析词条</b>
        <button class="secondary" type="button" data-px="close">关闭</button></div>
      <div class="small">英文仍然是最终提示词：这里只把整段拆成词条、给中文解释，点整行 = 保留 / 删除，改完实时写回分区。LoRA、score_*、人数标签等结构词条带 🔒 不翻译。</div>
      <div class="px-bar">
        <label class="small">分区 <select data-px="field">${SECTION_FIELDS.map(([id, label]) =>
          `<option value="${id}">${label}</option>`).join("")}</select></label>
        <button class="secondary" type="button" data-px="reparse">重新解析</button>
        <button class="secondary" type="button" data-px="keepAll">全保留</button>
        <button class="secondary" type="button" data-px="dropAll">全删除</button>
        <button class="secondary" type="button" data-px="filter">仅看已删除</button>
      </div>
      <div class="px-list" data-px="list"></div>
      <div class="px-foot">
        <span class="small" data-px="summary"></span>
        <span class="small" data-px="status" id="promptExplainStatus"></span>
        <button class="secondary" type="button" data-px="restore">恢复原文</button>
      </div>`;
    dialog.addEventListener("click", handleClick);
    dialog.addEventListener("change", (event) => {
      if (event.target && event.target.dataset && event.target.dataset.px === "field") {
        analyze(event.target.value);
      }
    });
    global.document.body.appendChild(dialog);
    return dialog;
  }

  function toggleToken(index) {
    const token = state.tokens[index];
    if (!token) return;
    if (token.protected) {
      setStatus("🔒 结构词条（LoRA / score / 人数标签）不参与删除。", false);
      return;
    }
    token.enabled = token.enabled === false;
    writeField(serializeTokens(state.tokens));
    setStatus(token.enabled === false
      ? `已删除「${token.text}」；分区已同步。`
      : `已恢复「${token.text}」；分区已同步。`, false);
    render();
  }

  async function retranslate(index) {
    const token = state.tokens[index];
    if (!token) return;
    if (token.protected) {
      setStatus("🔒 结构词条不翻译。", false);
      return;
    }
    delete glossary[token.text.toLowerCase()];
    token.translation = "";
    saveGlossary();
    setStatus(`正在重新翻译「${token.text}」…`, false);
    try {
      await translatePending();
      render();
      setStatus(token.translation ? `已重新翻译「${token.text}」：${token.translation}` : "没有取到新的解释。", false);
    } catch (error) {
      setStatus("重新翻译失败：" + (error && error.message ? error.message : error), true);
    }
  }

  function handleClick(event) {
    const trigger = event.target.closest ? event.target.closest("[data-px]") : null;
    if (!trigger) return;
    const action = trigger.dataset.px;
    if (action === "close") {
      dialog.close();
    } else if (action === "row") {
      toggleToken(Number(trigger.dataset.index));
    } else if (action === "retrans") {
      event.stopPropagation();
      retranslate(Number(trigger.dataset.index));
    } else if (action === "reparse") {
      analyze(state.fieldId);
    } else if (action === "keepAll") {
      state.tokens.forEach((token) => { token.enabled = true; });
      writeField(serializeTokens(state.tokens));
      setStatus("已全部保留。", false);
      render();
    } else if (action === "dropAll") {
      state.tokens.forEach((token) => { if (!token.protected) token.enabled = false; });
      writeField(serializeTokens(state.tokens));
      setStatus("已删除全部可删除词条（🔒 结构词条保留）。", false);
      render();
    } else if (action === "filter") {
      state.filter = state.filter === "removed" ? "all" : "removed";
      renderSummary();
      renderList();
    } else if (action === "restore") {
      writeField(state.original);
      state.tokens = seedFromReverseMap(
        applyGlossary(parsePromptTokens(state.original), glossary), glossary);
      state.filter = "all";
      setStatus("已恢复解析前的原文。", false);
      render();
    }
  }

  /**
   * 解析指定分区（默认用当前聚焦的分区）。doc §20：EasyPanelPromptExplainer.analyze("promptPose")
   */
  async function analyze(fieldId, options) {
    injectStyle();
    if (!dialog) buildDialog();
    const wanted = SECTION_FIELDS.some(([id]) => id === fieldId) ? fieldId : state.fieldId;
    state.fieldId = wanted;
    // 默认（没传 options）就从分区重新读一遍；显式 reset:false 才保留现有词条状态。
    const reset = !options || options.reset !== false;
    if (reset) {
      state.original = fieldValue(wanted);
      state.tokens = applyGlossary(parsePromptTokens(state.original), glossary);
      state.filter = "all";
      seedFromReverseMap(state.tokens, glossary);
    }
    const select = dialog.querySelector('[data-px="field"]');
    if (select) select.value = wanted;
    if (!dialog.open) dialog.showModal();
    render();
    if (!state.tokens.length) {
      setStatus(`「${labelFor(wanted)}」分区还是空的。`, true);
      return { tokens: [], translated: 0 };
    }
    setStatus("正在解析词条（本地离线翻译）…", false);
    try {
      const translated = await translatePending();
      render();
      setStatus(translated
        ? `翻译完成：${translated} 个词条（其余命中本地词条表）。`
        : "全部命中本地词条表，没有新增翻译。", false);
      return { tokens: state.tokens, translated };
    } catch (error) {
      setStatus("离线翻译不可用：" + (error && error.message ? error.message : error), true);
      return { tokens: state.tokens, translated: 0, error: String(error && error.message || error) };
    }
  }

  /** 把当前词条状态写回分区（点行已经是实时同步，这个入口给脚本/测试用）。 */
  function apply() {
    return writeField(serializeTokens(state.tokens));
  }

  /** 恢复解析前的原文。 */
  function restore() {
    return writeField(state.original);
  }

  function pickTargetField() {
    const active = global.document.activeElement;
    const id = active && active.id ? active.id : "";
    if (SECTION_FIELDS.some(([fieldId]) => fieldId === id)) return id;
    return state.fieldId;
  }

  function openForActiveField() {
    return analyze(pickTargetField());
  }

  global.easyPanelOpenPromptExplainer = openForActiveField;
  global.easyPanelAnalyzePromptField = (fieldId) => analyze(fieldId);
  Object.assign(global.EasyPanelPromptExplainer, { analyze, apply, restore, open: openForActiveField });
})(typeof window !== "undefined" ? window : globalThis);
