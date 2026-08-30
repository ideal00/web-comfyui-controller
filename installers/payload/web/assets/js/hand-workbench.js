(function () {
'use strict';

const hand = {
  image: null, file: null, sourceUrl: '', editedImage: null, editedUrl: '',
  anchors: [], segments: [], hoverPath: [], closed: false, tool: 'magnetic',
  mask: document.createElement('canvas'), maskTint: document.createElement('canvas'), gradient: null, gray: null,
  draggingAnchor: -1, miniPaintReady: false, miniPaintUrl: '',
};

function el(id) { return document.getElementById(id); }
function status(text, error) { const node=el('handStatus'); node.textContent=text; node.classList.toggle('diagnostic-error',!!error); }
function canvasPoint(event) {
  const canvas=el('handCanvas'), rect=canvas.getBoundingClientRect();
  return {x:Math.max(0,Math.min(canvas.width-1,(event.clientX-rect.left)*canvas.width/rect.width)),y:Math.max(0,Math.min(canvas.height-1,(event.clientY-rect.top)*canvas.height/rect.height))};
}
function imageFromUrl(url) { return new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(Error('图片无法载入。'));image.src=url;}); }
function currentImageUrl() { return hand.editedUrl || hand.sourceUrl; }
let handPaintResizeTimer=0,handPaintUnlockTimer=0,handPaintResizeSequence=0,handPaintActiveResize=0;
function finishMiniPaintResize(id){if(id&&id!==handPaintActiveResize)return;clearTimeout(handPaintUnlockTimer);handPaintActiveResize=0;const dialog=el('handWorkbench'),button=el('handPaintFullscreen');dialog?.classList.remove('paint-resizing');if(button)button.disabled=false}
function scheduleMiniPaintResize(){const dialog=el('handWorkbench'),pane=el('handPaintPane'),frame=el('handMiniPaint'),button=el('handPaintFullscreen');clearTimeout(handPaintResizeTimer);clearTimeout(handPaintUnlockTimer);if(!dialog?.open||pane?.hidden||!frame){finishMiniPaintResize(handPaintActiveResize);return}const resizeId=++handPaintResizeSequence;handPaintActiveResize=resizeId;dialog.classList.add('paint-resizing');if(button)button.disabled=true;handPaintResizeTimer=setTimeout(()=>{frame.contentWindow?.postMessage({source:'easy-panel-hand-workbench',type:'resize-editor',id:resizeId},location.origin);handPaintUnlockTimer=setTimeout(()=>finishMiniPaintResize(resizeId),900)},60)}
function setHandPaintExpanded(expanded){const dialog=el('handWorkbench'),button=el('handPaintFullscreen');dialog.classList.toggle('paint-expanded',!!expanded);if(button){button.textContent=expanded?'退出全屏':'全屏修图';button.setAttribute('aria-pressed',String(!!expanded))}scheduleMiniPaintResize()}
window.toggleHandPaintFullscreen=function(){setHandPaintExpanded(!el('handWorkbench').classList.contains('paint-expanded'));};

async function loadSource(file, url) {
  if (!url && !file) return;
  if (hand.sourceUrl && hand.sourceUrl.startsWith('blob:')) URL.revokeObjectURL(hand.sourceUrl);
  if (hand.editedUrl) URL.revokeObjectURL(hand.editedUrl);
  hand.sourceUrl=url || URL.createObjectURL(file); hand.file=file || null; hand.editedUrl=''; hand.editedImage=null; hand.miniPaintUrl='';
  try { hand.image=await imageFromUrl(hand.sourceUrl); } catch (error) { status(error.message,true); return; }
  const canvas=el('handCanvas'), scale=Math.min(1,1200/Math.max(hand.image.naturalWidth,hand.image.naturalHeight));
  canvas.width=Math.max(1,Math.round(hand.image.naturalWidth*scale)); canvas.height=Math.max(1,Math.round(hand.image.naturalHeight*scale));
  hand.mask.width=canvas.width; hand.mask.height=canvas.height; hand.mask.getContext('2d').clearRect(0,0,canvas.width,canvas.height);
  window.handClearSelection(false); prepareEdges(); el('handCanvasEmpty').hidden=true; render(); sendToMiniPaint();
  status(`已载入 ${hand.image.naturalWidth}×${hand.image.naturalHeight}。沿手部边缘点击锚点，磁性路径会自动贴边。`);
}

