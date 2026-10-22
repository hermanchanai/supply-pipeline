"""Rule layer for TCEQ construction stormwater NOIs: dwelling type without a model call
wherever the evidence allows, and the prompt for the rows it cannot decide.

Order of evidence (decide_rules):
  1. mf_override  -- positive multifamily / townhome evidence: an explicit name ("apartments",
                     "townhomes", senior living), a recurring apartment brand, or an operator that
                     only builds multifamily. Apartment projects are routinely filed under a
                     commercial construction type or a non-residential SIC code, so this runs
                     before those shortcuts would bury them.
  2. sfd_guard    -- a production homebuilder operator or a strong subdivision name means
                     single-family, even when the filing declares multi-family.
  3. construction type, then the 4-digit SIC code.
  4. None         -- only a model can decide (build_user_msg + SYSTEM_PROMPT).

Every roster and guard came from labelled drills on real filings; the comments say which
false positive each guard exists to stop.
"""
from __future__ import annotations

import json
import re

from ..classify import normalize
from ..llm.provider import Request

MODEL = "claude-haiku-4-5"
FEATURE = "tceq_noi_classify"

VALID = {
    "single_family", "townhome", "multifamily", "mixed", "commercial", "unknown",
}

# SIC-code deterministic fallback (used in decide() when construction_type is
# absent — i.e. list-level NOIs with no detail-page scrape). The 4-digit SIC is
# filed on every NOI list row, so it classifies the bulk without a Haiku call.
_SIC_SINGLE_FAMILY = {
    "1521",  # General Contractors — Single-Family Houses
    "1531",  # Operative Builders (build spec SFD)
    "6552",  # Land Subdividers & Developers (predominantly SFD master-plans; MF
             # ones are caught earlier by mf_override on operator/name)
}
_SIC_MULTIFAMILY = {
    "1522",  # General Contractors — Residential Bldgs other than Single-Family (MF/TH/condo)
}
_SIC_COMMERCIAL = {
    "1541", "1542",                 # industrial / nonresidential building
    "1611", "1622", "1623", "1629", # highway / bridge / heavy / water-sewer-pipeline
    "1711", "1731", "1794", "1795", # plumbing / electrical / excavation / wrecking
    "1311", "1321", "1381", "1382", "1389",  # oil & gas extraction/services
    "4911", "4922", "4923", "4924", "4925", "4931", "4939",  # electric / gas / utilities
    "4612", "4613", "4619",         # pipelines
    "8211",                          # schools
}

