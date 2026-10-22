"""Spreadsheet reader (NC DEQ): header-aware mapping on the real header row and sample
rows from the published xlsx, rebuilt into a small workbook at test time."""
from __future__ import annotations

import io
import json
import re
from datetime import datetime

import openpyxl
import pytest

from supply_pipeline.readers import ncdeq
from tests.fakes import fixture_bytes

FIX = json.loads(fixture_bytes("ncdeq/ncg_cocs_sample.json"))


def _cell(v):
    """The fixture stores dates as ISO text; the published workbook holds real dates."""
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", v):
        return datetime.fromisoformat(v)
    return v


def workbook(header, rows, sheet=FIX["sheet"], decoy=True) -> bytes:
    wb = openpyxl.Workbook()
    if decoy:                         # the data sheet is found by its header, not its position
        wb.active.title = "readme"
        wb.active.append(["This workbook lists certificates of coverage."])
        ws = wb.create_sheet(sheet)
    else:
        ws = wb.active
        ws.title = sheet
    ws.append(header)
    for r in rows:
        ws.append([_cell(v) for v in r])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_ncg01_rows_load_and_ncg25_is_excluded(store):
    res = ncdeq.run(store, xlsx=workbook(FIX["header"], FIX["rows"]), snapshot_date="2026-10-21")
    assert res.upserted == 3 and res.notes["excluded"] == {"NCG250000": 1}
    r = store.rows("select * from ncdeq.noi_submissions where permit_number = 'NCC190431'")[0]
    assert (r["county"], r["project_name"], r["effective_date"].isoformat()) == \
        ("Mecklenburg", "Walden Single Family Phase 5 & 7", "2024-04-01")


def test_columns_found_by_header_even_when_moved():
    header = list(FIX["header"])
    rows = [list(r) for r in FIX["rows"]]
    header = ["(Do Not Modify) Row Id"] + header           # a prepended column
    rows = [["x"] + r for r in rows]
    parsed, _ = ncdeq.parse(workbook(header, rows), "2026-10-21")
    assert parsed[0]["permit_number"] == "NCC190048"


def test_a_missing_header_raises_with_the_column_name():
    header = [h for h in FIX["header"] if not str(h).startswith("Primary Permittee")]
    with pytest.raises(ncdeq.HeaderDrift, match="primary_permittee"):
        ncdeq.parse(workbook(header, []), "2026-10-21")


def test_excel_serial_dates():
    assert ncdeq.excel_date(45383) == "2024-04-01"
    assert ncdeq.excel_date(None) is None
