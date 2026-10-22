"""Dwelling-type classifiers for stormwater notices of intent (one per state program).

Each module exposes SYSTEM_PROMPT, build_user_msg(row), classify(provider, row) and the
production MODEL id. The model id is configurable: classify() sends `provider.model`.
"""

VALID = {"single_family", "townhome", "multifamily", "mixed", "commercial", "unknown"}


def normalize(text: str, valid: set[str] = VALID) -> str:
    """Map a one-word model reply onto the enum, tolerating case/spacing slips."""
    raw = (text or "").strip().lower().replace(" ", "_").replace("-", "_")
    if raw in valid:
        return raw
    if "single" in raw or raw in ("sfd", "sf"):
        return "single_family"
    if "town" in raw:
        return "townhome"
    if "multi" in raw or "apart" in raw:
        return "multifamily"
    if "mixed" in raw:
        return "mixed"
    if "commercial" in valid and ("comm" in raw or "industrial" in raw or raw in ("retail", "office")):
        return "commercial"
    return "unknown"
