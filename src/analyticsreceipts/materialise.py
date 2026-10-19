"""Materialise expected result tables for the golden set from the pinned snapshot.

Expected tables are produced by compiling each frozen gold resolved_spec, never typed by hand.
Trap items also get the table their NAIVE reading produces, so the grader can tell when an agent
fell into the trap, and so the trap's strength (naive vs gold) is measured rather than assumed.
The compiler itself is checked against independent hand-written SQL in tests/test_reference.py.

Usage: python -m analyticsreceipts.materialise <golden.json> <retail.duckdb> <out.json>
"""

import hashlib
import json
import sys

from .compiler import compile_request
from .execution import Executor, result_sha256
from .model import default_model_path, load

DEDUP = ("SELECT * FROM raw_lines WHERE NOT (source_sheet = 'Year 2010-2011' "
         "AND invoice_ts < TIMESTAMP '2010-12-10 00:00:00')")
PRODUCT = "trim(stock_code) SIMILAR TO '[0-9]{5}[A-Za-z]{0,2}'"

# Each naive reading introduces ONLY the error its trap names (golden-v1 trap.naive_reading).
NAIVE_SQL = {
    "G11": (f"SELECT SUM(CASE WHEN {PRODUCT} THEN quantity * price END) AS v FROM raw_lines "
            "WHERE CAST(invoice_ts AS DATE) BETWEEN DATE '2010-12-01' AND DATE '2010-12-31'"),
    "G12": (f"SELECT SUM(quantity * price) AS v FROM ({DEDUP}) "
            "WHERE CAST(invoice_ts AS DATE) BETWEEN DATE '2011-01-01' AND DATE '2011-11-30'"),
    "G13": (f"SELECT COUNT(DISTINCT invoice) AS v FROM ({DEDUP}) "
            "WHERE CAST(invoice_ts AS DATE) BETWEEN DATE '2011-01-01' AND DATE '2011-11-30'"),
    "G14": (f"SELECT SUM(CASE WHEN {PRODUCT} THEN quantity * price END) / COUNT(DISTINCT CASE WHEN "
            f"invoice NOT LIKE 'C%' AND invoice NOT LIKE 'A%' AND {PRODUCT} AND customer_id IS NOT NULL "
            f"THEN customer_id END) AS v FROM ({DEDUP}) WHERE country = 'United Kingdom' AND "
            "CAST(invoice_ts AS DATE) BETWEEN DATE '2011-01-01' AND DATE '2011-11-30'"),
}


def spec_to_request(spec):
    req = {"metric": spec["metric"],
           "time_range": {"start": spec["period"]["start"], "end": spec["period"]["end"]},
           "filters": [{"dim": f["dim"], "op": f["op"], "value": f.get("value")} for f in spec.get("filters") or []],
           "grain": spec.get("grain"), "dimensions": list(spec.get("dimensions") or [])}
    if spec.get("comparison"):
        req["comparison_range"] = dict(spec["comparison"]["period"])
    if spec.get("ranking"):
        req["ranking"] = {"direction": spec["ranking"]["direction"], "limit": spec["ranking"]["limit"]}
    return req


def materialise(golden_path, db_path, model_path=None, compile_fn=compile_request):
    golden_bytes = open(golden_path, "rb").read()
    golden = json.loads(golden_bytes)
    model = load(model_path or default_model_path())
    ex = Executor(db_path)
    out = {"golden_sha256": hashlib.sha256(golden_bytes).hexdigest(), "semantic_model_sha256": model.sha256,
           "snapshot": ex.snapshot, "items": {}}
    for it in golden["items"]:
        spec = it.get("resolved_spec")
        if not spec:
            continue
        q = compile_fn(model, spec_to_request(spec))
        cols, rows, trunc, err = ex.run(q.sql, q.params)
        if err or trunc:
            raise RuntimeError(f"{it['id']}: {err or 'truncated'}")
        e = {"columns": cols, "rows": rows, "result_sha256": result_sha256(cols, rows),
             "compiled_sql_sha256": q.sha256, "metric_def_version": model.metrics[spec["metric"]].meta.get("version"),
             "naive": None, "trap_strength": None}
        if it["id"] in NAIVE_SQL:
            ncols, nrows, _, nerr = ex.run(NAIVE_SQL[it["id"]])
            if nerr:
                raise RuntimeError(f"{it['id']} naive: {nerr}")
            e["naive"] = {"columns": ncols, "rows": nrows}
            g, n = float(rows[0][-1]), float(nrows[0][-1])
            e["trap_strength"] = {"gold": g, "naive": n, "naive_minus_gold": n - g,
                                  "relative": (n - g) / abs(g) if g else None}
        out["items"][it["id"]] = e
    return out


if __name__ == "__main__":
    res = materialise(sys.argv[1], sys.argv[2])
    with open(sys.argv[3], "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
        f.write("\n")
    for k, v in res["items"].items():
        print(k, v["rows"][:3], v["trap_strength"])
