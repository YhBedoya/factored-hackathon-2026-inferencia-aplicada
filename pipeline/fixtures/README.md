TEST FIXTURE: synthetic CSV trees for `pipeline/tests/test_fixtures.py`. None of this is bank data,
and nothing here is ever ingested by `make data`. Every name contains `test_fixture`.
Each tree mirrors the raw layout (`transactions/year=/month=/day=/<file>.csv`).

- `test_fixture_late_partition/v1`, `test_fixture_late_partition/v2`: the same relative key. v2 is the later re-delivery of
  the partition with one corrected value (`TRX-TESTFIXTURE00001` amount 10.00 -> 99.00).
- `test_fixture_duplicate_batch`: `test_fixture_part.csv` plus `test_fixture_part_dup.csv` in the same
  partition, the same rows under a second key.
- `test_fixture_schema_change`: a normal partition (day 15) next to one (day 16) whose header renames
  `merchant_name` to `merchant` and adds `installments`.
