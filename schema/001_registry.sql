-- Feed registry: one row per tracked source. `access_method` is how the feed is retrieved;
-- the snapshot builder groups feeds by it.
CREATE SCHEMA IF NOT EXISTS registry;

CREATE TABLE IF NOT EXISTS registry.pipeline_sources (
    id              bigint PRIMARY KEY,
    msa             text NOT NULL,
    state           text,
    source_label    text NOT NULL,
    schema_name     text NOT NULL,
    table_name      text NOT NULL,
    filter_sql      text,
    stage           text NOT NULL DEFAULT 'late',
    ingest_ts_col   text,
    data_date_col   text,
    data_date_expr  text,
    status          text NOT NULL DEFAULT 'cron',
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    access_method   text CONSTRAINT pipeline_sources_access_method_chk CHECK (
        access_method IS NULL OR access_method IN (
            'arcgis', 'portal_json', 'html_scrape', 'pdf', 'browser',
            'open_data_api', 'spreadsheet', 'derived'))
);

-- Per-feed coverage: row count, last load, newest record date. Production refreshes it on
-- a schedule from each feed's table; here it is frozen in sample/coverage.csv.
CREATE TABLE IF NOT EXISTS registry.pipeline_coverage (
    msa             text NOT NULL,
    source_label    text NOT NULL,
    row_count       bigint,
    last_ingested   timestamptz,
    latest_data     date,
    refreshed_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (msa, source_label)
);
