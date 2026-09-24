/* 离线翻译（Argos Translate）：不联网、不需要 API Key 的中→英。
 *
 * 两个入口：
 *   ① 中文描述转换卡里的「🧩 离线翻译（Argos）」——把 #zhPrompt 整段翻译，
 *      结果形状与 Google 直译一致（写自然语言分区），复用面板的预览 + 应用按钮；
 *   ② 每个提示词框标题行上的「翻译」（与「清空 / 粘贴」同排，共 12 个）——只翻
 *      这个框里**含中文的片段**，英文标签原样保留；再点一次撤销，状态就写在按钮后面。
 *
 * 引擎、语言包探测与子进程调用都在后端 easy_panel_app/integrations/argos.py ，
 * 这里只负责收集文本、分批请求、写回。
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

  //: 每个带「清空 / 粘贴」按钮的分区也带一个「翻译」按钮（跟 index.html 里的按钮一一对应）。
  const FIELD_LABELS = Object.freeze({
    promptSubject: "人物与角色",
    promptAppearance: "外貌",
    promptExpression: "表情",
    promptClothing: "服装与材质",
    promptPose: "姿势",
    promptComposition: "构图与镜头",
    promptScene: "场景",
    promptLighting: "光线",
    promptStyle: "画风与上色",
    promptNaturalLanguage: "自然语言",
    prompt: "其他补充",
    negative: "额外负面词",
  });

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

  const BATCH_LIMIT = 32;   // 跟后端 MAX_TEXTS 对齐；超出的部分前端自己分批
  let argosPoster = null;   // 单测/嵌入场景可以换掉真正的 fetch

  function postArgos(body) {
    if (argosPoster) return argosPoster(body);
    return fetch("/api/argos-translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(async (response) => {
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      return data;
    });
  }

  /**
   * 批量翻译，**自动分批**：界面不该让用户感知后端 32 段的上限。
   * 返回与输入等长的数组；onProgress 用来提示「第 i/n 批」。
   */
  async function requestTranslations(items, options) {
    const opts = options && typeof options === "object" ? options : {};
    const texts = Array.isArray(items) ? items : [];
    if (!texts.length) return [];
    const chunks = [];
    for (let start = 0; start < texts.length; start += BATCH_LIMIT) {
      chunks.push(texts.slice(start, start + BATCH_LIMIT));
    }
    const out = [];
    for (let index = 0; index < chunks.length; index += 1) {
      if (typeof opts.onProgress === "function") opts.onProgress(index + 1, chunks.length);
      const body = { texts: chunks[index] };
      if (opts.from) body.from = opts.from;
      if (opts.to) body.to = opts.to;
      const data = await postArgos(body);
      const part = Array.isArray(data.texts) ? data.texts : [];
      if (part.length !== chunks[index].length) {
        throw new Error("离线翻译返回的段数与请求不一致。");
      }
      out.push(...part.map((value) => String(value == null ? "" : value)));
    }
    return out;
  }

  const testApi = {
    SECTION_FIELDS,
    FIELD_LABELS,
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
    BATCH_LIMIT,
    requestTranslations,
    setArgosPoster: (fn) => { argosPoster = typeof fn === "function" ? fn : null; },
  };
  global.EasyPanelOfflineTranslate = testApi;
  if (typeof module !== "undefined" && module.exports) module.exports = testApi;
  if (typeof global.document === "undefined") return;

  const byId = (id) => global.document.getElementById(id);
  let undoSnapshot = null;
  let writingField = "";

  function setHint(message, error) {
    const hint = byId("argosHint");
    if (hint) {
      hint.textContent = message;
      hint.classList.toggle("diagnostic-error", !!error);
    }
  }

  /** 每个框自己的状态位（就在「清空 / 粘贴 / 翻译」后面）。 */
  function setFieldHint(fieldId, message, error) {
    const hint = global.document.querySelector(`[data-translate-status="${fieldId}"]`);
    if (!hint) return;
    hint.textContent = message;
    hint.classList.toggle("diagnostic-error", !!error);
  }

  function setResult(message) {
    const result = byId("translationResult");
    if (result) result.textContent = message;
  }

  function setResultHtml(html) {
    const result = byId("translationResult");
    if (result) result.innerHTML = html;
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
        const translated = await requestTranslations(pending, {
          onProgress: (done, total) => setHint(`离线翻译中… 第 ${done}/${total} 批（共 ${batch.length} 段）`, false),
        });
        translated.forEach((value, index) => {
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
        invalidateFieldUndo(field.id);
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

  /** 每个框自己的「翻译」按钮：只翻这个框里的中文片段，英文标签保留。 */
  const fieldUndo = {};

  /** 过期快照失效：清空 / 粘贴 / 手动改 / 换预设之后，再点「翻译」应该重新翻而不是撤销。 */
  function invalidateFieldUndo(fieldId) {
    if (!fieldId) {
      for (const key of Object.keys(fieldUndo)) delete fieldUndo[key];
      return;
    }
    delete fieldUndo[fieldId];
  }

  async function translateField(fieldId) {
    const field = byId(fieldId);
    if (!field) return false;
    const button = global.document.querySelector(`[data-translate-field="${fieldId}"]`);
    const current = String(field.value == null ? "" : field.value);
    // 再点一次 = 撤销（仅当内容还是上次翻译的结果；手动改过就重新翻，不会覆盖你的修改）
    const previous = fieldUndo[fieldId];
    if (previous && current === previous.translated) {
      field.value = previous.original;
      delete fieldUndo[fieldId];
      writingField = fieldId;
      try {
        if (global.promptEditorChanged) global.promptEditorChanged();
      } finally {
        writingField = "";
      }
      setFieldHint(fieldId, `已撤销，回到 ${previous.original.split(",").length} 个词条的原文`, false);
      return true;
    }
    if (!current.trim()) {
      setFieldHint(fieldId, "框是空的：先填入中文或点「粘贴」", false);
      return false;
    }
    const segments = chineseSegments(current);
    if (!segments.length) {
      setFieldHint(fieldId, "这个框里没有中文片段", false);
      return false;
    }
    const { resolved, pending } = splitSegmentsByDictionary(segments);
    const mapping = { ...resolved };
    if (button) {
      button.disabled = true;
      button.textContent = "翻译中";
    }
    setFieldHint(fieldId, `翻译中…（${segments.length} 段）`, false);
    try {
      if (pending.length) {
        const translated = await requestTranslations(pending, {
          onProgress: (done, total) => setFieldHint(
            fieldId, `翻译中… 第 ${done}/${total} 批（共 ${segments.length} 段）`, false),
        });
        translated.forEach((value, index) => {
          if (pending[index]) mapping[pending[index]] = cleanTranslatedTag(value);
        });
      }
      const next = replaceSegments(current, mapping);
      if (next === current) {
        setFieldHint(fieldId, "翻译后没有变化", false);
        return false;
      }
      writingField = fieldId;
      try {
        field.value = next;
        if (global.promptEditorChanged) global.promptEditorChanged();
      } finally {
        writingField = "";
      }
      fieldUndo[fieldId] = { original: current, translated: next };
      const dictCount = Object.keys(resolved).length;
      setFieldHint(fieldId, `已翻译 ${segments.length} 段（词表 ${dictCount}）· 再点可撤销`, false);
      return true;
    } catch (error) {
      setFieldHint(fieldId, "翻译失败：" + (error && error.message ? error.message : error), true);
      return false;
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "翻译";
      }
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
      for (const button of global.document.querySelectorAll("[data-translate-field]")) {
        button.disabled = !info.available;
        button.title = info.available
          ? "把本框中文翻成英文；再点可撤销上一次翻译，手动修改后会重新翻译当前内容"
          : "离线翻译不可用：" + label;
      }
      return info;
    } catch (error) {
      setHint("离线翻译探测失败：" + (error && error.message ? error.message : error), true);
      return { available: false };
    }
  }

  global.translateArgosOffline = translateOffline;
  global.translateArgosSections = translateSections;
  global.translateArgosField = translateField;
  global.easyPanelUndoOfflineTranslate = undoTranslation;
  global.easyPanelArgosStatus = probeStatus;
  global.easyPanelArgosRefresh = probeStatus;
  // 解析词条（prompt-explain.js）复用同一套分批请求，不再自己拼请求。
  global.easyPanelArgosBatch = (texts, options) => requestTranslations(texts, options);
  global.easyPanelInvalidateFieldUndo = invalidateFieldUndo;

  /**
   * 手动改框 / 清空 / 粘贴 / 换预设之后，之前的撤销快照就该作废，
   * 否则再点「翻译」会回到一个用户已经不认得的旧文本。
   */
  function installUndoInvalidation() {
    const ids = new Set(Object.keys(FIELD_LABELS));
    global.document.addEventListener("input", (event) => {
      const target = event.target;
      if (!target || !target.id || !ids.has(target.id)) return;
      if (writingField === target.id) return;   // 自己写回去的那次不算手改
      delete fieldUndo[target.id];
      setFieldHint(target.id, "", false);
    }, true);
    const wrap = (name, clear) => {
      const original = global[name];
      if (typeof original !== "function" || original.__argosWrapped) return;
      const wrapped = function (...args) {
        const result = original.apply(this, args);
        clear(args[0]);
        return result;
      };
      wrapped.__argosWrapped = true;
      global[name] = wrapped;
    };
    // 清空 / 粘贴：作废那个框的快照并清空它自己的状态位；换预设 / 恢复面板：全部作废。
    const clearField = (fieldId) => {
      if (typeof fieldId !== "string" || !ids.has(fieldId)) return;
      delete fieldUndo[fieldId];
      setFieldHint(fieldId, "", false);
    };
    wrap("clearPromptSection", clearField);
    wrap("pastePromptSection", clearField);
    wrap("applyPromptPreset", () => invalidateFieldUndo());
    wrap("resetPrompt", () => invalidateFieldUndo());
    wrap("restorePayloadToPanel", () => invalidateFieldUndo());
  }

  installUndoInvalidation();

  if (global.document.readyState === "loading") {
    global.document.addEventListener("DOMContentLoaded", () => { probeStatus(); });
  } else {
    probeStatus();
  }
})(typeof window !== "undefined" ? window : globalThis);
