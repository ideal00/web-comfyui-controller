"""Route existing visual-library tags to compiler fields without adding prompt text.

Catalogues are not homogeneous: an eye state is an expression, an ear shape is
appearance, and holding a weapon is a pose. Each image can therefore contribute
one independent, English-only component per section.
"""
import re
from collections import defaultdict

LABELS = dict(subject='人物与角色', appearance='外貌', expression='表情', clothing='服装与材质',
              pose='姿势', composition='构图与镜头', scene='场景', lighting='光线',
              artist='画师 / 画风', manual='其他补充')
CATALOGUES = {
    '泳装展示':'clothing', '衬衫展示':'clothing', '裙子展示':'clothing', '鞋子展示':'clothing',
    '袜子展示':'clothing', '套装展示':'clothing', '裤子展示':'clothing', '上衣':'clothing',
    '礼服':'clothing', '面部配饰':'clothing', '颈部配饰':'clothing', '手部配饰展示':'clothing',
    '身体配饰':'clothing', '耳饰':'clothing', '发型展示':'appearance', '眼睛':'appearance',
    '身体部位':'appearance', '面部表情展示':'expression', '姿势-基础姿势':'pose',
    '腿部姿势与移动':'pose', '手臂姿势':'pose', '手势':'pose', '物体互动':'pose',
    '背景':'scene', '视角构图':'composition', '画风':'artist', '色彩光影':'artist',
    '武器':'manual', '二创属性':'subject', '二次元属性':'appearance', '身份设定':None,
}

def words(text):
    return set(text.split())

EXPRESSION = words('expressionless blush blush_stickers nose_blush smug smirk pout one_eye_closed '
    'closed_eyes half-closed_eyes narrowed_eyes blinking unusually_open_eyes tongue_out closed_mouth '
    'open_mouth parted_lips puffy_cheeks covering_mouth')
POSE = words('head_tilt looking_away wariza yokozuwari hugging_own_legs arms_behind_back paw_pose '
    'v finger_heart heart_hands elbows_on_table hands_up index_fingers_together crossed_ankles '
    'putting_on_footwear taking_off_footwear adjusting_footwear holding_shoes')
APPEARANCE = words('animal_ears fake_animal_ears pointy_ears long_pointy_ears large_ears small_ears '
    'cat_ears fang fangs sharp_teeth heart-shaped_pupils star-shaped_pupils cross-shaped_pupils '
    'x-shaped_pupils diamond-shaped_pupils slit_pupils bare_shoulders bare_arms barefoot '
    'hair_over_eyes hair_over_one_eye')
CLOTHING = words('neck_ribbon waist_apron sleeves_past_wrists sleeves_past_fingers oversized_clothes '
    'off_shoulder zettai_ryouiki bandage_over_one_eye blindfold')
COMPOSITION = words('depth_of_field bokeh blurry_foreground blurry_background motion_blur '
    'vignetting border chibi_inset projected_inset zoom_layer from_inside from_outside')
LIGHTING = words('backlighting overlighting sidelighting underlighting bloom caustics lens_flare '
    'diffraction_spikes light_rays drop_shadow overexposure chiaroscuro silhouette '
    'see-through_silhouette bright_background dark_background')
SUBJECT = words('loli gyaru onee_gyaru tomboy tsundere yandere pirate witch wizard mage doctor '
    'nurse soldier knight elf dark_elf angel demon nun priest monk ninja samurai police '
    'mermaid orc goblin dwarf dragon_girl android cyborg robot vampire zombie fairy '
    'bounty_hunter astronaut scientist teacher maid butler chef idol musician dancer alchemist '
    'archer artist bard barista dentist druid firefighter gym_teacher miko necromancer '
    'onmyouji paladin paramedic pilot plague_doctor ronin sailor surgeon traditional_nun')
