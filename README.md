# analyticsreceipts

Per-answer receipts for AI analytics agents, and a grader that records which part of the question an answer got wrong: the metric, a filter, the period or the grain. Every query an agent runs leaves a receipt (the request, the compiled SQL and its parameters, the result and its hash) that you can re-run and check. The grader uses the receipt and the agent's stated reading of the question to separate an answer that is right from one whose query ran fine and answered a different question.

> Every eval result below comes from a committed replay or report in this repository.

## Who this is for

When people ask an AI assistant a business question, like "what was revenue in Germany last November?", the assistant writes a database query, runs it and reports a number. The query can run perfectly and still answer a slightly different question: revenue including refunds, or a month that only has nine days of data. Nothing in the answer warns you. This tool is for teams who run an AI assistant over their company's metric definitions. It asks the assistant a fixed set of questions with known answers. For every answer it records exactly which metric definition was used, which filters and dates were applied, the query that ran and the result it produced. Then it tells you, answer by answer, whether the assistant got the metric, the numbers and the meaning of the question right. It also counts the answers where the query ran fine but answered the wrong question.

## What it catches

These are the six answers in the fixture set whose query ran but answered a different question. The fixtures are recorded transcripts with planted failures, so these are test cases rather than model behaviour. Each line gives what the receipt and the grader show.

| question | what the answer did | what the grader records |
|---|---|---|
| Revenue in the United Kingdom in November 2011 | queried `units_sold` and reported it as revenue | metric differs: `units_sold`, gold `net_product_revenue`; result table does not match |
| UK revenue in October 2011 compared with October 2010 | compared with September 2011 instead of October 2010 | spec field `comparison` differs; result table does not match |
| Revenue in December 2011 compared with November 2011 | right numbers, but did not flag that December 2011 ends on the 9th | spec field `incomplete` differs; trap `incomplete-month` sprung |
| Total revenue in December 2010 | raw SQL summed both yearly sheets, so a nine-day window counts twice | result table equals the trap's naive reading (`sheet-overlap`) |
| Orders placed between January and November 2011 | raw SQL counted cancellation and bad-debt invoices as orders | trap `cancellation-invoices-as-orders` sprung |
| Average revenue per UK customer, January to November 2011 | raw SQL kept revenue with no customer id in the numerator | trap `unattributed-revenue-in-numerator` sprung |

In the last three the agent stated the right reading of the question, and the receipt shows the SQL that did something else.

These results come from the fixture harness: 26 recorded agent transcripts with planted failures, run through the real server against the real warehouse. No model is involved, so they test the grader and the server.

- The grader agreed with grades written down before it ever ran, on all 26 fixtures and on every axis.
- It found the 6 answers above whose query ran but answered the wrong question, the same count under rule ER-1.
- The canary, a question with an independently computed answer (18,980,128.63), passed.
- A deliberately broken compiler that counts the duplicated nine-day window twice failed the canary (19,382,476.01). Exactly one fixture grade changed, the one registered in advance.

Reproduce it with the commands in the next section; the output is `reports/m1-fixtures.md`.

## What is in the box

1. A semantic model of the UCI Online Retail II dataset (CC BY 4.0), written in the Apache Ossie format. It encodes three conventions a naive query gets wrong: the two yearly sheets share an identical nine-day window, some stock codes are fees or adjustments rather than products, and December 2011 ends on the 9th.
2. A read-only MCP server (stdio, official `mcp` SDK) with five tools: `list_metrics`, `get_metric`, `list_dimensions`, `get_dimension_values` and `query_metric`. It has no raw SQL tool. A request it cannot answer from a governed metric returns a typed refusal (`needs_clarification`, `no_governed_metric` or `invalid_request`). Every `query_metric` result carries a receipt. Concurrent tool calls are safe: each call gets its own database cursor and its own timeout. At most 4 queries run at once, and the read-only database is capped at 1 GB of memory and 2 threads, with no temporary files on disk.
3. A deterministic grader. No model is used to grade. It scores four axes:

| axis | question it answers |
|---|---|
| a, metric | did the receipt use the gold metric id and version? (governed arm only) |
| b, query | does the last successful result table equal the expected table? |
| c, number | does every number the answer states match an expected value within its rounding? |
| d, interpretation | does the agent's stated reading (metric, filters, period, grain, ranking) equal gold, field by field? |

Each answer lands in exactly one cell. The headline cell, `valid_wrong_question`, means the query ran and its result answers a different question: the table does not match, or a trap was sprung. Rule ER-1 in `grader.py` fixes the meaning of every cell and the only two spec equivalences the grader accepts.

