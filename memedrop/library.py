from __future__ import annotations

import re
import os
import shutil
import sqlite3
import time
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .search import matches_search, search_key

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}
ANIMATION_EXTENSIONS = {'.gif'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.mkv', '.avi', '.m4v'}
EXTENSIONS = IMAGE_EXTENSIONS | ANIMATION_EXTENSIONS | VIDEO_EXTENSIONS


def media_kind(path: Path) -> str:
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        return 'video'
    if path.suffix.lower() in ANIMATION_EXTENSIONS:
        return 'animation'
    return 'image'


def parse_tags(value: str) -> list[str]:
    return sorted({x.strip().lstrip('#') for x in re.split(r'[,，;；\n]', value)
                   if x.strip().lstrip('#')}, key=str.casefold)


@dataclass
class Meme:
    id: int
    relative_path: str
    kind: str
    favorite: bool
    added: float
    last_used: float
    uses: int
    tags: tuple[str, ...]
    content: str = ''
    title: str = ''
    series_id: Optional[int] = None
    trashed_at: float = 0
    original_path: str = ''
    visible_tags: Optional[tuple[str, ...]] = None

    @property
    def display_tags(self):
        return self.tags if self.visible_tags is None else self.visible_tags

    @property
    def name(self) -> str:
        return self.title if self.kind == 'kaomoji' else Path(self.original_path or self.relative_path).stem


class Library:
    def __init__(self, root: Path, include_builtins: bool = True):
        self.root = root.resolve()
        self.media_dir = self.root / 'memes'
        self.data_dir = self.root / '.memedrop'
        self.trash_dir = self.data_dir / 'trash'
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.data_dir / 'library.sqlite3'))
        self.db.execute('PRAGMA foreign_keys = ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
                added REAL NOT NULL, last_used REAL NOT NULL DEFAULT 0,
                uses INTEGER NOT NULL DEFAULT 0, available INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS tags (
                media_id INTEGER REFERENCES media(id) ON DELETE CASCADE,
                name TEXT NOT NULL, PRIMARY KEY(media_id, name)
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS series (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS tag_edges (
                section TEXT NOT NULL, parent TEXT NOT NULL, child TEXT NOT NULL,
                PRIMARY KEY(section, parent, child));
        ''')
        # Additive migration preserves existing media, tags, favorites and history.
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(media)')}
        with self.db:
            for column in ('content', 'title'):
                if column not in columns:
                    self.db.execute(f"ALTER TABLE media ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            if 'series_id' not in columns:
                self.db.execute('ALTER TABLE media ADD COLUMN series_id INTEGER REFERENCES series(id)')
                # Existing subfolders become series without moving files or losing metadata.
                for mid, path in self.db.execute("SELECT id, path FROM media WHERE kind != 'kaomoji'").fetchall():
                    parts = Path(path).parts
                    if len(parts) > 1:
                        sid = self._folder_series(parts[0])
                        self.db.execute('UPDATE media SET series_id = ? WHERE id = ?', (sid, mid))
            if 'trashed_at' not in columns:
                self.db.execute('ALTER TABLE media ADD COLUMN trashed_at REAL NOT NULL DEFAULT 0')
            if 'original_path' not in columns:
                self.db.execute("ALTER TABLE media ADD COLUMN original_path TEXT NOT NULL DEFAULT ''")
        if include_builtins:
            self.seed_kaomoji()

    def seed_kaomoji(self):
        from .kaomoji import entries
        with self.db:
            for content, title, tags in entries():
                key = '@kaomoji/builtin/' + hashlib.sha256(content.encode('utf-8')).hexdigest()
                cursor = self.db.execute('''INSERT OR IGNORE INTO media(path, kind, added, content, title)
                    VALUES (?, 'kaomoji', 0, ?, ?)''', (key, content, title))
                if cursor.rowcount:
                    self.db.executemany('INSERT INTO tags VALUES (?, ?)',
                                        ((cursor.lastrowid, tag) for tag in dict.fromkeys(tags)))

    def save_kaomoji(self, content: str, title: str, tags: list[str], mid: Optional[int] = None) -> int:
        content = content.strip()
        if not content or len(content) > 500 or '\n' in content or '\r' in content:
            raise ValueError('請輸入 1～500 字的單行顏文字。')
        title = title.strip() or '我的顏文字'
        duplicate = self.db.execute("SELECT id FROM media WHERE kind = 'kaomoji' AND content = ? AND available = 1 AND id != ?",
                                    (content, mid or -1)).fetchone()
        if duplicate:
            raise ValueError('這個顏文字已存在，可搜尋它並加入收藏。')
        with self.db:
            if mid is None:
                cursor = self.db.execute('''INSERT INTO media(path, kind, added, content, title)
                    VALUES (?, 'kaomoji', ?, ?, ?)''', ('@kaomoji/custom/' + uuid.uuid4().hex, time.time(), content, title))
                mid = cursor.lastrowid
            else:
                cursor = self.db.execute("UPDATE media SET content = ?, title = ? WHERE id = ? AND kind = 'kaomoji' AND available = 1",
                                         (content, title, mid))
                if not cursor.rowcount:
                    raise ValueError('找不到這個顏文字，請重新整理。')
            self.db.execute('DELETE FROM tags WHERE media_id = ?', (mid,))
            self.db.executemany('INSERT OR IGNORE INTO tags VALUES (?, ?)', ((mid, tag) for tag in tags))
        return mid

    def remove_kaomoji(self, mid: int):
        meme = self._get_meme(mid)
        if meme.kind != 'kaomoji':
            raise ValueError('這個素材不是顏文字。')
        self._trash_one(meme)

    def scan(self) -> int:
        # Build the complete snapshot before changing availability in one transaction.
        found = []
        for path in self.media_dir.rglob('*'):
            if path.is_file() and path.suffix.lower() in EXTENSIONS:
                try:
                    path.resolve().relative_to(self.media_dir.resolve())
                except ValueError:
                    continue
                found.append((path.relative_to(self.media_dir).as_posix(), media_kind(path), time.time()))
        with self.db:
            self.db.execute("UPDATE media SET available = 0 WHERE kind != 'kaomoji' AND trashed_at = 0")
            for path, kind, added in found:
                existing = self.db.execute('SELECT id FROM media WHERE path = ?', (path,)).fetchone()
                parts = Path(path).parts
                sid = self._folder_series(parts[0]) if not existing and len(parts) > 1 else None
                self.db.execute('''INSERT INTO media(path, kind, added, series_id) VALUES(?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET available = 1, kind = excluded.kind WHERE media.trashed_at = 0''',
                    (path, kind, added, sid))
        return len(found)

    def _folder_series(self, name: str) -> int:
        self.db.execute('INSERT OR IGNORE INTO series(name) VALUES (?)', (name,))
        return self.db.execute('SELECT id FROM series WHERE name = ?', (name,)).fetchone()[0]

    def create_series(self, name: str) -> int:
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError('請輸入 1～80 字的系列名稱。')
        with self.db:
            try:
                return self.db.execute('INSERT INTO series(name) VALUES (?)', (name,)).lastrowid
            except sqlite3.IntegrityError:
                raise ValueError('這個系列名稱已存在。') from None

    def series_counts(self, query: str = '') -> list[tuple[int, str, int]]:
        rows = self.db.execute('''SELECT s.id, s.name, COUNT(m.id) FROM series s
            LEFT JOIN media m ON m.series_id = s.id AND m.available = 1 AND m.trashed_at = 0
            GROUP BY s.id ORDER BY s.name''').fetchall()
        return [row for row in rows if matches_search(row[1], query)] if query.split() else rows

    def rename_series(self, sid: int, name: str):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError('請輸入 1～80 字的系列名稱。')
        with self.db:
            try:
                cursor = self.db.execute('UPDATE series SET name = ? WHERE id = ?', (name, sid))
            except sqlite3.IntegrityError:
                raise ValueError('這個系列名稱已存在。') from None
            if not cursor.rowcount:
                raise ValueError('找不到這個系列，請重新整理。')

    def merge_series(self, source: int, target: int) -> int:
        if source == target:
            raise ValueError('請選擇另一個系列。')
        if self.db.execute('SELECT COUNT(*) FROM series WHERE id IN (?, ?)', (source, target)).fetchone()[0] != 2:
            raise ValueError('找不到來源或目標系列，請重新整理。')
        merged_edges = set(self.tag_edges(f'series:{source}')) | set(self.tag_edges(f'series:{target}'))
        self._ancestors_for(merged_edges)
        used = {Path(original or path).name.casefold() for path, original in self.db.execute(
            'SELECT path, original_path FROM media WHERE series_id = ?', (target,))}
        rows = self.db.execute('''SELECT id, path, available, trashed_at, original_path FROM media
            WHERE series_id = ? ORDER BY id''', (source,)).fetchall()
        moves = []
        try:
            with self.db:
                for mid, path, available, trashed, original in rows:
                    # Missing external files retain their path so a later scan can recover them.
                    if not available and not trashed:
                        continue
                    relative = Path(original or path)
                    filename = relative.name
                    index = 2
                    while (filename.casefold() in used or
                           (filename != relative.name and self._path_taken(relative.with_name(filename).as_posix(), mid)) or
                           (filename != relative.name and (self.media_dir / relative.with_name(filename)).exists())):
                        filename = f'{relative.stem} ({index}){relative.suffix}'
                        index += 1
                    used.add(filename.casefold())
                    if filename == relative.name:
                        continue
                    renamed = relative.with_name(filename).as_posix()
                    if trashed:
                        self.db.execute('UPDATE media SET original_path = ? WHERE id = ?', (renamed, mid))
                    else:
                        old = self.path(self._get_meme(mid))
                        new = old.with_name(filename)
                        self.db.execute('UPDATE media SET path = ? WHERE id = ?', (renamed, mid))
                        self._move_file(old, new)
                        moves.append((old, new))
                # Include unavailable and recycled items so restoring them follows the merge.
                cursor = self.db.execute('UPDATE media SET series_id = ? WHERE series_id = ?', (target, source))
                moved_count = cursor.rowcount
                self.db.executemany('INSERT OR IGNORE INTO tag_edges VALUES (?, ?, ?)',
                                    ((f'series:{target}', p, c) for p, c in merged_edges))
            return moved_count
        except Exception:
            for old, new in reversed(moves):
                self._move_file(new, old)
            raise

    def save_caption_series(self, frames, *, name: str = '', series_id: Optional[int] = None) -> tuple[int, int]:
        from .video_series import caption_stem, caption_text
        if not frames:
            raise ValueError('請至少選擇一張台詞截圖。')
        if series_id is None:
            name = name.strip()
            if not name or len(name) > 80:
                raise ValueError('請輸入 1～80 字的系列名稱。')
        elif not self.db.execute('SELECT 1 FROM series WHERE id = ?', (series_id,)).fetchone():
            raise ValueError('找不到這個系列，請重新整理。')
        created, folder = [], None
        try:
            with self.db:
                if series_id is None:
                    try:
                        series_id = self.db.execute('INSERT INTO series(name) VALUES (?)', (name,)).lastrowid
                    except sqlite3.IntegrityError:
                        raise ValueError('這個系列名稱已存在，請改名或加入既有系列。') from None
                folder = (self.media_dir / f'series-{series_id}').resolve()
                folder.relative_to(self.media_dir.resolve())
                folder.mkdir(exist_ok=True)
                for frame in frames:
                    text = caption_text(frame.text)
                    stem = caption_stem(text)
                    target = folder / (stem + '.png')
                    index = 2
                    while target.exists() or self._path_taken(target.relative_to(self.media_dir.resolve()).as_posix(), -1):
                        target = folder / f'{stem} ({index}).png'
                        index += 1
                    with frame.path.open('rb') as source, target.open('xb') as dest:
                        created.append(target)
                        shutil.copyfileobj(source, dest)
                    self.db.execute('''INSERT INTO media(path, kind, added, series_id, content)
                        VALUES (?, 'image', ?, ?, ?)''',
                        (target.relative_to(self.media_dir.resolve()).as_posix(), time.time(), series_id, text))
            return series_id, len(created)
        except Exception:
            for path in reversed(created):
                path.unlink()
            if folder is not None and folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
            raise

    def set_series(self, ids: list[int], series_id: Optional[int]):
        if series_id is not None and not self.db.execute('SELECT 1 FROM series WHERE id = ?', (series_id,)).fetchone():
            raise ValueError('找不到這個系列，請重新整理。')
        with self.db:
            self.db.executemany("UPDATE media SET series_id = ? WHERE id = ? AND kind != 'kaomoji' AND trashed_at = 0",
                                ((series_id, mid) for mid in ids))

    @staticmethod
    def section_clause(section: str) -> tuple[str, tuple]:
        # Used by both browsing and tag mutations so identical labels stay independent.
        if section == 'trash':
            return 'm.trashed_at > 0', ()
        if section == 'all':
            return 'm.trashed_at = 0', ()
        if section == 'my_memes':
            return "m.trashed_at = 0 AND m.kind != 'kaomoji' AND m.series_id IS NULL", ()
        if section == 'my_kaomoji':
            return "m.trashed_at = 0 AND m.kind = 'kaomoji' AND m.path NOT LIKE '@kaomoji/builtin/%'", ()
        if section == 'builtin_kaomoji':
            return "m.trashed_at = 0 AND m.kind = 'kaomoji' AND m.path LIKE '@kaomoji/builtin/%'", ()
        if section.startswith('series:'):
            return "m.trashed_at = 0 AND m.kind != 'kaomoji' AND m.series_id = ?", (int(section.split(':', 1)[1]),)
        raise ValueError('未知的素材區塊。')

    def path(self, meme: Meme) -> Path:
        if meme.kind == 'kaomoji':
            raise ValueError('顏文字是純文字，沒有素材檔案路徑。')
        base = self.trash_dir if meme.trashed_at else self.media_dir
        relative = Path(meme.relative_path).relative_to('@trash') if meme.trashed_at else meme.relative_path
        path = (base / relative).resolve()
        path.relative_to(base.resolve())
        if meme.trashed_at:
            base.resolve().relative_to(self.data_dir.resolve())
        return path

    def _get_meme(self, mid: int) -> Meme:
        row = self.db.execute('''SELECT id, path, kind, favorite, added, last_used, uses,
            content, title, series_id, trashed_at, original_path FROM media
            WHERE id = ? AND (available = 1 OR trashed_at > 0)''', (mid,)).fetchone()
        if row is None:
            raise ValueError('找不到這個素材，請重新整理。')
        tags = tuple(r[0] for r in self.db.execute('SELECT name FROM tags WHERE media_id = ? ORDER BY name', (mid,)))
        return Meme(*row[:7], tags, *row[7:])

    @staticmethod
    def _move_file(source: Path, target: Path):
        if os.name == 'nt':
            # Windows rename fails if another file already occupies the destination.
            source.rename(target)
            return
        # Exclusive creation provides the same no-overwrite guarantee on other platforms.
        created = False
        try:
            with source.open('rb') as src, target.open('xb') as dst:
                created = True
                shutil.copyfileobj(src, dst)
            shutil.copystat(source, target)
            source.unlink()
        except OSError:
            if created:
                target.unlink(missing_ok=True)
            raise

    def _relocate_file(self, meme: Meme, target: Path, path: str, trashed_at: float = 0,
                       original_path: str = ''):
        source = self.path(meme)
        moves = []
        try:
            with self.db:
                # Check database constraints before touching the file.
                self.db.execute('''UPDATE media SET path = ?, trashed_at = ?, original_path = ?,
                    available = ? WHERE id = ?''', (path, trashed_at, original_path, int(not trashed_at), meme.id))
                if target.exists() and source.samefile(target) and str(source) != str(target):
                    temporary = source.with_name(uuid.uuid4().hex + source.suffix)
                    self._move_file(source, temporary)
                    moves.append((source, temporary))
                    source = temporary
                self._move_file(source, target)
                moves.append((source, target))
        except Exception:
            # Compensate file moves when a later move or database commit fails.
            for old, new in reversed(moves):
                self._move_file(new, old)
            raise

    def _path_taken(self, path: str, exclude: int) -> bool:
        return self.db.execute('SELECT 1 FROM media WHERE path = ? COLLATE NOCASE AND id != ?', (path, exclude)).fetchone() is not None

    def rename_file(self, mid: int, filename: str):
        meme = self._get_meme(mid)
        if meme.kind == 'kaomoji' or meme.trashed_at:
            raise ValueError('請選取尚未移入回收站的表情包。')
        if (not filename or len(filename) > 255 or filename in ('.', '..')
                or filename.endswith((' ', '.')) or re.search(r'[<>:"/\\|?*\x00-\x1f]', filename)
                or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', filename, re.IGNORECASE)):
            raise ValueError('檔名無效，請勿使用路徑、特殊符號、保留名稱或結尾空白／句點。')
        source = self.path(meme)
        if Path(filename).suffix.lower() != source.suffix.lower():
            raise ValueError(f'請保留原本的 {source.suffix} 副檔名；重新命名不會轉換檔案格式。')
        if filename == source.name:
            return
        target = source.with_name(filename)
        relative = target.relative_to(self.media_dir.resolve()).as_posix()
        if self._path_taken(relative, mid) or (target.exists() and not source.samefile(target)):
            raise ValueError('這個檔名已存在，請使用其他名稱。')
        self._relocate_file(meme, target, relative)

    def _trash_one(self, meme: Meme):
        if meme.trashed_at:
            raise ValueError('這個素材已在回收站。')
        if meme.kind == 'kaomoji':
            with self.db:
                self.db.execute('UPDATE media SET trashed_at = ?, available = 0 WHERE id = ?', (time.time(), meme.id))
        else:
            self.trash_dir.mkdir(exist_ok=True)
            key = uuid.uuid4().hex + Path(meme.relative_path).suffix
            target_meme = Meme(meme.id, '@trash/' + key, meme.kind, meme.favorite, meme.added,
                               meme.last_used, meme.uses, meme.tags, trashed_at=time.time())
            target = self.path(target_meme)
            self._relocate_file(meme, target, target_meme.relative_path, target_meme.trashed_at, meme.relative_path)

    def _restore_one(self, meme: Meme):
        if not meme.trashed_at:
            raise ValueError('這個素材不在回收站。')
        if meme.kind == 'kaomoji':
            if self.db.execute("SELECT 1 FROM media WHERE kind = 'kaomoji' AND content = ? AND available = 1 AND id != ?", (meme.content, meme.id)).fetchone():
                raise ValueError('素材庫已有相同的顏文字，請先編輯或移除重複項目再還原。')
            with self.db:
                self.db.execute('UPDATE media SET trashed_at = 0, available = 1 WHERE id = ?', (meme.id,))
        else:
            target = (self.media_dir / meme.original_path).resolve()
            target.relative_to(self.media_dir.resolve())
            desired = target
            index = 2
            while target.exists() or self._path_taken(target.relative_to(self.media_dir.resolve()).as_posix(), meme.id):
                target = desired.with_name(f'{desired.stem} ({index}){desired.suffix}')
                index += 1
            target.parent.mkdir(parents=True, exist_ok=True)
            self._relocate_file(meme, target, target.relative_to(self.media_dir.resolve()).as_posix())

    def _delete_one(self, meme: Meme):
        if not meme.trashed_at:
            raise ValueError('永久刪除只適用於回收站內的素材。')
        with self.db:
            if meme.relative_path.startswith('@kaomoji/builtin/'):
                # Keep the seed key as a tombstone so deleted built-ins stay deleted.
                self.db.execute('''UPDATE media SET trashed_at = 0, available = 0, content = '', title = '',
                    favorite = 0, uses = 0, last_used = 0 WHERE id = ?''', (meme.id,))
                self.db.execute('DELETE FROM tags WHERE media_id = ?', (meme.id,))
            else:
                self.db.execute('DELETE FROM media WHERE id = ?', (meme.id,))
            if meme.kind != 'kaomoji':
                self.path(meme).unlink(missing_ok=True)

    def _batch_change(self, ids: list[int], operation) -> tuple[int, list[str]]:
        count, errors = 0, []
        for mid in dict.fromkeys(ids):
            label = f'素材 {mid}'
            try:
                meme = self._get_meme(mid)
                label = meme.name
                operation(meme)
                count += 1
            except (OSError, ValueError, sqlite3.Error) as exc:
                errors.append(f'{label}：{exc}')
        return count, errors

    def trash_items(self, ids: list[int]) -> tuple[int, list[str]]:
        return self._batch_change(ids, self._trash_one)

    def restore_items(self, ids: list[int]) -> tuple[int, list[str]]:
        return self._batch_change(ids, self._restore_one)

    def delete_items(self, ids: list[int]) -> tuple[int, list[str]]:
        return self._batch_change(ids, self._delete_one)

    def items(self, query: str = '', tag: Optional[str] = None, kind: str = 'all',
              collection: str = 'all', sort: str = 'newest', section: str = 'all') -> list[Meme]:
        from .kaomoji import ALIASES
        terms = [(word.casefold(), search_key(word)) for word in query.split()]
        graphs = {}
        aliases = {search_key(label): ' '.join(values) for label, values in ALIASES.items()} if terms else {}
        all_tags: dict[int, list[str]] = {}
        for mid, name in self.db.execute('SELECT media_id, name FROM tags ORDER BY name'):
            all_tags.setdefault(mid, []).append(name)
        clause, params = self.section_clause(section)
        rows = self.db.execute('''SELECT id, path, kind, favorite, added, last_used, uses, content, title, series_id,
            trashed_at, original_path FROM media m WHERE (available = 1 OR ? = 'trash') AND (''' + clause + ')', (section, *params))
        result = []
        for row in rows:
            meme = Meme(*row[:7], tuple(all_tags.get(row[0], [])), *row[7:])
            tag_section = self.tag_section(meme)
            if tag_section not in graphs:
                graphs[tag_section] = self.tag_ancestors(tag_section)
            ancestors = graphs[tag_section]
            effective = set(meme.tags)
            for label in meme.tags:
                effective.update(ancestors.get(label, set()))
            meme.visible_tags = tuple(label for label in meme.tags if not any(
                label in ancestors.get(other, set()) for other in meme.tags if other != label))
            if terms:
                haystack = meme.name + ' ' + meme.content + ' ' + (meme.original_path or meme.relative_path) + ' ' + ' '.join(effective)
                if meme.kind == 'kaomoji':
                    haystack += ' ' + ' '.join(aliases.get(search_key(label), '') for label in effective)
                original_haystack = haystack.casefold()
                normalized_haystack = search_key(haystack)
                # Preserve literal substring matches when phrase conversion differs from
                # converting a single character (for example, 乾 inside 乾坤).
                if not all(original in original_haystack or normalized in normalized_haystack
                           for original, normalized in terms):
                    continue
            if tag and tag not in effective:
                continue
            if kind != 'all' and meme.kind != kind:
                continue
            if collection == 'favorites' and not meme.favorite:
                continue
            if collection == 'recent' and not meme.last_used:
                continue
            if collection == 'untagged' and meme.tags:
                continue
            if collection == 'kaomoji' and meme.kind != 'kaomoji':
                continue
            result.append(meme)
        key = {'newest': lambda m: (-(m.trashed_at if section == 'trash' else m.added), m.name.casefold()),
               'name': lambda m: m.name.casefold(),
               'used': lambda m: (-m.uses, m.name.casefold()),
               'recent': lambda m: (-m.last_used, m.name.casefold())}
        return sorted(result, key=key['recent' if collection == 'recent' else sort])

    def tag_counts(self, section: str = 'all') -> list[tuple[str, int]]:
        counts = {}
        for parent, child in self.tag_edges(section):
            counts.setdefault(parent, 0)
            counts.setdefault(child, 0)
        graphs = {}
        for meme in self.items(section=section):
            scope = self.tag_section(meme)
            if scope not in graphs:
                graphs[scope] = self.tag_ancestors(scope)
            labels = set(meme.tags)
            for label in meme.tags:
                labels.update(graphs[scope].get(label, set()))
            for label in labels:
                counts[label] = counts.get(label, 0) + 1
        return sorted(counts.items())

    @staticmethod
    def tag_section(meme):
        if meme.kind == 'kaomoji':
            return 'builtin_kaomoji' if meme.relative_path.startswith('@kaomoji/builtin/') else 'my_kaomoji'
        return f'series:{meme.series_id}' if meme.series_id is not None else 'my_memes'

    def tag_edges(self, section):
        return self.db.execute('SELECT parent, child FROM tag_edges WHERE section = ? ORDER BY parent, child', (section,)).fetchall()

    @staticmethod
    def _ancestors_for(edges):
        parents = {}
        for parent, child in edges:
            parents.setdefault(child, set()).add(parent)
            parents.setdefault(parent, set())
        result, visiting = {}, set()

        def visit(label):
            if label in visiting:
                raise ValueError('父子標籤不能形成循環，也不能將標籤設為自己的父標籤。')
            if label not in result:
                visiting.add(label)
                found = set()
                for parent in parents[label]:
                    found.add(parent)
                    found.update(visit(parent))
                visiting.remove(label)
                result[label] = found
            return result[label]

        for label in parents:
            visit(label)
        return result

    def tag_ancestors(self, section):
        return self._ancestors_for(self.tag_edges(section))

    def set_tag_relations(self, tag, parents, children, section):
        self.section_clause(section)
        if section in ('all', 'trash'):
            raise ValueError('請在個別素材區塊管理標籤層級。')
        tag = tag.strip().lstrip('#')
        if not tag:
            raise ValueError('請輸入標籤名稱。')
        edges = {(parent, child) for parent, child in self.tag_edges(section) if tag not in (parent, child)}
        edges.update((parent, tag) for parent in parents)
        edges.update((tag, child) for child in children)
        self._ancestors_for(edges)
        with self.db:
            self.db.execute('DELETE FROM tag_edges WHERE section = ?', (section,))
            self.db.executemany('INSERT INTO tag_edges VALUES (?, ?, ?)', ((section, parent, child) for parent, child in edges))

    def set_tags(self, ids: list[int], tags: list[str], append: bool = False):
        with self.db:
            for mid in ids:
                if not self.db.execute('SELECT 1 FROM media WHERE id = ? AND trashed_at = 0', (mid,)).fetchone():
                    continue
                if not append:
                    self.db.execute('DELETE FROM tags WHERE media_id = ?', (mid,))
                self.db.executemany('INSERT OR IGNORE INTO tags VALUES (?, ?)', ((mid, t) for t in tags))

    def rename_tag(self, old: str, new: str, section: str = 'all'):
        new = new.strip().lstrip('#')
        if not new or new == old:
            return
        clause, params = self.section_clause(section)
        scope = 'SELECT id FROM media m WHERE ' + clause
        scopes = [row[0] for row in self.db.execute('SELECT DISTINCT section FROM tag_edges')] if section == 'all' else [section]
        updated = {}
        for scope_name in scopes:
            edges = {(new if parent == old else parent, new if child == old else child)
                     for parent, child in self.tag_edges(scope_name)}
            self._ancestors_for(edges)
            updated[scope_name] = edges
        with self.db:
            for scope_name, edges in updated.items():
                self.db.execute('DELETE FROM tag_edges WHERE section = ?', (scope_name,))
                self.db.executemany('INSERT INTO tag_edges VALUES (?, ?, ?)', ((scope_name, p, c) for p, c in edges))
            self.db.execute('INSERT OR IGNORE INTO tags SELECT media_id, ? FROM tags WHERE name = ? AND media_id IN (' + scope + ')', (new, old, *params))
            self.db.execute('DELETE FROM tags WHERE name = ? AND media_id IN (' + scope + ')', (old, *params))

    def delete_tag(self, tag: str, section: str = 'all'):
        clause, params = self.section_clause(section)
        with self.db:
            if section == 'all':
                self.db.execute('DELETE FROM tag_edges WHERE parent = ? OR child = ?', (tag, tag))
            else:
                self.db.execute('DELETE FROM tag_edges WHERE section = ? AND (parent = ? OR child = ?)', (section, tag, tag))
            self.db.execute('DELETE FROM tags WHERE name = ? AND media_id IN (SELECT id FROM media m WHERE ' + clause + ')', (tag, *params))

    def set_favorite(self, ids: list[int], value: bool):
        with self.db:
            self.db.executemany('UPDATE media SET favorite = ? WHERE id = ? AND trashed_at = 0', ((int(value), mid) for mid in ids))

    def record_use(self, mid: int):
        with self.db:
            self.db.execute('UPDATE media SET uses = uses + 1, last_used = ? WHERE id = ? AND trashed_at = 0', (time.time(), mid))

    def setting(self, key: str, default: str) -> str:
        row = self.db.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, value))

    def import_files(self, paths: list[Path], series_id: Optional[int] = None,
                     recognized_text: Optional[dict] = None) -> tuple[int, list[str]]:
        self.set_series([], series_id)  # Validate the destination before copying anything.
        if recognized_text is None:
            from .import_text import recognize_import_text
            recognized_text = recognize_import_text(paths)
        from .video_series import caption_stem
        count, errors = 0, []
        imported = []
        for source in paths:
            if not source.is_file() or source.suffix.lower() not in EXTENSIONS:
                errors.append(source.name + '：不支援的檔案')
                continue
            try:
                source.resolve().relative_to(self.media_dir.resolve())
                continue
            except ValueError:
                pass
            text = recognized_text.get(source, '')
            stem = caption_stem(text) if text.strip() else source.stem
            target = self.media_dir / (stem + source.suffix)
            index = 2
            while target.exists() or self._path_taken(target.relative_to(self.media_dir).as_posix(), -1):
                target = self.media_dir / f'{stem} ({index}){source.suffix}'
                index += 1
            try:
                # Exclusive creation prevents silently overwriting a concurrent import.
                with source.open('rb') as src, target.open('xb') as dst:
                    try:
                        shutil.copyfileobj(src, dst)
                    except OSError:
                        dst.close()
                        target.unlink(missing_ok=True)
                        raise
                count += 1
                imported.append((target.relative_to(self.media_dir).as_posix(), text))
            except OSError as exc:
                errors.append(f'{source.name}：{exc}')
        self.scan()
        with self.db:
            for path, text in imported:
                self.db.execute('UPDATE media SET series_id = ?, content = ? WHERE path = ?', (series_id, text, path))
        return count, errors

    def close(self):
        self.db.close()

