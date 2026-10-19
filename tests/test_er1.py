"""Rule ER-1 (review finding 10): spec equivalences E1/E2 and the valid-run cell partition.

Written before the grader change and shown to FAIL on the code before it. Needs no warehouse.
"""

import copy
import json
from pathlib import Path

from analyticsreceipts.grader import grade, spec_mismatches

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = {i["id"]: i for i in json.loads((ROOT / "golden" / "golden-v1.json").read_text())["items"]}
from analyticsreceipts.report import EXPECTED_TABLES  # noqa: E402

EXPECTED = json.loads(EXPECTED_TABLES.read_text())["items"]


def _receipt(cols, rows, metric="net_product_revenue", version="1.0.0"):
    return {"kind": "governed_metric", "error": None, "metric_id": metric, "metric_def_version": version,
            "result": {"columns": cols, "rows": rows}}


def _final(spec, answer):
    return json.dumps({"behavior": "answer", "resolved_spec": spec, "answer": answer})


def _with(spec, **kw):
    s = copy.deepcopy(spec)
    s.update(kw)
    return s


# ---------------- E1: single-bucket grain
def test_e1_month_grain_over_one_month_equals_no_grain():
    gold = GOLDEN["G11"]["resolved_spec"]          # 2010-12-01 .. 2010-12-31, grain null
    assert spec_mismatches(_with(gold, grain="month"), gold) == []


def test_e1_does_not_apply_when_the_period_spans_two_buckets():
    gold = GOLDEN["G12"]["resolved_spec"]          # 2011-01-01 .. 2011-11-30
    assert "grain" in spec_mismatches(_with(gold, grain="month"), gold)


def test_e1_quarter_and_year_buckets():
    gold = GOLDEN["G11"]["resolved_spec"]
    assert spec_mismatches(_with(gold, grain="quarter"), gold) == []   # Dec 2010 lies in Q4 2010
    assert spec_mismatches(_with(gold, grain="year"), gold) == []
    assert "grain" in spec_mismatches(_with(gold, grain="day"), gold)  # 31 days, 31 buckets


def test_e1_needs_the_comparison_period_in_one_bucket_too():
    gold = GOLDEN["G09"]["resolved_spec"]
    assert gold["comparison"] is not None
    assert spec_mismatches(_with(gold, grain="month"), gold) == []     # Oct 2011 vs Oct 2010
    wide_gold = _with(gold, comparison={"period": {"start": "2010-09-01", "end": "2010-10-31"}})
    assert spec_mismatches(_with(wide_gold, grain="month"), wide_gold) == ["grain"]


def test_e1_never_turns_a_gold_grain_into_null():
    gold = _with(GOLDEN["G11"]["resolved_spec"], grain="month")
    agent = _with(gold, grain=None)
    assert spec_mismatches(agent, gold) == []      # symmetric: one bucket either way


# ---------------- E2: one-value set
def test_e2_in_with_one_value_equals_eq():
    gold = GOLDEN["G01"]["resolved_spec"]          # country eq United Kingdom
    agent = _with(gold, filters=[{"dim": "country", "op": "in", "value": ["United Kingdom"]}])
    assert spec_mismatches(agent, gold) == []
    two = _with(gold, filters=[{"dim": "country", "op": "in", "value": ["United Kingdom", "EIRE"]}])
    assert "filters" in spec_mismatches(two, gold)


# ---------------- partition
def test_right_table_misstated_spec_is_not_the_headline_cell():
    item, exp = GOLDEN["G12"], EXPECTED["G12"]
    spec = _with(item["resolved_spec"], metric="total_revenue")
    rc = _receipt(exp["columns"], exp["rows"])
    g = grade(item, exp, {"arm": "raw", "receipts": [dict(rc, kind="raw_sql")],
                          "final_text": _final(spec, f"£{exp['rows'][0][-1]:,.2f}")})
    assert g["b"] is True and g["d"] is False and g["trap_sprung"] is False
    assert g["cell"] == "valid_misstated_spec"


def test_version_only_failure_is_valid_metric_mismatch_with_a_version_reason():
    item, exp = GOLDEN["G12"], EXPECTED["G12"]
    rc = _receipt(exp["columns"], exp["rows"], version="0.9.0")
    g = grade(item, exp, {"arm": "mcp", "receipts": [rc],
                          "final_text": _final(item["resolved_spec"], f"£{exp['rows'][0][-1]:,.2f}")})
    assert g["a"] is False and g["b"] and g["d"]
    assert g["cell"] == "valid_metric_mismatch"
    assert any("version" in r for r in g["reasons"]), g["reasons"]


def test_wrong_table_with_right_spec_stays_the_headline_cell():
    """F17/F19/F20 shape: the agent states the gold reading but its SQL ran the naive one."""
    item, exp = GOLDEN["G12"], EXPECTED["G12"]
    naive = exp["naive"]
    rc = dict(_receipt(naive["columns"], naive["rows"]), kind="raw_sql")
    g = grade(item, exp, {"arm": "raw", "receipts": [rc], "final_text": _final(item["resolved_spec"], "£1.00")})
    assert g["b"] is False and g["d"] is True
    assert g["cell"] == "valid_wrong_question"


def test_sprung_interpretation_trap_with_right_table_stays_the_headline_cell():
    item, exp = GOLDEN["G15"], EXPECTED["G15"]
    spec = copy.deepcopy(item["resolved_spec"])
    spec["period"]["incomplete"] = False
    rc = _receipt(["period", "net_product_revenue"], exp["rows"])
    g = grade(item, exp, {"arm": "mcp", "receipts": [rc], "final_text": _final(spec, "£441,363.22")})
    assert g["b"] is True and g["trap_sprung"] is True
    assert g["cell"] == "valid_wrong_question"


def test_live_v2_g11_shape_is_correct_under_e1():
    item, exp = GOLDEN["G11"], EXPECTED["G11"]
    spec = _with(item["resolved_spec"], grain="month")
    rc = _receipt(["period_start", "net_product_revenue"], [["2010-12-01", exp["rows"][0][-1]]])
    g = grade(item, exp, {"arm": "mcp", "receipts": [rc], "final_text": _final(spec, str(exp["rows"][0][-1]))})
    assert g["cell"] == "correct", g["reasons"]


# ---------------- reasons
def test_invalid_cells_say_no_query_succeeded():
    item, exp = GOLDEN["G01"], EXPECTED["G01"]
    rc = {"kind": "governed_metric", "error": "invalid_request", "result": None}
    g = grade(item, exp, {"arm": "mcp", "receipts": [rc], "final_text": _final(item["resolved_spec"], "£1.00")})
    assert g["cell"].startswith("invalid_")
    assert "no query succeeded" in g["reasons"]


def test_early_return_on_a_trap_says_the_trap_was_not_evaluated():
    item, exp = GOLDEN["G12"], EXPECTED["G12"]
    g = grade(item, exp, {"arm": "mcp", "receipts": [], "final_text": json.dumps(
        {"behavior": "abstain", "abstain_reason": "x"})})
    assert g["cell"] == "false_abstain" and g["trap_sprung"] is None
    assert any("trap not evaluated" in r for r in g["reasons"]), g["reasons"]