function prepareEdges() {
  const canvas=el('handCanvas'), tmp=document.createElement('canvas'); tmp.width=canvas.width;tmp.height=canvas.height;
  const ctx=tmp.getContext('2d',{willReadFrequently:true});ctx.drawImage(hand.image,0,0,canvas.width,canvas.height);
  const data=ctx.getImageData(0,0,canvas.width,canvas.height).data,n=canvas.width*canvas.height;
  hand.gray=new Float32Array(n);hand.gradient=new Float32Array(n);
  for(let i=0;i<n;i++)hand.gray[i]=data[i*4]*.299+data[i*4+1]*.587+data[i*4+2]*.114;
  let max=1;
  for(let y=1;y<canvas.height-1;y++)for(let x=1;x<canvas.width-1;x++){
    const i=y*canvas.width+x,gx=-hand.gray[i-canvas.width-1]-2*hand.gray[i-1]-hand.gray[i+canvas.width-1]+hand.gray[i-canvas.width+1]+2*hand.gray[i+1]+hand.gray[i+canvas.width+1],gy=-hand.gray[i-canvas.width-1]-2*hand.gray[i-canvas.width]-hand.gray[i-canvas.width+1]+hand.gray[i+canvas.width-1]+2*hand.gray[i+canvas.width]+hand.gray[i+canvas.width+1],g=Math.hypot(gx,gy);hand.gradient[i]=g;if(g>max)max=g;
  }
  for(let i=0;i<n;i++)hand.gradient[i]/=max;
}

class MinHeap {
  constructor(){this.a=[]} push(item){const a=this.a;a.push(item);let i=a.length-1;while(i){const p=(i-1)>>1;if(a[p][0]<=item[0])break;a[i]=a[p];i=p}a[i]=item}
  pop(){const a=this.a,root=a[0],last=a.pop();if(a.length){let i=0;while(true){let l=i*2+1,r=l+1;if(l>=a.length)break;let c=r<a.length&&a[r][0]<a[l][0]?r:l;if(a[c][0]>=last[0])break;a[i]=a[c];i=c}a[i]=last}return root} get length(){return this.a.length}
}

function magneticPath(start,end) {
  const w=el('handCanvas').width,h=el('handCanvas').height,r=Number(el('handSnapRadius').value||72);
  const minX=Math.max(0,Math.floor(Math.min(start.x,end.x)-r)),maxX=Math.min(w-1,Math.ceil(Math.max(start.x,end.x)+r)),minY=Math.max(0,Math.floor(Math.min(start.y,end.y)-r)),maxY=Math.min(h-1,Math.ceil(Math.max(start.y,end.y)+r));
  const rw=maxX-minX+1,rh=maxY-minY+1,total=rw*rh,dist=new Float32Array(total),prev=new Int32Array(total);dist.fill(Infinity);prev.fill(-1);
  const sx=Math.round(start.x)-minX,sy=Math.round(start.y)-minY,tx=Math.round(end.x)-minX,ty=Math.round(end.y)-minY,s=sy*rw+sx,t=ty*rw+tx,heap=new MinHeap();dist[s]=0;heap.push([0,s]);
  const dirs=[[-1,-1,1.414],[0,-1,1],[1,-1,1.414],[-1,0,1],[1,0,1],[-1,1,1.414],[0,1,1],[1,1,1.414]];
  while(heap.length){const [cost,i]=heap.pop();if(cost!==dist[i])continue;if(i===t)break;const x=i%rw,y=(i/rw)|0;
    for(const [dx,dy,step] of dirs){const nx=x+dx,ny=y+dy;if(nx<0||ny<0||nx>=rw||ny>=rh)continue;const ni=ny*rw+nx,gi=(ny+minY)*w+nx+minX,edge=hand.gradient[gi]||0,straight=Math.abs(dx)+Math.abs(dy)===1?.02:0,next=cost+step*(.035+Math.pow(1-edge,2.2)*4)+straight;if(next<dist[ni]){dist[ni]=next;prev[ni]=i;heap.push([next,ni])}}
  }
  if(prev[t]<0)return [start,end];const path=[];for(let i=t;i>=0;i=prev[i]){path.push({x:i%rw+minX,y:((i/rw)|0)+minY});if(i===s)break}path.reverse();return path;
}

