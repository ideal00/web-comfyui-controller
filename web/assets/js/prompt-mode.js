/* 中文描述转换的“高级覆写”模式：注入状态覆写规范（解耦 + 三维层叠 + 两阶段拆分）。 */
(function (global) {
  'use strict';

  var MODE_SELECT_ID = 'promptInstructionMode';

  // 与后端 PROMPT_INSTRUCTION_ADVANCED_RULES 保持一致（离线兜底用）。
  var ADVANCED_RULES = [
    '当前为“状态覆写”任务：角色或画面的既有状态需要被改变（破损战损、换装、附着物、多层穿透、解体变形、材质或环境重构等）。必须严格按以下规范执行：',
    '1) 冲突排查与特征解耦：先找出与目标状态冲突的既有属性原词（要露肤就清除 covered navel、full bodysuit；'
      + '要换装就清除原服装词；要破损就清除 intact、pristine 类词），一律清除；把整体概念拆成独立部件逐个改写'
      + '（torn bodysuit、shredded capelet、frayed gloves），禁止只给整体概念追加权重；'
      + '被清除的属性必须成对转移进负面提示词。',
    '2) 三维层叠法（正面提示词按三层堆叠）：结构层 shredded / tattered / frayed fabric / ragged edges / '
      + 'hanging cloth strips / dangling threads；展现层 exposed skin / midriff / navel / skin through clothes / torn revealing X；'
      + '痕迹层 bleeding / blood splatter / blood dripping / grime / soot / ash on skin / scratches on body / bruises'
      + '（非破坏类覆写换成该状态应有的材质与环境痕迹）。',
    '3) 负向截断：动漫与通用底模带有强烈的“光滑、洁净、无瑕、对称”审美先验，负面提示词必须压制与目标状态冲突的'
      + '既有先验：smooth skin、porcelain skin、spotless、clean、pristine、flawless skin、polished、'
      + 'clean clothes、undamaged clothes、intact clothing、fully clothed。',
    '4) 两阶段拆分：一阶段（denoise 1.0）只锁定构图、透视骨架、姿态与角色基调，仅保留轻度倾向，禁止高频噪点词；'
      + '二阶段（denoise 0.45~0.60）剔除一阶段被替换掉的旧属性词，全量注入三维层叠的新状态细节与高频物理细节。',
    '只按以下字段回答，每行一个字段，字段名保持大写英文：',
    'ANALYSIS: 中文一句话，说明清除了哪些冲突词、覆写了哪几层',
    'POSITIVE: 一阶段英文正向提示词（构图 / 姿态 / 角色基调 + 轻度改态倾向）',
    'NEGATIVE: 一阶段英文负面提示词（含被剔除的旧属性）',
    'STAGE2_POSITIVE: 二阶段英文正向提示词（全量三维层叠的新状态细节与材质重塑）',
    'STAGE2_NEGATIVE: 二阶段英文负面提示词',
    'PARAMS: 中文一行，给出建议 denoise 区间、CFG 倾向与 LoRA 双通道权重',
  ].join('\n');

  function byId(id) {
    return document.getElementById(id);
  }

  function currentMode() {
    return (byId(MODE_SELECT_ID) || {}).value || 'standard';
  }

  function syncInstructionModeHint() {
    var hint = byId('instructionModeHint');
    if (!hint) return;
    hint.textContent = currentMode() === 'advanced'
      ? '高级覆写：清除旧属性 → 三维层叠重写 → 输出两阶段提示词'
      : '常规：按模型族把中文转成英文标签';
  }

  /** 按“字段行 + 续行”解析回答，兼容旧的两行格式。 */
  function parseAnswer(raw) {
    var fields = {};
    var current = null;
    String(raw || '')
      .replace(/```[a-zA-Z]*/g, '')
      .replace(/```/g, '')
      .split(/\r?\n/)
      .forEach(function (line) {
        var match = /^\s*([A-Z][A-Z0-9_]{2,})\s*[:：]\s*(.*)$/.exec(line);
        if (match) {
          current = match[1].toUpperCase();
          fields[current] = match[2].trim();
          return;
        }
        if (current && line.trim()) {
          fields[current] += (fields[current] ? ' ' : '') + line.trim();
        }
      });
    return fields;
  }

  function fillExtras(fields) {
    var box = byId('translationExtras');
    if (!box) return;
    var analysis = fields.ANALYSIS || '';
    var params = fields.PARAMS || '';
    var stage2Positive = fields.STAGE2_POSITIVE || '';
    var stage2Negative = fields.STAGE2_NEGATIVE || '';
    var hasExtra = Boolean(analysis || params || stage2Positive || stage2Negative);
    box.style.display = hasExtra ? 'block' : 'none';
    if (byId('translatedAnalysis')) byId('translatedAnalysis').textContent = analysis;
    if (byId('translatedParams')) byId('translatedParams').textContent = params;
    if (byId('translatedStage2Positive')) byId('translatedStage2Positive').value = stage2Positive;
    if (byId('translatedStage2Negative')) byId('translatedStage2Negative').value = stage2Negative;
    if (hasExtra && byId('translationResult')) {
      byId('translationResult').textContent += '（已解析两阶段输出：可复制二阶段提示词用于二次采样 / 高清修复）';
    }
  }

  function copyStage2Prompt() {
    var positive = (byId('translatedStage2Positive') || {}).value || '';
    var negative = (byId('translatedStage2Negative') || {}).value || '';
    if (!positive && !negative) {
      if (byId('translationResult')) byId('translationResult').textContent = '还没有二阶段提示词：请先用“高级覆写”模式转换。';
      return;
    }
    var text = 'STAGE2_POSITIVE: ' + positive + '\nSTAGE2_NEGATIVE: ' + negative;
    if (global.EasyPanelClipboard && typeof global.EasyPanelClipboard.copyText === 'function') {
      try {
        if (global.EasyPanelClipboard.copyText(text) === true) {
          if (byId('translationResult')) byId('translationResult').textContent = '已复制二阶段提示词（denoise 0.45~0.60 时使用）。';
          return;
        }
      } catch (error) { /* 继续走浏览器剪贴板 */ }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        if (byId('translationResult')) byId('translationResult').textContent = '已复制二阶段提示词（denoise 0.45~0.60 时使用）。';
      });
    }
  }

  function install() {
    var originalShared = global.sharedPromptInstruction;
    var originalRead = global.readDeepSeekClipboard;

    if (typeof originalShared === 'function') {
      global.sharedPromptInstruction = async function (text) {
        var mode = currentMode();
        if (mode !== 'advanced') return originalShared(text);
        try {
          var response = await fetch('/api/prompt-instruction', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              text: text,
              mode: 'advanced',
              model: (byId('model') || {}).value || '',
              safetyLevel: (byId('safetyLevel') || {}).value || 'safe',
            }),
          });
          var data = await response.json();
          if (!response.ok || data.error || !data.instruction) {
            throw new Error(data.error || '服务器未返回提示词转换指令');
          }
          return {
            instruction: data.instruction,
            family: data.family || 'illustrious',
            familyLabel: data.family_label || '',
            model: data.model || '',
            mode: data.mode || 'advanced',
          };
        } catch (error) {
          var fallback = await originalShared(text);
          fallback.instruction = String(fallback.instruction || '') + '\n\n' + ADVANCED_RULES;
          fallback.mode = 'advanced';
          return fallback;
        }
      };
    }

    if (typeof originalRead === 'function') {
      global.readDeepSeekClipboard = async function () {
        await originalRead();
        if (!navigator.clipboard || !navigator.clipboard.readText) return;
        try {
          var fields = parseAnswer(await navigator.clipboard.readText());
          fillExtras(fields);
        } catch (error) { /* 读取失败时保持原有行为 */ }
      };
    }
  }

  function boot() {
    var select = byId(MODE_SELECT_ID);
    if (select) select.addEventListener('change', syncInstructionModeHint);
    syncInstructionModeHint();
    install();
    global.syncInstructionModeHint = syncInstructionModeHint;
    global.copyStage2Prompt = copyStage2Prompt;
    global.__promptInstructionMode = { parseAnswer: parseAnswer, rules: ADVANCED_RULES };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(window);
