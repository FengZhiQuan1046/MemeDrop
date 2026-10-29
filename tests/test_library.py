import tempfile
import unittest
from pathlib import Path

from memedrop.library import Library, parse_tags


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lib = Library(self.root, include_builtins=False)
        (self.lib.media_dir / '開心.PNG').write_bytes(b'image')
        (self.lib.media_dir / '子目錄').mkdir()
        (self.lib.media_dir / '子目錄' / '貓.gif').write_bytes(b'gif')
        (self.lib.media_dir / 'video.mp4').write_bytes(b'video')
        (self.lib.media_dir / 'ignore.txt').write_text('ignored')
        self.lib.scan()

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def test_recursive_scan_and_types(self):
        self.assertEqual(len(self.lib.items()), 3)
        self.assertEqual(len(self.lib.items(kind='animation')), 1)
        self.assertEqual(len(self.lib.items(kind='video')), 1)

    def test_search_tags_and_filters_combine(self):
        meme = self.lib.items(kind='image')[0]
        self.lib.set_tags([meme.id], ['開心', '上班'])
        self.lib.set_favorite([meme.id], True)
        self.assertEqual([m.id for m in self.lib.items('開心 上班', '上班', 'image', 'favorites')], [meme.id])
        self.assertEqual(self.lib.items('不存在'), [])
        self.assertEqual(len(self.lib.items(collection='untagged')), 2)

    def test_metadata_survives_scan_and_restart(self):
        meme = self.lib.items()[0]
        self.lib.set_tags([meme.id], ['好笑'])
        self.lib.record_use(meme.id)
        self.lib.set_favorite([meme.id], True)
        self.lib.scan()
        self.lib.close()
        self.lib = Library(self.root, include_builtins=False)
        result = self.lib.items(collection='recent')[0]
        self.assertEqual(result.id, meme.id)
        self.assertEqual(result.tags, ('好笑',))
        self.assertEqual(result.uses, 1)
        self.assertTrue(result.favorite)

    def test_removed_and_restored_file_keeps_tags(self):
        meme = self.lib.items()[0]
        self.lib.set_tags([meme.id], ['保留'])
        path = self.lib.path(meme)
        data = path.read_bytes()
        path.unlink()
        self.lib.scan()
        self.assertEqual(self.lib.items(tag='保留'), [])
        self.assertEqual(self.lib.tag_counts(), [])
        path.write_bytes(data)
        self.lib.scan()
        self.assertEqual(self.lib.items(tag='保留')[0].id, meme.id)

    def test_batch_append_replace_and_rename_merge(self):
        ids = [m.id for m in self.lib.items()]
        self.lib.set_tags(ids, ['A'])
        self.lib.set_tags(ids, ['B'], append=True)
        self.lib.rename_tag('A', 'B')
        self.assertEqual(self.lib.tag_counts(), [('B', 3)])
        self.lib.set_tags(ids[:1], ['C'])
        self.assertEqual(dict(self.lib.tag_counts()), {'B': 2, 'C': 1})
        self.lib.delete_tag('B')
        self.assertEqual(self.lib.tag_counts(), [('C', 1)])

    def test_import_never_overwrites(self):
        outside = self.root / 'video.mp4'
        outside.write_bytes(b'new video')
        count, errors = self.lib.import_files([outside])
        self.assertEqual((count, errors), (1, []))
        self.assertEqual((self.lib.media_dir / 'video.mp4').read_bytes(), b'video')
        self.assertEqual((self.lib.media_dir / 'video (2).mp4').read_bytes(), b'new video')
        self.assertEqual(self.lib.import_files([self.lib.media_dir / 'video.mp4']), (0, []))

    def test_settings_and_parse_tags(self):
        self.assertEqual(parse_tags(' #貓咪，開心; 貓咪\n 上班 '), ['上班', '貓咪', '開心'])
        self.lib.set_setting('hotkey', 'K')
        self.assertEqual(self.lib.setting('hotkey', 'M'), 'K')

    def test_path_traversal_is_rejected(self):
        meme = self.lib.items()[0]
        meme.relative_path = '../secret.png'
        with self.assertRaises(ValueError):
            self.lib.path(meme)

    def test_sections_partition_media_text_builtins_and_each_series(self):
        self.lib.seed_kaomoji()
        custom = self.lib.save_kaomoji('(^own^)', '自己的', ['共同', '文字專用'])
        sid = self.lib.series_counts()[0][0]
        other_sid = self.lib.create_series('第二系列')
        video = self.lib.items(kind='video')[0]
        self.lib.set_series([video.id], other_sid)
        sections = ['my_memes', 'my_kaomoji', 'builtin_kaomoji', f'series:{sid}', f'series:{other_sid}']
        partitions = [[m.id for m in self.lib.items(section=s)] for s in sections]
        flattened = [mid for group in partitions for mid in group]
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(set(flattened), {m.id for m in self.lib.items()})
        self.assertEqual(partitions[1], [custom])
        self.assertEqual(len(partitions[2]), 240)
        for group in partitions:
            self.lib.set_tags(group, ['共同'])
        self.lib.set_tags(partitions[0], ['圖片專用'], append=True)
        self.lib.rename_tag('共同', '改名', f'series:{sid}')
        self.assertEqual(self.lib.tag_counts(f'series:{sid}'), [('改名', 1)])
        self.assertEqual(self.lib.tag_counts(f'series:{other_sid}'), [('共同', 1)])
        self.assertEqual(self.lib.tag_counts('my_kaomoji'), [('共同', 1)])
        self.assertEqual(self.lib.tag_counts('builtin_kaomoji'), [('共同', 240)])
        self.lib.delete_tag('共同', 'my_memes')
        self.assertEqual(self.lib.tag_counts('my_memes'), [('圖片專用', 1)])
        self.assertEqual(self.lib.tag_counts('my_kaomoji'), [('共同', 1)])
        self.lib.rename_tag('共同', '內建', 'builtin_kaomoji')
        self.assertEqual(self.lib.tag_counts('builtin_kaomoji'), [('內建', 240)])
        self.assertEqual(self.lib.tag_counts('my_kaomoji'), [('共同', 1)])

    def test_series_assignment_survives_scan_restart_and_restored_files(self):
        cat = self.lib.items(kind='animation')[0]
        sid = self.lib.create_series('手動系列')
        self.lib.set_tags([cat.id], ['保留'])
        self.lib.set_favorite([cat.id], True)
        self.lib.record_use(cat.id)
        self.lib.set_series([cat.id], sid)
        path = self.lib.path(cat)
        data = path.read_bytes()
        path.unlink()
        self.lib.scan()
        self.assertEqual(self.lib.tag_counts(f'series:{sid}'), [])
        self.lib.rename_tag('保留', '改名', f'series:{sid}')
        path.write_bytes(data)
        self.lib.scan()
        self.lib.close()
        self.lib = Library(self.root, include_builtins=False)
        result = self.lib.items(section=f'series:{sid}', collection='recent')[0]
        self.assertEqual((result.id, result.tags, result.uses, result.favorite), (cat.id, ('改名',), 1, True))
        self.lib.set_series([cat.id], None)
        self.lib.scan()
        self.assertIn(cat.id, [m.id for m in self.lib.items(section='my_memes')])
        self.assertEqual(self.lib.items(section=f'series:{sid}'), [])

    def test_import_into_series_and_validation(self):
        sid = self.lib.create_series('新系列')
        source = self.root / 'new.png'
        source.write_bytes(b'new')
        self.assertEqual(self.lib.import_files([source], series_id=sid), (1, []))
        result = self.lib.items(section=f'series:{sid}')
        self.assertEqual([m.name for m in result], ['new'])
        self.lib.scan()
        self.assertEqual(self.lib.items(section=f'series:{sid}')[0].id, result[0].id)
        for name in ('', ' ', 'x' * 81, '新系列'):
            with self.assertRaises(ValueError):
                self.lib.create_series(name)
        with self.assertRaises(ValueError):
            self.lib.import_files([source], series_id=99999)
        self.assertEqual(len(self.lib.items(section=f'series:{sid}')), 1)
        custom = self.lib.save_kaomoji('(^no-series^)', '文字', [])
        self.lib.set_series([custom], sid)
        self.assertEqual(self.lib.items(section='my_kaomoji')[0].series_id, None)


if __name__ == '__main__':
    unittest.main()