function rebuildSegments(){hand.segments=[];for(let i=1;i<hand.anchors.length;i++)hand.segments.push(magneticPath(hand.anchors[i-1],hand.anchors[i]));if(hand.closed&&hand.anchors.length>2)hand.segments.push(magneticPath(hand.anchors.at(-1),hand.anchors[0]));if(hand.closed)fillPathMask();}
function combinedPath(includeHover){const points=[];for(const segment of hand.segments)points.push(...(points.length?segment.slice(1):segment));if(includeHover&&hand.hoverPath.length)points.push(...hand.hoverPath.slice(1));return points;}
function fillPathMask(){const points=combinedPath(false),ctx=hand.mask.getContext('2d');ctx.clearRect(0,0,hand.mask.width,hand.mask.height);if(points.length<3)return;ctx.fillStyle='#fff';ctx.beginPath();ctx.moveTo(points[0].x,points[0].y);for(const p of points.slice(1))ctx.lineTo(p.x,p.y);ctx.closePath();ctx.fill();}

function render() {
  const canvas=el('handCanvas'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);if(!hand.image)return;
  ctx.drawImage(hand.editedImage||hand.image,0,0,canvas.width,canvas.height);
  if(hand.mask.width){
    // Build the red selection preview on an isolated canvas. Compositing it on the
    // image canvas would let the already-drawn photo become the source-in mask and
    // tint the entire photo even when the actual selection is empty.
    if(hand.maskTint.width!==canvas.width||hand.maskTint.height!==canvas.height){hand.maskTint.width=canvas.width;hand.maskTint.height=canvas.height;}
    const tint=hand.maskTint.getContext('2d');tint.clearRect(0,0,canvas.width,canvas.height);tint.fillStyle='#ff315e';tint.fillRect(0,0,canvas.width,canvas.height);tint.globalCompositeOperation='destination-in';tint.drawImage(hand.mask,0,0);tint.globalCompositeOperation='source-over';
    ctx.save();ctx.globalAlpha=.43;ctx.drawImage(hand.maskTint,0,0);ctx.restore();
  }
  const path=combinedPath(!hand.closed);if(path.length){ctx.save();ctx.lineWidth=Math.max(1.5,2/canvas.clientWidth*canvas.width);ctx.strokeStyle='#70e7ff';ctx.shadowColor='#000';ctx.shadowBlur=3;ctx.beginPath();ctx.moveTo(path[0].x,path[0].y);for(const p of path.slice(1))ctx.lineTo(p.x,p.y);ctx.stroke();ctx.restore();}
  for(let i=0;i<hand.anchors.length;i++){const p=hand.anchors[i];ctx.beginPath();ctx.arc(p.x,p.y,i===0?6:4,0,Math.PI*2);ctx.fillStyle=i===hand.draggingAnchor?'#ffd166':i===0?'#72ff9b':'#fff';ctx.fill();ctx.strokeStyle='#111';ctx.stroke();}
}

function nearestAnchor(p){let best=-1,d=Infinity;hand.anchors.forEach((a,i)=>{const n=Math.hypot(a.x-p.x,a.y-p.y);if(n<d){d=n;best=i}});return d<18?best:-1;}
function pointerDown(event){if(!hand.image)return;const p=canvasPoint(event);if(hand.tool==='anchor'){hand.draggingAnchor=nearestAnchor(p);render();return}if(hand.tool==='wand'){magicWand(p);return}if(hand.closed)return;
  if(hand.anchors.length>2&&Math.hypot(p.x-hand.anchors[0].x,p.y-hand.anchors[0].y)<16){window.handClosePath();return}
  if(hand.anchors.length)hand.segments.push(magneticPath(hand.anchors.at(-1),p));hand.anchors.push(p);hand.hoverPath=[];render();status(`已放置 ${hand.anchors.length} 个锚点。继续沿轮廓点击，靠近绿色起点即可闭合。`);
}
function pointerMove(event){if(!hand.image)return;const p=canvasPoint(event);if(hand.tool==='anchor'&&hand.draggingAnchor>=0){hand.anchors[hand.draggingAnchor]=p;rebuildSegments();render();return}if(hand.tool==='magnetic'&&!hand.closed&&hand.anchors.length){hand.hoverPath=magneticPath(hand.anchors.at(-1),p);render();}}
function pointerUp(){hand.draggingAnchor=-1;}

