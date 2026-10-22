"""Arizona geography helpers for the ADRE reader.

Currently exposes:
  - AZ_COUNTIES        — canonical title-case county names keyed by lower-case alias
  - AZ_CITY_TO_COUNTY  — best-effort city -> county lookup (Maricopa+Pinal precise)
  - parse_az_county(loc)         — parse an ADRE-style county-name field
  - city_to_county(city)         — single-city lookup, returns Maricopa/Pinal/etc. or None
"""
from __future__ import annotations

import re

# Canonical AZ counties keyed by lowercase normalized alias
AZ_COUNTIES: dict[str, str] = {
    "apache":     "Apache",
    "cochise":    "Cochise",
    "coconino":   "Coconino",
    "gila":       "Gila",
    "graham":     "Graham",
    "greenlee":   "Greenlee",
    "la paz":     "La Paz",
    "maricopa":   "Maricopa",
    "mohave":     "Mohave",
    "navajo":     "Navajo",
    "pima":       "Pima",
    "pinal":      "Pinal",
    "santa cruz": "Santa Cruz",
    "yavapai":    "Yavapai",
    "yuma":       "Yuma",
}

# City -> county lookup. Targets Maricopa + Pinal precisely; other counties
# listed just so we don't mis-bucket their cities into Maricopa/Pinal.
AZ_CITY_TO_COUNTY: dict[str, str] = {
    # ----- Maricopa County -----
    "phoenix": "Maricopa", "scottsdale": "Maricopa", "tempe": "Maricopa",
    "mesa": "Maricopa", "chandler": "Maricopa", "gilbert": "Maricopa",
    "glendale": "Maricopa", "peoria": "Maricopa", "surprise": "Maricopa",
    "buckeye": "Maricopa", "goodyear": "Maricopa", "avondale": "Maricopa",
    "queen creek": "Maricopa",        # straddles -- mostly Maricopa
    "fountain hills": "Maricopa", "cave creek": "Maricopa",
    "carefree": "Maricopa", "paradise valley": "Maricopa",
    "litchfield park": "Maricopa", "el mirage": "Maricopa",
    "tolleson": "Maricopa", "wickenburg": "Maricopa",
    "youngtown": "Maricopa", "guadalupe": "Maricopa",
    "gila bend": "Maricopa", "sun city": "Maricopa",
    "sun city west": "Maricopa", "anthem": "Maricopa",
    "new river": "Maricopa", "rio verde": "Maricopa",
    "tonopah": "Maricopa", "morristown": "Maricopa",
    "wittmann": "Maricopa", "waddell": "Maricopa",
    "laveen": "Maricopa", "ahwatukee": "Maricopa",
    "ahwatukee foothills": "Maricopa", "verrado": "Maricopa",
    "tartesso": "Maricopa", "estrella": "Maricopa",
    "desert hills": "Maricopa",

    # ----- Pinal County -----
    "casa grande": "Pinal",
    "maricopa": "Pinal",              # CITY of Maricopa is in Pinal!
    "apache junction": "Pinal", "florence": "Pinal", "coolidge": "Pinal",
    "eloy": "Pinal", "kearny": "Pinal", "mammoth": "Pinal",
    "superior": "Pinal", "winkelman": "Pinal",
    "san tan valley": "Pinal", "queen valley": "Pinal",
    "saddlebrooke": "Pinal", "arizona city": "Pinal",
    "red rock": "Pinal", "oracle": "Pinal", "san manuel": "Pinal",
    "stanfield": "Pinal", "picacho": "Pinal",

    # ----- Pima -----
    "tucson": "Pima", "marana": "Pima", "sahuarita": "Pima",
    "oro valley": "Pima", "south tucson": "Pima", "vail": "Pima",
    "green valley": "Pima",
    # ----- Coconino -----
    "flagstaff": "Coconino", "page": "Coconino",
    # ----- Yavapai -----
    "sedona": "Yavapai", "prescott": "Yavapai",
    "prescott valley": "Yavapai", "cottonwood": "Yavapai",
    "camp verde": "Yavapai", "chino valley": "Yavapai",
    "dewey": "Yavapai", "humboldt": "Yavapai",
    # ----- Mohave -----
    "kingman": "Mohave", "lake havasu city": "Mohave",
    "bullhead city": "Mohave", "fort mohave": "Mohave",
    # ----- Yuma -----
    "yuma": "Yuma", "san luis": "Yuma", "somerton": "Yuma",
    "wellton": "Yuma",
    # ----- Navajo -----
    "show low": "Navajo", "snowflake": "Navajo",
    "winslow": "Navajo", "holbrook": "Navajo",
    "pinetop": "Navajo", "lakeside": "Navajo",
    # ----- Gila -----
    "globe": "Gila", "payson": "Gila", "miami": "Gila", "hayden": "Gila",
    "star valley": "Gila",
    # ----- Graham -----
    "safford": "Graham", "thatcher": "Graham", "pima": "Graham",
    # ----- Cochise -----
    "willcox": "Cochise", "sierra vista": "Cochise",
    "douglas": "Cochise", "bisbee": "Cochise",
    "benson": "Cochise", "tombstone": "Cochise", "huachuca city": "Cochise",
    # ----- Santa Cruz -----
    "nogales": "Santa Cruz", "patagonia": "Santa Cruz",
    "rio rico": "Santa Cruz",
    # ----- La Paz -----
    "parker": "La Paz", "quartzsite": "La Paz",
    # ----- Greenlee -----
    "duncan": "Greenlee", "clifton": "Greenlee", "morenci": "Greenlee",
    # ----- Apache -----
    "saint johns": "Apache", "st johns": "Apache",
    "springerville": "Apache", "eagar": "Apache",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def city_to_county(city: str | None) -> str | None:
    """Return canonical AZ county name for a given city, or None."""
    if not city:
        return None
    return AZ_CITY_TO_COUNTY.get(_norm(city))


def parse_az_county(loc: str | None) -> tuple[str | None, str | None, str | None]:
    """Parse a free-form Location field that may contain a county name,
    a 'City, ST' pair, or a bare city. Returns (city, state, county).

    Empirically the ADRE Location field is the COUNTY name (top-25 distinct
    values are AZ counties + all-caps + ' COUNTY'-suffixed variants), so
    we try county-name matching first and fall back to comma / city forms.
    """
    if not loc or not loc.strip():
        return None, None, None
    s = loc.strip()

    # Comma format: 'City, ST' or 'City, State Name'
    if "," in s:
        city, rest = s.rsplit(",", 1)
        city = city.strip()
        st = rest.strip().upper()
        if len(st) > 3:
            st = None
        county = city_to_county(city)
        return (city.title() if city else None, st, county)

    # County-name format (the common ADRE case)
    s_clean = re.sub(r"\s+(county|co\.?)$", "", s, flags=re.IGNORECASE).strip()
    s_norm = _norm(s_clean)
    if s_norm in AZ_COUNTIES:
        return (None, None, AZ_COUNTIES[s_norm])

    # Bare city without comma
    county = city_to_county(s)
    if county:
        return (s.title(), None, county)

    return (None, None, None)
