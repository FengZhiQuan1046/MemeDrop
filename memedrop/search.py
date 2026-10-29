"""Normalize search keys while keeping stored names, tags and text intact."""

from functools import lru_cache

from opencc import OpenCC


_to_simplified = OpenCC('t2s')


@lru_cache(maxsize=8192)
def search_key(text: str) -> str:
    return _to_simplified.convert(text).casefold()


def matches_search(text: str, query: str) -> bool:
    original = text.casefold()
    normalized = search_key(text)
    return all(word.casefold() in original or search_key(word) in normalized for word in query.split())
