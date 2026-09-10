/* 作品项目：把「一张一张生图」整理成「做一个角色作品」。
 * 项目 = 分区（基准角色 / 日常服装 / 战斗服装 / 废墟场景 / 夜景 / 最终精选…）
 *      + 项目内作品（可移入分区、设为封面、一键打开）
 *      + 关联资源（LoRA / Prompt 预设 / 单变量实验 / 收藏组）。 */
(function (global) {
  'use strict';

  var DIALOG_ID = 'projectWorkspaceDialog';
  var PICKER_ID = 'projectPickerDialog';
  var SECTION_HINT = '基准角色, 日常服装, 战斗服装, 废墟场景, 夜景, 最终精选';
  var state = { projects: [], detail: null, busy: false, notice: '', groups: [] };

  function byId(id) { return document.getElementById(id); }

  function asText(value) {
    return String(value == null ? '' : value).trim();
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function token() {
    var input = byId('creativeLibraryToken');
    return input ? asText(input.value) : '';
  }

  function requestHeaders(json) {
    var headers = {};
    var value = token();
    if (value) headers['X-RPG-Token'] = value;
    if (json) headers['Content-Type'] = 'application/json';
    return headers;
  }

  async function getJson(path) {
    var response = await fetch(path, { method: 'GET', credentials: 'same-origin', headers: requestHeaders(false) });
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok || data.error) throw new Error(data.error || ('读取失败：' + response.status));
    return data || {};
  }

  async function postJson(path, body) {
    var response = await fetch(path, {
      method: 'POST', credentials: 'same-origin',
      headers: requestHeaders(true), body: JSON.stringify(body || {}),
    });
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok || data.error) throw new Error(data.error || ('保存失败：' + response.status));
    return data || {};
  }

  function setNotice(message, kind) {
    state.notice = message || '';
    var node = byId('projectNotice');
    if (node) {
      node.textContent = state.notice;
      node.className = 'small' + (kind ? ' project-notice-' + kind : '');
    }
  }

  function thumbUrl(item) {
    var generation = (item && item.generation) || {};
    return asText(generation.thumbnail_url);
  }

  function imageTag(item, className) {
    var url = thumbUrl(item);
    var generation = (item && item.generation) || {};
    var label = asText(generation.model) + ' · ' + asText(generation.seed);
    if (!url) return '<div class="' + className + ' project-thumb-empty">无图</div>';
    return '<img class="' + className + '" loading="lazy" data-rpg-src="' + escapeHtml(url)
      + '" alt="' + escapeHtml(label) + '" title="' + escapeHtml(label) + '">';
  }

  async function loadThumbnails(root) {
    var scope = root || document;
    var images = scope.querySelectorAll('img[data-rpg-src]');
    for (var index = 0; index < images.length; index += 1) {
      var image = images[index];
      var source = asText(image.dataset.rpgSrc);
      if (!source || image.dataset.rpgLoaded) continue;
      image.dataset.rpgLoaded = '1';
      try {
        var response = await fetch(source, { credentials: 'same-origin', headers: requestHeaders(false) });
        if (!response.ok) continue;
        image.src = URL.createObjectURL(await response.blob());
      } catch (error) { /* 单张缩略图失败不影响项目视图 */ }
    }
  }

  /* --------------------------------------------------------------- 渲染 */
  function renderList() {
    var box = byId('projectList');
    if (!box) return;
    if (!state.projects.length) {
      box.innerHTML = '<div class="small muted">还没有项目。点“＋ 新建”建立第一个角色作品，例如「Luna 角色图集」。</div>';
      return;
    }
    box.innerHTML = state.projects.map(function (project) {
      var active = state.detail && state.detail.project
        && state.detail.project.project_id === project.project_id ? ' active' : '';
      return '<button type="button" class="project-list-item' + active + '" data-project="'
        + escapeHtml(project.project_id) + '">'
        + (project.cover_url
          ? '<img class="project-list-cover" loading="lazy" alt="" data-rpg-src="'
            + escapeHtml(project.cover_url) + '">'
          : '<span class="project-list-cover project-thumb-empty"></span>')
        + '<span class="project-list-text"><b>' + escapeHtml(project.name) + '</b>'
        + '<span class="small">' + (project.item_count || 0) + ' 件作品</span></span></button>';
    }).join('');
  }

  function renderItem(project, section, item) {
    var generation = item.generation || {};
    var options = (project.sections || []).concat(['']).map(function (name) {
      var label = name || '（未分组）';
      return '<option value="' + escapeHtml(name) + '"' + (name === item.section ? ' selected' : '') + '>'
        + escapeHtml(label) + '</option>';
    }).join('');
    return '<div class="project-item" data-item="' + escapeHtml(item.item_id) + '">'
      + '<button type="button" class="project-item-open" data-open="' + escapeHtml(generation.generation_id || '')
      + '" title="在作品库里打开">' + imageTag(item, 'project-thumb') + '</button>'
      + '<div class="project-item-meta"><span class="small">' + escapeHtml(asText(generation.model))
      + ' · seed ' + escapeHtml(asText(generation.seed)) + '</span>'
      + '<select class="project-item-section" data-move="' + escapeHtml(item.item_id) + '">' + options + '</select>'
      + '<div class="actions"><button type="button" class="secondary" data-cover="'
      + escapeHtml(generation.generation_id || '') + '">设为封面</button>'
      + '<button type="button" class="secondary" data-remove="' + escapeHtml(item.item_id) + '">移出</button></div></div>'
      + '</div>';
  }

  function renderDetail() {
    var root = byId('projectDetail');
    if (!root) return;
    var detail = state.detail;
    if (!detail || !detail.project) {
      root.innerHTML = '<div class="small muted">选择左侧项目查看分区与作品；或新建一个项目。</div>';
      return;
    }
    var project = detail.project;
    var links = detail.links || {};
    var sectionsHtml = (detail.sections || []).map(function (entry) {
      var name = entry.name || '（未分组）';
      var items = entry.items || [];
      return '<section class="project-section"><div class="project-section-heading"><b>' + escapeHtml(name)
        + '</b><span class="small">' + items.length + ' 件</span></div>'
        + (items.length
          ? '<div class="project-items">' + items.map(function (item) { return renderItem(project, entry.name, item); }).join('') + '</div>'
          : '<div class="small muted">这个分区还是空的。</div>')
        + '</section>';
    }).join('');
    var linkHtml = ['lora', 'preset', 'experiment', 'favorite_group'].map(function (kind) {
      var labels = { lora: 'LoRA', preset: 'Prompt 预设', experiment: '单变量实验', favorite_group: '收藏组' };
      var rows = (links[kind] || []).map(function (link) {
        return '<span class="tag">' + escapeHtml(link.label || link.ref)
          + ' <a href="#" data-unlink="' + escapeHtml(link.link_id) + '">×</a></span>';
      }).join(' ');
      return '<div class="project-link-row"><span class="small">' + labels[kind] + '</span>'
        + (rows || '<span class="small muted">未关联</span>') + '</div>';
    }).join('');
    root.innerHTML = ''
      + '<div class="project-detail-heading"><div><b>' + escapeHtml(project.name) + '</b>'
      + '<div class="small">' + (detail.total || 0) + ' 件作品 · 分区 ' + (project.sections || []).length + ' 个</div></div>'
      + '<div class="actions"><button type="button" class="secondary" id="projectRenameBtn">改名</button>'
      + '<button type="button" class="secondary" id="projectSectionsBtn" title="' + escapeHtml(SECTION_HINT) + '">编辑分区</button>'
      + '<button type="button" class="secondary" id="projectAddSectionBtn">＋ 分区</button>'
      + '<button type="button" class="danger" id="projectDeleteBtn">删除项目</button>'
      + '<button type="button" class="secondary" id="projectLinkBtn">关联资源</button></div></div>'
      + '<div class="project-links">' + linkHtml + '</div>'
      + sectionsHtml;
  }

  function render() {
    renderList();
    renderDetail();
    void loadThumbnails(document.getElementById(DIALOG_ID));
  }

  /* --------------------------------------------------------------- 数据 */
  async function loadProjects(projectId) {
    if (state.busy) return;
    state.busy = true;
    try {
      var data = await getJson('/api/rpg/library/projects');
      state.projects = data.items || [];
      render();
      var wanted = projectId || (state.detail && state.detail.project && state.detail.project.project_id);
      if (wanted) {
        await openProject(wanted);
      } else if (state.projects.length) {
        await openProject(state.projects[0].project_id);
      } else {
        state.detail = null;
        renderDetail();
      }
    } catch (error) {
      setNotice(error.message, 'error');
    } finally {
      state.busy = false;
    }
  }

  async function openProject(projectId) {
    try {
      state.detail = await getJson('/api/rpg/library/projects/' + projectId);
      render();
    } catch (error) {
      setNotice(error.message, 'error');
    }
  }

  async function projectAction(body, message) {
    var result = await postJson('/api/rpg/library/projects', body);
    setNotice(message || result.message || '已保存。', 'success');
    return result;
  }

  async function createProject() {
    var name = asText(global.prompt('项目名称（例如：Luna 角色图集）', ''));
    if (!name) return;
    try {
      var sectionsText = asText(global.prompt('分区（逗号分隔，可留空使用默认）', SECTION_HINT)) || '';
      var sections = sectionsText ? sectionsText.split(/[,，]/).map(asText).filter(Boolean) : null;
      var result = await projectAction({ action: 'create', name: name, sections: sections }, '项目已创建。');
      if (result.project) await loadProjects(result.project.project_id);
    } catch (error) {
      setNotice(error.message, 'error');
    }
  }

  async function renameProject() {
    var detail = state.detail;
    if (!detail || !detail.project) return;
    var name = asText(global.prompt('新的项目名称', detail.project.name));
    if (!name || name === detail.project.name) return;
    try {
      await projectAction({ action: 'update', project_id: detail.project.project_id, name: name }, '项目已改名。');
      await loadProjects(detail.project.project_id);
    } catch (error) {
      setNotice(error.message, 'error');
    }
  }

  async function editSections() {
    var detail = state.detail;
    if (!detail || !detail.project) return;
    var text = asText(global.prompt('分区（逗号分隔，顺序即显示顺序）', (detail.project.sections || []).join(', ')));
    if (!text) return;
    var sections = text.split(/[,，]/).map(asText).filter(Boolean);
    try {
      await projectAction({ action: 'update', project_id: detail.project.project_id, sections: sections }, '分区已更新。');
      await loadProjects(detail.project.project_id);
    } catch (error) {
      setNotice(error.message, 'error');
    }
  }

  async function addSection() {
    var detail = state.detail;
    if (!detail || !detail.project) return;
    var name = asText(global.prompt('新增分区名称', ''));
    if (!name) return;
    try {
      var sections = (detail.project.sections || []).concat([name]);
      await projectAction({ action: 'update', project_id: detail.project.project_id, sections: sections }, '分区已新增。');
      await loadProjects(detail.project.project_id);
    } catch (error) {
      setNotice(error.message, 'error');
    }
  }

  async function deleteProject() {
    var detail = state.detail;
    if (!detail || !detail.project) return;
    if (!global.confirm('删除项目「' + detail.project.name + '」？项目里的作品不会被删除。')) return;
    try {
      await projectAction({ action: 'delete', project_id: detail.project.project_id }, '项目已删除。');
      state.detail = null;
      await loadProjects();
    } catch (error) {
      setNotice(error.message, 'error');
    }
  }

  async function moveItem(itemId, section) {
    var detail = state.detail;
    if (!detail || !detail.project) return;
    try {
      await projectAction({ action: 'update-item', project_id: detail.project.project_id, item_id: itemId, section: section },
        section ? '已移入「' + section + '」。' : '已移出分区。');
      await openProject(detail.project.project_id);
    } catch (error) {
      setNotice(error.message, 'error');
    }
  }

  async function removeItem(itemId) {
    var detail = state.detail;
    if (!detail || !detail.project) return;
    try {
      await projectAction({ action: 'remove-items', project_id: detail.project.project_id, item_ids: [itemId] }, '已移出项目。');
      await loadProjects(detail.project.project_id);
    } catch (error) {
      setNotice(error.message, 'error');
    }
  }

  async function setCover(generationId) {
    var detail = state.detail;
    if (!detail || !detail.project) return;
    try {
      await projectAction({ action: 'set-cover', project_id: detail.project.project_id, generation_id: generationId }, '封面已更新。');
      await loadProjects(detail.project.project_id);
    } catch (error) {
      setNotice(error.message, 'error');
    }
  }

  function currentLoras() {
    try {
      if (typeof global.selectedLoraPayload === 'function') {
        return (global.selectedLoraPayload() || []).map(function (item) { return asText(item.name); }).filter(Boolean);
      }
    } catch (error) { /* 忽略：仅用于关联 */ }
    return [];
  }

  function currentPresetName() {
    var select = document.querySelector('select[id^="userPromptPreset"], select[id*="PromptPreset"]');
    if (!select) return '';
    var option = select.selectedOptions && select.selectedOptions[0];
    return asText(option ? option.textContent : '');
  }

  async function addLink() {
    var detail = state.detail;
    if (!detail || !detail.project) return;
    var kind = asText(global.prompt('关联类型：lora / preset / experiment / favorite_group', 'lora')).toLowerCase();
    if (['lora', 'preset', 'experiment', 'favorite_group'].indexOf(kind) < 0) {
      setNotice('关联类型只能是 lora / preset / experiment / favorite_group。', 'error');
      return;
    }
    var suggestion = '';
    if (kind === 'lora') suggestion = currentLoras().join(', ');
    else if (kind === 'preset') suggestion = currentPresetName();
    else if (kind === 'experiment') {
      var snapshot = global.__taskControl && global.__taskControl.state ? global.__taskControl.state.snapshot : null;
      var first = snapshot && snapshot.items ? snapshot.items.find(function (item) { return item.experiment; }) : null;
      suggestion = first ? first.experiment : '';
    }
    var ref = asText(global.prompt('关联内容（' + kind + '）', suggestion));
    if (!ref) return;
    var label = asText(global.prompt('显示名（可留空）', suggestion)) || ref;
    try {
      var refs = kind === 'lora' ? ref.split(/[,，]/).map(asText).filter(Boolean) : [ref];
      for (var index = 0; index < refs.length; index += 1) {
        await projectAction({ action: 'add-link', project_id: detail.project.project_id, kind: kind, ref: refs[index], label: label },
          '已关联 ' + refs.length + ' 条资源。');
      }
      await openProject(detail.project.project_id);
    } catch (error) {
      setNotice(error.message, 'error');
    }
  }

  async function removeLink(linkId) {
    var detail = state.detail;
    if (!detail || !detail.project) return;
    try {
      await projectAction({ action: 'remove-link', project_id: detail.project.project_id, link_id: linkId }, '已取消关联。');
      await openProject(detail.project.project_id);
    } catch (error) {
      setNotice(error.message, 'error');
    }
  }

  async function pickerProjects() {
    var data = await getJson('/api/rpg/library/projects');
    state.projects = data.items || [];
    return state.projects;
  }

  async function openProjectPicker(generationId) {
    var wanted = asText(generationId);
    if (!wanted) return;
    var dialog = byId(PICKER_ID);
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = PICKER_ID;
      dialog.className = 'project-picker-dialog';
      dialog.innerHTML = ''
        + '<h3>加入作品项目</h3>'
        + '<label class="field-title"><span>项目</span></label>'
        + '<select id="projectPickerSelect"></select>'
        + '<label class="field-title"><span>分区</span></label>'
        + '<select id="projectPickerSection"></select>'
        + '<div class="actions"><button type="button" class="secondary" data-picker="cancel">取消</button>'
        + '<button type="button" class="primary" data-picker="add">加入项目</button></div>'
        + '<div id="projectPickerNotice" class="small"></div>';
      document.body.appendChild(dialog);
    }
    try {
      var projects = await pickerProjects();
      var select = byId('projectPickerSelect');
      select.innerHTML = projects.map(function (project) {
        return '<option value="' + escapeHtml(project.project_id) + '">' + escapeHtml(project.name)
          + '（' + (project.item_count || 0) + ' 件）</option>';
      }).join('');
      if (!projects.length) {
        byId('projectPickerNotice').textContent = '还没有项目：请先打开“作品项目”新建一个。';
      }
      renderPickerSections();
      select.onchange = renderPickerSections;
      dialog.showModal();
      return await new Promise(function (resolve) {
        dialog.addEventListener('click', async function handler(event) {
          var button = event.target.closest('button[data-picker]');
          if (!button) return;
          dialog.removeEventListener('click', handler);
          if (button.dataset.picker === 'cancel') {
            dialog.close();
            resolve({ added: false });
            return;
          }
          var projectId = asText(select.value);
          var section = asText(byId('projectPickerSection').value);
          if (!projectId) {
            byId('projectPickerNotice').textContent = '请先选择项目。';
            return;
          }
          try {
            var result = await postJson('/api/rpg/library/projects', {
              action: 'add-items', project_id: projectId, generation_ids: [wanted], section: section,
            });
            dialog.close();
            setNotice('已加入项目（' + (result.added || 0) + ' 件）。', 'success');
            if (isOpen()) await loadProjects(projectId);
            resolve({ added: true });
          } catch (error) {
            byId('projectPickerNotice').textContent = error.message;
          }
        });
      });
    } catch (error) {
      setNotice(error.message, 'error');
      return { added: false };
    }
  }

  function renderPickerSections() {
    var select = byId('projectPickerSelect');
    var sectionSelect = byId('projectPickerSection');
    if (!select || !sectionSelect) return;
    var project = state.projects.find(function (item) { return item.project_id === select.value; });
    var sections = (project && project.sections) || [];
    sectionSelect.innerHTML = ['<option value="">（未分组）</option>'].concat(sections.map(function (name) {
      return '<option value="' + escapeHtml(name) + '">' + escapeHtml(name) + '</option>';
    })).join('');
  }

  /* --------------------------------------------------------------- 对话框 */
  function dialog() {
    var found = byId(DIALOG_ID);
    if (found) return found;
    var element = document.createElement('dialog');
    element.id = DIALOG_ID;
    element.className = 'project-dialog';
    element.innerHTML = ''
      + '<div class="project-layout">'
      + '  <aside class="project-list-pane">'
      + '    <div class="project-list-heading"><b>作品项目</b>'
      + '    <span class="actions"><button type="button" class="secondary" id="projectCreateBtn">＋ 新建</button>'
      + '    <button type="button" class="secondary" id="projectRefreshBtn">刷新</button></span></div>'
      + '    <div id="projectList" class="project-list"></div>'
      + '    <div id="projectNotice" class="small"></div>'
      + '  </aside>'
      + '  <section class="project-detail-pane" id="projectDetail"></section>'
      + '</div>'
      + '<div class="actions project-dialog-actions"><button type="button" class="secondary" id="projectCloseBtn">关闭</button></div>';
    document.body.appendChild(element);
    element.addEventListener('click', onDialogClick);
    return element;
  }

  function isOpen() {
    var element = byId(DIALOG_ID);
    return Boolean(element && element.open);
  }

  function onDialogClick(event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var projectButton = target.closest('[data-project]');
    if (projectButton) {
      void openProject(projectButton.dataset.project);
      return;
    }
    var openButton = target.closest('[data-open]');
    if (openButton && openButton.dataset.open) {
      document.dispatchEvent(new CustomEvent('easy-panel:open-generation', { detail: { generationId: openButton.dataset.open } }));
      return;
    }
    var coverButton = target.closest('[data-cover]');
    if (coverButton) { void setCover(coverButton.dataset.cover); return; }
    var removeButton = target.closest('[data-remove]');
    if (removeButton) { void removeItem(removeButton.dataset.remove); return; }
    var unlink = target.closest('[data-unlink]');
    if (unlink) { event.preventDefault(); void removeLink(unlink.dataset.unlink); return; }
    var moveSelect = target.closest('[data-move]');
    if (moveSelect && target.tagName === 'SELECT') {
      void moveItem(moveSelect.dataset.move, asText(target.value));
      return;
    }
    if (target.id === 'projectCreateBtn') { void createProject(); return; }
    if (target.id === 'projectRefreshBtn') { void loadProjects(); return; }
    if (target.id === 'projectRenameBtn') { void renameProject(); return; }
    if (target.id === 'projectSectionsBtn') { void editSections(); return; }
    if (target.id === 'projectAddSectionBtn') { void addSection(); return; }
    if (target.id === 'projectDeleteBtn') { void deleteProject(); return; }
    if (target.id === 'projectLinkBtn') { void addLink(); return; }
    if (target.id === 'projectCloseBtn') { byId(DIALOG_ID).close(); }
  }

  function openProjectWorkspace() {
    var element = dialog();
    render();
    if (!element.open) element.showModal();
    void loadProjects().catch(function () { /* 已在内部提示 */ });
  }

  function init() {
    byId('projectWorkspaceOpen')?.addEventListener('click', openProjectWorkspace);
    global.openProjectWorkspace = openProjectWorkspace;
    global.openProjectPicker = openProjectPicker;
    global.__projectWorkspace = {
      open: openProjectWorkspace, picker: openProjectPicker, state: state,
      load: loadProjects, openProject: openProject, render: render,
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
