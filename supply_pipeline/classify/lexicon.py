"""Developer lexicon: developer -> typical dwelling type, from independent evidence (county
permits and the developer's own description of what it builds). Keys are lowercase
substrings matched against an owner name or an email domain.

data/atlanta_developer_lexicon.json holds the Atlanta table. Caveat: developers
characterized while labelling a golden set trivially match those goldens, so a lexicon
score on the same goldens is not a generalization number.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "atlanta_developer_lexicon.json"


def load(path: Path = DEFAULT_PATH) -> dict[str, dict]:
    raw = json.loads(Path(path).read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9.\-]", "", (s or "").lower())


def lookup(table: dict[str, dict], *texts: str | None) -> dict | None:
    """First lexicon key found inside any of the texts (owner name, email domain).
    Longer keys win, so 'drhorton' beats a shorter key that happens to be inside it."""
    hay = [_norm(t) for t in texts if t]
    for key in sorted(table, key=len, reverse=True):
        k = _norm(key)
        if k and any(k in h for h in hay):
            return {"key": key, **table[key]}
    return None