4. Two harnesses. `fixtures` replays recorded transcripts with planted failures through the real server, with no model involved. `live` runs a local model through Ollama in two arms: the MCP tools, and plain `describe_tables` plus `run_sql`. `run_sql` takes one statement that starts with SELECT or WITH, and file paths in its error messages are replaced by `<path>`.

## Install and first result (about a minute, no model needed)

The eval data (the golden set, the fixtures and the replays) lives in the repository, so start from a clone:

```bash
git clone https://github.com/macamiri/analyticsreceipts && cd analyticsreceipts
python -m venv .venv && . .venv/bin/activate
pip install ".[load,test]"
curl -LO https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip
unzip online+retail+ii.zip
python -m analyticsreceipts.load online_retail_II.xlsx retail.duckdb
python -m analyticsreceipts.fixtures --db retail.duckdb --out fixtures-v1.json
python -m analyticsreceipts.report fixtures fixtures-v1.json --out m1-fixtures.md
```

The last command prints `agreement 26/26`. `m1-fixtures.md` shows the 6 wrong-question answers and the canary result.

Measured on a clean venv on a 16 GB M1 laptop, on battery in low power mode, timed with `/usr/bin/time` (the clone itself not included):

| step | seconds |
|---|---|
| venv | 2.7 |
| pip install | 8.8 |
| download (45.6 MB) | 15.8 |
| unzip | 0.5 |
| load | 42.3 |
| fixtures | 4.0 |
| report | 0.1 |
| total | 74.1 |

To serve the model to your own MCP client:

```bash
python -m analyticsreceipts.server --db retail.duckdb            # bundled Online Retail II model
python -m analyticsreceipts.server --db your.duckdb --model your_model.ossie.yaml
```

The server and the grader work from a plain `pip install`. The fixture and live harnesses need the eval data: run them from a clone's root, or set `ANALYTICSRECEIPTS_ROOT` to it.

## Run the tests

From the clone, after the load step above:

```bash
export ANALYTICSRECEIPTS_DB=$PWD/retail.duckdb
pytest -q tests        # 154 passed, 1 skipped (about 10 s)
```

The one skip is a test that needs a prompt snapshot kept out of the repository. Without `ANALYTICSRECEIPTS_DB`, the 42 tests that need the warehouse are also skipped (112 passed, 43 skipped), and pytest ends with a red "42 WAREHOUSE TESTS DID NOT RUN" banner instead of a clean pass.

## Receipt format

Every receipt validates against the JSON Schema in `src/analyticsreceipts/receipt.schema.json`, which ships in the wheel:

```python
from analyticsreceipts.receipts import validate_receipt
validate_receipt(receipt)   # raises jsonschema.ValidationError on a malformed receipt
```

This is a real receipt, copied unchanged from `replays/fixtures-v1.json` (fixture F01: UK revenue in November 2011). It was recorded as `receipt_version` "1". Receipts written now are version "2": they add a required `compiler` field (`"governed"` for the governed compiler) and no longer include a `non_additive_guard` check, which only ever reported success. The committed replays keep format v1, so the planted-compiler replay labels its receipts `governed_metric` (see `golden/EXPECTED-V1-DIVERGENCE.md`).

