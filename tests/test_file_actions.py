import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memedrop.library import Library


class FileActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lib = Library(self.root, include_builtins=False)
        folder = self.lib.media_dir / '原系列'
        folder.mkdir()
        (folder / '表情.png').write_bytes(b'original image')
        (self.lib.media_dir / 'other.gif').write_bytes(b'original gif')
        self.lib.scan()
        self.meme = self.lib.items(kind='image')[0]
        self.lib.set_tags([self.meme.id], ['保留'])
        self.lib.set_favorite([self.meme.id], True)
        self.lib.record_use(self.meme.id)

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def restart(self):
        self.lib.close()
        self.lib = Library(self.root, include_builtins=False)
        self.lib.scan()

    def assert_metadata(self, meme):
        self.assertEqual((meme.id, meme.tags, meme.favorite, meme.uses, meme.series_id, meme.added),
                         (self.meme.id, ('保留',), True, 1, self.meme.series_id, self.meme.added))

    def test_rename_changes_real_filename_and_preserves_metadata_after_restart(self):
        original = self.lib.path(self.meme)
        self.lib.rename_file(self.meme.id, '新名字.png')
        self.assertFalse(original.exists())
        self.assertEqual(original.with_name('新名字.png').read_bytes(), b'original image')
        self.restart()
        renamed = self.lib.items('新名字')[0]
        self.assert_metadata(renamed)
        self.assertEqual(renamed.relative_path, '原系列/新名字.png')
        self.assertEqual(self.lib.items('表情'), [])
        self.lib.rename_file(renamed.id, '新名字.png')  # Unchanged name is harmless.

    def test_rename_rejects_unsafe_names_format_changes_and_collisions(self):
        for name in ('', '../escape.png', 'sub/name.png', 'sub\\name.png', 'CON.png',
                     'COM1.png', 'LPT².png', 'bad?.png', 'bad\x00.png', 'name.png ', 'name.', 'name.gif'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.lib.rename_file(self.meme.id, name)
        occupied = self.lib.path(self.meme).with_name('occupied.png')
        occupied.write_bytes(b'keep this')
        with self.assertRaises(ValueError):
            self.lib.rename_file(self.meme.id, occupied.name)
        self.assertEqual(occupied.read_bytes(), b'keep this')
        self.assertEqual(self.lib.path(self.meme).read_bytes(), b'original image')

    def test_case_only_rename_and_missing_source(self):
        self.lib.rename_file(self.meme.id, '表情.PNG')
        result = self.lib.items(kind='image')[0]
        self.assertEqual(result.relative_path, '原系列/表情.PNG')
        self.lib.path(result).unlink()
        with self.assertRaises(OSError):
            self.lib.rename_file(result.id, 'missing.PNG')
        self.assertEqual(self.lib.items(kind='image')[0].relative_path, result.relative_path)

    def test_trash_scan_restart_and_restore_preserve_files_and_all_metadata(self):
        original = self.lib.path(self.meme)
        self.assertEqual(self.lib.trash_items([self.meme.id]), (1, []))
        self.assertFalse(original.exists())
        self.restart()
        self.assertEqual(self.lib.items(kind='image'), [])
        self.assertEqual(self.lib.tag_counts(), [])
        self.assertEqual(self.lib.series_counts()[0][2], 0)
        trashed = self.lib.items(section='trash')[0]
        self.assert_metadata(trashed)
        self.assertEqual(trashed.name, '表情')
        self.assertEqual(trashed.original_path, '原系列/表情.png')
        self.assertEqual(self.lib.path(trashed).read_bytes(), b'original image')
        self.lib.rename_tag('保留', '別區塊')
        self.lib.delete_tag('保留')
        self.lib.set_tags([trashed.id], ['不能修改'])
        self.lib.set_favorite([trashed.id], False)
        self.lib.record_use(trashed.id)
        self.assertEqual(self.lib.restore_items([trashed.id]), (1, []))
        self.restart()
        restored = self.lib.items(kind='image')[0]
        self.assert_metadata(restored)
        self.assertEqual(original.read_bytes(), b'original image')
        self.assertEqual(self.lib.items(section='trash'), [])

    def test_restore_keeps_both_files_when_original_name_is_reused(self):
        original = self.lib.path(self.meme)
        self.lib.trash_items([self.meme.id])
        original.write_bytes(b'new image at original path')
        self.lib.scan()
        newer = self.lib.items(kind='image')[0]
        self.assertNotEqual(newer.id, self.meme.id)
        self.assertEqual(self.lib.restore_items([self.meme.id]), (1, []))
        self.restart()
        restored = self.lib.items('表情 (2)')[0]
        self.assert_metadata(restored)
        self.assertEqual(self.lib.path(restored).read_bytes(), b'original image')
        self.assertEqual(original.read_bytes(), b'new image at original path')

    def test_move_failure_rolls_back_database_and_retains_source(self):
        with patch.object(self.lib, '_move_file', side_effect=OSError('file locked')):
            with self.assertRaises(OSError):
                self.lib.rename_file(self.meme.id, '失敗.png')
            count, errors = self.lib.trash_items([self.meme.id])
        self.assertEqual(count, 0)
        self.assertIn('file locked', errors[0])
        self.assertEqual(self.lib.path(self.meme).read_bytes(), b'original image')
        self.assert_metadata(self.lib.items(kind='image')[0])
        self.assertEqual(self.lib.items(section='trash'), [])
        self.lib.trash_items([self.meme.id])
        with patch.object(self.lib, '_move_file', side_effect=OSError('restore blocked')):
            self.assertEqual(self.lib.restore_items([self.meme.id])[0], 0)
        self.assertEqual(self.lib.path(self.lib.items(section='trash')[0]).read_bytes(), b'original image')

    def test_database_constraint_failure_does_not_move_file(self):
        self.lib.db.executescript("""CREATE TRIGGER block_rename BEFORE UPDATE OF path ON media
            BEGIN SELECT RAISE(ABORT, 'blocked'); END;""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.lib.rename_file(self.meme.id, 'blocked.png')
        self.assertTrue(self.lib.path(self.meme).is_file())
        self.assertFalse(self.lib.path(self.meme).with_name('blocked.png').exists())

    def test_permanent_delete_only_affects_trash_and_removes_its_tags(self):
        self.assertEqual(self.lib.delete_items([self.meme.id])[0], 0)
        self.lib.trash_items([self.meme.id])
        stored = self.lib.path(self.lib.items(section='trash')[0])
        self.lib.db.executescript("""CREATE TRIGGER block_purge BEFORE DELETE ON media
            BEGIN SELECT RAISE(ABORT, 'blocked'); END;""")
        self.assertEqual(self.lib.delete_items([self.meme.id])[0], 0)
        self.assertTrue(stored.is_file())
        self.lib.db.execute('DROP TRIGGER block_purge')
        self.assertEqual(self.lib.delete_items([self.meme.id]), (1, []))
        self.assertFalse(stored.exists())
        self.assertEqual(self.lib.db.execute('SELECT * FROM tags WHERE media_id = ?', (self.meme.id,)).fetchall(), [])
        self.restart()
        self.assertEqual(self.lib.items(section='trash'), [])
        self.assertEqual(len(self.lib.items()), 1)
        self.assertTrue((self.lib.media_dir / 'other.gif').is_file())

    def test_batch_deduplicates_and_reports_partial_errors(self):
        other = self.lib.items(kind='animation')[0]
        self.lib.path(other).unlink()
        count, errors = self.lib.trash_items([self.meme.id, self.meme.id, other.id])
        self.assertEqual((count, len(errors)), (1, 1))
        self.assertEqual(len(self.lib.items(section='trash')), 1)
        self.assertEqual(self.lib.restore_items([self.meme.id, self.meme.id]), (1, []))

    def test_restore_and_delete_reject_paths_outside_managed_folders(self):
        self.lib.trash_items([self.meme.id])
        outside = self.root / 'outside.png'
        outside.write_bytes(b'keep')
        with self.lib.db:
            self.lib.db.execute("UPDATE media SET original_path = '../outside.png' WHERE id = ?", (self.meme.id,))
        self.assertEqual(self.lib.restore_items([self.meme.id])[0], 0)
        with self.lib.db:
            self.lib.db.execute("UPDATE media SET path = '@trash/../../../outside.png' WHERE id = ?", (self.meme.id,))
        self.assertEqual(self.lib.delete_items([self.meme.id])[0], 0)
        self.assertEqual(outside.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
