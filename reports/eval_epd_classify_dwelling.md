# Eval run: epd_classify_dwelling

Model: claude-haiku-4-5 (provider: replay) | run at 2026-10-21T00:00:00+00:00

Replayed from `epd_classify_dwelling_haiku-4-5_2026-10-21.jsonl`: recorded model outputs, no API call.

- Strict accuracy: 72/93 = 77.4%
- Business-bucket accuracy (for sale / rental / mixed / commercial / unknown): 76/93 = 81.7%
- Rent / sale errors (business_miss): 11
- Baseline (strict): 82.8%
- Cost of this run: $0.0000

## Severity

- pass: 72 (exact match)
- cosmetic_miss: 4 (wrong class, same business bucket (SF<->TH): no decision impact)
- business_miss: 11 (crosses for_sale<->rental: corrupts supply counts)
- overcommit: 5 (golden=unknown, model guessed)
- abstain_miss: 1 (golden=confident, model returned unknown)
- validation_fail: 0 (output not in enum)

## Accuracy by golden class

- mixed: 0.0%
- multifamily: 68.8%
- single_family: 85.7%
- townhome: 94.7%
- unknown: 16.7%

## Failures (21)

- [business_miss] `566055` expected='multifamily' actual='townhome'
- [business_miss] `829076` expected='single_family' actual='multifamily'
- [business_miss] `845636` expected='single_family' actual='multifamily'
- [business_miss] `880679` expected='single_family' actual='multifamily'
- [business_miss] `891034` expected='mixed' actual='multifamily'
- [business_miss] `903558` expected='mixed' actual='single_family'
- [business_miss] `944561` expected='multifamily' actual='single_family'
- [business_miss] `967012` expected='single_family' actual='multifamily'
- [business_miss] `981944` expected='mixed' actual='multifamily'
- [business_miss] `985054` expected='multifamily' actual='single_family'
- [business_miss] `995305` expected='multifamily' actual='single_family'
- [overcommit] `898780` expected='unknown' actual='single_family'
- [overcommit] `936512` expected='unknown' actual='townhome'
- [overcommit] `953782` expected='unknown' actual='townhome'
- [overcommit] `963274` expected='unknown' actual='single_family'
- [overcommit] `986517` expected='unknown' actual='multifamily'
- [abstain_miss] `890979` expected='multifamily' actual='unknown'
- [cosmetic_miss] `1001367` expected='single_family' actual='townhome'
- [cosmetic_miss] `866522` expected='single_family' actual='townhome'
- [cosmetic_miss] `915864` expected='single_family' actual='townhome'
- [cosmetic_miss] `976656` expected='townhome' actual='single_family'

## Alert: CRITICAL

pass rate dropped 5.4% (baseline 82.8% -> 77.4%); 11 business_miss (crosses for_sale<->rental)

Exit code: 1 (1 = a business_miss or a hard regression; the calibration window closed 2026-06-22)