function magicWand(p){const w=hand.mask.width,h=hand.mask.height,x0=Math.round(p.x),y0=Math.round(p.y),seed=hand.gray[y0*w+x0],tol=Number(el('handTolerance').value||28),seen=new Uint8Array(w*h),queue=new Int32Array(w*h);let head=0,tail=0;queue[tail++]=y0*w+x0;seen[y0*w+x0]=1;const ctx=hand.mask.getContext('2d'),img=ctx.createImageData(w,h);
  while(head<tail){const i=queue[head++],x=i%w,y=(i/w)|0;if(Math.abs(hand.gray[i]-seed)>tol)continue;img.data[i*4]=img.data[i*4+1]=img.data[i*4+2]=img.data[i*4+3]=255;for(const ni of [i-1,i+1,i-w,i+w])if(ni>=0&&ni<w*h&&!seen[ni]&&Math.abs((ni%w)-x)<=1){seen[ni]=1;queue[tail++]=ni}}
  ctx.putImageData(img,0,0);hand.anchors=[];hand.segments=[];hand.closed=true;render();status(`魔棒已按容差 ${tol} 生成选区，可继续扩展、收缩或羽化。`);
}

function morphMask(amount){amount=Math.round(Number(amount)||0);if(!amount)return;const w=hand.mask.width,h=hand.mask.height,src=hand.mask.getContext('2d').getImageData(0,0,w,h),out=new ImageData(w,h),radius=Math.min(80,Math.abs(amount)),grow=amount>0;
  const binary=new Uint8Array(w*h);for(let i=0;i<binary.length;i++)binary[i]=src.data[i*4+3]>20?1:0;
  const horizontal=new Uint8Array(w*h);for(let y=0;y<h;y++){let sum=0;for(let x=-radius;x<=radius;x++)if(x>=0&&x<w)sum+=binary[y*w+x];for(let x=0;x<w;x++){horizontal[y*w+x]=grow?(sum>0):(sum===radius*2+1||sum===Math.min(w,radius*2+1));const remove=x-radius,add=x+radius+1;if(remove>=0)sum-=binary[y*w+remove];if(add<w)sum+=binary[y*w+add]}}
  for(let x=0;x<w;x++){let sum=0;for(let y=-radius;y<=radius;y++)if(y>=0&&y<h)sum+=horizontal[y*w+x];for(let y=0;y<h;y++){const need=Math.min(h,radius*2+1),on=grow?sum>0:sum===need,i=y*w+x;if(on)out.data.set([255,255,255,255],i*4);const remove=y-radius,add=y+radius+1;if(remove>=0)sum-=horizontal[remove*w+x];if(add<h)sum+=horizontal[add*w+x]}}
  hand.mask.getContext('2d').putImageData(out,0,0);render();
}
function featherMask(radius){radius=Math.max(0,Math.min(50,Number(radius)||0));if(!radius)return;const tmp=document.createElement('canvas');tmp.width=hand.mask.width;tmp.height=hand.mask.height;const ctx=tmp.getContext('2d');ctx.filter=`blur(${radius}px)`;ctx.drawImage(hand.mask,0,0);const target=hand.mask.getContext('2d');target.clearRect(0,0,hand.mask.width,hand.mask.height);target.drawImage(tmp,0,0);render();}

