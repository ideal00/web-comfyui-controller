/* Read-only provenance and reproducible restore helpers for snapshot schema v2. */
(function () {
  const legacyRestorePayloadToPanel = window.restorePayloadToPanel;

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function text(value, fallback) {
    const result = String(value == null ? '' : value).trim();
    return result || (fallback || '');
  }

  function setValue(id, value) {
    const element = document.getElementById(id);
    if (element && value != null && value !== '') element.value = String(value);
  }

  function setChecked(id, value) {
    const element = document.getElementById(id);
    if (element && value != null) element.checked = Boolean(value);
  }

  function snapshotTime(value) {
    try { return new Date(Number(value)).toLocaleString(); } catch (_) { return ''; }
  }

  function sourceTrace(item) {
    const source = item.source || {};
    const compiled = item.compiled || {};
    const sectionKeys = ['subject', 'appearance', 'clothing', 'pose', 'composition', 'scene', 'lighting', 'styleColoring', 'naturalLanguage', 'manual'];
    const sections = sectionKeys.filter(key => text(source[key])).map(key => `${escapeHtml(key)}: ${escapeHtml(source[key])}`);
    const loraEntries = Array.isArray(source.loras) ? source.loras.filter(lora => lora && typeof lora === 'object') : [];
    const loras = loraEntries.map(lora => {
      const weight = lora.weight == null ? '' : ` × ${escapeHtml(lora.weight)}`;
      const trigger = text(lora.trigger) ? ` · trigger: ${escapeHtml(lora.trigger)}` : '';
      return `${escapeHtml(lora.name || '')}${weight}${trigger}`;
    }).filter(Boolean);
    const generation = source.generation || {};
    const samplingTrace = compiled.sampling && typeof compiled.sampling === 'object' ? compiled.sampling : {};
    const samplingSettings = samplingTrace.settings && typeof samplingTrace.settings === 'object' ? samplingTrace.settings : generation;
    const sampling = formatRecord(samplingSettings);
    const sources = Array.isArray(compiled.sources) ? compiled.sources.filter(entry => entry && typeof entry === 'object') : [];
    const promptSources = sources.filter(entry => Array.isArray(entry.terms) && entry.terms.length).map(entry => `<div class="snapshot-source-row"><b>${escapeHtml(entry.label || entry.key || 'source')}</b><br>${escapeHtml(entry.terms.join(', '))}</div>`).join('');
    const userSources = sources.filter(entry => ['userPositive', 'naturalLanguage', 'manualOverride'].includes(entry.key) && Array.isArray(entry.terms) && entry.terms.length).map(entry => `<div class="snapshot-source-row"><b>${escapeHtml(entry.label || entry.key)}</b><br>${escapeHtml(entry.terms.join(', '))}</div>`).join('');
    const triggers = Array.isArray(compiled.triggers) ? compiled.triggers.filter(Boolean).join(', ') : '';
    const profile = compiled.profile && typeof compiled.profile === 'object' ? compiled.profile : (source.modelStrategy || {});
    const automation = compiled.automation && typeof compiled.automation === 'object' ? compiled.automation : {};
    const deduplication = compiled.deduplication && typeof compiled.deduplication === 'object' ? compiled.deduplication : {};
    const diagnostics = Array.isArray(compiled.diagnostics) ? compiled.diagnostics.filter(item => item && typeof item === 'object').map(item => `${escapeHtml(item.code || 'diagnostic')}：${escapeHtml(item.message || item.title || '')}`).join('<br>') : '';
    const warnings = Array.isArray(compiled.warnings) ? compiled.warnings.filter(Boolean).map(item => escapeHtml(item)).join('；') : '';
    const errors = Array.isArray(compiled.errors) ? compiled.errors.filter(Boolean).map(item => escapeHtml(item)).join('；') : '';
    const reasons = Array.isArray(samplingTrace.reasons) ? samplingTrace.reasons.filter(item => item && typeof item === 'object').map(item => escapeHtml(item.message || item.code || '')).filter(Boolean).join('；') : '';
    const finalPositive = text(compiled.positive);
    const finalNegative = text(compiled.negative);
    return `<details class="snapshot-source"><summary>来源追踪 · schema v${escapeHtml(item.schemaVersion || 2)}</summary>`
      + (source.checkpoint ? `<div class="snapshot-source-row"><b>Checkpoint</b>：${escapeHtml(source.checkpoint)}</div>` : '')
      + (source.vae && (source.vae.name || source.vae.mode) ? `<div class="snapshot-source-row"><b>VAE</b>：${escapeHtml(source.vae.name || source.vae.mode)}</div>` : '')
      + (profile && Object.keys(profile).length ? `<div class="snapshot-source-row"><b>模型 profile / 质量策略</b>：${formatRecord(profile)}</div>` : '')
      + (sampling ? `<div class="snapshot-source-row"><b>采样参数</b>：${sampling}${reasons ? `<br><small>为什么这样取值：${reasons}</small>` : ''}</div>` : '')
      + (Object.keys(automation).length ? `<div class="snapshot-source-row"><b>自动注入开关</b>：${formatRecord(automation)}</div>` : '')
      + (userSources || (sections.length ? `<div class="snapshot-source-row"><b>用户输入来源</b><br>${sections.join('<br>')}</div>` : ''))
      + (sections.length ? `<div class="snapshot-source-row"><b>结构化分区</b><br>${sections.join('<br>')}</div>` : '')
      + (source.regionGlobalPrompt ? `<div class="snapshot-source-row"><b>区域全局关系</b>：${escapeHtml(source.regionGlobalPrompt)}</div>` : '')
      + (loras.length ? `<div class="snapshot-source-row"><b>LoRA</b><br>${loras.join('<br>')}</div>` : '')
      + (triggers ? `<div class="snapshot-source-row"><b>可靠 LoRA trigger 实际注入</b>：${escapeHtml(triggers)}</div>` : '')
      + (promptSources || '<div class="snapshot-source-row">当前快照没有可显示的编译来源。</div>')
      + `<div class="snapshot-source-row"><b>去重 / 覆盖 / 冲突诊断</b>：${compiled.overridden ? '已启用手动最终文本覆盖' : '未启用手动最终文本覆盖'}${Object.keys(deduplication).length ? ` · ${formatRecord(deduplication)}` : ''}${diagnostics ? `<br>${diagnostics}` : '<br>无冲突诊断'}${warnings ? `<br>警告：${warnings}` : ''}${errors ? `<br>错误：${errors}` : ''}</div>`
      + `<div class="snapshot-source-row"><b>最终 positive</b><br><code>${escapeHtml(finalPositive || '（空）')}</code></div>`
      + `<div class="snapshot-source-row"><b>最终 negative</b><br><code>${escapeHtml(finalNegative || '（空）')}</code></div>`
      + '</details>';
  }

  function formatRecord(value) {
    if (!value || typeof value !== 'object') return escapeHtml(value == null ? '' : value);
    return Object.keys(value).map(key => `${escapeHtml(key)}=${escapeHtml(typeof value[key] === 'object' ? JSON.stringify(value[key]) : value[key])}`).join(' · ');
  }

  function normalizeRegion(region) {
    region = region || {};
    return {
      name: text(region.name), prompt: text(region.prompt), subject: text(region.subject, '1girl'),
      lora: text(region.lora), preset: text(region.preset, 'custom'),
      x: Number(region.x) || 0, y: Number(region.y) || 0,
      width: Number(region.width) || 1, height: Number(region.height) || 1,
      strength: Number(region.strength) || 1,
    };
  }

  function restoreAdvancedPayload(data) {
    if (!data) return;
    setValue('illustriousMode', data.illustriousMode);
    ['hiresScale', 'hiresDenoise', 'hiresSteps', 'hiresCfg', 'hiresSampler', 'hiresScheduler'].forEach(id => setValue(id, data[id]));
    ['hiresPositive', 'hiresNegative'].forEach(id => {
      const element = document.getElementById(id);
      if (element && data[id] != null) element.value = String(data[id]);
    });
    setValue('hiresPromptMode', data.hiresPromptMode);
    setChecked('hiresLockComposition', data.hiresLockComposition);
    if (typeof hiresPromptModeChanged === 'function') hiresPromptModeChanged(true);
    if (typeof hiresLockCompositionChanged === 'function') hiresLockCompositionChanged(true);
    if (data.guidance) {
      setValue('guidanceMode', data.guidance.mode);
      setValue('sagScale', data.guidance.sagScale);
      setValue('sagBlur', data.guidance.sagBlur);
      setValue('pagScale', data.guidance.pagScale);
      if (typeof guidanceChanged === 'function') guidanceChanged(true);
    }
    if (data.vae) {
      setValue('vaeMode', data.vae.mode);
      setValue('vaeTileSize', data.vae.tileSize);
      setValue('vaeOverlap', data.vae.overlap);
      if (typeof vaeModeChanged === 'function') vaeModeChanged(true);
    }
    if (data.modelEnhancement) {
      setValue('modelEnhancementMode', data.modelEnhancement.mode);
      setValue('freeuB1', data.modelEnhancement.b1);
      setValue('freeuB2', data.modelEnhancement.b2);
      setValue('freeuS1', data.modelEnhancement.s1);
      setValue('freeuS2', data.modelEnhancement.s2);
      setValue('cfgRescaleMultiplier', data.modelEnhancement.multiplier);
      if (typeof modelAdvancedChanged === 'function') modelAdvancedChanged(true);
    }
    if (data.regionGlobalPrompt != null) setValue('regionGlobalPrompt', data.regionGlobalPrompt);
    if (Array.isArray(data.regions) && typeof regions !== 'undefined') {
      regions = data.regions.map(normalizeRegion);
      setChecked('regionsEnabled', regions.length > 0);
      if (typeof renderRegions === 'function') renderRegions();
    }
    if (data.repair) {
      setValue('repairGrow', data.repair.grow);
      setValue('repairDenoise', data.repair.denoise);
      if (typeof repairUpload !== 'undefined') repairUpload = { image: text(data.repair.image), mask: text(data.repair.mask) };
    }
    if (data.img2img) {
      setChecked('img2imgEnabled', data.img2img.enabled);
      setValue('img2imgDenoise', data.img2img.denoise);
      if (typeof img2imgUpload !== 'undefined') img2imgUpload = { name: text(data.img2img.image), previewUrl: '' };
      if (typeof toggleImg2img === 'function') toggleImg2img();
    }
    if (data.pose) {
      setChecked('poseEnabled', data.pose.enabled);
      setValue('poseMode', data.pose.mode);
      setValue('poseControlnet', data.pose.controlnet);
      setValue('poseStrength', data.pose.strength);
      setValue('poseEnd', data.pose.end);
      if (typeof poseUpload !== 'undefined') poseUpload = { name: text(data.pose.image), previewUrl: '' };
      if (typeof poseExtractedJson !== 'undefined' && data.pose.poseJson) poseExtractedJson = text(data.pose.poseJson);
      if (typeof setPoseEditorReady === 'function') setPoseEditorReady();
      if (typeof togglePoseControls === 'function') togglePoseControls();
    }
    if (data.depth) {
      setChecked('depthEnabled', data.depth.enabled);
      setValue('depthControlnet', data.depth.controlnet);
      setValue('depthStrength', data.depth.strength);
      setValue('depthEnd', data.depth.end);
      setChecked('depthSuppressSimple', data.depth.suppressSimple);
      if (typeof depthUpload !== 'undefined') depthUpload = { name: text(data.depth.image), previewUrl: '' };
      if (typeof toggleDepthControls === 'function') toggleDepthControls();
    }
    if (data.colorCorrection) {
      setChecked('colorEnabled', data.colorCorrection.enabled);
      ['brightness', 'contrast', 'saturation', 'gamma', 'red', 'green', 'blue', 'hue', 'hsvSaturation', 'value', 'blackPoint', 'whitePoint', 'grayPoint'].forEach(key => setValue('color' + key.charAt(0).toUpperCase() + key.slice(1), data.colorCorrection[key]));
      if (typeof toggleColorCorrection === 'function') toggleColorCorrection();
    }
    if (data.outputEnhancement) {
      setValue('outputEnhancementMode', data.outputEnhancement.mode);
      setValue('outputEnhancementScale', data.outputEnhancement.scale);
      setValue('ultimateSteps', data.outputEnhancement.steps);
      setValue('ultimateDenoise', data.outputEnhancement.denoise);
      setValue('ultimateTileSize', data.outputEnhancement.tileSize);
      setValue('seedvrColor', data.outputEnhancement.seedvrColor);
      const face = data.outputEnhancement.faceDetailer || {};
      const limbs = data.outputEnhancement.limbDetailer || {};
      const colorMatch = data.outputEnhancement.colorMatch || {};
      setChecked('faceDetailerEnabled', face.enabled);
      setValue('faceDetailerGuideSize', face.guideSize);
      setValue('faceDetailerSteps', face.steps);
      setValue('faceDetailerDenoise', face.denoise);
      setChecked('handDetailerEnabled', limbs.hands);
      setChecked('footDetailerEnabled', limbs.feet);
      setValue('limbDetailerGuideSize', limbs.guideSize);
      setValue('limbDetailerSteps', limbs.steps);
      setValue('limbDetailerDenoise', limbs.denoise);
      setValue('handDetailerPositive', limbs.handPositive);
      setValue('handDetailerNegative', limbs.handNegative);
      setValue('footDetailerPositive', limbs.footPositive);
      setValue('footDetailerNegative', limbs.footNegative);
      setChecked('autoColorMatchEnabled', colorMatch.enabled);
      setValue('autoColorMethod', colorMatch.method);
      setValue('autoColorStrength', colorMatch.strength);
      if (typeof outputEnhancementChanged === 'function') outputEnhancementChanged(true);
    }
    if (data.transparentBackground) {
      setValue('transparentBackgroundMode', data.transparentBackground.mode);
      setChecked('transparentKeepOriginal', data.transparentBackground.keepOriginal);
      setValue('transparentDetailMethod', data.transparentBackground.detailMethod);
      setValue('transparentDetailErode', data.transparentBackground.detailErode);
      setValue('transparentDetailDilate', data.transparentBackground.detailDilate);
      setValue('transparentBlackPoint', data.transparentBackground.blackPoint);
      setValue('transparentWhitePoint', data.transparentBackground.whitePoint);
      setValue('transparentMaxMegapixels', data.transparentBackground.maxMegapixels);
      if (typeof transparentBackgroundChanged === 'function') transparentBackgroundChanged(true);
    }
    if (typeof applyIllustriousMode === 'function') applyIllustriousMode();
    if (typeof toggleRegions === 'function') toggleRegions();
  }

  window.restorePayloadToPanel = function (data) {
    if (typeof legacyRestorePayloadToPanel === 'function') legacyRestorePayloadToPanel(data);
    restoreAdvancedPayload(data);
  };

  window.getSnapshot = async function (id) {
    const data = await (await fetch('/api/snapshots')).json();
    if (data.error) throw Error(data.error);
    const item = (data.entries || []).find(entry => entry.id === id);
    if (!item) throw Error('找不到该快照。');
    return item;
  };

  window.loadSnapshots = async function () {
    const root = document.getElementById('snapshotList');
    if (!root) return;
    root.textContent = '正在读取快照…';
    try {
      const data = await (await fetch('/api/snapshots')).json();
      if (data.error) throw Error(data.error);
      const entries = data.entries || [];
      root.innerHTML = entries.slice(0, 40).map(item => {
        const source = item.source || {};
        const generation = source.generation || {};
        const model = text(source.checkpoint, text((item.payload || {}).model, '自动模型')).replace(/\\/g, '/').split('/').pop();
        const loras = (source.loras || []).map(lora => `${text(lora.name)}${lora.weight == null ? '' : `(${escapeHtml(lora.weight)})`}`).filter(Boolean).join(' → ') || '无 LoRA';
        const id = escapeHtml(item.id);
        return `<div class="snapshot-item"><div class="snapshot-head"><b>${escapeHtml(item.label || model || '生成快照')}</b><span>${escapeHtml(snapshotTime(item.createdAt))}</span></div><div>${escapeHtml(model)} · seed ${escapeHtml(generation.seed == null ? '?' : generation.seed)} · ${escapeHtml(loras)}</div><div>${(item.outputs || []).map(name => `<a class="snapshot-output" target="_blank" rel="noreferrer" href="/output?name=${encodeURIComponent(name)}" onclick="return openLinkedImageViewer(event,this)">${escapeHtml(name)}</a>`).join(' · ') || '尚未记录输出'}</div>${sourceTrace(item)}<div class="snapshot-actions"><button type="button" onclick="restoreSnapshot('${id}')">完整恢复</button><button type="button" onclick="restoreSnapshotSeedOnly('${id}')">只换 Seed</button><button type="button" onclick="continueSnapshotEdit('${id}')">继续编辑</button><button type="button" onclick="replaySnapshot('${id}')">完全复现</button><button type="button" onclick="compareSnapshot('${id}')">检查环境差异</button></div><div id="snapshotDiff_${id}"></div></div>`;
      }).join('') || '还没有生成快照。';
    } catch (error) {
      root.textContent = '读取快照失败：' + (error && error.message ? error.message : error);
    }
  };

  window.restoreSnapshot = async function (id) {
    try {
      const item = await window.getSnapshot(id);
      window.restorePayloadToPanel(item.payload);
      document.getElementById('status').textContent = '快照已完整恢复到面板；尚未提交生成。';
    } catch (error) {
      document.getElementById('status').textContent = '恢复失败：' + (error && error.message ? error.message : error);
    }
  };

  window.restoreSnapshotSeedOnly = async function (id) {
    try {
      const item = await window.getSnapshot(id);
      const payload = JSON.parse(JSON.stringify(item.payload || {}));
      const previous = String(payload.seed == null ? '' : payload.seed);
      if (/^\d+$/.test(previous)) {
        try { payload.seed = (BigInt(previous) + 1n).toString(); } catch (_) { payload.seed = String(Math.floor(Math.random() * 900000000000000000) + 1); }
      } else payload.seed = String(Math.floor(Math.random() * 900000000000000000) + 1);
      window.restorePayloadToPanel(payload);
      document.getElementById('status').textContent = '已恢复快照并只更换 Seed；尚未提交生成。';
    } catch (error) {
      document.getElementById('status').textContent = '换 Seed 失败：' + (error && error.message ? error.message : error);
    }
  };

  window.continueSnapshotEdit = async function (id) {
    await window.restoreSnapshot(id);
    const target = document.getElementById('compiledPositive') || document.getElementById('promptSubject');
    if (target) { target.scrollIntoView({ behavior: 'smooth', block: 'center' }); target.focus(); }
    document.getElementById('status').textContent = '快照已恢复；现在可以继续编辑提示词和参数，确认后再生成。';
  };

  window.loadSnapshots();
}());
