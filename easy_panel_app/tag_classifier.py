"""Deterministic semantic classifier for LoRA prompt tags.

The classifier is deliberately local: TXT contents and private LoRA metadata
never leave the machine.  Explicit section headers are handled by
``lora_sidecars``; this module classifies unlabelled Danbooru-style tags.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache


CATEGORIES = (
    "subject",
    "appearance",
    "clothing",
    "pose",
    "composition",
    "scene",
    "lighting",
    "style",
    "negative",
    "other",
)

COUNT_TAGS = {
    "1girl", "1boy", "2girls", "2boys", "3girls", "3boys", "4girls", "4boys",
    "5girls", "5boys", "6+girls", "6+boys", "solo", "group", "crowd",
    "multiple girls", "multiple boys", "multiple people", "no humans", "hetero",
    "male focus", "female focus", "1male", "1female", "1girl and 1boy",
    "1girl and 2boys", "2girls and 1boy",
}

SERIES_KEYWORDS = (
    "azur lane", "blue archive", "honkai", "genshin", "wuthering waves", "arknights",
    "fate", "grand order", "touhou", "nikke", "punishing gray raven", "kancolle",
    "idolmaster", "love live", "hololive", "umamusume", "vocaloid", "xenoblade",
    "pokemon", "street fighter", "nier", "original character",
)

ROLE_KEYWORDS = (
    "nurse", "maid", "idol", "soldier", "knight", "priest", "witch", "miko",
    "shrine maiden", "schoolgirl", "teacher", "police", "waitress", "cheerleader",
    "dancer", "goddess", "princess", "queen", "angel", "demon", "devil", "elf",
    "vampire", "catgirl", "fox girl", "bunny girl", "robot", "android", "cyborg",
    "magical girl", "saint", "nun", "bride", "groom", "pilot", "officer",
    "adult woman", "adult man", "faceless male", "faceless female",
    "护士", "女仆", "偶像", "士兵", "骑士", "修女", "巫女", "魔女", "学生",
    "老师", "警察", "服务员", "舞者", "女神", "公主", "女王", "天使", "恶魔",
    "精灵", "吸血鬼", "猫娘", "狐娘", "机器人", "新娘",
)

CLOTHING_KEYWORDS = (
    "dress", "skirt", "shirt", "blouse", "uniform", "swimsuit", "bikini", "kimono",
    "jacket", "coat", "blazer", "vest", "sweater", "hoodie", "cardigan", "jersey",
    "leotard", "bodysuit", "pants", "shorts", "trousers", "jeans", "leggings",
    "pantyhose", "stockings", "thighhighs", "tights", "socks", "boots", "shoes",
    "sandals", "heels", "footwear", "loafers", "sneakers", "gloves", "mittens",
    "hat", "cap", "beret", "headwear", "veil", "hood", "mask", "scarf", "tie",
    "necktie", "bowtie", "ribbon", "choker", "necklace", "pendant", "earrings",
    "bracelet", "ring", "brooch", "corset", "garter", "belt", "sash", "obi", "cape",
    "cloak", "armor", "gauntlet", "jewelry", "collar", "frills", "lace", "apron",
    "headband", "torn clothes", "open clothes", "bottomless", "topless", "underwear",
    "bra", "panties", "thong", "sailor collar", "serafuku", "labcoat", "pajamas",
    "nightgown", "costume", "armlet", "hair ribbon", "hair ornament", "hair clip", "glove",
    "sleeve", "sleeves", "clothes", "piercing", "anklet", "thighlet",
    "hair flower", "detached sleeves", "sleeveless", "long sleeves", "short sleeves",
    "off-shoulder", "bare shoulders", "clothing cutout", "see-through", "translucent",
    "crop top", "playboy bunny", "bunny suit", "criss-cross halter", "single thighhigh",
    "headgear", "strapless", "maid headdress", "pelvic curtain", "asymmetrical legwear",
    "halterneck", "bow", "side slit", "wrist cuffs", "hairband", "miniskirt", "cutout",
    "tiara", "zettai ryouiki", "gauntlets", "kneehighs", "zipper", "buttons", "trim",
    "bodystocking", "fishnets", "harness", "strap", "tube top", "armband", "breastplate",
    "highleg", "floral print", "fur trim", "underboob", "sideboob", "underbust",
    "服装", "衣服", "连衣裙", "裙子", "短裙", "衬衫", "制服", "校服", "泳装", "泳衣",
    "比基尼", "和服", "外套", "夹克", "裤子", "短裤", "牛仔裤", "丝袜", "裤袜",
    "长筒袜", "过膝袜", "袜子", "靴子", "鞋子", "高跟鞋", "手套", "帽子", "面纱",
    "围巾", "领带", "蝴蝶结", "项圈", "项链", "耳环", "手链", "戒指", "腰带",
    "披风", "斗篷", "盔甲", "蕾丝", "围裙", "内衣", "胸罩", "内裤", "丁字裤",
    "睡衣", "袖子", "露肩", "裸肩", "发饰", "头饰", "发带",
)

APPEARANCE_KEYWORDS = (
    "hair", "ahoge", "bangs", "sidelocks", "ponytail", "twintails", "braid", "hair bun",
    "eyes", "eye", "pupils", "eyelashes", "eyebrows", "heterochromia", "freckles",
    "mole", "fang", "teeth", "tongue", "facial mark", "blush", "smile", "crying",
    "breasts", "breast", "cleavage", "navel", "midriff", "belly", "waist", "hips",
    "thigh", "legs", "feet", "barefoot", "skin", "shoulder", "armpit", "collarbone",
    "neck", "back", "butt", "small breasts", "large breasts", "flat chest", "curvy",
    "slim", "petite", "muscular", "chubby", "abs", "body", "figure", "horns", "ears",
    "wings", "tail", "tattoo", "fingernails", "oni horns", "mechanical eye",
    "open mouth", "closed mouth", "nude", "completely nude", "nipples", "pussy", "penis",
    "anus", "clitoris", "testicles", "thighs", "stomach", "toes", "sweat", "tears",
    "saliva", "ahegao", "embarrassed", "nail polish", "halo", "skindentation",
    "double bun", "braided bun", "two side up", "one side up", "single sidelock",
    "头发", "长发", "短发", "双马尾", "马尾", "辫子", "发髻", "刘海", "眼睛", "瞳孔",
    "异色瞳", "睫毛", "眉毛", "雀斑", "痣", "虎牙", "舌头", "面部", "微笑", "脸红",
    "乳房", "胸部", "巨乳", "贫乳", "乳头", "乳沟", "肚脐", "腹部", "腰部", "臀部",
    "屁股", "大腿", "双腿", "脚部", "赤脚", "皮肤", "腋下", "锁骨", "裸体", "全裸",
    "苗条", "肌肉", "丰满", "兽耳", "角", "翅膀", "尾巴", "纹身",
)

POSE_KEYWORDS = (
    "standing", "sitting", "kneeling", "lying", "on back", "on stomach", "on side",
    "all fours", "crawling", "spread legs", "legs up", "leg up", "squatting", "leaning",
    "bent over", "arched back", "looking at viewer", "looking back", "looking away",
    "looking down", "looking up", "facing viewer", "facing away", "walking", "running",
    "jumping", "hand on hip", "hand on knee", "arms behind back", "arms up", "hands up",
    "hugging", "kissing", "holding", "carrying", "dancing", "sleeping", "crouching",
    "straddling", "riding", "groping", "fondling", "cowgirl position", "missionary",
    "doggystyle", "posing", "pose", "holding staff", "holding weapon", "holding sword",
    "holding gun", "holding cannon", "head tilt", "yawning", "crossed arms",
    "sex", "vaginal", "fellatio", "handjob", "kiss", "after sex", "pet play",
    "spread pussy", "spread anus", "cum", "cum in pussy", "cumdrip", "head grab",
    "stepped on", "trembling", "moaning", "arm support", "folded", "dildo", "sex toy",
    "katana", "leash", "erection",
    "站立", "坐着", "跪着", "躺着", "趴着", "四肢着地", "爬行", "张开双腿", "抬腿",
    "蹲下", "弯腰", "看向观众", "回头", "移开视线", "走路", "跑步", "跳跃", "举手",
    "拥抱", "接吻", "拿着", "抱着", "跳舞", "睡觉", "骑乘", "交叉双臂", "歪头",
)

COMPOSITION_KEYWORDS = (
    "full body", "upper body", "lower body", "cowboy shot", "portrait", "headshot",
    "close-up", "closeup", "medium shot", "wide shot", "from behind", "from above",
    "from below", "side view", "front view", "three-quarter view", "low angle",
    "high angle", "dutch angle", "foreshortening", "dynamic angle", "centered",
    "symmetrical", "perspective", "depth of field", "bokeh", "blurry background",
    "solo focus", "multiple views", "split screen", "collage", "panorama",
    "from side", "pov", "top-down bottom-up",
    "全身", "上半身", "下半身", "牛仔镜头", "肖像", "头像", "特写", "近景", "远景",
    "背面", "俯视", "仰视", "侧面", "正面", "低角度", "高角度", "荷兰角", "广角",
    "透视", "景深", "背景虚化", "居中", "对称", "多视图", "分屏", "拼贴", "全景",
)

SCENE_KEYWORDS = (
    "indoor", "outdoor", "classroom", "bedroom", "kitchen", "bathroom", "bath", "shower",
    "street", "city", "building", "room", "house", "garden", "park", "beach", "sea",
    "ocean", "sky", "cloud", "night", "day", "morning", "evening", "background",
    "window", "door", "doorway", "bed", "table", "desk", "chair", "floor", "wall",
    "snow", "rain", "forest", "mountain", "school", "laboratory", "office", "train",
    "station", "car", "aircraft", "space", "underwater", "stage", "balcony", "cafe",
    "restaurant", "library", "pool", "hot spring", "onsen", "bathhouse", "ruins",
    "temple", "residential area", "urban", "alley", "simple background", "white background",
    "black background", "gradient background", "plain background",
    "indoors", "pillow",
    "室内", "户外", "教室", "卧室", "厨房", "浴室", "街道", "城市", "房间", "房屋",
    "花园", "公园", "海滩", "海洋", "天空", "云朵", "夜晚", "白天", "早晨", "傍晚",
    "背景", "窗户", "门口", "床上", "桌子", "椅子", "地板", "墙壁", "下雪", "下雨",
    "森林", "山上", "学校", "实验室", "办公室", "火车", "车站", "汽车", "飞机",
    "太空", "水下", "舞台", "阳台", "咖啡厅", "餐厅", "图书馆", "泳池", "温泉",
    "废墟", "寺庙", "小巷", "纯色背景", "简单背景",
)

LIGHTING_KEYWORDS = (
    "light", "lighting", "sunlight", "moonlight", "backlighting", "backlight", "shadow",
    "glow", "glowing", "illumination", "ambient", "flash", "neon", "silhouette",
    "rim light", "candlelight", "lamplight", "twilight", "dawn", "dusk", "sunset",
    "sunrise", "volumetric", "cinematic lighting",
    "光线", "灯光", "阳光", "月光", "逆光", "阴影", "发光", "霓虹", "轮廓光", "烛光",
    "黄昏", "黎明", "日落", "日出", "体积光", "电影光效",
)

STYLE_KEYWORDS = (
    "anime screencap", "screencap", "chibi", "3d", "pvc", "game style", "official style",
    "sketch", "lineart", "watercolor", "oil painting", "illustration", "painting", "artwork",
    "cgi", "pixel art", "manga", "comic", "cell shading", "flat color", "monochrome",
    "grayscale", "pastel", "fanart", "cover", "poster", "render", "motion blur",
    "motion lines", "speed lines", "screen tone", "noir", "photorealistic", "realistic",
    "uncensored", "sound effects",
    "动漫", "动画截图", "二次元", "Q版", "游戏风格", "官方风格", "素描", "线稿", "水彩",
    "油画", "插画", "像素画", "漫画", "赛璐璐", "平涂", "单色", "灰度", "粉彩",
    "同人图", "封面", "海报", "渲染", "写实",
)

NEGATIVE_KEYWORDS = (
    "worst quality", "low quality", "bad anatomy", "bad hands", "extra fingers", "watermark",
    "signature", "jpeg artifacts", "lowres", "blurry", "censored", "malformed", "deformed",
    "duplicate", "text artifact",
    "低质量", "最差质量", "错误人体", "错误手部", "多余手指", "水印", "签名", "模糊",
    "畸形", "变形", "重复", "压缩伪影",
)

COLOR_WORDS = {
    "white", "black", "blue", "red", "pink", "purple", "green", "brown", "yellow",
    "grey", "gray", "orange", "gold", "silver", "aqua", "blonde", "teal", "cyan",
}

NON_TRIGGER_LABELS = {
    "default", "recommended", "normal", "basic", "base", "casual", "formal", "alternative",
    "outfit", "costume", "style", "preset", "prompt", "tags", "training", "metadata",
}


def normalize_tag(tag: str) -> str:
    value = str(tag or "").strip().strip("，,、;；")
    value = re.sub(r"\s+", " ", value.replace("_", " ")).strip().casefold()
    return value


@lru_cache(maxsize=None)
def _keyword_pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted({str(word).casefold() for word in words if str(word)}, key=len, reverse=True)
    return re.compile(r"(?<![a-z])(?:" + "|".join(map(re.escape, ordered)) + r")(?![a-z])")


def _has(value: str, words: Iterable[str]) -> bool:
    return bool(_keyword_pattern(tuple(words)).search(value))


def is_trigger_or_character(tag: str) -> bool:
    """Return true only after ordinary semantic categories were ruled out."""
    raw = str(tag or "").strip()
    low = normalize_tag(raw)
    if (not raw or not re.search(r"[A-Za-z]", raw) or low in COUNT_TAGS
            or low in NON_TRIGGER_LABELS
            or any(word in NON_TRIGGER_LABELS for word in low.split())):
        return False
    if re.search(r"\([^)]{2,}\)", raw):
        prefix = normalize_tag(raw.split("(", 1)[0])
        if prefix and not re.search(r"\b(?:steps?|rank|alpha|model|weight|official|default)\b", prefix):
            return True
    if re.search(r"[a-z][A-Z]", raw) or re.fullmatch(r"[A-Za-z]{2,}[0-9][A-Za-z0-9_-]*", raw):
        return True
    if (raw[0].isupper() and len(raw) >= 3 and " " not in raw
            and low.split(" ", 1)[0] not in COLOR_WORDS):
        return True
    words = raw.split()
    if (2 <= len(words) <= 4 and all(word[:1].isupper() for word in words)
            and not _has(low, ("official", "base model", "recommended weight", "training parameters"))):
        return True
    if "_" in raw and len(raw) <= 40 and re.search(r"[A-Za-z]", raw):
        generic = (*CLOTHING_KEYWORDS, *APPEARANCE_KEYWORDS, *POSE_KEYWORDS, *SCENE_KEYWORDS,
                   *COMPOSITION_KEYWORDS, *LIGHTING_KEYWORDS, *STYLE_KEYWORDS)
        return not _has(low, generic)
    return False


def classify_tag(tag: str) -> tuple[str, str, float]:
    """Return ``(category, reason, confidence)`` for one prompt fragment."""
    raw = str(tag or "").strip().strip("，,、;；")
    low = normalize_tag(raw)
    if not low:
        return "other", "empty", 0.0
    if raw.startswith("@"):
        return "style", "artist/style token", 0.98
    if _has(low, NEGATIVE_KEYWORDS):
        return "negative", "negative keyword", 0.99
    if low in COUNT_TAGS or _has(low, SERIES_KEYWORDS) or low in {normalize_tag(x) for x in ROLE_KEYWORDS}:
        return "subject", "subject/count/series keyword", 0.96
    if _has(low, POSE_KEYWORDS):
        return "pose", "pose/action keyword", 0.94
    if _has(low, CLOTHING_KEYWORDS):
        return "clothing", "clothing/accessory keyword", 0.95
    if _has(low, SCENE_KEYWORDS):
        return "scene", "scene keyword", 0.93
    if _has(low, LIGHTING_KEYWORDS):
        return "lighting", "lighting keyword", 0.93
    if _has(low, COMPOSITION_KEYWORDS):
        return "composition", "camera/composition keyword", 0.94
    if _has(low, APPEARANCE_KEYWORDS):
        return "appearance", "appearance keyword", 0.94
    if _has(low, STYLE_KEYWORDS):
        return "style", "style/medium keyword", 0.92
    if is_trigger_or_character(raw):
        return "subject", "trigger/character shape", 0.78
    return "other", "unrecognised semantic tag", 0.35


def classify_tag_list(tags: Iterable[str]) -> dict[str, list[str]]:
    result = {category: [] for category in CATEGORIES}
    seen = {category: set() for category in CATEGORIES}
    for raw in tags:
        tag = str(raw or "").strip().strip("，,、;；")
        if not tag:
            continue
        category, _, _ = classify_tag(tag)
        key = normalize_tag(tag)
        if key and key not in seen[category]:
            seen[category].add(key)
            result[category].append(tag)
    return result


def classify_tags(tags: Iterable[str]) -> dict[str, str]:
    """Backward-compatible string-valued API used by older helper scripts."""
    return {category: ", ".join(values) for category, values in classify_tag_list(tags).items()}


__all__ = [
    "CATEGORIES",
    "classify_tag",
    "classify_tag_list",
    "classify_tags",
    "is_trigger_or_character",
    "normalize_tag",
]
