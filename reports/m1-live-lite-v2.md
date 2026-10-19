# M1 LIVE-LITE report

**Superseded counts (rule ER-1):** re-graded with the ER-1 grader, valid_wrong_question is MCP 2 → 1 and raw 1 → 0, and MCP correct is 1 → 2 (G11/mcp → correct; G04/raw → valid_misstated_spec). See `m1-er1-regrade.md`. The body below is the original grading, kept unchanged.

**LIVE-LITE v2: ONE change from v1 (explicit tool-use instruction in the system prompt, both arms). Graded with grader bdfc424.**

**Label: LIVE-LITE.** One local model, one run per (item, arm), a fixed-priority queue under hard time caps: whatever completed is the result. N is tiny: every number is a count, intervals are Wilson 95 %, and no comparison between arms is claimed.

## Events

- start: {"resume": false, "config_sha256": "fc0b6f102d825cbe426bcbc4bae4ed088a8ddd82fc9a1e8fda9af88e4a9f474e", "prior_elapsed_s": 0.0, "prior_elapsed_note": "cumulative run time from the last stop event (auto-resume)", "pairs_remaining": [["G01", "mcp"], ["G01", "raw"], ["G11", "mcp"], ["G11", "raw"], ["G16", "mcp"], ["G16", "raw"], ["G19", "mcp"], ["G19", "raw"], ["G12", "mcp"], ["G12", "raw"], ["G04", "mcp"], ["G04", "raw"], ["G17", "mcp"], ["G17", "raw"], ["G20", "mcp"], ["G20", "raw"]], "conditions": {"t": "2026-10-16 14:35:09", "power_source": "AC Power", "battery_pct": 100, "lowpowermode": 1, "free_kib": 10551064, "swapusage": "vm.swapusage: total = 4096.00M  used = 2742.75M  free = 1353.25M  (encrypted)"}, "semantic_model_sha256": "d1d2cd0a49caf648ad0af6fb68bbd7fe9da80ed67da93ab8f2b7def5ae64e82e"}
- stop: {"reason": "queue_complete", "elapsed_s": 18471.5}
- end: {"reason": "queue_complete", "conditions": {"t": "2026-10-16 19:43:01", "power_source": "AC Power", "battery_pct": 100, "lowpowermode": 1, "free_kib": 5465468, "swapusage": "vm.swapusage: total = 9216.00M  used = 8526.31M  free = 689.69M  (encrypted)"}}

## Per-axis results

| arm | answers | a metric | b query | c number | d interpretation |
|---|---|---|---|---|---|
| mcp | 8 | 3/6 (N/A 2) | 2/6 (N/A 2) | 2/6 (N/A 2) | 3/8 |
| raw | 8 | 0/0 (N/A 8) | 1/5 (N/A 3) | 1/5 (N/A 3) | 3/8 |

## Cells

| cell | mcp | raw |
|---|---|---|
| correct | 1 | 0 |
| valid_wrong_question | 2 | 1 |
| valid_misreported | 0 | 0 |
| invalid_right_intent | 0 | 0 |
| invalid_wrong | 0 | 2 |
| no_answer | 1 | 0 |
| correct_abstain | 2 | 3 |
| false_abstain | 0 | 1 |
| unwarranted_answer | 2 | 1 |

- mcp: valid SQL, wrong question = 2/8, Wilson 95 % (0.071, 0.591)
- raw: valid SQL, wrong question = 1/8, Wilson 95 % (0.022, 0.471)

## Per run

