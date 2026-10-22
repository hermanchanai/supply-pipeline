"""Storage behind one small interface.

Production writes through database functions on a hosted Postgres. This repo keeps the
same SQL but runs it on a local Postgres started by `pgserver` (a pip-installable
Postgres binary), so every reader, the derived view and the snapshot builder run against a
real Postgres without a server to set up.

    store = PgStore.local(Path(".pgdata"))   # starts (or reuses) a local server
    store.apply_schema()
    store.upsert("nashville.building_permits_issued", rows, key=("permit_number",))
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"


class Store(Protocol):
    def execute(self, sql: str, params: Any = None) -> None: ...
    def rows(self, sql: str, params: Any = None) -> list[dict]: ...
    def upsert(self, table: str, rows: Sequence[dict], *, key: Sequence[str],
               coalesce: Sequence[str] = (), coord_pair: Sequence[str] = ()) -> int: ...


def upsert_sql(table: str, columns: Sequence[str], *, key: Sequence[str],
               coalesce: Sequence[str] = (), coord_pair: Sequence[str] = ()) -> str:
    """INSERT ... ON CONFLICT (key) DO UPDATE.

    Two column rules beyond plain `col = EXCLUDED.col`:
      coalesce   -- an incoming NULL means "no opinion": keep the stored value. Used for
                    enrichment columns (project name, units) that another process may
                    have filled and that a re-sweep from a thinner source would wipe.
      coord_pair -- (lat, lon) move together: the stored pair is kept unless BOTH incoming
                    values are present, so an update never splices a new latitude onto a
                    stale longitude, and a loader that cannot geocode never wipes one.
    """
    cols = list(columns)
    updates = []
    for c in cols:
        if c in key:
            continue
        if coord_pair and c in coord_pair:
            a, b = coord_pair
            updates.append(f"{c} = CASE WHEN EXCLUDED.{a} IS NOT NULL AND EXCLUDED.{b} IS NOT NULL "
                           f"THEN EXCLUDED.{c} ELSE t.{c} END")
        elif c in coalesce:
            updates.append(f"{c} = COALESCE(EXCLUDED.{c}, t.{c})")
        else:
            updates.append(f"{c} = EXCLUDED.{c}")
    placeholders = ", ".join(f"%({c})s" for c in cols)
    action = ("DO UPDATE SET " + ", ".join(updates)) if updates else "DO NOTHING"
    return (f"INSERT INTO {table} AS t ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({', '.join(key)}) {action}")


def _adapt(v: Any) -> Any:
    from psycopg2.extras import Json
    if isinstance(v, dict):
        return Json(v)
    return v


def dedupe(rows: Iterable[dict], key: Sequence[str]) -> list[dict]:
    """Keep the LAST row per key: a source that lists one record twice wins with its latest."""
    out: dict[tuple, dict] = {}
    for r in rows:
        k = tuple(r.get(c) for c in key)
        if all(v is not None for v in k):
            out[k] = r
    return list(out.values())


class PgStore:
    def __init__(self, dsn: str):
        import psycopg2
        self.dsn = dsn
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = True
        self._server = None

    @classmethod
    def local(cls, pgdata: Path, database: str = "supply") -> PgStore:
        """Start (or attach to) a pgserver-managed Postgres in `pgdata` and open `database`."""
        import pgserver
        server = pgserver.get_server(Path(pgdata), cleanup_mode="stop")
        exists = server.psql(f"SELECT 1 FROM pg_database WHERE datname = '{database}';")
        if "1 row" not in exists:
            server.psql(f"CREATE DATABASE {database};")
        store = cls(server.get_uri(database))
        store._server = server
        return store

    def close(self) -> None:
        self.conn.close()

    # ---- basic SQL --------------------------------------------------------
    def execute(self, sql: str, params: Any = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)

    def rows(self, sql: str, params: Any = None) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def cursor(self):
        return self.conn.cursor()

    # ---- schema -----------------------------------------------------------
    def apply_schema(self, schema_dir: Path = SCHEMA_DIR) -> list[str]:
        applied = []
        for f in sorted(schema_dir.glob("*.sql")):
            self.execute(f.read_text())
            applied.append(f.name)
        return applied

    def reset(self) -> None:
        """Drop every schema this repo creates (tests and `make snapshot` start clean)."""
        for s in ("registry", "nashville", "county_permits", "tceq", "azre", "coa", "ncdeq", "layers"):
            self.execute(f"DROP SCHEMA IF EXISTS {s} CASCADE")

    # ---- writes -----------------------------------------------------------
    def upsert(self, table: str, rows: Sequence[dict], *, key: Sequence[str],
               coalesce: Sequence[str] = (), coord_pair: Sequence[str] = (),
               batch_size: int = 500) -> int:
        rows = dedupe(rows, key)
        if not rows:
            return 0
        columns = list(dict.fromkeys(c for r in rows for c in r))   # union, first-seen order
        sql = upsert_sql(table, columns, key=key, coalesce=coalesce, coord_pair=coord_pair)
        n = 0
        with self.conn.cursor() as cur:
            for i in range(0, len(rows), batch_size):
                chunk = [{c: _adapt(r.get(c)) for c in columns} for r in rows[i:i + batch_size]]
                cur.executemany(sql, chunk)
                n += len(chunk)
        log.info("upserted %d rows into %s", n, table)
        return n


def to_json(v: Any) -> str:
    return json.dumps(v, default=str)
