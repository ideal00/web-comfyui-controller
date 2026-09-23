/* 尺寸选择器：图片比例 → 长边滑块 → 推荐档位 → 当前尺寸信息。
 *
 * 设计（用户方案，2026-09-23）：
 *   - 「比例」是用户意图：数学严格比例。长边由滑块 / 输入框决定，短边按比例计算后**向下**对齐到 8 的倍数
 *     （扩散模型的潜空间要求，后端 resolution.alignment 默认也是 8；向下对齐不会越过数学比例值多占显存，
 *     例如 3:2 长边 1664 → 理论短边 1109.3 → 1664×1104）；
 *   - 「推荐档位」是模型推荐尺寸：保留 index.html 里现有档位（≈ 表示该档位像素是近似比例，
 *     例如 1216×832 实际 1.46:1、768×1344 实际 4:7），点一下直接跳过去；
 *     **点比例时优先落在该比例的第一个严格档位**（3:2 → 1536×1024、16:9 → 1280×720），
 *     没有严格档位才退回近似档位，完全没有档位才用滑块中间值；
 *   - `宽 × 高` 是「自定义精确尺寸」：允许临时非标准比例，再次拖动「长边」就回到当前选定比例；
 *   - 每个比例记忆上次使用的尺寸（localStorage easyPanelSizeByRatioV1），再点该比例回到上次档位；
 *   - 显示当前尺寸、MP 与预计显存负载（Anima / Krea 2 在 8GB 上口径更紧）。
 *
 * 真相源仍然是隐藏的原生 <select id="size">：payload()、effectiveOutputSize()、
 * model-advanced.js 的模型上限判断都继续读它，所以这里只负责把新 UI 的选择写回去，
 * 不引入第二套尺寸状态；不写回时原生下拉依然可用（脚本没加载时页面照常工作）。
 */
