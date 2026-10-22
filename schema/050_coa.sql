-- Open-data API reader output (City of Austin subdivision cases, Socrata dataset it4s-wgjk).
-- Columns follow the fields the dataset publishes.
CREATE SCHEMA IF NOT EXISTS coa;

CREATE TABLE IF NOT EXISTS coa.subdivision_review_cases (
    folderrsn               text PRIMARY KEY,
    case_number             text,
    permit_number           text,
    case_name               text,
    case_type               text,
    sub_type                text,
    case_status             text,
    application_start_date  date,
    approval_date           date,
    proposed_no_of_lots     integer,
    gross_site_area_acres   numeric,
    latitude                double precision,
    longitude               double precision,
    ingested_at             timestamptz NOT NULL DEFAULT now(),
    last_refreshed_at       timestamptz NOT NULL DEFAULT now()
);
