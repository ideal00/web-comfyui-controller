import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

spec = importlib.util.spec_from_file_location('lora_preview_import', Path(__file__).resolve().parents[1] / 'tools/import_lora_previews.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LoraPreviewImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.models = self.root / 'loras'
        self.model = self.models / 'Anima_Soft_Illustration/04_画风与概念/Renamed.safetensors'
        self.model.parent.mkdir(parents=True)
        self.model.write_bytes(b'installed model')
        self.output = self.root / 'outputs'
        self.output.mkdir()
        self.entry = {'file':'OldName.safetensors','lora_name':'Anima_Soft_Illustration/OldName.safetensors',
                      'sha256':module.sha256(self.model),'filename_prefix':'anima/test-01'}
        self.manifest = {'width':768,'height':1024,'weight':0.8,'seed':1234,'steps':30,'entries':[self.entry]}
        self.manifest_path = self.root / 'manifest.json'
        self.manifest_path.write_text(json.dumps(self.manifest),encoding='utf-8')
        self.notes_path = self.root / 'notes.json'
        self.note = {'title':'Existing','trigger':'','outfits':[{'name':'style','main_class':'style','style':'real_trigger'}]}
        self.notes_path.write_text(json.dumps({self.model.name:self.note}),encoding='utf-8')
        self.graph = {'1':{'class_type':'LoraLoader','inputs':{'lora_name':self.entry['lora_name'],'strength_model':0.8,'strength_clip':0.8}},
                      '2':{'class_type':'KSampler','inputs':{'seed':1234,'steps':30}}}
        self.write_image()
        self.addCleanup(patch.stopall)
        patch.object(module.preset_examples,'EXAMPLE_DIR',self.root / 'examples').start()

    def write_image(self):
        meta = PngImagePlugin.PngInfo()
        meta.add_text('prompt',json.dumps(self.graph))
        Image.new('RGB',(768,1024),'blue').save(self.output / 'test-01_00001_.png',pnginfo=meta)

    def run_import(self):
        return module.import_previews(self.manifest_path,self.output,self.models,self.notes_path,self.root / 'new/report.json')

    def test_hash_matches_renamed_model_and_preserves_prompt_fields(self):
        report = self.run_import()
        self.assertEqual(len(report['bound']),1)
        notes = json.loads(self.notes_path.read_text(encoding='utf-8'))
        attached = notes[self.model.name]
        for key,value in self.note.items(): self.assertEqual(attached[key],value)
        self.assertEqual(attached['referenceImage']['modelSha256'],self.entry['sha256'])
        self.assertTrue(self.model.with_suffix('.preview.png').exists())
        self.assertTrue((self.root / 'new/lora_notes.before-preview-import.json').exists())

    def test_repeated_import_is_idempotent(self):
        first = self.run_import()
        before = self.notes_path.read_bytes()
        second = self.run_import()
        self.assertEqual(first,second)
        self.assertEqual(before,self.notes_path.read_bytes())
        self.assertEqual(len(list((self.root / 'examples').glob('*.webp'))),1)

    def test_wrong_image_model_is_rejected(self):
        self.graph['1']['inputs']['lora_name'] = 'Other.safetensors'
        self.write_image()
        with self.assertRaisesRegex(ValueError,'Image LoRA differs'): self.run_import()
        self.assertNotIn('referenceImage',json.loads(self.notes_path.read_text())[self.model.name])

    def test_wrong_weight_is_rejected(self):
        self.graph['1']['inputs']['strength_model'] = 1.0
        self.write_image()
        with self.assertRaisesRegex(ValueError,'Image parameters differ'): self.run_import()

    def test_missing_model_has_no_binding(self):
        self.model.unlink()
        report = self.run_import()
        self.assertEqual(len(report['missing_models']),1)
        self.assertEqual(report['bound'],[])


if __name__ == '__main__':
    unittest.main()
