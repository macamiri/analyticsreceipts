"""Deterministic compiler: a structured metric request -> one DuckDB SQL statement + bound parameters.

Rules (each one has a test):
  * only governed metrics and declared dimensions; anything else is refused with a typed result,
    never guessed (no raw SQL path exists);
  * one dataset, so no joins and no fan-out;
  * filter values are bound parameters, never interpolated into the SQL text;
  * ratio and count-distinct metrics are computed from their components inside every group; there is
    no rollup path that could sum or average them across groups;
  * the same request (after canonical ordering) always yields byte-identical SQL and the same hash.
"""

import datetime as dt
import hashlib
import json
from dataclasses import dataclass

from .model import TIME_GRAINS

OPS = ("eq", "ne", "in", "is_null", "not_null")
ROW_CAP = 1000


class RequestError(Exception):
    """A request the compiler refuses. `result_type` is what the server returns instead of rows."""

    def __init__(self, result_type, reason, candidates=()):
        super().__init__(reason)
        self.result_type = result_type
        self.reason = reason
        self.candidates = list(candidates)


@dataclass(frozen=True)
class Compiled:
    sql: str
    params: tuple
    sha256: str
    request: dict  # canonical form
    columns: tuple


def _date(s, what):
    try:
        return dt.date.fromisoformat(str(s)).isoformat()
    except ValueError:
        raise RequestError("invalid_request", f"{what} must be YYYY-MM-DD, got {s!r}")


def _range(r, what):
    if not isinstance(r, dict) or "start" not in r or "end" not in r:
        raise RequestError("needs_clarification", f"{what} needs a start and an end date")
    a, b = _date(r["start"], f"{what}.start"), _date(r["end"], f"{what}.end")
    if a > b:
        raise RequestError("invalid_request", f"{what} starts after it ends")
    return {"start": a, "end": b}


def candidates_for(model, text):
    t = (text or "").lower().replace("_", " ")
    out = []
    for m in model.metrics.values():
        names = [m.name.replace("_", " ")] + [s.lower() for s in m.synonyms]
        if any(n in t or t in n for n in names if n):
            out.append(m.name)
    return sorted(set(out))


def canonical(model, req):
    """Validate and canonicalise. Raises RequestError for anything the model cannot answer."""
    if not isinstance(req, dict):
        raise RequestError("invalid_request", "request must be an object")
    metric = req.get("metric")
    if not metric:
        raise RequestError("needs_clarification", "no metric was named", sorted(model.metrics))
    if metric not in model.metrics:
        raise RequestError("no_governed_metric", f"no governed metric named {metric!r}",
                           candidates_for(model, metric))
    if not req.get("time_range"):
        raise RequestError("needs_clarification", "a period (time_range) is required")
    out = {"metric": metric, "time_range": _range(req["time_range"], "time_range")}
    comp = req.get("comparison_range")
    out["comparison_range"] = _range(comp, "comparison_range") if comp else None
    grain = req.get("grain")
    if grain is not None and grain not in TIME_GRAINS:
        raise RequestError("invalid_request", f"grain must be one of {TIME_GRAINS}")
    out["grain"] = grain
    dims = list(req.get("dimensions") or [])
    for d in dims:
        if d not in model.dimensions or model.dimensions[d].is_time:
            raise RequestError("invalid_request", f"{d!r} is not a declared dimension; use grain for time")
    if len(set(dims)) != len(dims):
        raise RequestError("invalid_request", "duplicate dimension")
    out["dimensions"] = dims
    filters = []
    for f in req.get("filters") or []:
        if not isinstance(f, dict):
            raise RequestError("invalid_request", "each filter is {dim, op, value}")
        d, op, v = f.get("dim"), f.get("op"), f.get("value")
        if d not in model.dimensions or model.dimensions[d].is_time:
            raise RequestError("invalid_request", f"filter dimension {d!r} is not declared; use time_range for dates")
        if op not in OPS:
            raise RequestError("invalid_request", f"filter op must be one of {OPS}")
        if op in ("is_null", "not_null"):
            v = None
        elif op == "in":
            if not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v):
                raise RequestError("invalid_request", "op 'in' needs a non-empty list of strings")
            v = sorted(v)
        elif not isinstance(v, str):
            raise RequestError("invalid_request", f"op {op!r} needs a string value")
        filters.append({"dim": d, "op": op, "value": v})
    out["filters"] = sorted(filters, key=lambda x: json.dumps(x, sort_keys=True))
    rk = req.get("ranking")
    if rk:
        if rk.get("by", metric) != metric:
            raise RequestError("invalid_request", "ranking.by must be the requested metric")
        direction = rk.get("direction", "desc")
        if direction not in ("asc", "desc"):
            raise RequestError("invalid_request", "ranking.direction is asc or desc")
        limit = rk.get("limit")
        if not isinstance(limit, int) or not 1 <= limit <= ROW_CAP:
            raise RequestError("invalid_request", f"ranking.limit is an integer 1..{ROW_CAP}")
        if not dims:
            raise RequestError("invalid_request", "ranking needs at least one dimension to rank")
        out["ranking"] = {"by": metric, "direction": direction, "limit": limit}
    else:
        out["ranking"] = None
    return out


