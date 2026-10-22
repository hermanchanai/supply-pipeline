-- GIS map service reader output (Metro Nashville ArcGIS hub).
CREATE SCHEMA IF NOT EXISTS nashville;

CREATE TABLE IF NOT EXISTS nashville.building_permits_issued (
    permit_number               text PRIMARY KEY,
    permit_type_description     text,
    permit_subtype_description  text,
    parcel                      text,
    date_entered                date,
    date_issued                 date,
    const_cost                  numeric,
    address                     text,
    city                        text,
    state                       text,
    subdivision_lot             text,
    per_ty                      text,
    per_subty                   text,
    purpose                     text,
    council_district            numeric,
    census_tract                numeric,
    lon                         double precision,
    lat                         double precision,
    zip                         text,
    source_object_id            bigint,
    ingested_at                 timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_nash_bpi_date_issued ON nashville.building_permits_issued (date_issued DESC);
CREATE INDEX IF NOT EXISTS ix_nash_bpi_subtype ON nashville.building_permits_issued (permit_subtype_description);

-- Planning cases (same hub, second layer). The derived view in 080 reads this table.
CREATE TABLE IF NOT EXISTS nashville.planning_dev_cases (
    ca_object_id                bigint PRIMARY KEY,
    application_type            text,
    case_type_description       text,
    sub_type_description        text,
    date_accepted               date,
    mpc_case_number             text,
    ordinance_number            text,
    project_name                text,
    location                    text,
    mpc_meeting_date            date,
    council_3rd_reading_date    date,
    council_3rd_reading_action  text,
    council_district            text,
    case_caption                text,
    status                      text,
    council_2nd_reading_date    date,
    mpc_vote                    text,
    mpc_action                  text,
    council_2nd_reading_action  text,
    council_1st_reading_date    date,
    council_1st_reading_action  text,
    parcels                     text,
    acreage                     text,
    existing_zoning             text,
    new_zoning                  text,
    planned_unit_development    text,
    policy                      text,
    community_plan              text,
    lon                         double precision,
    lat                         double precision,
    source_object_id            bigint,
    ingested_at                 timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_nash_pdc_date_acc ON nashville.planning_dev_cases (date_accepted DESC);
