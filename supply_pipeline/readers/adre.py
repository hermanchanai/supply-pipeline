"""Method: PDF documents. Arizona Department of Real Estate subdivision public reports: a
CSV index of every registration, then one PDF per report that only a reader can mine for
lot count, acreage, water provider, HOA dues and amenities.

  1. CSV index      -> azre.public_reports            (one GET, header-mapped)
  2. report PDF     -> local disk                     (GET the development page for an
                                                       anti-forgery token, then POST)
  3. first 8 pages  -> a language model with a JSON schema -> azre.public_reports_extracted

Pages 9+ are soil, climate and HOA bylaws boilerplate, so trimming roughly halves the
document tokens. Production stores the PDF in an object-storage bucket; here it is written
under data/local/. Developer mailing addresses are neither stored nor kept in the model's
recorded output.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from .. import http
from ..llm import pricing
from ..llm.budget import BudgetGuard
from ..llm.provider import CallLog, Completion, Request, Usage
from .az_geo import parse_az_county
from .base import ReaderResult

log = logging.getLogger(__name__)

METHOD = "pdf"
EXAMPLE_FEED = 7   # Phoenix: ADRE subdivision public reports

CSV_URL = "https://services.azre.gov/PdbWeb/List/DownloadList/4"
ADRE_BASE = "https://services.azre.gov/PdbWeb"
TRIM_PAGES = 8
MODEL = "claude-haiku-4-5"
PDF_DIR = Path("data/local/adre_pdfs")
_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S")

EXTRACT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "total_lots":               {"type": ["integer", "null"], "description": "Total number of residential lots in the subdivision. E.g. 'Lots 1 through 192, inclusive' → 192. null if not stated."},
        "subdivision_acres":        {"type": ["number", "null"], "description": "Approximate project acres. 'subdivision is approximately 6 acres' → 6.0. null if not stated."},
        "effective_date":           {"type": "string", "description": "ISO YYYY-MM-DD of the Public Report effective date. '' if not stated."},
        "legal_name":               {"type": "string", "description": "Subdivision Legal Name as printed on page 1. '' if missing."},
        "marketing_name":           {"type": "string", "description": "Marketing Name. Often 'N/A' on the form — return '' in that case, not 'N/A'."},

        "developer_name":           {"type": "string"},
        "developer_address":        {"type": "string"},
        "developer_city":           {"type": "string"},
        "developer_state":          {"type": "string"},
        "developer_zip":            {"type": "string"},

        "location_description":     {"type": "string", "description": "The 'Location' line on the form. E.g. 'southeast corner of 64th Street and Mayo Boulevard, City of Phoenix, Maricopa County'. '' if missing."},
        "street_intersection":      {"type": "string", "description": "Just the intersection (e.g. '64th Street and Mayo Boulevard'). '' if not parseable."},
        "parsed_city":              {"type": "string", "description": "City extracted from location_description. '' if not parseable."},
        "parsed_county":            {"type": "string", "description": "County. '' if not parseable."},

        "water_provider":           {"type": "string", "description": "Water provider's name (e.g. 'City of Phoenix', 'EPCOR Water', 'Town of Queen Creek'). '' if 'Not available' or missing."},
        "sewer_provider":           {"type": "string"},
        "electricity_provider":     {"type": "string", "description": "E.g. 'Arizona Public Service Company', 'Salt River Project'. '' if missing."},
        "gas_provider":             {"type": "string", "description": "'' if 'Not available' on the form."},

        "hoa_present":              {"type": ["boolean", "null"], "description": "true if a HOA Assessment is described. false/null if no HOA."},
        "hoa_assessment_amount":    {"type": ["number", "null"], "description": "HOA assessment dollar amount. Look in the HOA Assessments / Property Owners Association section. null if not stated."},
        "hoa_assessment_period":    {"type": "string", "description": "One of: 'monthly', 'quarterly', 'annual', 'one_time', 'unknown'. '' if no HOA."},
        "master_planned_community": {"type": "string", "description": "Master-planned community name if the subdivision is part of one. '' if 'Not part of a Master Planned Community' or unspecified."},

        "amenities":                {"type": "array", "items": {"type": "string"}, "description": "Common-area amenities listed. Examples: 'community pool', 'pool building with restrooms', 'ramadas', 'tot lot', 'multi-use trail', 'dog park', 'pickleball courts', 'clubhouse', 'fitness center'. Empty array [] if 'common area landscaping only' or none listed."},

        "school_district":          {"type": "string", "description": "School district name (e.g. 'Paradise Valley Unified School District', 'Deer Valley USD'). '' if missing."},
        "nearest_hospital":         {"type": "string", "description": "Name of nearest hospital. '' if missing."},
        "estimated_completion_date":{"type": "string", "description": "ISO YYYY-MM-DD when subdivision improvements complete (e.g. 'Will be complete by: December 31, 2026'). '' if 'Complete' / 'TBD' / missing."},

        "extraction_notes":         {"type": "string", "description": "1-2 sentence flag for anything unusual (handwritten edits, partial reports, ambiguous lot count, etc.). '' if nothing notable."},
    },
    "required": [
        "total_lots", "subdivision_acres", "effective_date",
        "legal_name", "marketing_name",
        "developer_name", "developer_address", "developer_city", "developer_state", "developer_zip",
        "location_description", "street_intersection", "parsed_city", "parsed_county",
        "water_provider", "sewer_provider", "electricity_provider", "gas_provider",
        "hoa_present", "hoa_assessment_amount", "hoa_assessment_period",
        "master_planned_community", "amenities",
        "school_district", "nearest_hospital", "estimated_completion_date",
        "extraction_notes",
    ],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """You extract structured fields from Arizona Department of
