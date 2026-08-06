# -*- coding: utf-8 -*-
"""标签分类器：把提示词标签按语义分类到面板分区（subject/appearance/clothing/pose/scene/lighting/style/negative/other）。
规则基于 Danbooru 标签语义；服装优先于身体，用词边界避免子串误匹配（thigh 不吞 thighhighs）。"""
import re

COUNT_TAGS = {"1girl", "1boy", "2girls", "2boys", "3girls", "3boys", "4girls", "4boys", "5girls",
              "5boys", "6+girls", "6+boys", "solo", "group", "multiple girls", "multiple boys",
              "multiple people", "no humans", "crowd", "mixed pair", "1girl and 1boy", "1girl and 2boys",
              "2girls and 1boy", "hetero", "male focus", "female focus", "1male focus", "1male", "1female"}

SERIES_KEYWORDS = ("azur lane", "blue archive", "honkai", "genshin", "impact", "wuthering waves",
                   "arknights", "fate", "grand order", "touhou", "nikke", "punishing gray raven",
                   "alchemy stars", "kancolle", "idolmaster", "lovelive", "hololive",
                   "umamusume", "blue reflection", "miku", "vocaloid", "nier", "xenoblade", "pokemon",
                   "street fighter", "original", "oc", "character", "azur")

ROLE_KEYWORDS = ("nurse", "maid", "idol", "soldier", "knight", "priest", "witch", "miko", "shrine maiden",
                 "schoolgirl", "teacher", "police", "waitress", "cheerleader", "dancer", "goddess",
                 "princess", "queen", "angel", "demon", "devil", "elf", "vampire", "werewolf", "catgirl",
                 "fox girl", "bunny girl", "robot", "android", "cyborg", "magical girl", "saint",
                 "nun", "bride", "groom", "pilot", "captain", "officer", "racer", "rider", "nun",
                 "saint", "gym teacher", "mad scientist")

CLOTHING_KEYWORDS = ("dress", "skirt", "shirt", "blouse", "uniform", "swimsuit", "bikini", "kimono",
                     "jacket", "coat", "blazer", "vest", "sweater", "hoodie", "cardigan", "jersey",
                     "leotard", "bodysuit", "pants", "shorts", "trousers", "jeans", "leggings",
                     "pantyhose", "stockings", "thighhighs", "tights", "socks", "boots", "shoes",
                     "sandals", "heels", "footwear", "loafers", "sneakers", "gloves", "mittens",
                     "wristband", "hat", "cap", "beret", "headwear", "veil", "hood", "mask", "scarf",
                     "tie", "necktie", "bowtie", "ribbon", "choker", "necklace", "pendant", "earrings",
                     "bracelet", "ring", "brooch", "corset", "garter", "belt", "sash", "obi", "cape",
                     "cloak", "armor", "gauntlet", "piercing", "jewelry", "collar", "frills", "lace",
                     "see-through", "translucent", "clothing", "outfit", "sleeves", "sleeve", "cuffs",
                     "cuff", "apron", "headband", "torn clothes", "open clothes", "bottomless",
                     "topless", "nude", "clothes lift", "shirt lift", "skirt lift", "no panties",
                     "underwear", "bra", "panties", "panty", "garter belt", "suspenders", "garter straps",
                     "straps", "strap", "goggles", "headphones", "whistle", "miniskirt", "microskirt",
                     "thong", "sailor collar", "serafuku", "labcoat", "glove", "sock", "boot", "shoe",
                     "heel", "skirt", "suit", "ties", "belts", "scarves", "pajamas", "nightgown",
                     "costume", "armlet", "wrist cuff", "wrist cuffs", "cuff", "neck ribbon",
                     "hair ribbon", "hair ornament", "hair clip", "hair flower")

