# data/

## Golden sets (`goldens/*.jsonl`)

Filings with a researched dwelling type, used to score the classifiers. One JSON object per
line: the classifier input (`input_payload`), the expected class, and how the label was made.

| File | Rows | Metro |
|---|---|---|
| `azdeq_classify.jsonl` | 65 | Phoenix (Arizona ADEQ construction stormwater notices) |
| `epd_classify_dwelling.jsonl` | 93 | Atlanta (Georgia EPD construction stormwater notices) |

### How the labels were made (`label_method`)

Two methods, both web research and neither one ever shown the classifier's answers:

- `hand_web_research`: labelled by hand. For each filing I searched the developer and read
  the filing, the developer's own site and the county's permits. These are the first 50
  Atlanta filings.
- `llm_web_research`: labelled by a separate language-model run that followed the same
  web-research method. These are the other 43 Atlanta filings and all 65 Phoenix filings.

`labeled_by_db` keeps the value the production database recorded, verbatim. That column
names only the model runs, including for the 50 hand-labelled filings, which is why both
columns are here.

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

## Other files

- `atlanta_developer_lexicon.json`: developer -> typical dwelling type, from county permits
  and developers' own descriptions. Built while labelling the Atlanta goldens, so a score
  that uses it on those goldens is leaky and is not published.
- `eval_baselines.json`: the June 2026 baseline pass rate per surface.
- `local/` (gitignored): PDFs and the LLM call log from live runs.
