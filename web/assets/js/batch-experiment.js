/*
 * 批量单变量实验。
 *
 * 只改变一个变量、重复其它全部参数，是判断“到底哪一项有效”的最快方式。
 * 这里复用面板已有的任务队列：逐个改写目标字段 → 调用一次 enqueueJob() →
 * 恢复原值。每个任务带上 experiment.label，结果卡片与作品库会分别标注
 * 这次的变量取值，便于横向对比。
 */
(function (global) {
  'use strict';

  const DIALOG_ID = 'batchExperimentDialog';
  const MAX_VALUES = 8;
  const INPUT_IDS = ['seed', 'cfg', 'steps', 'hiresScale', 'hiresDenoise', 'hiresSteps', 'hiresCfg'];

  const VARIABLES = [
    { key: 'seed', label: 'Seed', inputId: 'seed', kind: 'seed', hint: '整数种子；写 random 表示随机' },
    { key: 'cfg', label: 'CFG', inputId: 'cfg', kind: 'number', hint: '常规范围 1–15' },
    { key: 'steps', label: '步数', inputId: 'steps', kind: 'number', hint: '常规范围 8–60' },
    { key: 'hiresScale', label: '二采倍率', inputId: 'hiresScale', kind: 'number', hint: '仅在二采模式下生效，1.10–1.50' },
    { key: 'hiresDenoise', label: '二采重绘幅度', inputId: 'hiresDenoise', kind: 'number', hint: '锁定首采构图时上限 0.35' },
    { key: 'hiresSteps', label: '二采步数', inputId: 'hiresSteps', kind: 'number', hint: '高清阶段步数' },
    { key: 'hiresCfg', label: '二采 CFG', inputId: 'hiresCfg', kind: 'number', hint: '高清阶段 CFG' },
  ];

  const state = { pendingLabel: '', pendingVariable: '', pendingValue: '', pendingSelected: true, running: false };

  function byId(id) {
    return global.document ? global.document.getElementById(id) : null;
  }

  function text(value) {
    return value == null ? '' : String(value).trim();
  }

  function createElement(tag, className, content) {
    const node = global.document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = content;
    return node;
  }

  function setStatus(message) {
    const node = byId('status');
    if (node) node.textContent = message;
  }

  function variableFor(key) {
    return VARIABLES.find((item) => item.key === key) || VARIABLES[0];
  }

  function currentValue(variable) {
    const input = byId(variable.inputId);
    return input ? text(input.value) : '';
  }

  /* ---------------------------------------------------------------- 取值解析 */

  function parseValues(variable, raw) {
    const chunks = text(raw).split(/[\s,，、;；|]+/u).filter(Boolean);
    const values = [];
    const invalid = [];
    for (const chunk of chunks) {
      if (values.length >= MAX_VALUES) {
        invalid.push(`${chunk}（超出 ${MAX_VALUES} 个上限）`);
        continue;
      }
      if (variable.kind === 'seed') {
        if (chunk.toLowerCase() === 'random' || chunk === '随机') {
          values.push('random');
          continue;
        }
        const parsed = Number(chunk);
        if (Number.isFinite(parsed) && Number.isInteger(parsed) && parsed >= 0) values.push(String(parsed));
        else invalid.push(chunk);
        continue;
      }
      const parsed = Number(chunk);
      if (Number.isFinite(parsed)) values.push(String(parsed));
      else invalid.push(chunk);
    }
    return { values, invalid };
  }

  function writeVariable(variable, value) {
    const input = byId(variable.inputId);
    if (!input) return false;
    input.value = variable.kind === 'seed' && value === 'random' ? '-1' : String(value);
    input.dispatchEvent(new global.Event('input', { bubbles: true }));
    input.dispatchEvent(new global.Event('change', { bubbles: true }));
    return true;
  }

  /* -------------------------------------------------------------- 标签注入 */

  function wrapPayload() {
    const original = global.payload;
    if (typeof original !== 'function' || original.__experimentWrapped) return false;
    const wrapped = function (...args) {
      const data = original.apply(this, args);
      if (state.pendingLabel && data && typeof data === 'object') {
        // 与既有 experiment.label 约定一致：结果卡片与作品库都会显示这个标签。
        data.experiment = {
          strict: false,
          mode: 'single-variable',
          label: state.pendingLabel,
          variable: state.pendingVariable,
          value: state.pendingValue,
        };
        // 未勾选“入选”的取值仍进队列，但标记 selected=false，配合“只运行入选实验”跳过。
        if (state.pendingSelected === false) data.selected = false;
      }
      return data;
    };
    wrapped.__experimentWrapped = true;
    global.payload = wrapped;
    return true;
  }

  /* ------------------------------------------------------------------ 执行 */

  function enqueueOne(variable, value, selected) {
    if (typeof global.enqueueJob !== 'function') return { ok: false, message: '当前页面缺少任务队列。' };
    const statusNode = byId('status');
    const before = statusNode ? statusNode.textContent : '';
    state.pendingLabel = `实验 ${variable.label}=${value}`;
    state.pendingVariable = variable.label;
    state.pendingValue = String(value);
    state.pendingSelected = selected !== false;
    try {
      global.enqueueJob();
    } finally {
      state.pendingLabel = '';
      state.pendingVariable = '';
      state.pendingValue = '';
      state.pendingSelected = true;
    }
    const after = statusNode ? statusNode.textContent : '';
    const failed = /失败/u.test(after) && after !== before;
    return { ok: !failed, message: failed ? after : '' };
  }

  function runExperiment(options) {
    const variable = variableFor(options && options.key);
    if (state.running) return { queued: 0, skipped: [], stopped: '已有实验正在加入队列。' };
    if (!byId(variable.inputId)) {
      return { queued: 0, skipped: [], stopped: `当前界面没有「${variable.label}」输入框（可能未启用二采）。` };
    }
    const parsed = parseValues(variable, options && options.values);
    if (!parsed.values.length) {
      return { queued: 0, skipped: parsed.invalid, stopped: '请至少填写一个有效取值。' };
    }
    const original = currentValue(variable);
    const queuedValues = [];
    const failures = [];
    const selection = Array.isArray(options && options.selectedValues) ? options.selectedValues : null;
    state.running = true;
    try {
      parsed.values.forEach((value) => {
        if (!writeVariable(variable, value)) return;
        const selected = selection ? selection.indexOf(String(value)) >= 0 : true;
        const result = enqueueOne(variable, value, selected);
        if (result.ok) queuedValues.push(value);
        else failures.push(`${value}：${result.message}`);
      });
    } finally {
      writeVariable(variable, original);
      state.running = false;
    }
    if (options && options.autoSend && queuedValues.length && typeof global.sendJobQueue === 'function') {
      void global.sendJobQueue();
    }
    return { queued: queuedValues.length, values: queuedValues, skipped: parsed.invalid, failures, variable };
  }

  /* ---------------------------------------------------------------- 对话框 */

  function buildDialog() {
    const dialog = createElement('dialog');
    dialog.id = DIALOG_ID;
    dialog.className = 'batch-experiment-dialog';
    dialog.setAttribute('aria-label', '批量单变量实验');

    const head = createElement('div', 'batch-experiment-head');
    head.append(
      createElement('h3', '', '批量单变量实验'),
      createElement('p', 'small', '固定其它参数，只改动一个变量；每个取值生成一个队列任务，方便横向对比。'),
    );

    const variableLabel = createElement('label', 'batch-experiment-field', '实验变量');
    const select = createElement('select');
    select.id = 'batchExperimentVariable';
    VARIABLES.forEach((item) => {
      const option = createElement('option', '', item.label);
      option.value = item.key;
      select.append(option);
    });
    variableLabel.append(select);

    const valueLabel = createElement('label', 'batch-experiment-field', '取值（逗号或空格分隔）');
    const valueInput = createElement('input');
    valueInput.id = 'batchExperimentValues';
    valueInput.type = 'text';
    valueInput.autocomplete = 'off';
    valueInput.placeholder = '例如 0.60, 0.70, 0.80, 0.90';
    valueLabel.append(valueInput);

    const currentHint = createElement('p', 'small batch-experiment-current');
    currentHint.id = 'batchExperimentCurrent';
    const hint = createElement('p', 'small batch-experiment-hint');
    hint.id = 'batchExperimentHint';

    const autoLabel = createElement('label', 'batch-experiment-auto');
    const auto = createElement('input');
    auto.type = 'checkbox';
    auto.id = 'batchExperimentAutoSend';
    autoLabel.append(auto, global.document.createTextNode('加入队列后立即开始生成'));

    const preview = createElement('p', 'small batch-experiment-preview');
    preview.id = 'batchExperimentPreview';

    const selectionBox = createElement('div', 'batch-experiment-selection small');
    selectionBox.id = 'batchExperimentSelection';

    const footer = createElement('div', 'actions');
    const cancel = createElement('button', 'secondary', '取消');
    cancel.type = 'button';
    const enqueue = createElement('button', 'secondary', '只加入队列');
    enqueue.type = 'button';
    const start = createElement('button', 'primary', '加入并开始');
    start.type = 'button';
    footer.append(cancel, enqueue, start);

    dialog.append(head, variableLabel, valueLabel, currentHint, hint, autoLabel, preview, selectionBox, footer);

    let lastFocus = null;

    function selectedVariable() {
      return variableFor(select.value);
    }

    function refreshHints() {
      const variable = selectedVariable();
      currentHint.textContent = `当前 ${variable.label}：${currentValue(variable) || '（空）'}`;
      hint.textContent = variable.hint || '';
      const parsed = parseValues(variable, valueInput.value);
      const parts = [];
      if (parsed.values.length) {
        parts.push(`将按 ${variable.label} = ${parsed.values.join(' / ')} 加入 ${parsed.values.length} 个任务，其它参数保持不变。`);
      } else {
        parts.push('填写若干取值后会显示将要加入的任务。');
      }
      if (parsed.invalid.length) parts.push(`忽略无效取值：${parsed.invalid.join('、')}`);
      preview.textContent = parts.join(' ');
      renderSelection(parsed.values);
    }

    /* 每个取值一个勾选框：取消勾选的取值仍会进队列，但由“只运行入选实验”跳过。 */
    function renderSelection(values) {
      const previous = {};
      selectionBox.querySelectorAll('input[type=checkbox]').forEach((input) => {
        previous[input.value] = input.checked;
      });
      selectionBox.textContent = values.length ? '入选（不打勾的取值会在队列里标记为跳过）：' : '';
      values.forEach((value) => {
        const label = createElement('label', 'batch-experiment-selection-item');
        const input = createElement('input');
        input.type = 'checkbox';
        input.value = String(value);
        input.checked = previous[String(value)] !== false;
        label.append(input, global.document.createTextNode(' ' + value));
        selectionBox.append(label);
      });
    }

    function selectedValues() {
      return Array.from(selectionBox.querySelectorAll('input[type=checkbox]'))
        .filter((input) => input.checked)
        .map((input) => input.value);
    }

    function close() {
      if (dialog.open && typeof dialog.close === 'function') dialog.close();
      else if (dialog.parentNode) dialog.parentNode.removeChild(dialog);
      if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();
    }

    function submit(autoSend) {
      const result = runExperiment({
        key: select.value,
        values: valueInput.value,
        autoSend,
        selectedValues: selectedValues(),
      });
      if (result.stopped) {
        setStatus(result.stopped);
        return;
      }
      const pieces = [`已加入 ${result.queued} 个单变量实验任务（${result.variable.label}）`];
      if (result.values.length) pieces.push(result.values.join(' / '));
      pieces.push('未入选项会在“只运行入选实验”模式下跳过');
      if (result.failures && result.failures.length) pieces.push(`失败：${result.failures.join('；')}`);
      if (result.skipped && result.skipped.length) pieces.push(`忽略：${result.skipped.join('、')}`);
      setStatus(pieces.join('；') + '。');
      close();
    }

    select.addEventListener('change', refreshHints);
    valueInput.addEventListener('input', refreshHints);
    cancel.addEventListener('click', close);
    enqueue.addEventListener('click', () => submit(false));
    start.addEventListener('click', () => submit(true));
    dialog.addEventListener('cancel', (event) => {
      event.preventDefault();
      close();
    });
    dialog.__prefill = (key) => {
      select.value = key;
      valueInput.value = defaultValuesFor(selectedVariable());
      refreshHints();
    };
    dialog.__focusTarget = (previous) => {
      lastFocus = previous || global.document.activeElement;
      valueInput.focus();
    };
    refreshHints();
    return dialog;
  }

  function defaultValuesFor(variable) {
    const presets = {
      seed: '1, 2, 3, 4',
      cfg: '4, 5, 6, 7',
      steps: '20, 24, 28, 32',
      hiresScale: '1.10, 1.20, 1.30, 1.40',
      hiresDenoise: '0.20, 0.25, 0.30, 0.35',
      hiresSteps: '10, 14, 18, 22',
      hiresCfg: '3.5, 4, 4.5, 5',
    };
    return presets[variable.key] || '';
  }

  function openDialog() {
    const existing = byId(DIALOG_ID);
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
    const previousFocus = global.document.activeElement;
    const dialog = buildDialog();
    global.document.body.append(dialog);
    const preferred = INPUT_IDS.find((id) => byId(id)) || 'seed';
    if (typeof dialog.__prefill === 'function') dialog.__prefill(preferred);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    if (typeof dialog.__focusTarget === 'function') dialog.__focusTarget(previousFocus);
    return dialog;
  }

  function init() {
    if (!global.document) return;
    wrapPayload();
    global.openBatchExperiment = openDialog;
    global.__batchExperiment = { run: runExperiment, parse: parseValues, variables: () => VARIABLES.slice() };
  }

  if (global.document && global.document.readyState === 'loading') {
    global.document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
}(typeof window !== 'undefined' ? window : globalThis));
