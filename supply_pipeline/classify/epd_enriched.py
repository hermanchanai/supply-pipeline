"""Base EPD classifier plus the developer lexicon.

  1. Run the base classifier.
  2. An explicit project-name signal ("Apartments", "Townhomes") stands.
  3. Otherwise a lexicon hit overrides the base only when it changes the business bucket
     (for sale vs for rent vs mixed); a single-family vs townhome swap stays with the base,
     since both are for-sale product. An outright 'unknown' is filled from the lexicon.
"""
from __future__ import annotations

import re

from . import epd, lexicon

_NAME_MF = re.compile(r"apartment|multi-?family|\bflats?\b|condominium", re.I)
_NAME_TH = re.compile(r"town\s?home|row\s?home|townhouse", re.I)
_BUCKET = {"single_family": "for_sale", "townhome": "for_sale", "multifamily": "rental",
           "mixed": "mixed", "unknown": "unknown"}


def classify_verbose(provider, row: dict, table: dict | None = None) -> dict:
    table = lexicon.load() if table is None else table
    base = epd.classify(provider, row)
    name = f"{row.get('facility_name') or ''} {row.get('common_development_name') or ''}"
    if _NAME_MF.search(name) or _NAME_TH.search(name):
        return {"dwelling_type": base, "base": base, "source": "name", "lexicon_key": None}
    hit = lexicon.lookup(table, row.get("owner_name"),
                         *(epd.email_domain(e) for e in row.get("email_domains") or []))
    if hit and hit.get("typical") not in (None, "unknown"):
        typ = hit["typical"]
        if (typ != base and _BUCKET.get(typ) != _BUCKET.get(base)) or base == "unknown":
            return {"dwelling_type": typ, "base": base, "source": "lexicon", "lexicon_key": hit["key"]}
    return {"dwelling_type": base, "base": base, "source": "base",
            "lexicon_key": hit["key"] if hit else None}


def classify(provider, row: dict) -> str:
    return classify_verbose(provider, row)["dwelling_type"]
