import tempfile
import unittest
from pathlib import Path

from memedrop.library import Library


class TagHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lib = Library(self.root, include_builtins=False)
        for name in ('a.png', 'b.png'):
            (self.lib.media_dir / name).write_bytes(b'image')
        self.lib.scan()
        self.ids = [m.id for m in self.lib.items()]
        self.scope = 'my_memes'

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def relation(self, tag, parents=(), children=()):
        self.lib.set_tag_relations(tag, parents, children, self.scope)

    def test_multiple_parents_children_leaf_display_and_inherited_filter(self):
        self.relation('動物', children=['貓', '狗'])
        self.relation('可愛', children=['貓', '狗'])
        self.relation('貓', parents=['動物', '可愛'], children=['橘貓'])
        self.lib.set_tags(self.ids[:1], ['動物', '可愛', '貓', '橘貓', '狗'])
        meme = self.lib.items(tag='動物', section=self.scope)[0]
        self.assertEqual(set(meme.display_tags), {'橘貓', '狗'})
        self.assertEqual(set(meme.tags), {'動物', '可愛', '貓', '橘貓', '狗'})
        self.assertEqual(dict(self.lib.tag_counts(self.scope)), {'動物': 1, '可愛': 1, '狗': 1, '貓': 1, '橘貓': 1})
        self.assertEqual(len(self.lib.items(collection='untagged', section=self.scope)), 1)
        self.lib.set_tags(self.ids[:1], ['橘貓'])
        self.assertEqual(len(self.lib.items(tag='動物', section=self.scope)), 1)
        self.assertEqual(len(self.lib.items('动物', section=self.scope)), 1)

    def test_cycles_rejected_atomically_and_relations_persist(self):
        self.relation('A', children=['B'])
        self.relation('B', parents=['A'], children=['C'])
        before = self.lib.tag_edges(self.scope)
        for name, parents in [('A', ['C']), ('C', ['C'])]:
            with self.assertRaises(ValueError):
                self.relation(name, parents=parents, children=['B'] if name == 'A' else [])
            self.assertEqual(self.lib.tag_edges(self.scope), before)
        self.lib.close()
        self.lib = Library(self.root, include_builtins=False)
        self.assertEqual(self.lib.tag_ancestors(self.scope)['C'], {'A', 'B'})

    def test_scoping_rename_delete_and_cycle_merge_guard(self):
        self.relation('A', children=['B'])
        self.lib.set_tag_relations('B', [], ['A'], 'my_kaomoji')
        self.lib.set_tags(self.ids, ['B'])
        self.lib.rename_tag('A', 'Root', self.scope)
        self.assertEqual(self.lib.tag_edges(self.scope), [('Root', 'B')])
        self.assertEqual(self.lib.tag_edges('my_kaomoji'), [('B', 'A')])
        with self.assertRaises(ValueError):
            self.lib.rename_tag('Root', 'B', self.scope)
        self.lib.delete_tag('Root', self.scope)
        self.assertEqual(self.lib.tag_edges(self.scope), [])
        self.assertTrue(all(m.display_tags == ('B',) for m in self.lib.items()))

    def test_series_merge_transfers_graph_and_rejects_conflicting_cycles(self):
        source = self.lib.create_series('來源')
        target = self.lib.create_series('目標')
        self.lib.set_series(self.ids, source)
        self.lib.set_tags(self.ids, ['Leaf'])
        self.lib.set_tag_relations('Root', [], ['Leaf'], f'series:{source}')
        self.lib.set_tag_relations('Leaf', [], ['Root'], f'series:{target}')
        with self.assertRaises(ValueError):
            self.lib.merge_series(source, target)
        self.assertEqual(len(self.lib.items(section=f'series:{source}')), 2)
        self.lib.set_tag_relations('Leaf', [], [], f'series:{target}')
        self.lib.merge_series(source, target)
        self.assertEqual(len(self.lib.items(tag='Root', section=f'series:{target}')), 2)
