"""python -m supply_pipeline.snapshot --sample sample --out build/supply-database.json

Starts a local Postgres (pgserver) in --pgdata, rebuilds the schema, loads the sample and
writes the snapshot JSON. Deterministic: the as-of date and generated_at come from
sample/manifest.json, so the same sample always produces the same file.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from ..store import PgStore
from . import builder, sample


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sample", type=Path, default=Path("sample"))
    ap.add_argument("--out", type=Path, default=Path("build/supply-database.json"))
    ap.add_argument("--pgdata", type=Path, default=Path(".pgdata"))
    ap.add_argument("--sample-per-market", type=int, default=15)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    m = sample.manifest(args.sample)
    store = PgStore.local(args.pgdata)
    try:
        store.reset()
        store.apply_schema()
        sample.load(store, args.sample)
        payload = builder.build(store, as_of=date.fromisoformat(m["as_of"]),
                                sample_per_market=args.sample_per_market,
                                generated_at=datetime.fromisoformat(m["frozen_at"]))
    except builder.Refusal as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    finally:
        store.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    h = payload["headline"]
    print(f"wrote {args.out}: {h['tracked_feeds']} feeds / {h['source_records']:,} records / "
          f"{h['metros']} metros; {sum(len(v) for v in payload['samples'].values())} sample rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
