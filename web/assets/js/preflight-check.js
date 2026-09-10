/*
 * 生成前检查 + 显存风险预估。
 *
 * 这一层只做“提交前的体检”，不改变任何生成参数：它把面板已有的
 * /api/prompt-compile 与各模型族 preflight 结果、以及本地可见的尺寸 /
 * LoRA / ControlNet / 二采 / 修复器信息汇总成一份清单，让用户在点击
 * 生成前就看到错误与风险。显存部分是相对等级估算，不是物理精确预测。
 */
(function (global) {
  'use strict';

  const DIALOG_ID = 'preflightCheckDialog';
  const VRAM_BUDGET_MB = 8192;
  const MAX_LISTED_ITEMS = 24;
  const FAMILY_ENDPOINTS = {
    anima: '/api/anima-preflight',
    krea2: '/api/krea2-preflight',
    illustrious: '/api/illustrious-preflight',
  };
  const FAMILY_LABELS = {
    anima: 'Anima',
    krea2: 'Krea 2',
    illustrious: 'Illustrious / SDXL',
  };
  const LEVEL_RANK = { ok: 0, note: 1, warn: 2, error: 3 };
  const LEVEL_ICONS = { ok: '✓', note: 'ℹ', warn: '⚠', error: '✗' };

  const state = {
    busy: false,
    report: null,
    skipSession: false,
    resolve: null,
    origin: null,
  };

  function byId(id) {
    return global.document ? global.document.getElementById(id) : null;
  }

  function text(value) {
    return value == null ? '' : String(value).trim();
  }

  function number(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function setStatus(message) {
    const node = byId('status');
    if (node) node.textContent = message;
  }

  function modelFamily(name) {
    const lowered = text(name).toLowerCase();
    if (lowered.includes('anima')) return 'anima';
    if (lowered.includes('krea')) return 'krea2';
    return 'illustrious';
  }

  function currentPayload() {
    if (typeof global.payload !== 'function') return null;
    try {
      return global.payload();
    } catch (_) {
      // payload() 会因为缺少必填项抛错；生成流程自己会给出更准确的提示。
      return null;
    }
  }

  async function postJson(path, body) {
    const response = await global.fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (data && data.error) throw new Error(String(data.error));
    return data || {};
  }

  function listFrom(value) {
    if (Array.isArray(value)) return value.filter((item) => text(item));
    if (text(value)) return [text(value)];
    return [];
  }

  /* ---------------------------------------------------------------- 本地检查 */

  function localItems(data) {
    const items = [];
    const payload = data || {};
    const model = text(payload.model);
    items.push(model
      ? { level: 'ok', label: '基础模型', detail: model }
      : { level: 'error', label: '基础模型', detail: '还没有选择基础模型。' });

    const loras = Array.isArray(payload.loras) ? payload.loras.filter((item) => text(item && item.name)) : [];
    const heavyLoras = loras.filter((item) => number(item.weight, 1) > 1.1);
    const silentLoras = loras.filter((item) => number(item.weight, 1) <= 0.02);
    if (!loras.length) {
      items.push({ level: 'ok', label: 'LoRA', detail: '未启用 LoRA。' });
    } else if (heavyLoras.length) {
      items.push({
        level: 'warn',
        label: `LoRA（${loras.length} 个）`,
        detail: `权重高于 1.1：${heavyLoras.map((item) => `${item.name} ${item.weight}`).join('、')}；叠加多个 LoRA 时建议先降到 1.0 附近。`,
      });
    } else if (silentLoras.length) {
      items.push({
        level: 'note',
        label: `LoRA（${loras.length} 个）`,
        detail: `权重接近 0（等于不生效）：${silentLoras.map((item) => item.name).join('、')}`,
      });
    } else {
      items.push({ level: 'ok', label: `LoRA（${loras.length} 个）`, detail: loras.map((item) => `${item.name} @${item.weight}`).join('、') });
    }

    const vae = payload.vae && typeof payload.vae === 'object' ? payload.vae : {};
    const vaeMode = text(vae.mode) || 'standard';
    items.push({
      level: vaeMode === 'tiled' ? 'ok' : 'ok',
      label: 'VAE',
      detail: vaeMode === 'tiled' ? `分块解码（tile ${number(vae.tileSize, 512)}）` : '标准解码',
    });

    const pose = payload.pose && typeof payload.pose === 'object' ? payload.pose : {};
    const depth = payload.depth && typeof payload.depth === 'object' ? payload.depth : {};
    const controlNets = [];
    if (pose.enabled) controlNets.push(`OpenPose ${text(pose.controlnet) || '（未选择）'}`);
    if (depth.enabled) controlNets.push(`Depth ${text(depth.controlnet) || '（未选择）'}`);
    items.push(controlNets.length
      ? { level: 'ok', label: 'ControlNet', detail: controlNets.join('、') }
      : { level: 'ok', label: 'ControlNet', detail: '未启用姿势 / 深度控制。' });

    const regions = Array.isArray(payload.regions) ? payload.regions.filter((item) => text(item && item.prompt)) : [];
    if (regions.length) {
      items.push({
        level: regions.length >= 2 ? 'ok' : 'warn',
        label: '多人分区',
        detail: regions.length >= 2
          ? `${regions.length} 个角色，各自独立提示词与区域遮罩。`
          : '只填写了 1 个角色的分区提示词；多人分区至少需要两个。',
      });
    }

    return items;
  }

  function familyItems(data, family) {
    const payload = data || {};
    const items = [];
    if (family !== 'illustrious') {
      const label = FAMILY_LABELS[family];
      if ((payload.pose || {}).enabled) {
        items.push({ level: 'error', label: 'ControlNet 兼容性', detail: `${label} 不能使用 SDXL / Illustrious 的 Xinsir OpenPose ControlNet。` });
      }
      if ((payload.depth || {}).enabled) {
        items.push({ level: 'error', label: 'Depth 兼容性', detail: `${label} 不能使用 Xinsir Depth ControlNet。` });
      }
      if (family === 'krea2') {
        items.push({
          level: 'note',
          label: 'FaceDetailer',
          detail: 'Krea 2 Turbo 不使用 FaceDetailer；人像请用参考图或后处理超分保持五官。',
        });
      }
    }
    const mode = text(payload.illustriousMode) || 'precision';
    const enhancement = payload.outputEnhancement && typeof payload.outputEnhancement === 'object' ? payload.outputEnhancement : {};
    if (mode === 'hires' && text(enhancement.mode) && text(enhancement.mode) !== 'off') {
      items.push({ level: 'error', label: '二采 / 超分冲突', detail: '高清二次采样与输出超分不能同时开启，请二选一。' });
    }
    if (mode === 'hires') {
      const lock = payload.hiresCompositionLock !== false;
      const denoise = number(payload.hiresDenoise, 0.25);
      items.push({
        level: lock && denoise <= 0.35 ? 'ok' : denoise > 0.45 ? 'warn' : 'note',
        label: '二次采样',
        detail: `倍率 ${number(payload.hiresScale, 1.25).toFixed(2)}× · 重绘 ${denoise.toFixed(2)} · ${lock ? '优先保持首采构图' : '未锁定构图'}`
          + (denoise > 0.35 ? '；重绘幅度偏高时二采可能改动构图。' : ''),
      });
    }
    if (payload.img2img && payload.img2img.enabled) {
      items.push({ level: 'ok', label: '图生图底图', detail: `${text(payload.img2img.image) || '（未选择）'} · 重绘 ${number(payload.img2img.denoise, 0.6).toFixed(2)}` });
    }
    if (text(payload.illustriousMode) === 'repair') {
      const repair = payload.repair && typeof payload.repair === 'object' ? payload.repair : {};
      const ready = Boolean(text(repair.image) && text(repair.mask));
      items.push({
        level: ready ? 'ok' : 'error',
        label: '局部修复',
        detail: ready ? `已准备原图与蒙版 · 重绘 ${number(repair.denoise, 0.5).toFixed(2)}` : '局部修复需要先上传原图并涂出蒙版。',
      });
    }
    return items;
  }

  function promptItems(compiled) {
    const data = compiled && typeof compiled === 'object' ? compiled : {};
    const items = [];
    const positives = number(data.positiveTerms, 0);
    const negatives = number(data.negativeTerms, 0);
    items.push({
      level: positives ? 'ok' : 'error',
      label: '提示词',
      detail: `正向 ${positives} 项 · 负向 ${negatives} 项 · LoRA 触发词 ${listFrom(data.triggers).length} 项`
        + (data.overridden ? '（已启用手动最终文本）' : ''),
    });
    const diagnostics = Array.isArray(data.diagnostics) ? data.diagnostics : [];
    const warnCount = diagnostics.filter((item) => item && item.severity === 'warning').length;
    items.push(diagnostics.length
      ? {
        level: warnCount ? 'warn' : 'note',
        label: `提示词冲突诊断（${diagnostics.length}）`,
        detail: diagnostics.slice(0, 4).map((item) => text(item && item.message)).filter(Boolean).join('；'),
      }
      : { level: 'ok', label: '提示词冲突诊断', detail: '没有发现人数、构图或正负向对抗冲突。' });
    return items;
  }

  /* ------------------------------------------------------------ 显存风险估算 */

  function vramAssessment(data, family, compiled) {
    const payload = data || {};
    const width = number(payload.width, 832);
    const height = number(payload.height, 1216);
    const megapixels = (width * height) / 1e6;
    const hires = text(payload.illustriousMode) === 'hires' && family === 'illustrious';
    const scale = hires ? number(payload.hiresScale, 1.25) : 1;
    const hiresMegapixels = megapixels * scale * scale;
    const loras = Array.isArray(payload.loras) ? payload.loras.length : 0;
    let controlNets = 0;
    if ((payload.pose || {}).enabled) controlNets += 1;
    if ((payload.depth || {}).enabled) controlNets += 1;
    const enhancement = payload.outputEnhancement && typeof payload.outputEnhancement === 'object' ? payload.outputEnhancement : {};
    const detailer = Boolean((enhancement.faceDetailer || {}).enabled
      || (enhancement.limbDetailer || {}).hands
      || (enhancement.limbDetailer || {}).feet);
    const postMode = text(enhancement.mode) || 'off';
    const regions = Array.isArray(payload.regions) ? payload.regions.filter((item) => text(item && item.prompt)).length : 0;

    // 相对系数：只用面板可见的参数做等级判断，不代表实测显存占用。
    const base = 3400 + megapixels * 950 + Math.max(0, loras - 1) * 380 + controlNets * 640
      + (detailer ? 620 : 0) + (postMode === 'seedvr2' ? 900 : 0) + Math.max(0, regions - 1) * 520;
    const hiresPeak = hires ? 3100 + hiresMegapixels * 1150 + Math.max(0, loras - 1) * 260 : base;
    const reference = 3400 + megapixels * 2.25 * 950 + Math.max(0, loras - 1) * 380;
    const peak = Math.max(base, hiresPeak, reference);
    const ratio = peak / VRAM_BUDGET_MB;
    const level = ratio < 0.85 ? 'ok' : ratio < 1.05 ? 'warn' : 'error';
    const notes = [];
    if (megapixels > 1.25) notes.push(`首采分辨率 ${width}×${height}（${megapixels.toFixed(2)} MP）偏大，8GB 显存建议 1.25 MP 以内。`);
    if (hires && hiresMegapixels > 1.9) notes.push(`二采成图约 ${hiresMegapixels.toFixed(2)} MP，风险明显上升，可改用 1.10–1.25×。`);
    if (loras >= 4) notes.push(`同时启用 ${loras} 个 LoRA，加载与交叉注意力开销都会增加。`);
    if (controlNets >= 2) notes.push('同时启用多个 ControlNet，需要额外常驻模型显存。');
    if (detailer && hires) notes.push('二采与脸/手脚修复同时开启，峰值出现在修复阶段。');
    if (postMode === 'seedvr2') notes.push('SeedVR2 后处理会额外加载一个放大模型。');
    if (!notes.length) notes.push('当前组合在 8GB 显存下属于常规负载。');
    return {
      level,
      ratio,
      baseMb: Math.round(base),
      hiresMb: Math.round(hiresPeak),
      referenceMb: Math.round(reference),
      peakMb: Math.round(peak),
      budgetMb: VRAM_BUDGET_MB,
      megapixels,
      hiresMegapixels,
      hires,
      label: level === 'ok' ? '低' : level === 'warn' ? '中（接近上限）' : '高',
      notes,
      quota: compiled && typeof compiled === 'object' ? compiled : {},
    };
  }

  /* ------------------------------------------------------------------ 报告生成 */

  async function buildReport() {
    const payload = currentPayload();
    if (!payload) return null;
    const family = modelFamily(payload.model);
    const items = localItems(payload);
    let compiled = {};
    try {
      compiled = await postJson('/api/prompt-compile', payload);
    } catch (error) {
      items.push({ level: 'warn', label: '提示词编译', detail: `无法编译提示词：${error.message}` });
    }
    items.push(...promptItems(compiled));
    items.push(...familyItems(payload, family));
    const endpoint = FAMILY_ENDPOINTS[family];
    if (endpoint) {
      try {
        const preflight = await postJson(endpoint, payload);
        const errors = listFrom(preflight.errors);
        const warnings = listFrom(preflight.warnings);
        items.push({
          level: errors.length ? 'error' : warnings.length ? 'warn' : 'ok',
          label: `${FAMILY_LABELS[family]} 预检`,
          detail: errors.length || warnings.length
            ? [...errors.map((item) => `错误：${item}`), ...warnings.map((item) => `提示：${item}`)].slice(0, 6).join('；')
            : '模型族链路、提示词与参数检查通过。',
        });
      } catch (error) {
        items.push({ level: 'note', label: `${FAMILY_LABELS[family]} 预检`, detail: `预检接口不可用：${error.message}` });
      }
    }
    const vram = vramAssessment(payload, family, compiled);
    items.push({ level: vram.level, label: `显存风险：${vram.label}`, detail: `估算峰值约 ${vram.peakMb} MB / 预算 ${vram.budgetMb} MB` });
    return {
      family,
      familyLabel: FAMILY_LABELS[family],
      items: items.slice(0, MAX_LISTED_ITEMS),
      vram,
      errors: items.filter((item) => item.level === 'error').length,
      warnings: items.filter((item) => item.level === 'warn').length,
    };
  }

  function highestLevel(items) {
    return (items || []).reduce((best, item) => (LEVEL_RANK[item.level] > LEVEL_RANK[best] ? item.level : best), 'ok');
  }

  /* -------------------------------------------------------------------- 对话框 */

  function bar(label, valueMb, level) {
    const row = global.document.createElement('div');
    row.className = `preflight-vram-row preflight-level-${level}`;
    const head = global.document.createElement('div');
    head.className = 'preflight-vram-head';
    head.append(global.document.createElement('span'), global.document.createElement('b'));
    head.firstChild.textContent = label;
    head.lastChild.textContent = `${Math.round(valueMb)} MB`;
    const track = global.document.createElement('div');
    track.className = 'preflight-vram-track';
    const fill = global.document.createElement('div');
    fill.className = 'preflight-vram-fill';
    fill.style.width = `${Math.min(100, Math.round((valueMb / VRAM_BUDGET_MB) * 100))}%`;
    track.append(fill);
    row.append(head, track);
    return row;
  }

  function buildDialog(report) {
    const dialog = global.document.createElement('dialog');
    dialog.id = DIALOG_ID;
    dialog.className = 'preflight-dialog';
    dialog.setAttribute('aria-label', '生成前检查');

    const head = global.document.createElement('div');
    head.className = 'preflight-dialog-head';
    const title = global.document.createElement('h3');
    title.textContent = '生成前检查';
    const subtitle = global.document.createElement('p');
    subtitle.className = 'small';
    subtitle.textContent = `当前模型族：${report.familyLabel} · 只读检查，不会自动提交任务。`;
    head.append(title, subtitle);

    const list = global.document.createElement('ul');
    list.className = 'preflight-check-list';
    report.items.forEach((item) => {
      const entry = global.document.createElement('li');
      entry.className = `preflight-check-item preflight-level-${item.level}`;
      const icon = global.document.createElement('span');
      icon.className = 'preflight-check-icon';
      icon.textContent = LEVEL_ICONS[item.level] || '·';
      const body = global.document.createElement('div');
      const label = global.document.createElement('b');
      label.textContent = item.label;
      const detail = global.document.createElement('div');
      detail.className = 'small';
      detail.textContent = item.detail || '';
      body.append(label, detail);
      entry.append(icon, body);
      list.append(entry);
    });

    const vramTitle = global.document.createElement('h4');
    vramTitle.textContent = `显存风险：${report.vram.label}（相对估算，8GB 基准）`;
    const bars = global.document.createElement('div');
    bars.className = 'preflight-vram';
    bars.append(
      bar('基础生成', report.vram.baseMb, report.vram.level),
      bar(report.vram.hires ? '当前二采峰值' : '当前配置峰值', report.vram.hiresMb, report.vram.level),
      bar('1.5× 尺寸参考', report.vram.referenceMb, report.vram.referenceMb / VRAM_BUDGET_MB < 0.85 ? 'ok' : 'warn'),
    );
    const notes = global.document.createElement('ul');
    notes.className = 'preflight-vram-notes small';
    report.vram.notes.forEach((note) => {
      const item = global.document.createElement('li');
      item.textContent = note;
      notes.append(item);
    });
    const disclaimer = global.document.createElement('p');
    disclaimer.className = 'small preflight-disclaimer';
    disclaimer.textContent = '这是按分辨率、LoRA、ControlNet、二采与修复器做的相对等级，不是物理精确的显存预测；真实占用还取决于驱动、精度与 ComfyUI 版本。';

    const skipLabel = global.document.createElement('label');
    skipLabel.className = 'preflight-skip';
    const skip = global.document.createElement('input');
    skip.type = 'checkbox';
    skip.disabled = report.errors > 0;
    skipLabel.append(skip, global.document.createTextNode('本次会话不再提示（存在错误时必须处理）'));

    const footer = global.document.createElement('div');
    footer.className = 'actions';
    const back = global.document.createElement('button');
    back.type = 'button';
    back.className = 'secondary';
    back.textContent = '返回修改';
    const go = global.document.createElement('button');
    go.type = 'button';
    go.className = 'primary';
    go.textContent = report.errors ? '仍有错误，无法生成' : '继续生成';
    go.disabled = report.errors > 0;
    footer.append(back, skipLabel, go);

    dialog.append(head, list, vramTitle, bars, notes, disclaimer, footer);
    const close = (proceed) => {
      state.skipSession = proceed && skip.checked === true;
      if (dialog.open && typeof dialog.close === 'function') dialog.close();
      else if (dialog.parentNode) dialog.parentNode.removeChild(dialog);
      const resolve = state.resolve;
      state.resolve = null;
      if (resolve) resolve(proceed);
    };
    back.addEventListener('click', () => close(false));
    go.addEventListener('click', () => close(true));
    dialog.addEventListener('cancel', (event) => {
      event.preventDefault();
      close(false);
    });
    return dialog;
  }

  function askUser(report) {
    const existing = byId(DIALOG_ID);
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
    const dialog = buildDialog(report);
    global.document.body.append(dialog);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    return new Promise((resolve) => { state.resolve = resolve; });
  }

  /* -------------------------------------------------------------------- 主流程 */

  async function checkAndConfirm() {
    let report = null;
    try {
      report = await buildReport();
    } catch (_) {
      // 检查本身失败绝不阻塞生成：面板与后端仍会给出真实报错。
      return { proceed: true, report: null };
    }
    if (!report) return { proceed: true, report: null };
    state.report = report;
    const level = highestLevel(report.items);
    if (level === 'ok') return { proceed: true, report };
    if (state.skipSession && report.errors === 0) return { proceed: true, report };
    setStatus(report.errors
      ? `生成前检查发现 ${report.errors} 个错误，请先处理。`
      : `生成前检查有 ${report.warnings} 项提示，请确认后再生成。`);
    const proceed = await askUser(report);
    return { proceed, report };
  }

  function wrapGenerate() {
    const original = global.generate;
    if (typeof original !== 'function' || original.__preflightWrapped) return false;
    const wrapped = async function (...args) {
      if (state.busy) return undefined;
      state.busy = true;
      try {
        const outcome = await checkAndConfirm();
        if (!outcome.proceed) {
          setStatus('已取消生成：请根据检查清单调整后重新点击生成。');
          return undefined;
        }
      } finally {
        state.busy = false;
      }
      return original.apply(this, args);
    };
    wrapped.__preflightWrapped = true;
    global.generate = wrapped;
    return true;
  }

  function init() {
    if (!global.document) return;
    wrapGenerate();
    global.__preflightCheck = {
      run: buildReport,
      check: checkAndConfirm,
      wrap: wrapGenerate,
      skipSession: () => state.skipSession,
      reset: () => { state.skipSession = false; },
    };
    global.runGenerationPreflight = async () => {
      const report = await buildReport();
      if (report) await askUser(report);
      return report;
    };
  }

  if (global.document && global.document.readyState === 'loading') {
    global.document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
}(typeof window !== 'undefined' ? window : globalThis));
