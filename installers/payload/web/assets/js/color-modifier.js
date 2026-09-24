/* 颜色修饰（Color Modifier）：写入标签时可选的前置修饰词。
 *
 * 设计（2026-09-24 用户方案，两个选词入口共用同一条写入管线）：
 *   可视化词条库 ─┐
 *                 ├─→ compose() ─→ Prompt Dialect ─→ appendEnglish()
 *   标签搜索与填入 ┘
 *
 * 规则：
 *   - 只改“写入的那一刻”：数据库（TAG_INDEX / visual_tag_index / Danbooru 云）始终存原形，
 *     修饰词只是 UI 状态（localStorage），不写进任何数据；
 *   - 只在颜色标签上生效：颜色词后面必须紧跟可着色属性（hair / eyes / skin / dress …），
 *     所以 blue_hair → dark_blue_hair，而 long_hair / hair_ribbon / ice_cream / blue_archive 原样返回；
 *   - 不叠加：dark_blue_hair + dark 原样返回；换成 pale 则替换成 pale_blue_hair；
 *   - 画师标签（@name）、score_*、含括号的角色/作品限定名（red_(pokemon)）一律不处理。
 */
(function () {
  "use strict";

  const STORAGE_KEY = "easyPanelColorModifierV1";

  // 用户选定的修饰词表（明度/深浅 + 饱和度/鲜艳程度），label 供下拉显示。
  const MODIFIERS = [
    { key: "light", label: "浅 light" },
    { key: "dark", label: "深 dark" },
    { key: "pale", label: "淡 pale" },
    { key: "deep", label: "浓 deep" },
    { key: "bright", label: "明亮 bright" },
    { key: "vivid", label: "鲜艳 vivid" },
    { key: "muted", label: "压低 muted" },
    { key: "soft", label: "柔和 soft" },
    { key: "desaturated", label: "低饱和 desaturated" },
    { key: "rich", label: "浓郁 rich" },
  ];

  // 颜色词（Danbooru 常见色；只作为“是否颜色标签”的第一道判断）。
  const COLOR_WORDS = [
    "black", "white", "gray", "grey", "silver", "blonde",
    "red", "orange", "yellow", "green", "blue", "cyan", "teal", "turquoise", "aqua",
    "purple", "violet", "indigo", "pink", "magenta", "crimson", "scarlet", "maroon",
    "brown", "beige", "cream", "ivory", "navy", "lavender", "lilac", "azure",
    "emerald", "mint", "peach", "amber", "hazel", "golden", "platinum",
  ];

  // 颜色词后面必须紧跟这些“可着色属性”，否则不算颜色标签。
  // 目的：挡住 blue_archive（作品）、ice_cream / cream_pie（食物）这类同形陷阱。
  const COLORABLE_ATTRIBUTES = [
    // 身体与毛发
    "hair", "eyes", "eye", "eyebrows", "eyelashes", "pupils", "iris", "skin", "fur", "feathers",
    "scales", "horns", "horn", "tail", "wings", "nails", "lips", "lipstick", "blush", "markings",
    "gradient", "streaks", "streak", "highlights", "tips", "ends", "roots", "bangs", "braid",
    "braids", "ponytail", "twintails", "ahoge",
    // 服装与配饰
    "dress", "skirt", "shirt", "blouse", "jacket", "coat", "cape", "cloak", "hoodie", "sweater",
    "cardigan", "swimsuit", "bikini", "kimono", "yukata", "qipao", "uniform", "bodysuit", "leotard",
    "stockings", "thighhighs", "pantyhose", "socks", "gloves", "scarf", "tie", "ribbon", "bow",
    "shorts", "pants", "jeans", "boots", "shoes", "heels", "sandals", "hat", "beret", "cap",
    "hood", "vest", "neckwear", "lingerie", "camisole", "apron", "sleeves",
    // 场景与其他
    "background", "sky", "wall", "flower", "flowers", "petals", "theme",
  ];

  const MODIFIER_KEYS = {};
  MODIFIERS.forEach((item) => { MODIFIER_KEYS[item.key] = item.label; });
  const COLOR_SET = {};
  COLOR_WORDS.forEach((word) => { COLOR_SET[word] = true; });
  const ATTRIBUTE_SET = {};
  COLORABLE_ATTRIBUTES.forEach((word) => { ATTRIBUTE_SET[word] = true; });

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

  function normalize(value) {
    const key = String(value == null ? "" : value).trim().toLowerCase();
    return Object.prototype.hasOwnProperty.call(MODIFIER_KEYS, key) ? key : "";
  }

  function current() {
    return normalize(readStored(STORAGE_KEY));
  }

  function notifyVisualLibrary() {
    if (typeof document === "undefined") return;
    const overlay = byId("vtlOverlay");
    if (!overlay || overlay.hidden) return;
    const library = window.EasyPanelVisualTags;
    if (library && typeof library.rerender === "function") library.rerender();
  }

  function set(value) {
    const key = normalize(value);
    writeStored(STORAGE_KEY, key);
    const select = byId("colorModifier");
    if (select && select.value !== key) select.value = key;
    updateHint();
    notifyVisualLibrary();
    return key;
  }

  function describe(value) {
    const key = normalize(value === undefined ? current() : value);
    return key ? MODIFIER_KEYS[key] : "无";
  }

  function blocked(tag) {
    if (tag.charAt(0) === "@") return true;                       // 画师标签
    if (tag.indexOf("(") >= 0 || tag.indexOf(")") >= 0) return true;  // 角色/作品限定名
    if (/^score_\d+/i.test(tag)) return true;                     // score_* 永不处理
    return false;
  }

  /* 标签可能是 Danbooru 原形（blue_hair）或本地标签库的空格写法（blue hair），
   * 两种都要能拆词，并按原分隔符拼回去。 */
  function splitTag(raw) {
    if (raw.indexOf("_") >= 0) return { tokens: raw.split("_"), separator: "_" };
    return { tokens: raw.split(/\s+/), separator: " " };
  }

  /* 颜色标签分析：返回 { colorIndex, modifierIndex }，不适用时 colorIndex = -1。
   * 插入点是“最靠前的颜色词”，但整条标签必须至少有一个颜色词后面紧跟可着色属性，
   * 否则视为同形陷阱（blue_archive / ice_cream）不处理。 */
  function analyze(tag) {
    const raw = String(tag == null ? "" : tag).trim();
    if (!raw || blocked(raw)) return { colorIndex: -1, modifierIndex: -1 };
    const tokens = splitTag(raw.toLowerCase()).tokens;
    const colorIndexes = [];
    let applicable = false;
    for (let index = 0; index < tokens.length; index += 1) {
      if (!COLOR_SET[tokens[index]]) continue;
      colorIndexes.push(index);
      const next = tokens[index + 1];
      if (next && ATTRIBUTE_SET[next]) applicable = true;
    }
    if (!applicable || !colorIndexes.length) return { colorIndex: -1, modifierIndex: -1 };
    const colorIndex = colorIndexes[0];
    const previous = colorIndex > 0 ? tokens[colorIndex - 1] : "";
    return {
      colorIndex,
      modifierIndex: Object.prototype.hasOwnProperty.call(MODIFIER_KEYS, previous) ? colorIndex - 1 : -1,
    };
  }

  function isColorTag(tag) {
    return analyze(tag).colorIndex >= 0;
  }

  /* 核心组合函数：原形 tag + 当前颜色修饰 → 写入用原形（仍保有下划线，方言层随后处理）。
   * modifier 省略时读当前 UI 状态；显式传 "" 表示不修饰。 */
  function compose(tag, modifier) {
    const raw = String(tag == null ? "" : tag).trim();
    if (!raw) return raw;
    const key = normalize(modifier === undefined ? current() : modifier);
    if (!key) return raw;
    const info = analyze(raw);
    if (info.colorIndex < 0) return raw;
    const parts = splitTag(raw);
    const tokens = parts.tokens;
    if (info.modifierIndex >= 0) {
      if (String(tokens[info.modifierIndex]).toLowerCase() === key) return raw;   // 已经是它，不叠加
      tokens[info.modifierIndex] = key;                                          // 换成新的修饰词
    } else {
      tokens.splice(info.colorIndex, 0, key);
    }
    return tokens.join(parts.separator);
  }

  function composeTags(tags, modifier) {
    return (tags || []).map((tag) => compose(tag, modifier));
  }

  /* ---------------------------------------------------------------- 界面 */

  const STYLE_ID = "colorModifierStyles";

  function installStyles() {
    if (typeof document === "undefined" || byId(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
.prompt-tag-search .field-title{flex-wrap:wrap}
.prompt-tag-search .field-title .color-modifier{display:inline-flex;align-items:center;gap:5px;margin-left:auto;align-self:center;color:var(--muted,#adb7cb);white-space:nowrap}
.color-modifier select{background:var(--bg,#10131c);border:1px solid var(--line,#343d53);color:inherit;border-radius:8px;padding:4px 6px;font-size:calc(var(--input-font-size,15px) - 4px)}
.color-modifier.active select{border-color:var(--accent,#9174ff)}
.color-modifier.active .color-modifier-label{color:var(--accent,#9174ff)}`;
    document.head.appendChild(style);
  }

  function options() {
    return '<option value="">无</option>'
      + MODIFIERS.map((item) => `<option value="${item.key}">${item.label}</option>`).join("");
  }

  function updateHint() {
    if (typeof document === "undefined") return;
    const wrap = byId("colorModifierWrap");
    const select = byId("colorModifier");
    const key = current();
    if (wrap) wrap.classList.toggle("active", Boolean(key));
    if (!select) return;
    if (key) {
      const sample = compose("blue_hair", key);
      select.title = `颜色修饰已开启：${describe(key)}。写入颜色标签时自动变成 ${sample}（再按模型方言转换）。`
        + "只影响颜色标签（如 blue_hair / blue_eyes），且不会重复叠加。";
    } else {
      select.title = "关闭时不改动任何标签；选择后，写入的颜色标签会带上该修饰词（如 blue_hair → dark_blue_hair）。";
    }
  }

  function installUi() {
    if (typeof document === "undefined") return;
    const title = document.querySelector(".prompt-tag-search .field-title");
    if (!title || byId("colorModifier")) return;
    installStyles();
    const wrap = document.createElement("span");
    wrap.id = "colorModifierWrap";
    wrap.className = "color-modifier";
    wrap.innerHTML = `<span class="color-modifier-label">颜色修饰</span>`
      + `<select id="colorModifier" aria-label="颜色修饰">${options()}</select>`;
    title.appendChild(wrap);
    const select = byId("colorModifier");
    select.value = current();
    select.addEventListener("change", () => set(select.value));
    updateHint();
  }

  const testApi = {
    STORAGE_KEY, MODIFIERS, COLOR_WORDS, COLORABLE_ATTRIBUTES, MODIFIER_KEYS,
    current, set, normalize, describe, analyze, isColorTag, compose, composeTags, splitTag,
    installStyles, installUi, updateHint,
  };
  window.EasyPanelColorModifier = testApi;
  if (typeof module !== "undefined" && module.exports) module.exports = testApi;

  if (typeof document === "undefined") return;   // node 测试环境没有 DOM

  function boot() {
    installUi();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