```json
{
  "receipt_version": "1",
  "kind": "governed_metric",
  "request": {
    "metric": "net_product_revenue",
    "time_range": {
      "start": "2011-11-01",
      "end": "2011-11-30"
    },
    "comparison_range": null,
    "grain": null,
    "dimensions": [],
    "filters": [
      {
        "dim": "country",
        "op": "eq",
        "value": "United Kingdom"
      }
    ],
    "ranking": null
  },
  "metric_id": "net_product_revenue",
  "metric_def_version": "1.0.0",
  "semantic_model_sha256": "d1d2cd0a49caf648ad0af6fb68bbd7fe9da80ed67da93ab8f2b7def5ae64e82e",
  "compiled_sql": "WITH lines AS (SELECT * FROM raw_lines WHERE NOT (source_sheet = 'Year 2010-2011' AND invoice_ts < TIMESTAMP '2010-12-10 00:00:00')) SELECT * FROM (SELECT SUM(CASE WHEN (trim(stock_code) SIMILAR TO '[0-9]{5}[A-Za-z]{0,2}') THEN (quantity * price) END) AS net_product_revenue FROM lines WHERE CAST(invoice_ts AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) AND country = ?) AS q LIMIT 1001",
  "params": [
    "2011-11-01",
    "2011-11-30",
    "United Kingdom"
  ],
  "compiled_sql_sha256": "22507f3f57a993105c7df573833c5ea95fc138126bad0a8167619c6cfca1cb1c",
  "engine": {
    "name": "duckdb",
    "version": "1.5.6"
  },
  "snapshot": {
    "source_xlsx_sha256": "bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980",
    "max_invoice_ts": "2011-12-09T12:50:00",
    "db_file_sha256": "c2f31a41753548a1ba21d48e152901cf40e1502637d204f1788bad035934310b"
  },
  "result": {
    "columns": [
      "net_product_revenue"
    ],
    "rows": [
      [
        1264300.58
      ]
    ]
  },
  "result_sha256": "7557a08caf0bac91bd49730d54ae371a490f5a7836e58df85cb995c23b7bd423",
  "row_count": 1,
  "truncated": false,
  "error": null,
  "checks": [
    {
      "name": "time_range_complete",
      "success": true,
      "expected": "end <= last data date 2011-12-09",
      "actual": "2011-11-30",
      "note": null
    },
    {
      "name": "time_range_starts_in_data",
      "success": true,
      "expected": "start >= 2009-12-01",
      "actual": "2011-11-01"
    },
    {
      "name": "non_additive_guard",
      "success": true,
      "expected": "ratio/count-distinct computed from components in every group",
      "actual": "additive metric"
    },
    {
      "name": "row_cap",
      "success": true,
      "expected": "<= 1000 rows",
      "actual": 1
    }
  ],
  "uncertainty": {
    "caveats_applied": [
      "C1",
      "C2",
      "C3"
    ]
  },
  "run": {
    "request_id": "63e876cddd1b40578fdf5df07e531f71",
    "server_version": "0.0.1",
    "started_at": "2026-10-15T09:32:19.203",
    "elapsed_s": 0.013
  }
}
```

To re-check a receipt, run its SQL through the same executor, against the warehouse whose file hash is `snapshot.db_file_sha256`. The executor normalises cell values before hashing, so a plain DuckDB query returns `Decimal('1264300.580')` here and hashes differently.

```python
from analyticsreceipts.execution import Executor, result_sha256
cols, rows, truncated, err = Executor("retail.duckdb").run(receipt["compiled_sql"], receipt["params"])
assert result_sha256(cols, rows) == receipt["result_sha256"]
```

The frozen pre-registration, `golden/expected-v1.json`, has three SQL hashes (G02, G03, G07) that predate two compiler fixes, with identical result tables, so `golden/expected-v2.json` is canonical (see `golden/EXPECTED-V1-DIVERGENCE.md`).

## Validated examples

Dataset: UCI Online Retail II, https://archive.ics.uci.edu/dataset/502/online+retail+ii
Task: 26 recorded transcripts (17 MCP arm, 9 raw SQL arm) with planted failures, graded against 20 frozen golden questions.
Result: see "What it catches" above. 26 of 26 grades match the pre-registered ones; 6 answers ran and answered the wrong question; the canary passed; the broken compiler failed it.
Reproducible with: the commands above; the output is `reports/m1-fixtures.md`.

## Field note: a small local model (tiny N)

This is a field note and makes no benchmark claim. The model was `qwen3:4b` through Ollama, with one run per item and arm on 8 items, on a 16 GB M1 laptop. Each grade count is given twice: "as run" (the grader at the time of the run) and "under ER-1" (the rule adopted after the run; its prediction was not blind, see `reports/m1-er1-regrade.md`).

| run | arm | correct (as run / ER-1) | query ran, wrong question (as run / ER-1) | right table, misstated spec (as run / ER-1) |
|---|---|---|---|---|
| original prompt | MCP | 0 / 0 | 0 / 0 | 0 / 0 |
| original prompt | raw SQL | 0 / 0 | 1 / 1 | 0 / 0 |
| one added prompt sentence | MCP | 1 / 2 | 2 / 1 | 0 / 0 |
| one added prompt sentence | raw SQL | 0 / 0 | 1 / 0 | 0 / 1 |

- With the original prompt, the model made 0 `query_metric` calls in 8 runs.
- The added sentence told it to call `list_metrics` and then `query_metric`. After that, the MCP arm made 6 such calls.
- The one answer still counted as "wrong question" under ER-1 dropped the United Kingdom filter.
- The median MCP arm loop took 1,205 s.
- N is tiny, so these numbers are counts only; they support no comparison between arms.

Reproducible with: `reports/m1-live-lite.md`, `reports/m1-live-lite-v2.md` and `reports/m1-er1-regrade.md`, all generated offline from the committed replays.