SYSTEM_PROMPT = """You classify a Texas TCEQ stormwater Construction General Permit (CGP) NOI into one dwelling type, based on the project name and site context.

Return EXACTLY one word — no explanation, no punctuation:
- single_family    (detached single-family home subdivision; SFR / BFR / BTR rentals; "Estates", "Ranch", "Manor", "Preserve", "Reserve", "Trails", "Ridge", "Heights", "Hills", "Farms", "Landing", "Crossing", "Pointe", "Village", "Park" when paired with residential context)
- townhome         (attached townhomes; "Townhomes", "Town Homes", "TH", row homes, "Brownstones")
- multifamily      (apartments, garden-style MF, condo buildings; "Apartments", "MF", "Residences" when paired with multi-story)
- mixed            (project name explicitly combines two or more residential types, or mixed-use w/ residential)
- commercial       (ANYTHING non-residential: schools, hospitals, parking lots, warehouses, retail, fuel stations, gas stations, car washes, restaurants, hotels, data centers, fire stations, parks, road improvements, utility projects, industrial, self-storage, RV parks, churches, mass grading w/o named residential project, detention ponds)
- unknown          (truly insufficient signal — use only as last resort)

Use SIC code as a strong supporting signal:
- SIC 1521 = Single-Family Housing Construction       → single_family by default
- SIC 1522 = Residential Construction, Other (MF/TH)  → multifamily or townhome
- SIC 1541 = Industrial Building Construction         → commercial
- SIC 1542 = Nonresidential Building Construction     → commercial
- SIC 1611 = Highway/Street Construction              → commercial (infrastructure)
- SIC 1623 = Water/Sewer/Pipeline Construction        → commercial (infrastructure)
- SIC 1629 = Heavy Construction (mass grading)        → context-dependent; default commercial unless project name clearly residential
- SIC 6552 = Land Subdividers and Developers          → single_family by default

The construction_type field is a useful prior:
- construction_type == "RESIDENTIAL"  → expect single_family / townhome / multifamily (use name to pick)
- construction_type == "INDUSTRIAL"   → commercial
- construction_type == "COMMERCIAL"   → commercial
- construction_type == "MIXED"        → mixed (or single_family if name strongly indicates SFR)

Bias toward committing. Examples:
- "NORTHWEST 99 MASS GRADING & DETENTION"            → commercial (mass grading)
- "Bridgeland Creekland Village Sec 26"              → single_family (subdivision phase)
- "Mesa Vista"                                       → single_family (subdivision name)
- "Cypress Trails at Bauer Landing"                  → single_family
- "Sila Sec 13" / SIC 6552                           → single_family (subdivision phase + land subdivider)
- "Trillium Sec 14" / SIC 6552                       → single_family
- "Poundbury Sec 2" / Lovett Homes                   → single_family
- "IDV HOLDERRIETH" / SIC 1541                       → commercial (industrial building)
- "Harris County Toll Road Authority" / SIC 1611     → commercial (highway)
- "QUICK QUACK CAR WASH"                             → commercial
- "AMAZON DC HOUSTON"                                → commercial (data center / distribution)
- "Riviera Pines Townhomes"                          → townhome
- "Bridgeland Apartments"                            → multifamily"""


def build_user_msg(row: dict) -> str:
    return json.dumps({
        "project_name":      row.get("project_name"),
        "operator_name":     row.get("operator_name"),
        "site_address":      row.get("site_address"),
        "site_city":         row.get("site_city"),
        "site_county":       row.get("site_county"),
        "disturbed_acres":   row.get("disturbed_acres"),
        "construction_type": row.get("construction_type"),
        "primary_sic_code":  row.get("primary_sic_code"),
    }, default=str)


# MF-builder roster (operator-name substrings). Derived from the Houston lifecycle
# eval golden (2026-05-29) + the precision/recall blind drills (2026-06-03): these
# entities are MF/BTR SPECIALISTS, so an operator match is a high-precision MF
# signal. Tokens are distinctive (multi-word where a single word would over-match).
# DELIBERATELY EXCLUDES diversified GCs (Arch-Con, Cadence McShane) and SFR/BTR
# detached builders (DHI Communities, Camillo) — the precision drill showed Arch-Con
# over-fires to commercial, so operator alone is not enough for them.
MF_ROSTER = (
    "multifamily", "multi-family", "multi family",
    # national / conventional MF
    "hanover", "greystar", "venterra", "wood partners", "trammell crow",
    "high street resid", "jlb partners", "morgan group", "marquette", "dinerstein",
    "mill creek resid", "alliance residential", "cortland", "embrey", "allied orion",
    "knightvest", "sueba", "oht houston", "oht construction", "oht partners",
    # "pelican build" REMOVED 2026-10-05: Pelican Builders files detached SFD
    # (SOMERSET GREEN, WOODMILL CREEK, BOULEVARD GREEN 98 for-sale homes); its one MF
    # filing (BOULEVARD GREEN AT VISION PARK) is CT=MULTI-FAMILY and classifies MF anyway.
    "zom ", "leon multifamily", "thompson thrift",
    # Houston apartment GCs surfaced by the eval (operator-name matches on the NOI)
    "maple multi", "oden hughes", "camden builders", "nrp construction",
    "blazer building", "domain builders", "strategic construction",
    "davis brothers construction", "westchase construction", "ahc construction",
    "dale construction services", "rah contractors", "caldwell multifamily",
    "ascension multifamily", "resia construction", "tx-morrow", "mcrt",
    # Added 2026-06-03 from the MF-lifecycle recall re-run (each EVAL-CONFIRMED + production-
    # checked safe — every operator~token NOI in the 9-county set is this one MF developer):
    #   "clay residential" → Willow at Marvida 368u (was single_family via SIC-1611)
    #   "brownstone" → The Brownstone Group; 15 NOIs all this MF dev (Edison 55, Hawthorne at
    #     Bay Forest, Lancaster Senior Village… 5 commercial/1 SF were mislabels). NOT "tannos"
    #     (diversified — also files SF "Estates at Wilderness Trails" → would FP).
    "clay residential", "brownstone",
)

