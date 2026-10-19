"""Read-only semantic-layer MCP server (official `mcp` SDK, stdio).

Tools: list_metrics, get_metric, list_dimensions, get_dimension_values, query_metric.
There is no raw-SQL tool. A question the model cannot answer gets a typed result
(`needs_clarification`, `no_governed_metric`, `invalid_request`), never a guess.
Every query_metric response carries a receipt built on the execution path.

Run: ANALYTICSRECEIPTS_DB=/path/retail.duckdb python -m analyticsreceipts.server
"""

import argparse
import hashlib
import json
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from mcp.server.mcpserver import MCPServer

from . import __version__
from .compiler import RequestError, compile_request
from .execution import Executor, make_receipt, now_iso, period_checks
from .model import default_model_path, load

TOOL_DESCRIPTIONS = {
    "list_metrics": "List the governed metrics: name, description, synonyms, type and version.",
    "get_metric": "Full definition of one governed metric, including the business conventions it applies.",
    "list_dimensions": "Dimensions you can filter or group by, and the time grains available.",
    "get_dimension_values": "Distinct values of one dimension (at most 100), to ground filter values.",
    "query_metric": ("Compute one governed metric for an inclusive date range, optionally filtered, grouped by "
                     "dimensions or a time grain, ranked, or compared with a second date range. Returns rows "
                     "and a receipt. If the question cannot be answered with a governed metric, the result_type "
                     "says so instead of returning rows."),
}


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dim: str
    op: Literal["eq", "ne", "in", "is_null", "not_null"]
    value: str | list[str] | None = None


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str = Field(description="Inclusive start date, YYYY-MM-DD")
    end: str = Field(description="Inclusive end date, YYYY-MM-DD")


