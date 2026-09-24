/* 离线翻译（Argos Translate）：不联网、不需要 API Key 的中→英。
 *
 * 两个入口：
 *   ① 中文描述转换卡里的「🧩 离线翻译（Argos）」——把 #zhPrompt 整段翻译，
 *      结果形状与 Google 直译一致（写自然语言分区），复用面板的预览 + 应用按钮；
 *   ② 结构化提示词编译器里的「🧩 分区中文→英文」——只翻译分区里**含中文的片段**，
 *      英文标签原样保留，翻完写回字段（并给一个「撤销」按钮）。
 *
 * 引擎、语言包探测与子进程调用都在后端 easy_panel_app/integrations/argos.py，
 * 这里只负责收集文本、调用、写回。
 */
(function (global) {
  "use strict";

  const SECTION_FIELDS = Object.freeze([
    ["promptSubject", "人物与角色"],
    ["promptAppearance", "外貌"],
    ["promptExpression", "表情"],
    ["promptClothing", "服装与材质"],
    ["promptPose", "姿势"],
    ["promptComposition", "构图与镜头"],
    ["promptScene", "场景"],
    ["promptLighting", "光线"],
    ["promptStyle", "画风与上色"],
    ["promptNaturalLanguage", "自然语言"],
    ["prompt", "其他补充"],
  ]);
  const CJK_PATTERN = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;
  const SEGMENT_SPLIT = /[,，;；\n]+/;

  function text(value) {
    return String(value == null ? "" : value).trim();
  }

  function hasChinese(value) {
    return CJK_PATTERN.test(String(value == null ? "" : value));
  }

  /** 一段文本里含中文的片段（按逗号/分号/换行切分，去重保序）。 */
  function chineseSegments(value) {
    const seen = new Set();
    const result = [];
    for (const part of String(value == null ? "" : value).split(SEGMENT_SPLIT)) {
      const segment = part.trim();
      if (!segment || !hasChinese(segment)) continue;
      const key = segment.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(segment);
    }
    return result;
  }

  /** 用 {原文: 译文} 把含中文的片段替换掉，英文标签与分隔符保持原样。 */
  function replaceSegments(value, mapping) {
    const source = String(value == null ? "" : value);
    if (!source.trim()) return source;
    // 捕获组切分：偶数下标是片段，奇数下标是逗号/分号/换行。
    const parts = source.split(/([,，;；\n]+)/);
    return parts.map((part, index) => {
      if (index % 2 === 1) return part;
      const segment = part.trim();
      const replacement = segment && hasChinese(segment) && mapping[segment] ? mapping[segment] : segment;
      const leading = (/^\s*/.exec(part) || [""])[0];
      return leading + replacement;
    }).join("");
  }

  /** 收集所有分区里需要翻译的片段（按分区去重，返回批次与分区映射）。 */
  function collectFieldSegments(values) {
    const fields = [];
    const batch = [];
    const seen = new Set();
    for (const [id, label] of SECTION_FIELDS) {
      const raw = text(values && values[id]);
      if (!raw) continue;
      const segments = chineseSegments(raw);
      if (!segments.length) continue;
      fields.push({ id, label, raw, segments });
      for (const segment of segments) {
        const key = segment.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        batch.push(segment);
      }
    }
    return { fields, batch };
  }

  function statusText(status) {
    const info = status && typeof status === "object" ? status : {};
    if (info.available) {
      const pairs = Array.isArray(info.pairs) && info.pairs.length ? info.pairs.join("、") : "zh→en";
      return `离线可用：${pairs}（${info.home || "已检测"}）`;
    }
    return info.reason || "离线翻译不可用：请先配置 Argos 翻译器目录。";
  }

  function summarizeChanges(changedFields) {
    if (!changedFields.length) return "没有需要翻译的中文片段。";
    return "已翻译：" + changedFields.map((item) => `${item.label}(${item.count} 段)`).join("、");
  }

  /**
   * 面板自带的 101 条中英词表（panel.js 顶层的 chineseMap）。
   * 它的英文是照 Danbooru 习惯手写的（蓝发→blue hair），质量比通用机翻好，
   * 所以分段翻译时**先过词表，剩下的中文才交给 Argos**。
   */
  function chineseMapEntries() {
    try {
      const map = chineseMap; // eslint-disable-line no-undef
      return map && typeof map === "object" ? map : {};
    } catch (_) {
      return {};
    }
  }

  /** 最长优先、不重叠地把词表词换成英文；返回替换后的文本与命中数。 */
  function applyChineseMap(value) {
    const map = chineseMapEntries();
    const source = String(value == null ? "" : value);
    const matches = [];
    for (const key of Object.keys(map).sort((a, b) => b.length - a.length)) {
      let from = 0;
      for (;;) {
        const start = source.indexOf(key, from);
        if (start < 0) break;
        const end = start + key.length;
        if (!matches.some((range) => start < range.end && end > range.start)) {
          matches.push({ start, end, value: String(map[key]) });
        }
        from = end;
      }
    }
    if (!matches.length) return { text: source, hits: 0, hasChineseLeft: hasChinese(source) };
    matches.sort((left, right) => left.start - right.start);
    const parts = [];
    let cursor = 0;
    for (const match of matches) {
      parts.push(source.slice(cursor, match.start), match.value);
      cursor = match.end;
    }
    parts.push(source.slice(cursor));
    const joined = parts.join("").replace(/\s{2,}/g, " ").trim();
    return { text: joined, hits: matches.length, hasChineseLeft: hasChinese(joined) };
  }

  /** 机翻结果的标签化清理：去掉句尾句号、压空格、转小写（Danbooru 习惯）。 */
  function cleanTranslatedTag(value) {
    return String(value == null ? "" : value)
      .replace(/[.。;；、]+\s*$/g, "")
      .replace(/\s{2,}/g, " ")
      .trim()
      .toLowerCase();
  }

  /** 把一批中文片段拆成「词表直接搞定」与「需要 Argos」两拨。 */
  function splitSegmentsByDictionary(segments) {
    const resolved = {};
    const pending = [];
    for (const segment of segments) {
      const local = applyChineseMap(segment);
      if (local.hits && !local.hasChineseLeft) resolved[segment] = local.text;
      else pending.push(segment);
    }
    return { resolved, pending };
  }

  const testApi = {
    SECTION_FIELDS,
    hasChinese,
    chineseSegments,
    replaceSegments,
    collectFieldSegments,
    statusText,
    summarizeChanges,
    chineseMapEntries,
    applyChineseMap,
    cleanTranslatedTag,
    splitSegmentsByDictionary,
  };
  global.EasyPanelOfflineTranslate = testApi;
  if (typeof module !== "undefined" && module.exports) module.exports = testApi;
  if (typeof global.document === "undefined") return;

  const byId = (id) => global.document.getElementById(id);
  let undoSnapshot = null;

  function setHint(message, error) {
    for (const id of ["argosHint", "argosSectionHint"]) {
      const hint = byId(id);
      if (!hint) continue;
      hint.textContent = message;
      hint.classList.toggle("diagnostic-error", !!error);
    }
  }

  function setResult(message) {
    const result = byId("translationResult");
    if (result) result.textContent = message;
  }

  function setResultHtml(html) {
    const result = byId("translationResult");
    if (result) result.innerHTML = html;
  }

  async function postArgos(body) {
    const response = await fetch("/api/argos-translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (data.error) throw new Error(data.error);
    return data;
  }

  /** ① 整段中文描述 → 英文（与 Google 直译同一条应用路径）。 */
  async function translateOffline() {
    const source = text(byId("zhPrompt") && byId("zhPrompt").value);
    if (!source) {
      setResult("请先输入中文描述。");
      return false;
    }
    setResult("离线翻译中…（本地 Argos，第一次调用要加载语言包）");
    try {
      const data = await postArgos({ text: source });
      const positive = text(data.positive);
      try {
        // panel.js 顶层的 translated 变量：整段直译只写自然语言分区。
        translated = { positive, negative: "", promptMode: "flat", sections: { naturalLanguage: positive } };
      } catch (_) {
        /* 没有该全局变量时仍然把结果显示出来 */
      }
      const positiveNode = byId("translatedPositive");
      if (positiveNode) positiveNode.textContent = positive || "（未返回英文结果）";
      const negativeNode = byId("translatedNegative");
      if (negativeNode) negativeNode.textContent = "（离线直译会写入自然语言分区）";
      const preview = byId("translationPreview");
      if (preview) preview.style.display = "block";
      const extras = byId("translationExtras");
      if (extras) extras.style.display = "none";
      setResult("离线翻译完成（本地 Argos）：确认后点「加入正向提示词」写入自然语言分区。");
      return true;
    } catch (error) {
      setResult("离线翻译失败：" + (error && error.message ? error.message : error));
      return false;
    }
  }

  /** ② 分区里含中文的片段 → 英文，写回字段（保留英文标签）。 */
  async function translateSections() {
    const values = {};
    for (const [id] of SECTION_FIELDS) {
      const field = byId(id);
      if (field) values[id] = field.value;
    }
    const { fields, batch } = collectFieldSegments(values);
    if (!batch.length) {
      setHint("没有找到中文分区内容。", false);
      setResult("所有分区里都没有中文片段，无需翻译。");
      return false;
    }
    setHint(`离线翻译中…（${batch.length} 段）`, false);
    try {
      const { resolved, pending } = splitSegmentsByDictionary(batch);
      const mapping = { ...resolved };
      if (pending.length) {
        const data = await postArgos({ texts: pending });
        (data.texts || []).forEach((value, index) => {
          if (pending[index]) mapping[pending[index]] = cleanTranslatedTag(value);
        });
      }
      const dictCount = Object.keys(resolved).length;
      const snapshot = {};
      const changed = [];
      for (const field of fields) {
        const next = replaceSegments(field.raw, mapping);
        if (next === field.raw) continue;
        const node = byId(field.id);
        if (!node) continue;
        snapshot[field.id] = field.raw;
        node.value = next;
        changed.push({ field: field.id, label: field.label, count: field.segments.length });
      }
      if (global.promptEditorChanged) global.promptEditorChanged();
      if (!changed.length) {
        setHint("翻译完成，但内容没有变化。", false);
        setResult("离线翻译没有产生变化（可能语言包返回了原文）。");
        return false;
      }
      undoSnapshot = snapshot;
      const summary = summarizeChanges(changed);
      const detail = dictCount ? `${summary}（其中 ${dictCount} 段用本地词表，其余离线机翻）` : summary;
      setHint(detail, false);
      setResultHtml(`${detail}。<button class="secondary" type="button" onclick="easyPanelUndoOfflineTranslate()">撤销本次翻译</button>`);
      return true;
    } catch (error) {
      setHint("离线翻译失败：" + (error && error.message ? error.message : error), true);
      setResult("离线翻译失败：" + (error && error.message ? error.message : error));
      return false;
    }
  }

  function undoTranslation() {
    if (!undoSnapshot) {
      setHint("没有可撤销的翻译。", false);
      return false;
    }
    for (const [id, value] of Object.entries(undoSnapshot)) {
      const node = byId(id);
      if (node) node.value = value;
    }
    undoSnapshot = null;
    if (global.promptEditorChanged) global.promptEditorChanged();
    setHint("已撤销本次离线翻译。", false);
    setResult("已撤销本次离线翻译。");
    return true;
  }

  /** 面板加载时探测一次：按钮可用性 + 路径/语言对提示。 */
  async function probeStatus() {
    try {
      const data = await postArgos({ status: true });
      const info = data.status || {};
      const label = statusText(info);
      setHint(label, !info.available);
      const button = byId("argosSectionTranslate");
      if (button) button.disabled = !info.available;
      return info;
    } catch (error) {
      setHint("离线翻译探测失败：" + (error && error.message ? error.message : error), true);
      return { available: false };
    }
  }

  global.translateArgosOffline = translateOffline;
  global.translateArgosSections = translateSections;
  global.easyPanelUndoOfflineTranslate = undoTranslation;
  global.easyPanelArgosStatus = probeStatus;
  global.easyPanelArgosRefresh = probeStatus;

  if (global.document.readyState === "loading") {
    global.document.addEventListener("DOMContentLoaded", () => { probeStatus(); });
  } else {
    probeStatus();
  }
})(typeof window !== "undefined" ? window : globalThis);