def _bucket(model, grain):
    t = model.fields[model.time_dimension]
    return f"CAST(date_trunc('{grain}', {t}) AS DATE)"


def _select(model, req, start, end, label):
    params = []
    t = model.fields[model.time_dimension]
    cols, group, group_exprs = [], [], []
    if label is not None:
        cols.append(f"'{label}' AS period")  # label is one of two fixed literals, never user text
    if req["grain"]:
        cols.append(f"{_bucket(model, req['grain'])} AS period_start")
        group.append("period_start")
        group_exprs.append(_bucket(model, req["grain"]))
    for d in req["dimensions"]:
        cols.append(f"{model.fields[d]} AS {d}")
        group.append(d)
        # group by the field EXPRESSION: an alias that shadows a raw column (stock_code) would bind to
        # the raw column and split one trimmed code into several groups
        group_exprs.append(model.fields[d])
    cols.append(f"{model.metric_sql(req['metric'])} AS {req['metric']}")
    where = [f"{t} BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)"]
    params += [start, end]
    for f in req["filters"]:
        e = model.fields[f["dim"]]
        if f["op"] == "eq":
            where.append(f"{e} = ?")
            params.append(f["value"])
        elif f["op"] == "ne":
            # "not X" keeps rows where the value is missing; SQL's <> alone would silently drop them
            where.append(f"({e} <> ? OR {e} IS NULL)")
            params.append(f["value"])
        elif f["op"] == "in":
            where.append(f"{e} IN ({', '.join('?' for _ in f['value'])})")
            params += f["value"]
        elif f["op"] == "is_null":
            where.append(f"{e} IS NULL")
        else:
            where.append(f"{e} IS NOT NULL")
    sql = f"SELECT {', '.join(cols)} FROM {model.dataset_name} WHERE {' AND '.join(where)}"
    if group_exprs:
        sql += f" GROUP BY {', '.join(group_exprs)}"
    return sql, params, group


def compile_request(model, req):
    req = canonical(model, req)
    with_cte = f"WITH {model.dataset_name} AS ({' '.join(model.dataset_source.split())}) "
    tr, cr = req["time_range"], req["comparison_range"]
    if cr:
        s1, p1, group = _select(model, req, tr["start"], tr["end"], "current")
        s2, p2, _ = _select(model, req, cr["start"], cr["end"], "comparison")
        body = f"{s1} UNION ALL {s2}"
        params = p1 + p2
        order = ["period DESC"] + group  # 'current' before 'comparison'
        cols = ("period",)
    else:
        body, params, group = _select(model, req, tr["start"], tr["end"], None)
        order = list(group)
        cols = ()
    cols += (("period_start",) if req["grain"] else ()) + tuple(req["dimensions"]) + (req["metric"],)
    sql = with_cte + f"SELECT * FROM ({body}) AS q"
    if req["ranking"] and cr:
        # rank WITHIN each period: top-N of the current period, then top-N of the comparison period
        rk = req["ranking"]
        by = f"{req['metric']} {rk['direction'].upper()} NULLS LAST"
        tiebreak = ", ".join(group)
        within = by + (f", {tiebreak}" if tiebreak else "")
        sql += f" QUALIFY row_number() OVER (PARTITION BY period ORDER BY {within}) <= {int(rk['limit'])}"
        sql += f" ORDER BY period DESC, {within}"
    elif req["ranking"]:
        rk = req["ranking"]
        tiebreak = ", ".join(order)
        sql += f" ORDER BY {req['metric']} {rk['direction'].upper()} NULLS LAST" + (f", {tiebreak}" if tiebreak else "")
        sql += f" LIMIT {int(rk['limit'])}"
    else:
        if order:
            sql += f" ORDER BY {', '.join(order)}"
        sql += f" LIMIT {ROW_CAP + 1}"
    payload = sql + "\n" + json.dumps(params)
    return Compiled(sql, tuple(params), hashlib.sha256(payload.encode()).hexdigest(), req, cols)


compile_request.compiler_id = "governed"  # recorded in every receipt