# MF brand-name roster (project-name substrings) — recurring Houston apartment brands
# (each spans multiple properties), so a name match is high-precision MF even when the
# operator is a no-name LLC. Grows with each labeling pass (cf. Atlanta developer lexicon).
_MF_BRAND_TOKENS = (
    "springs at ", "ariza", "alders ", "slate ", "modera", "elan ", "alta ",
    "allora", "broadstone", "prose ", "aspire ", "amplify", "the verge",
    "lenox ", "highbridge", "boulevard green", "smart living", "cadence creek",
    "two lakes edge", "watermere", "lakeside row",
)
# "district west" REMOVED 2026-10-05: it is a Katy SUBMARKET name, not a brand --
# it fired on DISTRICT WEST retail (CT=COMMERCIAL 1542) and DISTRICT WEST PUBLIC
# IMPROVEMENTS (CT=UTILITY 1623). Every real DISTRICT WEST apartment filing (PROSE /
# ALLORA DISTRICT WEST, DISTRICT WEST II/III) is caught by CT=MF or the roster anyway.
#
# Brand tokens are matched WHOLE-WORD (regex \b...\b, see _brand_match) since 2026-10-05:
# a bare substring let short tokens ride other words. Place names that collide with a
# brand are blanked out first -- "ALTA LOMA" (Galveston Co.) is not an Alta property;
# it fired on two CenterPoint 138kV transmission rebuilds.
_BRAND_RE = re.compile(r"\b(?:" + "|".join(re.escape(t.strip()) for t in _MF_BRAND_TOKENS) + r")\b")
_BRAND_PLACE_COLLISIONS = ("alta loma",)


def _brand_match(name: str) -> bool:
    for place in _BRAND_PLACE_COLLISIONS:
        name = name.replace(place, " ")
    return bool(_BRAND_RE.search(name))


# Infrastructure filings. A road / utility-line / transmission NOI
# that happens to carry an apartment BRAND or be filed by an MF-specialist operator is
# sitework, not housing supply (the eval labels these commercial -- cf. June goldens
# "INDIAN HILLS MULTIFAMILY ... WASTEWATER", "BELMONT APARTMENTS PARKING"). So the WEAK
# signals (brand / roster / ambiguous senior) never override an infrastructure SIC, nor an
# infrastructure CT unless the SIC itself is 1522 (CT=UTILITY + SIC 1522 is a real
# apartment filed by its utility sub: ASHER SPRING CYPRESS, THE ALCOVE AT BENDERS LANDING).
# CT=COMMERCIAL is deliberately NOT a veto: real MF is routinely filed CT=COMMERCIAL 1542
# (ALTA SERGEANT, ALLORA FALLBROOK, Urbana) -- that burial is why mf_override exists.
# Name-explicit MF ("apartment", "multi family") still beats all of this.
_INFRA_SIC = {"1611", "1622", "1623", "4612", "4613", "4619"}   # + every 49xx utility
_INFRA_CT = {"UTILITY", "HIGHWAY OR ROAD"}


def _is_infra_sic(sic: str) -> bool:
    return sic in _INFRA_SIC or (len(sic) == 4 and sic.startswith("49"))


def _is_infrastructure(ct: str, sic: str) -> bool:
    return _is_infra_sic(sic) or (ct in _INFRA_CT and sic != "1522")


