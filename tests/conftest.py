from __future__ import annotations

import pytest

from supply_pipeline.store import PgStore


@pytest.fixture(scope="session")
def _server_store(tmp_path_factory):
    store = PgStore.local(tmp_path_factory.mktemp("pgdata"), database="supply_test")
    yield store
    store.close()


@pytest.fixture
def store(_server_store):
    """A clean schema for every test (drop + re-apply takes well under a second)."""
    _server_store.reset()
    _server_store.apply_schema()
    return _server_store
