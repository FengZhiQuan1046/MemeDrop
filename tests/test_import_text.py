import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from memedrop.library import Library
from memedrop.video_series import render_subtitle


class ImportTextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lib = Library(self.root)

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def test_real_ocr_names_images_and_keeps_blank_original_and_source_bytes(self):
        frame = render_subtitle(np.full((360, 640, 3), 45, dtype=np.uint8), '今天也要加油')
        first = self.root / 'random.png'
        second = self.root / 'another.png'
        blank = self.root / '沒有文字.png'
        for path in (first, second):
            path.write_bytes(cv2.imencode('.png', frame)[1].tobytes())
        Image.new('RGB', (100, 100), 'white').save(blank)
        original = first.read_bytes()
        self.assertEqual(self.lib.import_files([first, second, blank]), (3, []))
        self.assertEqual({m.name for m in self.lib.items(kind='image')}, {'今天也要加油', '今天也要加油 (2)', '沒有文字'})
        self.assertEqual(len(self.lib.items('今天也要加油', kind='image')), 2)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual((self.lib.media_dir / '今天也要加油.png').read_bytes(), original)

    def test_animation_samples_later_frame_and_preserves_original_gif(self):
        from memedrop.import_text import recognize_import_text
        path = self.root / 'animation.gif'
        Image.new('RGB', (80, 60), 'white').save(path, save_all=True,
            append_images=[Image.fromarray(np.tile(np.arange(80, dtype=np.uint8)[None, :, None], (60, 1, 3)))], duration=100, loop=0)
        original = path.read_bytes()
        with patch('memedrop.video_series.SubtitleOCR') as engine:
            engine.return_value.return_value = ('動畫中的文字?', .99)
            texts = recognize_import_text([path])
        sid = self.lib.create_series('動圖集合')
        self.assertEqual(self.lib.import_files([path], sid, recognized_text=texts), (1, []))
        result = self.lib.items(section=f'series:{sid}')[0]
        self.assertEqual(result.name, '動畫中的文字？')
        self.assertEqual(self.lib.path(result).read_bytes(), original)
        self.assertEqual(result.content, '動畫中的文字?')

    def test_recognition_failure_falls_back_to_original_name(self):
        path = self.root / '保留原名.png'
        Image.fromarray(np.tile(np.arange(80, dtype=np.uint8)[None, :, None], (60, 1, 3))).save(path)
        with patch('memedrop.video_series.SubtitleOCR', side_effect=RuntimeError('unavailable')), \
             self.assertLogs(level='ERROR'):
            self.assertEqual(self.lib.import_files([path]), (1, []))
        self.assertEqual(self.lib.items(kind='image')[0].name, '保留原名')


if __name__ == '__main__':
    unittest.main()
