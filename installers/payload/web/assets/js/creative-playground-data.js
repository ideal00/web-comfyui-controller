(function (root) {
  'use strict';
  const camera = 'Frame the subject from the head to the hips at eye level with both hands visible.';
  const light = 'Use broad soft light from the front left and faint reflected fill on the shaded cheek.';
  function career(id, name, moment, clothing, pose, expression, scene, extra = {}) {
    return {id, name, moment, sections: {clothing, pose, expression, scene, composition:camera, lighting:light, ...extra}};
  }
  const careers = [
    career('florist','花店 · 花束太大','捧起包装好的花束，花朵挡住下巴，眼睛从上方露出来。',
      'Wear a canvas work apron over a plain long-sleeved shirt and trousers.',
      'Support an oversized wrapped bouquet with one forearm beneath it and the opposite hand around the stems. Keep the flowers just below the nose.',
      'Look over the flowers with raised eyebrows and a small amused smile.',
      'Use a flower shop work area with buckets of flowers and rolls of wrapping paper.'),
    career('barista','咖啡师 · 奶泡画坏了','端出歪歪扭扭的奶泡图案，试图保持专业。',
      'Wear a dark waist apron over a collared shirt with rolled sleeves and straight trousers.',
      'Hold a saucer flat on one palm and steady its edge with the other hand. A cup on the saucer contains an uneven heart-shaped patch of milk foam.',
      'Keep the lips in a restrained smile with one eyebrow slightly raised.',
      'Use a cafe counter with an espresso machine and stacked clean cups.',
      {composition:'Use a slightly elevated waist-up view that reveals the cup surface and the face in the same frame.'}),
    career('librarian','管理员 · 书快滑落','怀里最上面一本书滑开，空出一只手去接。',
      'Wear a knit vest over a buttoned shirt with a long skirt and simple shoes.',
      'Cradle three books against the torso with one forearm. Reach the other hand beneath the top book as it tilts outward from the stack.',
      'Widen the eyes and part the lips slightly while looking toward the slipping book.',
      'Use a library aisle with shelves on both sides and a nearby book cart.'),
    career('mechanic','修理工 · 探头检查','从打开的机盖旁探头，脸上沾了一点油。',
      'Wear full-length work overalls over a plain shirt with sturdy work boots.',
      'Lean around the edge of an open engine hood with one palm resting on its outer rim. Hold a small wrench in the lowered opposite hand.',
      'Look toward the viewer with a pleased closed-mouth smile.',
      'Use a repair workshop with an open vehicle engine bay and a tool cabinet.',
      {manual:'Add a small grease smudge on one cheek.'}),
    career('weather','气象员 · 地图被风吹起','双手抓住地图两角，纸张鼓起来。',
      'Wear a zipped outdoor jacket with straight trousers and weatherproof shoes.',
      'Grip the two upper corners of a folded paper map with separate hands. Let its lower half billow forward in a gust.',
      'Narrow the eyes against the wind with the mouth slightly open.',
      'Use an outdoor observation deck with a weather vane and distant hills.',
      {manual:'Blow the loose hair ends in the same direction as the lifted map edge.'}),
    career('baker','烘焙师 · 面粉鼻尖','端着刚整好的面团，鼻尖沾着面粉。',
      'Wear a clean kitchen apron over a cotton shirt with the sleeves rolled back.',
      'Carry a baking tray with both hands supporting its opposite edges. Place three unbaked dough rolls on the tray.',
      'Glance toward the viewer with a relaxed smile.',
      'Use a bakery preparation room with a wooden workbench and flour containers.',
      {manual:'Place a small dusting of flour on the nose tip and fingertips.'}),
    career('gardener','园艺师 · 发现新芽','蹲在花盆前，用指尖轻轻拨开遮挡的叶子。',
      'Wear a sturdy gardening apron over a long-sleeved shirt with work trousers and boots.',
      'Crouch beside a planter and rest one hand on its rim. Use the other hand to gently part two leaves above a new shoot.',
      'Look down at the shoot with softly raised eyebrows and a small smile.',
      'Use a greenhouse planting bench area with pots and a clear stone walkway.',
      {composition:'Frame the whole crouching figure and the planter from a slightly elevated three-quarter angle.'}),
    career('astronomer','观测员 · 对准星图','望远镜旁一手指着星图，一手调整旋钮。',
      'Wear a quilted field jacket over a high-neck shirt with comfortable trousers.',
      'Place one fingertip on a star chart fixed to a stand and use the opposite hand to turn a telescope adjustment knob.',
      'Direct the gaze toward the chart with a focused brow and relaxed lips.',
      'Use an observatory with a telescope beneath an open dome at night.',
      {lighting:'Use a dim warm task lamp over the chart with weak neutral ambient fill on the face.'})
  ];
  const personalities = [
    {id:'warm', name:'热情', pose:'Lean the torso slightly forward and extend the offering hand farther toward the recipient.', expression:'Meet the recipient\'s gaze with open eyes and a broad welcoming smile.'},
    {id:'shy', name:'害羞', pose:'Keep the shoulders drawn slightly inward and the offering elbow close to the body.', expression:'Glance to the side with a small closed-mouth smile and a faint blush.'},
    {id:'proud', name:'高傲', pose:'Keep the torso upright with the chin slightly lifted and the offering elbow loosely bent.', expression:'Look sideways toward the recipient with a restrained smile and one subtly raised eyebrow.'},
    {id:'tired', name:'疲惫', pose:'Let the shoulders droop and keep the offering elbow low beside the waist.', expression:'Use heavy eyelids and a relaxed closed mouth while looking toward the recipient.'}
  ];
  const actions = [
    {id:'cup',name:'递饮料',pose:'Offer a paper cup in one hand while keeping its opening upright. Rest the other hand beside the body.',scene:'Use a quiet cafe interior with a clear counter behind the subject.'},
    {id:'ticket',name:'递车票',pose:'Offer a single paper ticket held between the thumb and index finger of one hand. Keep the opposite hand lowered.',scene:'Use a quiet railway station concourse with a timetable board in the background.'},
    {id:'flower',name:'递一枝花',pose:'Offer a single flower by its lower stem with one hand. Keep the blossom separated from the face and the other hand lowered.',scene:'Use a garden path bordered by low flowering plants.'}
  ];
  function acting(actionId, personalityId) {
    const a = actions.find(x=>x.id===actionId), p = personalities.find(x=>x.id===personalityId);
    if (!a || !p) throw Error('未知的动作或性格。');
    return {id:`${a.id}_${p.id}`,name:`${a.name} · ${p.name}`,moment:'同组四张只改变姿势细节和表情。',sections:{pose:`${a.pose} ${p.pose}`,expression:p.expression,scene:a.scene,composition:camera,lighting:light}};
  }
  // Original framing diagrams, not AI samples or copies of reference artwork.
  const shots = [
    {id:'portrait',name:'平视近景',ratio:'1:1',size:'1024x1024',scale:1.7,x:50,y:51,depth:false,notes:'主体约占八成；镜头平视；头肩入画；保留发顶。',sections:{composition:'Frame the head and shoulders at eye level with a small margin above the hair. Keep both eyes sharp.'}},
    {id:'full',name:'完整角色展示',ratio:'3:4',size:'1152x1536',scale:.82,x:50,y:48,depth:false,notes:'主体约占八成高度；双手与鞋子完整；背景留呼吸空间。',sections:{composition:'Frame the entire subject at eye level with a clear margin above the head and below both shoes.'}},
    {id:'space',name:'偏侧留白',ratio:'16:9',size:'1536x864',scale:.7,x:28,y:49,depth:false,notes:'人物靠左三分位；右侧留环境；适合远望和等候。',sections:{composition:'Place the full figure in the left third of a wide frame. Leave open space on the right and use a level horizon.'}},
    {id:'hands',name:'脸与手部接触',ratio:'4:3',size:'1536x1152',scale:1.15,x:50,y:55,depth:false,notes:'头至腰部；道具与双手全部入镜；检查手指接触点。',sections:{composition:'Frame from the head to the hips with both hands and the complete held object visible. Keep the face and contact points in focus.'}},
    {id:'door',name:'门框中的人物',ratio:'3:4',size:'1152x1536',scale:.68,x:52,y:48,depth:true,notes:'近处门框作前景；人物在门后；不遮挡面部。',sections:{composition:'Use the near doorway as a foreground frame around the full figure farther inside. Keep the doorframe clear of the face.'}},
    {id:'low',name:'轻低机位',ratio:'3:4',size:'1152x1536',scale:.8,x:50,y:46,depth:false,notes:'镜头在腰部高度；轻微仰视；保留完整腿脚。',sections:{composition:'Place the camera at waist height and angle it gently upward. Show the entire subject with restrained perspective distortion.'}},
    {id:'diagonal',name:'动作前方留白',ratio:'3:4',size:'1152x1536',scale:.72,x:35,y:48,depth:false,notes:'人物偏后侧；移动方向留空；手脚远离边缘。',sections:{composition:'Place the full figure slightly left of center with extra room toward the right for the movement. Keep all extremities inside the frame.'}},
    {id:'world',name:'小人物与大环境',ratio:'16:9',size:'1536x864',scale:.35,x:62,y:61,depth:true,notes:'人物约三分之一画高；近中远三层；适合空间展示。',sections:{composition:'Use a wide view with the subject occupying one third of the image height. Separate a near foreground edge, the middle-ground figure, and the distant environment.'}}
  ];
  const data = {version:1,careers,personalities,actions,acting,shots};
  if (typeof module !== 'undefined' && module.exports) module.exports = data;
  else root.EasyPanelPlaygroundData = data;
})(typeof window !== 'undefined' ? window : globalThis);
