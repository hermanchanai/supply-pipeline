# Eval run: azdeq_classify

Model: claude-haiku-4-5 (provider: replay) | run at 2026-10-03T00:00:00+00:00

Replayed from `azdeq_classify_haiku-4-5_2026-10-03.jsonl`: recorded model outputs, no API call.

- Strict accuracy: 55/65 = 84.6%
- Business-bucket accuracy (for sale / rental / mixed / commercial / unknown): 56/65 = 86.2%
- Rent / sale errors (business_miss): 7
- Baseline (strict): 84.6%
- Cost of this run: $0.0000

## Severity

- pass: 55 (exact match)
- cosmetic_miss: 1 (wrong class, same business bucket (SF<->TH): no decision impact)
- business_miss: 7 (crosses for_sale<->rental: corrupts supply counts)
- overcommit: 1 (golden=unknown, model guessed)
- abstain_miss: 1 (golden=confident, model returned unknown)
- validation_fail: 0 (output not in enum)

## Accuracy by golden class

- commercial: 100.0%
- mixed: 50.0%
- multifamily: 83.3%
- single_family: 81.2%
- townhome: 80.0%
- unknown: 80.0%

## Failures (10)

- [business_miss] `10015` expected='single_family' actual='multifamily'
- [business_miss] `11512` expected='single_family' actual='multifamily'
- [business_miss] `12836` expected='multifamily' actual='single_family'
- [business_miss] `13750` expected='townhome' actual='multifamily'
- [business_miss] `13790` expected='mixed' actual='commercial'
- [business_miss] `8884` expected='single_family' actual='commercial'
- [business_miss] `9639` expected='multifamily' actual='mixed'
- [overcommit] `9322` expected='unknown' actual='commercial'
- [abstain_miss] `11422` expected='mixed' actual='unknown'
- [cosmetic_miss] `10602` expected='townhome' actual='single_family'

## Alert: CRITICAL

7 business_miss (crosses for_sale<->rental)

Exit code: 1 (1 = a business_miss or a hard regression; the calibration window closed 2026-06-22)
