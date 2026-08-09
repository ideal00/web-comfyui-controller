"""AI prompt translation providers and prompt classification."""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from easy_panel_app.prompt_utils import (
    normalized_safety_level,
    split_prompt_terms,
    unique_prompt_terms,
)

DEFAULT_AI_CHAT = "https://api.deepseek.com/chat/completions"
DEFAULT_ANTHROPIC_MESSAGES = "https://api.anthropic.com/v1/messages"
DEFAULT_GEMINI_GENERATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GOOGLE_TRANSLATE = "https://translation.googleapis.com/language/translate/v2"
PROMPT_SECTION_KEYS = (
    "subject", "appearance", "clothing", "pose", "composition",
    "scene", "lighting", "style", "manual",
)

_ANIMA_TRANSLATION_PROMPT = """\
You are an Anima prompt adapter. Convert the user's Chinese image description into one precise English positive prompt for Anima.

Rules:
1. Preserve every explicitly stated subject, appearance, garment, pose, action, expression, camera angle, setting, lighting, color, and medium. Never invent or remove elements.
2. The message contains application fields (ANIMA_PREFIX, SAFETY_TAG) followed by CHINESE_DESCRIPTION:. Insert their values where told, ignore empty ones, and never output field names.
3. Place LoRA triggers, <lora:...>, embeddings, wildcards, and weights like (concept:1.5) verbatim at the very start, in original order. Character, series, and artist tags are preserved but placed in their section below.
4. After triggers, order: quality/meta, safety, subject count, character, series, artist, appearance, clothing, pose/action, expression/gaze, composition/camera, setting, lighting/color/style, then natural-language sentence if any.
5. Lowercase normal tags; underscores to spaces (keep only in score_*); prefer canonical Gelbooru terms; comma-separated; concise. Merge duplicates, synonyms, and hierarchies (e.g. "very long hair" not "long hair, very long hair").
6. Artist: output "@artist name" only when given; never invent one.
7. Use 1-2 concise English sentences only when needed (multiple subjects, complex poses, hand placement, spatial relations); clearly attribute each action to the right subject.
8. Keep about 10-45 meaningful tags; never add filler quality spam unless requested.
9. Put ANIMA_PREFIX after any triggers; use SAFETY_TAG as the rating; add no other quality or score_* tags.
10. Output only the final positive prompt, one line, no headings, explanations, quotation marks, Markdown, JSON, negative prompt, or alternatives.
"""

_ILLUSTRIOUS_TRANSLATION_PROMPT = """\
You are an Illustrious XL prompt adapter. Convert the user's Chinese description into one compact English positive prompt using canonical Danbooru tags (natural language only for actions tags cannot express).

Rules:
1. Keep every stated subject/count, character and series name, physical appearance, hairstyle, clothing, pose/action, interaction, expression, gaze, camera distance and angle, foreground/background, lighting/color, style/medium. Never invent details, identity, franchise, or story elements.
2. The message contains ILLUSTRIOUS_PREFIX followed by CHINESE_DESCRIPTION:. Insert its value, ignore empty ones, and never output field names.
3. Place LoRA triggers, <lora:...>, embeddings, wildcards, escaped character tags, and existing weights verbatim at the start; never translate them.
4. Order: triggers, quality prefix, subject count, character/series, major appearance, hair/face, clothing/accessories, pose, action/interaction, expression/gaze, framing/camera, background/environment, lighting/color, style/medium.
5. Lowercase ordinary tags with spaces, not underscores (keep underscores only inside protected, parenthetical, or tag-database tokens); comma-separated; prefer Danbooru terms. Deduplicate and merge synonyms/hierarchies (e.g. "white collared shirt" not "shirt, white shirt, collared shirt").
6. Use an established character/series tag only when present in the input or the application tag database; otherwise keep the readable name.
7. Simple scenes: tags only. Complex relationships: add one short clause identifying each subject; never write the whole output as prose.
8. Use ILLUSTRIOUS_PREFIX as the quality prefix; add no score_* or "very awa" tags, model magic words, or conflicting quality tiers.
9. Keep the smallest tag set that fully preserves the request (about 12-50 typical).
10. Output only the final positive prompt, one line, no explanations, headings, categories, bullet points, Markdown, JSON, negative prompt, comments, or alternatives.
"""

