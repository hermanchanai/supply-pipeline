"""One reader per collection method. Each module exposes `METHOD`, `EXAMPLE_FEED` (the
registry id of the feed it reproduces) and `run(store, ...) -> ReaderResult`."""
from __future__ import annotations

from importlib import import_module

READERS = {
    "arcgis": "supply_pipeline.readers.arcgis",
    "portal_json": "supply_pipeline.readers.energov",
    "html_scrape": "supply_pipeline.readers.tceq",
    "pdf": "supply_pipeline.readers.adre",
    "browser": "supply_pipeline.readers.accela",
    "open_data_api": "supply_pipeline.readers.socrata",
    "spreadsheet": "supply_pipeline.readers.ncdeq",
    "derived": "supply_pipeline.readers.derived",
}


def reader(method: str):
    return import_module(READERS[method])
