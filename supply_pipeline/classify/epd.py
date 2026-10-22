"""Georgia EPD construction stormwater NOIs (Atlanta): dwelling type of a residential NOI.

Production also sends the email DOMAINS of the filing's contacts (lennar.com reads as
single-family, greystar.com as apartments). The addresses themselves are personal data, so
the classifier never takes them: upstream code reduces them to a list of domains in
row["email_domains"], and the public golden set carries none.
"""
from __future__ import annotations

import json

from ..llm.provider import Request
from . import normalize

MODEL = "claude-haiku-4-5"
FEATURE = "epd_classify_dwelling"
VALID = {"single_family", "townhome", "multifamily", "mixed", "unknown"}

SYSTEM_PROMPT = """You classify a Georgia EPD Stormwater NOI residential project into one dwelling type.

Return EXACTLY one word — no explanation, no punctuation:
- single_family    (detached single-family home subdivision; includes BFR/SFR rentals)
- townhome         (attached townhomes, "TH", row homes)
- multifamily      (apartments, garden-style MF, condo buildings)
- mixed            (project explicitly combines two or more residential types)
- unknown          (truly insufficient signal — only use as last resort)

Pay attention to:
- Project / facility name (often contains "Townhomes", "Subdivision", "Apartments", etc.)
- Owner name and entity pattern ("X Apartments LLC" / "X Apartments Owner LLC" → MF;
  "X Homes LLC" / national homebuilder LLCs → SFD)
- Owner / operator / site-contact email DOMAIN — a strong signal:
  * SFD homebuilders: lennar.com, drhorton.com, pultegroup.com, kbhome.com, nvrinc.com,
    ashtonwoods.com, brockbuilt.com, drbgroup.com, mckinleyhomes.com, relianthomes.com,
    forestar.com, jwcatlanta.com, empirecommunities.com, drhorton.com
  * BFR / SFR operators (SFD product): amh.com, ah4r.com, invitationhomes.com, tricon.com,
    nexmetrocommunities.com
  * MF developers/operators: greystar.com, bellpartners.com, camdenliving.com, avalonbay.com,
    essex.com, milcreekres.com, hpdev.com, hanoverco.com, ardmoreresidential.com,
    twocapitalpartners.com, aviladevelopment.com, birgeandheld.com, trg-atl.com,
    pacesfoundation.org, cityscapehousing.com, firstcommercialconsulting.com,
    cowartresidential.com, templar-dev.com
  * Edge cases: epconcommunities.com (55+ townhome/villa — usually townhome, sometimes mixed)
- Extraction notes (narrative description from the form)
- Disturbed acres vs typical density (TH ≈ 6-10 u/ac, SFD ≈ 2-4, MF ≈ 20-40)
- Construction activity types
- Common development name

Bias toward committing. If the name says "Estates", "Subdivision", "Manor", "Preserve", "Pointe", "Landing", "Heights", "Hills", "Reserve", "Farms", "Ridge", default to single_family. If "Townhomes" or "Town Home" anywhere, default to townhome. If "Apartment" or "Multifamily", default to multifamily. If the email domain is a known national SFD homebuilder (Lennar, DR Horton, Pulte, KB, NVR, Ashton Woods, DRB, Brock Built, Reliant, etc.), default to single_family REGARDLESS of name. Only return 'unknown' when there is truly no signal."""


def email_domain(email) -> str | None:
    """'someone@builder.example' -> 'builder.example'. A bare domain passes through."""
    s = str(email or "").strip().lower()
    return (s.split("@", 1)[1] if "@" in s else s) or None


def build_user_msg(row: dict) -> str:
    msg = {
        "facility_name": row.get("facility_name"),
        "common_development_name": row.get("common_development_name"),
        "formerly_known_as": row.get("formerly_known_as"),
        "site_address": row.get("site_address"),
        "site_city": row.get("site_city"),
        "site_county": row.get("site_county"),
        "disturbed_acres": row.get("disturbed_acres"),
        "construction_activity_types": row.get("construction_activity_types"),
    }
    if row.get("owner_name"):
        msg["owner_name"] = row["owner_name"]
    domains = [d for d in (email_domain(e) for e in row.get("email_domains") or []) if d]
    if domains:
        msg["email_domains"] = domains     # domains only, never an address
    return json.dumps(msg, default=str)


def classify(provider, row: dict) -> str:
    c = provider.complete(Request(system=SYSTEM_PROMPT, user=build_user_msg(row), max_tokens=10,
                                  model=provider.model), feature=FEATURE)
    return normalize(c.text, VALID)
