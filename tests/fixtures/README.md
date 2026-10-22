# Recorded fixtures

Every network reader is tested against responses recorded from the real public source on
2026-10-21, trimmed to what the test needs. Nothing here was invented except where noted.

| File | Source | Trimming and scrubbing |
|---|---|---|
| `arcgis/nashville_permits_offset{0,2}.json` | Metro Nashville ArcGIS, Building_Permits_Issued_2, two pages of 2 | `fields` array removed; the `Contact` attribute removed |
| `arcgis/nashville_planning.geojson` | Metro Nashville ArcGIS, Development_Tracker_Cases_view, 7 cases | applicant and reviewer fields removed; each caption's requested-by clause replaced with `Example Engineering LLC` / `Example Holdings LLC`; the collection-level `exceededTransferLimit` set to false so it reads as a last page |
| `socrata/austin_it4s_wgjk.json` | City of Austin Socrata dataset `it4s-wgjk`, 3 rows | geometry, applicant and case-manager fields removed |
| `energov/henderson_tentative_p1.json` | Henderson, NV EnerGov plan search, keyword "tentative", page 1 of 5 | none |
| `tceq/waller_list_p1.html` | TCEQ WQ-DPA search, Waller County, 09/01–10/15/2026 | count messages, header row and 5 of 26 rows; counts in the message edited to 5 to match |
| `tceq/detail_TXR1501ZP.html` | TCEQ permit summary page | label/value paragraphs only; operator mailing address removed |
| `adre/public_reports_list.csv` | ADRE subdivision CSV index | 5 rows plus one duplicate; developer mailing-address columns blanked |
| `adre/view_development_62884.html` | ADRE development page | the download form only; anti-forgery token replaced with a placeholder |
| `adre/recorded_extraction_DM26-062884.json` | the production model's stored output for that report (Claude Haiku 4.5) | developer mailing-address keys removed |
| `accela/clark_tentative_map_results.html` | Clark County Accela Planning search, Tentative Map, 08/01–10/15/2026 | the results grid only: header, first 4 rows, pager; scripts and form state removed |
| `ncdeq/ncg_cocs_sample.json` | NC DEQ certificates-of-coverage xlsx | the real header row plus 3 NCG01 rows and 1 NCG25 row, stored as JSON; the test rebuilds an xlsx from it |
| `site/supply-database.json` | the public page's own JSON (site repo) | none; the builder's shape test compares against it |

The ADRE report PDF is not recorded (a full report runs to megabytes);
tests generate blank-page PDFs to exercise downloading and trimming.
