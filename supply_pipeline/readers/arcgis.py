"""Method: GIS map service. A county or city ArcGIS FeatureServer layer queried like an API.

One generic reader; a layer is configuration (URL, key, field mapping). Two Metro Nashville
layers ship: building permits issued (the example feed) and planning cases (which the
derived view in schema/080_views.sql narrows to entitlements).

Paging: ArcGIS caps each response at the layer's maxRecordCount. A short page usually
means the end, but some servers serve short pages mid-stream and flag it with
`exceededTransferLimit`; the reader keeps paging while that flag is set.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .. import http
from .base import ReaderResult

log = logging.getLogger(__name__)

METHOD = "arcgis"
EXAMPLE_FEED = 36   # Nashville: Davidson building permits issued


def epoch_ms_to_date(v) -> str | None:
    if v is None or v == "":
        return None
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=UTC).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def centroid(geom: dict | None) -> tuple[float | None, float | None]:
    """(lat, lon) of a GeoJSON point or the vertex mean of a (multi)polygon."""
    if not geom or not geom.get("coordinates"):
        return None, None
    gtype, coords = geom.get("type"), geom["coordinates"]
    if gtype == "Point":
        return coords[1], coords[0]
    if gtype == "MultiPoint":
        return coords[0][1], coords[0][0]
    rings = coords if gtype == "Polygon" else [r for poly in coords for r in poly] if gtype == "MultiPolygon" else []
    pts = [pt for ring in rings for pt in ring]
    if not pts:
        return None, None
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


@dataclass(frozen=True)
class Layer:
    name: str
    url: str
    table: str
    key: str
    order_by: str
    since_field: str
    transform: Callable[[dict], dict | None]
    page_size: int = 1000
    geojson: bool = False


# --------------------------------------------------------------------------- Nashville
def permit_row(feat: dict) -> dict | None:
    a = feat.get("attributes") or {}
    pno = a.get("Permit__")
    if pno in (None, ""):
        return None
    return {
        "permit_number": str(pno).strip(),
        "permit_type_description": a.get("Permit_Type_Description"),
        "permit_subtype_description": a.get("Permit_Subtype_Description"),
        "parcel": a.get("Parcel"),
        "date_entered": epoch_ms_to_date(a.get("Date_Entered")),
        "date_issued": epoch_ms_to_date(a.get("Date_Issued")),
        "const_cost": a.get("Const_Cost"),
        "address": a.get("Address"),
        "city": a.get("City"),
        "state": a.get("State"),
        "subdivision_lot": a.get("Subdivision_Lot"),
        "per_ty": a.get("Per_Ty"),
        "per_subty": a.get("Per_SubTy"),
        "purpose": a.get("Purpose"),
        "council_district": a.get("Council_Dist"),
        "census_tract": a.get("Census_Tract"),
        "lon": a.get("Lon"),
        "lat": a.get("Lat"),
        "zip": a.get("ZIP"),
        "source_object_id": a.get("ObjectId"),
    }


_REQUESTED_BY = re.compile(r",?\s*requested by\b.*$", re.I | re.S)


def redact_caption(caption: str | None) -> str | None:
    """Captions end "..., requested by <applicant>, applicant; <owner>, owner." and the
    applicant and owner are often private individuals. Keep the description, drop the clause."""
    if not caption:
        return caption
    out = _REQUESTED_BY.sub("", caption).rstrip(" ,;")
    return (out + ".") if out and not out.endswith(".") else out


def planning_row(feat: dict) -> dict | None:
    """Planning case. Applicant / reviewer contact fields are deliberately not read, and
    the caption's requested-by clause (applicant and owner names) is removed."""
    p = feat.get("properties") or {}
    oid = p.get("CA_OBJECT_ID")
    if oid in (None, ""):
        return None
    lat, lon = centroid(feat.get("geometry"))
    return {
        "ca_object_id": int(oid),
        "application_type": p.get("PERTYPE"),
        "case_type_description": p.get("CASE_TYPE_DESC"),
        "sub_type_description": p.get("SUB_TYPE_DESC"),
        "date_accepted": epoch_ms_to_date(p.get("DATE_ACCEPTED")),
        "mpc_case_number": p.get("MPCNUM"),
        "ordinance_number": p.get("BILLNUM"),
        "project_name": p.get("PROJECT_DESC"),
        "location": p.get("LOCATION_DESC"),
        "mpc_meeting_date": epoch_ms_to_date(p.get("MPC_DATE")),
        "council_3rd_reading_date": epoch_ms_to_date(p.get("READ3_DATE")),
        "council_3rd_reading_action": p.get("READ3"),
        "council_district": p.get("CD"),
        "case_caption": redact_caption(p.get("CAPTION")),
        "status": p.get("PSTAT"),
        "council_2nd_reading_date": epoch_ms_to_date(p.get("READ2_DATE")),
        "mpc_vote": p.get("MPC_VOTE"),
        "mpc_action": p.get("MPC_ACTION_DESC"),
        "council_2nd_reading_action": p.get("READ2"),
        "council_1st_reading_date": epoch_ms_to_date(p.get("READ1_DATE")),
        "council_1st_reading_action": p.get("READ1"),
        "parcels": p.get("Parcels"),
        "acreage": p.get("Acreage"),
        "existing_zoning": p.get("ExistingZoning"),
        "new_zoning": p.get("NewZoning"),
        "planned_unit_development": p.get("PlannedUnitDevelopment"),
        "policy": p.get("Policy"),
        "community_plan": p.get("CommunityPlan"),
        "lon": lon,
        "lat": lat,
        "source_object_id": p.get("OBJECTID"),
    }


