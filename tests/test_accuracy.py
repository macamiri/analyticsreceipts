"""Remaining accuracy findings from the second code review (number parsing, tolerances, edge cases).

Written before each fix and shown to FAIL on the code before it. Finding numbers are the review's.
Needs no warehouse.
"""

import json

import pytest

from analyticsreceipts.contract import parse_final
from analyticsreceipts.grader import norm_spec, table_match
from analyticsreceipts.numbers import asserted, extract, matches


def _vals(text, question=""):
    return [round(v, 6) for v, _, _ in asserted(text, question)]


# ---------------- finding 11: prose numbers and years (axis c)
@pytest.mark.parametrize("text", [
    "The top 5 countries were the Netherlands (£262,997.04) and EIRE (£243,860.47).",
    "December 2011 is incomplete (only 9 days of data): £441,363.22 so far.",
    "Over the 11 months, revenue was £8,590,689.43.",
    "It was the 3rd largest month, at £1,432,731.70.",
])
def test_f11_prose_counts_durations_and_ordinals_are_not_asserted_values(text):
    vals = _vals(text)
    assert all(v >= 1000 for v in vals), vals


def test_f11_a_year_shaped_value_is_checked_when_it_is_not_a_year():
    """'2005 orders' is a metric value; before the fix every bare 1900-2100 integer was skipped."""
    assert 2005 in _vals("There were 2005 orders from Germany.")
    assert 2011 not in _vals("Revenue in 2011 was £1.2m.")
    assert 2010 not in _vals("Revenue fell between 2010 and 2011 by £3,000.")
    assert 2011 not in _vals("Germany had 92 customers.", "How many customers in Germany in 2011?")


# ---------------- finding 12: tolerances
def test_f12_ratio_cells_use_a_relative_tolerance():
    exp = {"columns": ["r"], "rows": [[0.1643]]}
    assert table_match(exp, ["r"], [[0.1643]])
    assert not table_match(exp, ["r"], [[0.16]])          # 2.6 % off: was inside ATOL 0.005
    money = {"columns": ["m"], "rows": [[1234.567]]}
    assert table_match(money, ["m"], [[1234.57]])         # penny rounding still matches


def test_f12_a_rounded_number_must_carry_two_significant_figures():
    assert not any(matches(n, [1_260_000.0]) for n in extract("about £1m"))
    assert any(matches(n, [1_260_000.0]) for n in extract("£1.26m"))
    assert any(matches(n, [0.164]) for n in extract("16%"))


# ---------------- finding 17 (accuracy-lens edge cases)
def test_f17_month_name_period_labels_match_iso_dates():
    exp = {"columns": ["period_start", "v"], "rows": [["2010-12-01", 760257.78]]}
    assert table_match(exp, ["month", "v"], [["December 2010", 760257.78]])
    assert table_match(exp, ["month", "v"], [["Dec 2010", 760257.78]])
    assert not table_match(exp, ["month", "v"], [["November 2010", 760257.78]])


def test_f17_string_false_is_not_read_as_incomplete():
    s = {"metric": "m", "period": {"start": "2011-12-01", "end": "2011-12-31", "incomplete": "false"}}
    assert norm_spec(s)["incomplete"] is False
    s["period"]["incomplete"] = "true"
    assert norm_spec(s)["incomplete"] is True


def test_f17_leading_point_and_signed_currency_parse():
    assert [round(v, 6) for v, _, _ in extract("down .5%")] == [0.5]
    assert [v for v, _, _ in extract("a change of -£25,566.53")] == [-25566.53]


def test_f17_contract_parser_ignores_braces_inside_strings():
    text = 'Here: {"behavior": "answer", "resolved_spec": null, "answer": "use {x} } here"} done'
    d, why = parse_final(text)
    assert why is None and d["answer"] == "use {x} } here"
