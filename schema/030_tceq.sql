-- HTML scrape reader output (TCEQ construction stormwater notices of intent, TXR150000).
CREATE SCHEMA IF NOT EXISTS tceq;

CREATE TABLE IF NOT EXISTS tceq.cgp_noi (
    noi_id                      bigserial PRIMARY KEY,
    authorization_number        text NOT NULL UNIQUE,
    lgl_id                      text,
    pita_id                     text,
    phys_id                     text,
    princ_id                    text,
    reg_ent_id                  text,
    operator_name               text,
    primary_sic_code            text,
    region                      text,
    region_number               integer,
    site_address                text,
    site_city                   text,
    site_county                 text NOT NULL,
    project_name                text,
    authorization_status        text,
    authorization_type          text,
    date_coverage_began         date,
    date_coverage_ended         date,
    replaced_permit_number      text,
    disturbed_acres             numeric,
    common_plan_of_development  boolean,
    construction_type           text,
    latitude                    numeric,
    longitude                   numeric,
    dwelling_type               text CHECK (dwelling_type IS NULL OR dwelling_type IN (
        'single_family', 'townhome', 'multifamily', 'mixed', 'commercial', 'unknown')),
    dwelling_type_classified_at timestamptz,
    ingested_at                 timestamptz DEFAULT now(),
    last_refreshed_at           timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cgp_noi_county ON tceq.cgp_noi (site_county);
CREATE INDEX IF NOT EXISTS idx_cgp_noi_coverage_began ON tceq.cgp_noi (date_coverage_began);
