"""Regression tests for the findings of the code review.

Each test was written first and shown to FAIL on the code before its fix. The finding number and the
reproduced case are named in each test. Needs the warehouse (ANALYTICSRECEIPTS_DB) unless marked.
"""

import os
import threading
import time
from pathlib import Path

import pytest

from analyticsreceipts.execution import Executor

DB = os.environ.get("ANALYTICSRECEIPTS_DB")
needs_db = pytest.mark.skipif(not DB or not Path(DB).exists(), reason="ANALYTICSRECEIPTS_DB not built")


# ---------------------------------------------------------------- C1 / finding 1: shared connection
@needs_db
def test_c1_parallel_calls_never_return_another_querys_rows():
    """Reproduced 171/600 wrong rows with 3 threads on one Executor (review finding 1)."""
    ex = Executor(DB)
    res = {"ok": 0, "wrong": 0, "err": 0}
    lock = threading.Lock()

    def worker(k):
        for _ in range(200):
            _, rows, _, err = ex.run(f"SELECT {k} AS k FROM range(2000) LIMIT 1")
            with lock:
                if err:
                    res["err"] += 1
                elif rows and rows[0][0] == k:
                    res["ok"] += 1
                else:
                    res["wrong"] += 1

    ts = [threading.Thread(target=worker, args=(k,)) for k in (1, 2, 3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert res == {"ok": 600, "wrong": 0, "err": 0}


@needs_db
def test_c1_one_calls_timeout_does_not_cancel_another_call():
    ex = Executor(DB)
    slow = "SELECT count(*) FROM range(400000000) t(x) WHERE x % 7 = 3"
    out = {}

    def a():
        out["a"] = ex.run(slow, timeout_s=30)

    def b():
        time.sleep(0.05)
        out["b"] = ex.run(slow, timeout_s=0.05)

    ta, tb = threading.Thread(target=a), threading.Thread(target=b)
    ta.start(); tb.start(); ta.join(); tb.join()
    assert out["b"][3] is not None, "B should time out"
    assert out["a"][3] is None, f"A was cancelled by B's timeout: {out['a'][3]}"


# ---------------------------------------------------------------- C2 / finding 8: planted-bug identity
def _call(srv, name, args):
    import json

    import anyio

    async def go():
        return await srv.call_tool(name, args)

    res = anyio.run(go)
    return json.loads(res.content[0].text)


DEC2010 = {"metric": "net_product_revenue", "time_range": {"start": "2010-12-01", "end": "2010-12-31"}}


@needs_db
def test_c2_governed_receipt_names_the_governed_compiler_and_model():
    from analyticsreceipts.model import default_model_path, load
    from analyticsreceipts.server import build_server

    r = _call(build_server(db_path=DB), "query_metric", DEC2010)["receipt"]
    assert r["compiler"] == "governed"
    assert r["semantic_model_sha256"] == load(default_model_path()).sha256


@needs_db
def test_c2_planted_receipt_says_so_and_does_not_claim_the_governed_model():
    from analyticsreceipts.broken import compile_request_broken
    from analyticsreceipts.model import default_model_path, load
    from analyticsreceipts.server import build_server

    r = _call(build_server(db_path=DB, compile_fn=compile_request_broken), "query_metric", DEC2010)["receipt"]
    assert r["compiler"] == "planted:drop_c1"
    assert r["semantic_model_sha256"] != load(default_model_path()).sha256


@needs_db
def test_n3_control_receipts_do_not_carry_the_governed_kind():
    """Re-admission N3: a planted-compiler receipt said kind 'governed_metric', so a consumer checking
    `kind` alone was fooled. Only the governed compiler may emit that kind."""
    from analyticsreceipts.broken import compile_request_broken
    from analyticsreceipts.server import build_server

    gov = _call(build_server(db_path=DB), "query_metric", DEC2010)["receipt"]
    ctl = _call(build_server(db_path=DB, compile_fn=compile_request_broken), "query_metric", DEC2010)["receipt"]
    assert gov["kind"] == "governed_metric"
    assert ctl["kind"] == "control_metric"


def test_n3_grader_still_reads_metric_identity_from_control_receipts():
    """The planted control is pre-registered with axis a = True (the metric is right; the compiler is
    broken). Relabelling the kind must not change that grade."""
    from analyticsreceipts.grader import grade

    item, exp = _g("G11")
    rc = dict(_receipt(exp["columns"], exp["rows"]), kind="control_metric")
    g = grade(item, exp, {"arm": "mcp", "receipts": [rc], "final_text": _final(item["resolved_spec"], "£760,257.78")})
    assert g["a"] is True


def test_c2_product_server_main_ignores_the_planted_bug_variable(monkeypatch):
    import analyticsreceipts.server as srv

    seen = {}

    class Fake:
        def run(self, transport):
            seen["transport"] = transport

    def fake_build(**kw):
        seen.update(kw)
        return Fake()

    monkeypatch.setenv("ANALYTICSRECEIPTS_PLANTED_BUG", "drop_c1")
    monkeypatch.setattr(srv, "build_server", fake_build)
    srv.main([])
    assert seen.get("compile_fn") is None


# ---------------------------------------------------------------- C3 / finding 16: pin the model text
PIN_FILE = Path(__file__).resolve().parent / "semantic-model.sha256"


def _pin_holds(model_path, pin_path):
    """The one pin check every C3 test uses: the model as LOADED equals the pinned digest."""
    from analyticsreceipts.model import load

    return load(model_path).sha256 == Path(pin_path).read_text().split()[0]


def test_c3_semantic_model_hash_is_pinned():
    """The model's conventions/instructions/descriptions reach the agent through list_metrics/get_metric;
    a change to that text must fail a test, not pass silently."""
    from analyticsreceipts.model import default_model_path

    assert _pin_holds(default_model_path(), PIN_FILE)


def test_c3_pin_detects_a_one_byte_change(tmp_path):
    """Re-admission N2: the old control only compared two hashlib digests and never ran the pin check.
    This one runs the SAME check (_pin_holds) on copies, and each alteration must be caught on its own:
    a one-byte change to the model file, and a one-character change to the pinned hash file."""
    import shutil

    from analyticsreceipts.model import default_model_path

    model, pin = tmp_path / "model.ossie.yaml", tmp_path / "pin.sha256"
    shutil.copy(default_model_path(), model)
    shutil.copy(PIN_FILE, pin)
    assert _pin_holds(model, pin)                        # untouched copies: the check passes

    raw = model.read_bytes()
    model.write_bytes(raw.replace(b"Revenue means net product revenue", b"Revenue means net product revenuE", 1))
    assert model.read_bytes() != raw
    assert not _pin_holds(model, pin)                    # model altered, pin intact
    model.write_bytes(raw)

    text = pin.read_text()
    pin.write_text(("0" if text[0] != "0" else "1") + text[1:])
    assert not _pin_holds(model, pin)                    # pin altered, model intact


# ---------------------------------------------------------------- finding 2: comparison direction + period labels
def _g(item_id):
    import json

    root = Path(__file__).resolve().parents[1]
    golden = {i["id"]: i for i in json.loads((root / "golden" / "golden-v1.json").read_text())["items"]}
    from analyticsreceipts.report import EXPECTED_TABLES

    expected = json.loads(EXPECTED_TABLES.read_text())["items"]
    return golden[item_id], expected[item_id]


def _receipt(cols, rows, metric="net_product_revenue"):
    return {"kind": "governed_metric", "error": None, "metric_id": metric, "metric_def_version": "1.0.0",
            "result": {"columns": cols, "rows": rows}}


def _final(spec, answer):
    import json

    return json.dumps({"behavior": "answer", "resolved_spec": spec, "answer": answer})


def test_f2_rose_when_revenue_fell_fails_axis_c():
    """Reproduced: 'rose by £50,613.04 (5.45%)' graded correct on G09, where UK revenue FELL."""
    from analyticsreceipts.grader import grade

    item, exp = _g("G09")
    rc = _receipt(["period", "net_product_revenue"], [["current", 877754.89], ["comparison", 928367.93]])
    g = grade(item, exp, {"arm": "mcp", "receipts": [rc], "final_text": _final(
        item["resolved_spec"], "UK revenue rose by £50,613.04 (5.45%) from October 2010 to October 2011.")})
    assert g["c"] is False and g["cell"] != "correct"


def test_f2_correct_direction_still_passes():
    from analyticsreceipts.grader import grade

    item, exp = _g("G09")
    rc = _receipt(["period", "net_product_revenue"], [["current", 877754.89], ["comparison", 928367.93]])
    g = grade(item, exp, {"arm": "mcp", "receipts": [rc], "final_text": _final(
        item["resolved_spec"], "UK revenue fell by £50,613.04 (5.45%) to £877,754.89 in October 2011.")})
    assert g["c"] is True and g["cell"] == "correct", g["reasons"]


def test_f2_swapped_period_receipt_fails_axis_b():
    """Reproduced: a receipt with current=928,367.93 (the 2010 value) graded correct."""
    from analyticsreceipts.grader import grade

    item, exp = _g("G09")
    rc = _receipt(["period", "net_product_revenue"], [["current", 928367.93], ["comparison", 877754.89]])
    g = grade(item, exp, {"arm": "mcp", "receipts": [rc], "final_text": _final(
        item["resolved_spec"], "UK revenue was £877,754.89 in October 2011 against £928,367.93 in October 2010.")})
    assert g["b"] is False


def test_f2_blind_spot_label_swap_is_detected_by_table_match():
    """test_reference's comparison check could not detect a compiler that swaps period labels."""
    from analyticsreceipts.grader import table_match

    exp = {"columns": ["period", "v"], "rows": [["current", 877754.89], ["comparison", 928367.93]]}
    assert table_match(exp, ["period", "v"], [["current", 877754.89], ["comparison", 928367.93]])
    assert not table_match(exp, ["period", "v"], [["current", 928367.93], ["comparison", 877754.89]])


# ---------------------------------------------------------------- findings 3, 4, 13: compiler
def _run(req):
    from analyticsreceipts.compiler import compile_request
    from analyticsreceipts.model import default_model_path, load

    q = compile_request(load(default_model_path()), req)
    cols, rows, _, err = Executor(DB).run(q.sql, q.params)
    assert err is None, err
    return cols, rows


@needs_db
def test_f3_group_by_stock_code_uses_the_trimmed_code():
    """Reproduced: 47503J appeared twice (one source row has a trailing space)."""
    _, rows = _run({"metric": "net_product_revenue", "time_range": {"start": "2009-12-01", "end": "2011-12-09"},
                    "dimensions": ["stock_code"], "filters": [{"dim": "stock_code", "op": "eq", "value": "47503J"}]})
    assert len(rows) == 1 and rows[0][0] == "47503J"
    assert abs(rows[0][1] - (16.13 + 2568.33)) < 0.01


@needs_db
def test_f4_ranking_with_comparison_ranks_within_each_period():
    """Reproduced: LIMIT 3 applied across both periods mixed: [comparison UK, current UK, comparison EIRE]."""
    cols, rows = _run({"metric": "net_product_revenue", "time_range": {"start": "2011-10-01", "end": "2011-10-31"},
                       "comparison_range": {"start": "2010-10-01", "end": "2010-10-31"},
                       "dimensions": ["country"], "ranking": {"direction": "desc", "limit": 3}})
    periods = [r[0] for r in rows]
    assert periods == ["current"] * 3 + ["comparison"] * 3
    for p in ("current", "comparison"):
        vals = [r[-1] for r in rows if r[0] == p]
        assert vals == sorted(vals, reverse=True)


@needs_db
def test_f13_ne_keeps_rows_where_the_value_is_missing():
    """Reproduced: customer_id ne 12346 returned 7,397,419.27, dropping all £1,193,270.16 without an ID."""
    _, rows = _run({"metric": "net_product_revenue", "time_range": {"start": "2011-01-01", "end": "2011-11-30"},
                    "filters": [{"dim": "customer_id", "op": "ne", "value": "12346"}]})
    _, total = _run({"metric": "net_product_revenue", "time_range": {"start": "2011-01-01", "end": "2011-11-30"}})
    _, one = _run({"metric": "net_product_revenue", "time_range": {"start": "2011-01-01", "end": "2011-11-30"},
                   "filters": [{"dim": "customer_id", "op": "eq", "value": "12346"}]})
    assert abs(rows[0][0] - (total[0][0] - (one[0][0] or 0))) < 0.01


# ---------------------------------------------------------------- finding 6: table_match complexity
def test_f6_tied_rows_failing_match_is_fast():
    """Measured: n=10 identical rows with one unmatched expected row took 20.2 s (factorial)."""
    from analyticsreceipts.grader import table_match

    n = 10
    exp = {"columns": ["k", "v"], "rows": [["a", 0.0]] * (n - 1) + [["b", 1.0]]}
    t = time.monotonic()
    assert table_match(exp, ["k", "v"], [["a", 0.0]] * n) is False
    assert time.monotonic() - t < 1.0


def test_f6_thousand_row_table_does_not_hit_the_recursion_limit():
    """Measured: a 1,000-row table raised RecursionError (one recursion level per row)."""
    import random

    from analyticsreceipts.grader import table_match

    rows = [[f"k{i}", float(i)] for i in range(1000)]
    shuffled = rows[:]
    random.Random(42).shuffle(shuffled)
    t = time.monotonic()
    assert table_match({"columns": ["k", "v"], "rows": rows}, ["k", "v"], shuffled) is True
    assert time.monotonic() - t < 5.0


def test_f6_new_matcher_agrees_with_brute_force_on_random_small_tables():
    """The rewrite must not change any yes/no: compare with exhaustive assignment on 3,000 random cases."""
    import itertools
    import random

    from analyticsreceipts.grader import _norm_cell, _row_covers, table_match

    rnd = random.Random(7)
    for _ in range(3000):
        n = rnd.randint(0, 5)
        exp_rows = [[rnd.choice("ab"), float(rnd.randint(0, 2))] for _ in range(n)]
        got_rows = [[rnd.choice("ab"), float(rnd.randint(0, 2)), float(rnd.randint(0, 2))] for _ in range(n)]
        e = [[_norm_cell(c) for c in r] for r in exp_rows]
        g = [[_norm_cell(c) for c in r] for r in got_rows]
        brute = any(all(_row_covers(e[i], g[p[i]]) for i in range(n)) for p in itertools.permutations(range(n)))
        assert table_match({"columns": ["k", "v"], "rows": exp_rows}, ["k", "v", "w"], got_rows) == brute


# ---------------------------------------------------------------- findings 5 + 7: portability
TINY_MODEL = """version: 0.2.0.dev0
name: tiny_shop
datasets:
  - name: sales
    source: SELECT * FROM orders
    primary_key: [id]
    fields:
      - name: day
        expression: {dialects: [{dialect: ANSI_SQL, expression: order_day}]}
        datatype: Date
        dimension: {is_time: true}
      - name: region
        expression: {dialects: [{dialect: ANSI_SQL, expression: region}]}
        datatype: String
        dimension: {is_time: false}
      - name: amount
        expression: {dialects: [{dialect: ANSI_SQL, expression: amount}]}
        datatype: Decimal
metrics:
  - name: total_sales
    expression: {dialects: [{dialect: ANSI_SQL, expression: "SUM(sales.amount)"}]}
    custom_extensions:
      - vendor_name: analyticsreceipts
        data: '{"type":"simple","version":"1.0.0","non_additive":false,"conventions":[],"status":"approved"}'
"""


@pytest.fixture
def tiny(tmp_path):
    import duckdb

    db = tmp_path / "tiny.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE orders (id INTEGER, order_day DATE, region VARCHAR, amount DECIMAL(10,2))")
    con.execute("INSERT INTO orders VALUES (1, DATE '2024-01-05', 'north', 10.50), (2, DATE '2024-01-20', 'south', 4.00),"
                " (3, DATE '2024-02-02', 'north', 7.25)")
    con.close()
    model = tmp_path / "tiny.ossie.yaml"
    model.write_text(TINY_MODEL)
    return str(db), str(model)


def test_f7_server_serves_a_second_model_on_a_warehouse_without_snapshot_meta(tiny):
    from analyticsreceipts.server import build_server

    db, model = tiny
    srv = build_server(db_path=db, model_path=model)
    names = [m["name"] for m in _call(srv, "list_metrics", {})["metrics"]]
    assert names == ["total_sales"]
    body = _call(srv, "query_metric", {"metric": "total_sales", "time_range": {"start": "2024-01-01", "end": "2024-01-31"},
                                       "dimensions": ["region"]})
    assert body["result_type"] == "ok" and sorted(body["rows"]) == [["north", 10.5], ["south", 4.0]]
    checks = {c["name"]: c for c in body["receipt"]["checks"]}
    assert checks["time_range_complete"]["success"] is True
    late = _call(srv, "query_metric", {"metric": "total_sales", "time_range": {"start": "2024-02-01", "end": "2024-02-29"}})
    assert {c["name"]: c for c in late["receipt"]["checks"]}["time_range_complete"]["success"] is False  # data ends 02-02
    early = _call(srv, "query_metric", {"metric": "total_sales", "time_range": {"start": "2023-12-01", "end": "2024-01-31"}})
    assert {c["name"]: c for c in early["receipt"]["checks"]}["time_range_starts_in_data"]["success"] is False


def test_f7_server_cli_takes_a_model_path(monkeypatch, tiny):
    import analyticsreceipts.server as srv

    seen = {}

    class Fake:
        def run(self, transport):
            pass

    monkeypatch.setattr(srv, "build_server", lambda **kw: (seen.update(kw), Fake())[1])
    srv.main(["--db", tiny[0], "--model", tiny[1]])
    assert seen["model_path"] == tiny[1] and seen["db_path"] == tiny[0]


def test_f7_raw_tools_describe_the_tables_that_exist(tiny):
    from analyticsreceipts.rawtools import RawTools

    d = RawTools(Executor(tiny[0])).describe_tables()
    assert [t["name"] for t in d["tables"]] == ["orders"]


def test_f5_installed_wheel_finds_its_model_and_schema(tmp_path):
    """After a normal install, model and schema lookup went up two folders to a repo that is not there."""
    import subprocess
    import sys
    import zipfile

    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "dist"
    b = subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out), str(root)], capture_output=True, text=True,
                       timeout=300)
    assert b.returncode == 0, b.stderr[-800:]
    whl = next(out.glob("analyticsreceipts-*.whl"))
    site = tmp_path / "site"
    zipfile.ZipFile(whl).extractall(site)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import analyticsreceipts, analyticsreceipts.model as m; "
            "assert analyticsreceipts.__file__.startswith(sys.argv[1]), analyticsreceipts.__file__; "
            "print(m.load(m.default_model_path()).sha256)")
    r = subprocess.run([sys.executable, "-I", "-c", code, str(site)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    pinned = (Path(__file__).resolve().parent / "semantic-model.sha256").read_text().split()[0]
    assert r.stdout.strip() == pinned


def test_installed_wheel_finds_the_eval_data_of_the_clone_it_runs_in(tmp_path):
    """Timed clean install: `pip install` then `python -m analyticsreceipts.fixtures` from a clone failed,
    because the eval data (golden/, fixtures/) was looked up next to the installed module. From a clone's root,
    the installed package must use that clone's data; with no data anywhere it must say so clearly."""
    import subprocess
    import sys
    import zipfile

    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "dist"
    b = subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out), str(root)], capture_output=True, text=True,
                       timeout=300)
    assert b.returncode == 0, b.stderr[-800:]
    site = tmp_path / "site"
    zipfile.ZipFile(next(out.glob("analyticsreceipts-*.whl"))).extractall(site)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import analyticsreceipts.report as r, analyticsreceipts.fixtures as f; "
            "assert r.__file__.startswith(sys.argv[1]); print(r.EXPECTED_TABLES); print(f.ROOT)")
    ok = subprocess.run([sys.executable, "-I", "-c", code, str(site)], cwd=root, capture_output=True, text=True, timeout=120)
    assert ok.returncode == 0, ok.stderr[-800:]
    lines = ok.stdout.split()
    assert lines[0] == str(root / "golden" / "expected-v2.json") and lines[1] == str(root), lines
    empty = tmp_path / "empty"
    empty.mkdir()
    code2 = ("import sys; sys.path.insert(0, sys.argv[1]); from analyticsreceipts.paths import data_root; data_root()")
    bad = subprocess.run([sys.executable, "-I", "-c", code2, str(site)], cwd=empty, capture_output=True, text=True,
                         timeout=120)
    assert bad.returncode != 0 and "ANALYTICSRECEIPTS_ROOT" in bad.stderr, bad.stderr[-400:]


