import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from easy_panel_app.visual_tag_sections import build_catalog, split_entry
from easy_panel_app import visual_tag_library as vtl


class VisualSectionTests(unittest.TestCase):
    def test_mixed_catalogues_split_by_semantics(self):
        cases = [('色彩光影','光照方向','backlighting','lighting'),
                 ('色彩光影','整体色调与配色','pastel_colors','artist'),
                 ('眼睛','闭眼与眼部状态','closed_eyes','expression'),
                 ('眼睛','虹膜颜色','blue_eyes','appearance'),
                 ('眼睛','遮挡与眼部配饰','eyepatch','clothing'),
                 ('耳饰','耳朵形态','pointy_ears','appearance'),
                 ('耳饰','耳环基础','earrings','clothing'),
                 ('武器','','sword','manual'), ('物体互动','','holding_sword','pose'),
                 ('画风','纹理与特殊效果','depth_of_field','composition')]
        for category,group,tag,section in cases:
            with self.subTest(tag=tag):
                self.assertEqual(split_entry(dict(category=category,group_name=group,tag=tag)),{section:[tag]})

    def test_identity_components_use_only_existing_english_and_retain_one_image(self):
        data=build_catalog([
            dict(id='shirt',category='上衣',tag='coat'),
            dict(id='role',name_zh='海盗',category='身份设定',
                 tag='1.35::pirate::, 1.2::pirate_hat::, coat, holding_sword, cutlass',
                 image_path='ref.jpg',image_status='ready',sample='1girl, lumine')])
        parts={r['section']:r for r in data['results'] if r['visualId']=='role'}
        self.assertEqual(parts['subject']['tags'],['pirate'])
        self.assertEqual(parts['clothing']['tags'],['pirate_hat','coat'])
        self.assertEqual(parts['pose']['tags'],['holding_sword'])
        self.assertEqual(parts['manual']['tags'],['cutlass'])
        self.assertTrue(all(r['image'] and r['split'] for r in parts.values()))
        self.assertNotIn('lumine',str(parts))
        self.assertEqual(split_entry(dict(category='身份设定',tag='海盗')), {})

    def test_new_document_aliases_preserve_hyphenated_and_combination_tags(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'doc.md'
            p.write_text('''## 1. 海盗
<img src="images/ref.jpg">
| 职业/身份原型（中文） | 海盗 |
| NovelAI / Danbooru Tag 串 | 1.35::pirate::, 1.28::pirate_hat:: |
| 组合思路（大白话） | 帽子和外套 |
| 世界细分 | 航海 |
''',encoding='utf-8')
            row=vtl.parse_document(p,'身份设定')[0]
            self.assertEqual(row['tag'],'1.35::pirate::, 1.28::pirate_hat::')
            self.assertEqual(row['name_zh'],'海盗')
            self.assertEqual(row['group_name'],'航海')
            p.write_text('''## 1. half-closed_eyes, smirk — 半闭眼坏笑
<img src="images/ref.jpg">
| 二次元属性的中文名 | 半闭眼坏笑 |
| Danbooru tag / NovelAI tag串 | half-closed_eyes, smirk |
''',encoding='utf-8')
            self.assertEqual(vtl.parse_document(p,'二次元属性')[0]['tag'],'half-closed_eyes, smirk')

    def test_gallery_section_filter_matches_only_its_components(self):
        rows=[dict(id='light',category='色彩光影',tag='backlighting'),
              dict(id='color',category='色彩光影',tag='pastel_colors')]
        with mock.patch.object(vtl,'ensure_index',return_value={'available':True}),mock.patch.object(vtl,'_rows',return_value=rows):
            result=vtl.search('',section='lighting')
        self.assertEqual(result['matched'],1)
        self.assertEqual(result['results'][0]['id'],'light')
        self.assertEqual(result['results'][0]['compiler_sections'][0]['label'],'光线')


if __name__ == '__main__': unittest.main()
