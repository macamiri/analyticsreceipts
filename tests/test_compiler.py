"""Compiler rules, one test each (compiler.py docstring). No warehouse needed except where marked."""

import os
from pathlib import Path

import pytest

from analyticsreceipts.compiler import RequestError, compile_request
from analyticsreceipts.model import default_model_path, load

M = load(default_model_path())
BASE = {"metric": "net_product_revenue", "time_range": {"start": "2011-01-01", "end": "2011-01-31"}}
DB = os.environ.get("ANALYTICSRECEIPTS_DB")
needs_db = pytest.mark.skipif(not DB or not Path(DB).exists(), reason="ANALYTICSRECEIPTS_DB not built")


def test_deterministic_bytes_and_hash():
    a = compile_request(M, dict(BASE, filters=[{"dim": "country", "op": "eq", "value": "EIRE"},
                                               {"dim": "stock_code", "op": "eq", "value": "85123A"}]))
    b = compile_request(M, dict(BASE, filters=[{"dim": "stock_code", "op": "eq", "value": "85123A"},
                                               {"dim": "country", "op": "eq", "value": "EIRE"}]))
    assert a.sql == b.sql and a.params == b.params and a.sha256 == b.sha256


def test_filter_values_are_bound_never_interpolated():
    evil = "x'; DROP TABLE raw_lines; --"
    q = compile_request(M, dict(BASE, filters=[{"dim": "country", "op": "eq", "value": evil}]))
    assert evil not in q.sql and evil in q.params


@pytest.mark.parametrize("req,rtype", [
    ({"metric": "profit_margin", "time_range": BASE["time_range"]}, "no_governed_metric"),
    ({"time_range": BASE["time_range"]}, "needs_clarification"),
    ({"metric": "orders"}, "needs_clarification"),
    (dict(BASE, dimensions=["description"]), "invalid_request"),
    (dict(BASE, filters=[{"dim": "country", "op": "like", "value": "U%"}]), "invalid_request"),
    (dict(BASE, filters=[{"dim": "invoice_date", "op": "eq", "value": "2011-01-01"}]), "invalid_request"),
    (dict(BASE, time_range={"start": "2011-02-01", "end": "2011-01-01"}), "invalid_request"),
    (dict(BASE, time_range={"start": "Jan 2011", "end": "2011-01-31"}), "invalid_request"),
    (dict(BASE, ranking={"direction": "desc", "limit": 5}), "invalid_request"),  # ranking without a dimension
])
def test_refusals_are_typed(req, rtype):
    with pytest.raises(RequestError) as e:
        compile_request(M, req)
    assert e.value.result_type == rtype


def test_unknown_metric_offers_candidates():
    with pytest.raises(RequestError) as e:
        compile_request(M, {"metric": "revenue", "time_range": BASE["time_range"]})
    assert "net_product_revenue" in e.value.candidates


def test_no_raw_sql_path():
    with pytest.raises(RequestError):
        compile_request(M, dict(BASE, metric="SUM(price) FROM raw_lines; --"))


@needs_db
def test_ratio_is_computed_from_components_not_averaged():
    """Q1 cancellation_rate must equal the ratio of Q1 components, not the mean of the monthly ratios."""
    from analyticsreceipts.execution import Executor
    ex = Executor(DB)
    tr = {"start": "2011-01-01", "end": "2011-03-31"}
    q = compile_request(M, {"metric": "cancellation_rate", "time_range": tr})
    whole = ex.run(q.sql, q.params)[1][0][0]
    qm = compile_request(M, {"metric": "cancellation_rate", "time_range": tr, "grain": "month"})
    monthly = [r[-1] for r in ex.run(qm.sql, qm.params)[1]]
    assert len(monthly) == 3
    assert abs(whole - sum(monthly) / 3) > 1e-6  # the two differ on this data; only `whole` is reported


@needs_db
def test_dedup_window_counted_once():
    from analyticsreceipts.execution import Executor
    ex = Executor(DB)
    q = compile_request(M, {"metric": "net_product_revenue", "time_range": {"start": "2010-12-01", "end": "2010-12-09"}})
    governed = ex.run(q.sql, q.params)[1][0][0]
    raw = ex.run("SELECT sum(quantity*price) FROM raw_lines WHERE trim(stock_code) SIMILAR TO '[0-9]{5}[A-Za-z]{0,2}' "
                 "AND CAST(invoice_ts AS DATE) BETWEEN DATE '2010-12-01' AND DATE '2010-12-09'")[1][0][0]
    assert abs(raw - 2 * governed) < 0.01  # the raw table holds the window twice


def test_reference_check_can_fail():
    """Negative control for test_reference: the table matcher rejects a near miss and a missing row."""
    from analyticsreceipts.grader import table_match
    exp = {"columns": ["v"], "rows": [[1264300.58]]}
    assert table_match(exp, ["v"], [[1264300.58]])
    assert not table_match(exp, ["v"], [[1264300.60]])
    assert not table_match({"columns": ["m", "v"], "rows": [["2011-01-01", 1.0], ["2011-02-01", 2.0]]},
                           ["m", "v"], [["2011-01-01", 1.0]])
