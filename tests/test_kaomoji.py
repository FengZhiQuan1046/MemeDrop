import sqlite3
import tempfile
import unittest
from pathlib import Path

from memedrop.kaomoji import entries, GROUPS
from memedrop.library import Library


class KaomojiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lib = Library(self.root)

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def test_catalog_is_unique_and_available_without_media(self):
        catalog = list(entries())
        self.assertEqual(len(GROUPS), 16)
        self.assertEqual(len(catalog), 240)
        self.assertEqual(len({text for text, _, _ in catalog}), 240)
        self.lib.scan()
        self.assertEqual(len(self.lib.items(collection='kaomoji')), 240)
        self.assertEqual(self.lib.items(kind='image'), [])

    def test_simplified_traditional_and_english_search(self):
        expected = [m.id for m in self.lib.items('開心')]
        self.assertEqual(len(expected), 15)
        self.assertEqual([m.id for m in self.lib.items('开心')], expected)
        self.assertEqual([m.id for m in self.lib.items('happy')], expected)
        self.assertEqual(len(self.lib.items(tag='動物')), 15)

    def test_seed_preserves_user_edits_favorites_history_and_deleted_items(self):
        first, removed = self.lib.items()[:2]
        self.lib.save_kaomoji('(^edited^)', '自己改過', ['我的'], first.id)
        self.lib.set_favorite([first.id], True)
        self.lib.record_use(first.id)
        self.lib.remove_kaomoji(removed.id)
        self.lib.close()
        self.lib = Library(self.root)
        self.lib.scan()
        self.assertEqual(len(self.lib.items()), 239)
        found = self.lib.items('自己改過')[0]
        self.assertEqual(found.content, '(^edited^)')
        self.assertEqual(found.tags, ('我的',))
        self.assertTrue(found.favorite)
        self.assertEqual(found.uses, 1)
        self.assertNotIn(removed.id, [m.id for m in self.lib.items()])

    def test_add_edit_remove_and_duplicate_validation(self):
        mid = self.lib.save_kaomoji('  (^custom^)  ', '自訂', ['自己的'])
        self.assertEqual(self.lib.items('自訂')[0].content, '(^custom^)')
        with self.assertRaises(ValueError):
            self.lib.save_kaomoji('(^custom^)', '重複', [])
        for text in ('', 'x' * 501, 'a\nb'):
            with self.assertRaises(ValueError):
                self.lib.save_kaomoji(text, '', [])
        self.lib.save_kaomoji('(^updated^)', '已更新', ['快樂'], mid)
        self.assertEqual(self.lib.items('已更新')[0].id, mid)
        with self.assertRaises(ValueError):
            self.lib.path(self.lib.items('已更新')[0])
        self.lib.remove_kaomoji(mid)
        self.assertEqual(self.lib.items('已更新'), [])

    def test_recycle_text_restore_duplicates_and_builtin_permanent_deletion(self):
        builtin = self.lib.items()[0]
        self.lib.set_favorite([builtin.id], True)
        self.lib.record_use(builtin.id)
        custom = self.lib.save_kaomoji('(^recycle_text^)', '自己的', ['私人'])
        self.assertEqual(self.lib.trash_items([builtin.id, custom]), (2, []))
        self.lib.seed_kaomoji()
        self.assertEqual(len(self.lib.items(section='trash')), 2)
        self.assertEqual(len(self.lib.items(section='builtin_kaomoji')), 239)
        self.lib.save_kaomoji('(^recycle_text^)', '另一個', [])
        self.assertEqual(self.lib.restore_items([custom])[0], 0)
        self.assertEqual(self.lib.restore_items([builtin.id]), (1, []))
        restored = next(m for m in self.lib.items() if m.id == builtin.id)
        self.assertEqual((restored.favorite, restored.uses), (True, 1))
        self.lib.trash_items([builtin.id])
        self.assertEqual(self.lib.delete_items([builtin.id, custom]), (2, []))
        self.assertEqual(self.lib.db.execute('SELECT content, title FROM media WHERE id = ?', (builtin.id,)).fetchone(), ('', ''))
        self.assertEqual(self.lib.db.execute('SELECT * FROM tags WHERE media_id = ?', (builtin.id,)).fetchall(), [])
        self.lib.close()
        self.lib = Library(self.root)
        self.assertNotIn(builtin.id, [m.id for m in self.lib.items()])
        self.assertEqual(self.lib.items(section='trash'), [])

    def test_media_scan_and_text_never_overwrite_each_other(self):
        (self.lib.media_dir / 'photo.png').write_bytes(b'image')
        self.lib.scan()
        picture = self.lib.items(kind='image')[0]
        self.lib.set_tags([picture.id], ['自己的圖片'])
        self.lib.scan()
        self.assertEqual(len(self.lib.items()), 241)
        self.assertEqual(self.lib.items(kind='image')[0].tags, ('自己的圖片',))
        self.assertEqual(self.lib.items()[0].id, picture.id)

    def test_legacy_database_migration_preserves_existing_records(self):
        legacy_root = self.root / 'legacy'
        data_dir = legacy_root / '.memedrop'
        data_dir.mkdir(parents=True)
        db = sqlite3.connect(str(data_dir / 'library.sqlite3'))
        db.executescript('''
            CREATE TABLE media (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
                added REAL NOT NULL, last_used REAL NOT NULL DEFAULT 0,
                uses INTEGER NOT NULL DEFAULT 0, available INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE tags (media_id INTEGER REFERENCES media(id), name TEXT NOT NULL,
                PRIMARY KEY(media_id, name));
            INSERT INTO media VALUES (1, '舊系列/old.png', 'image', 1, 123, 456, 7, 1);
            INSERT INTO tags VALUES (1, '舊標籤');
        ''')
        db.close()
        migrated = Library(legacy_root)
        try:
            old = migrated.items(kind='image')[0]
            self.assertEqual((old.id, old.uses, old.favorite, old.tags), (1, 7, True, ('舊標籤',)))
            self.assertEqual(len(migrated.items(kind='kaomoji')), 240)
            self.assertEqual(migrated.series_counts(), [(old.series_id, '舊系列', 1)])
            self.assertEqual(migrated.tag_counts(f'series:{old.series_id}'), [('舊標籤', 1)])
            self.assertEqual(migrated.items(section='my_memes'), [])
        finally:
            migrated.close()


if __name__ == '__main__':
    unittest.main()