class Ranking(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Literal["asc", "desc"] = "desc"
    limit: int = Field(ge=1, le=1000)


def build_server(db_path=None, model_path=None, compile_fn=None):
    db_path = db_path or os.environ["ANALYTICSRECEIPTS_DB"]
    model = load(model_path or default_model_path())
    ex = Executor(db_path)
    t = model.fields[model.time_dimension]
    lo, hi = ex.con.execute(f"WITH {model.dataset_name} AS ({' '.join(model.dataset_source.split())}) "
                            f"SELECT CAST(min({t}) AS DATE), CAST(max({t}) AS DATE) FROM {model.dataset_name}").fetchone()
    ex.set_data_range(lo.isoformat(), hi.isoformat())
    compile_fn = compile_fn or compile_request
    compiler_id = getattr(compile_fn, "compiler_id", "custom")
    # a receipt names the model that actually ran: any non-governed compiler gets a derived hash
    model_hash = (model.sha256 if compiler_id == "governed"
                  else hashlib.sha256(f"{model.sha256}|{compiler_id}".encode()).hexdigest())
    # only the governed compiler emits kind "governed_metric"; a control run says so in `kind` too
    receipt_kind = "governed_metric" if compiler_id == "governed" else "control_metric"
    server = MCPServer(name="analyticsreceipts", version=__version__)

    def envelope(values):
        # dataset strings are untrusted input: returned as data, never as instructions
        return {"data_untrusted": values}

    @server.tool(description=TOOL_DESCRIPTIONS["list_metrics"])
    def list_metrics() -> str:
        return json.dumps({"metrics": [
            {"name": m.name, "description": m.description, "synonyms": list(m.synonyms),
             "type": m.meta.get("type"), "version": m.meta.get("version"), "status": m.meta.get("status")}
            for m in model.metrics.values()], "conventions": model.instructions})

    @server.tool(description=TOOL_DESCRIPTIONS["get_metric"])
    def get_metric(metric: str) -> str:
        m = model.metrics.get(metric)
        if not m:
            from .compiler import candidates_for
            return json.dumps({"result_type": "no_governed_metric", "reason": f"no governed metric named {metric!r}",
                               "candidates": candidates_for(model, metric)})
        return json.dumps({"name": m.name, "description": m.description, "instructions": m.instructions,
                           "synonyms": list(m.synonyms), "expression": m.expression, **m.meta,
                           "dimensions_allowed": [d for d, v in model.dimensions.items() if not v.is_time],
                           "time_grains": ["day", "month", "quarter", "year"]})

    @server.tool(description=TOOL_DESCRIPTIONS["list_dimensions"])
    def list_dimensions() -> str:
        return json.dumps({"dimensions": [
            {"name": d.name, "description": d.description, "synonyms": list(d.synonyms)}
            for d in model.dimensions.values() if not d.is_time],
            "time": {"field": model.time_dimension, "grains": ["day", "month", "quarter", "year"],
                     "data_ends": ex.data_range[2]}})

    @server.tool(description=TOOL_DESCRIPTIONS["get_dimension_values"])
    def get_dimension_values(dimension: str, search: str | None = None, limit: int = 50) -> str:
        if dimension not in model.dimensions or model.dimensions[dimension].is_time:
            return json.dumps({"result_type": "invalid_request", "reason": f"unknown dimension {dimension!r}"})
        limit = max(1, min(int(limit), 100))
        expr = model.fields[dimension]
        sql = (f"WITH {model.dataset_name} AS ({' '.join(model.dataset_source.split())}) "
               f"SELECT DISTINCT {expr} AS v FROM {model.dataset_name} WHERE {expr} IS NOT NULL"
               + (f" AND lower({expr}) LIKE ?" if search else "") + f" ORDER BY v LIMIT {limit}")
        _, rows, _, err = ex.run(sql, [f"%{search.lower()}%"] if search else [])
        if err:
            return json.dumps({"result_type": "error", "reason": err})
        return json.dumps({"dimension": dimension, **envelope([str(r[0])[:80] for r in rows])})

    @server.tool(description=TOOL_DESCRIPTIONS["query_metric"])
    def query_metric(metric: str, time_range: DateRange | None = None, filters: list[Filter] | None = None,
                     grain: Literal["day", "month", "quarter", "year"] | None = None,
                     dimensions: list[str] | None = None, ranking: Ranking | None = None,
                     comparison_range: DateRange | None = None) -> str:
        started = now_iso()
        req = {"metric": metric, "time_range": time_range.model_dump() if time_range else None,
               "filters": [f.model_dump() for f in (filters or [])], "grain": grain,
               "dimensions": list(dimensions or []),
               "ranking": ranking.model_dump() if ranking else None,
               "comparison_range": comparison_range.model_dump() if comparison_range else None}
        try:
            q = compile_fn(model, req)
        except RequestError as e:
            return json.dumps({"result_type": e.result_type, "reason": e.reason, "candidates": e.candidates,
                               "rows": [], "receipt": None})
        m = model.metrics[q.request["metric"]]
        cols, rows, truncated, err = ex.run(q.sql, q.params)
        checks = period_checks(ex.data_range, q.request["time_range"], q.request["comparison_range"])
        checks.append({"name": "row_cap", "success": not truncated, "expected": "<= 1000 rows", "actual": len(rows)})
        receipt = make_receipt(executor=ex, kind=receipt_kind, request=q.request, metric_id=m.name,
                               metric_def_version=m.meta.get("version"), semantic_model_sha256=model_hash,
                               compiler=compiler_id,
                               sql=q.sql, params=q.params, sql_sha256=q.sha256, columns=cols, rows=rows,
                               truncated=truncated, error=err, checks=checks,
                               caveats=m.meta.get("conventions", []), server_version=__version__, started=started)
        return json.dumps({"result_type": "error" if err else "ok", "columns": cols, "rows": rows,
                           "truncated": truncated, "receipt": receipt})

    return server


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="analyticsreceipts.server")
    ap.add_argument("--db", default=os.environ.get("ANALYTICSRECEIPTS_DB"), help="DuckDB file (read-only)")
    ap.add_argument("--model", default=os.environ.get("ANALYTICSRECEIPTS_MODEL"),
                    help="Ossie semantic model YAML (default: the bundled Online Retail II model)")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    build_server(db_path=a.db, model_path=a.model).run("stdio")


if __name__ == "__main__":
    main()
