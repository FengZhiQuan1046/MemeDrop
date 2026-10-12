from __future__ import annotations

import re
import shutil
import sqlite3
import time
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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

    @property
    def name(self) -> str:
        return self.title if self.kind == 'kaomoji' else Path(self.relative_path).stem


class Library:
    def __init__(self, root: Path, include_builtins: bool = True):
        self.root = root.resolve()
        self.media_dir = self.root / 'memes'
        self.data_dir = self.root / '.memedrop'
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
        ''')
        # Additive migration preserves existing media, tags, favorites and history.
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(media)')}
        with self.db:
            for column in ('content', 'title'):
                if column not in columns:
                    self.db.execute(f"ALTER TABLE media ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
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
        # Keep a tombstone so removed built-ins are not restored on restart.
        with self.db:
            self.db.execute("UPDATE media SET available = 0 WHERE id = ? AND kind = 'kaomoji'", (mid,))

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
            self.db.execute("UPDATE media SET available = 0 WHERE kind != 'kaomoji'")
            self.db.executemany('''INSERT INTO media(path, kind, added) VALUES(?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET available = 1, kind = excluded.kind''', found)
        return len(found)

    def path(self, meme: Meme) -> Path:
        if meme.kind == 'kaomoji':
            raise ValueError('顏文字是純文字，沒有素材檔案路徑。')
        path = (self.media_dir / meme.relative_path).resolve()
        path.relative_to(self.media_dir.resolve())
        return path

    def items(self, query: str = '', tag: Optional[str] = None, kind: str = 'all',
              collection: str = 'all', sort: str = 'newest') -> list[Meme]:
        from .kaomoji import ALIASES
        all_tags: dict[int, list[str]] = {}
        for mid, name in self.db.execute('SELECT media_id, name FROM tags ORDER BY name'):
            all_tags.setdefault(mid, []).append(name)
        rows = self.db.execute('SELECT id, path, kind, favorite, added, last_used, uses, content, title FROM media WHERE available = 1')
        words = query.casefold().split()
        result = []
        for row in rows:
            meme = Meme(*row[:7], tuple(all_tags.get(row[0], [])), *row[7:])
            haystack = (meme.name + ' ' + meme.content + ' ' + meme.relative_path + ' ' + ' '.join(meme.tags)).casefold()
            if meme.kind == 'kaomoji':
                haystack += ' ' + ' '.join(alias for label in meme.tags for alias in ALIASES.get(label, [])).casefold()
            if not all(word in haystack for word in words):
                continue
            if tag and tag not in meme.tags:
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
        key = {'newest': lambda m: (-m.added, m.name.casefold()),
               'name': lambda m: m.name.casefold(),
               'used': lambda m: (-m.uses, m.name.casefold()),
               'recent': lambda m: (-m.last_used, m.name.casefold())}
        return sorted(result, key=key['recent' if collection == 'recent' else sort])

    def tag_counts(self) -> list[tuple[str, int]]:
        return self.db.execute('''SELECT t.name, COUNT(*) FROM tags t JOIN media m
            ON t.media_id = m.id WHERE m.available = 1 GROUP BY t.name ORDER BY t.name''').fetchall()

    def set_tags(self, ids: list[int], tags: list[str], append: bool = False):
        with self.db:
            for mid in ids:
                if not append:
                    self.db.execute('DELETE FROM tags WHERE media_id = ?', (mid,))
                self.db.executemany('INSERT OR IGNORE INTO tags VALUES (?, ?)', ((mid, t) for t in tags))

    def rename_tag(self, old: str, new: str):
        new = new.strip().lstrip('#')
        if not new or new == old:
            return
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO tags SELECT media_id, ? FROM tags WHERE name = ?', (new, old))
            self.db.execute('DELETE FROM tags WHERE name = ?', (old,))

    def delete_tag(self, tag: str):
        with self.db:
            self.db.execute('DELETE FROM tags WHERE name = ?', (tag,))

    def set_favorite(self, ids: list[int], value: bool):
        with self.db:
            self.db.executemany('UPDATE media SET favorite = ? WHERE id = ?', ((int(value), mid) for mid in ids))

    def record_use(self, mid: int):
        with self.db:
            self.db.execute('UPDATE media SET uses = uses + 1, last_used = ? WHERE id = ?', (time.time(), mid))

    def setting(self, key: str, default: str) -> str:
        row = self.db.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, value))

    def import_files(self, paths: list[Path]) -> tuple[int, list[str]]:
        count, errors = 0, []
        for source in paths:
            if not source.is_file() or source.suffix.lower() not in EXTENSIONS:
                errors.append(source.name + '：不支援的檔案')
                continue
            try:
                source.resolve().relative_to(self.media_dir.resolve())
                continue
            except ValueError:
                pass
            target = self.media_dir / source.name
            index = 2
            while target.exists():
                target = self.media_dir / f'{source.stem} ({index}){source.suffix}'
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
            except OSError as exc:
                errors.append(f'{source.name}：{exc}')
        self.scan()
        return count, errors

    def close(self):
        self.db.close()

