/* Presentation and preset navigation only; generation settings stay untouched. */
(function(){
  'use strict';
  const fieldCategories={promptSubject:'subject',promptAppearance:'appearance',promptClothing:'clothing',promptPose:'pose',promptExpression:'expression',promptComposition:'composition',promptScene:'scene',promptLighting:'lighting',promptStyle:'artist'};
  function init(){
    const panel=document.getElementById('userPromptPresetPanel'),editor=panel?.querySelector('.user-preset-editor');
    if(!panel||!editor||document.getElementById('presetEditorFold'))return;
    const fold=document.createElement('details');fold.id='presetEditorFold';fold.className='preset-editor-fold';
    const summary=document.createElement('summary');summary.textContent='新建 / 编辑预设';fold.append(summary);editor.before(fold);fold.append(editor);
    const search=document.getElementById('userPresetSearch'),filter=document.getElementById('userPresetFilter');
    if(search){search.setAttribute('aria-label','搜索我的提示词预设');search.placeholder='搜索名称、英文提示词或使用说明…';}
    if(filter)filter.setAttribute('aria-label','预设分类筛选');
    function browse(category){
      panel.open=true;
      if(category&&filter){filter.value=category;if(search)search.value='';window.renderUserPromptPresets?.();}
      requestAnimationFrame(()=>{search?.scrollIntoView({block:'center',behavior:'smooth'});search?.focus({preventScroll:true});});
    }
    const tools=document.createElement('div');tools.className='preset-browse-tools';
    const browseButton=document.createElement('button');browseButton.type='button';browseButton.textContent='查找我的预设';browseButton.onclick=()=>browse();
    const createButton=document.createElement('button');createButton.type='button';createButton.className='secondary';createButton.textContent='新建 / 编辑预设';createButton.onclick=()=>{panel.open=true;fold.open=true;document.getElementById('userPresetName')?.focus();};
    const hint=document.createElement('span');hint.className='small';hint.textContent='按分区挑选，追加或替换';tools.append(browseButton,createButton,hint);fold.before(tools);
    // Existing edit actions populate the same form before this bubble listener runs.
    panel.addEventListener('click',event=>{if(event.target.closest('button[onclick^="editUserPromptPreset("]')){fold.open=true;document.getElementById('userPresetName')?.focus();}});
    for(const [id,category] of Object.entries(fieldCategories)){
      const area=document.getElementById(id),card=area?.closest('[data-prompt-group]');
      const controls=card?.querySelector('.prompt-chip-controls');if(!controls)continue;
      const button=document.createElement('button');button.type='button';button.className='section-preset-browse';button.textContent='预设';button.title='查找并筛选本分区的个人预设';button.onclick=()=>browse(category);controls.append(button);
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
