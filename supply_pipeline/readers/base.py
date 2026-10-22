from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReaderResult:
    feed: str
    fetched: int
    upserted: int
    notes: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.fetched >= 0


def strip_or_none(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
