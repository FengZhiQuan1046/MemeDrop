import tempfile
import unittest
from pathlib import Path

from memedrop.library import Library


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lib = Library(self.root, include_builtins=False)
        (self.lib.media_dir / '快樂貓咪Happy.png').write_bytes(b'image')
        folder = self.lib.media_dir / '工作日志'
        folder.mkdir()
        (folder / '开心Dog.gif').write_bytes(b'gif')
        self.lib.scan()
        self.picture = self.lib.items(kind='image')[0]
        self.animation = self.lib.items(kind='animation')[0]
        self.lib.set_tags([self.picture.id], ['辦公', 'THANKS'])
        self.lib.set_tags([self.animation.id], ['感谢', 'Work'])
        self.text = self.lib.save_kaomoji('(可愛MiXeD)', '专属文字CUSTOM', ['歡迎', '情绪Smile'])

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def ids(self, query, **filters):
        return {m.id for m in self.lib.items(query, **filters)}

    def test_file_names_match_mixed_case_and_both_chinese_scripts(self):
        for query in ('快樂貓咪Happy', '快乐猫咪hAPPY', '快樂猫咪HAPPY', 'hApPy.PNG'):
            with self.subTest(query=query):
                self.assertEqual(self.ids(query), {self.picture.id})
        for query in ('開心dOG', '开心DOG', '開心Dog.GIF'):
            with self.subTest(query=query):
                self.assertEqual(self.ids(query), {self.animation.id})

    def test_paths_and_tags_match_in_both_directions(self):
        self.assertEqual(self.ids('工作日誌'), {self.animation.id})
        self.assertEqual(self.ids('工作日志'), {self.animation.id})
        self.assertEqual(self.ids('办公 thanks'), {self.picture.id})
        self.assertEqual(self.ids('感謝 wORK'), {self.animation.id})

    def test_custom_kaomoji_title_content_and_tags_share_matching_rules(self):
        for query in ('專屬文字custom', '专属文字CuStOm', '可爱mixed', '欢迎 情緒sMILE'):
            with self.subTest(query=query):
                self.assertEqual(self.ids(query, section='my_kaomoji'), {self.text})

    def test_builtin_aliases_work_with_simplified_custom_tags(self):
        self.lib.seed_kaomoji()
        expected = {m.id for m in self.lib.items(tag='開心', section='builtin_kaomoji')}
        for query in ('開心', '开心', 'Happy', 'HAPPY'):
            with self.subTest(query=query):
                self.assertTrue(expected.issubset(m.id for m in self.lib.items(query, section='builtin_kaomoji')))
        self.lib.set_tags([self.text], ['开心'])
        self.assertEqual(self.ids('HAPPY', section='my_kaomoji'), {self.text})

    def test_combined_words_and_other_filters_still_apply(self):
        self.lib.set_favorite([self.picture.id, self.animation.id], True)
        self.lib.record_use(self.picture.id)
        self.assertEqual(self.ids('快乐 THANKS', section='my_memes', collection='favorites', kind='image', tag='辦公'), {self.picture.id})
        self.assertEqual(self.ids('快乐 THANKS', collection='recent'), {self.picture.id})
        self.assertEqual(self.ids('快乐 WORK'), set())
        self.assertEqual(self.ids('happy', section=f'series:{self.animation.series_id}'), set())
        self.assertEqual(self.ids('開心DOG', kind='image'), set())

    def test_recycle_bin_search_uses_original_names_paths_and_tags(self):
        self.lib.trash_items([self.picture.id, self.animation.id, self.text])
        self.lib.scan()
        self.assertEqual(self.ids('快乐猫咪HAPPY THANKS', section='trash'), {self.picture.id})
        self.assertEqual(self.ids('工作日誌 感謝 dOG', section='trash'), {self.animation.id})
        self.assertEqual(self.ids('專屬文字custom 可爱MIXED', section='trash'), {self.text})
        self.assertEqual(self.ids('HAPPY'), set())

    def test_search_keeps_original_spelling_content_and_tag_identity(self):
        before = self.lib.items(sort='name')
        for query in ('快樂 貓咪', '快乐 猫咪', 'WORK', '專屬文字CUSTOM', '可爱mixed'):
            self.lib.items(query)
        self.assertEqual(self.lib.items(sort='name'), before)
        self.assertTrue((self.lib.media_dir / '快樂貓咪Happy.png').is_file())
        self.assertEqual(self.lib.items(section='my_kaomoji')[0].content, '(可愛MiXeD)')
        self.assertEqual(self.lib.items(section='my_kaomoji')[0].tags, ('情绪Smile', '歡迎'))

    def test_empty_and_whitespace_queries_match_the_whole_section(self):
        self.assertEqual(self.ids('  \t\n'), self.ids(''))
        self.assertEqual(self.ids('   ', section='my_memes'), {self.picture.id})
        self.assertEqual(self.ids('不存在'), set())

    def test_phrase_conversion_keeps_literal_partial_matches(self):
        (self.lib.media_dir / '乾坤.png').write_bytes(b'image')
        self.lib.scan()
        mid = self.lib.items('乾坤')[0].id
        for query in ('乾', '乾坤'):
            with self.subTest(query=query):
                self.assertEqual(self.ids(query), {mid})


if __name__ == '__main__':
    unittest.main()