window.openHandWorkbench=async function(){const dialog=el('handWorkbench');if(!dialog.open)dialog.showModal();await refreshOutputs();if(repairImageFile&&!hand.image)loadSource(repairImageFile);};
window.closeHandWorkbench=function(){el('handWorkbench').close();};
window.handLoadFile=function(file){if(file)loadSource(file);};
window.handLoadOutput=async function(){const name=el('handSourceOutput').value;if(!name)return;status('正在读取输出图片…');const response=await fetch('/output?name='+encodeURIComponent(name));if(!response.ok){status('无法读取该输出图片。',true);return}const blob=await response.blob(),file=new File([blob],name,{type:blob.type||'image/png'});loadSource(file,URL.createObjectURL(file));};
async function refreshOutputs(){try{const data=await(await fetch('/api/output-images')).json();el('handSourceOutput').innerHTML='<option value="">— 从最近输出选择 —</option>'+(data.entries||[]).map(e=>`<option value="${String(e.name).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}">${e.name}</option>`).join('')}catch{}}
window.setHandTab=function(tab){if(tab!=='paint')setHandPaintExpanded(false);for(const name of ['select','paint','compare']){el('hand'+name[0].toUpperCase()+name.slice(1)+'Pane').hidden=name!==tab;el('handTab'+name[0].toUpperCase()+name.slice(1)).classList.toggle('active',name===tab)}if(tab==='paint'){sendToMiniPaint();scheduleMiniPaintResize()}if(tab==='compare')window.renderHandCompare();};
window.setHandTool=function(tool){hand.tool=tool;for(const name of ['Magnetic','Anchor','Wand'])el('handTool'+name).classList.toggle('active',tool===name.toLowerCase());status(tool==='magnetic'?'沿轮廓点击锚点，青色线会自动吸附边缘。':tool==='anchor'?'拖动白色或绿色锚点可修正路径。':'点击颜色相近且连续的区域生成选区。');};
window.handClosePath=function(){if(hand.anchors.length<3){status('至少需要 3 个锚点才能闭合选区。',true);return}hand.closed=true;hand.hoverPath=[];rebuildSegments();render();status('选区已闭合。可调整锚点，或扩缩、羽化、反选后转为 AI 蒙版。');};
window.handUndoAnchor=function(){if(!hand.anchors.length)return;hand.closed=false;hand.anchors.pop();rebuildSegments();hand.mask.getContext('2d').clearRect(0,0,hand.mask.width,hand.mask.height);render();};
window.handClearSelection=function(show=true){hand.anchors=[];hand.segments=[];hand.hoverPath=[];hand.closed=false;hand.draggingAnchor=-1;if(hand.mask.width)hand.mask.getContext('2d').clearRect(0,0,hand.mask.width,hand.mask.height);render();if(show)status('选区已清空。');};
window.handApplyGrow=function(){morphMask(Number(el('handGrow').value));status('已应用选区扩展/收缩。');};
window.handApplyFeather=function(){featherMask(Number(el('handFeather').value));status('已应用选区羽化。');};
window.handInvertSelection=function(){const ctx=hand.mask.getContext('2d'),img=ctx.getImageData(0,0,hand.mask.width,hand.mask.height);for(let i=0;i<img.data.length;i+=4){const a=255-img.data[i+3];img.data[i]=img.data[i+1]=img.data[i+2]=255;img.data[i+3]=a}ctx.putImageData(img,0,0);render();status('已反选。');};

