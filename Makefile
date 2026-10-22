PY ?= python

.PHONY: test lint snapshot eval

test:
	$(PY) -m pytest -p no:cacheprovider --disable-socket

lint:
	$(PY) -m ruff check .

snapshot:
	$(PY) -m supply_pipeline.snapshot --sample sample --out build/supply-database.json

eval:
	-$(PY) -m supply_pipeline.evals.run --surface azdeq_classify --replay data/recorded/azdeq_classify_haiku-4-5_2026-10-03.jsonl --out reports --run-at 2026-10-03T00:00:00+00:00
	-$(PY) -m supply_pipeline.evals.run --surface epd_classify_dwelling --replay data/recorded/epd_classify_dwelling_haiku-4-5_2026-10-21.jsonl --out reports --run-at 2026-10-21T00:00:00+00:00
