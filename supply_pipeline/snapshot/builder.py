"""Aggregate the store into one JSON file, the shape of the public supply-database page.

Every number is computed from the tables at build time, so the page cannot claim a figure
the database does not hold, and nothing on it is typed by hand.

What goes out:
  headline         metros, tracked feeds, source records, fresh feeds, entitlement cases,
                   active multifamily/townhome permit-layer projects and their units
  methods          feeds grouped by HOW they are retrieved (registry access_method), with
                   one example source per method (EXAMPLES)
  markets          per-metro coverage: feeds by stage and method, records, freshness
  freshness / entitlement_types / permit_products    composition rollups
  samples          a stable pseudo-random draw of named projects per metro

"Tracked" = registry row active AND status <> 'retired'.

REFUSES (Refusal) so a new feed cannot reach the page mis-described:
  * a tracked source with NULL access_method;
  * a tracked source whose msa is not in METROS;
  * an access_method missing from METHODS;
  * an EXAMPLES id that is not tracked, or is tagged with another method.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

# code -> (display name, registry msa, project-layer msa slug)
METROS = {
    "ATL": ("Atlanta, GA", "Atlanta", "atlanta"),
    "AUS": ("Austin, TX", "Austin", "austin"),
    "CLT": ("Charlotte, NC", "Charlotte", "charlotte"),
    "HOU": ("Houston, TX", "Houston", "houston"),
    "HSV": ("Huntsville, AL", "Huntsville", "huntsville"),
    "LAS": ("Las Vegas, NV", "Las Vegas", "las_vegas"),
    "NSH": ("Nashville, TN", "Nashville", "nashville"),
    "PHX": ("Phoenix, AZ", "Phoenix", "phoenix"),
    "TPA": ("Tampa, FL", "Tampa", "tampa"),
}
BY_REGISTRY = {v[1]: k for k, v in METROS.items()}
BY_SLUG = {v[2]: k for k, v in METROS.items()}

# Order = display order. The note is one line on what the method costs to keep running.
METHODS = {
    "arcgis": ("GIS map service",
               "A county or city ArcGIS layer queried like an API. Structured and cheap; "
               "breaks loudly when a layer is renamed."),
    "portal_json": ("Permit-portal JSON",
                    "The JSON a permit or agenda portal feeds its own search page. One reader "
                    "per vendor covers every jurisdiction on that software."),
    "html_scrape": ("HTML page scrape",
                    "Server-rendered search pages, parsed field by field. The most layout-"
                    "sensitive of the structured methods."),
    "pdf": ("PDF documents",
            "Agendas, weekly lists and public reports. Text is extracted, and a language "
            "model reads what rules cannot."),
    "browser": ("Browser automation",
                "Portals that only work in a real browser, driven headless. Slowest and most "
                "fragile, so it is the last resort."),
    "open_data_api": ("Open-data API",
                      "A published open-data API with documented fields. The easiest feeds "
                      "to keep healthy."),
    "spreadsheet": ("Spreadsheet download",
                    "An xlsx or csv file published on a schedule. One request, then a "
                    "column mapping that must survive format changes."),
    "derived": ("Derived view",
                "Not a download: a filtered view over a table another feed already loads."),
}

# One real source per method, by registry id. Each has a reader in supply_pipeline.readers.
EXAMPLES = {
    "arcgis": 36,          # Nashville: Davidson building permits issued
    "portal_json": 195,    # Las Vegas: Henderson entitlement plans (Tyler EnerGov)
    "html_scrape": 18,     # Houston: TCEQ construction stormwater NOIs
    "pdf": 7,              # Phoenix: ADRE subdivision public reports
    "browser": 193,        # Las Vegas: Clark County Accela planning cases
    "open_data_api": 14,   # Austin: City of Austin subdivision review cases
    "spreadsheet": 24,     # Charlotte: NC DEQ NCG01 stormwater NOIs
    "derived": 177,        # Nashville: Davidson Metro planning entitlement arm
}
EXAMPLE_WHAT = {
    "arcgis": "Davidson County building permits issued, from Metro Nashville's ArcGIS hub",
    "portal_json": "Henderson entitlement plans, from the city's Tyler EnerGov portal",
    "html_scrape": "Texas construction stormwater notices of intent, from TCEQ's search pages",
    "pdf": "Arizona subdivision public reports: a CSV index plus one PDF per report",
    "browser": "Clark County planning cases, from its Accela citizen portal",
    "open_data_api": "City of Austin subdivision review cases, from its Socrata open-data API",
    "spreadsheet": "North Carolina construction stormwater permits, one xlsx from NC DEQ",
    "derived": "Nashville planning cases filtered to rezonings, plats and PUDs",
}

ENT_TYPES = {
    "rezoning": "Rezoning", "plat": "Plat", "dev_project": "Development project",
    "site_plan": "Site plan", "sup": "Special use permit", "pre_application": "Pre-application",
    "variance": "Variance", "design_review": "Design review",
}
PRODUCTS = {
    "apartment_rental": "Apartments", "townhome": "Townhomes", "condo": "Condos",
    "duplex_etc": "Duplex to fourplex", "duplex": "Duplex to fourplex",
}
PERMIT_STAGES = {"planned": "Planned", "permitted_pending": "Permit pending",
                 "permitted": "Permitted", "unknown": "Stage unknown"}
DWELLING = {"single_family": "SFD", "townhome": "TH", "multifamily": "MF", "mixed": "Mixed"}
CANON_STAGE = {
    "initial_only": "Filed", "noi_active": "Site work", "active_reissue": "Site work",
    "vertical": "Vertical", "plat_in_review": "Plat in review", "plat_recorded": "Plat recorded",
    "complete": "Complete", "updated": "Filed",
}
ENT_STATUS = {
    "approved": "Approved", "in_review": "In review", "under_review": "In review",
    "permitted": "Permitted", "delivered": "Delivered", "built": "Built",
    "recorded": "Recorded", "unknown": None,
}
RECORD = {"lihtc_app": "LIHTC application", "prelim_plat": "Preliminary plat",
          "final_plat": "Final plat", "final_site_plan": "Final site plan",
          "slup": "Special land use permit", "gpa": "General plan amendment"}
# Canonical rows whose "name" is a permit description rather than a project name.
DESCRIPTION_NAME = (r"(new construction|expedited review|^construct |^eplan|^new [0-9]|"
                    r"multi-?family (bldg|building|complex))")
SFD_STAGE = {"planned": "Planned", "permitted": "Permitted", "permitted_pending": "Permit pending",
             "delivered": "Delivered", "unknown": None}
CANONICAL_METROS = ("ATL", "AUS", "HOU", "PHX")   # metros with a cross-source canonical layer
SAMPLE_EXCLUDE_JURISDICTIONS: tuple[str, ...] = ()
FRESH_DAYS = 8
SAMPLE_SALT = "supply-sample-v1"


class Refusal(Exception):
    """The registry does not support an honest export."""


def jsonable(v):
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f.is_integer() else round(f, 2)
    if isinstance(v, datetime | date):
        return v.isoformat()
    return v


def rows(store, sql: str, params=None) -> list[dict]:
    return [{k: jsonable(v) for k, v in r.items()} for r in store.rows(sql, params)]


def validate_registry(tracked: list[dict]) -> None:
    untagged = [f"{r['id']} {r['msa']} — {r['source_label']}" for r in tracked
                if r["access_method"] is None]
    if untagged:
        raise Refusal("tracked sources with NULL access_method: " + "; ".join(untagged))
    unknown = sorted({r["msa"] for r in tracked} - set(BY_REGISTRY))
    if unknown:
        raise Refusal(f"tracked sources in metros missing from METROS: {unknown}")
    bad_method = sorted({r["access_method"] for r in tracked} - set(METHODS))
    if bad_method:
        raise Refusal(f"access_method values missing from METHODS: {bad_method}")
    by_id = {r["id"]: r for r in tracked}
    for method, sid in EXAMPLES.items():
        r = by_id.get(sid)
        if r is None:
            raise Refusal(f"EXAMPLES[{method!r}] = {sid} is not a tracked source")
        if r["access_method"] != method:
            raise Refusal(f"EXAMPLES[{method!r}] = {sid} is tagged {r['access_method']!r}")


def place(r: dict) -> str | None:
    """A readable jurisdiction: city, else county."""
    city = (r.get("city") or "").strip()
    county = (r.get("county") or "").strip()
    if city:
        return city.title()
    if county:
        c = county.title()
        return c if "county" in c.lower() or "parish" in c.lower() else c + " County"
    return None


def feed_age(r: dict, today: date) -> int | None:
    """Days since the feed last showed life: the later of its last load and its newest
    record date. Several feeds have no load timestamp, so load time alone would call a
    feed stale that loaded yesterday's records."""
    seen = [datetime.fromisoformat(r["last_ingested"]).date()] if r["last_ingested"] else []
    if r["latest_data"] and date.fromisoformat(r["latest_data"]) <= today:
        seen.append(date.fromisoformat(r["latest_data"]))
    return (today - max(seen)).days if seen else None


