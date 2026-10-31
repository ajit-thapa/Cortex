"""Shared household memory. Pure Python book plus a thin persistence layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import re
from typing import Any
import uuid

CATEGORIES = ("fact", "preference", "person", "place", "routine", "note")
MAX_ITEMS = 400
_TOKEN = re.compile(r"[a-z0-9']+")
_STOP = frozenset(
    "the a an is are was to of and in on at it my me i you do does what who when "
    "where for with that this about like likes".split()
)


def tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1}


@dataclass
class Memory:
    text: str
    category: str = "fact"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str | None = None
    hits: int = 0


class MemoryBook:
    """In-memory list with near-duplicate merging and keyword recall."""

    def __init__(self, items: list[Memory] | None = None) -> None:
        self.items: list[Memory] = items or []

    @classmethod
    def from_data(cls, data: dict[str, Any] | None) -> MemoryBook:
        raw = (data or {}).get("items", [])
        return cls([Memory(**i) for i in raw])

    def to_data(self) -> dict[str, Any]:
        return {"items": [asdict(m) for m in self.items]}

    def add(self, text: str, category: str = "fact", source: str | None = None) -> Memory:
        text = " ".join(text.split())
        if not text:
            raise ValueError("nothing to remember")
        if category not in CATEGORIES:
            category = "fact"
        new = tokens(text)
        for old in self.items:
            have = tokens(old.text)
            if new and have and len(new & have) / len(new | have) >= 0.75:
                old.text, old.category = text, category
                return old
        memory = Memory(text=text, category=category, source=source)
        self.items.append(memory)
        if len(self.items) > MAX_ITEMS:
            self.items.sort(key=lambda m: (m.hits, m.created))
            self.items = self.items[-MAX_ITEMS:]
        return memory

    def recall(self, query: str, limit: int = 6) -> list[Memory]:
        want = tokens(query)
        if not want:
            return sorted(self.items, key=lambda m: (m.hits, m.created), reverse=True)[:limit]
        scored = []
        for memory in self.items:
            have = tokens(memory.text)
            score = len(want & have) + 0.5 * sum(
                1 for a in want for b in have if a != b and len(a) > 3 and (a in b or b in a)
            )
            if score:
                scored.append((score, memory.created, memory))
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        found = [m for _, _, m in scored[:limit]]
        for memory in found:
            memory.hits += 1
        return found

    def forget(self, ident: str) -> Memory | None:
        target = next((m for m in self.items if m.id == ident), None)
        if target is None:
            best = self.recall(ident, limit=1)
            target = best[0] if best else None
        if target:
            self.items.remove(target)
        return target
