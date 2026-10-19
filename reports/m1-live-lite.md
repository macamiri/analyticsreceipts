# M1 LIVE-LITE report

**Re-graded with grader bdfc424 (after the code-review fixes); 0 of 16 grades changed versus grader d46e3b4.**

**Label: LIVE-LITE.** One local model, one run per (item, arm), a fixed-priority queue under hard time caps: whatever completed is the result. N is tiny: every number is a count, intervals are Wilson 95 %, and no comparison between arms is claimed.

## Events

- start: {"resume": false, "config_sha256": "81ddc674f643d7dee5cc3c9c2390b23d029467085a7a9a65a447c691868fddda", "pairs_remaining": [["G01", "mcp"], ["G01", "raw"], ["G11", "mcp"], ["G11", "raw"], ["G16", "mcp"], ["G16", "raw"], ["G19", "mcp"], ["G19", "raw"], ["G12", "mcp"], ["G12", "raw"], ["G04", "mcp"], ["G04", "raw"], ["G17", "mcp"], ["G17", "raw"], ["G20", "mcp"], ["G20", "raw"]], "conditions": {"t": "2026-10-15 10:23:25", "power_source": "Battery Power", "battery_pct": 86, "lowpowermode": 1, "free_kib": 11966156, "swapusage": "vm.swapusage: total = 2048.00M  used = 1082.50M  free = 965.50M  (encrypted)"}, "semantic_model_sha256": "d1d2cd0a49caf648ad0af6fb68bbd7fe9da80ed67da93ab8f2b7def5ae64e82e"}
- start: {"resume": true, "config_sha256": "81ddc674f643d7dee5cc3c9c2390b23d029467085a7a9a65a447c691868fddda", "prior_elapsed_s": 6536.0, "prior_elapsed_note": "session 1: start event 2026-10-15 10:23:25 to SIGTERM 12:12:21 (manual stop)", "pairs_remaining": [["G19", "raw"], ["G12", "mcp"], ["G12", "raw"], ["G04", "mcp"], ["G04", "raw"], ["G17", "mcp"], ["G17", "raw"], ["G20", "mcp"], ["G20", "raw"]], "conditions": {"t": "2026-10-16 10:05:04", "power_source": "Battery Power", "battery_pct": 34, "lowpowermode": 1, "free_kib": 11873520, "swapusage": "vm.swapusage: total = 3072.00M  used = 1949.00M  free = 1123.00M  (encrypted)"}, "semantic_model_sha256": "d1d2cd0a49caf648ad0af6fb68bbd7fe9da80ed67da93ab8f2b7def5ae64e82e"}
- stop: {"reason": "battery_floor", "elapsed_s": 9359.9, "conditions": {"t": "2026-10-16 10:52:08", "battery_pct": 10, "power_source": "Battery Power", "free_kib": 10111304, "swapusage": "vm.swapusage: total = 4096.00M  used = 3313.81M  free = 782.19M  (encrypted)"}}
- start: {"resume": true, "config_sha256": "81ddc674f643d7dee5cc3c9c2390b23d029467085a7a9a65a447c691868fddda", "prior_elapsed_s": 9359.9, "prior_elapsed_note": "cumulative run time from the last stop event (auto-resume)", "pairs_remaining": [["G04", "raw"], ["G17", "mcp"], ["G17", "raw"], ["G20", "mcp"], ["G20", "raw"]], "conditions": {"t": "2026-10-16 11:44:49", "power_source": "AC Power", "battery_pct": 18, "lowpowermode": 1, "free_kib": 10805132, "swapusage": "vm.swapusage: total = 4096.00M  used = 2545.50M  free = 1550.50M  (encrypted)"}, "semantic_model_sha256": "d1d2cd0a49caf648ad0af6fb68bbd7fe9da80ed67da93ab8f2b7def5ae64e82e"}
- stop: {"reason": "queue_complete", "elapsed_s": 12871.0}
- end: {"reason": "queue_complete", "conditions": {"t": "2026-10-16 12:43:20", "power_source": "AC Power", "battery_pct": 87, "lowpowermode": 1, "free_kib": 9570808, "swapusage": "vm.swapusage: total = 5120.00M  used = 4627.06M  free = 492.94M  (encrypted)"}}