_KREA_TRANSLATION_PROMPT = """\
You are a Krea 2 prompt editor. Convert the user's Chinese description into one clear, visually grounded English prompt that reads as a coherent image description (not a tag list).

Rules:
1. Keep every stated subject, appearance, hairstyle, clothing/accessory, pose/action, interaction, expression, gaze, camera view, environment, lighting, color palette, medium, and style. Never invent elements, visible text, or story events.
2. The message contains KREA_EXPANSION_MODE and CHINESE_DESCRIPTION:. Insert their values, ignore empty ones, and never output field names.
3. Place LoRA or style trigger words verbatim at the very start, followed by a comma; keep character/series names and requested quoted text exactly.
4. Describe in natural order: subject, defining appearance, clothing/accessories, pose/action, interaction and spatial relations, expression/gaze, composition and framing, setting/background, lighting/color/texture/atmosphere. Flow naturally, not template-like.
5. For multiple characters, associate each with their own appearance, clothing, position, action, and gaze using explicit spatial wording (left/right/foreground/behind/facing); avoid ambiguous pronouns.
6. KREA_EXPANSION_MODE: strict = add no unspecified lighting, framing, style, medium, color, atmosphere, or scene detail; balanced = may add one restrained framing/lighting/medium when unspecified. In both, never add subjects, objects, clothing, colors, locations, identities, or story.
7. Describe poses physically: body orientation, head/torso direction, visible hands, contact, camera-relative direction, standing/sitting/kneeling/reclining/moving. No unrequested poses.
8. Use concrete visual language (e.g. "soft directional lighting", "low-angle medium shot"); avoid promotional fluff ("breathtaking", "perfect", "viral artwork").
9. Reproduce requested in-image text exactly inside English quotation marks.
10. Length proportional to input (about 15-50 words simple, 50-140 detailed); no filler.
11. Output only the final prompt as one cohesive paragraph; no reasoning, explanations, headings, bullet points, Markdown, JSON, negatives, alternatives, or surrounding quotes.
"""


def ai_prompt_system(family: str) -> str:
    """Return the model-family-specific translation system prompt (production spec)."""
    family = str(family or "").strip().lower()
    if family == "krea2":
        return _KREA_TRANSLATION_PROMPT
    if family == "anima":
        return _ANIMA_TRANSLATION_PROMPT
    return _ILLUSTRIOUS_TRANSLATION_PROMPT


def validated_ai_endpoint(raw_endpoint: str, protocol: str, model: str) -> str:
    defaults = {
        "openai": DEFAULT_AI_CHAT,
        "anthropic": DEFAULT_ANTHROPIC_MESSAGES,
        "gemini": DEFAULT_GEMINI_GENERATE,
    }
    endpoint = str(raw_endpoint or defaults[protocol]).strip()
    if protocol == "gemini":
        endpoint = endpoint.replace("{model}", urllib.parse.quote(model, safe="-._"))
    if len(endpoint) > 1000:
        raise ValueError("AI 接口地址过长。")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("AI 接口地址必须是完整的 HTTP 或 HTTPS URL。")
    if parsed.username or parsed.password:
        raise ValueError("请勿把 API Key 写进接口 URL；请使用密钥输入框。")
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme == "http" and parsed.hostname.lower() not in local_hosts:
        raise ValueError("远程 AI 接口必须使用 HTTPS；HTTP 仅允许本机 Ollama 等服务。")
    return endpoint