| item | arm | s | turns | tool calls (failed) | loop-timeout | tok/s | a | b | c | d | cell | trap | receipts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| G01 | mcp | 1205.22 | 3 | 2 (0) | False | 8.05 | True | False | False | False | valid_wrong_question | None | addf55275b |
| G01 | raw | 1537.41 | 2 | 1 (0) | False | 7.81 | N/A | False | False | False | invalid_wrong | None | none |
| G11 | mcp | 735.8 | 3 | 2 (0) | False | 8.17 | True | True | True | False | valid_wrong_question | False | bd9af2983a |
| G11 | raw | 735.76 | 1 | 0 (0) | False | 7.2 | N/A | False | False | False | invalid_wrong | False | none |
| G16 | mcp | 1437.89 | 3 | 2 (0) | False | 8.07 | False | False | False | False | unwarranted_answer | None | 8fa58a4f08 |
| G16 | raw | 1431.26 | 3 | 2 (0) | False | 8.19 | N/A | False | False | False | unwarranted_answer | None | 0ac7c8767e |
| G19 | mcp | 305.33 | 2 | 1 (0) | False | 9.11 | N/A | N/A | N/A | True | correct_abstain | None | none |
| G19 | raw | 411.19 | 2 | 1 (0) | False | 9.26 | N/A | N/A | N/A | True | correct_abstain | None | none |
| G12 | mcp | 911.19 | 3 | 2 (0) | False | 8.58 | True | True | True | True | correct | False | 4b83f45897 |
| G12 | raw | 2083.75 | 3 | 2 (1) | False | 8.46 | N/A | False | False | False | false_abstain | None | 2d60c0b582 |
| G04 | mcp | 2700.01 | 4 | 4 (0) | True | 7.34 | False | False | False | False | no_answer | None | edb42cd96b |
| G04 | raw | 1617.92 | 3 | 2 (0) | False | 8.91 | N/A | True | True | False | valid_wrong_question | None | 262efa4f26 |
| G17 | mcp | 1368.38 | 4 | 3 (0) | False | 8.63 | False | False | False | False | unwarranted_answer | None | eeff558cf8 |
| G17 | raw | 1504.26 | 3 | 2 (1) | False | 8.77 | N/A | N/A | N/A | True | correct_abstain | None | da80e6beaa |
| G20 | mcp | 262.97 | 2 | 1 (0) | False | 9.48 | N/A | N/A | N/A | True | correct_abstain | None | none |
| G20 | raw | 221.73 | 1 | 0 (0) | False | 9.63 | N/A | N/A | N/A | True | correct_abstain | None | none |

## v1 vs v2, side by side

**One change** (the explicit tool-use instruction, both arms). **Tiny N** (8 answers per arm, 4 answerable). **Descriptive only; no significance claim.** Both replays graded by the same grader. Regenerate with: `python -m analyticsreceipts.compare replays/live-lite-v1.jsonl replays/live-lite-v2.jsonl --names v1,v2`.

| measure | v1 mcp | v2 mcp | v1 raw | v2 raw |
|---|---|---|---|---|
| answers | 8 | 8 | 8 | 8 |
| answerable | 4 | 4 | 4 | 4 |
| well_formed_call_plus_numeric | 0 | 2 | 0 | 1 |
| tool_calls | 2 | 17 | 7 | 10 |
| primary_tool_calls (query_metric or run_sql) | 0 | 6 | 2 | 4 |
| median_seconds | 685.17 | 1205.22 | 739.96 | 1504.26 |
| a | 0/5 | 3/6 | 0/0 | 0/0 |
| b | 0/5 | 2/6 | 0/5 | 1/5 |
| c | 0/5 | 2/6 | 0/5 | 1/5 |
| d | 3/8 | 3/8 | 3/8 | 3/8 |
| correct | 0 | 1 | 0 | 0 |
| valid_wrong_question | 0 | 2 | 1 | 1 |
| valid_misreported | 0 | 0 | 0 | 0 |
| invalid_right_intent | 0 | 0 | 0 | 0 |
| invalid_wrong | 3 | 0 | 1 | 2 |
| no_answer | 0 | 1 | 1 | 0 |
| correct_abstain | 3 | 2 | 3 | 3 |
| false_abstain | 1 | 0 | 1 | 1 |
| unwarranted_answer | 1 | 2 | 1 | 1 |

Reading notes (from the per-run reasons above, no inference beyond them):
- 2 of the 3 v2 `valid_wrong_question` cells (G11/mcp, G04/raw) have the expected table and number (b and c pass) and fail only on axis d: the agent's resolved_spec says `grain: month` for a one-month total (G11), or does not use the governed spec vocabulary (G04/raw). The headline cell is a catch-all for d failures (review finding 10, not in this fix scope), so those two are spec-form failures, not different questions.
- G04/mcp hit the 2,700 s loop cap (4 tool calls, no final message) and is `no_answer`.
