/* 可视化词条库（Visual Tag Library V1）
 *
 * 双源统一卡片：
 *   本地精选（G:\QK download，1868 条中文词条 + 精选参考图，离线可用）
 *   Danbooru 云端（只读、每页 20 张、限速 + 缓存 + 失败降级）
 *
 * 所有插入都经过 Prompt 方言层（window.EasyPanelDialect）：
 * 数据库保存 Danbooru 原形，写入时按当前模型方言转换；LoRA 触发词永不转换。
 */
(function () {
  "use strict";

  const LOCAL_API = "/api/visual-tags";
  const IMAGE_API = "/api/visual-tags/image";
  const CLOUD_API = "/api/danbooru/posts";
  const STORAGE_KEY = "easyPanelVisualTagLibraryV1";
  const LOCAL_LIMIT = 48;
  const CLOUD_LIMIT = 20;
  const RATINGS = { general: "General 全年龄", sensitive: "Sensitive 敏感", questionable: "Questionable 暗示", explicit: "Explicit 明确" };
  const SORTS = { newest: "最新", oldest: "最旧" };
  const RATING_BADGE = { g: "G", s: "S", q: "Q", e: "E" };
  const GROUP_LABELS = { general: "通用", character: "角色", copyright: "系列", artist: "画师" };

  const byId = (id) => document.getElementById(id);
  const esc = window.esc || ((value) => String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"));
  const dialect = () => window.EasyPanelDialect;

  const state = {
    source: "local",
    query: "",
    category: "",
    rating: "general",
    sort: "newest",
    page: 1,
    results: [],
    selected: [],
    expanded: {},
    meta: {},
    notice: "",
    error: "",
    loading: false,
    localTotal: 0,
    categories: [],
    recent: [],
  };

  /* ------------------------------------------------------------- 工具 */

  function formatTag(tag, kind) {
    const layer = dialect();
    if (layer && typeof layer.formatTag === "function") return layer.formatTag(tag, { kind: kind });
    return String(tag || "");
  }

  function dialectLabel() {
    const layer = dialect();
    if (layer && typeof layer.describe === "function") return layer.describe();
    return "Danbooru 原样";
  }

  function targetSection() {
    const select = byId("tagTarget");
    return (select && select.value) || "manual";
  }

  function targetLabel(section) {
    const select = byId("tagTarget");
    const option = select && [...select.options].find((item) => item.value === section);
    return option ? option.textContent.replace(/^写入：/, "") : section;
  }

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        source: state.source, category: state.category, rating: state.rating, sort: state.sort,
      }));
    } catch (_error) { /* 忽略隐私模式写入失败 */ }
  }

  function loadState() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      if (saved.source === "local" || saved.source === "cloud") state.source = saved.source;
      if (typeof saved.category === "string") state.category = saved.category;
      if (RATINGS[saved.rating]) state.rating = saved.rating;
      if (SORTS[saved.sort]) state.sort = saved.sort;
    } catch (_error) { /* 首次使用没有存档 */ }
  }

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.focus();
    area.select();
    try {
      return document.execCommand("copy");
    } finally {
      area.remove();
    }
  }

  function setNotice(message, kind) {
    state.notice = message || "";
    state.error = kind === "error" ? message || "" : "";
    renderStatus();
  }

  /* ------------------------------------------------------------- 数据 */

  async function loadLocal() {
    state.loading = true;
    renderAll();
    try {
      const layer = dialect();
      const params = new URLSearchParams({
        q: state.query, limit: String(LOCAL_LIMIT), category: state.category,
        family: layer ? layer.family() : "", dialect: layer ? layer.currentDialect() : "",
      });
      const response = await fetch(`${LOCAL_API}?${params.toString()}`);
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      state.results = data.results || [];
      state.meta = data;
      state.categories = data.categories || [];
      state.localTotal = data.total || 0;
    } catch (error) {
      state.results = [];
      state.error = `本地词条库读取失败：${error.message}`;
    } finally {
      state.loading = false;
      renderAll();
    }
  }

  async function loadCloud() {
    if (!state.query.trim()) {
      state.results = [];
      setNotice("云端查询需要英文 tag；输入中文时会先自动解析（如“高跟鞋” → high_heels）。");
      return;
    }
    state.loading = true;
    renderAll();
    try {
      const params = new URLSearchParams({
        tags: state.query, limit: String(CLOUD_LIMIT), page: String(state.page),
        rating: state.rating, sort: state.sort,
      });
      const response = await fetch(`${CLOUD_API}?${params.toString()}`);
      const data = await response.json();
      state.results = data.results || [];
      state.meta = data;
      if (data.error) {
        state.error = data.error;
        state.notice = "";
      } else {
        state.error = "";
        const notes = [];
        if (data.resolved_tags) notes.push(`已把“${data.original_query}”解析为 ${data.resolved_tags}`);
        if (data.cached) notes.push("本次来自本地缓存");
        if (data.local_matches) notes.push(`本地精选库也有 ${data.local_matches} 条匹配`);
        state.notice = notes.join(" · ");
      }
    } catch (error) {
      state.results = [];
      state.error = `云端查询失败：${error.message}`;
    } finally {
      state.loading = false;
      renderAll();
    }
  }

  async function reload() {
    if (state.source === "cloud") return loadCloud();
    return loadLocal();
  }

  async function loadStats() {
    try {
      const data = await (await fetch(`${LOCAL_API}?stats=1`)).json();
      state.localTotal = data.entries || 0;
      state.categories = data.categories || [];
      state.meta = Object.assign({}, state.meta, { stats: data });
      renderStatus();
    } catch (_error) { /* 统计失败不影响使用 */ }
  }

  async function rebuildIndex() {
    setNotice("正在重建本地索引…");
    try {
      const response = await fetch(`${LOCAL_API}/rebuild`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      state.meta = Object.assign({}, state.meta, { stats: data });
      state.localTotal = data.entries || 0;
      state.categories = data.categories || [];
      await loadLocal();
      setNotice(`索引已重建：${data.entries} 条词条 / ${(data.categories || []).length} 个分类（${data.generated_at}）。`);
    } catch (error) {
      setNotice(`重建索引失败：${error.message}`, "error");
    }
  }

  /* ------------------------------------------------------------- 选择 */

  function isSelected(tag) {
    return state.selected.some((item) => item.tag === tag);
  }

  function toggleSelect(tag, kind) {
    if (!tag) return;
    if (isSelected(tag)) {
      state.selected = state.selected.filter((item) => item.tag !== tag);
    } else {
      state.selected.push({ tag: tag, kind: kind || "general" });
    }
    renderGrid();
    renderFooter();
  }

  function addTag(tag, kind) {
    const formatted = formatTag(tag, kind);
    if (typeof window.appendEnglish === "function") window.appendEnglish(formatted, targetSection());
    const changed = formatted !== tag;
    setNotice(`${changed ? `${tag} → ${formatted}（按 ${dialectLabel()} 转换）` : `${formatted}`} 已写入「${targetLabel(targetSection())}」。`);
  }

  function insertSelected(mode) {
    if (!state.selected.length) {
      setNotice("先点选卡片，或直接点卡片上的「＋」。");
      return;
    }
    if (mode === "hires") {
      const field = byId("hiresPositive");
      if (!field) {
        setNotice("当前面板没有二采输入框；请先在生成设置里开启高清二采。", "error");
        return;
      }
      const formatted = state.selected.map((item) => formatTag(item.tag, item.kind));
      const existing = String(field.value || "").trim();
      field.value = existing ? `${existing}, ${formatted.join(", ")}` : formatted.join(", ");
      field.dispatchEvent(new Event("input", { bubbles: true }));
      if (typeof window.hiresPromptInputChanged === "function") window.hiresPromptInputChanged();
      setNotice(`已加入二采补充词：${formatted.join(", ")}`);
      return;
    }
    state.selected.forEach((item) => addTag(item.tag, item.kind));
    const summary = state.selected.map((item) => formatTag(item.tag, item.kind)).join(", ");
    state.selected = [];
    renderGrid();
    renderFooter();
    setNotice(`已写入「${targetLabel(targetSection())}」：${summary}`);
    scrollToEdit();
  }

  async function copySelected() {
    if (!state.selected.length) {
      setNotice("先点选卡片再复制。");
      return;
    }
    const text = state.selected.map((item) => formatTag(item.tag, item.kind)).join(", ");
    try {
      await copyText(text);
      setNotice(`已复制：${text}`);
    } catch (error) {
      setNotice(`复制失败：${error.message}`, "error");
    }
  }

  function clearSelection() {
    state.selected = [];
    renderGrid();
    renderFooter();
  }

  /* ------------------------------------------------------------- 渲染 */

  function thumbUrl(entry) {
    return `${IMAGE_API}?id=${encodeURIComponent(entry.id)}&size=thumb&px=320`;
  }

  function localCard(entry) {
    const selected = isSelected(entry.tag);
    const formatted = entry.formatted || formatTag(entry.tag, entry.kind);
    const converted = formatted !== entry.tag;
    const unmatched = entry.image_status && entry.image_status !== "ready";
    return `<article class="vtl-card${selected ? " selected" : ""}" data-tag="${esc(entry.tag)}" data-kind="${esc(entry.kind || "general")}">
      <div class="vtl-thumb">
        <img loading="lazy" src="${thumbUrl(entry)}" alt="${esc(entry.tag)}" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'vtl-nothumb',textContent:'无预览图'}))">
        ${unmatched ? '<span class="vtl-badge warn">参考图未匹配</span>' : ""}
        <button type="button" class="vtl-full" data-full="${IMAGE_API}?id=${encodeURIComponent(entry.id)}&size=full" title="查看原图">⤢</button>
      </div>
      <div class="vtl-body">
        <div class="vtl-tag">${esc(entry.tag)}</div>
        <div class="vtl-zh">${esc(entry.name_zh || "")}${entry.group ? `<span class="vtl-group">${esc(entry.group)}</span>` : ""}</div>
        ${entry.description ? `<div class="vtl-desc" title="${esc(entry.description)}">${esc(entry.description)}</div>` : ""}
        ${converted ? `<div class="vtl-write">写入：${esc(formatted)}</div>` : ""}
      </div>
      <div class="vtl-actions">
        <button type="button" class="vtl-add">＋ 加入</button>
        <span class="vtl-cat">${esc(entry.category || "")}</span>
      </div>
    </article>`;
  }

  function tagChips(card) {
    const groups = card.groups || {};
    return Object.keys(GROUP_LABELS).filter((key) => (groups[key] || []).length).map((key) =>
      `<div class="vtl-taggroup"><span class="vtl-grouplabel">${GROUP_LABELS[key]}</span>${
        groups[key].map((tag) => `<button type="button" class="vtl-chip" data-tag="${esc(tag)}" data-kind="${key}" title="点击写入「${esc(targetLabel(targetSection()))}」">${esc(tag)}</button>`).join("")
      }</div>`).join("");
  }

  function cloudCard(card) {
    const queryTag = state.query.trim();
    const selected = isSelected(queryTag);
    const expanded = !!state.expanded[card.id];
    const badge = RATING_BADGE[card.rating] || "?";
    const size = card.width && card.height ? `${card.width}×${card.height}` : "";
    return `<article class="vtl-card vtl-cloud${selected ? " selected" : ""}" data-post="${esc(card.id)}">
      <div class="vtl-thumb">
        <img loading="lazy" src="${esc(card.preview_url)}" alt="post ${esc(String(card.post_id))}" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'vtl-nothumb',textContent:'预览不可用'}))">
        <span class="vtl-badge">${badge}</span>
        ${card.sample_url ? `<button type="button" class="vtl-full" data-full="${esc(card.sample_url)}" title="查看示例大图">⤢</button>` : ""}
      </div>
      <div class="vtl-body">
        <div class="vtl-tag">#${esc(String(card.post_id))}${size ? ` · ${esc(size)}` : ""}</div>
        <div class="vtl-zh">score ${esc(String(card.score))} · ${esc(String(card.tag_count))} 个标签</div>
      </div>
      <div class="vtl-actions">
        <button type="button" class="vtl-add">＋ ${esc(queryTag)}</button>
        <button type="button" class="vtl-expand">${expanded ? "收起 Tags" : "查看 Tags"}</button>
        <a class="vtl-link" href="${esc(card.post_url)}" target="_blank" rel="noopener noreferrer">帖子</a>
      </div>
      <div class="vtl-post-tags" ${expanded ? "" : "hidden"}></div>
    </article>`;
  }

  function renderGrid() {
    const grid = byId("vtlGrid");
    if (!grid) return;
    if (state.loading) {
      grid.innerHTML = '<div class="vtl-empty">正在读取…</div>';
      return;
    }
    if (!state.results.length) {
      const hint = state.source === "local" && state.query
        ? `<div class="vtl-empty">本地词条库没有“${esc(state.query)}”。<button type="button" class="vtl-tocloud">☁ 去 Danbooru 云端查</button></div>`
        : `<div class="vtl-empty">${state.source === "cloud" ? "输入英文 tag 后查询云端；中文会先自动解析。" : "输入关键词搜索本地精选词条，或留空浏览全部。"}</div>`;
      grid.innerHTML = hint;
      return;
    }
    grid.innerHTML = state.results.map((item) =>
      state.source === "cloud" ? cloudCard(item) : localCard(item)).join("");
  }

  function renderStatus() {
    const status = byId("vtlStatus");
    if (!status) return;
    const parts = [];
    if (state.source === "local") {
      const stats = (state.meta && state.meta.stats) || {};
      parts.push(`本地精选：${state.localTotal} 条${state.meta && state.meta.matched != null ? ` · 命中 ${state.meta.matched}` : ""}${stats.generated_at ? ` · 索引 ${stats.generated_at}` : ""}`);
    } else {
      parts.push(`Danbooru 云端：每页 ${CLOUD_LIMIT} 张 · 第 ${state.page} 页${state.meta && state.meta.composed_query ? ` · 查询 ${state.meta.composed_query}` : ""}`);
    }
    parts.push(`写入形式：${dialectLabel()}`);
    status.innerHTML = `<span>${esc(parts.join(" · "))}</span>`;
    const notice = byId("vtlNotice");
    if (notice) {
      notice.textContent = state.error || state.notice || "";
      notice.classList.toggle("error", !!state.error);
      notice.hidden = !(state.error || state.notice);
    }
  }

  function renderFooter() {
    const count = byId("vtlCount");
    if (!count) return;
    const preview = state.selected.slice(0, 4).map((item) => formatTag(item.tag, item.kind));
    count.textContent = state.selected.length
      ? `已选 ${state.selected.length}：${preview.join(", ")}${state.selected.length > 4 ? " …" : ""}`
      : "未选择任何词条";
    const pager = byId("vtlPager");
    if (pager) pager.hidden = state.source !== "cloud";
    const pageLabel = byId("vtlPageLabel");
    if (pageLabel) pageLabel.textContent = `第 ${state.page} 页`;
    const prev = byId("vtlPrev");
    const next = byId("vtlNext");
    if (prev) prev.disabled = state.page <= 1 || state.loading;
    if (next) next.disabled = state.loading || state.results.length < CLOUD_LIMIT;
  }

  function renderToolbar() {
    const category = byId("vtlCategory");
    if (category) {
      const current = state.category;
      category.hidden = state.source !== "local";
      category.innerHTML = '<option value="">全部分类</option>' + state.categories
        .map((item) => `<option value="${esc(item)}">${esc(item)}</option>`).join("");
      if (state.categories.indexOf(current) >= 0) category.value = current;
    }
    ["vtlRating", "vtlSort"].forEach((id) => {
      const node = byId(id);
      if (node) node.hidden = state.source !== "cloud";
    });
    const rebuild = byId("vtlRebuild");
    if (rebuild) rebuild.hidden = state.source !== "local";
    const search = byId("vtlSearch");
    if (search && search.value !== state.query) search.value = state.query;
    const tabs = document.querySelectorAll(".vtl-tab");
    tabs.forEach((tab) => {
      const active = tab.dataset.source === state.source;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
    });
  }

  function renderAll() {
    renderToolbar();
    renderStatus();
    renderGrid();
    renderFooter();
  }

  /* ------------------------------------------------------------- 界面 */

  function buildDialog() {
    const overlay = document.createElement("div");
    overlay.id = "vtlOverlay";
    overlay.className = "vtl-overlay";
    overlay.hidden = true;
    overlay.innerHTML = `
      <div class="vtl-dialog" role="dialog" aria-modal="true" aria-label="视觉词条库">
        <header class="vtl-head">
          <b>视觉词条库</b>
          <div class="vtl-tabs" role="tablist">
            <button type="button" class="vtl-tab active" data-source="local" role="tab">本地精选</button>
            <button type="button" class="vtl-tab" data-source="cloud" role="tab">Danbooru 云端</button>
          </div>
          <button type="button" class="vtl-close" title="关闭（Esc）">✕</button>
        </header>
        <div class="vtl-toolbar">
          <input id="vtlSearch" class="vtl-search" placeholder="搜索 tag / 中文名 / 释义；中文可直接输入（云端会先解析）">
          <select id="vtlCategory" title="按本地分类筛选"></select>
          <select id="vtlRating" title="云端分级过滤">${Object.keys(RATINGS).map((key) => `<option value="${key}">${RATINGS[key]}</option>`).join("")}</select>
          <select id="vtlSort" title="云端排序（不提供热门排序：Danbooru 的 order:score 在热门标签上会 500）">${Object.keys(SORTS).map((key) => `<option value="${key}">${SORTS[key]}</option>`).join("")}</select>
          <select id="vtlTarget" title="插入到哪个提示词分区"></select>
          <button type="button" id="vtlRebuild" class="vtl-ghost" title="源文档有改动时重建本地索引">重建索引</button>
        </div>
        <div id="vtlStatus" class="vtl-status"></div>
        <div id="vtlNotice" class="vtl-notice" hidden></div>
        <div id="vtlGrid" class="vtl-grid"></div>
        <footer class="vtl-foot">
          <span id="vtlCount" class="vtl-foot-count"></span>
          <div class="vtl-foot-actions">
            <button type="button" id="vtlCopy" class="vtl-ghost">复制 Tag</button>
            <button type="button" id="vtlInsert" class="vtl-primary">加入当前分区</button>
            <button type="button" id="vtlInsertHires" class="vtl-ghost">加入二采</button>
            <button type="button" id="vtlClear" class="vtl-ghost">清空选择</button>
          </div>
          <span id="vtlPager" class="vtl-pager" hidden>
            <button type="button" id="vtlPrev" class="vtl-ghost">上一页</button>
            <span id="vtlPageLabel"></span>
            <button type="button" id="vtlNext" class="vtl-ghost">下一页</button>
          </span>
        </footer>
      </div>`;
    document.body.appendChild(overlay);

    const target = byId("vtlTarget");
    const source = byId("tagTarget");
    if (target && source) {
      target.innerHTML = source.innerHTML;
      target.value = source.value;
      target.addEventListener("change", () => {
        source.value = target.value;
        if (typeof window.promptEditorChanged === "function") window.promptEditorChanged();
        renderGrid();
        renderFooter();
      });
      source.addEventListener("change", () => { target.value = source.value; });
    }

    byId("vtlSearch").addEventListener("input", debounce(() => {
      state.query = byId("vtlSearch").value.trim();
      state.page = 1;
      reload();
    }, 300));
    byId("vtlSearch").addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      state.query = byId("vtlSearch").value.trim();
      state.page = 1;
      reload();
    });
    byId("vtlCategory").addEventListener("change", () => {
      state.category = byId("vtlCategory").value;
      saveState();
      loadLocal();
    });
    byId("vtlRating").addEventListener("change", () => {
      state.rating = byId("vtlRating").value;
      saveState();
      state.page = 1;
      loadCloud();
    });
    byId("vtlSort").addEventListener("change", () => {
      state.sort = byId("vtlSort").value;
      saveState();
      state.page = 1;
      loadCloud();
    });
    byId("vtlRebuild").addEventListener("click", rebuildIndex);
    byId("vtlCopy").addEventListener("click", copySelected);
    byId("vtlInsert").addEventListener("click", () => insertSelected("section"));
    byId("vtlInsertHires").addEventListener("click", () => insertSelected("hires"));
    byId("vtlClear").addEventListener("click", clearSelection);
    byId("vtlPrev").addEventListener("click", () => {
      state.page = Math.max(1, state.page - 1);
      loadCloud();
    });
    byId("vtlNext").addEventListener("click", () => {
      state.page += 1;
      loadCloud();
    });
    overlay.querySelector(".vtl-close").addEventListener("click", close);
    overlay.addEventListener("click", (event) => { if (event.target === overlay) close(); });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !overlay.hidden) close();
    });
    overlay.querySelectorAll(".vtl-tab").forEach((tab) => tab.addEventListener("click", () => {
      if (state.source === tab.dataset.source) return;
      state.source = tab.dataset.source;
      state.page = 1;
      saveState();
      reload();
    }));

    byId("vtlGrid").addEventListener("click", async (event) => {
      const card = event.target.closest(".vtl-card");
      if (!card) return;
      const full = event.target.closest(".vtl-full");
      if (full) {
        window.open(full.dataset.full, "_blank", "noopener,noreferrer");
        return;
      }
      const chip = event.target.closest(".vtl-chip");
      if (chip) {
        addTag(chip.dataset.tag, chip.dataset.kind);
        return;
      }
      const expand = event.target.closest(".vtl-expand");
      if (expand && state.source === "cloud") {
        const id = card.dataset.post;
        state.expanded[id] = !state.expanded[id];
        renderGrid();
        if (state.expanded[id]) {
          // Tags 懒渲染：展开时才写入 chips（一页 20 张卡全部预渲染会多出 1200+ 个节点）
          const box = document.querySelector(`.vtl-card[data-post="${card.dataset.post}"] .vtl-post-tags`);
          const post = state.results.find((item) => item.id === card.dataset.post);
          if (box && post) box.innerHTML = tagChips(post);
        }
        return;
      }
      const toCloud = event.target.closest(".vtl-tocloud");
      if (toCloud) {
        state.source = "cloud";
        state.page = 1;
        saveState();
        reload();
        return;
      }
      if (event.target.closest(".vtl-add")) {
        if (state.source === "cloud") addTag(state.query.trim(), "general");
        else addTag(card.dataset.tag, card.dataset.kind);
        return;
      }
      if (state.source === "cloud") toggleSelect(state.query.trim(), "general");
      else toggleSelect(card.dataset.tag, card.dataset.kind);
    });
  }

  const STYLE_ID = "vtlStyles";

  function installStyles() {
    if (byId(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
.vtl-open-row{display:flex;gap:8px;align-items:center;margin-top:6px;flex-wrap:wrap}
.vtl-open-row .small{color:var(--muted,#adb7cb)}
button.vtl-primary{background:linear-gradient(135deg,var(--accent,#9174ff),var(--accent2,#c977fa));color:#fff;border:0;border-radius:8px;padding:6px 12px;cursor:pointer;font-size:calc(var(--input-font-size,15px) - 3px)}
button.vtl-ghost{background:var(--token,#282d40);color:inherit;border:1px solid var(--line,#343d53);border-radius:8px;padding:5px 10px;cursor:pointer;font-size:calc(var(--input-font-size,15px) - 3px)}
button.vtl-ghost:disabled{opacity:.45;cursor:not-allowed}
.vtl-overlay{position:fixed;inset:0;z-index:9000;background:rgba(6,8,14,.68);display:flex;align-items:center;justify-content:center;padding:18px}
/* ⚠️ 自定义 display 会盖掉 [hidden] 的 display:none，必须显式补回，否则隐藏的遮罩仍拦截点击。 */
.vtl-overlay[hidden],.vtl-post-tags[hidden],.vtl-pager[hidden]{display:none}
.vtl-dialog{background:var(--panel,#141925);border:1px solid var(--line,#343d53);border-radius:14px;width:min(1180px,100%);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;color:inherit}
.vtl-head{display:flex;align-items:center;gap:12px;padding:10px 14px;border-bottom:1px solid var(--line,#343d53)}
.vtl-head b{font-size:calc(var(--input-font-size,15px) + 1px)}
.vtl-tabs{display:flex;gap:6px;margin-left:6px}
.vtl-tab{background:transparent;border:1px solid var(--line,#343d53);color:var(--muted,#adb7cb);border-radius:999px;padding:4px 12px;cursor:pointer;font-size:calc(var(--input-font-size,15px) - 3px)}
.vtl-tab.active{color:#fff;border-color:transparent;background:linear-gradient(135deg,var(--accent,#9174ff),var(--accent2,#c977fa))}
.vtl-close{margin-left:auto;background:transparent;border:0;color:var(--muted,#adb7cb);font-size:16px;cursor:pointer;padding:2px 6px}
.vtl-toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:10px 14px 6px}
.vtl-toolbar input,.vtl-toolbar select{background:var(--bg,#10131c);border:1px solid var(--line,#343d53);color:inherit;border-radius:8px;padding:6px 8px;font-size:var(--input-font-size,15px)}
.vtl-toolbar .vtl-search{flex:1 1 260px;min-width:200px}
.vtl-status{display:flex;gap:10px;justify-content:space-between;padding:0 14px 6px;color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px)}
.vtl-notice{margin:0 14px 8px;padding:6px 10px;border-radius:8px;background:rgba(145,116,255,.12);border:1px solid rgba(145,116,255,.35);font-size:calc(var(--input-font-size,15px) - 3px)}
.vtl-notice.error{background:rgba(255,110,110,.12);border-color:rgba(255,110,110,.45);color:#ffb4b4}
.vtl-grid{flex:1 1 auto;overflow:auto;display:grid;gap:10px;padding:4px 14px 12px;grid-template-columns:repeat(auto-fill,minmax(168px,1fr))}
.vtl-empty{grid-column:1/-1;color:var(--muted,#adb7cb);padding:18px 4px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.vtl-card{background:var(--card,#1b202c);border:1px solid var(--line,#343d53);border-radius:12px;overflow:hidden;display:flex;flex-direction:column;cursor:pointer;transition:border-color .15s,transform .15s}
.vtl-card:hover{transform:translateY(-1px)}
.vtl-card.selected{border-color:var(--accent,#9174ff);box-shadow:0 0 0 1px var(--accent,#9174ff) inset}
.vtl-thumb{position:relative;background:#0b0e15;aspect-ratio:3/4;display:flex;align-items:center;justify-content:center;overflow:hidden}
.vtl-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.vtl-nothumb{color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px)}
.vtl-badge{position:absolute;left:6px;top:6px;background:rgba(8,10,16,.72);border:1px solid var(--line,#343d53);border-radius:6px;padding:1px 6px;font-size:11px;letter-spacing:.5px}
.vtl-badge.warn{border-color:#c98b3a;color:#ffcf8f;left:auto;right:6px;top:auto;bottom:6px}
.vtl-full{position:absolute;right:6px;top:6px;background:rgba(8,10,16,.72);border:1px solid var(--line,#343d53);color:#fff;border-radius:6px;padding:1px 6px;cursor:pointer}
.vtl-body{padding:8px 9px 4px;display:flex;flex-direction:column;gap:4px}
.vtl-tag{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:calc(var(--input-font-size,15px) - 2px);word-break:break-word}
.vtl-zh{font-size:calc(var(--input-font-size,15px) - 3px);display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.vtl-group{background:var(--token,#282d40);border:1px solid var(--line,#343d53);border-radius:999px;padding:0 7px;color:var(--muted,#adb7cb);font-size:11px}
.vtl-desc{color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.vtl-write{color:#9fe3b0;font-size:calc(var(--input-font-size,15px) - 4px);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.vtl-actions{display:flex;gap:6px;align-items:center;padding:6px 9px 9px;margin-top:auto;flex-wrap:wrap}
.vtl-actions button{background:var(--token,#282d40);border:1px solid var(--line,#343d53);color:inherit;border-radius:7px;padding:3px 8px;cursor:pointer;font-size:calc(var(--input-font-size,15px) - 4px)}
.vtl-actions .vtl-add{border-color:rgba(145,116,255,.5)}
.vtl-actions .vtl-cat{margin-left:auto;color:var(--muted,#adb7cb);font-size:11px}
.vtl-link{color:var(--accent,#9174ff);font-size:calc(var(--input-font-size,15px) - 4px);text-decoration:none}
.vtl-post-tags{border-top:1px dashed var(--line,#343d53);padding:6px 9px 10px;display:flex;flex-direction:column;gap:6px;max-height:220px;overflow:auto}
.vtl-taggroup{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.vtl-grouplabel{color:var(--muted,#adb7cb);font-size:11px;min-width:30px}
.vtl-chip{background:var(--token,#282d40);border:1px solid var(--line,#343d53);color:inherit;border-radius:999px;padding:1px 8px;cursor:pointer;font-size:calc(var(--input-font-size,15px) - 4px)}
.vtl-chip:hover{border-color:var(--accent,#9174ff)}
.vtl-foot{display:flex;gap:10px;align-items:center;padding:9px 14px;border-top:1px solid var(--line,#343d53);flex-wrap:wrap}
.vtl-foot-count{color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px);flex:1 1 200px}
.vtl-foot-actions{display:flex;gap:6px;flex-wrap:wrap}
.vtl-pager{display:flex;gap:6px;align-items:center;color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px)}
.prompt-dialect{display:inline-flex;align-items:center;gap:4px}
.prompt-dialect select{background:var(--bg,#10131c);border:1px solid var(--line,#343d53);color:inherit;border-radius:8px;padding:5px 6px;font-size:calc(var(--input-font-size,15px) - 3px)}
.prompt-dialect-hint{color:var(--muted,#adb7cb)}
@keyframes vtlFlash{0%{box-shadow:0 0 0 2px rgba(145,116,255,.85)}100%{box-shadow:0 0 0 2px rgba(145,116,255,0)}}
.vtl-flash{animation:vtlFlash .9s ease-out}`;
    document.head.appendChild(style);
  }

  function debounce(fn, wait) {
    let timer = 0;
    return function () {
      const args = arguments;
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(null, args), wait);
    };
  }

  function scrollToEdit() {
    if (typeof window.setStudioCreationTab === "function") {
      try { window.setStudioCreationTab("prompt"); } catch (_error) { /* 无标签页结构 */ }
    }
    requestAnimationFrame(() => {
      const block = document.querySelector(".prompt-tag-search");
      if (block) block.scrollIntoView({ behavior: "smooth", block: "center" });
      const field = byId(promptFieldId(targetSection()));
      if (!field) return;
      field.scrollIntoView({ behavior: "smooth", block: "center" });
      field.classList.add("vtl-flash");
      setTimeout(() => field.classList.remove("vtl-flash"), 900);
    });
  }

  function promptFieldId(section) {
    const ids = {
      subject: "promptSubject", appearance: "promptAppearance", expression: "promptExpression",
      clothing: "promptClothing", pose: "promptPose", composition: "promptComposition",
      scene: "promptScene", lighting: "promptLighting", style: "promptStyle", manual: "prompt",
    };
    return ids[section] || "prompt";
  }

  function open() {
    state.source = state.source || "local";
    state.query = (byId("tagSearch") && byId("tagSearch").value.trim()) || state.query;
    const target = byId("vtlTarget");
    if (target && byId("tagTarget")) target.value = byId("tagTarget").value;
    if (state.results.length === 0 && !state.query) {
      state.category = state.category || "";
    }
    if (!state.localTotal) loadStats();
    reload();
    const overlay = byId("vtlOverlay");
    if (overlay) overlay.hidden = false;
    const search = byId("vtlSearch");
    if (search) setTimeout(() => search.focus(), 30);
  }

  function close() {
    const overlay = byId("vtlOverlay");
    if (overlay) overlay.hidden = true;
  }

  function installButton() {
    const block = document.querySelector(".prompt-tag-search");
    if (!block || byId("vtlOpen")) return;
    const actions = document.createElement("div");
    actions.className = "vtl-open-row";
    actions.innerHTML = '<button type="button" id="vtlOpen" class="vtl-primary">🖼 可视化词条库</button>'
      + '<span class="small">本地精选词条 + Danbooru 云端图片；点击卡片即可写入提示词分区。</span>';
    block.appendChild(actions);
    byId("vtlOpen").addEventListener("click", open);
  }

  const testApi = {
    LOCAL_API, CLOUD_API, IMAGE_API, LOCAL_LIMIT, CLOUD_LIMIT,
    RATINGS, SORTS, RATING_BADGE, GROUP_LABELS,
    formatTag, dialectLabel, targetSection, targetLabel, promptFieldId, state,
    open, close, reload,
  };
  window.EasyPanelVisualTags = Object.assign(testApi, {
    refresh: () => {
      const overlay = typeof document !== "undefined" ? byId("vtlOverlay") : null;
      if (overlay && !overlay.hidden) reload();
    },
  });
  if (typeof module !== "undefined" && module.exports) module.exports = testApi;

  if (typeof document === "undefined") return;   // node 测试环境没有 DOM

  function boot() {
    loadState();
    installStyles();
    buildDialog();
    installButton();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