def ai_auth_headers(api_key: str, auth_type: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if not api_key or auth_type == "none":
        return headers
    if auth_type == "bearer":
        headers["Authorization"] = "Bearer " + api_key
    elif auth_type == "x-api-key":
        headers["x-api-key"] = api_key
    elif auth_type == "api-key":
        headers["api-key"] = api_key
    elif auth_type == "x-goog-api-key":
        headers["x-goog-api-key"] = api_key
    else:
        raise ValueError("不支持的 API 鉴权方式。")
    return headers


def _openai_style_text(payload: dict) -> str:
    """Extract text from OpenAI-compatible responses across common shapes."""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                text = "\n".join(str(part.get("text", "")).strip() for part in content
                                 if isinstance(part, dict) and part.get("text")).strip()
                if text:
                    return text
            if content:
                return str(content).strip()
            # DeepSeek reasoner keeps the final answer in content; reasoning_content
            # is not a usable image prompt, so it is intentionally ignored.
        if first.get("text"):
            return str(first["text"]).strip()
    message = payload.get("message")
    if isinstance(message, dict) and message.get("content"):
        return str(message["content"]).strip()
    for key in ("response", "output_text", "content", "result", "output"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def ai_response_text(payload: dict, protocol: str) -> str:
    """Extract the assistant text from an AI response across common shapes.

    Returns "" when no text is found so callers can report a precise error.
    Raises ValueError when the service returned a business error with HTTP 200.
    """
    if not isinstance(payload, dict):
        return ""
    # Some compatible servers return {"error": {...}} while still replying HTTP 200.
    err = payload.get("error")
    if isinstance(err, dict):
        detail = err.get("message") or err.get("error") or err.get("type") or json.dumps(err, ensure_ascii=False)
        raise ValueError("AI 服务返回错误：%s" % str(detail)[:500])
    if isinstance(err, str) and err:
        raise ValueError("AI 服务返回错误：%s" % err[:500])

    if protocol == "anthropic":
        blocks = payload.get("content", [])
        text = "\n".join(str(block.get("text", "")).strip() for block in blocks
                         if isinstance(block, dict) and block.get("type") == "text").strip()
        if text:
            return text
        # Anthropic-compatible servers that reply OpenAI-style.
        return _openai_style_text(payload)

    if protocol == "gemini":
        candidates = payload.get("candidates", [])
        if isinstance(candidates, list) and candidates:
            first = candidates[0] if isinstance(candidates[0], dict) else {}
            content = first.get("content")
            if isinstance(content, dict):
                parts = content.get("parts", [])
                text = "\n".join(str(part.get("text", "")).strip() for part in parts
                                 if isinstance(part, dict) and part.get("text")).strip()
                if text:
                    return text
            for key in ("output", "text"):
                if first.get(key):
                    return str(first[key]).strip()
        if payload.get("output_text"):
            return str(payload["output_text"]).strip()
        return ""

    return _openai_style_text(payload)


def parse_ai_json(content: str) -> dict:
    cleaned = str(content or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start >= 0:
            try:
                value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                pass
    return {"sections": {"manual": cleaned}, "negative": ""}


# --- Flat English prompt -> panel section classifier (AI translation application) ---

_SECTION_ORDER = ("subject", "appearance", "clothing", "pose", "composition",
                  "scene", "lighting", "style", "manual")

_SUBJECT_TERMS = ("1girl", "2girls", "3girls", "1boy", "2boys", "woman", "man", "girl",
                  "boy", "solo", "character", "characters", "multiple girls",
                  "multiple characters", "group", "couple", "female", "male", "teenager",
                  "adult", "young woman", "young man", "loli", "shota", "milf", "person")

_APPEARANCE_TERMS = ("hair", "eyes", "pupils", "eyelashes", "eyebrows", "bangs", "sidelocks",
                     "braid", "ponytail", "twintails", "ahoge", "drill hair", "streaked hair",
                     "gradient hair", "hair between eyes", "hair ornament", "hairpin",
                     "hairclip", "hairband", "headband", "skin", "blush", "freckles", "mole",
                     "breasts", "cleavage", "body", "figure", "waist", "thighs", "legs",
                     "collarbone", "shoulders", "heterochromia", "navel", "midriff", "stomach",
                     "arms", "hands", "fingers", "toenails", "neck", "face", "expression",
                     "fang", "scar", "tattoo", "wings", "tail", "ears", "horns", "halo",
                     "slim", "curvy", "athletic", "large breasts", "small breasts",
                     "medium breasts", "covered breasts", "underboob", "sideboob",
                     "body markings", "skin fangs", "smile", "frown", "eyebrow", "fingernails",
                     "nails", "feet", "barefoot", "cleavage cutout", "collarbone")

_CLOTHING_TERMS = ("dress", "shirt", "blouse", "skirt", "pants", "shorts", "uniform", "coat",
                   "jacket", "sweater", "hoodie", "kimono", "robe", "cape", "cloak", "scarf",
                   "tie", "necktie", "ribbon", "bow", "belt", "sash", "gloves", "mittens",
                   "sleeves", "collar", "choker", "necklace", "pendant", "earrings", "ring",
                   "bracelet", "watch", "hat", "headwear", "cap", "beret", "veil", "crown",
                   "tiara", "pantyhose", "tights", "stockings", "thighhighs", "socks",
                   "leggings", "footwear", "shoes", "boots", "heels", "sandals", "mary janes",
                   "bikini", "swimsuit", "leotard", "bodysuit", "lingerie", "underwear",
                   "panties", "bra", "garter", "bodystocking", "apron", "corset", "camisole",
                   "jumpsuit", "overalls", "cardigan", "blazer", "hood", "vest", "waistcoat",
                   "poncho", "fabric", "lace", "frills", "fur", "leather", "denim", "pocket",
                   "buttons", "zipper", "armor", "breastplate", "gauntlets", "armlet",
                   "wristband", "cuffs", "sleeves past wrists", "showgirl skirt",
                   "pleated skirt", "sailor", "serafuku", "school uniform", "military uniform",
                   "gym uniform", "maid", "nun", "china dress", "pantsuit", "suit", "tuxedo",
                   "tank top", "crop top", "tube top", "halter", "bodice", "pelvic curtain",
                   "breast curtain", "thong", "swimwear", "wetsuit", "armor", "gauntlet",
                   "kneehighs", "anklet", "chaps", "capelet", "poncho", "overalls",
                   "playboy bunny", "bunnysuit", "bunny suit")

_POSE_TERMS = ("standing", "sitting", "lying", "kneeling", "crouching", "leaning", "walking",
               "running", "jumping", "dancing", "raising", "holding", "carrying", "hugging",
               "embracing", "kissing", "touching", "pointing", "looking at viewer",
               "looking back", "looking away", "looking to the side", "looking down",
               "looking up", "pose", "gesture", "hand on hip", "crossed legs", "spread legs",
               "arms up", "arms behind head", "arms crossed", "squatting", "crawling",
               "riding", "bent over", "prone", "supine", "spread", "groping", "caressing",
               "grabbing", "waving", "stretching", "bending", "turning", "reaching", "lifting",
               "hand in own panties", "masturbation", "thigh straddle", "ass up",
               "doggy style", "missionary", "cowgirl position", "standing on one leg",
               "sitting on", "kneeling on", "lying on", "leaning on", "leaning against",
               "back-to-back", "piggyback", "bridal carry", "hand on", "arm around",
               "headpat", "handholding", "hand-holding", "crossdressing", "pose")

_COMPOSITION_TERMS = ("full body", "upper body", "waist up", "bust", "portrait", "close-up",
                      "close up", "headshot", "medium shot", "wide shot", "long shot",
                      "low angle", "high angle", "bird's eye view", "first-person view",
                      "view", "perspective", "framing", "composition", "cropped",
                      "from behind", "from side", "from front", "depth of field", "focus",
                      "centered", "off-center", "rule of thirds", "head tilted", "cut-in",
                      "cowboy shot", "full shot", "closeup", "faraway", "distant",
                      "extreme close-up", "over-the-shoulder", "pov", "selfie")

_SCENE_TERMS = ("background", "indoors", "outdoor", "classroom", "corridor", "city", "street",
                "building", "room", "bedroom", "kitchen", "bathroom", "beach", "seaside",
                "ocean", "sea", "pool", "mountain", "forest", "park", "garden",
                "cherry blossoms", "snow", "rain", "night", "sky", "window", "door", "chair",
                "bed", "desk", "stage", "temple", "shrine", "castle", "palace", "throne",
                "rooftop", "balcony", "train", "car", "library", "cafe", "restaurant",
                "market", "alley", "bridge", "river", "lake", "water", "grass", "flowers",
                "tree", "clouds", "moon", "sun", "stars", "sign", "fence", "wall", "floor",
                "ceiling", "couch", "sofa", "table", "bath", "shower", "office", "school",
                "dormitory", "ship", "battlefield", "ruins", "space", "city lights", "bokeh",
                "winter", "autumn", "spring", "summer", "sunny", "meadow", "hill", "cliff",
                "cave", "desert", "waterfall", "pond", "boat", "airplane", "helicopter",
                "station", "platform", "elevator", "stairs", "sidewalk", "crosswalk",
                "neon city", "skyline", "horizon", "cloudy", "overcast", "indoors",
                "outdoors", "outside", "inside", "hospital", "laboratory", "garage",
                "workshop", "factory", "warehouse", "church", "cathedral", "graveyard",
                "cemetery", "dungeon", "cave")

_LIGHTING_TERMS = ("lighting", "light", "shadow", "sunlight", "daylight", "moonlight", "lamp",
                   "neon", "glow", "rim light", "backlight", "soft light", "hard light",
                   "sunset", "golden hour", "color grading", "palette", "colored",
                   "overexposed", "underexposed", "silhouette", "backlit", "candlelight",
                   "starlight", "spotlight", "fluorescent", "volumetric", "light rays",
                   "god rays", "twilight", "dusk", "dawn", "glowing", "luminous", "shade",
                   "highlight", "contrast", "bright", "dim", "dark", "moody", "warm light",
                   "cool light", "bokeh lights", "streetlight", "neon light")

_STYLE_TERMS = ("anime", "illustration", "painting", "lineart", "line art", "sketch",
                "watercolor", "cel shading", "cell shading", "3d", "3d render", "render",
                "photorealistic", "realistic", "artstyle", "art style", "aesthetic",
                "monochrome", "grayscale", "pastel", "oil painting", "acrylic",
                "digital painting", "concept art", "anime coloring", "flat color", "detailed",
                "intricate", "clean lineart", "semi-realistic", "pixel art", "chibi",
                "minimalist", "impressionist", "surreal", "fantasy art", "8k", "hd", "sharp",
                "vibrant", "muted", "saturated", "official art", "promotional art", "art",
                "traditional media", "film grain", "drawing", "painterly", "soft shading",
                "flat shading", "masterpiece", "best quality", "style", "colorful",
                "storybook", "comic", "manga", "cartoon", "graphic novel", "ukiyo-e",
                "abstract", "minimal", "glossy", "matte", "smooth")

# Compiler-managed control tokens: dropped from the sections so they are not duplicated
# or left stale when the user switches checkpoints. The compiler re-injects them.
_TRANSLATE_FILTER_PREFIX = ("score_",)
_TRANSLATE_FILTER_EXACT = frozenset((
    "masterpiece", "best quality", "amazing quality", "very awa", "highres", "absurdres",
    "newest", "ultra-detailed", "safe", "nsfw", "explicit", "sensitive", "lowres",
    "bad quality", "worst quality", "bad anatomy", "bad hands", "jpeg artifacts",
))

_NL_MARKERS = (" is ", " are ", " was ", " were ", " has ", " have ", " wearing ",
               " behind ", " beside ", " next to ", " in front of ", " on the ",
               " in the ", " at the ", " with the ", " facing ", " viewed from ",
               " between ", " from behind ", " to the left ", " to the right ",
               " in her ", " in his ", " her hand ", " his hand ", " one hand ",
               " both hands ", " she is ", " he is ", " they are ", " the other ",
               " while ")


def _is_natural_language(term: str) -> bool:
    words = [word for word in str(term).split() if word]
    if len(words) < 4:
        return False
    low = " " + str(term).lower() + " "
    return any(marker in low for marker in _NL_MARKERS)


_WEIGHT_BRACKET_RE = re.compile(r"\([^()]*:\s*(?:0(?:\.\d+)?|1(?:\.\d+)?|2(?:\.0+)?)\)")


def _is_trigger_like(term: str) -> bool:
    """Character/series/trigger tokens: parenthesised, camelCase, numbered, underscored.

    Prompt-weight syntax like (holding hands:1.2) is emphasis, not a trigger word,
    so it is stripped before the trigger-feature test.
    """
    stripped = _WEIGHT_BRACKET_RE.sub("", term)
    if stripped != term:
        if not stripped.strip():
            return False
        term = stripped
    return bool(re.search(r"\([^()]*\)|[a-z][A-Z]|[A-Za-z]{2,}\d|\w_\w", term))


def _matches_terms(low: str, terms: tuple) -> bool:
    """Whole-word match for single words, substring match for multi-word phrases.

    This keeps 'scarf' from matching the 'scar' appearance keyword while still
    matching phrases like 'looking at viewer' or 'long hair'.
    """
    words = set(low.split())
    for term in terms:
        if " " in term:
            if term in low:
                return True
        elif term in words:
            return True
    return False


def _split_sentence_tail(term: str) -> tuple:
    """Split 'anime style. She is sitting ...' into ('anime style', 'She is sitting ...').

    Tag-style output (Anima / Illustrious) can glue a trailing sentence to the last
    tag with '. '; return the tag head for classification and the sentence for the
    naturalLanguage section.
    """
    parts = re.split(r"(?<=[.!?])\s+", str(term or "").strip())
    if len(parts) <= 1:
        return str(term or "").strip(), ""
    sentence = parts[-1].strip()
    head = ", ".join(part.strip().rstrip(".!?") for part in parts[:-1] if part.strip())
    return head, sentence


def classify_english_prompt(text: str, family: str = "illustrious") -> dict:
    """Split a flat English positive prompt into panel sections.

    Krea 2 output is one natural-language paragraph and is kept whole in the
    naturalLanguage section. Tag-style output (Anima / Illustrious) is classified
    term by term; application-injected quality/safety tokens are dropped because
    the compiler re-injects them from the model profile.
    """
    sections: dict[str, list[str]] = {key: [] for key in _SECTION_ORDER}
    sections["naturalLanguage"] = []
    for term in split_prompt_terms(text, limit=240):
        head, sentence = _split_sentence_tail(term)
        if sentence:
            sections["naturalLanguage"].append(sentence)
        term = head
        low = str(term).strip().lower()
        if not low:
            continue
        if _is_natural_language(term):
            sections["naturalLanguage"].append(term)
            continue
        if low.startswith("@"):
            sections["style"].append(term)  # artist tag
            continue
        if low.startswith(_TRANSLATE_FILTER_PREFIX) or low in _TRANSLATE_FILTER_EXACT:
            continue
        match = _WEIGHT_BRACKET_RE.sub("", low).strip()
        if not match:
            inner = re.search(r"\(([^()]*):", low)
            match = inner.group(1).strip() if inner else low
        if _is_trigger_like(term) or _matches_terms(match, _SUBJECT_TERMS):
            sections["subject"].append(term)
        elif _matches_terms(match, _COMPOSITION_TERMS):
            sections["composition"].append(term)
        elif _matches_terms(match, _POSE_TERMS):
            sections["pose"].append(term)
        elif _matches_terms(match, _APPEARANCE_TERMS):
            sections["appearance"].append(term)
        elif _matches_terms(match, _CLOTHING_TERMS):
            sections["clothing"].append(term)
        elif _matches_terms(match, _SCENE_TERMS):
            sections["scene"].append(term)
        elif _matches_terms(match, _LIGHTING_TERMS):
            sections["lighting"].append(term)
        elif _matches_terms(match, _STYLE_TERMS):
            sections["style"].append(term)
        else:
            sections["manual"].append(term)
    if family == "krea2":
        # Natural-language family: keep the whole paragraph in one place.
        return {"naturalLanguage": str(text or "").strip()}
    return {key: ", ".join(values) for key, values in sections.items() if values}


TRANSLATION_MAX_TOKENS = {"anima": 260, "illustrious": 220, "krea2": 320}


def illustrious_quality_prefix(model_name: str) -> list[str]:
    """Checkpoint-aware Illustrious quality prefix; the translator and compiler share it."""
    name = Path(str(model_name or "")).name.lower()
    if "noobai" in name:
        return ["very awa", "masterpiece", "best quality", "newest", "highres", "absurdres"]
    if name.startswith("wai"):
        return ["masterpiece", "best quality", "amazing quality"]
    return ["masterpiece", "best quality"]


def translation_prefix(family: str, model: str, safety: str) -> str:
    """The quality prefix injected into the translator's user message, from model config."""
    if family == "anima":
        name = Path(str(model or "")).name.lower()
        return "masterpiece, best quality" if "aesthetic" in name else "masterpiece, best quality, score_7"
    if family == "krea2":
        return ""
    if family == "illustrious":
        return ", ".join(illustrious_quality_prefix(model))
    return "masterpiece, best quality, highres"


def build_translation_user_message(family: str, prefix: str, safety: str, text: str) -> str:
    """Assemble the translator user message: application fields then the Chinese description."""
    lines: list[str] = []
    if family == "anima":
        if prefix:
            lines.append("ANIMA_PREFIX: " + prefix)
        lines.append("SAFETY_TAG: " + safety)
    elif family == "illustrious":
        if prefix:
            lines.append("ILLUSTRIOUS_PREFIX: " + prefix)
    elif family == "krea2":
        lines.append("KREA_EXPANSION_MODE: balanced")
    lines.append("CHINESE_DESCRIPTION: " + str(text or "").strip())
    return "\n".join(lines)


def _is_param_rejected(detail: str) -> bool:
    """True when an OpenAI-compatible gateway rejected our extra sampling params."""
    low = (detail or "").lower()
    words = ("max_tokens", "top_p", "unsupported parameter", "unknown parameter",
             "not supported", "invalid parameter", "extra inputs", "unexpected parameter",
             "additional properties")
    return any(word in low for word in words)


def _is_reasoning_model(model: str) -> bool:
    """True for reasoning models whose output budget is split with reasoning_content."""
    name = str(model or "").lower().replace("_", "-")
    marks = ("reasoner", "thinking", "-r1", "-o1", "-o3", "-o4",
             "deepseek-v3.1", "deepseek-v4", "deepseek-r1", "v4-flash")
    return any(mark in name for mark in marks)


def _response_has_reasoning(payload: dict) -> bool:
    """True when the response carries reasoning_content (reasoning models)."""
    if not isinstance(payload, dict):
        return False
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and message.get("reasoning_content") is not None:
            return True
    return "reasoning_content" in payload or "reasoning" in payload


def _finish_reason_length(payload: dict) -> bool:
    """True when the response was cut off by the token budget (finish_reason=length)."""
    if not isinstance(payload, dict):
        return False
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0].get("finish_reason") == "length"
    return False


# Reasoning models spend output tokens on reasoning_content; the initial budget is
# already generous, and the retry ladder grows it further until an answer fits.
REASONING_MAX_TOKENS = 16384
REASONING_RETRY_BUDGETS = (16384, 32768)


def ai_translate(data: dict) -> dict:
    """Convert Chinese to a family-specific final English positive prompt.

    The system prompt is per model family (Anima / Illustrious / Krea 2) and the
    quality prefix, safety tag and expansion mode are injected as application fields
    so the translator never guesses model magic words.
    """
    api_key = str(data.get("apiKey", "")).strip()
    text = str(data.get("text", "")).strip()
    protocol = str(data.get("protocol", "openai")).strip().lower()
    auth_type = str(data.get("authType", "bearer")).strip().lower()
    model = str(data.get("model", "")).strip()
    checkpoint = str(data.get("checkpoint", "") or "")
    family = str(data.get("family", "illustrious")).strip().lower()
    if family not in {"anima", "illustrious", "krea2"}:
        family = "krea2" if family == "krea" else "illustrious"
    if protocol not in {"openai", "anthropic", "gemini"}:
        raise ValueError("接口协议仅支持 OpenAI 兼容、Anthropic 或 Gemini。")
    if protocol in {"anthropic", "gemini"} and not model:
        raise ValueError("该接口协议必须填写模型名称。")
    endpoint = validated_ai_endpoint(str(data.get("endpoint", "")), protocol, model)
    parsed = urllib.parse.urlparse(endpoint)
    is_local = (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
    if not api_key and auth_type != "none" and not is_local:
        raise ValueError("请填写 API Key，或把鉴权方式设为“无需密钥”。")
    if not text:
        raise ValueError("请先填写中文描述。")
    if len(text) > 6000:
        raise ValueError("中文描述过长，请控制在 6000 个字符以内。")
    if len(model) > 300:
        raise ValueError("模型名称过长。")

    system = ai_prompt_system(family)
    safety = normalized_safety_level(data)
    prefix = translation_prefix(family, checkpoint, safety)
    user_message = build_translation_user_message(family, prefix, safety, text)
    max_tokens = TRANSLATION_MAX_TOKENS.get(family, 220)
    if _is_reasoning_model(model):
        # Reasoning models spend output tokens on reasoning_content; give them headroom
        # so the final answer is not truncated to empty.
        max_tokens = REASONING_MAX_TOKENS

    def _make_body(max_tok: int) -> dict:
        if protocol == "anthropic":
            return {"model": model, "max_tokens": max_tok, "temperature": 0.2,
                    "system": system, "messages": [{"role": "user", "content": user_message}]}
        if protocol == "gemini":
            return {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                "generationConfig": {"temperature": 0.2, "topP": 0.9, "maxOutputTokens": max_tok},
            }
        body = {"messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user_message}],
                "temperature": 0.2, "top_p": 0.9, "max_tokens": max_tok}
        if model:
            body["model"] = model
        return body

    request_body = _make_body(max_tokens)

    headers = ai_auth_headers(api_key, auth_type)
    if protocol == "anthropic":
        headers["anthropic-version"] = "2023-06-01"

    def _post(body: dict):
        request = urllib.request.Request(endpoint, data=json.dumps(body).encode("utf-8"),
                                         method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8")), None
        except urllib.error.HTTPError as exc:
            return None, (exc.code, exc.read().decode("utf-8", "replace"))

    payload, http_err = _post(request_body)
    if http_err and protocol == "openai" and _is_param_rejected(http_err[1]):
        # Some OpenAI-compatible gateways reject max_tokens / top_p / temperature.
        slim = {"messages": request_body["messages"]}
        if request_body.get("model"):
            slim["model"] = request_body["model"]
        payload, http_err = _post(slim)
    if http_err:
        raise ValueError("AI 请求失败（HTTP %s）：%s" % (http_err[0], http_err[1][:700]))
    content = ai_response_text(payload, protocol)
    if not content and (_response_has_reasoning(payload) or _finish_reason_length(payload)):
        # Reasoning content (or a plain truncation) burned the output budget, leaving
        # the final answer empty. Retry with progressively larger budgets.
        for budget in REASONING_RETRY_BUDGETS:
            if budget <= max_tokens:
                continue
            payload, http_err = _post(_make_body(budget))
            if http_err:
                break
            max_tokens = budget
            content = ai_response_text(payload, protocol)
            if content:
                break
            if not _response_has_reasoning(payload) and not _finish_reason_length(payload):
                break
    if not content:
        snippet = json.dumps(payload, ensure_ascii=False)[:400]
        reason = "该模型把输出预算全用于思维链推理，多次提高预算后仍未返回正文。" if _response_has_reasoning(payload) else "输出可能被截断。"
        raise ValueError(
            "AI 接口返回成功，但没有找到文本内容；%s"
            "服务端返回：%s" % (reason, snippet)
        )

    positive = str(content or "").strip()
    negative = ""
    prompt_mode = "flat"
    sections: dict = {}
    # Robust fallback: if a model returns JSON sections anyway, convert them.
    if positive.startswith("{") and ("sections" in positive or "negative" in positive):
        parsed_result = parse_ai_json(positive)
        raw_sections = parsed_result.get("sections", {}) if isinstance(parsed_result, dict) else {}
        if isinstance(raw_sections, dict) and any(raw_sections.values()):
            sections = {}
            for key in (*PROMPT_SECTION_KEYS, "naturalLanguage"):
                value = raw_sections.get(key, "")
                if isinstance(value, list):
                    value = ", ".join(str(item) for item in value if str(item).strip())
                sections[key] = str(value or "").strip()
            positive = unique_prompt_terms(*(sections[key] for key in PROMPT_SECTION_KEYS))
            if sections["naturalLanguage"]:
                positive = positive.rstrip(" .") + ". " + sections["naturalLanguage"]
            negative = str(parsed_result.get("negative", "") if isinstance(parsed_result, dict) else "").strip()
            prompt_mode = "sections"
    if not sections:
        sections = classify_english_prompt(positive, family)
    return {"positive": positive, "negative": negative, "protocol": protocol,
            "family": family, "promptMode": prompt_mode, "prefix": prefix,
            "sections": sections}


def google_translate(data: dict) -> dict:
    """Official Google Cloud Translation Basic v2 request."""
    api_key = str(data.get("apiKey", "")).strip()
    text = str(data.get("text", "")).strip()
    if not api_key:
        raise ValueError("请先在面板中填写 Google Cloud Translation API Key。")
    if not text:
        raise ValueError("请先填写中文描述。")
    if len(text) > 6000:
        raise ValueError("中文描述过长，请控制在 6000 个字符以内。")
    encoded = json.dumps({"q": text, "source": "zh-CN", "target": "en", "format": "text"}).encode("utf-8")
    endpoint = GOOGLE_TRANSLATE + "?" + urllib.parse.urlencode({"key": api_key})
    request = urllib.request.Request(endpoint, data=encoded, method="POST", headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise ValueError("Google 翻译请求失败（HTTP %s）：%s" % (exc.code, detail[:500])) from exc
    translated = payload.get("data", {}).get("translations", [{}])[0].get("translatedText", "")
    positive = html.unescape(str(translated)).strip()
    return {"positive": positive, "negative": "",
            "sections": {"naturalLanguage": positive}}

__all__ = [
    "ai_auth_headers",
    "ai_prompt_system",
    "ai_response_text",
    "ai_translate",
    "build_translation_user_message",
    "classify_english_prompt",
    "google_translate",
    "illustrious_quality_prefix",
    "parse_ai_json",
    "translation_prefix",
    "validated_ai_endpoint",
]
