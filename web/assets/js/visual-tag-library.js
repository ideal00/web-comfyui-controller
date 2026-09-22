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
  const CLOUD_IMAGE_API = "/api/danbooru/image";
  const STORAGE_KEY = "easyPanelVisualTagLibraryV1";
  const LOCAL_LIMIT = 48;
  const CLOUD_LIMIT = 20;  const RATINGS = { general: "General 全年龄", sensitive: "Sensitive 敏感", questionable: "Questionable 暗示", explicit: "Explicit 明确" };
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
    shown: 0,
    hasMore: false,
    indexGeneratedAt: "",
    bundleCategory: "",
    bundleMode: "append",
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
        bundleCategory: state.bundleCategory, bundleMode: state.bundleMode,
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
      if (typeof saved.bundleCategory === "string") state.bundleCategory = saved.bundleCategory;
      if (saved.bundleMode === "replace" || saved.bundleMode === "append") state.bundleMode = saved.bundleMode;
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

  function pageSize() {
    return state.source === "cloud" ? CLOUD_LIMIT : LOCAL_LIMIT;
  }

  async function loadLocal() {
    state.loading = true;
    renderAll();
    try {
      const layer = dialect();
      const params = new URLSearchParams({
        q: state.query, limit: String(LOCAL_LIMIT), category: state.category,
        offset: String(Math.max(0, state.page - 1) * LOCAL_LIMIT),
        family: layer ? layer.family() : "", dialect: layer ? layer.currentDialect() : "",
      });
      const response = await fetch(`${LOCAL_API}?${params.toString()}`);
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      state.results = data.results || [];
      state.meta = data;
      state.categories = data.categories || [];
      // 搜索响应自带总数/分类/索引时间，不必再单独请求一次统计。
      state.localTotal = data.total || 0;
      state.indexGeneratedAt = data.generated_at || "";
      state.hasMore = !!data.has_more;
      state.shown = data.shown || 0;
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
        state.shown = data.received != null ? data.received : (data.results || []).length;
        state.hasMore = state.shown >= CLOUD_LIMIT;
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

  function pageChanged() {
    const grid = byId("vtlGrid");
    if (grid) grid.scrollTop = 0;
    const panel = document.querySelector(".vtl-dialog");
    if (panel) panel.scrollTop = 0;
    return reload();
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

  function toggleSelect(tag, kind, element) {
    if (!tag) return;
    if (isSelected(tag)) {
      state.selected = state.selected.filter((item) => item.tag !== tag);
    } else {
      state.selected.push({ tag: tag, kind: kind || "general" });
    }
    // 局部刷新选中态：整格重渲染会换掉 DOM 节点，连续点多张时容易丢点击。
    if (element && element.classList) element.classList.toggle("selected", isSelected(tag));
    refreshSelectionUi();
  }

  function refreshSelectionUi() {
    document.querySelectorAll("#vtlGrid .vtl-card").forEach((card) => {
      const target = card.dataset.tag
        ? { tag: card.dataset.tag }
        : cloudAddTarget(card);
      if (target && target.tag) card.classList.toggle("selected", isSelected(target.tag));
    });
    document.querySelectorAll("#vtlGrid .vtl-chip").forEach((chip) => {
      const tag = chip.dataset.tag || "";
      const active = isSelected(tag);
      chip.classList.toggle("checked", active);
      chip.textContent = active ? `✓ ${tag}` : tag;
    });
    document.querySelectorAll(".vtl-tagpanel-count").forEach((node) => {
      node.textContent = `已选 ${state.selected.length}`;
    });
    renderFooter();
  }

  function refreshPostTags(postId) {
    const card = document.querySelector(`.vtl-card[data-post="${postId}"]`);
    if (!card) return;
    const box = card.querySelector(".vtl-post-tags");
    const post = state.results.find((item) => item.id === postId);
    if (box && post) box.innerHTML = tagChips(post);
  }

  function addTag(tag, kind, sectionOverride) {
    const section = sectionOverride || targetSection();
    const formatted = formatTag(tag, kind);
    if (typeof window.appendEnglish === "function") window.appendEnglish(formatted, section);
    const changed = formatted !== tag;
    setNotice(`${changed ? `${tag} → ${formatted}（按 ${dialectLabel()} 转换）` : `${formatted}`} 已写入「${targetLabel(section)}」。`);
    return formatted;
  }

  function insertMany(items, sectionOverride) {
    const written = [];
    items.forEach((item) => {
      if (!item || !item.tag) return;
      written.push(addTag(item.tag, item.kind, sectionOverride));
    });
    if (!written.length) {
      setNotice("先点选标签或卡片。");
      return [];
    }
    const section = sectionOverride || targetSection();
    setNotice(`已写入「${targetLabel(section)}」：${written.join(", ")}`);
    return written;
  }

  function searchTag(tag, source) {
    if (!tag) return;
    state.query = String(tag).trim();
    state.page = 1;
    if (source) state.source = source;
    // 换搜索词就清空已选：上一次结果里的选中项留在新结果上会让人误以为还是那批标签。
    state.selected = [];
    const search = byId("vtlSearch");
    if (search) search.value = state.query;
    saveState();
    reload();
  }

  function selectedTags() {
    return state.selected.map((item) => item.tag);
  }

  function focusTag(card) {
    if (state.selected.length) return state.selected[0].tag;
    const info = state.meta && state.meta.query_tags;
    const tags = (info && info.tags) || [];
    if (tags.length) return tags[0];
    return (card && card.dataset && card.dataset.focus) || "";
  }

  async function loadRelatedTags(box, tag) {
    if (!box) return;
    if (!tag) {
      box.hidden = false;
      box.textContent = "请先选中一个标签，或用单个标签搜索后再点相关 Tag。";
      return;
    }
    box.hidden = false;
    box.innerHTML = `<span class="vtl-tagpanel-count">正在查「${esc(tag)}」的相关标签…</span>`;
    try {
      const data = await (await fetch(`/api/danbooru/related?` + new URLSearchParams({ tag: tag, limit: "24" }))).json();
      if (data.error) throw new Error(data.error);
      const items = data.results || [];
      if (!items.length) {
        box.textContent = `没有找到「${tag}」的相关标签。`;
        return;
      }
      box.innerHTML = `<span class="vtl-grouplabel">相关（${esc(tag)}）</span>` + items.map((item) =>
        `<span class="vtl-chip-wrap">${chipButton(item.tag, item.kind || "general")}<button type="button" class="vtl-chip-search" data-search="${esc(item.tag)}" title="搜「${esc(item.tag)}」">🔍</button></span>`).join("");
    } catch (error) {
      box.textContent = `相关标签读取失败：${error.message}`;
    }
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

  function kindForTag(tag, card) {
    const groups = (card && card.groups) || {};
    for (const key of ["artist", "character", "copyright", "general"]) {
      if ((groups[key] || []).indexOf(tag) >= 0) return key;
    }
    return "general";
  }

  /**
   * 云端卡片的“＋”只能加**单个明确标签**：
   *  - 搜索只有一个用户标签（high_heels）→ 就加它；
   *  - 搜索含多个标签（1girl high_heels）或只有过滤词（rating:g）→ 不猜，
   *    改为引导展开该图的 Tags 面板挑选，避免把整串搜索词写进 Prompt。
   */
  function cloudAddTarget(card) {
    const info = state.meta && state.meta.query_tags;
    const tags = (info && info.tags) || [];
    if (tags.length !== 1) return null;
    return { tag: tags[0], kind: kindForTag(tags[0], card) };
  }

  function chipButton(tag, kind) {
    const active = state.selected.some((item) => item.tag === tag);
    return `<span class="vtl-chip-wrap"><button type="button" class="vtl-chip${active ? " checked" : ""}" data-tag="${esc(tag)}" data-kind="${esc(kind)}" title="点选/取消（可多选后批量写入）">${active ? "✓ " : ""}${esc(tag)}</button><button type="button" class="vtl-chip-search" data-search="${esc(tag)}" title="用「${esc(tag)}」重新搜索云端图片">🔍</button></span>`;
  }

  function tagChips(card) {
    const groups = card.groups || {};
    const body = Object.keys(GROUP_LABELS).filter((key) => (groups[key] || []).length).map((key) =>
      `<div class="vtl-taggroup"><span class="vtl-grouplabel">${GROUP_LABELS[key]}</span>${
        groups[key].map((tag) => chipButton(tag, key)).join("")
      }</div>`).join("");
    return `${body}
      <div class="vtl-tagpanel-actions">
        <span class="vtl-tagpanel-count">已选 ${state.selected.length}</span>
        <button type="button" class="vtl-quick" data-section="clothing">加入服装</button>
        <button type="button" class="vtl-quick" data-section="pose">加入姿势</button>
        <button type="button" class="vtl-quick" data-section="appearance">加入外貌</button>
        <button type="button" class="vtl-batch-search">用已选搜索</button>
        <button type="button" class="vtl-batch-copy">复制</button>
        <button type="button" class="vtl-related">相关 Tag</button>
      </div>
      <div class="vtl-related-box" hidden></div>`;
  }

  function cloudCard(card) {
    const expanded = !!state.expanded[card.id];
    const badge = RATING_BADGE[card.rating] || "?";
    const size = card.width && card.height ? `${card.width}×${card.height}` : "";
    const target = cloudAddTarget(card);
    const addLabel = target ? `＋ ${target.tag}` : "＋ 从 Tags 选择";
    const selected = !!target && isSelected(target.tag);
    return `<article class="vtl-card vtl-cloud${selected ? " selected" : ""}" data-post="${esc(card.id)}">
      <div class="vtl-thumb">
        <img loading="lazy" src="${CLOUD_IMAGE_API}?post=${encodeURIComponent(String(card.post_id))}&kind=preview" alt="post ${esc(String(card.post_id))}" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'vtl-nothumb',textContent:'预览不可用'}))">
        <span class="vtl-badge">${badge}</span>
        ${card.sample_url ? `<button type="button" class="vtl-full" data-full="${CLOUD_IMAGE_API}?post=${encodeURIComponent(String(card.post_id))}&kind=sample" title="查看示例大图">⤢</button>` : ""}
      </div>
      <div class="vtl-body">
        <div class="vtl-tag">#${esc(String(card.post_id))}${size ? ` · ${esc(size)}` : ""}</div>
        <div class="vtl-zh">score ${esc(String(card.score))} · ${esc(String(card.tag_count))} 个标签</div>
      </div>
      <div class="vtl-actions">
        <button type="button" class="vtl-add">${esc(addLabel)}</button>
        <button type="button" class="vtl-expand">${expanded ? "收起 Tags" : "查看 Tags"}</button>
        <a class="vtl-link" href="${esc(card.post_url)}" target="_blank" rel="noopener noreferrer">帖子</a>
      </div>
      <div class="vtl-post-tags" ${expanded ? "" : "hidden"}></div>
    </article>`;
  }

  function emptyHint() {
    if (state.source === "local") {
      return state.query
        ? `<div class="vtl-empty">${state.category ? `分类「${esc(state.category)}」里没有“${esc(state.query)}”。` : `本地词条库没有“${esc(state.query)}”。`}${
            state.category ? '<button type="button" class="vtl-clear-category">清除分类筛选</button>' : ""
          }<button type="button" class="vtl-tocloud">☁ 去 Danbooru 云端查</button></div>`
        : `<div class="vtl-empty">输入关键词搜索本地精选词条，或留空浏览全部。</div>`;
    }
    // 云端：Danbooru 只认**完整**标签（输 high 查不到图）+ 分级过滤会进一步收窄结果。
    const info = state.meta && state.meta.query_tags;
    const typed = ((info && info.tags) || []).join(" ");
    return `<div class="vtl-empty">云端没有匹配结果。可能原因：
      <b>①</b> 标签不完整（Danbooru 要完整标签，如 <code>high_heels</code> 而不是 <code>high</code>）；
      <b>②</b> 分级过滤太窄（当前 <b>${esc(RATINGS[state.rating] || state.rating)}</b>）；
      <b>③</b> 刚被限流（稍等十几秒重试）。
      ${typed ? `<button type="button" class="vtl-suggest-btn" data-term="${esc(typed)}">⚡ 补全「${esc(typed)}」相关标签</button>` : ""}
    </div>`;
  }

  async function loadTagSuggestions(term) {
    const box = byId("vtlSuggest");
    if (!box) return;
    const needle = String(term || "").trim().replace(/[*\s]+$/, "");
    if (!needle) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML = `<span class="vtl-tagpanel-count">正在查以「${esc(needle)}」开头的标签…</span>`;
    try {
      const data = await (await fetch("/api/danbooru/tags?" + new URLSearchParams({ q: needle, limit: "12" }))).json();
      if (data.error) throw new Error(data.error);
      const items = (data.results || []).filter((item) => item.tag.toLowerCase() !== needle.toLowerCase());
      if (!items.length) {
        box.textContent = `没有以「${needle}」开头的标签，试试换一个词。`;
        return;
      }
      box.innerHTML = `<span class="vtl-grouplabel">标签补全</span>` + items.map((item) =>
        `<button type="button" class="vtl-suggest" data-tag="${esc(item.tag)}" title="点击搜索「${esc(item.tag)}」">${esc(item.tag)} <small>${item.post_count.toLocaleString()}</small></button>`).join("");
    } catch (error) {
      box.textContent = `标签补全失败：${error.message}`;
    }
  }

  function renderGrid() {
    const grid = byId("vtlGrid");
    if (!grid) return;
    const thumbHint = byId("vtlThumbHint");
    if (state.loading) {
      grid.innerHTML = '<div class="vtl-empty">正在读取…</div>';
      if (thumbHint) thumbHint.textContent = "";
      return;
    }
    if (!state.results.length) {
      grid.innerHTML = emptyHint();
      if (thumbHint) thumbHint.textContent = "";
      if (state.source === "cloud") {
        const info = state.meta && state.meta.query_tags;
        const first = ((info && info.tags) || [])[0] || "";
        if (state.error) {
          const box = byId("vtlSuggest");
          if (box) box.hidden = true;
        } else if (first) {
          loadTagSuggestions(first);
        }
      }
      return;
    }
    grid.innerHTML = state.results.map((item) =>
      state.source === "cloud" ? cloudCard(item) : localCard(item)).join("");
    const suggestBox = byId("vtlSuggest");
    if (suggestBox) {
      suggestBox.hidden = true;
      suggestBox.innerHTML = "";
    }
    // 展开过的云端卡片要重新填回 Tags 面板（懒渲染）。
    Object.keys(state.expanded).forEach((id) => {
      if (state.expanded[id]) refreshPostTags(id);
    });
    refreshSelectionUi();
    trackThumbProgress();
  }

  function trackThumbProgress() {
    // 冷缓存时缩略图要现生成；磁盘缓存命中后几乎瞬回。
    // ⚠️ 只统计「已开始加载」的图：loading="lazy" 且未进入视口的图永远 complete=false，
    // 直接统计会把它们算成永久待加载（提示卡在“加载中”）。
    const hint = byId("vtlThumbHint");
    if (!hint) return;
    const images = [...document.querySelectorAll("#vtlGrid .vtl-thumb img")];
    const started = images.filter((image) => image.currentSrc || image.complete);
    if (!started.length || !started.some((image) => !image.complete)) {
      hint.textContent = "";
      return;
    }
    const repaint = () => {
      const left = started.filter((image) => !image.complete).length;
      hint.textContent = left ? `缩略图加载中…（${started.length - left}/${started.length}）` : "";
      if (!left) hint.textContent = "";
    };
    repaint();
    started.forEach((image) => {
      image.addEventListener("load", repaint, { once: true });
      image.addEventListener("error", repaint, { once: true });
    });
  }

  function renderStatus() {
    const status = byId("vtlStatus");
    if (!status) return;
    const parts = [];
    if (state.source === "local") {
      const shown = state.shown || state.results.length;
      const from = shown ? state.meta.offset + 1 : 0;
      const to = state.meta.offset + shown;
      parts.push(`本地精选：${state.localTotal} 条${state.meta && state.meta.matched != null ? ` · 命中 ${state.meta.matched}` : ""}${shown ? ` · 显示 ${from}–${to}` : ""}${state.indexGeneratedAt ? ` · 索引 ${state.indexGeneratedAt}（源文档未改不会重建）` : ""}`);
    } else {
      const shown = (state.meta && state.meta.received != null) ? state.meta.received : state.results.length;
      parts.push(`Danbooru 云端：每页 ${CLOUD_LIMIT} 张 · 第 ${state.page} 页${shown ? ` · 本页 ${shown} 张` : ""}${state.meta && state.meta.composed_query ? ` · 查询 ${state.meta.composed_query}` : ""}`);
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
    if (pager) pager.hidden = false;
    const pageLabel = byId("vtlPageLabel");
    if (pageLabel) {
      const pages = state.source === "cloud"
        ? 0
        : Math.max(1, Math.ceil((state.meta && state.meta.matched ? state.meta.matched : state.results.length) / LOCAL_LIMIT));
      pageLabel.textContent = pages > 1 ? `第 ${state.page} / ${pages} 页` : `第 ${state.page} 页`;
    }
    const prev = byId("vtlPrev");
    const next = byId("vtlNext");
    if (prev) prev.disabled = state.page <= 1 || state.loading;
    if (next) next.disabled = state.loading || !state.hasMore;
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
        <div id="vtlSuggest" class="vtl-suggest-row" hidden></div>
        <div id="vtlThumbHint" class="vtl-thumb-hint"></div>
        <div id="vtlNotice" class="vtl-notice" hidden></div>
        <div id="vtlGrid" class="vtl-grid"></div>
        <footer class="vtl-foot">
          <span id="vtlCount" class="vtl-foot-count"></span>
          <div class="vtl-foot-actions">
            <button type="button" id="vtlBundle" class="vtl-ghost" title="把已选标签存成可复用的提示词组件（存 Danbooru 原形，插入时按模型方言转换）">存为组件</button>
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
      state.selected = [];
      reload();
    }, 300));
    byId("vtlSearch").addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      state.query = byId("vtlSearch").value.trim();
      state.page = 1;
      state.selected = [];
      reload();
    });
    byId("vtlCategory").addEventListener("change", () => {
      state.category = byId("vtlCategory").value;
      state.page = 1;
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
    byId("vtlSuggest").addEventListener("click", (event) => {
      const chip = event.target.closest(".vtl-suggest");
      if (chip) searchTag(chip.dataset.tag, "cloud");
    });
    byId("vtlCopy").addEventListener("click", copySelected);
    byId("vtlBundle").addEventListener("click", openBundleDialog);
    byId("vtlInsert").addEventListener("click", () => insertSelected("section"));
    byId("vtlInsertHires").addEventListener("click", () => insertSelected("hires"));
    byId("vtlClear").addEventListener("click", clearSelection);
    byId("vtlPrev").addEventListener("click", () => {
      state.page = Math.max(1, state.page - 1);
      pageChanged();
    });
    byId("vtlNext").addEventListener("click", () => {
      state.page += 1;
      pageChanged();
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
      state.selected = [];
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
      // ---- Tags 面板（V2.2 / V2.3）：点选多选、🔍 再搜索、快捷写入、相关标签 ----
      const chipSearch = event.target.closest(".vtl-chip-search");
      if (chipSearch) {
        searchTag(chipSearch.dataset.search, "cloud");
        return;
      }
      const chip = event.target.closest(".vtl-chip");
      if (chip) {
        // 只更新选中态：重建 Tags 面板会换掉 DOM 节点，连续点多条时后面几下会落空。
        toggleSelect(chip.dataset.tag, chip.dataset.kind);
        return;
      }
      const quick = event.target.closest(".vtl-quick");
      if (quick) {
        insertMany(state.selected.slice(), quick.dataset.section);
        return;
      }
      const batchSearch = event.target.closest(".vtl-batch-search");
      if (batchSearch) {
        const tags = selectedTags();
        if (!tags.length) {
          setNotice("先点选要搜索的标签。");
          return;
        }
        searchTag(tags.join(" "), "cloud");
        return;
      }
      const batchCopy = event.target.closest(".vtl-batch-copy");
      if (batchCopy) {
        copySelected();
        return;
      }
      const related = event.target.closest(".vtl-related");
      if (related) {
        const box = card.querySelector(".vtl-related-box");
        loadRelatedTags(box, focusTag(card));
        return;
      }
      const expand = event.target.closest(".vtl-expand");
      if (expand && state.source === "cloud") {
        const id = card.dataset.post;
        state.expanded[id] = !state.expanded[id];
        renderGrid();
        if (state.expanded[id]) refreshPostTags(card.dataset.post);
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
      const clearCategory = event.target.closest(".vtl-clear-category");
      if (clearCategory) {
        state.category = "";
        state.page = 1;
        saveState();
        loadLocal();
        return;
      }
      const suggestBtn = event.target.closest(".vtl-suggest-btn");
      if (suggestBtn) {
        loadTagSuggestions(suggestBtn.dataset.term);
        return;
      }
      if (event.target.closest(".vtl-add")) {
        if (state.source === "cloud") {
          const target = cloudAddTarget(card);
          if (target) addTag(target.tag, target.kind);
          else {
            setNotice("这张图对应多个搜索标签或只有过滤词；已展开 Tags，请挑具体标签（单个可多选后批量写入）。");
            state.expanded[card.dataset.post] = true;
            renderGrid();
            refreshPostTags(card.dataset.post);
          }
        } else {
          addTag(card.dataset.tag, card.dataset.kind);
        }
        return;
      }
      if (state.source === "cloud") {
        const target = cloudAddTarget(card);
        if (target) toggleSelect(target.tag, target.kind, card);
        else {
          state.expanded[card.dataset.post] = true;
          renderGrid();
          refreshPostTags(card.dataset.post);
          setNotice("搜索含多个标签，已展开这张图的 Tags，点选后再批量写入。");
        }
      } else {
        toggleSelect(card.dataset.tag, card.dataset.kind, card);
      }
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
.vtl-thumb-hint{padding:0 14px 6px;color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px);min-height:14px}
.vtl-notice{margin:0 14px 8px;padding:6px 10px;border-radius:8px;background:rgba(145,116,255,.12);border:1px solid rgba(145,116,255,.35);font-size:calc(var(--input-font-size,15px) - 3px)}
.vtl-notice.error{background:rgba(255,110,110,.12);border-color:rgba(255,110,110,.45);color:#ffb4b4}
.vtl-grid{flex:1 1 auto;overflow:auto;display:grid;gap:10px;padding:4px 14px 12px;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));align-items:start;grid-auto-rows:min-content}
.vtl-empty{grid-column:1/-1;color:var(--muted,#adb7cb);padding:18px 4px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.vtl-card{background:var(--card,#1b202c);border:1px solid var(--line,#343d53);border-radius:12px;overflow:hidden;display:flex;flex-direction:column;cursor:pointer;transition:border-color .15s,transform .15s;align-self:start}
.vtl-card:hover{transform:translateY(-1px)}
.vtl-card.selected{border-color:var(--accent,#9174ff);box-shadow:0 0 0 1px var(--accent,#9174ff) inset}
/* ⚠️ 缩略图容器必须给**确定高度**：flex 项上的 aspect-ratio 在本页会被解析成 0 高度，
   卡片 overflow:hidden 一裁，图就“看不见”了（图其实已加载）。 */
.vtl-thumb{position:relative;background:#0b0e15;height:232px;flex:0 0 auto;display:flex;align-items:center;justify-content:center;overflow:hidden}
.vtl-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.vtl-nothumb{color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px)}
.vtl-badge{position:absolute;left:6px;top:6px;background:rgba(8,10,16,.72);border:1px solid var(--line,#343d53);border-radius:6px;padding:1px 6px;font-size:11px;letter-spacing:.5px}
.vtl-badge.warn{border-color:#c98b3a;color:#ffcf8f;left:auto;right:6px;top:auto;bottom:6px}
.vtl-full{position:absolute;right:6px;top:6px;background:rgba(8,10,16,.72);border:1px solid var(--line,#343d53);color:#fff;border-radius:6px;padding:1px 6px;cursor:pointer}
.vtl-body{padding:8px 9px 4px;display:flex;flex-direction:column;gap:4px}
.vtl-tag{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:calc(var(--input-font-size,15px) - 2px);word-break:break-word;overflow-wrap:anywhere}
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
.vtl-chip.checked{border-color:var(--accent,#9174ff);background:rgba(145,116,255,.22)}
.vtl-chip-wrap{display:inline-flex;align-items:center;gap:2px;margin:2px 2px 2px 0}
.vtl-chip-search{background:transparent;border:1px dashed var(--line,#343d53);color:var(--muted,#adb7cb);border-radius:999px;padding:1px 5px;cursor:pointer;font-size:calc(var(--input-font-size,15px) - 6px)}
.vtl-chip-search:hover{border-color:var(--accent,#9174ff);color:inherit}
.vtl-tagpanel-actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center;border-top:1px dashed var(--line,#343d53);padding-top:6px;margin-top:2px}
.vtl-tagpanel-count{color:var(--muted,#adb7cb);font-size:11px}
.vtl-tagpanel-actions button{background:var(--token,#282d40);border:1px solid var(--line,#343d53);color:inherit;border-radius:7px;padding:2px 8px;cursor:pointer;font-size:calc(var(--input-font-size,15px) - 4px)}
.vtl-related-box{display:flex;gap:6px;flex-wrap:wrap;align-items:center;color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px)}
.vtl-related-box[hidden]{display:none}
.vtl-suggest-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;padding:0 14px 8px;color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px)}
.vtl-suggest-row[hidden]{display:none}
.vtl-suggest,.vtl-suggest-btn{background:var(--token,#282d40);border:1px solid var(--line,#343d53);color:inherit;border-radius:999px;padding:2px 10px;cursor:pointer;font-size:calc(var(--input-font-size,15px) - 4px)}
.vtl-suggest:hover,.vtl-suggest-btn:hover{border-color:var(--accent,#9174ff)}
.vtl-suggest small{color:var(--muted,#adb7cb)}
.vtl-empty code{background:var(--token,#282d40);border-radius:4px;padding:0 4px}
.vtl-foot{display:flex;gap:10px;align-items:center;padding:9px 14px;border-top:1px solid var(--line,#343d53);flex-wrap:wrap}
.vtl-foot-count{color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px);flex:1 1 200px}
.vtl-foot-actions{display:flex;gap:6px;flex-wrap:wrap}
.vtl-pager{display:flex;gap:6px;align-items:center;color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px)}
.vtl-bundle-dialog{max-width:560px}
.vtl-bundle-body{display:flex;flex-direction:column;gap:10px;padding:0 14px 12px;font-size:calc(var(--input-font-size,15px) - 3px)}
.vtl-field{display:flex;flex-direction:column;gap:4px}
.vtl-field>span{color:var(--muted,#adb7cb);font-size:calc(var(--input-font-size,15px) - 4px)}
.vtl-field input,.vtl-field select{background:var(--token,#282d40);border:1px solid var(--line,#343d53);border-radius:8px;color:inherit;padding:6px 8px;font-size:inherit;font-family:inherit}
.vtl-bundle-tags{display:flex;flex-direction:column;gap:6px}
.vtl-bundle-chips{display:flex;flex-wrap:wrap;gap:6px}
.vtl-bundle-chip{cursor:default}
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

  /* ------------------------------------------- V2.6 提示词组件（Tag Bundle）
   *
   * 组件 = 名称 + 描述 + 一组标签 + 分类（插到哪个分区）+ 插入方式 + 保存时模型。
   * 标签一律存 **Danbooru 原形**，插入时才过 `window.EasyPanelDialect`：
   * 切模型不用重新保存，同一个组件在 Anima 下写空格、在 Illustrious 下写下划线。
   */

  const BUNDLE_CATEGORY_ORDER = [
    "clothing", "appearance", "subject", "expression", "pose",
    "scene", "lighting", "composition", "artist", "manual", "negative",
  ];

  function bundleCategories() {
    const layer = window.EasyPanelPromptComponent;
    const map = (layer && layer.categories) || {};
    const keys = BUNDLE_CATEGORY_ORDER.filter((key) => map[key]);
    Object.keys(map).forEach((key) => {
      if (key !== "combo" && keys.indexOf(key) < 0) keys.push(key);
    });
    return keys.map((key) => ({ key: key, label: (map[key] && map[key].label) || key }));
  }

  function canonicalTag(tag) {
    return String(tag || "").trim().toLowerCase().replace(/\s+/g, "_").slice(0, 96);
  }

  function bundleNotice(message) {
    const notice = byId("vtlBundleNotice");
    if (!notice) return;
    notice.textContent = message || "";
    notice.hidden = !message;
  }

  function buildBundleDialog() {
    if (byId("vtlBundleOverlay")) return;
    const overlay = document.createElement("div");
    overlay.id = "vtlBundleOverlay";
    overlay.className = "vtl-overlay vtl-bundle-overlay";
    overlay.hidden = true;
    overlay.innerHTML = `
      <div class="vtl-dialog vtl-bundle-dialog" role="dialog" aria-modal="true" aria-label="存为提示词组件">
        <header class="vtl-head">
          <b>存为提示词组件</b>
          <button type="button" class="vtl-close" title="关闭（Esc）">✕</button>
        </header>
        <div class="vtl-bundle-body">
          <label class="vtl-field"><span>组件名称</span>
            <input id="vtlBundleName" maxlength="80" placeholder="例如：黑色细高跟"></label>
          <label class="vtl-field"><span>描述（可选）</span>
            <input id="vtlBundleDesc" maxlength="400" placeholder="例如：细高跟 + 踝带，冷色皮鞋"></label>
          <label class="vtl-field"><span>分类（决定插入到哪个分区）</span>
            <select id="vtlBundleCategory"></select></label>
          <label class="vtl-field"><span>插入方式</span>
            <select id="vtlBundleMode">
              <option value="append">追加（保留分区原有内容）</option>
              <option value="replace">覆盖（替换该分区）</option>
            </select></label>
          <div class="vtl-bundle-tags">
            <span class="vtl-grouplabel">标签（按 Danbooru 原形保存，插入时才转方言）</span>
            <div id="vtlBundleTags" class="vtl-bundle-chips"></div>
          </div>
          <div id="vtlBundleNotice" class="vtl-notice" hidden></div>
        </div>
        <footer class="vtl-foot">
          <span id="vtlBundleCount" class="vtl-foot-count"></span>
          <div class="vtl-foot-actions">
            <button type="button" id="vtlBundleSave" class="vtl-primary">保存组件</button>
            <button type="button" id="vtlBundleCancel" class="vtl-ghost">取消</button>
          </div>
        </footer>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector(".vtl-close").addEventListener("click", closeBundleDialog);
    byId("vtlBundleCancel").addEventListener("click", closeBundleDialog);
    byId("vtlBundleSave").addEventListener("click", saveBundle);
    overlay.addEventListener("click", (event) => { if (event.target === overlay) closeBundleDialog(); });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !overlay.hidden) closeBundleDialog();
    });
  }

  function openBundleDialog() {
    if (!state.selected.length) {
      setNotice("先点选要收进组件的标签。");
      return;
    }
    const overlay = byId("vtlBundleOverlay");
    if (!overlay) return;
    const categories = bundleCategories();
    const select = byId("vtlBundleCategory");
    if (select) {
      select.innerHTML = categories.map((item) => `<option value="${esc(item.key)}">${esc(item.label)}</option>`).join("");
      const preferred = state.bundleCategory || targetSection();
      if (categories.some((item) => item.key === preferred)) select.value = preferred;
    }
    const mode = byId("vtlBundleMode");
    if (mode) mode.value = state.bundleMode === "replace" ? "replace" : "append";
    const tags = state.selected.map((item) => canonicalTag(item.tag)).filter(Boolean);
    const preview = byId("vtlBundleTags");
    if (preview) {
      preview.innerHTML = tags.map((tag) => `<span class="vtl-chip vtl-bundle-chip">${esc(tag)}</span>`).join("");
    }
    const count = byId("vtlBundleCount");
    if (count) count.textContent = `${tags.length} 个标签 · 存 Danbooru 原形，插入时按当前模型方言转换`;
    bundleNotice("");
    const name = byId("vtlBundleName");
    if (name) name.focus();
    overlay.hidden = false;
  }

  function closeBundleDialog() {
    const overlay = byId("vtlBundleOverlay");
    if (overlay) overlay.hidden = true;
  }

  function saveBundle() {
    const layer = window.EasyPanelPromptComponent;
    if (!layer || typeof layer.save !== "function") {
      bundleNotice("当前页面没有加载提示词预设模块，无法保存组件。");
      return;
    }
    const name = byId("vtlBundleName").value.trim();
    const description = byId("vtlBundleDesc").value.trim();
    const category = byId("vtlBundleCategory").value;
    const mode = byId("vtlBundleMode").value;
    const tags = state.selected.map((item) => canonicalTag(item.tag)).filter(Boolean);
    let result = null;
    try {
      result = layer.save({
        name: name, description: description, category: category, mode: mode, tags: tags,
        model: (byId("model") && byId("model").value) || "",
      });
    } catch (error) {
      bundleNotice(`保存失败：${error.message}`);
      return;
    }
    if (!result || !result.ok) {
      bundleNotice((result && result.error) || "保存失败。");
      return;
    }
    state.bundleCategory = category;
    state.bundleMode = mode;
    saveState();
    closeBundleDialog();
    setNotice(`已存为组件「${name}」（${result.count || tags.length} 个标签 · ${bundleCategoryLabel(category)}）${result.replaced ? "，同名组件已更新" : ""}；在「我的提示词预设」里可一键插入或加入二采。`);
  }

  function bundleCategoryLabel(key) {
    const found = bundleCategories().find((item) => item.key === key);
    return found ? found.label : key;
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
    canonicalTag, openBundleDialog, closeBundleDialog, saveBundle, bundleCategories,
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
    buildBundleDialog();
    installButton();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
