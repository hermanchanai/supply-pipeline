"""Arizona ADEQ construction stormwater NOIs (Maricopa / Pinal): dwelling type from the
facility name and site context.

About three in four ADEQ construction NOIs are non-residential (fuel stops, self-storage,
car washes, schools, data centers), and the program carries no structured residential
flag, so the classifier must also emit `commercial`. Input is name-only: no owner, email
or narrative fields.
"""
from __future__ import annotations

import json

from ..llm.provider import Request
from . import VALID, normalize

MODEL = "claude-haiku-4-5"
FEATURE = "azdeq_classify"

SYSTEM_PROMPT = """You classify an Arizona ADEQ stormwater Construction General Permit (CGP) NOI into one dwelling type, based mostly on the facility/project name.

Return EXACTLY one word — no explanation, no punctuation:
- single_family    (detached single-family home subdivision; SFR / BFR / BTR rentals; "Estates", "Ranch", "Manor", "Preserve", "Reserve", "Trails", "Ridge", "Heights", "Hills", "Farms", "Landing", "Crossing", "Pointe")
- townhome         (attached townhomes; "Townhomes", "Town Homes", "TH", row homes)
- multifamily      (apartments, garden-style MF, condo buildings; "Apartments", "MF", "Residences" when paired with multi-story)
- mixed            (project name explicitly combines two or more residential types)
- commercial       (ANYTHING non-residential: schools, hospitals, parking lots, warehouses, retail, fuel stations, gas stations, car washes, restaurants, hotels, data centers, fire stations, parks, road improvements, utility projects, industrial, self-storage, RV parks, churches)
- unknown          (truly insufficient signal — use only as last resort)

The name is the strongest signal. Examples to internalize:
- "Estates at Hayden"                    → single_family
- "Quail Ranch"                          → single_family
- "Discovery IV at Bella Vista Farms"    → single_family
- "Missouri Townhomes"                   → townhome
- "Banyan Washington Apartments"         → multifamily
- "Palm Lane Residences"                 → multifamily (or single_family if narrative says so)
- "METRO TECH HIGH SCHOOL"               → commercial
- "Quick Quack Car Wash Surprise"        → commercial
- "Black Rock Coffee Bar, 91st Ave"      → commercial
- "AWS MESA"                             → commercial
- "Christy Cove Park Renovations"        → commercial
- "AH Sun City Parking Lot"              → commercial
- "Ryder Truck Rental and Leasing"       → commercial

Bias toward committing. Most ADEQ CGP NOIs ARE commercial — when the name clearly describes a non-residential use, return `commercial`. When the name has classic subdivision branding ("Reserve at X", "Pointe at Y") and is on a multi-acre project, default to single_family."""


def build_user_msg(row: dict) -> str:
    """Field order and serialization are part of the contract: recorded answers are keyed
    on the exact text this returns."""
    return json.dumps({
        "facility_name": row.get("facility_name"),
        "application_name": row.get("application_name"),
        "address": row.get("address"),
        "city": row.get("city"),
        "county": row.get("parsed_county"),
        "acres_disturbed_project": row.get("acres_disturbed_project"),
        "acres_disturbed_operations": row.get("acres_disturbed_operations"),
    }, default=str)


def classify(provider, row: dict) -> str:
    c = provider.complete(Request(system=SYSTEM_PROMPT, user=build_user_msg(row), max_tokens=10,
                                  model=provider.model), feature=FEATURE)
    return normalize(c.text, VALID)