## Related work

- Lee (2026), "Business Truth, not SQL Accuracy" (arXiv:2608.09254), introduces WarehouseReliabilityBench: 400 frozen tasks over two synthetic warehouses, where roughly half the correct responses are a clarification, an abstention or a refusal. It names the failure this tool counts: "queries that execute successfully while returning the wrong business number". Its answerable tasks are scored by "result equivalence against one or more accepted SQL programs", and the rest "against a behaviour contract". Its agent, QueryProof, checks inside the agent that the "filters applied, period applied" match the metric definition before it answers.
- [slayer-evals](https://github.com/MotleyAI/slayer-evals) asks "Do agents actually reach for SLayer's DSL — and does it beat raw SQL on correctness?". It includes traps "where the straightforward SQL silently returns wrong numbers", and each trial gets two verdicts, "correct" and "single query".
- Sourati et al. (2026), "Same Context, Different Agents" (arXiv:2610.20959), study semantic layers, orchestration and compaction across 1,514 tasks. Among other findings, they describe "premature answerers that answer without inspecting data", and investigators for whom "the semantic layer stops them from looking". The field note above shows a small local model skipping the tools in the same way.
- [semantic-layer-mcp-eval](https://github.com/rahulsuravarapu29/semantic-layer-mcp-eval) is a small prototype with "an MCP server that exposes it to an AI agent, and an evaluation with a golden answer set and a gap matrix". Its README notes that "the raw-SQL attempts are hand-written to represent common failure patterns".

What this project adds to that work:
- For each answer it records which field the answer got wrong (metric, filter, period, grain, comparison, the incomplete-period flag) by comparing the agent's stated reading with a golden reading.
- It keeps a receipt for every query, with the compiled SQL, its parameters and a hash of the result, that anyone can re-run against the same warehouse.
- It grades through a server that has no raw SQL tool, over your own Ossie semantic model.

How the search was done (2026-10-18):
- Sources: GitHub repository and code search; PyPI's full project-name index; the arXiv API (newest first); and Hacker News. Each source was checked with a query that must return a known result before its other results were read.
- Not checked: PyPI's search page, which blocked automated requests, so PyPI package descriptions were not read. GitHub code search does not index small new repositories, so code inside such repositories was not searched.
- Projects created after that date are not covered.

## When not to use this

- To rank models or compare two agents. The bundled golden set has 20 questions, which supports no comparison. The power of an exact McNemar test at this N is at most 0.196.
- As a decision rule. The tool reports measurements and receipts. It does not tell you whether to ship.
- If your metrics live outside an Ossie model. The compiler reads only Ossie YAML.
- For prose answers with unusual number formats. Axis c parses common forms (thousands separators, k/m/bn, percentages, currency signs) and ignores counts like "top 5" or "9 days". Anything else may be graded wrong.

## Where this breaks

- Your own model with free-text dimensions. `query_metric` returns result rows to the agent as they are, without truncation and without marking them as untrusted data. `get_dimension_values` does both: it marks values as untrusted and cuts each one to 80 characters. In the bundled model the longest value of any dimension is 20 characters (a country name). In a model that groups by comments or product descriptions, any text stored in the data reaches the agent verbatim, and that is a prompt-injection route. Treat the server as admitted for such models only after you add your own wrapping.
- Answers written in SQL vocabulary. Free-form specs from the raw SQL arm are never mapped to governed names. A right number stated as `count(DISTINCT customer_id)` lands in `valid_misstated_spec`, and does not count as correct.
- Small models that skip the tools. With the original prompt, `qwen3:4b` wrote its final answer on the first turn, without calling a tool, in 6 of 8 MCP arm runs. Every answer it gave used the metric name "revenue", which does not exist in the model. The grader reports this correctly, but the receipts then say nothing about the semantic layer.
- Number formats outside the parser. Axis c reads thousands separators, k/m/bn, percentages and currency signs. An answer in another format can be graded wrong.

## Known limitations

- The gold expected tables are computed by the compiler under test. For 15 of 20 items they are cross-checked against independent hand-written SQL in `tests/test_reference.py`.
- The `replays/*.resources.log` files are kept as recorded: once a minute during the live runs they logged the time, battery level, power source, free disk space and swap use of the laptop that ran them.

## How it was built

Built with help from coding agents. A person reviewed the golden set before it was frozen.

## License

MIT for the code. The dataset is CC BY 4.0 (UCI, DOI 10.24432/C5CG6D). The Ossie schema is vendored under its own licence; see `vendor/ossie/`.