def build(store, *, as_of: date, sample_per_market: int = 15,
          generated_at: datetime | None = None) -> dict:
    tracked = rows(store, """
        select s.id, s.msa, s.source_label, s.access_method, s.stage,
               c.row_count, c.last_ingested, c.latest_data
          from registry.pipeline_sources s
          left join registry.pipeline_coverage c
            on c.msa = s.msa and c.source_label = s.source_label
         where s.active and s.status <> 'retired'
         order by s.id""")
    validate_registry(tracked)
    refreshed = rows(store, "select max(refreshed_at) as t from registry.pipeline_coverage")[0]["t"]
    ages = {r["id"]: feed_age(r, as_of) for r in tracked}

    # ---- methods ----
    by_id = {r["id"]: r for r in tracked}
    methods = []
    for m, (label, note) in METHODS.items():
        feeds = [r for r in tracked if r["access_method"] == m]
        ex = by_id[EXAMPLES[m]]
        methods.append({
            "method": m, "label": label, "note": note,
            "feeds": len(feeds),
            "metros": len({r["msa"] for r in feeds}),
            "records": sum(r["row_count"] or 0 for r in feeds),
            "example": {"market": BY_REGISTRY[ex["msa"]], "what": EXAMPLE_WHAT[m],
                        "records": ex["row_count"] or 0},
        })

    # ---- per-metro project layers ----
    ent = {BY_SLUG[r["msa"]]: r for r in rows(store, """
        select msa, count(*) as cases, count(*) filter (where units > 0) as with_units
          from county_permits.v_entitlement_served group by msa""") if r["msa"] in BY_SLUG}
    mf = {BY_SLUG[r["msa"]]: r for r in rows(store, """
        select msa, count(*) as projects,
               coalesce(sum(max_units_signal) filter (where max_units_signal between 1 and 2000), 0) as units
          from layers.mf_projects
         where is_active_supply and is_cluster_primary group by msa""") if r["msa"] in BY_SLUG}

    markets = []
    for code, (_name, reg, _slug) in METROS.items():
        feeds = [r for r in tracked if r["msa"] == reg]
        markets.append({
            "market": code,
            "feeds": len(feeds),
            "early": sum(r["stage"] == "early" for r in feeds),
            "entitlement": sum(r["stage"] == "entitlement" for r in feeds),
            "late": sum(r["stage"] == "late" for r in feeds),
            "records": sum(r["row_count"] or 0 for r in feeds),
            "fresh": sum(ages[r["id"]] is not None and ages[r["id"]] <= FRESH_DAYS for r in feeds),
            "methods": {m: sum(r["access_method"] == m for r in feeds) for m in METHODS},
            "entitlement_cases": ent.get(code, {}).get("cases", 0),
            "mf_projects": mf.get(code, {}).get("projects", 0),
            "mf_units": mf.get(code, {}).get("units", 0),
        })
    markets.sort(key=lambda m: -m["feeds"])

    # ---- freshness buckets by stage ----
    stages = ("early", "entitlement", "late")
    buckets = [("Within a day", 0, 1), ("2–8 days", 2, 8), ("9–30 days", 9, 30),
               ("Over 30 days", 31, 10**6)]
    freshness = []
    for label, lo, hi in buckets:
        sel = [r for r in tracked if (a := ages[r["id"]]) is not None and lo <= a <= hi]
        freshness.append({"bucket": label, "feeds": len(sel),
                          **{s: sum(r["stage"] == s for r in sel) for s in stages}})
    no_ts = [r for r in tracked if ages[r["id"]] is None]
    if no_ts:
        freshness.append({"bucket": "No date to judge by", "feeds": len(no_ts),
                          **{s: sum(r["stage"] == s for r in no_ts) for s in stages}})

    # ---- composition ----
    ent_types = rows(store, """
        select stage, count(*) as cases, count(*) filter (where units > 0) as with_units
          from county_permits.v_entitlement_served group by stage order by 2 desc, 1""")
    top = [dict(t, label=ENT_TYPES[t["stage"]]) for t in ent_types if t["stage"] in ENT_TYPES]
    rest = [t for t in ent_types if t["stage"] not in ENT_TYPES]
    top.append({"stage": "other", "label": "Other filing types",
                "cases": sum(t["cases"] for t in rest),
                "with_units": sum(t["with_units"] for t in rest)})

    prod_rows = rows(store, """
        select project_subtype, best_lifecycle_stage, count(*) as n,
               coalesce(sum(max_units_signal) filter (where max_units_signal between 1 and 2000), 0) as units
          from layers.mf_projects
         where is_active_supply and is_cluster_primary group by 1, 2 order by 1, 2""")
    products: dict[str, dict] = {}
    for r in prod_rows:
        label = PRODUCTS.get(r["project_subtype"], "Other / unclassified")
        p = products.setdefault(label, {"product": label, "projects": 0, "units": 0,
                                        **{s: 0 for s in PERMIT_STAGES}})
        p["projects"] += r["n"]
        p["units"] += r["units"]
        stage = r["best_lifecycle_stage"] if r["best_lifecycle_stage"] in PERMIT_STAGES else "unknown"
        p[stage] += r["n"]
    permit_products = sorted(products.values(),
                             key=lambda p: (p["product"] == "Other / unclassified", -p["projects"]))

    samples = {code: sample_market(store, code, sample_per_market, as_of) for code in METROS}

    return {
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        "coverage_refreshed_at": refreshed,
        "headline": {
            "metros": len(METROS),
            "tracked_feeds": len(tracked),
            "source_records": sum(r["row_count"] or 0 for r in tracked),
            "fresh_feeds": sum(m["fresh"] for m in markets),
            "fresh_days": FRESH_DAYS,
            "entitlement_cases": sum(m["entitlement_cases"] for m in markets),
            "mf_projects": sum(m["mf_projects"] for m in markets),
            "mf_units": sum(m["mf_units"] for m in markets),
        },
        "metros": {k: v[0] for k, v in METROS.items()},
        "methods": methods,
        "markets": markets,
        "freshness": freshness,
        "entitlement_types": top,
        "permit_stages": PERMIT_STAGES,
        "permit_products": permit_products,
        "sample_per_market": sample_per_market,
        "samples": samples,
    }