def _sfr_btr_guarded(name: str) -> bool:
    """_SFR_BTR_GUARD mixes substrings and \\b-regexes; a literal `in` test never matched
    the regex entries (Codex design review 2026-10-05: 'ALTA BTR HOMES' rode a brand)."""
    return any(re.search(g, name) if g.startswith("\\b") else g in name for g in _SFR_BTR_GUARD)

# Senior congregate-RENTAL signals → multifamily. "_STRONG" are unambiguous MF rental;
# "_AMBIG" (active-adult / 55+) can be detached for-sale (Del Webb), so they only fire
# past the homebuilder/SFR guards.
_SENIOR_STRONG = ("senior living", "assisted living", "independent living",
                  "memory care", "senior residence", "senior apartments")
_SENIOR_AMBIG = ("active adult", "55+", "62+")

# Detached SFR / build-to-rent / cottage → stays single_family BY FORM (rental but not MF).
_SFR_BTR_GUARD = ("sfr", "single family", "single-family", "build to rent",
                  "build-to-rent", "\\bbtr\\b", "cottages", "summerwell", "sunterra")

# Non-residential project-name guard: a roster surname (e.g. "hanover") can match a
# contractor who also builds warehouses, AND a commercial project mis-coded SIC 1522
# (McDonald's, hospitals, churches) must not flip to MF — so block the weak overrides
# when the name is clearly non-residential. Expanded 2026-06-03 from the recall drill.
_NONRES_NAME_GUARD = (
    "logistics", "warehouse", "distribution", "industrial", "mitigation",
    "data center", "car wash", "self storage", "storage facility", "fulfillment",
    "hospital", "medical", "clinic", "dialysis", "wellness", "surgery",
    "church", "ministr", "chapel", "mosque", "temple", "worship",
    "school", "academy", "montessori", "daycare", "day care", "learning center",
    "university", "college", "seminary", "isd ", "elementary",
    "hotel", " inn", "suites", "motel", "hospitality",
    "retail", "shopping", "market", "store", "restaurant", "mcdonald", "bank",
    "office", "business park", "industries", "manufacturing", "refinery",
    # Added 2026-06-11 (Austin region-11 reconcile): roster surnames false-fired on
    # "MCCLAINS RV SERVICE CENTER" (op contains "morgan group") + "HANOVER RED BUD
    # BUSINESS CENTER" (op contains "hanover"). Statewide sweep: every other
    # business/service-center NOI is already commercial — zero genuine-MF collisions.
    "business center", "service center",
    "terminal", "yacht", "marina", "rv resort", "rv park", "golf",
    "rec center", "recreation", "fire station", "justice center", "jail",
    "civic", "library", "museum", "hangar", "airport", "fuel", "gas station",
    "dealership", "collision", "tesla", "amazon", "walmart", "costco",
    "criminal", "detention center", "powell", "praxair", "exxon", "data ",
)

# Production SFD homebuilders / land developers (operator substrings). A match means
# the project is single-family REGARDLESS of a mis-declared CT=MULTI-FAMILY (the cause
# of every precision false-positive in the drill). Curated to pure-SFD shops only —
# NOT Camden (MF), NOT DHI Communities (BTR).
_HOMEBUILDER_OPS = (
    "castlerock", "lennar", "d.r. horton", "dr horton", "d r horton",
    "perry homes", "david weekley", "meritage", "pulte", "kb home",
    "century communit", "lgi ", "chesmar", "coventry homes", "highland homes",
    "ashton woods", "taylor morrison", "hovnanian", "kendall homes",
    "ultimate homes", "green texas builders", "gehan", "westin homes",
    "long lake", "land tejas", "dunhill", "\\btoll", "k. hovnanian",
    "stylecraft",   # 2026-10-05: Bryan/College Station production SFD builder
)

