"""0.0.2 security review: the raw-SQL arm (harness only) ran any statement the connection allowed, several
per call, and its error text could carry absolute file paths into the committed replays. Needs no warehouse.

Written before the fix and shown to FAIL on 0.0.1."""

import duckdb
import pytest

from analyticsreceipts.execution import Executor
from analyticsreceipts.rawtools import RawTools


@pytest.fixture
def raw(tmp_path):
    p = tmp_path / "t.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE TABLE t AS SELECT range AS x FROM range(3)")
    con.close()
    return RawTools(Executor(str(p)))


@pytest.mark.parametrize("sql", [
    "SELECT x FROM t ORDER BY x",
    "with a as (select x from t) select count(*) from a",
    "  -- a comment\nSELECT ';' AS semicolon_in_a_string",
    "/* block */ SELECT 1;",
])
def test_one_select_or_with_statement_runs(raw, sql):
    body = raw.run_sql(sql)
    assert body["result_type"] == "ok", body
    assert body["receipt"]["kind"] == "raw_sql"


@pytest.mark.parametrize("sql", [
    "SELECT 1; SELECT 2",
    "SELECT 1; DROP TABLE t",
    "SELECT 1;\nATTACH ':memory:' AS m",
])
def test_multi_statement_input_is_rejected(raw, sql):
    body = raw.run_sql(sql)
    assert body["result_type"] == "invalid_request" and body["receipt"] is None
    assert "one statement" in body["reason"]


@pytest.mark.parametrize("sql", [
    "PRAGMA database_list",
    "COPY (SELECT 1) TO 'out.csv'",
    "ATTACH ':memory:' AS m",
    "INSTALL httpfs",
    "SET threads = 64",
    "FROM t",
    "(SELECT 1)",
])
def test_statements_not_starting_with_select_or_with_are_rejected(raw, sql):
    body = raw.run_sql(sql)
    assert body["result_type"] == "invalid_request" and body["receipt"] is None
    assert "SELECT or WITH" in body["reason"]


def test_a_syntax_error_still_returns_an_error_receipt(raw):
    """Unparseable SQL is not rejected up front: it runs and fails as before, so its grade is unchanged."""
    body = raw.run_sql("SELEC x FROM t")
    assert body["result_type"] == "error" and body["receipt"]["error"]


PLANTED = "/srv/planted-dir/private/customers-export.csv"


def test_absolute_paths_are_scrubbed_from_error_text(raw):
    body = raw.run_sql(f"SELECT * FROM read_csv('{PLANTED}')")
    assert body["result_type"] == "error"
    for text in (body["error"], body["receipt"]["error"]):
        assert "/srv/" not in text and "planted-dir" not in text and "<path>" in text, text


def test_the_planted_path_really_was_in_the_unscrubbed_error(raw):
    """Positive control: without the scrub, DuckDB's own error names the file."""
    _, _, _, err = raw.ex.run(f"SELECT * FROM read_csv('{PLANTED}')")
    assert PLANTED in err


@pytest.mark.parametrize("text, want", [
    ("IO Error: No files found that match the pattern \"/tmp/x/y.csv\"", "IO Error: No files found that match the pattern \"<path>\""),
    ("Cannot open ~/data/secret.duckdb here", "Cannot open <path> here"),
    ("Binder Error: column a / b not found", "Binder Error: column a / b not found"),
    ("C:\\Users\\someone\\x.csv missing", "<path> missing"),
])
def test_scrub_paths(text, want):
    from analyticsreceipts.rawtools import scrub_paths
    assert scrub_paths(text) == want