def sample_market(store, code: str, n: int, as_of: date) -> list[dict]:
    """A stable pseudo-random draw (md5 of the name plus a salt) of named projects with a
    unit count, from the best layer each metro has: the cross-source canonical layer where
    it exists, Las Vegas's tract rollups, and entitlement cases elsewhere."""
    slug = METROS[code][2]
    if code in CANONICAL_METROS:
        raw = rows(store, """
            select project_name, city, county, dwelling_type, lifecycle_status,
                   units_measured, units_estimated, source_count
              from layers.pipeline_unified
             where metro = %s and project_name is not null
               and coalesce(units_measured, units_estimated) between 10 and 2000
               and latest_signal_date >= %s::date - 365
               and lifecycle_status <> 'withdrawn_or_admin'
               and project_name !~* %s
             order by md5(lower(project_name) || %s)
             limit %s""", (slug, as_of, DESCRIPTION_NAME, SAMPLE_SALT, n * 2))
        seen, deduped = set(), []
        for r in raw:   # one row per name: two phases can share a canonical name
            if r["project_name"].lower() not in seen:
                seen.add(r["project_name"].lower())
                deduped.append(r)
        return [{
            "name": r["project_name"], "place": place(r),
            "product": DWELLING.get(r["dwelling_type"]),
            "stage": CANON_STAGE.get(r["lifecycle_status"]),
            "units": r["units_measured"] or r["units_estimated"],
            "estimated": r["units_measured"] is None,
            "record": f"{r['source_count']} linked filings" if (r["source_count"] or 0) > 1 else "1 filing",
        } for r in deduped[:n]]
    if code == "LAS":
        raw = rows(store, """
            select project_name, city, county, project_subtype, best_lifecycle_stage, max_units_signal
              from layers.sfd_projects
             where msa = %s and project_name is not null and max_units_signal between 10 and 2000
             order by md5(mv_row_id::text || %s)
             limit %s""", (slug, SAMPLE_SALT, n))
        return [{
            "name": r["project_name"], "place": place(r),
            "product": "TH" if r["project_subtype"] == "townhome" else "SFD",
            "stage": SFD_STAGE.get(r["best_lifecycle_stage"]),
            "units": r["max_units_signal"], "estimated": False,
            "record": "Building permits, rolled up by tract",
        } for r in raw]
    raw = rows(store, """
        select * from (
            select distinct on (lower(project_name))
                   project_name, county, jurisdiction, stage, lifecycle_status, dwelling_type, units,
                   md5(coalesce(case_number, '') || project_name || %s) as k
              from county_permits.v_entitlement_served
             where msa = %s and project_name is not null and units between 10 and 2000
               and lifecycle_status not in ('denied', 'withdrawn', 'terminal', 'closed')
               and coalesce(latest_action_date, submitted_date) between %s::date - 365 and %s::date
               and jurisdiction <> all(%s)
             order by lower(project_name), coalesce(latest_action_date, submitted_date) desc
        ) d order by k limit %s""",
        (SAMPLE_SALT, slug, as_of, as_of, list(SAMPLE_EXCLUDE_JURISDICTIONS), n))
    return [{
        "name": r["project_name"], "place": place(r),
        "product": DWELLING.get(r["dwelling_type"]),
        "stage": ENT_STATUS.get(r["lifecycle_status"]),
        "units": r["units"], "estimated": False,
        "record": ENT_TYPES.get(r["stage"]) or RECORD.get(r["stage"])
                  or (r["stage"] or "filing").replace("_", " ").capitalize(),
    } for r in raw]