_SIC_SFD_HARD = {"1521", "6552"}                 # single-family GC + land subdivider
_SIC_SITE_HARD = {"1611", "1623", "1629", "1794"}  # paving / utility / heavy / excavation


def _is_homebuilder(op: str) -> bool:
    return any(t.replace("\\b", "") in op for t in _HOMEBUILDER_OPS)


def _looks_sfd_name(name: str) -> bool:
    """Strong SFD-subdivision name markers only (no generic geography tokens like
    reserve/crossing/pointe/ranch — those over-fire on MF brands, per the drill)."""
    n = f" {name} "
    if "subdivision" in name or "estates" in name or "land development" in name:
        return True
    if " sec " in n or " section " in n or " sections " in n:
        return True
    if " lot " in n or " lots " in n:
        return True
    # "SEC1" / "SECTION2" with no space.
    if re.search(r"\bsec(?:tion)?\d", name):
        return True
    return False


def mf_override(row: dict) -> str | None:
    """High-precision multifamily/townhome override applied BEFORE the CT/SIC
    shortcuts. Returns 'multifamily'/'townhome' or None.

    Why: TCEQ operators file apartment projects under construction_type=COMMERCIAL
    or a non-residential SIC (1542/1623), so the deterministic shortcuts in decide()
    would bury them. Positive-evidence only (apartment/townhome/senior NAME, MF brand,
    MF specialist operator) — a blunt SIC-1522->MF flip was rejected: the recall drill
    showed ~58% of non-MF SIC-1522 rows are commercial misfiles (McDonald's, hospitals).

    Detached BTR/SFR/cottage and production-homebuilder rows stay single_family by form.
    """
    name = (row.get("project_name") or "").lower()
    op = (row.get("operator_name") or "").lower()
    ct = (row.get("construction_type") or "").strip().upper()
    sic = (row.get("primary_sic_code") or "").strip()
    # 1. Name-explicit MF beats everything (incl a SIC-1521 misfile, e.g.
    #    "THE VIREO APARTMENTS"/SIC 1521, "NORTHWOOD APARTMENTS"/SIC 1521 are real MF).
    #    "apartment" is checked before "townhome" so "...Town Homes AND Apartments" -> MF;
    #    "lofts"/"flats" added so "Lofts at Knight Estates" isn't demoted by the SFD guard.
    if "apartment" in name or "lofts" in name or " flats" in name:
        return "multifamily"
    if "townhome" in name or "townhomes" in name or "town home" in name:
        return "townhome"
    # Senior-congregate tokens yield to an explicit single-family CT (: ADERRA
    # SENIOR LIVING AT AUDUBON - HOME BUILDING = 155 detached for-sale 62+ homes,
    # CT=SINGLE-FAMILY RESIDENTIAL, SIC 1521). No real senior-rental filing carries CT=SF.
    if ct != "SINGLE-FAMILY RESIDENTIAL" and any(t in name for t in _SENIOR_STRONG):
        return "multifamily"
    # 2. Guards for the weaker (brand / operator / ambiguous-senior) signals.
    if _sfr_btr_guarded(name):
        return None
    if any(g in name for g in _NONRES_NAME_GUARD):
        return None
    if _is_homebuilder(op):
        return None
    # 2b. Explicit multi-family in the NAME. Same evidence tier as "apartment"
    #     in step 1, but sequenced past the guards above so a non-housing
    #     collision cannot ride the token — and ahead of the CT branch below so
    #     a utility/sitework filing (CT=UTILITY, SIC 4922) can't bury it.
    if any(t in name for t in _MF_NAME_TOKENS):
        return "multifamily"
    if ct == "SINGLE-FAMILY RESIDENTIAL":
        return None
    # 2c. Infrastructure filings never ride a weak signal.
    if _is_infrastructure(ct, sic):
        return None
    # 3. Weaker positive signals (past the guards above).
    if any(t in name for t in _SENIOR_AMBIG):
        return "multifamily"
    # A brand is NAME-only evidence, so a single-family-GC SIC outranks it (:
    # BOULEVARD GREEN, SIC 1521, 98 detached homes). The operator roster is NOT gated on
    # 1521: MF specialists do file 1521 (ALLORA FRIENDSWOOD/Maple, CAMDEN LONG MEADOW FARMS).
    if sic not in ("1521", "1531") and _brand_match(name):
        return "multifamily"
    if any(tok in op for tok in MF_ROSTER):
        return "multifamily"
    return None


