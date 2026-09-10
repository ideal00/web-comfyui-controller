/* 任务批处理控制：运行 / 暂停 / 取消当前 / 取消后续 / 只运行入选实验 / 清理失败任务
 * 以及提交前的重复任务检测（同模型 + 同 LoRA + 同提示词 + 同 seed + 同参数）。 */
(function (global) {
  'use strict';

  var DIALOG_ID = 'duplicateTaskDialog';
  var POLL_MS = 2000;
  var STATUS_LABELS = {
    pending: '排队中', running: '执行中', completed: '已完成',
    error: '失败', cancelled: '已取消', skipped: '已跳过',
  };
  var state = { snapshot: null, timer: 0, busy: false, pendingDuplicate: null };

  function $(id) { return document.getElementById(id); }

  function text(id, value) {
    var node = $(id);
    if (node) node.textContent = value;
  }

  function status(message) {
    var node = $('status');
    if (node) node.textContent = message;
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function json(path, options) {
    var response = await fetch(path, options);
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok || (data && data.error)) {
      throw new Error((data && data.error) || ('请求失败：' + response.status));
    }
    return data || {};
  }

  function post(path, body) {
    return json(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
  }

  /* ------------------------------------------------------------ 服务端队列 */
  async function refresh() {
    try {
      var snapshot = await json('/api/tasks');
      state.snapshot = snapshot;
      render(snapshot);
    } catch (error) {
      text('taskQueueNotice', '任务队列读取失败：' + error.message);
    }
  }

  function countsText(counts) {
    counts = counts || {};
    return ['排队中 ' + (counts.pending || 0), '执行中 ' + (counts.running || 0),
            '已完成 ' + (counts.completed || 0), '失败 ' + (counts.error || 0),
            '已取消 ' + (counts.cancelled || 0), '已跳过 ' + (counts.skipped || 0)].join(' · ');
  }

  function renderItem(item) {
    var badge = STATUS_LABELS[item.status] || item.status;
    var detail = [];
    if (item.experiment_value) detail.push(item.experiment_value);
    if (item.error) detail.push(item.error);
    var selected = item.selected !== false;
    return '<div class="task-item task-item-' + escapeHtml(item.status) + '">'
      + '<label class="task-item-check"><input type="checkbox" data-task-select="' + escapeHtml(item.id) + '"'
      + (selected ? ' checked' : '') + '><span class="task-item-label">' + escapeHtml(item.label) + '</span></label>'
      + '<span class="task-item-status task-status-' + escapeHtml(item.status) + '">' + escapeHtml(badge) + '</span>'
      + (detail.length ? '<span class="task-item-detail">' + escapeHtml(detail.join(' · ')) + '</span>' : '')
      + '</div>';
  }

  function render(snapshot) {
    var list = $('taskQueueServerList');
    if (list) {
      var items = snapshot.items || [];
      list.innerHTML = items.length
        ? items.map(renderItem).join('')
        : '<div class="small muted">暂无服务端任务。点击“发送队列”后任务会先进入这里，可随时暂停或取消。</div>';
    }
    text('taskQueueServerCounts', countsText(snapshot.counts));
    var notice = [snapshot.message || ''];
    if (snapshot.runner && snapshot.runner.last_error) notice.push('后台错误：' + snapshot.runner.last_error);
    text('taskQueueNotice', notice.filter(Boolean).join(' '));
    var autoSkip = $('taskAutoSkip');
    if (autoSkip) autoSkip.checked = snapshot.auto_skip !== false;
    var selectOnly = $('taskSelectOnly');
    if (selectOnly) selectOnly.checked = snapshot.selected_only === true;
    var paused = snapshot.paused === true;
    var pauseBtn = $('taskPauseBtn');
    if (pauseBtn) {
      pauseBtn.disabled = paused;
      pauseBtn.classList.toggle('primary', !paused);
    }
    var runBtn = $('taskRunBtn');
    if (runBtn) {
      runBtn.disabled = !paused;
      runBtn.classList.toggle('primary', paused);
    }
    var cleanBtn = $('taskCleanFailedBtn');
    if (cleanBtn) {
      var failed = (snapshot.counts && (snapshot.counts.error + snapshot.counts.cancelled + snapshot.counts.skipped)) || 0;
      cleanBtn.disabled = failed <= 0;
    }
  }

  async function control(action, extra) {
    if (state.busy) return;
    state.busy = true;
    try {
      var payload = Object.assign({ action: action }, extra || {});
      var snapshot = await post('/api/tasks/control', payload);
      state.snapshot = snapshot;
      render(snapshot);
      notifyControl(action, snapshot);
    } catch (error) {
      status('队列操作失败：' + error.message);
    } finally {
      state.busy = false;
    }
  }

  function notifyControl(action, snapshot) {
    var messages = {
      run: '队列已继续。', pause: '队列已暂停：当前任务跑完，不再投递新任务。',
      'cancel-current': '已中断当前任务。', 'cancel-pending': '已取消后续任务。',
      'clean-failed': '已清理失败/取消/跳过的任务。', 'clean-finished': '已清理全部结束的任务。',
    };
    var message = snapshot.message || messages[action] || '队列已更新。';
    if (action === 'cancel-pending' || action === 'cancel-current') {
      var comfy = snapshot.comfy || {};
      message += '（ComfyUI 队列删除 ' + (comfy.deleted || 0) + ' 项）';
    }
    status(message);
  }

  function bindToolbar() {
    var run = $('taskRunBtn');
    if (run) run.addEventListener('click', function () { control('run'); });
    var pause = $('taskPauseBtn');
    if (pause) pause.addEventListener('click', function () { control('pause'); });
    var cancelCurrent = $('taskCancelCurrentBtn');
    if (cancelCurrent) cancelCurrent.addEventListener('click', function () { control('cancel-current'); });
    var cancelPending = $('taskCancelPendingBtn');
    if (cancelPending) cancelPending.addEventListener('click', function () { control('cancel-pending'); });
    var cleanFailed = $('taskCleanFailedBtn');
    if (cleanFailed) cleanFailed.addEventListener('click', function () { control('clean-failed'); });
    var cleanFinished = $('taskCleanFinishedBtn');
    if (cleanFinished) cleanFinished.addEventListener('click', function () { control('clean-finished'); });
    var autoSkip = $('taskAutoSkip');
    if (autoSkip) {
      autoSkip.addEventListener('change', function () {
        control('auto-skip', { value: autoSkip.checked });
      });
    }
    var selectOnly = $('taskSelectOnly');
    if (selectOnly) {
      selectOnly.addEventListener('change', function () {
        control('select-only', { value: selectOnly.checked });
      });
    }
    var list = $('taskQueueServerList');
    if (list) {
      list.addEventListener('change', function (event) {
        var input = event.target;
        if (!input || !input.dataset || !input.dataset.taskSelect) return;
        control('select', { ids: [input.dataset.taskSelect], selected: input.checked });
      });
    }
  }

  function startPolling() {
    if (state.timer) return;
    state.timer = setInterval(function () {
      if (document.hidden) return;
      refresh();
    }, POLL_MS);
  }

  /* ------------------------------------------------------------ 重复任务检测 */
  function duplicateDialog() {
    var dialog = $(DIALOG_ID);
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = DIALOG_ID;
    dialog.className = 'duplicate-task-dialog';
    dialog.innerHTML = ''
      + '<h3>发现完全相同的生成任务</h3>'
      + '<p class="small">同样的模型、LoRA、提示词、seed 与采样参数已经生成过。选择下一步：</p>'
      + '<ul class="duplicate-task-list small"></ul>'
      + '<div class="actions">'
      + '  <button type="button" class="secondary" data-dup="cancel">取消重复任务</button>'
      + '  <button type="button" class="secondary" data-dup="open">打开已有结果</button>'
      + '  <button type="button" class="primary" data-dup="still">仍然生成</button>'
      + '</div>';
    document.body.appendChild(dialog);
    return dialog;
  }

  function askDuplicate(info) {
    var dialog = duplicateDialog();
    var list = dialog.querySelector('.duplicate-task-list');
    if (list) {
      list.innerHTML = (info.duplicates || []).map(function (item) {
        var when = item.created_at ? new Date(item.created_at).toLocaleString() : '';
        return '<li>' + escapeHtml(when) + ' · <code>' + escapeHtml(String(item.generation_id || '').slice(0, 12))
          + '</code> · ' + escapeHtml(item.model || '') + '</li>';
      }).join('') || '<li>（无详情）</li>';
    }
    var first = (info.duplicates || [])[0] || {};
    return new Promise(function (resolve) {
      function onClick(event) {
        var button = event.target.closest('button[data-dup]');
        if (!button) return;
        dialog.removeEventListener('click', onClick);
        dialog.close();
        resolve({ choice: button.dataset.dup, generationId: first.generation_id || '' });
      }
      dialog.addEventListener('click', onClick);
      dialog.showModal();
    });
  }

  function openGeneration(generationId) {
    if (!generationId) return;
    if (typeof global.openCreativeLibrary === 'function') {
      global.openCreativeLibrary();
    }
    document.dispatchEvent(new CustomEvent('easy-panel:open-generation', { detail: { generationId: generationId } }));
  }

  async function checkDuplicate(payload) {
    try {
      return await post('/api/generate-check', { payload: payload });
    } catch (error) {
      return { duplicate: false, error: error.message };
    }
  }

  function wrapGenerate() {
    var original = global.generate;
    if (typeof original !== 'function' || original.__duplicateWrapped) return;
    async function wrapped() {
      if (state.allowOnce) {
        state.allowOnce = false;
        return original.apply(this, arguments);
      }
      if (state.busy) {
        return original.apply(this, arguments);
      }
      var build = global.payloadWithoutFinalPromptOverride || global.payload;
      var data = typeof build === 'function' ? build() : {};
      if (data && data.duplicatePolicy === 'allow') {
        return original.apply(this, arguments);
      }
      state.busy = true;
      var info;
      try {
        info = await checkDuplicate(data);
      } finally {
        state.busy = false;
      }
      if (!info.duplicate) {
        return original.apply(this, arguments);
      }
      var answer = await askDuplicate(info);
      if (answer.choice === 'cancel') {
        status('已取消重复任务：完全相同的生成已存在。');
        return { skipped: true, duplicate: true };
      }
      if (answer.choice === 'open') {
        openGeneration(answer.generationId);
        status('已打开已有结果。');
        return { skipped: true, duplicate: true };
      }
      state.allowOnce = true;
      status('已确认仍然生成：正在提交与已有作品完全相同的任务。');
      return original.apply(this, arguments);
    }
    wrapped.__duplicateWrapped = true;
    global.generate = wrapped;
  }

  /* ------------------------------------------------------------ 入队（批量） */
  async function submitBatch(jobs, options) {
    var body = Object.assign({ jobs: jobs, duplicatePolicy: 'skip' }, options || {});
    var result = await post('/api/tasks/add', body);
    state.snapshot = result;
    render(result);
    var message = '已加入任务队列：' + (result.added_count || 0) + ' 个';
    if (result.duplicate_skipped) message += '，跳过重复任务 ' + result.duplicate_skipped + ' 个';
    status(message + '。');
    return result;
  }

  function init() {
    bindToolbar();
    wrapGenerate();
    refresh();
    startPolling();
    global.__taskControl = {
      refresh: refresh, control: control, submitBatch: submitBatch,
      checkDuplicate: checkDuplicate, askDuplicate: askDuplicate, state: state,
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
