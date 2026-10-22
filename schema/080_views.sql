-- Method "derived": a feed that is not a download but a filtered view over a table another
-- feed already loads. This is the Nashville planning arm of the entitlement layer: planning
-- cases (loaded by the ArcGIS reader) narrowed to rezonings, specific plans, PUDs and plats.
CREATE OR REPLACE VIEW nashville.v_planning_entitlements AS
SELECT 'nashville'::text AS msa,
       'davidson_metro'::text AS jurisdiction,
       'nashville_planning'::text AS source,
       COALESCE(NULLIF(d.mpc_case_number, ''), d.ca_object_id::text) AS case_number,
       CASE
           WHEN d.application_type = 'Standard Rezoning' THEN 'rezoning'
           WHEN d.application_type IN ('Specific Plan New', 'Specific Plan Amendment') THEN 'rezoning'
           WHEN d.application_type IN ('Specific Plan Final Site Plan', 'Subdivision Final Site Plan',
                                       'Planned Unit Development Final Site Plan') THEN 'final_site_plan'
           WHEN d.application_type LIKE 'Planned Unit Development%' THEN 'pad'
           WHEN d.application_type = 'Subdivision Concept Plan' THEN 'pre_application'
           ELSE 'plat'
       END AS stage,
       d.application_type AS filing_type,
       COALESCE(NULLIF(d.project_name, ''), d.case_caption) AS project_name,
       d.status AS status_raw,
       CASE
           WHEN d.status = 'Complete' AND COALESCE(d.mpc_action, '') ILIKE '%disapprov%' THEN 'denied'
           WHEN d.status = 'Complete' THEN 'approved'
           ELSE 'in_review'
       END AS lifecycle_status,
       CASE
           WHEN upper(COALESCE(d.project_name, '') || ' ' || COALESCE(d.case_caption, '')) ~ 'TOWNHOME|TOWNHOUSE'
               THEN 'townhome'
           WHEN upper(COALESCE(d.project_name, '') || ' ' || COALESCE(d.case_caption, ''))
                ~ 'APARTMENT|MULTIFAMILY|MULTI-FAMILY|FLATS|CONDOMINIUM|SENIOR LIVING' THEN 'multifamily'
           WHEN d.new_zoning ~ '^RM' THEN 'multifamily'
           WHEN d.new_zoning ~ '^MU' THEN 'mixed'
           WHEN d.new_zoning ~ '^(RS|R[0-9])' THEN 'single_family'
           WHEN d.application_type LIKE 'Subdivision%' THEN 'single_family'
       END AS dwelling_type,
       NULL::integer AS units,
       CASE WHEN d.acreage ~ '^[0-9]+\.?[0-9]*$' THEN d.acreage::numeric END AS acres,
       d.date_accepted AS submitted_date,
       COALESCE(d.council_3rd_reading_date, d.council_2nd_reading_date, d.council_1st_reading_date,
                d.mpc_meeting_date, d.date_accepted) AS latest_action_date,
       'DAVIDSON'::text AS county,
       d.location AS address,
       d.lat AS latitude,
       d.lon AS longitude
  FROM nashville.planning_dev_cases d
 WHERE d.application_type IN (
       'Standard Rezoning', 'Specific Plan New', 'Specific Plan Amendment',
       'Specific Plan Final Site Plan', 'Planned Unit Development Amendment',
       'Planned Unit Development Revise', 'Planned Unit Development Final Site Plan',
       'Subdivision Concept Plan', 'Subdivision Final Plat', 'Subdivision Ammend',
       'Subdivision Final Site Plan');

-- The entitlement layer the snapshot builder counts: reader-loaded cases, the derived
-- Nashville arm, and sample rows for feeds without a reader in this repo.
CREATE OR REPLACE VIEW county_permits.v_entitlement_served AS
SELECT e.msa, e.jurisdiction, e.source_type AS source, e.case_number, e.stage,
       e.project_name, e.lifecycle_status, e.dwelling_type, e.units_filed AS units,
       e.county, e.application_date AS submitted_date, e.latest_action_date
  FROM county_permits.entitlement_cases e
UNION ALL
SELECT n.msa, n.jurisdiction, n.source, n.case_number, n.stage,
       n.project_name, n.lifecycle_status, n.dwelling_type, n.units,
       n.county, n.submitted_date, n.latest_action_date
  FROM nashville.v_planning_entitlements n
UNION ALL
SELECT o.msa, o.jurisdiction, 'sample'::text AS source, o.case_number, o.stage,
       o.project_name, o.lifecycle_status, o.dwelling_type, o.units,
       o.county, o.submitted_date, o.latest_action_date
  FROM layers.entitlement_other o;
