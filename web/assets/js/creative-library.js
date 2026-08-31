(function (global) {
  'use strict';

  const OPERATIONS = Object.freeze([
    'txt2img', 'seed_variant', 'img2img', 'inpaint', 'face_fix',
    'hand_fix', 'upscale', 'outfit_change', 'scene_change', 'style_change', 'unknown',
  ]);
  const STATUSES = Object.freeze(['queued', 'running', 'completed', 'error', 'cancelled', 'unknown']);
  const PAGE_SIZE = 24;
  const MAX_PAGE_SIZE = 100;
  const MAX_OFFSET = 1000000;
  const IMAGE_PATH = '/api/rpg/image';

  function asText(value) {
    return value == null ? '' : String(value).trim();
  }

  function clampInteger(value, fallback, minimum, maximum) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.min(maximum, Math.max(minimum, Math.round(parsed)));
  }

  function oneOf(value, values) {
    const normalized = asText(value).toLowerCase();
    return values.includes(normalized) ? normalized : '';
  }

  function buildListQuery(options) {
    const input = options && typeof options === 'object' ? options : {};
    const params = new URLSearchParams();
    params.set('limit', String(clampInteger(input.limit, PAGE_SIZE, 1, MAX_PAGE_SIZE)));
    params.set('offset', String(clampInteger(input.offset, 0, 0, MAX_OFFSET)));
    const operation = oneOf(input.operation, OPERATIONS);
    const status = oneOf(input.status, STATUSES);
    if (operation) params.set('operation', operation);
    if (status) params.set('status', status);
    const model = asText(input.model).slice(0, 200);
    if (model) params.set('model', model);
    const sort = oneOf(input.sort, ['created_at', 'updated_at', 'status', 'operation', 'model']);
    const order = oneOf(input.order, ['asc', 'desc']);
    if (sort) params.set('sort', sort);
    if (order) params.set('order', order);
    return params.toString();
  }

  function safeGenerationId(value) {
    const id = asText(value).toLowerCase();
    if (!/^[0-9a-f]{32}$/u.test(id)) throw new Error('作品编号无效。');
    return id;
  }

  function originFor(value) {
    try {
      return new URL(value || 'http://localhost', 'http://localhost').origin;
    } catch (_) {
      return 'http://localhost';
    }
  }

  function safeLibraryImagePath(value, baseOrigin) {
    const raw = asText(value);
    if (!raw) return '';
    try {
      const base = baseOrigin || (global.location && global.location.origin) || 'http://localhost';
      const parsed = new URL(raw, base);
      if (parsed.origin !== originFor(base) || parsed.pathname !== IMAGE_PATH) return '';
      return parsed.pathname + parsed.search;
    } catch (_) {
      return '';
    }
  }

  function safeOutputFilename(value) {
    const name = asText(value).replace(/\\/gu, '/');
    if (!name || name === '.' || name === '..' || name.includes('/') || name.includes('\u0000')) return '';
    if (name.includes('..')) return '';
    return name.slice(0, 512);
  }

  function safeOutputSubfolder(value) {
    const folder = asText(value).replace(/\\/gu, '/').replace(/^\/+|\/+$/gu, '');
    if (!folder) return '';
    const parts = folder.split('/');
    if (parts.some((part) => !part || part === '.' || part === '..' || part.includes('\u0000'))) return '';
    return parts.join('/').slice(0, 512);
  }

  function artifactPath(artifact, baseOrigin) {
    const supplied = safeLibraryImagePath(artifact && artifact.url, baseOrigin);
    if (supplied) return supplied;
    const filename = safeOutputFilename(artifact && artifact.filename);
    if (!filename) return '';
    const params = new URLSearchParams({
      name: filename,
      type: asText(artifact && (artifact.type || artifact.image_type)) || 'output',
    });
    const subfolder = safeOutputSubfolder(artifact && artifact.subfolder);
    if (subfolder) params.set('subfolder', subfolder);
    return IMAGE_PATH + '?' + params.toString();
  }

  function cloneObject(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    try {
      const cloned = JSON.parse(JSON.stringify(value));
      return cloned && typeof cloned === 'object' && !Array.isArray(cloned) ? cloned : {};
    } catch (_) {
      return {};
    }
  }

  function payloadFromDetail(detail) {
    if (!detail || typeof detail !== 'object') return {};
    const snapshot = detail.snapshot && typeof detail.snapshot === 'object' && !Array.isArray(detail.snapshot)
      ? detail.snapshot : {};
    const replay = detail.replay && typeof detail.replay === 'object' && !Array.isArray(detail.replay)
      ? detail.replay : {};
    const candidate = snapshot.payload && typeof snapshot.payload === 'object' && !Array.isArray(snapshot.payload)
      ? snapshot.payload
      : replay.payload && typeof replay.payload === 'object' && !Array.isArray(replay.payload)
        ? replay.payload
        : detail.input;
    return cloneObject(candidate);
  }

  function nextSeed(value) {
    const previous = asText(value);
    if (/^\d+$/u.test(previous)) {
      try {
        const next = BigInt(previous) + 1n;
        const maximum = 9223372036854775807n;
        return String(next > maximum ? 1n : next);
      } catch (_) {
        // Fall through to a bounded random seed if the host lacks BigInt.
      }
    }
    return String(Math.floor(Math.random() * 900000000000000000) + 1);
  }

  function restorePayloadForForm(detail, mode) {
    const payload = payloadFromDetail(detail);
    if (mode === 'seed-variant') {
      payload.seed = nextSeed(payload.seed == null ? detail && detail.seed : payload.seed);
    }
    return payload;
  }

  function derivationOperationForRestore(detail, mode) {
    if (mode === 'seed-variant') return 'seed_variant';
    const source = oneOf(detail && detail.operation, OPERATIONS);
    // Restore currently fills the existing form only.  It does not select a
    // concrete output as an img2img/inpaint/repair input, so keep the
    // recorded operation instead of claiming an edit input that was not used.
    return source && source !== 'unknown' ? source : 'txt2img';
  }

  function pendingDerivationContextForDetail(detail, mode) {
    if (!detail || typeof detail !== 'object') return null;
    let parentGenerationId;
    try { parentGenerationId = safeGenerationId(detail.generation_id); } catch (_) { return null; }
    return {
      parentGenerationId,
      operation: derivationOperationForRestore(detail, mode),
    };
  }

  function attachPendingDerivationToPayload(payload, context) {
    const result = cloneObject(payload);
    if (!context || typeof context !== 'object') return result;
    let parentGenerationId;
    try { parentGenerationId = safeGenerationId(context.parentGenerationId); } catch (_) { return result; }
    const operation = oneOf(context.operation, OPERATIONS);
    if (!operation) return result;
    result.parentGenerationId = parentGenerationId;
    if (context.parentArtifactId) {
      try { result.parentArtifactId = safeGenerationId(context.parentArtifactId); } catch (_) {}
    }
    result.operation = operation;
    return result;
  }

  function errorStatus(error) {
    return Number(error && (error.status || error.code)) || 0;
  }

  function libraryErrorMessage(error, action) {
    const status = errorStatus(error);
    if (status === 404) return '当前电脑端版本不支持作品库，现有生成面板仍可继续使用。';
    if (status === 401 || status === 403) return `${action || '读取作品库'}需要 RPG Token，或当前 Token 无效。`;
    if (status === 503) return '电脑端尚未配置 RPG Token；请先检查 Easy Panel 启动配置。';
    if (error && error.name === 'AbortError') return `${action || '读取作品库'}已取消。`;
    if (error && error.message) return `${action || '读取作品库'}失败：${error.message}`;
    return `${action || '读取作品库'}失败，请检查电脑端服务和网络。`;
  }

  async function requestJson(path, token, fetchImpl) {
    const fetcher = fetchImpl || global.fetch;
    if (typeof fetcher !== 'function') throw new Error('当前浏览器不支持网络请求。');
    const headers = {};
    if (asText(token)) headers['X-RPG-Token'] = asText(token);
    const response = await fetcher(path, { method: 'GET', credentials: 'same-origin', headers });
    let data = {};
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) {
      const error = new Error(asText(data && data.error) || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function requestBlob(path, token, fetchImpl) {
    const fetcher = fetchImpl || global.fetch;
    if (typeof fetcher !== 'function') throw new Error('当前浏览器不支持网络请求。');
    const headers = {};
    if (asText(token)) headers['X-RPG-Token'] = asText(token);
    const response = await fetcher(path, { method: 'GET', credentials: 'same-origin', headers });
    if (!response.ok) {
      const error = new Error(`HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return response.blob();
  }

  const testApi = {
    OPERATIONS,
    STATUSES,
    artifactPath,
    buildListQuery,
    clampInteger,
    errorStatus,
    libraryErrorMessage,
    nextSeed,
    payloadFromDetail,
    attachPendingDerivationToPayload,
    derivationOperationForRestore,
    requestBlob,
    requestJson,
    pendingDerivationContextForDetail,
    restorePayloadForForm,
    safeGenerationId,
    safeLibraryImagePath,
    safeOutputFilename,
    safeOutputSubfolder,
  };

  global.EasyPanelCreativeLibrary = testApi;
  if (typeof module !== 'undefined' && module.exports) module.exports = testApi;

  if (!global.document) return;

  const state = {
    token: '',
    offset: 0,
    total: 0,
    hasMore: false,
    items: [],
    detail: null,
    lineage: null,
    loading: false,
    requestNumber: 0,
    imageUrls: new Map(),
    lastFocus: null,
    filters: {
      operation: '', status: '', model: '', sort: 'created_at', order: 'desc',
    },
  };

  function byId(id) {
    return global.document.getElementById(id);
  }

  function setText(id, value) {
    const node = byId(id);
    if (node) node.textContent = asText(value);
    return node;
  }

  function createElement(tag, className, text) {
    const node = global.document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = asText(text);
    return node;
  }

  function operationLabel(value) {
    return {
      txt2img: '文生图', seed_variant: '换 Seed', img2img: '图生图', inpaint: '局部重绘',
      face_fix: '修脸', hand_fix: '修手', upscale: '放大', outfit_change: '换服装',
      scene_change: '换场景', style_change: '换风格', unknown: '未知操作',
    }[asText(value)] || '未知操作';
  }

  function statusLabel(value) {
    return {
      queued: '排队中', running: '生成中', completed: '已完成', error: '失败',
      cancelled: '已取消', unknown: '未知状态',
    }[asText(value)] || '状态未知';
  }

  function formatTime(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) return '未知时间';
    try { return new Date(number).toLocaleString(); } catch (_) { return '未知时间'; }
  }

  function imageKeyForThumbnail(id) {
    return `thumb:${id}`;
  }

  function imageKeyForArtifact(id) {
    return `artifact:${id}`;
  }

  function canCreateObjectUrl() {
    return typeof global.URL !== 'undefined' && typeof global.URL.createObjectURL === 'function';
  }

  function clearImageUrls() {
    if (global.URL && typeof global.URL.revokeObjectURL === 'function') {
      state.imageUrls.forEach((url) => global.URL.revokeObjectURL(url));
    }
    state.imageUrls.clear();
  }

  function showAuth(show) {
    const form = byId('creativeLibraryAuth');
    if (form) form.hidden = !show;
  }

  function showNotice(message, kind) {
    const node = byId('creativeLibraryNotice');
    if (!node) return;
    node.textContent = asText(message);
    node.className = `creative-library-notice${kind ? ` ${kind}` : ''}`;
  }

  function showListView() {
    const list = byId('creativeLibraryListView');
    const detail = byId('creativeLibraryDetailView');
    if (list) list.hidden = false;
    if (detail) detail.hidden = true;
  }

  function showDetailView() {
    const list = byId('creativeLibraryListView');
    const detail = byId('creativeLibraryDetailView');
    if (list) list.hidden = true;
    if (detail) detail.hidden = false;
  }

  function appendMeta(parent, label, value) {
    const row = createElement('div', 'creative-library-meta-row');
    row.append(createElement('span', 'creative-library-meta-label', label));
    row.append(createElement('span', 'creative-library-meta-value', value || '—'));
    parent.append(row);
  }

  function appendLineageMarker(parent, item) {
    const markers = [];
    if (Number(item && item.parent_count) > 0) markers.push(`父 ${Number(item.parent_count)}`);
    if (Number(item && item.child_count) > 0) markers.push(`子 ${Number(item.child_count)}`);
    parent.append(createElement('span', 'creative-library-marker', markers.length ? markers.join(' / ') : '无父子记录'));
  }

  function appendThumbnail(parent, item) {
    const source = state.imageUrls.get(imageKeyForThumbnail(item.generation_id));
    if (source) {
      const image = createElement('img');
      image.src = source;
      image.alt = `${asText(item.model) || '作品'} 缩略图`;
      image.loading = 'lazy';
      parent.append(image);
    } else {
      parent.append(createElement('span', 'creative-library-thumb-placeholder', '作品'));
    }
  }

  function renderList() {
    const root = byId('creativeLibraryList');
    if (!root) return;
    root.replaceChildren();
    if (state.loading) {
      root.append(createElement('p', 'creative-library-loading', '正在读取作品库…'));
      return;
    }
    if (!state.items.length) {
      root.append(createElement('div', 'creative-library-empty', '暂无符合条件的作品记录。'));
      return;
    }
    state.items.forEach((item) => {
      const button = createElement('button', 'creative-library-item');
      button.type = 'button';
      button.dataset.generationId = safeGenerationId(item.generation_id);
      button.addEventListener('click', () => { void openDetail(button.dataset.generationId); });
      const thumb = createElement('span', 'creative-library-thumb');
      appendThumbnail(thumb, item);
      const copy = createElement('span', 'creative-library-item-copy');
      const heading = createElement('span', 'creative-library-item-heading');
      heading.append(createElement('strong', '', asText(item.model) || '自动模型'));
      heading.append(createElement('small', '', formatTime(item.created_at)));
      const operation = createElement('span', 'creative-library-item-operation', `${operationLabel(item.operation)} · ${statusLabel(item.status)}`);
      const details = createElement('span', 'creative-library-item-details', `seed ${item.seed == null ? '?' : item.seed} · ${item.width || '?'}×${item.height || '?'}`);
      const markers = createElement('span', 'creative-library-item-markers');
      appendLineageMarker(markers, item);
      copy.append(heading, operation, details, markers);
      button.append(thumb, copy);
      root.append(button);
    });
  }

  function renderPagination() {
    const nav = byId('creativeLibraryPagination');
    const previous = byId('creativeLibraryPrevious');
    const next = byId('creativeLibraryNext');
    const pageInfo = byId('creativeLibraryPageInfo');
    const visible = state.total > 0 || state.offset > 0;
    if (nav) nav.hidden = !visible;
    if (previous) previous.disabled = state.offset <= 0 || state.loading;
    if (next) next.disabled = !state.hasMore || state.loading;
    const first = state.total ? state.offset + 1 : 0;
    const last = Math.min(state.total, state.offset + state.items.length);
    if (pageInfo) pageInfo.textContent = state.total ? `${first}–${last} / ${state.total}` : '0 / 0';
  }

  function filterValues() {
    return {
      operation: byId('creativeLibraryOperation')?.value || '',
      status: byId('creativeLibraryStatus')?.value || '',
      model: byId('creativeLibraryModel')?.value || '',
      sort: byId('creativeLibrarySort')?.value || 'created_at',
      order: byId('creativeLibraryOrder')?.value || 'desc',
    };
  }

  function detailFromResponse(data) {
    return data && data.generation && typeof data.generation === 'object' && !Array.isArray(data.generation)
      ? data.generation : null;
  }

  function lineageFromResponse(data) {
    return data && data.lineage && typeof data.lineage === 'object' && !Array.isArray(data.lineage)
      ? data.lineage : null;
  }

  async function loadImage(path, key, requestNumber) {
    if (!canCreateObjectUrl()) return;
    const safePath = safeLibraryImagePath(path);
    if (!safePath) return;
    try {
      const blob = await requestBlob(safePath, state.token);
      if (requestNumber !== state.requestNumber) return;
      const source = global.URL.createObjectURL(blob);
      const previous = state.imageUrls.get(key);
      if (previous && global.URL.revokeObjectURL) global.URL.revokeObjectURL(previous);
      state.imageUrls.set(key, source);
    } catch (_) {
      // A missing output should leave a usable metadata-only card.
    }
  }

  async function loadListThumbnails(items, requestNumber) {
    if (!canCreateObjectUrl()) return;
    await Promise.all(items.map((item) => loadImage(item.thumbnail_url, imageKeyForThumbnail(item.generation_id), requestNumber)));
    if (requestNumber === state.requestNumber) renderList();
  }

  function responseItems(data) {
    if (!data || !Array.isArray(data.items)) return [];
    return data.items.filter((item) => {
      try { safeGenerationId(item && item.generation_id); return true; } catch (_) { return false; }
    });
  }

  async function loadList() {
    const requestNumber = ++state.requestNumber;
    state.loading = true;
    state.detail = null;
    state.lineage = null;
    showListView();
    showNotice('正在读取电脑端作品库…');
    showAuth(false);
    renderList();
    renderPagination();
    clearImageUrls();
    try {
      const query = buildListQuery({ ...state.filters, limit: PAGE_SIZE, offset: state.offset });
      const data = await requestJson(`/api/rpg/library/generations?${query}`, state.token);
      if (requestNumber !== state.requestNumber) return;
      state.items = responseItems(data);
      state.total = clampInteger(data && data.total, state.items.length, 0, MAX_OFFSET);
      state.hasMore = Boolean(data && data.has_more);
      state.loading = false;
      showNotice(state.items.length ? `已读取 ${state.items.length} 条作品。` : '电脑端暂无符合条件的作品。', 'success');
      renderList();
      renderPagination();
      void loadListThumbnails(state.items, requestNumber);
    } catch (error) {
      if (requestNumber !== state.requestNumber) return;
      state.loading = false;
      state.items = [];
      state.total = 0;
      state.hasMore = false;
      showNotice(libraryErrorMessage(error, '读取作品库'), errorStatus(error) === 404 ? 'warning' : 'error');
      showAuth(errorStatus(error) === 401 || errorStatus(error) === 403);
      renderList();
      renderPagination();
    }
  }

  function appendSafeImageLink(parent, source, label, className) {
    if (!source) return null;
    const link = createElement('a', className || 'creative-library-image-link', label);
    link.href = source;
    link.target = '_blank';
    link.rel = 'noreferrer';
    link.addEventListener('click', (event) => {
      const viewer = global.openLinkedImageViewer;
      if (typeof viewer === 'function') {
        const result = viewer(event, link);
        if (result === false) return;
      }
    });
    parent.append(link);
    return link;
  }

  function appendOutputSection(parent, detail) {
    const section = createElement('section', 'creative-library-detail-section');
    section.append(createElement('h3', '', '输出文件'));
    const outputs = Array.isArray(detail.artifacts) ? detail.artifacts : [];
    if (!outputs.length) {
      section.append(createElement('p', 'creative-library-muted', '暂无可用输出；缺失文件只显示记录，不会被提供，也不会改写源记录。'));
      parent.append(section);
      return;
    }
    const list = createElement('div', 'creative-library-output-list');
    outputs.forEach((artifact) => {
      const row = createElement('div', 'creative-library-output-row');
      const source = state.imageUrls.get(imageKeyForArtifact(artifact.artifact_id));
      const filename = `${asText(artifact.filename) || '未命名图片'}${artifact.exists === false ? '（文件缺失）' : ''}`;
      const name = createElement('span', 'creative-library-output-name', filename);
      row.append(name);
      if (source) appendSafeImageLink(row, source, '打开预览', 'creative-library-image-link snapshot-output');
      const download = createElement('button', 'secondary', '下载');
      download.type = 'button';
      download.disabled = !source || artifact.exists === false;
      download.addEventListener('click', () => { void downloadArtifact(artifact); });
      row.append(download);
      list.append(row);
    });
    section.append(list);
    parent.append(section);
  }

  function appendLineageSection(parent, detail, lineage) {
    const section = createElement('section', 'creative-library-detail-section');
    section.append(createElement('h3', '', '父 / 子谱系'));
    const summary = `父作品 ${Number(detail.parent_count) || 0} · 子作品 ${Number(detail.child_count) || 0}`;
    section.append(createElement('p', 'creative-library-muted', summary));
    const nodes = [];
    if (lineage && Array.isArray(lineage.ancestors)) {
      lineage.ancestors.forEach((item) => nodes.push(['父', item]));
    }
    if (lineage && Array.isArray(lineage.descendants)) {
      lineage.descendants.forEach((item) => nodes.push(['子', item]));
    }
    if (!nodes.length) {
      section.append(createElement('p', 'creative-library-muted', lineage ? '暂无已索引的父子作品。' : '当前服务端未提供谱系信息。'));
    } else {
      const list = createElement('div', 'creative-library-lineage-list');
      nodes.forEach(([kind, item]) => {
        const id = asText(item && item.generation_id);
        const label = `${kind} · ${id.slice(0, 12)}${id ? '…' : ''} · ${operationLabel(item && item.operation)} · ${asText(item && item.model) || '自动模型'}`;
        list.append(createElement('span', '', label));
      });
      section.append(list);
    }
    parent.append(section);
  }

  function appendLoraSection(parent, detail) {
    const section = createElement('section', 'creative-library-detail-section');
    section.append(createElement('h3', '', 'LoRA'));
    const loras = Array.isArray(detail.loras) ? detail.loras : [];
    if (!loras.length) section.append(createElement('p', 'creative-library-muted', '本次记录没有 LoRA。'));
    else {
      const list = createElement('div', 'creative-library-lora-list');
      loras.forEach((lora) => {
        const weight = lora.weight == null ? '' : ` × ${lora.weight}`;
        const role = asText(lora.role) && asText(lora.role) !== 'other' ? ` · ${lora.role}` : '';
        list.append(createElement('span', '', `${asText(lora.name) || '未命名 LoRA'}${weight}${role}`));
      });
      section.append(list);
    }
    parent.append(section);
  }

  function promptValue(detail) {
    const replay = detail && detail.replay && typeof detail.replay.payload === 'object' ? detail.replay.payload : {};
    const input = detail && detail.input && typeof detail.input === 'object' ? detail.input : {};
    const value = replay.prompt || replay.positive || input.prompt || input.positive;
    if (value) return value;
    const sections = replay.promptSections || input.promptSections;
    if (!sections || typeof sections !== 'object' || Array.isArray(sections)) return '（没有记录提示词）';
    return Object.values(sections).filter((item) => asText(item)).map((item) => asText(item)).join(', ') || '（没有记录提示词）';
  }

  function appendPromptSection(parent, detail) {
    const section = createElement('section', 'creative-library-detail-section');
    section.append(createElement('h3', '', '提示词预览'));
    section.append(createElement('pre', 'creative-library-prompt', promptValue(detail)));
    section.append(createElement('p', 'creative-library-muted', '只读预览；恢复操作只填入当前表单。'));
    parent.append(section);
  }

  function renderDetail() {
    const root = byId('creativeLibraryDetail');
    const detail = state.detail;
    if (!root || !detail) return;
    root.replaceChildren();
    const summary = createElement('div', 'creative-library-detail-summary');
    const preview = createElement('div', 'creative-library-detail-preview');
    const firstArtifact = Array.isArray(detail.artifacts) ? detail.artifacts[0] : null;
    const previewSource = firstArtifact && state.imageUrls.get(imageKeyForArtifact(firstArtifact.artifact_id));
    const thumbSource = state.imageUrls.get(imageKeyForThumbnail(detail.generation_id));
    const source = previewSource || thumbSource;
    if (source) {
      const link = appendSafeImageLink(preview, source, '打开大图', 'creative-library-preview-link snapshot-output');
      const image = createElement('img');
      image.src = source;
      image.alt = `${asText(detail.model) || '作品'} 预览`;
      if (link) link.replaceChildren(image);
    } else preview.append(createElement('span', 'creative-library-thumb-placeholder', '暂无预览'));
    const copy = createElement('div', 'creative-library-detail-copy');
    copy.append(createElement('h3', '', asText(detail.model) || '自动模型'));
    appendMeta(copy, '操作 / 状态', `${operationLabel(detail.operation)} · ${statusLabel(detail.status)}`);
    appendMeta(copy, '时间', formatTime(detail.created_at));
    appendMeta(copy, 'Seed', detail.seed == null ? '?' : detail.seed);
    appendMeta(copy, '尺寸 / 质量', `${detail.width || '?'}×${detail.height || '?'} · ${asText(detail.quality) || '自定义'}`);
    appendMeta(copy, '作品 ID', detail.generation_id);
    summary.append(preview, copy);
    root.append(summary);

    const actions = createElement('div', 'creative-library-actions');
    const reproduce = createElement('button', 'primary', '复现到当前表单');
    reproduce.type = 'button';
    reproduce.addEventListener('click', () => restoreToForm('reproduce'));
    const seedVariant = createElement('button', 'secondary', '换 Seed 到当前表单');
    seedVariant.type = 'button';
    seedVariant.addEventListener('click', () => restoreToForm('seed-variant'));
    const continueEdit = createElement('button', 'secondary', '继续编辑');
    continueEdit.type = 'button';
    continueEdit.addEventListener('click', () => restoreToForm('continue-edit'));
    actions.append(reproduce, seedVariant, continueEdit);
    root.append(actions);
    root.append(createElement('p', 'creative-library-safe-note', '这些操作只恢复参数，不会自动提交任务；请确认后手动点击“生成图片”。'));
    appendLineageSection(root, detail, state.lineage);
    appendLoraSection(root, detail);
    appendOutputSection(root, detail);
    appendPromptSection(root, detail);
  }

  async function loadDetailImages(detail, requestNumber) {
    const artifacts = Array.isArray(detail.artifacts) ? detail.artifacts : [];
    const jobs = [];
    const thumbnailPath = detail.thumbnail_url;
    if (thumbnailPath) jobs.push(loadImage(thumbnailPath, imageKeyForThumbnail(detail.generation_id), requestNumber));
    artifacts.forEach((artifact) => {
      if (artifact.exists === false) return;
      jobs.push(loadImage(artifactPath(artifact), imageKeyForArtifact(artifact.artifact_id), requestNumber));
    });
    await Promise.all(jobs);
    if (requestNumber === state.requestNumber) renderDetail();
  }

  async function openDetail(id) {
    let generationId;
    try { generationId = safeGenerationId(id); } catch (error) {
      showNotice(error.message, 'error');
      return;
    }
    const requestNumber = ++state.requestNumber;
    state.loading = true;
    state.detail = null;
    state.lineage = null;
    showDetailView();
    showNotice('正在读取作品详情…');
    showAuth(false);
    setText('creativeLibraryDetailStatus', '读取中…');
    const root = byId('creativeLibraryDetail');
    if (root) root.replaceChildren(createElement('p', 'creative-library-loading', '正在读取作品详情…'));
    try {
      const data = await requestJson(`/api/rpg/library/generations/${generationId}`, state.token);
      if (requestNumber !== state.requestNumber) return;
      const detail = detailFromResponse(data);
      if (!detail) throw new Error('电脑端返回的作品详情格式无效。');
      state.detail = detail;
      state.loading = false;
      setText('creativeLibraryDetailStatus', `${operationLabel(detail.operation)} · ${statusLabel(detail.status)}`);
      showNotice('详情已加载；恢复后请确认参数，再手动生成。', 'success');
      renderDetail();
      try {
        const lineageData = await requestJson(`/api/rpg/library/generations/${generationId}/lineage`, state.token);
        if (requestNumber === state.requestNumber) state.lineage = lineageFromResponse(lineageData);
      } catch (lineageError) {
        if (requestNumber === state.requestNumber && errorStatus(lineageError) !== 401 && errorStatus(lineageError) !== 403) {
          state.lineage = null;
        }
      }
      if (requestNumber === state.requestNumber) renderDetail();
      await loadDetailImages(detail, requestNumber);
    } catch (error) {
      if (requestNumber !== state.requestNumber) return;
      state.loading = false;
      state.detail = null;
      state.lineage = null;
      setText('creativeLibraryDetailStatus', '读取失败');
      showNotice(libraryErrorMessage(error, '读取作品详情'), errorStatus(error) === 404 ? 'warning' : 'error');
      showAuth(errorStatus(error) === 401 || errorStatus(error) === 403);
      if (root) root.replaceChildren(createElement('p', 'creative-library-muted', '无法显示该作品详情；可以返回列表继续使用现有面板。'));
    }
  }

  function downloadArtifact(artifact) {
    const source = state.imageUrls.get(imageKeyForArtifact(artifact && artifact.artifact_id));
    if (!source || !artifact || artifact.exists === false) return;
    const filename = safeOutputFilename(artifact.filename) || 'easy-panel-library.png';
    const link = createElement('a');
    link.href = source;
    link.download = filename;
    link.rel = 'noreferrer';
    global.document.body.append(link);
    link.click();
    link.remove();
    showNotice(`已开始下载：${filename}`, 'success');
  }

  function restoreToForm(mode) {
    if (!state.detail) return;
    const restore = global.restorePayloadToPanel;
    if (typeof restore !== 'function') {
      showNotice('当前页面缺少表单恢复能力，请刷新电脑端页面后重试。', 'error');
      return;
    }
    try {
      const payload = restorePayloadForForm(state.detail, mode === 'seed-variant' ? 'seed-variant' : 'reproduce');
      const derivation = pendingDerivationContextForDetail(state.detail, mode);
      if (!derivation) throw new Error('作品缺少安全的作品编号，无法建立派生关联。');
      restore(payload);
      if (typeof global.setPendingDerivationContext === 'function') {
        global.setPendingDerivationContext(derivation);
      }
      const status = byId('status');
      const relationHint = `将从作品 ${derivation.parentGenerationId.slice(0, 10)}… 派生（${operationLabel(derivation.operation)}）；未自动选择输出图，可取消关联。`;
      if (status) status.textContent = mode === 'seed-variant'
        ? `作品参数和新 Seed 已恢复到面板；${relationHint} 请确认后手动点击“生成图片”。`
        : `作品参数已恢复到面板；${relationHint} 请确认后手动点击“生成图片”。`;
      closeDialog();
      if (mode === 'continue-edit') {
        if (typeof global.jumpToPanelSection === 'function') global.jumpToPanelSection('promptComposer');
        global.setTimeout(() => {
          const target = byId('compiledPositive') || byId('promptSubject');
          if (target && typeof target.focus === 'function') target.focus();
        }, 0);
      }
    } catch (error) {
      showNotice(libraryErrorMessage(error, '恢复作品参数'), 'error');
    }
  }

  function closeDialog() {
    const dialog = byId('creativeLibraryDialog');
    if (dialog && dialog.open && typeof dialog.close === 'function') dialog.close();
    else if (dialog) dialog.removeAttribute('open');
  }

  function cleanupAfterClose() {
    state.requestNumber += 1;
    state.loading = false;
    state.detail = null;
    state.lineage = null;
    state.token = '';
    const token = byId('creativeLibraryToken');
    if (token) token.value = '';
    clearImageUrls();
    state.lastFocus?.focus?.();
    state.lastFocus = null;
  }

  function openDialog() {
    const dialog = byId('creativeLibraryDialog');
    if (!dialog) return;
    state.lastFocus = global.document.activeElement;
    state.offset = 0;
    state.filters = filterValues();
    showListView();
    if (!dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    }
    void loadList();
  }

  function submitAuth(event) {
    event.preventDefault();
    state.token = asText(byId('creativeLibraryToken')?.value);
    state.offset = 0;
    void loadList();
  }

  function applyFilters(event) {
    event.preventDefault();
    state.filters = filterValues();
    state.offset = 0;
    void loadList();
  }

  function goPrevious() {
    if (state.loading || state.offset <= 0) return;
    state.offset = Math.max(0, state.offset - PAGE_SIZE);
    void loadList();
  }

  function goNext() {
    if (state.loading || !state.hasMore) return;
    state.offset += PAGE_SIZE;
    void loadList();
  }

  function backToList() {
    state.detail = null;
    state.lineage = null;
    showListView();
    showNotice(state.items.length ? '已返回作品列表。' : '作品列表为空。', state.items.length ? 'success' : '');
    renderList();
    renderPagination();
  }

  function init() {
    if (!byId('creativeLibraryDialog')) return;
    byId('creativeLibraryOpen')?.addEventListener('click', openDialog);
    byId('creativeLibraryClose')?.addEventListener('click', closeDialog);
    byId('creativeLibraryRefresh')?.addEventListener('click', () => { state.offset = 0; void loadList(); });
    byId('creativeLibraryAuth')?.addEventListener('submit', submitAuth);
    byId('creativeLibraryFilters')?.addEventListener('submit', applyFilters);
    byId('creativeLibraryPrevious')?.addEventListener('click', goPrevious);
    byId('creativeLibraryNext')?.addEventListener('click', goNext);
    byId('creativeLibraryBack')?.addEventListener('click', backToList);
    byId('creativeLibraryDialog')?.addEventListener('close', cleanupAfterClose);
    global.openCreativeLibrary = openDialog;
    global.closeCreativeLibrary = closeDialog;
  }

  if (global.document.readyState === 'loading') global.document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
}(typeof window !== 'undefined' ? window : globalThis));
