"""The raw-SQL arm's tools, provided by the harness (the MCP server has no raw-SQL tool).

`describe_tables` shows the warehouse schema; `run_sql` runs one statement on the same hardened
read-only connection as the server, with the same caps, and emits a receipt on the execution path.
A raw receipt has no metric_id and no metric version: axis (a) is N/A for this arm.
"""

import json

from . import __version__
from .execution import make_receipt, now_iso

TOOL_SPECS = [
    {"name": "describe_tables",
     "description": "Describe the warehouse tables: columns, types and the date range of the data.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "run_sql",
     "description": "Run one read-only DuckDB SQL SELECT statement on the warehouse and return the rows (at most 1000).",
     "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"],
                      "additionalProperties": False}},
]


class RawTools:
    def __init__(self, executor):
        self.ex = executor

    def describe_tables(self):
        """Every base table in the warehouse except the loader's snapshot_meta bookkeeping table."""
        _, rows, _, err = self.ex.run(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_name IN (SELECT table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE') "
            "AND table_name <> 'snapshot_meta' ORDER BY table_name, ordinal_position")
        tables = {}
        for t, c, ty in rows:
            tables.setdefault(t, []).append({"name": c, "type": ty})
        return {"tables": [{"name": t, "columns": cs} for t, cs in tables.items()],
                "data_ends": self.ex.snapshot.get("max_invoice_ts"), "error": err}

    def run_sql(self, sql):
        started = now_iso()
        if not isinstance(sql, str) or not sql.strip():
            return {"result_type": "invalid_request", "reason": "sql must be a non-empty string", "receipt": None}
        cols, rows, truncated, err = self.ex.run(sql)
        receipt = make_receipt(executor=self.ex, kind="raw_sql", request={"sql": sql}, metric_id=None,
                               metric_def_version=None, semantic_model_sha256=None, sql=sql, params=(),
                               sql_sha256=None, columns=cols, rows=rows, truncated=truncated, error=err,
                               checks=[{"name": "row_cap", "success": not truncated, "expected": "<= 1000 rows",
                                        "actual": len(rows)}],
                               caveats=[], server_version=__version__, started=started)
        return {"result_type": "error" if err else "ok", "error": err, "columns": cols, "rows": rows,
                "truncated": truncated, "receipt": receipt}

    def call(self, name, args):
        if name == "describe_tables":
            return self.describe_tables()
        if name == "run_sql":
            return self.run_sql((args or {}).get("sql"))
        return {"result_type": "invalid_request", "reason": f"unknown tool {name!r}", "receipt": None}


def compact(result):
    """What the model sees: rows and status, not the full receipt (the harness keeps the receipt)."""
    if not isinstance(result, dict):
        return json.dumps(result)
    out = {k: v for k, v in result.items() if k != "receipt"}
    r = result.get("receipt")
    if r:
        failed = [c for c in r.get("checks", []) if not c.get("success")]
        if failed:
            out["failed_checks"] = failed
    return json.dumps(out, default=str)
