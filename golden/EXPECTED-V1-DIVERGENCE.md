# expected-v1 known divergence

`golden/expected-v1.json` is the frozen pre-registration. The committed fixture replays cite its sha256 (345dd5cd00485668f9f3bcdd2baf2515db0af452ecf07b968a75a62d1b404719, pinned in `FREEZE-v1.sha256`), so it stays byte-identical.

Three of its `compiled_sql_sha256` values were recorded with the compiler from before two fixes:
- G02 and G07 have a time grain. The compiler now groups by the bucket expression instead of by the `period_start` alias.
- G03 uses `country ne "United Kingdom"`. The compiler now compiles `ne` as `(e <> ? OR e IS NULL)`.

The SQL text changed and the result tables did not. `golden/expected-v2.json` is canonical (`src/analyticsreceipts/report.py`, `EXPECTED_TABLES`).

| item | v1 compiled_sql_sha256 | v2 compiled_sql_sha256 | result_sha256 (v1 = v2) |
|---|---|---|---|
| G02 | `dd081ca1432a789ad0bfb5712f34894e2a02798e36dd6b31f06d2f40d4c2b88e` | `a904cfbf047a013d785470b0626e7b527dd6a81a6f93b15798aa579f96ef8d50` | `f7fd172ffcd823d3f4eb7440f1107d0405445d3bd0e42070d2307af8c4cbb8b7` |
| G03 | `9741972bfb505008f68725dd497ae80e773d9f2932160533eb7e8ca33db0e867` | `807d9ce26ecf2029cf990d12f0f50cfad2377c74f9ef5d402331eb4459f18e70` | `db7d3b63b72c05332d95ea588e974e667d06d8ed3febb453f4f2e92b7d3d7af3` |
| G07 | `2e2fd681630963f30f778b4f3876709ca723529f26cc64d57cfa3350b2d5f531` | `6b71f2f70016cb262413993b2ebc3b6699c5f5f7d2d370b28214b984418172a7` | `7d5817c06a3175d03b48479186099745a1dcd5c4be658eb849a326b3382f7b5c` |

How v2 was made: `python -m analyticsreceipts.materialise golden/golden-v1.json <warehouse> golden/expected-v2.json`, with the shipped compiler against the same warehouse (`snapshot.db_file_sha256` equal in v1 and v2). Field by field, the only differing field is `compiled_sql_sha256` for these three items. `rows`, `result_sha256`, `naive` and `trap_strength` are identical for all 15 items. The grader reads `rows`, `columns`, `naive` and `metric_def_version`, never `compiled_sql_sha256`.

Tests:
- `tests/test_freeze.py::test_expected_v1_known_sql_divergence` recompiles and re-runs all 15 golden specs and asserts that the SQL hashes differ from v1 for exactly {G02, G03, G07} and that every result hash equals v1 (needs the warehouse).
- `tests/test_expected_tables.py::test_canonical_expected_tables_match_the_shipped_compiler` asserts that v2 matches the shipped compiler for all 15.
- `tests/test_freeze.py::test_expected_v2_hash_unchanged` pins v2 (sha256 5a07c30be866206c561857b5858301d17d9f65cae2a853ff38ef9df4a666d04a).

## Committed replays: receipt format v1

The committed replays use receipt format v1, recorded before receipts carried `compiler` and before `kind` distinguished a control run, so the planted-compiler replay `replays/fixtures-v1-broken.json` labels its 12 MCP receipts `governed_metric` with the governed model hash; today's server labels planted-compiler receipts `control_metric` and names the compiler (`tests/test_freeze.py::test_broken_control_replay_is_receipt_v1` and `::test_planted_control_run_today_labels_its_receipts`).
