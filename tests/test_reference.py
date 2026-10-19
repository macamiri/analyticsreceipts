"""The compiler against independent, hand-written SQL.

Each reference query below was written from the golden set's conventions (C1-C8) directly against
`raw_lines`, without the semantic model or the compiler. If the compiler and the reference agree on
every answerable golden item, the expected tables are not just the compiler agreeing with itself.
Needs the warehouse: set ANALYTICSRECEIPTS_DB (built by `python -m analyticsreceipts.load`).
"""

import json
import os
from pathlib import Path

import pytest

from analyticsreceipts.compiler import compile_request
from analyticsreceipts.execution import Executor
from analyticsreceipts.grader import table_match
from analyticsreceipts.materialise import spec_to_request
from analyticsreceipts.model import default_model_path, load

DB = os.environ.get("ANALYTICSRECEIPTS_DB")
pytestmark = pytest.mark.skipif(not DB or not Path(DB).exists(), reason="ANALYTICSRECEIPTS_DB not built")
GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "golden-v1.json"

L = ("(SELECT *, trim(stock_code) AS sc FROM raw_lines WHERE NOT (source_sheet = 'Year 2010-2011' "
     "AND invoice_ts < TIMESTAMP '2010-12-10 00:00:00'))")
PROD = "regexp_full_match(sc, '[0-9]{5}[A-Za-z]{0,2}')"
ORDER_LINE = f"(left(invoice, 1) NOT IN ('C', 'A') AND {PROD})"
D = "CAST(invoice_ts AS DATE)"

REFERENCE = {
    "G01": f"SELECT sum(quantity*price) FILTER (WHERE {PROD}) FROM {L} WHERE country='United Kingdom' AND {D} >= DATE '2011-11-01' AND {D} < DATE '2011-12-01'",
    "G02": f"SELECT strftime({D}, '%Y-%m'), sum(quantity*price) FILTER (WHERE {PROD}) FROM {L} WHERE {D} >= DATE '2011-01-01' AND {D} < DATE '2011-07-01' GROUP BY 1",
    "G03": f"SELECT country, sum(quantity*price) FILTER (WHERE {PROD}) AS r FROM {L} WHERE country <> 'United Kingdom' AND {D} >= DATE '2011-01-01' AND {D} < DATE '2011-12-01' GROUP BY 1 ORDER BY r DESC LIMIT 5",
    "G04": f"SELECT count(DISTINCT customer_id) FILTER (WHERE {ORDER_LINE}) FROM {L} WHERE country='Germany' AND {D} >= DATE '2011-01-01' AND {D} < DATE '2011-12-01'",
    "G05": f"SELECT sum(quantity) FILTER (WHERE {ORDER_LINE}) FROM {L} WHERE sc='85123A' AND {D} >= DATE '2011-01-01' AND {D} < DATE '2011-12-01'",
    "G06": f"SELECT (count(DISTINCT invoice) FILTER (WHERE invoice LIKE 'C%'))::DOUBLE / count(DISTINCT invoice) FILTER (WHERE invoice NOT LIKE 'A%') FROM {L} WHERE {D} >= DATE '2011-01-01' AND {D} < DATE '2011-04-01'",
    "G07": f"SELECT 'Q' || quarter({D}) || ' ' || year({D}), count(DISTINCT invoice) FILTER (WHERE {ORDER_LINE}) FROM {L} WHERE country='Netherlands' AND {D} >= DATE '2011-01-01' AND {D} < DATE '2011-10-01' GROUP BY 1",
    "G08": f"SELECT -sum(quantity) FILTER (WHERE invoice LIKE 'C%' AND {PROD}) FROM {L} WHERE {D} >= DATE '2011-01-01' AND {D} < DATE '2011-12-01'",
    "G09": (f"SELECT sum(quantity*price) FILTER (WHERE {PROD} AND {D} >= DATE '2011-10-01' AND {D} < DATE '2011-11-01'), "
            f"sum(quantity*price) FILTER (WHERE {PROD} AND {D} >= DATE '2010-10-01' AND {D} < DATE '2010-11-01') FROM {L} WHERE country='United Kingdom'"),
    "G10": f"SELECT sum(quantity*price) FILTER (WHERE {PROD}) FROM {L} WHERE customer_id IS NULL AND {D} >= DATE '2011-01-01' AND {D} < DATE '2011-12-01'",
    "G11": f"SELECT sum(quantity*price) FILTER (WHERE {PROD}) FROM {L} WHERE {D} >= DATE '2010-12-01' AND {D} < DATE '2011-01-01'",
    "G12": f"SELECT sum(quantity*price) FILTER (WHERE {PROD}) FROM {L} WHERE {D} >= DATE '2011-01-01' AND {D} < DATE '2011-12-01'",
    "G13": f"SELECT count(DISTINCT invoice) FILTER (WHERE {ORDER_LINE}) FROM {L} WHERE {D} >= DATE '2011-01-01' AND {D} < DATE '2011-12-01'",
    "G14": (f"SELECT sum(quantity*price) FILTER (WHERE {PROD} AND customer_id IS NOT NULL) / "
            f"count(DISTINCT customer_id) FILTER (WHERE {ORDER_LINE}) FROM {L} WHERE country='United Kingdom' AND {D} >= DATE '2011-01-01' AND {D} < DATE '2011-12-01'"),
    "G15": (f"SELECT sum(quantity*price) FILTER (WHERE {PROD} AND {D} >= DATE '2011-12-01'), "
            f"sum(quantity*price) FILTER (WHERE {PROD} AND {D} >= DATE '2011-11-01' AND {D} < DATE '2011-12-01') FROM {L}"),
}
WIDE = {"G09", "G15"}  # reference returns current and comparison side by side: compare as two rows


@pytest.fixture(scope="module")
def env():
    return load(default_model_path()), Executor(DB), json.loads(GOLDEN.read_text())


@pytest.mark.parametrize("item_id", sorted(REFERENCE))
def test_compiler_equals_reference(env, item_id):
    model, ex, golden = env
    item = next(i for i in golden["items"] if i["id"] == item_id)
    q = compile_request(model, spec_to_request(item["resolved_spec"]))
    cols, rows, _, err = ex.run(q.sql, q.params)
    assert err is None
    rcols, rrows, _, rerr = ex.run(REFERENCE[item_id])
    assert rerr is None, rerr
    if item_id in WIDE:
        # label the reference's two columns, so a compiler that swaps the period labels fails here
        rrows = [["current", rrows[0][0]], ["comparison", rrows[0][1]]]
        rcols = ["period", "v"]
    assert table_match({"columns": rcols, "rows": rrows}, cols, rows), (rrows, rows)
    assert table_match({"columns": cols, "rows": rows}, rcols, rrows)


def test_every_answerable_item_has_a_reference(env):
    _, _, golden = env
    answerable = {i["id"] for i in golden["items"] if i.get("resolved_spec")}
    assert answerable == set(REFERENCE)
