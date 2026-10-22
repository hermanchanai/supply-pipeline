-- Entitlement (pre-permit) cases from many jurisdictions in one table. The permit-portal
-- JSON reader (Tyler EnerGov) and the browser reader (Accela) both write here.
CREATE SCHEMA IF NOT EXISTS county_permits;

CREATE TABLE IF NOT EXISTS county_permits.entitlement_cases (
    id                  bigserial PRIMARY KEY,
    msa                 text NOT NULL,
    jurisdiction        text NOT NULL,
    source_type         text NOT NULL,
    case_number         text NOT NULL,
    case_type_raw       text,
    stage               text NOT NULL,
    project_name        text,
    status_raw          text,
    lifecycle_status    text,
    application_date    date,
    latest_action_date  date,
    land_use_raw        text,
    dwelling_type       text,
    units_filed         integer,
    lots_filed          integer,
    acres               numeric,
    address             text,
    city                text,
    county              text,
    latitude            double precision,
    longitude           double precision,
    link                text,
    raw_json            jsonb NOT NULL DEFAULT '{}'::jsonb,
    first_observed_at   timestamptz NOT NULL DEFAULT now(),
    ingested_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (jurisdiction, case_number)
);
CREATE INDEX IF NOT EXISTS entitlement_cases_msa_stage_idx ON county_permits.entitlement_cases (msa, stage);
