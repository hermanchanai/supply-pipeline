# data/

## Golden sets (`goldens/*.jsonl`)

Filings with a researched dwelling type, used to score the classifiers. One JSON object per
line: the classifier input (`input_payload`), the expected class, and how the label was made.

| File | Rows | Metro |
|---|---|---|
| `azdeq_classify.jsonl` | 65 | Phoenix (Arizona ADEQ construction stormwater notices) |
| `epd_classify_dwelling.jsonl` | 93 | Atlanta (Georgia EPD construction stormwater notices) |

### How the labels were made (`label_method`)

Every row is `llm_web_research`: labelled by a separate language-model run with web
search, never shown the classifier's answers. The methodology was set and directed by me:
for each filing, search the developer and read the filing, the developer's own site and
the county's permits, then record the dwelling type with the evidence. I labelled the
earliest filings the same way by hand before handing the method to a model.

`labeled_by_db` keeps the value the production database recorded, verbatim (for example
`opus4.8+websearch (herman-directed 2026-06-02)` for the first 50 Atlanta rows).

### What was removed

- Phoenix: two facility names that are a private person's surname, and one "<surname>
  Residence", are replaced with `[surname]` (`input_redacted: true`). The recorded model
  outputs for those three rows were produced on the original names.
- Atlanta: owner names, every email field and the free-text notes are dropped (they name
  people), leaving the project name, place, acreage and activity types. Production also
  sends email domains, so the Atlanta score cannot be reproduced from these inputs without
  a new paid run; see the README.

## Recorded model outputs (`recorded/`)

`azdeq_classify_haiku-4-5_2026-10-03.jsonl` is the production eval run of Claude Haiku 4.5
on the 65 Phoenix goldens, one line per golden, keyed by a SHA-256 of the exact user message
the classifier sends. `ReplayProvider` answers from it, so the eval re-scores for $0 and a
changed prompt input fails loudly instead of drifting.

`epd_classify_dwelling_haiku-4-5_2026-10-21.jsonl` is a live run of the same model on the 93
Atlanta goldens **as published here**, without the owner names and email domains production
also sends. It was recorded with `--live --record` (93 calls, $0.086) so the Atlanta score
re-scores offline too: 77.4% exact (72), 81.7% right business bucket (76), 11 rent/sale
errors, against 82.8% exact in production with the full inputs. The gap is the value of the
owner and email-domain signals, which cannot be published.

## Other files

- `atlanta_developer_lexicon.json`: developer -> typical dwelling type, from county permits
  and developers' own descriptions. Built while labelling the Atlanta goldens, so a score
  that uses it on those goldens is leaky and is not published.
- `eval_baselines.json`: the June 2026 baseline pass rate per surface.
- `local/` (gitignored): PDFs and the LLM call log from live runs.
