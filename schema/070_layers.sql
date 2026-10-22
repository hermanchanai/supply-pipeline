-- Project layers the snapshot builder reads. In production these are views and
-- materialized views merging every feed; here they are plain tables filled from sample/.
CREATE SCHEMA IF NOT EXISTS layers;

-- Multifamily / townhome permit-layer projects, one row per deduplicated project.
CREATE TABLE IF NOT EXISTS layers.mf_projects (
    mv_row_id               bigint PRIMARY KEY,
    msa                     text,
    project_subtype         text,
    best_lifecycle_stage    text,
    max_units_signal        integer,
    is_active_supply        boolean,
    is_cluster_primary      boolean
);

-- Cross-source canonical projects (the metros that have one).
CREATE TABLE IF NOT EXISTS layers.pipeline_unified (
    canonical_project_id    text PRIMARY KEY,
    metro                   text,
    project_name            text,
    county                  text,
    city                    text,
    dwelling_type           text,
    units_measured          integer,
    units_estimated         integer,
    lifecycle_status        text,
    latest_signal_date      date,
    source_count            integer
);

-- Single-family permit-layer projects rolled up by tract.
CREATE TABLE IF NOT EXISTS layers.sfd_projects (
    mv_row_id               bigint PRIMARY KEY,
    msa                     text,
    project_name            text,
    city                    text,
    county                  text,
    project_subtype         text,
    best_lifecycle_stage    text,
    max_units_signal        integer
);

-- Entitlement cases from feeds this repo has no reader for (sample rows only).
CREATE TABLE IF NOT EXISTS layers.entitlement_other (
    msa                 text NOT NULL,
    jurisdiction        text NOT NULL,
    case_number         text NOT NULL,
    stage               text,
    project_name        text,
    lifecycle_status    text,
    dwelling_type       text,
    units               integer,
    county              text,
    submitted_date      date,
    latest_action_date  date,
    PRIMARY KEY (jurisdiction, case_number)
);