window.handSendMaskToRepair=async function(){try{if(!hand.image||!hand.file){status('请先载入图片。',true);return}let pixels=0,d=hand.mask.getContext('2d',{willReadFrequently:true}).getImageData(0,0,hand.mask.width,hand.mask.height).data;for(let i=3;i<d.length;i+=4)if(d[i]>8)pixels++;if(!pixels){status('当前选区为空。',true);return}
  const repairCanvas=el('repairCanvas'),scale=Math.min(1,1024/Math.max(hand.image.naturalWidth,hand.image.naturalHeight));repairCanvas.width=Math.max(1,Math.round(hand.image.naturalWidth*scale));repairCanvas.height=Math.max(1,Math.round(hand.image.naturalHeight*scale));
  repairImg=hand.editedImage||hand.image;repairImageFile=hand.file;repairMaskCv=document.createElement('canvas');repairMaskCv.width=repairCanvas.width;repairMaskCv.height=repairCanvas.height;repairMaskCv.getContext('2d').drawImage(hand.mask,0,0,repairCanvas.width,repairCanvas.height);repairUndoStack=[];repairTintCv=null;repairUpload={image:'',mask:''};
  if(el('illustriousMode'))el('illustriousMode').value='repair';if(el('repairControls'))el('repairControls').style.display='block';renderRepairView();el('handWorkbench').close();el('repairStatus').textContent=`已从手部工作台接收蒙版（${pixels.toLocaleString()} px），请点击“上传蒙版”后生成。`;el('repairControls').scrollIntoView({behavior:'smooth',block:'center'});
  }catch(error){status('蒙版回传失败：'+error.message,true);}
};

function sendToMiniPaint(){const url=currentImageUrl();if(!hand.miniPaintReady||!url||url===hand.miniPaintUrl)return;hand.miniPaintUrl=url;el('handMiniPaint').contentWindow.postMessage({source:'easy-panel-hand-workbench',type:'load-image',url},location.origin);}
window.handExportMiniPaint=function(){if(!hand.miniPaintReady){status('miniPaint 仍在载入。',true);return}status('正在从 miniPaint 合并图层…');el('handMiniPaint').contentWindow.postMessage({source:'easy-panel-hand-workbench',type:'export-image'},location.origin);};
window.addEventListener('message',async event=>{if(event.origin!==location.origin||event.source!==el('handMiniPaint')?.contentWindow||event.data?.source!=='easy-panel-minipaint')return;if(event.data.type==='resize-complete'){finishMiniPaintResize(event.data.id);return}if(event.data.type==='ready'){hand.miniPaintReady=true;sendToMiniPaint()}if(event.data.type==='export-image'&&event.data.url){if(hand.editedUrl)URL.revokeObjectURL(hand.editedUrl);const blob=await(await fetch(event.data.url)).blob();hand.editedUrl=URL.createObjectURL(blob);hand.miniPaintUrl=hand.editedUrl;hand.editedImage=await imageFromUrl(hand.editedUrl);hand.file=new File([blob],'hand_repaired.png',{type:'image/png'});render();window.renderHandCompare();window.setHandTab('compare');status('miniPaint 修图结果已回传。可对比，也可返回智能选区继续制作 AI 蒙版。');}});
window.renderHandCompare=function(){const canvas=el('handCompareCanvas');if(!hand.image)return;const scale=Math.min(1,1200/Math.max(hand.image.naturalWidth,hand.image.naturalHeight));canvas.width=Math.round(hand.image.naturalWidth*scale);canvas.height=Math.round(hand.image.naturalHeight*scale);const ctx=canvas.getContext('2d'),split=canvas.width*Number(el('handCompareRange').value||50)/100;ctx.drawImage(hand.editedImage||hand.image,0,0,canvas.width,canvas.height);ctx.save();ctx.beginPath();ctx.rect(0,0,split,canvas.height);ctx.clip();ctx.drawImage(hand.image,0,0,canvas.width,canvas.height);ctx.restore();ctx.fillStyle='#fff';ctx.fillRect(split-1,0,2,canvas.height);el('handCompareInfo').textContent=hand.editedImage?'左侧原图 / 右侧 miniPaint 修复图':'尚无修复图，当前两侧均为原图。';};

const canvas=el('handCanvas');canvas.addEventListener('pointerdown',pointerDown);canvas.addEventListener('pointermove',pointerMove);canvas.addEventListener('pointerup',pointerUp);canvas.addEventListener('pointercancel',pointerUp);canvas.addEventListener('pointerleave',()=>{if(hand.tool==='magnetic'){hand.hoverPath=[];render()}});
el('handWorkbench').addEventListener('close',()=>setHandPaintExpanded(false));
const miniPaintFrame=el('handMiniPaint');if(typeof ResizeObserver!=='undefined'&&miniPaintFrame)new ResizeObserver(scheduleMiniPaintResize).observe(miniPaintFrame);
})();
