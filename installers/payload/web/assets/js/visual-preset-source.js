/* Local illustrated tags are section components, not personal saved presets. */
(function(g){
  'use strict';
  let rows=[], loaded=false, pending=null, error='';
  const norm=value=>String(value||'').toLowerCase().replace(/_/g,' ').replace(/\s+/g,' ').trim();
  function candidates(section,query='',limit=Infinity){
    const words=norm(query).split(' ').filter(Boolean);
    return rows.filter(item=>item.section===section && words.every(word=>norm([item.name,item.description,item.category,item.group,...item.tags].join(' ')).includes(word)))
      .map(item=>({...item,source:'preset',origin:'visual',tag:item.name,
        text:g.EasyPanelDialect?.formatTags ? g.EasyPanelDialect.formatTags(item.tags).join(', ') : item.tags.join(', '),
        exampleImage:item.image ? {source:'visual',id:item.visualId} : '',updatedAt:0}))
      .sort((a,b)=>{const q=norm(query),rank=item=>norm(item.name)===q?0:norm(item.name).startsWith(q)?1:2;return rank(a)-rank(b);}).slice(0,limit);
  }
  function ensure(force=false){
    if(pending)return pending;
    if(loaded&&!force)return Promise.resolve(rows);
    pending=fetch('/api/visual-tags/section-presets',{credentials:'same-origin'}).then(async response=>{
      const data=await response.json();if(!response.ok||!data.ok||!Array.isArray(data.results))throw Error(data.error||'可视化图库读取失败');
      rows=data.results.filter(item=>item.id&&item.section&&Array.isArray(item.tags));loaded=true;error='';
      g.dispatchEvent?.(new Event('visualPresetSourceChanged'));return rows;
    }).catch(reason=>{error=reason.message;throw reason;}).finally(()=>{pending=null;});
    return pending;
  }
  g.EasyPanelVisualPresetSource={candidates,ensure,get loaded(){return loaded;},get error(){return error;}};
  if(typeof module!=='undefined'&&module.exports)module.exports=g.EasyPanelVisualPresetSource;
  if(typeof document==='undefined')return;
  const warm=()=>ensure().catch(()=>{});
  document.addEventListener('easy-panel:visual-tag-added',()=>ensure(true).catch(()=>{}));
  document.addEventListener('easy-panel:visual-tag-rebuilt',()=>ensure(true).catch(()=>{}));
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',warm);else warm();
})(typeof window!=='undefined'?window:globalThis);