HAIR_KEYWORDS = ("ahoge", "bangs", "sidelocks", "ponytail", "twintails", "braid", "bun", "drill hair",
                 "wavy hair", "straight hair", "very long hair", "long hair", "short hair",
                 "medium hair", "streaked hair", "gradient hair", "multicolored hair",
                 "colored inner hair", "two-tone hair", "hair over one eye", "hair tubes",
                 "hair scrunchie", "hair bow", "hairpin", "blunt bangs", "cowlick", "low twintails",
                 "high ponytail", "side ponytail", "braided ponytail", "braided bun", "double bun",
                 "hair intakes", "scrunchie", "hair bobbles", "hair between eyes", "hair rings",
                 "single hair bun", "hair bun", "hair clip")

EYE_KEYWORDS = ("eyes", "eye", "pupils", "pupil", "eyelashes", "eyebrows", "eyeliner", "heterochromia",
                "glasses", "contacts", "blindfold", "mole", "fang", "freckles", "facial mark",
                "blush", "smile", "teeth", "tongue", "expression", "face", "cheeks", "eyebrow",
                "eyewear", "crying", "tears", "crossed eyes", "narrowed eyes", "closed eyes",
                "half-closed eyes", "looking at viewer", "looking")

BODY_KEYWORDS = ("breasts", "breast", "cleavage", "navel", "midriff", "belly", "stomach", "waist",
                 "hips", "thigh", "leg", "feet", "foot", "barefoot", "toes", "skin", "shoulder",
                 "armpits", "armpit", "arm", "hand", "finger", "nail", "collarbone", "neck", "back",
                 "butt", "ass", "small breasts", "large breasts", "big breasts", "flat chest", "curvy",
                 "slim", "petite", "muscular", "chubby", "abs", "body", "figure", "beauty mark",
                 "nipples", "pussy", "penis", "testicles", "pubic hair", "anus", "underboob",
                 "sideboob", "kneepits", "inner thigh")

POSE_KEYWORDS = ("standing", "sitting", "kneeling", "lying", "on back", "on stomach", "on side",
                 "all fours", "crawling", "spread legs", "legs up", "leg up", "knee up", "squatting",
                 "leaning", "bent over", "arched back", "looking back", "looking away", "looking down",
                 "looking up", "facing viewer", "facing away", "from behind", "from above", "from below",
                 "side view", "front view", "three-quarter view", "cowgirl position", "missionary",
                 "doggystyle", "sex", "posing", "pose", "walking", "running", "jumping", "lying down",
                 "hand on hip", "hand on knee", "arms behind back", "arms up", "hands up", "spreading",
                 "spread", "hugging", "kissing", "holding", "carrying", "dancing", "sleeping",
                 "crouching", "straddling", "riding", "groping", "fondling", "on all fours",
                 "legs apart", "kneeling", "arm support", "ass up")

SCENE_KEYWORDS = ("indoor", "outdoor", "classroom", "bedroom", "kitchen", "bathroom", "bath", "shower",
                  "street", "city", "building", "room", "house", "garden", "park", "beach", "sea", "ocean",
                  "sky", "cloud", "night", "day", "morning", "evening", "background", "window", "door",
                  "doorway", "bed", "table", "desk", "chair", "floor", "wall", "snow", "rain", "forest",
                  "mountain", "school", "laboratory", "office", "train", "station", "car", "aircraft",
                  "space", "underwater", "dark room", "darkness", "dark", "stage", "balcony", "café",
                  "restaurant", "library", "pool", "hot spring", "onsen", "bathhouse", "ruins", "temple",
                  "residential area", "urban", "alley", "street")

LIGHT_KEYWORDS = ("light", "lighting", "sunlight", "moonlight", "backlighting", "backlight", "shadow",
                  "shadows", "glow", "glowing", "illumination", "ambient", "flash", "neon", "silhouette",
                  "rim light", "candlelight", "lamplight", "twilight", "dawn", "dusk", "sunset", "sunrise")

