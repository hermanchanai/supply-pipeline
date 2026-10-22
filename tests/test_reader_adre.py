"""PDF reader (ADRE public reports): CSV index, the token-then-POST download, trimming to
8 pages, and the extraction row built from a recorded model output."""
from __future__ import annotations

import io
import json

import pytest

from supply_pipeline.readers import adre
from tests.fakes import FakeResponse, RecordedSession, fixture_bytes, html_response


def make_pdf(pages: int) -> bytes:
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


RECORDED = json.loads(fixture_bytes("adre/recorded_extraction_DM26-062884.json"))


class RecordedExtractor:
    model = "claude-haiku-4-5"

    def __init__(self):
        self.seen = []

    def __call__(self, pdf: bytes) -> dict:
        self.seen.append(pdf)
        return {**RECORDED, "developer_address": "should not be stored"}


def test_csv_index_parses_and_dedupes():
    rows = adre.parse_csv(fixture_bytes("adre/public_reports_list.csv").decode("utf-8"))
    assert len(rows) == 5                                  # 6 lines, one duplicate registration
    r = next(x for x in rows if x["registration_number"] == "DM26-062884")
    assert (r["parsed_county"], r["date_issued"], r["developer_name"]) == ("Maricopa", "2026-10-15", "ASHTON WOODS ARIZONA LLC")
    assert "developer_address_1" not in r


def test_reg_to_id():
    assert adre.reg_to_id("DM26-062672") == 62672
    with pytest.raises(ValueError):
        adre.reg_to_id("62672")


def test_trim_keeps_the_first_eight_pages():
    trimmed, n = adre.trim_pdf(make_pdf(12))
    from pypdf import PdfReader
    assert n == 8 and len(PdfReader(io.BytesIO(trimmed)).pages) == 8


def pdf_session(pdf: bytes) -> RecordedSession:
    s = RecordedSession()
    s.add("GET", "ViewDevelopment/62884", html_response("adre/view_development_62884.html"))
    s.add("POST", "DownloadPublicReport", FakeResponse(pdf, content_type="application/pdf"))
    return s


def test_download_sends_the_page_token():
    s = pdf_session(make_pdf(1))
    assert adre.fetch_pdf(s, "DM26-062884").startswith(b"%PDF")
    assert s.calls[1]["data"] == {"__RequestVerificationToken": "example-anti-forgery-token", "id": "62884"}


def test_html_instead_of_a_pdf_raises():
    s = RecordedSession()
    s.add("GET", "ViewDevelopment", html_response("adre/view_development_62884.html"))
    s.add("POST", "DownloadPublicReport", FakeResponse(b"<html>no report</html>", content_type="text/html"))
    with pytest.raises(RuntimeError, match="no report PDF"):
        adre.fetch_pdf(s, "DM26-062884")


def test_run_extracts_into_the_store(store, tmp_path):
    csv_text = fixture_bytes("adre/public_reports_list.csv").decode("utf-8")
    only = "\n".join(line for i, line in enumerate(csv_text.splitlines()) if i == 0 or "DM26-062884" in line)
    ex = RecordedExtractor()
    res = adre.run(store, session=pdf_session(make_pdf(10)), extractor=ex, csv_text=only,
                   pdf_dir=tmp_path, delay=0)
    assert res.notes == {"extracted": 1, "failed": []}
    r = store.rows("select * from azre.public_reports_extracted")[0]
    assert r["total_lots"] == RECORDED["total_lots"] and r["pdf_pages"] == 8
    assert "developer_address" not in r["raw_extraction_json"]
    assert (tmp_path / "DM26-062884.pdf").exists()
    # a second run finds nothing left to extract
    res2 = adre.run(store, session=pdf_session(make_pdf(10)), extractor=ex, csv_text=only,
                    pdf_dir=tmp_path, delay=0)
    assert res2.notes["extracted"] == 0 and len(ex.seen) == 1
