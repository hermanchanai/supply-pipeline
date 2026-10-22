# Schema

Column definitions come from the production database's catalog (read-only, schema only,
no rows), trimmed for this repo:

- Columns that hold people's contact details (applicant and reviewer names, emails,
  phones and mailing addresses) are left out. Readers never fetch them into a row.
- Raw-payload blobs (`raw_attributes`, `raw_socrata_payload`, `raw_csv_row`, ...) are left
  out. The source can always be re-fetched, and a blob is where personal fields hide.
- Production writes through `bulk_upsert_*` database functions. Here every reader goes
  through `Store.upsert`, which issues the same `INSERT ... ON CONFLICT` itself.
- `layers.*` stand in for the production views that merge all ~250 feeds into project
  layers. Only the columns the snapshot builder reads are kept, and they are filled from
  `sample/` alone.

Files apply in name order. `supply_pipeline.store.PgStore.apply_schema()` runs them.
