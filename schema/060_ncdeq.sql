-- Spreadsheet reader output (NC DEQ construction stormwater certificates of coverage, one xlsx).
CREATE SCHEMA IF NOT EXISTS ncdeq;

CREATE TABLE IF NOT EXISTS ncdeq.noi_submissions (
    permit_number               text PRIMARY KEY,
    originating_application     text,
    permit_type                 text,
    general_permit              text,
    primary_permittee           text,
    project_name                text,
    full_address                text,
    effective_date              date,
    expiration_date             date,
    termination_date            date,
    version                     integer,
    region                      text,
    county                      text NOT NULL,
    status                      text,
    status_reason               text,
    created_on                  timestamptz,
    latitude                    double precision,
    longitude                   double precision,
    snapshot_date               date NOT NULL,
    list_loaded_at              timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ncdeq_noi_submissions_county_idx ON ncdeq.noi_submissions (county);