STYLE_KEYWORDS = ("anime screencap", "screencap", "chibi", "3d", "pvc", "game style", "official style",
                  "sketch", "lineart", "watercolor", "oil painting", "illustration", "painting",
                  "artwork", "style", "cgi", "pixel", "manga", "comic", "cell shading", "flat color",
                  "monochrome", "grayscale", "colorful", "pastel", "dark persona", "fanart", "cover",
                  "poster", "logo", "render", "blurry background", "blur", "depth of field", "bokeh",
                  "perspective", "wide shot", "close-up", "closeup", "full body", "upper body",
                  "cowboy shot", "portrait", "headshot", "medium shot", "low angle", "high angle",
                  "dutch angle", "foreshortening", "dynamic angle", "center", "symmetrical", "frame",
                  "focus", "vignetting", "motion blur", "motion lines", "speed lines", "screen tone",
                  "gradient background", "grey background", "white background", "plain background",
                  "simple background", "art", "noir", "borders", "border")

NEGATIVE_KEYWORDS = ("worst quality", "low quality", "bad anatomy", "bad hands", "extra fingers",
                     "watermark", "signature", "text", "jpeg artifacts", "lowres", "blurry", "censored")

COLOR_WORDS = {"white", "black", "blue", "red", "pink", "purple", "green", "brown", "yellow", "grey",
               "gray", "orange", "gold", "silver", "aqua", "blonde", "multicolor", "two-tone",
               "light", "dark", "colorful", "teal", "cyan", "violet", "indigo", "tan", "olive"}


def _has(tag_norm, words):
    """词边界子串匹配：'thigh' 匹配 'thigh' 但不匹配 'thighhighs'（按空格归一后）。"""
    for w in words:
        if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", tag_norm):
            return True
    return False


def is_trigger_or_char(tag):
    if not tag or not re.search(r"[A-Za-z]", tag):
        return False
    low = tag.lower().replace("_", " ")
    low = re.sub(r"\s+", " ", low)
    if low in COUNT_TAGS:
        return False
    # 含括号的角色tag：unicorn(azur lane)、Mb_Def 等
    if re.search(r"\([^)]*\)", tag):
        return True
    # 触发词常见形态：首字母大写专有名词
    if tag[0].isupper() and low.split(" ")[0] not in COLOR_WORDS and len(tag) >= 3 and " " not in tag.strip():
        return True
    # 大写驼峰 / 数字版本 / 下划线缩写
    if re.search(r"[a-z][A-Z]", tag) and len(tag) >= 4:
        return True
    if re.search(r"[A-Za-z]{2,}\d[A-Za-z\d]{1,}", tag) or re.search(r"[A-Za-z]+_[A-Za-z]+_?\d?", tag):
        return True
    if "_" in tag and len(tag) <= 24 and not _has(low, ("hair", "eyes", "dress", "skirt", "shirt",
                                                       "glove", "sock", "boot", "thighhigh", "uniform")):
        return True
    return False


def classify_tags(tags):
    out = {"subject": [], "appearance": [], "clothing": [], "pose": [],
           "scene": [], "lighting": [], "style": [], "negative": [], "other": []}
    for t in tags:
        raw = str(t).strip().strip("，,、")
        if not raw:
            continue
        low = raw.lower().replace("_", " ")
        low = re.sub(r"\s+", " ", low).strip()
        if low in COUNT_TAGS:
            out["subject"].append(raw)
        elif _has(low, SERIES_KEYWORDS):
            out["subject"].append(raw)
        elif is_trigger_or_char(raw):
            out["subject"].append(raw)
        elif _has(low, ROLE_KEYWORDS):
            out["subject"].append(raw)
        elif _has(low, CLOTHING_KEYWORDS):
            out["clothing"].append(raw)
        elif _has(low, HAIR_KEYWORDS) or _has(low, EYE_KEYWORDS) or _has(low, BODY_KEYWORDS):
            out["appearance"].append(raw)
        elif _has(low, POSE_KEYWORDS):
            out["pose"].append(raw)
        elif _has(low, SCENE_KEYWORDS):
            out["scene"].append(raw)
        elif _has(low, LIGHT_KEYWORDS):
            out["lighting"].append(raw)
        elif _has(low, STYLE_KEYWORDS):
            out["style"].append(raw)
        elif _has(low, NEGATIVE_KEYWORDS):
            out["negative"].append(raw)
        else:
            out["other"].append(raw)
    return {k: ", ".join(v).strip() for k, v in out.items()}