(function () {
  "use strict";

  const ALIGNMENT = 8;
  const MIN_SIDE = 512;
  const FALLBACK_MAX_SIDE = 2560;
  const FALLBACK_LONG_EDGE = 1216;
  const MEMORY_KEY = "easyPanelSizeByRatioV1";
  const CUSTOM_VALUE_RE = /^(\d{2,5})x(\d{2,5})$/;
  const RATIO_LABEL_RE = /[（(]\s*(\d+)\s*[:：]\s*(\d+)\s*[)）]/;
  const RATIO_EXACT_TOLERANCE = 0.012;

  /** 主比例表；数组顺序 = 按钮顺序（先方图 / 竖图，再横图）。 */
  const RATIO_ORDER = ["1:1", "2:3", "3:4", "9:16", "1:2", "9:21", "3:2", "4:3", "16:9", "2:1", "21:9"];
  const SIZE_RATIOS = {
    "1:1": { w: 1, h: 1 },
    "2:3": { w: 2, h: 3 },
    "3:4": { w: 3, h: 4 },
    "9:16": { w: 9, h: 16 },
    "1:2": { w: 1, h: 2 },
    "9:21": { w: 9, h: 21 },
    "3:2": { w: 3, h: 2 },
    "4:3": { w: 4, h: 3 },
    "16:9": { w: 16, h: 9 },
    "2:1": { w: 2, h: 1 },
    "21:9": { w: 21, h: 9 },
  };

  const PANEL_HTML = `
    <div class="size-picker-head"><span class="size-picker-title">图片比例</span><span id="sizeRatioValue" class="small">—</span></div>
    <div id="sizeRatioChips" class="size-ratio-chips" role="group" aria-label="图片比例"></div>
    <div class="size-picker-row"><span class="size-picker-label">尺寸</span><b id="sizeCurrentValue">—</b><span id="sizeCurrentMp" class="small"></span></div>
    <div id="sizeVramHint" class="small size-picker-vram"></div>
    <div class="size-picker-row size-picker-range"><span class="small">较小</span><input id="sizeLongEdgeRange" type="range" aria-label="长边像素"><span class="small">较大</span></div>
    <div class="size-picker-row"><span class="size-picker-label">长边</span><input id="sizeLongEdgeNumber" type="number" inputmode="numeric"><span class="small">px</span><span id="sizeLongEdgeHint" class="small"></span></div>
    <div class="size-picker-row size-picker-presets"><span class="size-picker-label">推荐档位</span><span id="sizePresetChips" class="size-preset-chips"></span></div>
    <div class="size-picker-row"><span class="size-picker-label">自定义精确尺寸</span><span class="size-picker-custom"><span class="small">宽</span><input id="sizeCustomWidth" type="number" inputmode="numeric"><span class="small">×</span><span class="small">高</span><input id="sizeCustomHeight" type="number" inputmode="numeric"></span><span class="small size-picker-custom-hint">修改宽高会暂时允许非标准比例，再次拖动「长边」后恢复当前选定比例</span></div>
    <div id="sizePickerNote" class="small size-picker-note"></div>`;

  const byId = (id) => (typeof document === "undefined" ? null : document.getElementById(id));

  /* ---------- 纯计算（node 测试直接调用，不依赖 DOM） ---------- */

  function alignTo(value, step) {
    const unit = Math.max(8, Math.round(Number(step) || ALIGNMENT));
    const number = Math.max(0, Math.round(Number(value) || 0));
    return Math.max(unit, Math.round(number / unit) * unit);
  }

  /** 向小的方向对齐（派生短边用：宁可少 1 档像素，也不越过数学比例值多占显存）。 */
  function alignDown(value, step) {
    const unit = Math.max(8, Math.round(Number(step) || ALIGNMENT));
    const number = Math.max(0, Math.round(Number(value) || 0));
    return Math.max(unit, Math.floor(number / unit) * unit);
  }

  function alignUp(value, step) {
    const unit = Math.max(8, Math.round(Number(step) || ALIGNMENT));
    const number = Math.max(0, Math.round(Number(value) || 0));
    return Math.max(unit, Math.ceil(number / unit) * unit);
  }

  function ratioInfo(key) {
    const item = SIZE_RATIOS[key];
    if (!item) return null;
    return {
      key,
      w: item.w,
      h: item.h,
      portrait: item.h >= item.w,
      /** 短边 / 长边 */
      factor: Math.min(item.w, item.h) / Math.max(item.w, item.h),
      ratio: item.w / item.h,
    };
  }

  /** 比例 + 长边 → 尺寸；短边按比例计算后向下对齐到 step 的倍数（1664×1104、1408×936）。 */
  function computeSize(key, longEdge, alignment) {
    const info = ratioInfo(key);
    if (!info) return null;
    const unit = Math.max(8, Math.round(Number(alignment) || ALIGNMENT));
    const long = alignTo(longEdge, unit);
    const exact = Math.round(long * info.factor * 1e6) / 1e6;
    const short = alignDown(exact, unit);
    return info.portrait ? { width: short, height: long } : { width: long, height: short };
  }

  /** 该比例下短边不触发后端 min 值钳制的最小长边（1:2 → 1024、9:21 → 1200）。 */
  function minLongEdge(key, alignment, minSide) {
    const info = ratioInfo(key);
    const unit = Math.max(8, Math.round(Number(alignment) || ALIGNMENT));
    const floor = Math.max(MIN_SIDE, Number(minSide) || MIN_SIDE);
    if (!info) return Math.max(unit, floor);
    let long = alignUp(Math.ceil(floor / info.factor), unit);
    for (let guard = 0; guard < 4; guard += 1) {
      const size = computeSize(key, long, unit);
      if (Math.min(size.width, size.height) >= floor) break;
      long += unit;
    }
    return long;
  }

  /** 档位标签里的比例，例如「标准竖图 832 × 1216（2:3）」→ "2:3"；只认主比例表。 */
  function ratioKeyFromLabel(label) {
    const match = RATIO_LABEL_RE.exec(String(label || ""));
    if (!match) return "";
    const key = `${Number(match[1])}:${Number(match[2])}`;
    return Object.prototype.hasOwnProperty.call(SIZE_RATIOS, key) ? key : "";
  }

  /** 像素 → 最接近的主比例（档位标签没写比例，或标签用了 4:7 这类近似写法时用）。 */
  function nearestRatioKey(width, height) {
    const w = Number(width) || 0;
    const h = Number(height) || 0;
    if (w <= 0 || h <= 0) return "";
    const target = Math.log(w / h);
    let best = "";
    let gap = Infinity;
    RATIO_ORDER.forEach((key) => {
      const info = SIZE_RATIOS[key];
      const delta = Math.abs(Math.log(info.w / info.h) - target);
      if (delta < gap - 1e-9) {
        best = key;
        gap = delta;
      }
    });
    return best;
  }

  function isExactForRatio(key, width, height) {
    const info = SIZE_RATIOS[key];
    const actual = (Number(width) || 0) / (Number(height) || 0);
    if (!info || !actual) return false;
    const target = info.w / info.h;
    return Math.abs(actual - target) / target <= RATIO_EXACT_TOLERANCE;
  }

  /**
   * 把原生 select 的档位按比例分组（顺序 = RATIO_ORDER）。
   * 档位标签写了主比例就听标签（用户意图），否则按像素找最接近的比例；
   * 自定义 option（dataset.sizeCustomOption）不参与分组。
   */
  function groupPresets(options) {
    const buckets = new Map(RATIO_ORDER.map((key) => [key, []]));
    (options || []).forEach((option) => {
      if (!option || option.custom) return;
      const value = String(option.value || "");
      const match = CUSTOM_VALUE_RE.exec(value);
      if (!match) return;
      const width = Number(match[1]);
      const height = Number(match[2]);
      const key = ratioKeyFromLabel(option.label) || nearestRatioKey(width, height);
      if (!buckets.has(key)) return;
      buckets.get(key).push({
        value,
        width,
        height,
        label: String(option.label || value),
        disabled: !!option.disabled,
        exact: isExactForRatio(key, width, height),
      });
    });
    return RATIO_ORDER.map((key) => ({
      key,
      presets: (buckets.get(key) || []).sort(
        (left, right) =>
          Math.max(left.width, left.height) - Math.max(right.width, right.height) || left.width - right.width,
      ),
    }));
  }

  /** 8GB / Anima / Krea 2 口径的显存负载估计（相对系数，不是显存物理预测）。 */
  function vramEstimate(width, height, family) {
    const megapixels = ((Number(width) || 0) * (Number(height) || 0)) / 1e6;
    const tight = family === "anima" || family === "krea2";
    const levels = tight
      ? { high: 1.5, more: 1.15, mid: 0.9 }
      : { high: 2.6, more: 1.9, mid: 1.2 };
    if (megapixels > levels.high) {
      return {
        level: "高",
        rank: 3,
        megapixels,
        note: tight
          ? "8GB 显存压力大：可能走 CPU 卸载（很慢）或直接显存不足，建议 1024px 以内。"
          : "建议一次只生成 1 张；显存不足时切精准模式或降到 1.5MP 以内。",
      };
    }
    if (megapixels > levels.more) {
      return { level: "较高", rank: 2, megapixels, note: "8GB 通常可出图，请一次生成 1 张。" };
    }
    if (megapixels > levels.mid) {
      return { level: "中", rank: 1, megapixels, note: "常规档位，8GB 可以稳定运行。" };
    }
    return { level: "低", rank: 0, megapixels, note: "显存压力很小，适合快速试稿。" };
  }

  /* ---------- 比例记忆（localStorage，node 用内存兜底） ---------- */

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

  function readMemory() {
    const raw = readStored(MEMORY_KEY);
    if (!raw) return {};
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_error) {
      return {};
    }
  }

  function writeMemory(map) {
    const clean = {};
    Object.keys(map || {}).forEach((key) => {
      const value = String(map[key] || "");
      if (SIZE_RATIOS[key] && CUSTOM_VALUE_RE.test(value)) clean[key] = value;
    });
    writeStored(MEMORY_KEY, JSON.stringify(clean));
    return clean;
  }

  /* ---------- 页面状态 ---------- */

  let elements = null;
  let groups = [];
  let memory = {};
  let activeRatio = "";
  let renderedRatio = "";
  let refreshQueued = false;
  let observer = null;

  function profile() {
    try {
      return (window.currentSamplingProfile && window.currentSamplingProfile()) || {};
    } catch (_error) {
      return {};
    }
  }

  function modelLimits() {
    const resolution = profile().resolution || {};
    const maxSide = Math.max(256, Math.round(Number(resolution.max) || FALLBACK_MAX_SIDE));
    const alignment = Math.max(8, Math.round(Number(resolution.alignment) || ALIGNMENT));
    const minSide = Math.max(MIN_SIDE, Math.round(Number(resolution.min) || MIN_SIDE));
    return { maxSide, alignment, minSide };
  }

  function presetGroup(key) {
    return groups.find((group) => group.key === key) || { key, presets: [] };
  }

  function optionList() {
    return Array.from(elements.select.options).map((option) => ({
      value: option.value,
      label: option.textContent,
      disabled: option.disabled,
      custom: !!(option.dataset && option.dataset.sizeCustomOption),
    }));
  }

  function refreshPresets() {
    if (!elements) return;
    groups = groupPresets(optionList());
    renderRatioChips();
    renderPresetChips();
    updateRangeBounds();
  }

  function renderRatioChips() {
    elements.chips.innerHTML = "";
    RATIO_ORDER.forEach((key) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "size-ratio-chip";
      button.dataset.ratio = key;
      button.textContent = key;
      button.setAttribute("aria-pressed", "false");
      const info = SIZE_RATIOS[key];
      button.title = `${key}（${info.h > info.w ? "竖版" : info.w > info.h ? "横版" : "方版"}）：拖动滑块时按严格比例计算尺寸`;
      button.addEventListener("click", () => selectRatio(key));
      elements.chips.appendChild(button);
    });
  }

  function renderPresetChips() {
    const wrap = elements.presets;
    renderedRatio = activeRatio;
    wrap.innerHTML = "";
    const presets = presetGroup(activeRatio).presets.filter((item) => !item.disabled);
    if (!presets.length) {
      wrap.innerHTML = '<span class="small">该比例暂无推荐档位，直接拖滑块即可。</span>';
      return;
    }
    presets.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "size-preset-chip" + (item.exact ? "" : " size-preset-approx");
      button.dataset.value = item.value;
      button.textContent = `${item.exact ? "" : "≈"}${item.width}×${item.height}`;
      button.title = item.exact
        ? `${item.label}（严格 ${activeRatio}）`
        : `${item.label}（≈ 近似比例：现有推荐档位为了 latent / 计算效率不严格等于 ${activeRatio}）`;
      button.addEventListener("click", () => selectPreset(item.value, activeRatio));
      wrap.appendChild(button);
    });
  }

  function updateRangeBounds() {
    const limits = modelLimits();
    const key = activeRatio || RATIO_ORDER[0];
    const min = minLongEdge(key, limits.alignment, limits.minSide);
    const max = Math.max(min + limits.alignment, limits.maxSide);
    elements.range.min = String(min);
    elements.range.max = String(max);
    elements.range.step = String(limits.alignment);
    elements.longInput.min = String(min);
    elements.longInput.max = String(max);
    elements.longInput.step = String(limits.alignment);
    elements.hint.textContent = `范围 ${min}–${max}px（当前模型上限），短边按比例向下对齐 ${limits.alignment} 的倍数`;
  }

  /** 实际像素比例文本（用于说明近似档位差多少）。 */
  function actualRatioText(width, height) {
    const value = Number(width) / Number(height);
    return Number.isFinite(value) && value > 0 ? `${value.toFixed(2)}:1` : "";
  }

  function noteText(value) {
    const preset = presetGroup(activeRatio).presets.find((item) => item.value === value);
    if (preset) {
      const info = ratioInfo(activeRatio);
      const drift = Math.abs(preset.width / preset.height - info.ratio) / info.ratio;
      const suffix = drift <= 0.001 ? "" : `（实际 ${actualRatioText(preset.width, preset.height)} ≈ ${activeRatio}）`;
      return `${preset.label}${suffix}；每个比例会记住上次用的尺寸。`;
    }
    const match = CUSTOM_VALUE_RE.exec(value);
    if (!match) return "";
    const exact = isExactForRatio(activeRatio, Number(match[1]), Number(match[2]));
    const suffix = exact ? `严格 ${activeRatio}` : `非标准比例，≈ ${activeRatio}`;
    return `自定义精确尺寸 ${match[1]} × ${match[2]}（${suffix}）：拖动「长边」会恢复当前比例并对齐 8 的倍数；自定义值不写入比例记忆。`;
  }

  function render() {
    if (!elements) return;
    const value = String(elements.select.value || "");
    const match = CUSTOM_VALUE_RE.exec(value);
    if (!match) return;
    const width = Number(match[1]);
    const height = Number(match[2]);
    const longEdge = Math.max(width, height);
    const estimate = vramEstimate(width, height, profile().family || "");
    elements.ratioValue.textContent = activeRatio || "—";
    elements.sizeValue.textContent = `${width} × ${height}`;
    elements.mp.textContent = `${estimate.megapixels.toFixed(2)} MP`;
    let hiresNote = "";
    try {
      const effective = window.effectiveOutputSize && window.effectiveOutputSize();
      if (effective && effective.scale > 1 && effective.megapixels > estimate.megapixels + 1e-6) {
        hiresNote = `；二采后约 ${effective.width} × ${effective.height}（${effective.megapixels.toFixed(2)} MP）`;
      }
    } catch (_error) {
      hiresNote = "";
    }
    elements.vram.textContent = `预计显存负载：${estimate.level}${hiresNote}`;
    elements.vram.title = estimate.note || "";
    elements.range.value = String(longEdge);
    elements.longInput.value = String(longEdge);
    elements.widthInput.value = String(width);
    elements.heightInput.value = String(height);
    elements.note.textContent = noteText(value);
    Array.from(elements.chips.querySelectorAll(".size-ratio-chip")).forEach((chip) => {
      const active = chip.dataset.ratio === activeRatio;
      chip.classList.toggle("active", active);
      chip.setAttribute("aria-pressed", active ? "true" : "false");
    });
    Array.from(elements.presets.querySelectorAll(".size-preset-chip")).forEach((chip) => {
      chip.classList.toggle("active", chip.dataset.value === value);
    });
  }

  function refresh(force) {
    refreshPresets();
    syncFromSelect(force === true);
  }

  function queueRefresh() {
    if (refreshQueued || !elements) return;
    refreshQueued = true;
    const run = () => {
      refreshQueued = false;
      refresh(true);
    };
    if (typeof window.setTimeout === "function") window.setTimeout(run, 0);
    else run();
  }

  /** 跟随原生 select（其它脚本也会改它：模型上限、读图还原、快照恢复）。 */
  function syncFromSelect(rebuild) {
    if (!elements) return;
    const value = String(elements.select.value || "");
    const match = CUSTOM_VALUE_RE.exec(value);
    if (!match) return;
    const width = Number(match[1]);
    const height = Number(match[2]);
    const option = elements.select.selectedOptions && elements.select.selectedOptions[0];
    const label = option ? option.textContent : "";
    const ratio = ratioKeyFromLabel(label) || nearestRatioKey(width, height) || activeRatio;
    activeRatio = ratio || activeRatio;
    // 比例变了就要重建档位条（applyValue 会先把 activeRatio 写新，所以比的是“已渲染过的比例”）
    if (rebuild || activeRatio !== renderedRatio) refreshPresets();
    render();
  }

  /* ---------- 写回原生 select ---------- */

  function createCustomOption(value) {
    const option = document.createElement("option");
    const match = CUSTOM_VALUE_RE.exec(value);
    option.value = value;
    option.textContent = `自定义 ${match[1]} × ${match[2]}`;
    option.dataset.sizeCustomOption = "1";
    elements.select.appendChild(option);
    return option;
  }

  function removeCustomOptions(keep) {
    Array.from(elements.select.options).forEach((option) => {
      if (!(option.dataset && option.dataset.sizeCustomOption)) return;
      if (keep && option.value === keep) return;
      option.remove();
    });
  }

  function setSelectValue(value) {
    const presets = Array.from(elements.select.options).filter(
      (option) => !(option.dataset && option.dataset.sizeCustomOption),
    );
    let option = presets.find((item) => item.value === value);
    if (option) {
      removeCustomOptions();
    } else {
      const existing = Array.from(elements.select.options).find(
        (item) => item.value === value && item.dataset && item.dataset.sizeCustomOption,
      );
      option = existing || createCustomOption(value);
      removeCustomOptions(value);
    }
    if (elements.select.value !== value) elements.select.value = value;
    return option;
  }

  /** 统一入口：写回 #size → 更新记忆 → 通知 updateSizeInfo()（会刷新 sizeInfo 与本面板）。 */
  function applyValue(value, options) {
    if (!elements) return null;
    const match = CUSTOM_VALUE_RE.exec(String(value || ""));
    if (!match) return null;
    const limits = modelLimits();
    let width = Number(match[1]);
    let height = Number(match[2]);
    let clamped = false;
    if (Math.max(width, height) > limits.maxSide) {
      const scale = limits.maxSide / Math.max(width, height);
      width = alignTo(width * scale, limits.alignment);
      height = alignTo(height * scale, limits.alignment);
      clamped = true;
    }
    const target = `${width}x${height}`;
    const option = setSelectValue(target);
    const ratio =
      (options && options.ratio) ||
      ratioKeyFromLabel(option && option.textContent) ||
      nearestRatioKey(width, height) ||
      activeRatio;
    if (ratio) activeRatio = ratio;
    if (options && options.remember && ratio) {
      memory[ratio] = target;
      memory = writeMemory(memory);
    }
    if (typeof window.updateSizeInfo === "function") window.updateSizeInfo();
    else render();
    return { width, height, value: target, ratio, remember: !!(options && options.remember), clamped };
  }

  function applyLongEdge(rawValue, options) {
    if (!elements) return null;
    const limits = modelLimits();
    const key = activeRatio || RATIO_ORDER[0];
    const min = minLongEdge(key, limits.alignment, limits.minSide);
    const max = Math.max(min, limits.maxSide);
    const long = Math.max(min, Math.min(max, alignTo(rawValue, limits.alignment)));
    const size = computeSize(key, long, limits.alignment);
    if (!size) return null;
    return applyValue(`${size.width}x${size.height}`, { ratio: key, remember: !!(options && options.remember) });
  }

  function applyCustomFields() {
    if (!elements) return null;
    const limits = modelLimits();
    const width = alignTo(elements.widthInput.value || FALLBACK_LONG_EDGE, limits.alignment);
    const height = alignTo(elements.heightInput.value || FALLBACK_LONG_EDGE, limits.alignment);
    return applyValue(`${width}x${height}`, { ratio: nearestRatioKey(width, height), remember: false });
  }

  function selectPreset(value, key) {
    return applyValue(value, { ratio: key, remember: true });
  }

  /**
   * 点比例时的默认档位：**优先第一个严格比例档位**（避免“比例写着 3:2、尺寸却是 1216×832”的错位），
   * 没有严格档位才退回第一个近似档位，返回 null 表示该比例没有可用档位。
   */
  function pickDefaultPreset(presets) {
    const usable = (presets || []).filter((item) => item && !item.disabled);
    return usable.find((item) => item.exact) || usable[0] || null;
  }

  /** 点比例：优先回到该比例上次用的尺寸，其次该比例第一个严格档位（再退近似档），最后用滑块中间值。 */
  function selectRatio(key) {
    if (!elements) return null;
    const remembered = CUSTOM_VALUE_RE.test(String(memory[key] || "")) ? memory[key] : "";
    if (remembered) return applyValue(remembered, { ratio: key, remember: false });
    const preset = pickDefaultPreset(presetGroup(key).presets);
    if (preset) return applyValue(preset.value, { ratio: key, remember: false });
    const limits = modelLimits();
    const min = minLongEdge(key, limits.alignment, limits.minSide);
    const middle = alignTo((min + Math.max(min, limits.maxSide)) / 2, limits.alignment);
    return applyLongEdge(middle, { remember: false });
  }

  /* ---------- 安装 ---------- */

  function bindEvents() {
    elements.range.addEventListener("input", () => applyLongEdge(elements.range.value, { remember: false }));
    elements.range.addEventListener("change", () => applyLongEdge(elements.range.value, { remember: true }));
    elements.longInput.addEventListener("change", () => applyLongEdge(elements.longInput.value, { remember: true }));
    elements.widthInput.addEventListener("change", () => applyCustomFields());
    elements.heightInput.addEventListener("change", () => applyCustomFields());
    elements.select.addEventListener("change", () => refresh(true));
  }

  function observeSelect() {
    if (observer || typeof MutationObserver === "undefined") return;
    observer = new MutationObserver(() => queueRefresh());
    observer.observe(elements.select, { childList: true, attributes: true, subtree: true });
  }

  function wrapGlobal(name, after) {
    const original = window[name];
    if (typeof original !== "function" || original.__sizeSelectorWrapped) return false;
    const wrapped = function () {
      const result = original.apply(this, arguments);
      try {
        after();
      } catch (_error) {
        /* 尺寸面板只是显示层，不能影响主流程 */
      }
      return result;
    };
    wrapped.__sizeSelectorWrapped = true;
    window[name] = wrapped;
    return true;
  }

  function installUi() {
    if (elements) return true;
    const select = byId("size");
    if (!select) return false;
    if (byId("sizeRatioPanel")) return true;
    const host = select.parentElement || select.parentNode;
    const title = select.previousElementSibling;
    const panel = document.createElement("div");
    panel.id = "sizeRatioPanel";
    panel.className = "size-picker";
    panel.innerHTML = PANEL_HTML;
    select.style.display = "none";
    if (title && title.classList && title.classList.contains("field-title")) title.style.display = "none";
    const grid = host && host.parentElement;
    if (grid && grid.classList && grid.classList.contains("three")) host.classList.add("size-field-wide");
    if (host) host.insertBefore(panel, select);
    else document.body.appendChild(panel);
    elements = {
      select,
      panel,
      chips: byId("sizeRatioChips"),
      ratioValue: byId("sizeRatioValue"),
      sizeValue: byId("sizeCurrentValue"),
      mp: byId("sizeCurrentMp"),
      vram: byId("sizeVramHint"),
      range: byId("sizeLongEdgeRange"),
      longInput: byId("sizeLongEdgeNumber"),
      hint: byId("sizeLongEdgeHint"),
      presets: byId("sizePresetChips"),
      widthInput: byId("sizeCustomWidth"),
      heightInput: byId("sizeCustomHeight"),
      note: byId("sizePickerNote"),
    };
    memory = readMemory();
    syncFromSelect(true);
    bindEvents();
    return true;
  }

  function boot() {
    if (!installUi()) return;
    wrapGlobal("updateSizeInfo", () => syncFromSelect(false));
    wrapGlobal("modelChanged", () => queueRefresh());
    wrapGlobal("modelAdvancedChanged", () => queueRefresh());
    observeSelect();
  }

  const testApi = {
    ALIGNMENT,
    MIN_SIDE,
    FALLBACK_MAX_SIDE,
    MEMORY_KEY,
    RATIO_ORDER,
    SIZE_RATIOS,
    alignTo,
    alignDown,
    alignUp,
    ratioInfo,
    computeSize,
    minLongEdge,
    ratioKeyFromLabel,
    nearestRatioKey,
    isExactForRatio,
    groupPresets,
    vramEstimate,
    pickDefaultPreset,
    readMemory,
    writeMemory,
    /** 供其它脚本（读图还原 / 快照恢复 / 控制台）按精确像素设置尺寸。 */
    applySize: (width, height, options) => applyValue(`${Number(width) || 0}x${Number(height) || 0}`, options),
    applyLongEdge: (longEdge, options) => applyLongEdge(longEdge, options),
    selectRatio: (key) => selectRatio(key),
    selectPreset: (value, key) => selectPreset(value, key || nearestRatioKey(...String(value).split("x").map(Number))),
    activeRatio: () => activeRatio,
    presets: () => groups.map((group) => ({ key: group.key, presets: group.presets.slice() })),
    refresh: () => refresh(true),
    install: () => installUi(),
  };

  window.EasyPanelSizeSelector = testApi;
  if (typeof module !== "undefined" && module.exports) module.exports = testApi;

  if (typeof document === "undefined") return; // node 测试环境没有 DOM

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