# ---------------------------------------------------------------- blind spots 2 + 3 (review finding 10/11)
# These were pinned as strict xfail while the defects were open. Both are now fixed (rule ER-1 for the G15
# null spec; numbers.py rank/duration/ordinal exclusions for the prose numbers) and the markers are gone.

def test_blindspot_g15_trap_counts_as_sprung_when_the_spec_is_missing():
    import json

    from analyticsreceipts.grader import grade

    item, exp = _g("G15")
    rc = _receipt(["period", "net_product_revenue"], [["current", 441363.22], ["comparison", 1432731.7]])
    g = grade(item, exp, {"arm": "mcp", "receipts": [rc], "final_text": json.dumps(
        {"behavior": "answer", "resolved_spec": None, "answer": "December 2011 revenue was £441,363.22."})})
    assert g["trap_sprung"] is True


@pytest.mark.parametrize("item_id,answer", [
    ("G03", "The top 5 countries were the Netherlands (£262,997.04), EIRE (£243,860.47), Germany (£181,344.86), "
            "France (£167,282.76) and Australia (£135,984.90)."),
    ("G15", "December 2011 is incomplete (only 9 days of data): £441,363.22 so far, against £1,432,731.70 in November 2011."),
])
def test_blindspot_prose_numbers_do_not_fail_a_correct_answer(item_id, answer):
    from analyticsreceipts.grader import grade

    item, exp = _g(item_id)
    cols = ["period", "net_product_revenue"] if item_id == "G15" else ["country", "net_product_revenue"]
    rc = _receipt(cols, exp["rows"])
    g = grade(item, exp, {"arm": "mcp", "receipts": [rc], "final_text": _final(item["resolved_spec"], answer)})
    assert g["c"] is True, g["reasons"]


# ---------------------------------------------------------------- finding 15: a claim that was not a check
@needs_db
def test_f15_receipts_carry_no_non_additive_guard():
    """The receipt's non_additive_guard 'check' was hard-coded to success. It is removed, not built."""
    import json

    from analyticsreceipts.server import build_server

    r = _call(build_server(db_path=DB), "query_metric", DEC2010)["receipt"]
    assert "non_additive_guard" not in json.dumps(r)
    assert all(c["name"] != "non_additive_guard" for c in r["checks"])
