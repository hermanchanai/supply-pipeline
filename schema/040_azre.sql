-- PDF reader output (Arizona Department of Real Estate subdivision public reports):
-- the CSV index row, then the fields a language model reads from the report PDF.
CREATE SCHEMA IF NOT EXISTS azre;

CREATE TABLE IF NOT EXISTS azre.public_reports (
    registration_number text PRIMARY KEY,
    development_name    text,
    marketing_name      text,
    location            text,
    parsed_city         text,
    parsed_state        text,
    parsed_county       text,
    application_type    text,
    application_status  text,
    lot_status          text,
    date_filed          date,
    date_issued         date,
    developer_name      text,
    developer_dba       text,
    ingested_at         timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pr_date_issued_idx ON azre.public_reports (date_issued);

CREATE TABLE IF NOT EXISTS azre.public_reports_extracted (
    registration_number         text PRIMARY KEY
        REFERENCES azre.public_reports (registration_number) ON UPDATE CASCADE ON DELETE CASCADE,
    total_lots                  integer,
    subdivision_acres           numeric,
    effective_date              date,
    legal_name                  text,
    marketing_name              text,
    developer_name              text,
    location_description        text,
    street_intersection         text,
    parsed_city                 text,
    parsed_county               text,
    water_provider              text,
    sewer_provider              text,
    electricity_provider        text,
    gas_provider                text,
    hoa_present                 boolean,
    hoa_assessment_amount       numeric,
    hoa_assessment_period       text CHECK (hoa_assessment_period IS NULL OR hoa_assessment_period IN (
        'monthly', 'quarterly', 'annual', 'one_time', 'unknown')),
    master_planned_community    text,
    amenities                   text[],
    school_district             text,
    nearest_hospital            text,
    estimated_completion_date   date,
    pdf_pages                   integer,
    pdf_byte_size               integer,
    pdf_path                    text,
    raw_extraction_json         jsonb,
    model                       text,
    extracted_at                timestamptz NOT NULL DEFAULT now()
);