# Explicit multi-family PROJECT-NAME tokens. MF_ROSTER already carries these
# three spellings, but MF_ROSTER is only ever matched against `operator_name`
# (`any(tok in op ...)`) — so a project literally NAMED "... MULTI FAMILY ..."
# fell through mf_override entirely and landed on the CT/SIC branches, which
# return 'commercial' when a utility/sitework contractor filed the NOI. That is
# exactly the burial mf_override exists to defeat, and it is the same class the
# 2026-06-11 region-11 reconcile fixed for apartment-named rows (WOLF LAKES
# APARTMENTS, GRAND AVENUE FLATS).
#
# Placement is deliberate: applied AFTER the SFR/non-residential/homebuilder
# guards, so a non-housing collision ("MULTI FAMILY OFFICE" is a wealth-
# management term) cannot ride the token; but BEFORE the construction_type
# branch, so it still beats a mis-declared CT — which is the whole point.
# Added 2026-08-04 from LAWHON MULTI-FAMILY PHS 1 / MULTI FAMILY PHS 2
# (Georgetown, Williamson; Atmos Energy + Denbow; CT=UTILITY, SIC 4922).
_MF_NAME_TOKENS = ("multifamily", "multi-family", "multi family")


# A subdivision-style name token ("lot"/"block"/"sec") can sit on a row that is
# actually a NON-residential component — a platted COMMERCIAL lot, a community
# AMENITY CENTER (clubhouse), a SITE-DEVELOPMENT/sitework package. Those must NOT be
# demoted to single_family by the name guard. Added 2026-06-11 (Austin region-11
# SF-radar precision tail: "MANOR NE COMMERCIAL LOT 25 BLOCK A" was riding the " lot "
# token to single_family). Safe by construction — sfd_guard only OVERRIDES a
# non-residential CT; a genuinely-residential row (CT=SINGLE-FAMILY RESIDENTIAL) still
# stays SF via the CT branch below, so blocking the guard here can't demote real SFD.
_SFD_GUARD_BLOCK = ("commercial", "amenity center", "site development")


def sfd_guard(row: dict) -> str | None:
    """Single-family demotion, applied AFTER mf_override (so genuine MF already
    returned). Fires on a production homebuilder operator OR a strong SFD-subdivision
    name — this is what overrides the mis-declared CT=MULTI-FAMILY that caused every
    precision false-positive in the drill (Grand Magnolia Sections, Castlerock, Bay
    Utilities subdivisions all filed CT=MF)."""
    op = (row.get("operator_name") or "").lower()
    name = (row.get("project_name") or "").lower()
    if _is_homebuilder(op):
        return "single_family"
    if _looks_sfd_name(name) and not any(t in name for t in _SFD_GUARD_BLOCK):
        return "single_family"
    return None


