# M1 FIXTURES report

**Label: FIXTURES.** Recorded transcripts with planted failures, executed against the real server, raw-SQL tools and grader. These are not model outputs and say nothing about any model.

Inputs: transcripts `61e022183498`, expected grades `fa54230acf3d`, golden `9472869d5b1a`, expected tables `345dd5cd0048`, semantic model `d1d2cd0a49ca`.

## Grader vs pre-registered expected grades

Agreement: **26/26** fixtures match on every field (a, b, c, d, cell, trap_sprung).

## Per-axis results

| arm | answers | a metric | b query | c number | d interpretation |
|---|---|---|---|---|---|
| mcp | 17 | 10/15 (N/A 2) | 9/15 (N/A 2) | 8/15 (N/A 2) | 11/17 |
| raw | 9 | 0/0 (N/A 9) | 3/8 (N/A 1) | 3/8 (N/A 1) | 7/9 |

## Cells

| cell | mcp | raw |
|---|---|---|
| correct | 7 | 3 |
| valid_wrong_question | 3 | 3 |
| valid_misreported | 1 | 0 |
| invalid_right_intent | 1 | 0 |
| invalid_wrong | 0 | 0 |
| no_answer | 1 | 1 |
| correct_abstain | 2 | 1 |
| false_abstain | 1 | 0 |
| unwarranted_answer | 1 | 1 |

Valid SQL, wrong question (headline count): **6**.

Traps sprung: 4 of 8 trap answers.

## Controls

- Canary (known answer 18980128.63): result 18980128.63, **PASS**.
- Planted broken compiler (`drop_c1`): canary result 19382476.01, **FAIL (as required)**.
- Grades that changed under the broken compiler: F26 {'b': (True, False), 'c': (True, False), 'cell': ('correct', 'valid_wrong_question'), 'trap_sprung': (False, True)}. Pre-registered change: ['F26']. **As pre-registered**.

## Per-fixture grades

| fixture | arm | item | planted | a | b | c | d | cell | trap |
|---|---|---|---|---|---|---|---|---|---|
| F01 | mcp | G01 | none (correct) | True | True | True | True | correct | None |
| F02 | mcp | G12 | none (governed metric excludes non-product rows) | True | True | True | True | correct | False |
| F03 | mcp | G01 | axis a: wrong governed metric (units_sold) reported as revenue | False | False | False | False | valid_wrong_question | None |
| F04 | mcp | G09 | axis d + b: compared with September 2011 instead of October 2010 | True | False | False | False | valid_wrong_question | None |
| F05 | mcp | G01 | axis c only: correct query, number misreported by +10% | True | True | False | True | valid_misreported | None |
| F06 | mcp | G15 | axis d only (trap): incomplete December not flagged | True | True | True | False | valid_wrong_question | True |
| F07 | mcp | G15 | none (incomplete period flagged) | True | True | True | True | correct | False |
| F08 | mcp | G16 | none (correct clarification) | N/A | N/A | N/A | True | correct_abstain | None |
| F09 | mcp | G19 | none (correct abstention after no_governed_metric) | N/A | N/A | N/A | True | correct_abstain | None |
| F10 | mcp | G04 | false abstention on an answerable item | False | False | False | False | false_abstain | None |
| F11 | mcp | G19 | unwarranted answer: revenue reported as profit margin | False | False | False | False | unwarranted_answer | None |
| F12 | mcp | G05 | tool-call failure: malformed filter op, then no final message | False | False | False | False | no_answer | None |
| F13 | mcp | G06 | tool-call failure, then an invented number with the right spec | False | False | False | True | invalid_right_intent | None |
| F14 | mcp | G06 | none (ratio stated as a percentage) | True | True | True | True | correct | None |
| F15 | mcp | G07 | none (quarterly grain, three rows) | True | True | True | True | correct | None |
| F16 | mcp | G03 | none (ranking with a negated filter) | True | True | True | True | correct | None |
| F17 | raw | G11 | trap: sheet overlap counted twice | N/A | False | False | True | valid_wrong_question | True |
| F18 | raw | G11 | none (overlap removed) | N/A | True | True | True | correct | False |
| F19 | raw | G13 | trap: cancellation and bad-debt invoices counted as orders | N/A | False | False | True | valid_wrong_question | True |
| F20 | raw | G14 | trap: unattributed revenue in the numerator | N/A | False | False | True | valid_wrong_question | True |
| F21 | raw | G02 | none (months written as YYYY-MM) | N/A | True | True | True | correct | None |
| F22 | raw | G03 | tool-call failure (bad column), then a prose reply that breaks the output contract | N/A | False | False | False | no_answer | None |
| F23 | raw | G10 | none (null customer filter) | N/A | True | True | True | correct | None |
| F24 | raw | G18 | none (correct clarification) | N/A | N/A | N/A | True | correct_abstain | None |
| F25 | raw | G20 | unwarranted answer: an invented visitor count | N/A | False | False | False | unwarranted_answer | None |
| F26 | mcp | G11 | none (correct); the planted broken compiler control flips it | True | True | True | True | correct | False |