CLOTHING.update(words('eyepatch medical_eyepatch glasses eyewear bandages frills fur_trim '
    'frilled_cuffs tricorn hood slacks scrubs coveralls labcoat headband headscarf hair_ornament '
    'hair_stick hairnet sam_browne_belt eboshi kariginu kusazuri sode suneate yuanlingpao '
    'gun_holster holster shoulder_holster quiver earpiece headset mouthguard ruff cravat circlet '
    'tiara insignia name_tag beads protective_eyewear'))
APPEARANCE.update(words('antlers black_wings fox_ears halo mechanical_limbs robot_joints single_mechanical_arm'))
STYLE = words('cyberpunk medieval renaissance victorian western cowboy_western camouflage')

def bare(token):
    """Read existing NAI weights; compiler dialect will format the underlying tag."""
    token = token.strip()
    match = re.fullmatch(r'[0-9.]+::(.+)::', token)
    return match[1] if match else token

def classify(tag, category, group='', known=None):
    if tag in COMPOSITION: return 'composition'
    if tag in LIGHTING: return 'lighting'
    if tag in EXPRESSION: return 'expression'
    if tag in POSE or tag.startswith(('holding_', 'grabbing_', 'hand_under_', 'putting_on_', 'taking_off_', 'adjusting_')):
        return 'pose'
    if tag in APPEARANCE: return 'appearance'
    if tag in CLOTHING: return 'clothing'
    if category == '身份设定':
        if tag in SUBJECT: return 'subject'
        if tag in STYLE: return 'artist'
        if tag.endswith(('_hat','_cap','_helmet','_headdress','_headdress)', '_clothes','_uniform',
                         '_armor','_suit','_vest','_belt','_sleeves','_gloves','_boots','_collar',
                         '_dress','_robe','_hanfu','_eyewear','_cuffs','_cloak','_jewelry','_apron')): return 'clothing'
        return (known or {}).get(tag, 'manual')
    if category == '二次元属性' and tag in SUBJECT: return 'subject'
    if category == '眼睛' and group == '闭眼与眼部状态': return 'expression'
    if category == '面部表情展示' and group == '特殊瞳孔': return 'appearance'
    if category == '耳饰' and group == '耳朵形态': return 'appearance'
    if category == '袜子展示' and group == '动作互动': return 'pose'
    if category == '色彩光影' and group in {'光照方向','光线形态与光学效果','时段光线','自然光源','人工光源','阴影与暗部'}:
        return 'lighting'
    if category == '二创属性':
        if group in {'整体服装变化','局部服饰/配件变化'}: return 'manual' if 'weapon' in tag else 'clothing'
        if group in {'身体特征变化','头发变化','眼睛变化','年龄变化'}: return 'expression' if tag == 'unusually_open_eyes' else 'appearance'
        if group == '整体配色变化': return 'artist'
    return CATALOGUES.get(category) or (known or {}).get(tag, 'manual')

def split_entry(entry, known=None):
    sections = defaultdict(list)
    for token in str(entry.get('tags') or entry.get('tag') or '').split(','):
        tag = bare(token)
        # Chinese labels, model examples and malformed empty tokens never enter prompts.
        if not tag or re.search(r'[\u3400-\u9fff]', tag): continue
        section = classify(tag, entry.get('category',''), entry.get('group_name') or entry.get('group',''), known)
        if tag not in sections[section]: sections[section].append(tag)
    return dict(sections)

def build_catalog(rows):
    known = {}
    for entry in rows:
        if entry.get('category') == '身份设定': continue
        for section, tags in split_entry(entry).items():
            for tag in tags: known.setdefault(tag, section)
    results, counts = [], defaultdict(int)
    for entry in rows:
        sections = split_entry(entry, known)
        for section,tags in sections.items():
            counts[section] += 1
            results.append(dict(id=f"visual:{entry['id']}:{section}", visualId=entry['id'],
                section=section, name=entry.get('name_zh') or entry.get('tag'), tags=tags,
                description=entry.get('description',''), category=entry.get('category',''),
                group=entry.get('group_name',''), split=len(sections)>1,
                image=bool(entry.get('image_path')) and entry.get('image_status')=='ready'))
    return dict(results=results, counts=dict(counts), labels=LABELS)