def _decide_rules(row: dict) -> str | None:
    """All deterministic branches. Returns a label, or None when only the Haiku
    model can decide. Shared by decide() and decide_deterministic()/--reconcile."""
    ct = (row.get("construction_type") or "").strip().upper()
    sic = (row.get("primary_sic_code") or "").strip()
    mf = mf_override(row)
    if mf:
        return mf
    sfd = sfd_guard(row)
    if sfd:
        return sfd
    if ct == "SINGLE-FAMILY RESIDENTIAL":
        return "single_family"
    if ct == "MULTI-FAMILY RESIDENTIAL":
        # Trust CT=MF ONLY when the SIC doesn't unambiguously contradict it. A
        # single-family-GC (1521) / land-subdivider (6552) / paving-utility (161x/1794)
        # filing CT=MF is a misdeclaration — the SIC wins. (mf_override already
        # rescued the genuine MF-by-operator/name rows above.)
        if sic in _SIC_SFD_HARD:
            return "single_family"
        if sic in _SIC_SITE_HARD or _is_infra_sic(sic):
            return "commercial"
        return "multifamily"
    if ct in ("INDUSTRIAL", "COMMERCIAL", "INSTITUTIONAL", "UTILITY", "HIGHWAY OR ROAD"):
        return "commercial"
    if sic in ("1541", "1542", "1611", "1623"):
        return "commercial"
    if ct == "OTHER" and sic in ("6552", "1521"):
        return "single_family"
    if sic in _SIC_SINGLE_FAMILY:
        return "single_family"
    if sic in _SIC_MULTIFAMILY:
        # SIC 1522 is ~70% MF but ~30% misfiled commercial/SFD (McDonald's, hospitals,
        # SFD master-plans filed under it). Only commit when the name corroborates;
        # otherwise DEFER (None -> Haiku in a full run; left UNCHANGED in --reconcile,
        # so a correct legacy label is never clobbered). mf_override already rescued
        # apartment/senior/brand/MF-operator rows above.
        nm = (row.get("project_name") or "").lower()
        if any(g in nm for g in _NONRES_NAME_GUARD):
            return "commercial"
        if _looks_sfd_name(nm) or _is_homebuilder((row.get("operator_name") or "").lower()):
            return "single_family"
        if not ct and _sic1522_no_ct_is_apartment(row):
            return "multifamily"
        return None
    if sic in _SIC_COMMERCIAL:
        return "commercial"
    return None


# (2026-10-05). SIC 1522 ("residential other than single-family") with NO
# construction_type and no name signal used to defer to Haiku, which called 7 of 43
# blind-eval apartment complexes 'townhome' (ESPERANZA AT KIETH HARROW 276u, LONG POINT
# 308u, ...; all 6-16 ac). A townhome call needs ATTACHED-product evidence, and real
# townhome filings carry it in the name ("... TOWNHOMES", already caught by mf_override)
# or are infill-sized. So on an apartment-sized site with none of the attached / SFR-BTR /
# site-only tokens below, SIC 1522 resolves to multifamily. Outside 5-40 ac, or with any
# such token, it still defers (Haiku for a new row; --reconcile leaves the label alone).
_ATTACHED_TOKENS = ("duplex", "triplex", "fourplex", "quadplex", "townhouse", "row home",
                    "rowhome", "patio home", "garden home", " towns", "brownstones")
_SITE_ONLY_RE = re.compile(r"\b(?:detention|drainage|ponds?|swppp|spoil|parking|amenity|"
                           r"utilit\w*|water|wastewater|sewer|road|street|drive|"
                           r"improvements?|grading|sitework|site work|site development|"
                           r"clearing|paving|excavation|infrastructure)\b")
_SIC1522_MF_ACRES = (5.0, 40.0)


def _sic1522_no_ct_is_apartment(row: dict) -> bool:
    name = f" {(row.get('project_name') or '').lower()} "
    if any(t in name for t in _ATTACHED_TOKENS) or _SITE_ONLY_RE.search(name):
        return False
    if _sfr_btr_guarded(name):
        return False
    try:
        acres = float(row.get("disturbed_acres"))
    except (TypeError, ValueError):
        return False
    lo, hi = _SIC1522_MF_ACRES
    return lo <= acres <= hi


def decide_rules(row: dict) -> str | None:
    """Public name for the deterministic layer."""
    return _decide_rules(row)


def classify(provider, row: dict) -> str:
    """Rules first; the model only for what they leave undecided."""
    label = _decide_rules(row)
    if label is not None:
        return label
    c = provider.complete(Request(system=SYSTEM_PROMPT, user=build_user_msg(row), max_tokens=10,
                                  model=provider.model), feature=FEATURE)
    return normalize(c.text, VALID)
