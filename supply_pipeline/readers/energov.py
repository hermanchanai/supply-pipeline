"""Method: permit-portal JSON. Tyler EnerGov Self Service portals feed their own search page
from a JSON API; one reader covers every jurisdiction on that software.

Anonymous plan-module sweep only (no login flows). The recipe: keep SearchModule=1 and set
FilterModule=3 (plans). An empty keyword sorted by ApplyDate returns the whole plan feed
newest-first. Some tenants throttle that feed after a dozen pages while still reporting
the full TotalPages, so a keyword list re-slices the archive; CaseId dedup makes the
overlap harmless.

Only genuine entitlement case types are kept (rezonings, PDs, SUPs, plats, site plans);
zoning-verification letters, licenses, engineering and right-of-way cases are dropped by
an explicit allowlist / denylist pair. Henderson, NV is the bundled config.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass

from .. import http
from .base import ReaderResult, strip_or_none
from .entitlement import classify_dwelling, upsert_cases

log = logging.getLogger(__name__)

METHOD = "portal_json"
EXAMPLE_FEED = 195   # Las Vegas: Henderson entitlement plans (Tyler EnerGov)

HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "tenantid": "1",
    "tyler-tenant-culture": "en-US",
    "tyler-tenanturl": "home",
}

# The full criteria object the portal's own search page posts. The server rejects a body
# that leaves out a criteria block, so the shape is kept verbatim.
SEARCH_BODY_TEMPLATE = {
    "Keyword": "",
    "ExactMatch": False,
    "SearchModule": 1,
    "FilterModule": 2,  # 2 = Permits only
    "SearchMainAddress": False,
    "PlanCriteria": {
        "PlanNumber": None, "PlanTypeId": None, "PlanWorkclassId": None, "PlanStatusId": None,
        "ProjectName": None, "ApplyDateFrom": None, "ApplyDateTo": None,
        "ExpireDateFrom": None, "ExpireDateTo": None, "CompleteDateFrom": None, "CompleteDateTo": None,
        "Address": None, "Description": None, "SearchMainAddress": False, "ContactId": None,
        "ParcelNumber": None, "TypeId": None, "WorkClassIds": None, "ExcludeCases": None,
        "EnableDescriptionSearch": False, "PageNumber": 0, "PageSize": 0,
        "SortBy": None, "SortAscending": False,
    },
    "PermitCriteria": {
        "PermitNumber": None, "PermitTypeId": None, "PermitWorkclassId": None, "PermitStatusId": None,
        "ProjectName": None, "IssueDateFrom": None, "IssueDateTo": None,
        "Address": None, "Description": None, "ExpireDateFrom": None, "ExpireDateTo": None,
        "FinalDateFrom": None, "FinalDateTo": None, "ApplyDateFrom": None, "ApplyDateTo": None,
        "SearchMainAddress": False, "ContactId": None, "TypeId": None, "WorkClassIds": None,
        "ParcelNumber": None, "ExcludeCases": None, "EnableDescriptionSearch": False,
        "PageNumber": 0, "PageSize": 0, "SortBy": "relevance", "SortAscending": False,
    },
    "InspectionCriteria": {
        "Keyword": None, "ExactMatch": False, "Complete": None, "InspectionNumber": None,
        "InspectionTypeId": None, "InspectionStatusId": None, "RequestDateFrom": None,
        "RequestDateTo": None, "ScheduleDateFrom": None, "ScheduleDateTo": None,
        "Address": None, "SearchMainAddress": False, "ContactId": None, "TypeId": [],
        "WorkClassIds": [], "ParcelNumber": None, "DisplayCodeInspections": False,
        "ExcludeCases": [], "ExcludeFilterModules": [], "HiddenInspectionTypeIDs": None,
        "PageNumber": 0, "PageSize": 0, "SortBy": None, "SortAscending": False,
    },
    "CodeCaseCriteria": {
        "CodeCaseNumber": None, "CodeCaseTypeId": None, "CodeCaseStatusId": None, "ProjectName": None,
        "OpenedDateFrom": None, "OpenedDateTo": None, "ClosedDateFrom": None, "ClosedDateTo": None,
        "Address": None, "ParcelNumber": None, "Description": None, "SearchMainAddress": False,
        "RequestId": None, "ExcludeCases": None, "ContactId": None, "EnableDescriptionSearch": False,
        "HiddenCodeCaseTypeIds": None, "PageNumber": 0, "PageSize": 0,
        "SortBy": None, "SortAscending": False,
    },
    "RequestCriteria": {
        "RequestNumber": None, "RequestTypeId": None, "RequestStatusId": None, "ProjectName": None,
        "EnteredDateFrom": None, "EnteredDateTo": None, "DeadlineDateFrom": None,
        "DeadlineDateTo": None, "CompleteDateFrom": None, "CompleteDateTo": None,
        "Address": None, "ParcelNumber": None, "SearchMainAddress": False,
        "PageNumber": 0, "PageSize": 0, "SortBy": None, "SortAscending": False,
    },
    "BusinessLicenseCriteria": {
        "LicenseNumber": None, "LicenseTypeId": None, "LicenseClassId": None, "LicenseStatusId": None,
        "BusinessStatusId": None, "LicenseYear": None, "ApplicationDateFrom": None,
        "ApplicationDateTo": None, "IssueDateFrom": None, "IssueDateTo": None,
        "ExpirationDateFrom": None, "ExpirationDateTo": None, "SearchMainAddress": False,
        "CompanyTypeId": None, "CompanyName": None, "BusinessTypeId": None, "Description": None,
        "CompanyOpenedDateFrom": None, "CompanyOpenedDateTo": None,
        "CompanyClosedDateFrom": None, "CompanyClosedDateTo": None,
        "LastAuditDateFrom": None, "LastAuditDateTo": None, "ParcelNumber": None,
        "Address": None, "TaxID": None, "DBA": None, "ExcludeCases": None,
        "ContactId": None, "PageNumber": 0, "PageSize": 0, "SortBy": None, "SortAscending": False,
    },
    "ProfessionalLicenseCriteria": {"PageNumber": 0, "PageSize": 0},
    "LicenseCriteria": {"PageNumber": 0, "PageSize": 0},
    "ProjectCriteria": {"PageNumber": 0, "PageSize": 0},
    "PlanSortList": [], "PermitSortList": [], "InspectionSortList": [],
    "CodeCaseSortList": [], "RequestSortList": [], "LicenseSortList": [],
    "ProjectSortList": [], "ExcludeCases": [], "SortOrderList": [],
    "HiddenInspectionTypeIDs": None,
    "PageNumber": 1, "PageSize": 50, "SortBy": "ApplyDate", "SortAscending": False,
}


@dataclass(frozen=True)
class Tenant:
    jurisdiction: str
    msa: str
    county: str
    default_city: str
    api_url: str
    base_url: str
    keywords: tuple[str, ...] = ("",)
    max_pages: int = 60


HENDERSON = Tenant(
    jurisdiction="henderson_nv", msa="las_vegas", county="CLARK", default_city="Henderson",
    api_url="https://hendersonnv-energovweb.tylerhost.net/apps/SelfService/api/energov/search/search",
    base_url="https://hendersonnv-energovweb.tylerhost.net/apps/SelfService",
    keywords=("", "tentative", "rezone", "rezoning", "zone change", "design review", "conditional use",
              "parcel map", "final map", "concept plan", "master plan", "apartment", "multifamily",
              "multi-family", "townhome"))

# CaseType -> stage, first match wins. Anything unmatched is dropped (the allowlist).
STAGE_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"rezon|zoning map amendment|zoning change", re.I), "rezoning"),
    (re.compile(r"planned development|\bpud\b|\bpd\b|\bpad\b|planned unit", re.I), "rezoning"),
    (re.compile(r"specific use|special use|conditional use|\bsup\b|\bslup\b|\bcup\b", re.I), "sup"),
    (re.compile(r"concept plan|general plan", re.I), "plat"),
    (re.compile(r"site plan|site development|development plan", re.I), "site_plan"),
    (re.compile(r"master plan", re.I), "plat"),
    (re.compile(r"tentative map|final map|parcel map", re.I), "plat"),
    (re.compile(r"design review", re.I), "design_review"),
    (re.compile(r"waiver of (?:development )?standards", re.I), "variance"),
    (re.compile(r"re-?plat|preliminary plat|final plat|minor plat|amending plat|\bplat\b|subdivision", re.I), "plat"),
)
# Explicit noise, even when a keyword above would match ("Zoning Verification").
DROP_RE = re.compile(
    r"verification letter|\bzvl\b|alcohol|prequal|business license|license|sign permit|\bsign\b|tree|"
    r"floodplain|\bcip\b|right[- ]of[- ]way|\brow\b|engineering plan review|grading|clearing|driveway|"
    r"utility|pre-?application|pre-?development meeting", re.I)
LIFECYCLE = {
    "approved": "approved", "completed": "approved", "issued": "approved", "recorded": "recorded",
    "final": "approved", "in review": "in_review", "under review": "in_review", "review": "in_review",
    "submitted": "in_review", "pending": "in_review", "active": "in_review", "denied": "terminal",
    "withdrawn": "terminal", "expired": "terminal", "void": "terminal", "cancelled": "terminal",
    "canceled": "terminal", "closed": "terminal", "inactive": "terminal",
}
RAW_KEYS = ("CaseId", "CaseNumber", "CaseType", "CaseWorkclass", "CaseStatus", "ApplyDate",
            "ProjectName", "Description", "MainParcel", "AddressDisplay")


def stage_for(case_type: str | None) -> str | None:
    ct = case_type or ""
    if DROP_RE.search(ct):
        return None
    for rx, stage in STAGE_RULES:
        if rx.search(ct):
            return stage
    return None


def lifecycle(status: str | None) -> str:
    s = (status or "").lower()
    for k, v in LIFECYCLE.items():
        if k in s:
            return v
    return "unknown"


def iso(s) -> str | None:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(s or ""))
    return m.group(1) if m else None


def address(case: dict, default_city: str) -> tuple[str | None, str]:
    a = case.get("Address") or {}
    if isinstance(a, dict) and a:
        parts = [(a.get(k) or "").strip() for k in ("AddressLine1", "AddressLine2", "AddressLine3")]
        street = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip() or None
        return street, (a.get("City") or "").strip() or default_city
    disp = (case.get("AddressDisplay") or "").strip()
    return (disp.split(",")[0].strip() or None) if disp else None, default_city


def search_body(keyword: str, page: int, page_size: int) -> dict:
    body = json.loads(json.dumps(SEARCH_BODY_TEMPLATE))
    body.update(SearchModule=1, FilterModule=3, Keyword=keyword, PageNumber=page, PageSize=page_size,
                SortBy="ApplyDate", SortAscending=False)
    return body


class IncompleteSweep(RuntimeError):
    """A page failed mid-sweep: the remaining pages are unknown, not empty."""


def sweep_plans(session, tenant: Tenant, *, page_size: int = 50) -> Iterator[dict]:
    seen: set[str] = set()
    for kw in tenant.keywords:
        total_pages = None
        for pn in range(1, tenant.max_pages + 1):
            r = session.post(tenant.api_url, json=search_body(kw, pn, page_size), timeout=45)
            if r.status_code != 200 or "json" not in (r.headers.get("content-type") or ""):
                raise IncompleteSweep(f"{tenant.jurisdiction} kw={kw!r} page {pn}: HTTP {r.status_code}")
            result = (r.json() or {}).get("Result") or {}
            items = result.get("EntityResults") or []
            total_pages = total_pages or result.get("TotalPages")
            for it in items:
                cid = it.get("CaseId")
                if cid and cid not in seen:
                    seen.add(cid)
                    yield it
            if len(items) < page_size or (total_pages and pn >= total_pages):
                break


def to_row(case: dict, tenant: Tenant) -> dict | None:
    stage = stage_for(case.get("CaseType"))
    if not stage:
        return None
    name = strip_or_none(case.get("ProjectName"))
    street, city = address(case, tenant.default_city)
    return {
        "msa": tenant.msa, "jurisdiction": tenant.jurisdiction, "source_type": "tyler_energov_plan",
        "case_number": str(case.get("CaseNumber") or case.get("CaseId")),
        "case_type_raw": case.get("CaseType"), "stage": stage, "project_name": name,
        "status_raw": case.get("CaseStatus"), "lifecycle_status": lifecycle(case.get("CaseStatus")),
        "application_date": iso(case.get("ApplyDate")), "latest_action_date": iso(case.get("ApplyDate")),
        "dwelling_type": classify_dwelling(name, case.get("CaseType"), case.get("CaseWorkclass"),
                                           case.get("Description")),
        "address": street, "city": city, "county": tenant.county, "latitude": None, "longitude": None,
        "link": f"{tenant.base_url}#/plan/{case['CaseId']}" if case.get("CaseId") else None,
        "raw_json": {k: case[k] for k in RAW_KEYS if case.get(k) not in (None, "", [], {})},
    }


def run(store, tenant: Tenant = HENDERSON, *, session=None, page_size: int = 50,
        limit: int | None = None) -> ReaderResult:
    session = session or http.session(HEADERS)
    rows, scanned = [], 0
    for case in sweep_plans(session, tenant, page_size=page_size):
        scanned += 1
        row = to_row(case, tenant)
        if row:
            rows.append(row)
        if limit and len(rows) >= limit:
            break
    n = upsert_cases(store, rows)
    return ReaderResult(tenant.jurisdiction, scanned, n, notes={"kept": len(rows)})