_HUB = "https://services2.arcgis.com/HdTo6HJqh92wn4D8/arcgis/rest/services"
NASHVILLE_PERMITS = Layer(
    name="nashville_building_permits", url=f"{_HUB}/Building_Permits_Issued_2/FeatureServer/0",
    table="nashville.building_permits_issued", key="permit_number", order_by="ObjectId ASC",
    since_field="Date_Issued", transform=permit_row, page_size=1000)
NASHVILLE_PLANNING = Layer(
    name="nashville_planning_cases", url=f"{_HUB}/Development_Tracker_Cases_view/FeatureServer/0",
    table="nashville.planning_dev_cases", key="ca_object_id", order_by="OBJECTID ASC",
    since_field="DATE_ACCEPTED", transform=planning_row, page_size=2000, geojson=True)
LAYERS = {lyr.name: lyr for lyr in (NASHVILLE_PERMITS, NASHVILLE_PLANNING)}


# --------------------------------------------------------------------------- fetch
def query_page(session, layer: Layer, where: str, offset: int, count: int) -> dict:
    params = {
        "where": where, "outFields": "*", "f": "geojson" if layer.geojson else "json",
        "returnGeometry": "true" if layer.geojson else "false",
        "resultOffset": offset, "resultRecordCount": count, "orderByFields": layer.order_by,
    }
    if layer.geojson:
        params["outSR"] = 4326
    r = session.get(f"{layer.url}/query", params=params, timeout=180)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"{layer.name}: ArcGIS error {data['error']}")
    return data


def fetch_all(session, layer: Layer, where: str = "1=1", limit: int | None = None,
              max_pages: int = 5000) -> list[dict]:
    feats: list[dict] = []
    offset = 0
    for _ in range(max_pages):
        count = min(layer.page_size, limit) if limit else layer.page_size
        data = query_page(session, layer, where, offset, count)
        page = data.get("features") or []
        feats.extend(page)
        more = bool(data.get("exceededTransferLimit")
                    or (data.get("properties") or {}).get("exceededTransferLimit"))
        log.info("%s: page at offset %d -> %d (more=%s)", layer.name, offset, len(page), more)
        if limit and len(feats) >= limit:
            return feats[:limit]
        if not page or (len(page) < count and not more):
            return feats
        offset += len(page)
    raise RuntimeError(f"{layer.name}: still paging after {max_pages} pages; refusing to loop forever")


def where_since(layer: Layer, since: str | None) -> str:
    if not since:
        return "1=1"
    dt = datetime.fromisoformat(since).replace(tzinfo=UTC)
    return f"{layer.since_field} >= {int(dt.timestamp() * 1000)}"


def run(store, layer: Layer = NASHVILLE_PERMITS, *, since: str | None = None,
        limit: int | None = None, session=None) -> ReaderResult:
    session = session or http.session()
    feats = fetch_all(session, layer, where_since(layer, since), limit=limit)
    rows = [r for r in (layer.transform(f) for f in feats) if r is not None]
    n = store.upsert(layer.table, rows, key=(layer.key,))
    return ReaderResult(layer.name, len(feats), n)