Real Estate (ADRE) Subdivision Public Reports. The input is the first ~8 pages
of an ADRE Disclosure Report PDF (filed under A.R.S. § 32-2183 for any
subdivision of ≥6 lots offered to the public). The report follows a fixed
template — Subdivision Information, General, Utilities, Streets/Roads, Local
Services, Common Areas, Assurances for Completion.

Read the PDF and return a JSON object that matches the provided schema
exactly. You do not invent data. You do not infer fields that aren't on the
form. The report follows a labeled-field structure; your job is to match the
label to the value next to it, normalize the value, and write it into the
right JSON field.

==========================================================================
Per-field extraction guidance
==========================================================================

SUBDIVISION INFO (page 1)
-------------------------
- legal_name: 'Legal Name:' on page 1. The subdivision's recorded name.
  Capture verbatim including capitalization. E.g. 'Prestige on 64th'.
- marketing_name: 'Marketing Name:' on page 1. The brand/sales name. If the
  form says 'N/A', return "" (empty string), NOT the string 'N/A'.
- effective_date: 'Effective Date:' on page 1. Format as ISO YYYY-MM-DD.
  'May 4, 2026' → '2026-05-04'.
- developer_name: 'Developer Name:' verbatim, including 'LLC', 'Inc.',
  partnership designators, etc. E.g. 'K. Hovnanian at Prestige on 64th, LLC'.
- developer_address / developer_city / developer_state / developer_zip:
  developer's mailing address split into components. Two-letter state code
  preferred ('AZ' over 'Arizona').

