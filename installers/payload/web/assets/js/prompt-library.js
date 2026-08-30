(function () {
'use strict';

// Illustrious-first: dedicated groups prioritize canonical Danbooru tags and
// official/checkpoint quality controls. General groups retain broader phrases.
// Chinese labels are UI copy; English values are the prompts written to fields.
const rows = (section, source) => source.trim().split('\n').map(line => {
  const split = line.indexOf('|');
  return [line.slice(0, split).trim(), line.slice(split + 1).trim(), section];
});
const combine = (...groups) => groups.flat();

window.EASY_PANEL_PROMPT_LIBRARY = {
  '常用精选': combine(
    rows('style', `
杰作|masterpiece
最佳质量|best quality
惊艳质量|amazing quality
高分辨率|highres
超高分辨率|absurdres
唯美画面|very aesthetic
动漫插画|official art
干净线稿|lineart`),
    rows('subject', `
单个女孩|1girl, solo
成年女性|1girl, mature female
双人构图|2girls`),
    rows('pose', `
自然站立|standing
优雅坐姿|sitting, elegant pose
看向观众|looking at viewer
回眸|looking back
动态姿势|dynamic pose`),
    rows('composition', `
全身像|full body
大腿以上|cowboy shot
上半身|upper body
面部特写|portrait, close-up
消失点构图|vanishing point`),
    rows('scene', `
风景背景|scenery
纯色背景|simple background
室内窗边|indoors, window
城市夜景|cityscape, night`),
    rows('lighting', `
柔和窗光|sunlight, window shadow
电影逆光|backlighting, lens flare
阳光光束|sunbeam, light rays
侧面光|sidelighting`)
  ),

  '光辉·质量与画风': rows('style', `
杰作|masterpiece
最佳质量|best quality
优秀质量|good quality
惊艳质量|amazing quality
唯美画面|very aesthetic
高分辨率|highres
超高分辨率|absurdres
最新画风|newest
2024年画风|year 2024
2023年画风|year 2023
动漫上色|anime coloring
概念艺术|concept art
官方作品|official art
官方画风|official style
风格模仿|style parody
名画模仿|fine art parody
复古画风|retro artstyle
七十年代画风|1970s (style)
八十年代画风|1980s (style)
九十年代画风|1990s (style)
二〇〇〇年代画风|2000s (style)
二〇一〇年代画风|2010s (style)
新艺术风格|art nouveau
浮世绘|ukiyo-e
卡通画风|toon (style)
Q版|chibi
像素艺术|pixel art
三维画面|3d
写实风格|realistic
摄影写实|photorealistic
传统媒介|traditional media
绘画媒介|painting (medium)
水彩媒介|watercolor (medium)
水彩铅笔|watercolor pencil (medium)
油画媒介|oil painting (medium)
丙烯颜料|acrylic paint (medium)
水粉媒介|gouache (medium)
墨水媒介|ink (medium)
水墨画|ink wash painting
书法笔触|calligraphy brush (medium)
蘸水笔|nib pen (medium)
针管笔|millipen (medium)
马克笔|marker (medium)
圆珠笔|ballpoint pen (medium)
石墨铅笔|graphite (medium)
彩色铅笔|colored pencil (medium)
粉彩媒介|pastel (medium)
厚涂|impasto
照片媒介|photo (medium)
草图|sketch
线稿|lineart
无线稿|no lineart
平涂|flat color
赛璐璐阴影|cel shading
渐变色|gradient
局部强调色|spot color
局部上色|partially colored
彩色描线|color trace
有限色板|limited palette
灰调配色|muted color
淡雅配色|pale color
粉彩配色|pastel colors
鲜艳色彩|colorful
单色画面|monochrome
灰阶画面|greyscale
灰阶彩色背景|greyscale with colored background
多格单色|multiple monochrome
彩虹渐变|rainbow gradient
渐变背景|gradient background
多色背景|multicolored background
胶片颗粒|film grain
色差|chromatic aberration
暗角|vignetting`),

  '光辉·表情标签': rows('pose', `
微笑|smile
轻微微笑|light smile
露齿笑|grin
邪恶咧嘴笑|evil grin
邪恶微笑|evil smile
得意坏笑|smirk
魅惑微笑|seductive smile
大笑|laughing
紧张微笑|nervous smile
悲伤微笑|sad smile
疯狂微笑|crazy smile
勉强微笑|forced smile
虚假微笑|false smile
张嘴|open mouth
闭嘴|closed mouth
微张嘴唇|parted lips
波浪嘴|wavy mouth
栗子嘴|chestnut mouth
三角嘴|triangle mouth
歪嘴|sideways mouth
嘟起嘴唇|puckered lips
抿嘴|pursed lips
皱眉|frown
怒容|scowl
生气|angry
不耐烦|annoyed
眉头紧锁|furrowed brow
严肃|serious
面无表情|expressionless
困惑|confused
惊讶|surprised
害怕|scared
担忧|worried
紧张|nervous
尴尬|embarrassed
害羞|shy
慌乱脸红|flustered
悲伤|sad
哭泣|crying
抽泣|sobbing
噘嘴|pout
闹别扭|sulking
失望|disappointed
消沉|depressed
孤独|lonely
坚定|determined
自鸣得意|smug
兴奋|excited
开心|happy
困倦|sleepy
无聊|bored
叹气|sigh
醉态|drunk
恍惚|dazed
疯狂|crazy
病娇|yandere
脸红|blush
满脸通红|full-face blush
鼻尖脸红|nose blush
轻微脸红|light blush
耳朵泛红|ear blush
眼泪|tears
泪流不止|streaming tears
泪滴|teardrop
眼含泪光|tearing up
湿润眼眸|watery eyes
单滴眼泪|single tear
喜极而泣|happy tears
睁眼哭泣|crying with eyes open
疯狂眼神|crazy eyes
空洞眼神|empty eyes
呆滞眼神|blank eyes
眯眼|narrowed eyes
半闭眼|half-closed eyes
闭眼|closed eyes
单眼闭合|one eye closed
闪亮眼睛|sparkling eyes
发光眼睛|glowing eyes
爱心瞳孔|heart-shaped pupils
星形瞳孔|star-shaped pupils
瞳孔收缩|constricted pupils
瞳孔放大|dilated pupils
竖瞳|slit pupils
三白眼|sanpaku
冷淡眼神|jitome
下垂眼|tareme
上挑眼|tsurime
挑眉|raised eyebrow
V形眉毛|v-shaped eyebrows`),

  '光辉·成人主体（仅成年）': rows('subject', `
单个成年女性|1girl, mature female, solo
单个成年男性|1boy, mature male, solo
两名成年女性|2girls, mature female
两名成年男性|2boys, mature male
成年男女双人|1girl, 1boy, mature female, mature male
多名成年女性|multiple girls, mature female
多名成年男性|multiple boys, mature male`),

  '光辉·成人反应（仅成年）': rows('pose', `
性唤起|aroused
高潮反应|orgasm
高潮脸|ahegao
高潮后失神|fucked silly
急促呼吸|heavy breathing
身体颤抖|trembling
剧烈发抖|shaking
出汗|sweat
大量出汗|sweating profusely
可见唾液|saliva
流涎|drooling
唾液拉丝|saliva trail
唾液滴落|saliva drip
筋疲力尽|exhausted
放松表情|relaxed
亲昵表情|affectionate
不开心|unhappy
茫然凝视|blank stare
低垂眼神|downcast eyes
眼球上翻|rolling eyes
睁大眼睛|wide-eyed
凝视|staring
一瞥|glance
舌头可见|tongue`),

  '光辉·成人裸露与遮挡（仅成年）': rows('clothing', `
裸体|nude
完全裸体|completely nude
上身裸体|topless
下身裸体|bottomless
暴露服装|revealing clothes
胸部可见|breasts
乳头可见|nipples
女性生殖器可见|pussy
男性生殖器可见|penis
睾丸可见|testicles
臀部可见|ass
裸露肩膀|bare shoulders
乳沟|cleavage
侧乳|sideboob
下乳|underboob
已审查遮挡|censored
马赛克遮挡|mosaic censoring
黑条遮挡|bar censor
巧妙遮挡|convenient censoring
画面外遮挡|out-of-frame censoring
无遮挡|uncensored`),

  '光辉·成人互动（仅成年自愿）': rows('pose', `
性行为|sex
暗示性行为|implied sex
事后情境|after sex
口部性行为|oral
口交（对男性）|fellatio
口交（对女性）|cunnilingus
手部刺激（男性）|handjob
手指刺激|fingering
自慰|masturbation
相互自慰|mutual masturbation
多人性行为|group sex
三人性行为|threesome
多人群交|orgy
后入体位|sex from behind
传教士体位|missionary
女上位|cowgirl position
反向女上位|reverse cowgirl position
站立性行为|standing sex
阴道性交|vaginal
肛交|anal`),

  '光辉·成人体液（仅成年）': rows('manual', `
精液|cum
体表精液|cum on body
衣物上的精液|cum on clothes
口内精液|cum in mouth
舌头上的精液|cum on tongue
胸部上的精液|cum on breasts
臀部上的精液|cum on ass
女性生殖器上的精液|cum on pussy
男性生殖器上的精液|cum on penis
颜射|facial
唾液|saliva
汗液|sweat
泪液|tears`),

  '光辉·光线与氛围': rows('lighting', `
光线|light
阳光|sunlight
逆光|backlighting
侧面光|sidelighting
下方打光|underlighting
轮廓光|rim lighting
光芒|light rays
太阳光束|sunbeam
光柱|light beam
斑驳阳光|dappled sunlight
阴影|shadow
彩色阴影|colored shadow
投影|drop shadow
不同方向阴影|different shadow
不祥阴影|ominous shadow
眼部藏于阴影|eyes in shadow
高反差|high contrast
低反差|low contrast
聚光灯|spotlight
探照灯|searchlight
舞台灯光|stage lights
城市灯光|city lights
霓虹灯光|neon lights
天花板灯|ceiling light
屏幕光|screen light
吊灯光源|hanging light
天窗光|skylight
烛光|candlelight
月光|moonlight
车灯|headlight
手电筒光|flashlight
圣诞彩灯|christmas lights
串灯|string of light bulbs
手持荧光棒|penlight
紫外线灯|ultraviolet light
发光|glowing
外发光|outer glow
泛光|bloom
镜头光晕|lens flare
过量镜头光晕|lens flare abuse
光粒子|light particles
光轨|light trail
闪光|sparkle
焦散光|caustics
倒影|reflection
折射|refraction
虹彩|iridescent
余晖|afterglow
放射状阳光|sunburst
剪影|silhouette
白天|day
夜晚|night
黎明|dawn
黄昏|dusk
薄暮|twilight
日出|sunrise
日落|sunset
太阳|sun
月亮|moon
满月|full moon
新月|crescent moon
半月|half moon
红月|red moon
多个月亮|multiple moons
蓝天|blue sky
多云天空|cloudy sky
阴天|overcast
云|cloud
夜空|night sky
星空|starry sky
天空星星|star (sky)
银河|milky way
流星|shooting star
橙色天空|orange sky
粉色天空|pink sky
紫色天空|purple sky
红色天空|red sky
黄色天空|yellow sky
绿色天空|green sky
多色天空|multicolored sky
暗色天空|dark sky
暗色背景|dark background
黑暗房间|dark room
黑暗|darkness
暗调|dark
极光|aurora
彩虹|rainbow
雾|fog
霾|haze
烟雾|smoke
蒸汽|steam
余烬|embers
火花|spark
火焰光源|fire
雨|rain
湿润表面|wet
水洼反光|puddle
飘雪|snowing
风|wind
闪电|lightning
暴风雨|storm
乌云|dark clouds
背景虚化|blurry background
前景虚化|blurry foreground
散景|bokeh
景深|depth of field
动态模糊|motion blur
柔焦|soft focus
过曝|overexposure`),

  '通用·质量与画风': rows('style', `
杰作|masterpiece
最佳质量|best quality
惊艳质量|amazing quality
优秀质量|great quality
唯美画面|very aesthetic
审美画面|very aesthetic
高分辨率|highres
超高分辨率|absurdres
无文字|no text
最新画风|newest
2024年画风|year 2024
2023年画风|year 2023
动漫插画|anime coloring
精细插画|concept art
干净线稿|lineart
厚涂|impasto
水彩画|watercolor (medium)
油画|oil painting (medium)
赛璐璐上色|flat color
柔和上色|pastel (medium)
精细上色|colorful
半写实|realistic
写实风格|realistic
摄影感|photorealistic
三维渲染|3d
电影质感|film grain
超精细细节|ultra detailed
高度精细|highly detailed
丰富细节|intricate details
精细背景|detailed background
锐利焦点|sharp focus
清晰轮廓|crisp edges
精修插画|polished illustration
专业插画|professional illustration
细腻质感|fine texture
高细节纹理|detailed textures
复古插画|retro artstyle
极简风格|simple background
鲜艳色彩|colorful
柔和色彩|pastel (medium)
低饱和色彩|limited palette
单色画面|monochrome
柔和配色|soft colors
灰调配色|muted colors
高饱和配色|vibrant colors
暖色调色板|warm color palette
冷色调色板|cool color palette
互补色配色|complementary colors
邻近色配色|analogous colors
电影级调色|cinematic color grading
渐变上色|gradient coloring
光泽上色|glossy coloring
柔和阴影上色|soft shading
硬边阴影上色|hard shading
赛璐璐阴影|cel shading
绘画式阴影|painterly shading
官方作品|official art
概念艺术|concept art
草图|sketch
标准线稿|lineart
清爽线稿|clean lineart
流畅线稿|smooth lineart
柔和线稿|soft lineart
粗线稿|bold lineart
多变线宽|varied line weight
精细墨线|fine ink lines
传统媒介|traditional media
水彩媒介|watercolor (medium)
油画媒介|oil painting (medium)
数字绘画|digital painting (medium)
绘本风绘画|painterly
水粉画|gouache (medium)
水墨画|ink wash painting
彩色铅笔|colored pencil (medium)
炭笔画|charcoal drawing
马克笔画|marker drawing
粉彩画|pastel drawing
版画风格|printmaking
木刻版画|woodcut (medium)
剪纸艺术|paper cutout
彩色玻璃|stained glass
平涂|flat color
像素艺术|pixel art
九十年代画风|1990s (style)
八十年代画风|1980s (style)
二〇〇〇年代画风|2000s (style)
二〇一〇年代画风|2010s (style)
复古动漫|retro anime
漫画风格|manga (style)
少女漫画风|shoujo manga style
美式漫画风|western comics (style)
图像小说风|graphic novel (style)
新艺术风格|art nouveau
装饰艺术风格|art deco
波普艺术|pop art
印象派|impressionism
表现主义|expressionism
超现实主义|surrealism
浪漫主义|romanticism
奇幻艺术|fantasy art
黑暗奇幻|dark fantasy
蒸汽朋克|steampunk
赛博朋克|cyberpunk
蒸汽波|vaporwave
合成波|synthwave
几何艺术|geometric art
浮世绘|ukiyo-e
Q版|chibi
三维画面|3d`),

  '人物与外貌': combine(
    rows('subject', `
单个女孩|1girl, solo
两个女孩|2girls
单个男孩|1boy, solo
一女一男|1girl, 1boy
成年女性|1girl, mature female
成年男性|1boy, mature male
多人|multiple girls
背景人物|crowd`),
    rows('appearance', `
精细面容|detailed face
对称面容|symmetrical face
成熟面容|mature face
圆脸|round face
尖下巴|pointy chin
雀斑|freckles
泪痣|mole under eye
白皙皮肤|pale skin
深色皮肤|dark skin
小麦肤色|tan
自然肤色|natural skin tone
光滑肌肤|smooth skin
细腻肌肤|detailed skin
透亮肌肤|subtle luminous skin
脸红|blush
轻微脸红|light blush
浓重脸红|full-face blush
锁骨|collarbone
肚脐|navel
露腰|midriff
露肩|bare shoulders
后背|back
睫毛|eyelashes
长睫毛|long eyelashes
口红|lipstick
小虎牙|fang
皮肤虎牙|skin fang
眼袋|bags under eyes`)
  ),

  '头发与眼睛': combine(
    rows('appearance', `
长发|long hair
超长发|very long hair
中长发|medium hair
短发|short hair
波波头|bob cut
直发|straight hair
波浪发|wavy hair
卷发|curly hair
马尾|ponytail
双马尾|twintails
侧马尾|side ponytail
低马尾|low ponytail
单辫|single braid
双辫|braided twintails
姬发式|hime cut
狼尾发|wolf cut
凌乱头发|messy hair
飘动头发|floating hair
风吹头发|floating hair
遮住一只眼|hair over one eye
齐刘海|blunt bangs
分缝刘海|parted bangs
大眼睛|wide-eyed
锐利眼神|tsurime
下垂眼|tareme
上挑眼|tsurime
半闭眼|half-closed eyes
异色瞳|heterochromia
发光眼睛|glowing eyes
精细眼睛|eye focus
发髻|hair bun
双发髻|double bun
侧边辫子|side braid
皇冠辫|crown braid
辫子|braid
单侧束发|one side up
双侧束发|two side up
低位双马尾|low twintails
高马尾|high ponytail
短马尾|short ponytail
眼间发丝|hair between eyes
侧扫刘海|swept bangs
不对称刘海|asymmetrical bangs
进气口发型|hair intakes
呆毛|ahoge
天线发|antenna hair
环形卷发|ringlets
钻头卷发|drill hair
多色头发|multicolored hair
渐变发色|gradient hair
挑染头发|streaked hair
双色头发|two-tone hair
内层染发|colored inner hair
头发饰品|hair ornament
发带蝴蝶结|hair ribbon
发夹|hairclip
头花|hair flower
黑色眼睛|black eyes
棕色眼睛|brown eyes
蓝色眼睛|blue eyes
水色眼睛|aqua eyes
绿色眼睛|green eyes
红色眼睛|red eyes
紫色眼睛|purple eyes
粉色眼睛|pink eyes
灰色眼睛|grey eyes
橙色眼睛|orange eyes
白色眼睛|white eyes
单眼闭合|one eye closed
双眼闭合|closed eyes
瞳孔收缩|constricted pupils
瞳孔放大|dilated pupils
星形瞳孔|star-shaped pupils
心形瞳孔|heart-shaped pupils`)
  ),

  '服装与丝袜': rows('clothing', `
白衬衫|white shirt
黑衬衫|black shirt
女式衬衫|blouse
高领毛衣|turtleneck sweater
针织衫|sweater
开衫|cardigan
连帽卫衣|hoodie
西装外套|blazer
夹克|jacket
风衣|trench coat
连衣裙|dress
吊带裙|sundress
晚礼服|evening gown
旗袍|china dress
女仆装|maid
水手服|serafuku, sailor collar
西式制服|school uniform
百褶裙|pleated skirt
包臀裙|pencil skirt
长裙|long skirt
短裤|shorts
牛仔裤|jeans
西装裤|pants
黑色连裤袜|black pantyhose
白色连裤袜|white pantyhose
透明连裤袜|sheer pantyhose
轻薄尼龙袜|pantyhose
不透明裤袜|black pantyhose
网眼袜|fishnet pantyhose
过膝袜|thighhighs
蕾丝边过膝袜|lace-trimmed thighhighs
吊带袜|thighhighs, garter straps
高跟鞋|high heels
长靴|boots
手套|gloves
蕾丝材质|lace
丝绸材质|silk
缎面材质|satin
褶皱布料|wrinkled fabric
针织材质|ribbed sweater
半透明材质|see-through clothes
湿衣效果|wet clothes
服装褶皱|wrinkled fabric
无袖|sleeveless
短袖|short sleeves
长袖|long sleeves
泡泡袖|puffy sleeves
露肩装|off shoulder
无肩带|strapless
吊带背心|camisole
背心|tank top
露脐上衣|crop top
毛衣背心|sweater vest
西装|suit
商务西装|business suit
燕尾礼服|tuxedo
大衣|coat
雨衣|raincoat
和服|kimono
浴衣|yukata
汉服|hanfu
盔甲|armor
紧身连体衣|bodysuit
体操服|leotard
泳装|swimsuit
连体泳衣|one-piece swimsuit
竞赛泳衣|competition swimsuit
比基尼|bikini
运动服|sportswear
体操制服|gym uniform
围裙|apron
睡衣|pajamas
睡裙|nightgown
内衣套装|lingerie
贴身衣物|underwear
内裤|panties
胸罩|bra
及膝袜|kneehighs
腿套|leg warmers
短袜|ankle socks
乐福鞋|loafers
运动鞋|sneakers
凉鞋|sandals
赤脚|barefoot
项链|necklace
颈圈|choker
耳环|earrings
手镯|bracelet
腕表|wristwatch
帽子|hat
贝雷帽|beret
棒球帽|baseball cap
遮阳帽|sun hat
眼镜|glasses
太阳镜|sunglasses`),

  '场景与道具': rows('scene', `
纯色背景|simple background
白色背景|white background
渐变背景|gradient background
风景背景|scenery
室内|indoors
室外|outdoors
卧室|bedroom
客厅|living room
现代室内|indoors, living room
厨房|kitchen
浴室|bathroom
温泉|onsen
酒店房间|hotel room
咖啡馆|cafe
餐厅|restaurant
夜总会|nightclub
教室|classroom
走廊|hallway
图书馆|library
办公室|office
医院|hospital
健身房|gym
更衣室|locker room
电梯|elevator
列车内部|train interior
公交车内部|bus interior
汽车内部|car interior
飞机内部|airplane interior
舞台|stage
剧院|theater
音乐会|concert
城市|city
城市景观|cityscape
城市街道|city, street
小巷|alley
人行横道|crosswalk
霓虹街道|street, neon lights
火车站|train station
地铁站|subway station
机场|airport
便利店|convenience store
超级市场|supermarket
游乐园|amusement park
嘉年华|carnival
屋顶|rooftop
阳台|balcony
花园|garden
公园|park
游乐场|playground
森林|forest
竹林|bamboo forest
花田|flower field
草甸|meadow
山地|mountain
峡谷|canyon
沙漠|desert
洞穴|cave
海滩|beach
海洋|ocean
水下|underwater
泳池|pool
泳池边|poolside
瀑布|waterfall
河流|river
湖泊|lake
码头|dock
栈桥|pier
港口|harbor
农场|farm
神社|shrine
寺庙|temple
教堂|church
城堡|castle
宫殿|palace
遗迹|ruins
赛博朋克场景|cyberpunk
太空|space
宇宙飞船|spacecraft
月球|moon
雨景|rain
降雪|snowing
雾景|fog
樱花|cherry blossoms, falling petals
夜空|night sky
星空|starry sky
黄昏天空|sunset
日出天空|sunrise
窗户|window
床|bed
沙发|couch
椅子|chair
桌子|table
镜子|mirror
汽车|car
雨伞|umbrella
花束|bouquet
书本|book
咖啡杯|coffee, cup`),

  '通用·光线与氛围': rows('lighting', `
阳光|sunlight
逆光|backlighting
侧面光|sidelighting
正面光|front lighting
顶光|top lighting
底光|underlighting
轮廓光|rim light
发丝光|hair light
边缘光|edge lighting
主光|key light
补光|fill light
环境光|ambient light
自然光|natural lighting
摄影棚灯光|studio lighting
电影级灯光|cinematic lighting
戏剧性灯光|dramatic lighting
柔光|soft light
硬光|hard light
漫射光|diffused lighting
体积光|volumetric lighting
低调照明|low-key lighting
高调照明|high-key lighting
明暗对照|chiaroscuro
暖色灯光|warm lighting
冷色灯光|cool lighting
双色灯光|two-tone lighting
彩色灯光|multicolored lighting
红色灯光|red light
蓝色灯光|blue light
紫色灯光|purple light
光束|light rays
丁达尔光束|sunbeam
耶稣光|god rays
斑驳阳光|dappled sunlight
窗格投影|window shadow
普通阴影|shadow
柔和阴影|soft shadows
硬边阴影|hard shadows
长阴影|long shadows
投射阴影|cast shadow
斑驳阴影|dappled shadows
彩色阴影|colored shadow
高反差|high contrast
聚光灯|spotlight
探照灯|searchlight
舞台灯光|stage lights
城市灯光|city lights
霓虹灯光|neon lights
天花板灯|ceiling light
屏幕光|screen light
月光|moonlight
烛光|candlelight
星光|starlight
火光|firelight
灯笼光|lantern light
荧光灯|fluorescent lighting
白炽灯|incandescent lighting
生物荧光|bioluminescence
镜头光晕|lens flare
光晕|bloom
光粒子|light particles
光轨|light trail
焦散光|caustics
发光|glowing
闪光|sparkle
剪影|silhouette
眼部藏于阴影|eyes in shadow
白天|day
夜晚|night
清晨|dawn
晨光|morning light
日出|sunrise
午后阳光|afternoon sunlight
傍晚|evening
日落|sunset
金色时刻|golden hour
蓝色时刻|blue hour
夕阳余晖|sunset glow
暮色|dusk
薄暮|twilight
暮光辉映|twilight glow
蓝天|blue sky
多云天空|cloudy sky
阴天|overcast
云朵|cloud
夜空|night sky
星空|starry sky
天空星星|star (sky)
橙色天空|orange sky
紫色天空|purple sky
红色天空|red sky
极光|aurora
彩虹|rainbow
雾|fog
薄雾|mist
朦胧空气|haze
空气透视|atmospheric perspective
漂浮尘埃|dust motes
烟雾|smoke
蒸汽|steam
倒影|reflection
湿地反光|wet reflections
折射|refraction
虹彩|iridescent
柔焦|soft focus
黑暗氛围|dark
梦幻氛围|dreamy atmosphere
空灵氛围|ethereal atmosphere
浪漫氛围|romantic atmosphere
宁静氛围|serene atmosphere
温馨氛围|cozy atmosphere
亲密氛围|intimate atmosphere
怀旧氛围|nostalgic atmosphere
忧郁氛围|melancholic atmosphere
神秘氛围|mysterious atmosphere
诡异氛围|eerie atmosphere
不祥氛围|ominous atmosphere
节日氛围|festive atmosphere
情绪化灯光|moody lighting
色差|chromatic aberration
胶片颗粒|film grain
暗角|vignetting`),

  '构图与镜头': rows('composition', `
全身像|full body
大腿以上|cowboy shot
膝盖以上|cowboy shot
上半身|upper body
胸像|upper body
面部特写|portrait, close-up
极近特写|close-up
远景|wide shot
全景|panorama
正面视角|straight-on
人物侧面|profile
侧面视角|from side
背面视角|from behind
俯拍|from above
仰拍|from below
第一人称视角|pov
荷兰角|dutch angle
鱼眼镜头|fisheye
透视缩短|foreshortening
消失点|vanishing point
负空间|negative space
景深|depth of field
背景虚化|blurry background
前景虚化|blurry foreground
镜面构图|mirror
剪影|silhouette
人物聚焦|solo focus
面部聚焦|portrait
眼睛聚焦|eye focus
手部聚焦|hand focus
腿部聚焦|leg focus
背部聚焦|back focus
近距离特写|close-up
头像特写|headshot
从室外观察|from outside
从室内观察|from inside
多视图|multiple views
脚部出框|feet out of frame
腿部裁切|cropped legs
风景主体|scenery
无人场景|no humans`),

  '写真·站立倚靠': rows('pose', `
自然站立|standing
笔直站立|standing, upright
放松站立|standing, relaxed pose
重心偏向一侧|standing, contrapposto
双腿并拢站立|standing, legs together
双腿交叉站立|standing, crossed legs
双脚分开站立|standing, feet apart
一条腿向前|standing, one leg forward
一条腿向后|standing, one leg behind
单膝弯曲站立|standing, bent knee
踮脚站立|standing, tiptoes
单脚站立|standing on one leg
站姿前倾|standing, leaning forward
站姿后仰|standing, leaning back
站姿侧倾|standing, leaning to the side
侧身站立|standing, from side
背对镜头站立|standing, from behind
背对镜头回头|standing, looking back
转动上半身|standing, torso twist
挺胸站立|standing, chest out
一手叉腰站立|standing, hand on hip
双手叉腰站立|standing, hands on hips
双手背后站立|standing, arms behind back
双臂交叉站立|standing, crossed arms
双臂举起站立|standing, arms up
双手脑后站立|standing, arms behind head
单臂举起站立|standing, one arm up
站姿整理头发|standing, adjusting hair
站姿撩头发|standing, hand in hair
站姿扶帽子|standing, holding hat
站姿拉裙摆|standing, holding skirt
站姿整理衣服|standing, adjusting clothes
站姿手指抵唇|standing, finger to lips
站姿双手扶腿|standing, hands on thighs
站姿回眸观众|standing, looking back, looking at viewer
站姿伸懒腰|standing, stretching, arms up
模特台步姿势|standing, model pose
优雅站姿|standing, elegant pose
自信站姿|standing, confident pose
害羞内八站姿|standing, pigeon-toed
靠墙站立|standing, leaning on wall
背靠墙壁|against wall, back against wall
肩膀靠墙|shoulder against wall
单手撑墙|hand on wall
双手撑墙|hands on wall
面向墙壁|facing wall
靠着门框|leaning on door frame
扶着门框|holding door frame
靠着栏杆|leaning on railing
双手扶栏杆|hands on railing
趴在栏杆|leaning over railing
靠着桌子|leaning on table
单手撑桌|hand on table
双手撑桌|hands on table
扶着椅背|standing, holding chair
靠着窗户|leaning against window
单手扶窗|hand on window
靠着汽车|leaning on car`),

  '写真·坐跪蹲': rows('pose', `
普通坐姿|sitting
端正坐姿|sitting, upright
放松坐姿|sitting, relaxed pose
坐在椅子上|sitting on chair
坐在沙发上|sitting on couch
坐在床上|sitting on bed
坐在床边|sitting on edge of bed
坐在桌面|sitting on table
坐在桌边|sitting on edge of table
坐在窗台|sitting on windowsill
坐在地板|sitting on floor
坐在台阶|sitting on stairs
双腿并拢坐|sitting, legs together
双腿交叉坐|sitting, crossed legs
盘腿坐|sitting, cross-legged
坐姿单膝抬起|sitting, one knee up
坐姿双膝抬起|sitting, knees up
坐姿抱膝|sitting, hugging own knees
坐姿双腿伸直|sitting, legs extended
一腿伸直一腿弯曲|sitting, one leg extended, one knee up
双腿悬空坐|sitting, feet off ground
坐姿前倾|sitting, leaning forward
坐姿后仰|sitting, leaning back
双手身后支撑|sitting, arms behind back, supporting self
单手支撑坐姿|sitting, supporting self with one arm
手肘放在膝盖|sitting, elbows on knees
双手放在膝盖|sitting, hands on knees
双手放在大腿|sitting, hands on thighs
坐姿托腮|sitting, chin rest
反向跨坐椅子|straddling chair, backwards chair
正坐|seiza
跪坐|sitting on heels
鸭子坐|wariza
侧向坐姿|sitting sideways
回头坐姿|sitting, looking back
坐姿伸懒腰|sitting, stretching
优雅坐姿|sitting, elegant pose
慵懒坐姿|sitting, slouching
双膝跪地|kneeling
单膝跪地|one knee, kneeling
挺直跪姿|kneeling, upright
跪坐脚后跟|kneeling, sitting on heels
跪在床上|kneeling on bed
跪在沙发|kneeling on couch
跪姿前倾|kneeling, leaning forward
跪姿后仰|kneeling, leaning back
跪姿侧身|kneeling, from side
跪姿回头|kneeling, looking back
跪姿双手扶腿|kneeling, hands on thighs
跪姿双臂举起|kneeling, arms up
跪姿双手脑后|kneeling, arms behind head
跪姿双手背后|kneeling, arms behind back
跪姿单手撑地|kneeling, hand on floor
跪姿双手撑地|kneeling, hands on floor
普通下蹲|squatting
深蹲|deep squat
单膝蹲姿|crouching, one knee down
踮脚下蹲|squatting, on tiptoes
蹲姿双膝并拢|squatting, knees together
蹲姿前倾|squatting, leaning forward
蹲姿托腮|squatting, chin rest
蹲姿回头|squatting, looking back
单手撑地蹲姿|crouching, hand on ground
抱膝蹲下|crouching, hugging own knees`),

  '写真·躺卧支撑': rows('pose', `
普通躺姿|lying
仰躺|lying on back
俯卧|lying on stomach
侧躺|lying on side
躺在床上|lying on bed
躺在沙发|lying on couch
躺在地板|lying on floor
躺在草地|lying on grass
身体蜷缩|curled up
侧躺蜷缩|curled up, lying on side
躺姿单膝弯曲|lying, bent knee
躺姿双膝弯曲|lying, knees up
躺姿一腿曲起|lying, one leg extended, one knee up
躺姿双腿伸直|lying, legs extended
躺姿双腿抬起|lying, legs up
双腿靠墙|lying, legs against wall
躺姿双腿交叉|lying, crossed legs
躺姿双手脑后|lying, arms behind head
双臂伸过头顶|lying, arms above head
躺姿手放额头|lying, hand on forehead
躺姿手托脸|lying, hand on cheek
单手撑头侧躺|lying, head propped on hand
躺姿拱背|lying, arched back
仰躺看观众|lying on back, looking at viewer
侧躺看观众|lying on side, looking at viewer
俯卧回头|lying on stomach, looking back
趴着托腮|lying on stomach, chin rest
趴着翘腿|lying on stomach, feet up
半躺姿势|reclining
双肘支撑半躺|reclining, propped up on elbows
单臂支撑半躺|reclining, supporting self with one arm
慵懒斜躺|reclining, relaxed pose
侧躺撩头发|lying on side, hand in hair
躺姿伸懒腰|lying, stretching
手膝着地|all fours
手膝着地看镜头|all fours, looking at viewer
手膝着地回头|all fours, looking back
手膝着地侧面|all fours, from side
手膝着地背面|all fours, from behind
双手撑床跪姿|hands on bed, kneeling
双手撑沙发跪姿|hands on couch, kneeling`),

  '写真·动态躯干': rows('pose', `
行走|walking
向镜头走来|walking toward viewer
背对镜头走开|walking away
行走时回头|walking, looking back
模特台步|catwalk, model pose
奔跑|running
小跑|jogging
跳跃|jumping
单脚跳跃|jumping, one leg raised
原地旋转|spinning
转身|turning around
舞蹈动作|dancing
芭蕾动作|ballet
踮脚舞姿|dancing, on tiptoes
甩头发|hair flip
伸懒腰|stretching
双臂展开动态|arms spread
向上伸展|reaching up
向前伸手|reaching toward viewer
弯腰拾物|bending over, reaching down
风吹动态|wind, dynamic pose, hair blowing
快速转身回眸|turning, looking back, dynamic pose
挺胸|chest out
弓背|arched back
身体前倾|leaning forward
身体后仰|leaning back
身体侧倾|leaning to the side
腰部扭转|torso twist
肩膀转向镜头|shoulders turned
一侧肩膀抬起|raised shoulder
双肩放松|relaxed shoulders
缩肩害羞|shy, shoulders raised
低头|head down
抬头|head up
歪头|head tilt
仰头|head back
回头|looking back
侧身回头|torso twist, looking back`),

  '写真·手势动作': rows('pose', `
双臂自然下垂|arms at sides
单臂举起|one arm up
双臂举起|arms up
双臂过头|arms above head
双臂脑后|arms behind head
双臂背后|arms behind back
双臂交叉|crossed arms
双臂展开|arms spread
双臂向前伸|arms forward
单臂横过身体|arm across body
抱住自己的手臂|holding own arm
自我拥抱|self hug
握住自己手腕|holding own wrist
十指交扣|interlocked fingers
双手合十|hands together
单手叉腰|hand on hip
双手叉腰|hands on hips
手放自己大腿|hand on own thigh
双手放在大腿|hands on thighs
手放膝盖|hand on knee
双手放在膝盖|hands on knees
手放自己肩膀|hand on own shoulder
手放自己颈部|hand on own neck
手放自己脸颊|hand on own cheek
手放额头|hand on forehead
手放胸口|hand on chest
手放腹部|hand on stomach
托腮|chin rest
手指抵唇|finger to lips
遮住嘴巴|covering mouth
遮住脸|covering face
撩头发|hand in hair
抚摸头发|touching own hair
整理头发|adjusting hair
扎头发|tying hair
握住马尾|holding ponytail
扶眼镜|adjusting eyewear
扶帽子|holding hat
整理领口|adjusting collar
拉衣袖|pulling sleeve
握住肩带|holding strap
整理裙摆|adjusting skirt
拉住裙摆|holding skirt
整理袜子|adjusting legwear
整理手套|adjusting gloves
向观众伸手|reaching toward viewer
招手|waving
双手比心|heart hands
手指比心|finger heart
V字手势|peace sign
OK手势|ok sign
飞吻|blowing kiss
招手邀请|beckoning
指向观众|pointing at viewer`),

  '写真·腿部表情': combine(
    rows('pose', `
双腿并拢|legs together
双腿交叉|crossed legs
双腿伸直|legs extended
单腿弯曲|bent knee
双膝弯曲|knees up
单腿抬起|leg lift
一腿向前|one leg forward
一腿向后|one leg behind
单脚站立|standing on one leg
踮脚|tiptoes
脚尖向内|pigeon-toed
脚尖绷直|pointed toes
膝盖贴近胸口|knees to chest
双腿悬空|feet off ground
双脚翘起|feet up
踢腿动作|high kick
芭蕾抬腿|ballet pose, leg lift
看向观众|looking at viewer
回头看|looking back
向上看|looking up
向下看|looking down
看向侧面|looking to the side
视线移开|looking away
闭眼|closed eyes
半闭眼|half-closed eyes
慵懒眼神|bedroom eyes
侧目|sideways glance
害羞移开视线|shy, looking away
自信神情|confident
柔和微笑|soft smile
诱惑式微笑|seductive smile
得意微笑|smirk
嘴唇微张|parted lips
脸红|blush
害羞|shy
尴尬|embarrassed
惊讶|surprised
调皮表情|playful
眨眼|one eye closed, wink
吐舌|tongue out`)
  ),

  '写真·双人互动': rows('pose', `
并肩站立|2girls, standing side by side
背靠背站立|2girls, back-to-back
面对面站立|2girls, facing each other
牵手|holding hands
拥抱|hug
从背后拥抱|hug from behind
侧面拥抱|side hug
搂住腰部|arm around waist
搂住肩膀|arm around shoulder
额头相贴|foreheads touching
鼻尖相碰|noses touching
相互对视|looking at each other
一起坐着|sitting together
依靠对方肩膀|head on shoulder
躺在对方腿上|lap pillow
共舞|dancing together
扶住对方|supporting another
公主抱|princess carry
背起对方|piggyback`),

  '写真·组合预设': rows('pose', `
回眸站姿|standing, contrapposto, crossed legs, hand on hip, torso twist, looking back, looking at viewer, from behind, three-quarter view
床边坐姿|sitting on edge of bed, crossed legs, leaning forward, hands on thighs, looking at viewer, soft smile, cowboy shot, three-quarter view
沙发半躺|reclining on couch, one knee up, supporting self with one arm, arched back, hand in hair, looking at viewer, half-closed eyes
跪姿写真|kneeling on bed, upright, hands on thighs, head tilt, looking at viewer, parted lips, cowboy shot, three-quarter view
靠墙站姿|standing, leaning on wall, crossed legs, arms behind back, looking at viewer, confident, full body, from below
俯卧写真|lying on stomach, feet up, chin rest, looking at viewer, soft smile, from above
侧躺写真|lying on side, one knee up, head propped on hand, looking at viewer, bedroom eyes, full body, three-quarter view
手膝支撑写真|adult, mature female, solo, clothed, non-explicit, all fours, looking back, from side, full body
模特行走|walking toward viewer, model pose, one leg forward, hand on hip, hair blowing, confident, full body, dynamic angle
撩发站姿|standing, contrapposto, one arm up, hand in hair, head tilt, looking at viewer, cowboy shot, three-quarter view`)
};
})();
