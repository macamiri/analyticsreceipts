# Re-grade under rule ER-1 (equivalence + cell partition)

**Label: POST-HOC offline re-grade.** No model was called. Every committed replay was graded twice: by the grader before ER-1 and by the grader with ER-1 plus the number-parsing, tolerance and edge-case fixes made at the same time. Frozen expected grades and the golden set are unchanged.

## The rule (written and logged with its expected effect before any count was computed)
- **E1, single-bucket grain:** a grain counts as "no grain" when every period in the spec lies inside one bucket of that grain. Example: grain `month` over 2010-12-01 to 2010-12-31.
- **E2, one-value set:** `in [x]` counts as `eq x`.
- **Cell partition:** the headline cell `valid_wrong_question` now means the executed query answered a different question: the result table does not match, or a trap was sprung. A right table with a misstated spec is `valid_misstated_spec`. A right table where only the receipt's metric id or version fails is `valid_metric_mismatch`.
- Nothing that depends on the data is treated as equivalent. Free-form spec vocabulary from the raw-SQL arm is never mapped to governed names.

## Cell counts, before → after (an unchanged cell shows one number)

| set | arm | correct | correct_abstain | false_abstain | invalid_right_intent | invalid_wrong | no_answer | unwarranted_answer | valid_misreported | valid_misstated_spec | valid_wrong_question |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fixtures | mcp | 7 | 2 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 3 |
| fixtures | raw | 3 | 1 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 3 |
| fixtures, planted broken compiler | mcp | 6 | 2 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 4 |
| fixtures, planted broken compiler | raw | 3 | 1 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 3 |
| LIVE-LITE v1 | mcp | 0 | 3 | 1 | 0 | 3 | 0 | 1 | 0 | 0 | 0 |
| LIVE-LITE v1 | raw | 0 | 3 | 1 | 0 | 1 | 1 | 1 | 0 | 0 | 1 |
| LIVE-LITE v2 | mcp | 1→2 | 2 | 0 | 0 | 0 | 1 | 2 | 0 | 0 | 2→1 |
| LIVE-LITE v2 | raw | 0 | 3 | 1 | 0 | 2 | 0 | 1 | 0 | 0→1 | 1→0 |

`valid_metric_mismatch` is 0 in every row, both before and after.

## What changed
- Fixtures: 0 of 26 grades changed. All 26 still equal the frozen expected grades. The planted broken compiler still fails the canary, and its fixture grades did not change.
- LIVE-LITE v1: 0 of 16 grades changed.
- LIVE-LITE v2: 2 of 16 grades changed.
  - **G11, MCP arm:** right table and right number (760,257.78), with the spec at grain `month` over one calendar month. Axis d now passes by E1, so the cell goes `valid_wrong_question` → `correct`.
  - **G04, raw arm:** right table and right number (92), with a spec written in SQL vocabulary. Axis d still fails, so the cell goes `valid_wrong_question` → `valid_misstated_spec`.
- The only remaining headline cell in v2 is G01 in the MCP arm. It returned total November revenue (1,432,731.70) with no United Kingdom filter, so the query really did answer a different question.
- These counts matched the expected effect logged before the re-grade. That prediction was not blind: the two affected runs had already been named in the v2 report's caveat.

## Direction of the changes
Both changes point the same way: fewer headline cells and one more correct answer, in favour of the agent arms. Read the rule as a correction to the meaning of the headline cell. It is not a stricter grader. The number-parsing and tolerance fixes go both ways:
- stricter: ratio cells now use a 0.5 % relative tolerance; a rounded number must be within 5 % of the value; year-shaped values are checked outside a year context;
- more lenient: counts in phrases like "top 5" or "9 days" and ordinals are not treated as asserted values.

None of them changed any committed grade.

## Reproduce
The script and both result JSON files are kept with the build's internal review files; the counts above are copied from their output. Re-run the v1-vs-v2 side by side with:
`python -m analyticsreceipts.compare replays/live-lite-v1.jsonl replays/live-lite-v2.jsonl --names v1,v2`