## Per-axis results

| arm | answers | a metric | b query | c number | d interpretation |
|---|---|---|---|---|---|
| mcp | 8 | 0/5 (N/A 3) | 0/5 (N/A 3) | 0/5 (N/A 3) | 3/8 |
| raw | 8 | 0/0 (N/A 8) | 0/5 (N/A 3) | 0/5 (N/A 3) | 3/8 |

## Cells

| cell | mcp | raw |
|---|---|---|
| correct | 0 | 0 |
| valid_wrong_question | 0 | 1 |
| valid_misreported | 0 | 0 |
| invalid_right_intent | 0 | 0 |
| invalid_wrong | 3 | 1 |
| no_answer | 0 | 1 |
| correct_abstain | 3 | 3 |
| false_abstain | 1 | 1 |
| unwarranted_answer | 1 | 1 |

- mcp: valid SQL, wrong question = 0/8, Wilson 95 % (0.0, 0.324)
- raw: valid SQL, wrong question = 1/8, Wilson 95 % (0.022, 0.471)

## Per run

| item | arm | s | turns | tool calls (failed) | loop-timeout | tok/s | a | b | c | d | cell | trap | receipts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| G01 | mcp | 689.08 | 1 | 0 (0) | False | 8.13 | False | False | False | False | invalid_wrong | None | none |
| G01 | raw | 715.98 | 2 | 1 (0) | False | 8.73 | N/A | False | False | False | false_abstain | None | none |
| G11 | mcp | 943.05 | 1 | 0 (0) | False | 7.7 | False | False | False | False | invalid_wrong | False | none |
| G11 | raw | 2059.42 | 3 | 2 (0) | False | 7.34 | N/A | False | False | False | valid_wrong_question | False | 9b90d3ac2f |
| G16 | mcp | 1122.52 | 2 | 1 (0) | False | 8.24 | N/A | N/A | N/A | True | correct_abstain | None | none |
| G16 | raw | 318.46 | 1 | 0 (0) | False | 8.67 | N/A | N/A | N/A | True | correct_abstain | None | none |
| G19 | mcp | 245.33 | 2 | 1 (0) | False | 8.65 | N/A | N/A | N/A | True | correct_abstain | None | none |
| G19 | raw | 517.82 | 2 | 1 (0) | False | 8.57 | N/A | N/A | N/A | True | correct_abstain | None | none |
| G12 | mcp | 543.16 | 1 | 0 (0) | False | 8.78 | False | False | False | False | invalid_wrong | False | none |
| G12 | raw | 739.96 | 1 | 0 (0) | False | 8.45 | N/A | False | False | False | invalid_wrong | False | none |
| G04 | mcp | 529.9 | 1 | 0 (0) | False | 9.28 | False | False | False | False | false_abstain | None | none |
| G04 | raw | 1310.28 | 3 | 2 (0) | False | 7.85 | N/A | False | False | False | no_answer | None | 262efa4f26 |
| G17 | mcp | 685.17 | 1 | 0 (0) | False | 7.66 | False | False | False | False | unwarranted_answer | None | none |
| G17 | raw | 1309.34 | 2 | 1 (0) | False | 8.45 | N/A | False | False | False | unwarranted_answer | None | none |
| G20 | mcp | 129.06 | 1 | 0 (0) | False | 9.55 | N/A | N/A | N/A | True | correct_abstain | None | none |
| G20 | raw | 76.43 | 1 | 0 (0) | False | 9.94 | N/A | N/A | N/A | True | correct_abstain | None | none |

Incomplete (saved by a stop, not graded): G04/raw (battery_floor)
