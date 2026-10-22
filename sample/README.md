# sample/

What `make snapshot` loads into a local Postgres before running the snapshot builder.
One file per table, named `<schema>.<table>`. Provenance and dates are in `manifest.json`.

| File | Rows | What it is |
|---|---|---|
| `registry.pipeline_sources.jsonl` | 254 | every tracked feed when the public page was generated (2026-09-30): metro, stage, access method, table |
| `registry.pipeline_coverage.jsonl` | 254 | each feed's record count, last load and newest record date, as of 2026-10-21 |
| `layers.mf_projects.csv` | 2,330 | every active multifamily / townhome project in the permit layer: id, metro, product, stage, units |
| `layers.pipeline_unified.jsonl`, `layers.sfd_projects.jsonl`, `layers.entitlement_other.jsonl` | 117 / 15 / 60 | the candidate rows each metro's 15-project sample is drawn from |
| the eight example feeds' tables | 10 each (20 for entitlement cases) | public-record rows, for running the views and seeing real values |

## How the output compares with the live page

- Same shape, same methods, same metros, same feed counts per method and per metro: the
  registry is the one the page was built from.
- Record counts and freshness differ: they are the 2026-10-21 coverage counts. Production
  keeps only the current coverage table, so the 2026-09-30 counts cannot be recovered.
- Multifamily projects and units are the full layer on 2026-10-21.
- Entitlement-case counts are small: only the sampled cases are bundled, not the 115,834
  behind the page.