LOT COUNT (page 2, GENERAL section) — most important field
-----------------------------------------------------------
- total_lots: From phrasing like 'This report includes: Lots 1 through 192,
  inclusive.' or 'The subdivision has been divided into 192 Lots and Tracts
  A through H.' Return 192 as an integer.
  - If the report includes a discontinuous lot range (e.g. 'Lots 14-17, 23,
    25 and 30-47'), sum to the total contiguous count.
  - If the report says 'inclusive' or 'consisting of N Lots' both forms
    appear — both yield N.
  - Tracts (lettered A through H) are not residential lots. Do NOT include
    them in total_lots.
  - If the lot count is truly missing, return null.

- subdivision_acres: From phrasing like 'The subdivision is approximately 6
  acres in size'. Return the number as a float to 0.1 precision. null if
  not stated.

UTILITIES (page 2-3)
--------------------
- water_provider: The 'Water' provider's Name. Common values:
    'City of Phoenix', 'City of Scottsdale', 'City of Buckeye', 'EPCOR Water',
    'Town of Queen Creek', 'Town of Gilbert', 'Global Water Resources',
    'Pinal County Water Company', 'Arizona Water Company',
    'Liberty Utilities'.
  - If 'Not available' or blank, return "".
  - The water provider is the most important cross-source join key — this
    is what links ADRE projects to ADWR AAWS determinations.

- sewer_provider / electricity_provider / gas_provider: Same pattern. APS,
  SRP are typical electricity. Southwest Gas is typical gas. '' if 'Not
  available' or missing.

LOCATION (page 2, 'Location' field)
-----------------------------------
- location_description: The full 'Location' string verbatim. Often phrased
  as 'Subdivision is located at the southeast corner of 64th Street and
  Mayo Boulevard, within the City of Phoenix, Maricopa County, State of
  Arizona.'
- street_intersection: Just the intersection ('64th Street and Mayo
  Boulevard'). '' if the location is described differently (e.g. 'along
  XYZ Highway').
- parsed_city: City name ('Phoenix', 'Scottsdale'). '' if not extractable.
- parsed_county: County ('Maricopa', 'Pinal').

HOA (later pages — sometimes pages 7-9; rely on what's in the first 8)
-----------------------------------------------------------------------
- hoa_present: true if the form references HOA Assessments at all
  (typically in 'Purchasers' costs are included in: ... HOA Assessments').
  false/null if explicitly no HOA.
- hoa_assessment_amount: If the report states a dollar amount (e.g. '$165
  monthly' or '$1,800 annually'), return the numeric value (165 or 1800).
  null if not stated in the first 8 pages.
- hoa_assessment_period: 'monthly' / 'quarterly' / 'annual' / 'one_time'.
  If amount is null, return 'unknown'.
- master_planned_community: If the report says 'Not part of a Master
  Planned Community', return "". Otherwise the MPC name.

COMMON AREAS / AMENITIES (page 6)
---------------------------------
- amenities: Array of distinct amenity items from the 'State all common
  area amenities' section. Examples that should be returned as separate
  array items:
    ['common area landscaping', 'community pool', 'pool building with
     restrooms', 'ramadas', 'tot lot', 'multi-use trail', 'dog park']
  - Split on commas/semicolons. Keep multi-word items intact ('pool
    building with restrooms' is one item).
  - If the only amenity is generic 'common area landscaping', still
    include it as a single-item array.
  - If the form says no amenities, return an empty array [].

LOCAL SERVICES (page 4-5)
-------------------------
- school_district: From the schools section, the unified school district
  name. E.g. 'Paradise Valley Unified School District', 'Deer Valley
  USD'. '' if not stated.
- nearest_hospital: First hospital name in the Hospital section. E.g.
  'Mayo Clinic Hospital', 'HonorHealth Scottsdale Thompson Peak Hospital'.

COMPLETION (page 3+)
--------------------
- estimated_completion_date: ISO YYYY-MM-DD from phrasing like 'Will be
  complete by: December 31, 2026' under the Streets or Common Areas
  sections. Use the latest date if multiple are stated. '' if all marked
  'Complete' or no date stated.

EXTRACTION NOTES
----------------
- extraction_notes: 1-2 sentence note on anything unusual — handwritten
  overrides, partial / amended reports, mentions of phased takedown,
  unusual lot/tract structure, ambiguous lot count. '' if nothing notable.

==========================================================================
Conventions
==========================================================================
- Empty over guessing. "" for string fields, [] for array fields,
  null for numeric and ternary-boolean fields.
- Numeric fields are ALWAYS numbers, never strings. 192 not "192".
- Boolean fields are always booleans, never strings.
- Dates are ALWAYS ISO YYYY-MM-DD.
"""


# ----------------------------------------------------------------- 1. CSV index
def parse_date(s) -> str | None:
    s = (s or "").strip()
    if not s or s.upper() in ("NULL", "N/A"):
        return None
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt).date()
            return None if d.year > datetime.now(UTC).year + 2 else d.isoformat()
        except ValueError:
            continue
    return None


def parse_csv(text: str) -> list[dict]:
    """One row per registration; the first occurrence of a duplicated number wins."""
    rows: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        reg = (r.get("RegistrationNumber") or "").strip()
        if not reg or reg in rows:
            continue
        loc = (r.get("Location") or "").strip()
        city, state, county = parse_az_county(loc)

        def g(k, r=r):
            return (r.get(k) or "").strip() or None
        rows[reg] = {
            "registration_number": reg, "development_name": g("DevelopmentName"),
            "marketing_name": g("MarketingName"), "location": loc or None,
            "parsed_city": city, "parsed_state": state, "parsed_county": county,
            "application_type": g("ApplicationType"), "application_status": g("ApplicationStatus"),
            "lot_status": g("LotStatus"), "date_filed": parse_date(r.get("DateFiled")),
            "date_issued": parse_date(r.get("DateIssued")), "developer_name": g("DeveloperName"),
            "developer_dba": g("DeveloperDBA"),
        }
    return list(rows.values())


def fetch_csv(session) -> str:
    r = session.get(CSV_URL, timeout=180)
    r.raise_for_status()
    return r.content.decode("utf-8-sig")


# ----------------------------------------------------------------- 2. report PDF
def reg_to_id(registration_number: str) -> int:
    """DM26-062672 -> 62672 (the URL drops the prefix and leading zeros)."""
    m = re.match(r"^[A-Z]{2,3}\d{2}-(\d+)$", registration_number)
    if not m:
        raise ValueError(f"unrecognized registration number: {registration_number!r}")
    return int(m.group(1))


def fetch_pdf(session, registration_number: str) -> bytes:
    pdb_id = reg_to_id(registration_number)
    view = session.get(f"{ADRE_BASE}/Development/ViewDevelopment/{pdb_id}", timeout=30)
    view.raise_for_status()
    m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', view.text)
    if not m:
        raise RuntimeError(f"no anti-forgery token on the development page for {registration_number}")
    r = session.post(f"{ADRE_BASE}/Development/DownloadPublicReport",
                     data={"__RequestVerificationToken": m.group(1), "id": str(pdb_id)}, timeout=60)
    r.raise_for_status()
    if "application/pdf" not in (r.headers.get("Content-Type") or r.headers.get("content-type") or ""):
        raise RuntimeError(f"no report PDF for {registration_number} (cancelled or withdrawn registrations have none)")
    return r.content


def trim_pdf(pdf: bytes, max_pages: int = TRIM_PAGES) -> tuple[bytes, int]:
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(io.BytesIO(pdf))
    writer = PdfWriter()
    n = min(max_pages, len(reader.pages))
    for i in range(n):
        writer.add_page(reader.pages[i])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), n


# ----------------------------------------------------------------- 3. extraction
class AnthropicPdfExtractor:
    """Live extraction: the trimmed PDF as a document block, the field rules as a cached
    system prompt, and a JSON schema for the output. Needs requirements-live.txt."""

    def __init__(self, *, model: str = MODEL, guard: BudgetGuard | None = None,
                 log: CallLog | None = None, client=None):
        if client is None:
            import os

            import anthropic
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.client, self.model = client, model
        self.guard = guard or BudgetGuard(max_call_usd=0.10)
        self.log = log or CallLog(None)

    def __call__(self, pdf: bytes) -> dict:
        self.guard.check(len(pdf) / 1e6)   # coarse ceiling: about 1 USD per MB of PDF at Haiku rates
        t0 = time.perf_counter()
        resp = self.client.messages.create(
            model=self.model, max_tokens=2048,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                "data": base64.standard_b64encode(pdf).decode("ascii")}},
                {"type": "text", "text": "Extract the ADRE Subdivision Public Report fields from this PDF."}]}],
            output_config={"format": {"type": "json_schema", "schema": EXTRACT_SCHEMA}},
        )
        u = resp.usage
        usage = Usage(u.input_tokens, u.output_tokens, getattr(u, "cache_read_input_tokens", 0) or 0,
                      getattr(u, "cache_creation_input_tokens", 0) or 0)
        cost = pricing.cost_usd(self.model, *usage.__dict__.values()) or 0.0
        self.guard.record(cost)
        text = next((b.text for b in resp.content if b.type == "text"), "")
        self.log.write(provider="anthropic", req=Request("adre", "pdf", 2048, self.model), feature="adre_extract",
                       c=Completion(text, usage, int((time.perf_counter() - t0) * 1000)), cost=cost)
        return json.loads(text)


def to_extracted_row(reg: str, parsed: dict, *, pdf_path: Path | None, pdf_bytes: int,
                     pdf_pages: int, model: str) -> dict:
    def e(v):
        return None if v in ("", []) else v
    keep = {k: v for k, v in parsed.items()
            if not k.startswith("developer_") or k == "developer_name"}   # no mailing address
    return {
        "registration_number": reg, "total_lots": parsed.get("total_lots"),
        "subdivision_acres": parsed.get("subdivision_acres"),
        "effective_date": parsed.get("effective_date") or None,
        **{k: e(parsed.get(k)) for k in (
            "legal_name", "marketing_name", "developer_name", "location_description", "street_intersection",
            "parsed_city", "parsed_county", "water_provider", "sewer_provider", "electricity_provider",
            "gas_provider", "hoa_assessment_period", "master_planned_community", "school_district",
            "nearest_hospital")},
        "hoa_present": parsed.get("hoa_present"), "hoa_assessment_amount": parsed.get("hoa_assessment_amount"),
        "amenities": parsed.get("amenities") or None,
        "estimated_completion_date": parsed.get("estimated_completion_date") or None,
        "pdf_pages": pdf_pages, "pdf_byte_size": pdf_bytes,
        "pdf_path": str(pdf_path) if pdf_path else None,
        "raw_extraction_json": keep, "model": model,
        "extracted_at": datetime.now(UTC),
    }


def run(store, *, session=None, extractor=None, csv_text: str | None = None,
        counties: tuple[str, ...] = ("Maricopa", "Pinal"), limit: int | None = None,
        pdf_dir: Path = PDF_DIR, delay: float = 0.5) -> ReaderResult:
    """Load the index, then extract every unextracted report in `counties`."""
    session = session or http.session()
    rows = parse_csv(csv_text if csv_text is not None else fetch_csv(session))
    n_index = store.upsert("azre.public_reports", rows, key=("registration_number",))
    todo = store.rows("""
        select p.registration_number from azre.public_reports p
          left join azre.public_reports_extracted e using (registration_number)
         where e.registration_number is null and p.parsed_county = any(%s)
           and p.application_type like 'Subdivision%%'
         order by p.date_issued desc nulls last limit %s""", (list(counties), limit or 10**9))
    extracted, failed = 0, []
    extractor = extractor or AnthropicPdfExtractor()
    for t in todo:
        reg = t["registration_number"]
        try:
            pdf = fetch_pdf(session, reg)
            trimmed, pages = trim_pdf(pdf)
            path = Path(pdf_dir) / f"{reg}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(pdf)
            parsed = extractor(trimmed)
            store.upsert("azre.public_reports_extracted",
                         [to_extracted_row(reg, parsed, pdf_path=path, pdf_bytes=len(pdf), pdf_pages=pages,
                                           model=getattr(extractor, "model", "unknown"))],
                         key=("registration_number",))
            extracted += 1
        except Exception as e:   # one bad report must not stop the batch; it is reported
            failed.append(f"{reg}: {type(e).__name__}: {e}"[:200])
        time.sleep(delay)
    return ReaderResult("adre_public_reports", len(rows), n_index,
                        notes={"extracted": extracted, "failed": failed})
