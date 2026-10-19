"""Server surface and security controls.

* The registered tools equal a committed manifest (names, descriptions, input schemas) and its hash,
  so a tool cannot appear or change its description unnoticed.
* There is no raw-SQL tool.
* The execution connection is read-only, cannot read or write files, and cannot loosen its settings.
"""

import hashlib
import json
import os
from pathlib import Path

import anyio
import pytest

from analyticsreceipts.execution import Executor

DB = os.environ.get("ANALYTICSRECEIPTS_DB")
needs_db = pytest.mark.skipif(not DB or not Path(DB).exists(), reason="ANALYTICSRECEIPTS_DB not built")
MANIFEST = Path(__file__).resolve().parent / "tool-manifest.json"


def registered_tools():
    from analyticsreceipts.server import build_server

    srv = build_server(db_path=DB)

    async def go():
        return await srv.list_tools()

    tools = anyio.run(go)
    return sorted(({"name": t.name, "description": t.description, "input_schema": t.input_schema}
                   for t in tools), key=lambda t: t["name"])


def manifest_hash(tools):
    return hashlib.sha256(json.dumps(tools, sort_keys=True).encode()).hexdigest()


@needs_db
def test_tools_equal_committed_manifest():
    tools = registered_tools()
    committed = json.loads(MANIFEST.read_text())
    assert tools == committed["tools"]
    assert manifest_hash(tools) == committed["sha256"]


@needs_db
def test_no_raw_sql_tool():
    names = {t["name"] for t in registered_tools()}
    assert names == {"list_metrics", "get_metric", "list_dimensions", "get_dimension_values", "query_metric"}
    for t in registered_tools():
        assert "sql" not in json.dumps(t["input_schema"]).lower()


@needs_db
@pytest.mark.parametrize("stmt", [
    "CREATE TABLE x AS SELECT 1",
    "DELETE FROM raw_lines",
    "SELECT * FROM read_csv('/etc/hosts')",
    "COPY (SELECT 1) TO '/tmp/analyticsreceipts-should-not-exist.csv'",
    "SET enable_external_access = true",
    "ATTACH '/tmp/other.duckdb' AS o",
    "INSTALL httpfs",
])
def test_connection_refuses_writes_files_and_settings(stmt):
    ex = Executor(DB)
    _, _, _, err = ex.run(stmt)
    assert err is not None, stmt
    assert not Path("/tmp/analyticsreceipts-should-not-exist.csv").exists()


@needs_db
def test_select_still_works():
    ex = Executor(DB)
    _, rows, _, err = ex.run("SELECT count(*) FROM raw_lines")
    assert err is None and rows[0][0] == 1067371


@needs_db
def test_control_unhardened_connection_would_read_files():
    """Positive control: without the hardening, the same file-read statement succeeds (fresh process,
    because DuckDB shares one instance per file within a process)."""
    import subprocess
    import sys
    code = ("import duckdb,sys; c=duckdb.connect(sys.argv[1], read_only=True); "
            "print(c.execute(\"SELECT count(*) FROM read_text('/etc/hosts')\").fetchone()[0])")
    out = subprocess.run([sys.executable, "-c", code, DB], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == "1", out.stderr


@needs_db
def test_hardened_connection_refuses_the_control_statement():
    _, _, _, err = Executor(DB).run("SELECT count(*) FROM read_text('/etc/hosts')")
    assert err is not None
