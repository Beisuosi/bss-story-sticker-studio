import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw

spec = importlib.util.spec_from_file_location('studio', Path(__file__).resolve().parents[1]/'scripts/studio.py')
studio = importlib.util.module_from_spec(spec); spec.loader.exec_module(studio)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        photo = self.root/'photo.png'; Image.new('RGB', (60, 60), 'tan').save(photo)
        self.project = self.root/'project'; studio.init(self.project, photo)
        plan = json.loads((self.project/'plan.json').read_text(encoding='utf-8'))
        plan['stickers'] = plan['stickers'][:1]
        e = plan['stickers'][0];e['grid']=[2,1];e['order']=[0,1];e['durations_ms']=[200,400];e['caption_box']=[0,.8,1,1]
        sheet=Image.new('RGBA',(160,80));d=ImageDraw.Draw(sheet)
        d.rectangle((10,10,40,55),fill='red');d.rectangle((100,10,130,55),fill='blue')
        d.rectangle((0,64,79,79),fill='green');d.rectangle((80,64,159,79),fill='yellow')
        sheet.save(self.project/e['source']);studio.write(self.project/'plan.json',plan)

    def tearDown(self):self.tmp.cleanup()

    def test_real_decode_caption_and_private_exclusion(self):
        studio.build(self.project);studio.pack(self.project)
        with Image.open(self.project/'output/01.gif') as im:
            first=im.convert('RGBA');self.assertEqual(first.getpixel((230,5))[3],0)
            im.seek(1);second=im.convert('RGBA')
            self.assertEqual(first.crop((0,192,240,240)).tobytes(),second.crop((0,192,240,240)).tobytes())
            self.assertNotEqual(first.tobytes(),second.tobytes())
        with zipfile.ZipFile(self.project/'delivery.zip') as z:
            self.assertFalse(any('private' in n or 'sources' in n or 'plan.json' in n for n in z.namelist()))

    def test_reject_external_source(self):
        p=studio.load(self.project);p['stickers'][0]['source']='../photo.png';studio.write(self.project/'plan.json',p)
        with self.assertRaises(ValueError):studio.build(self.project)

    def test_reject_static_fake_animation(self):
        studio.build(self.project)
        Image.new('RGB',(240,240),'white').save(self.project/'output/01.gif',loop=0,duration=200)
        with self.assertRaises(ValueError):studio.check(self.project)

    def test_reject_bad_grid(self):
        Image.new('RGB',(161,80)).save(self.project/'sources/01.png')
        with self.assertRaises(ValueError):studio.build(self.project)

    def test_refuse_stale_export(self):
        studio.build(self.project)
        p=studio.load(self.project);p['stickers'][0]['caption']='Changed';studio.write(self.project/'plan.json',p)
        with self.assertRaises(ValueError):studio.pack(self.project)


if __name__ == '__main__':unittest.main()
