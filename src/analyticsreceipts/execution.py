"""Read-only execution with caps, and the receipt emitted on the execution path.

The connection is opened read-only with external access disabled and the configuration locked, so
a statement cannot read or write files outside the database (no read_csv, no COPY TO) or loosen
those settings. Every result is capped by rows and by time. The same instance is capped in memory, threads
and temp-file disk use (set before the lock), and at most MAX_CONCURRENT_RUNS statements run at once.
"""

import datetime as dt
import decimal
import hashlib
import json
import threading
import time
import uuid

import duckdb

RECEIPT_VERSION = "2"  # 2: `compiler` required and tied to `kind`; no non_additive_guard check
ROW_CAP = 1000
TIMEOUT_S = 20.0
MEMORY_LIMIT = "1GB"           # per DuckDB instance, shared by every cursor on it
THREADS = 2
MAX_TEMP_DIRECTORY_SIZE = "0B"  # no spilling to disk: a query over the memory limit fails instead
MAX_CONCURRENT_RUNS = 4         # per process; further calls wait (up to their timeout) for a slot
_RUN_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
_LIMITS = {"memory_limit": f"'{MEMORY_LIMIT}'", "threads": str(THREADS),
           "max_temp_directory_size": f"'{MAX_TEMP_DIRECTORY_SIZE}'"}


def connect(db_path):
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": False})
    # a second connection to the same file in one process shares the (already locked) instance
    if not con.execute("SELECT current_setting('lock_configuration')").fetchone()[0]:
        for name, value in _LIMITS.items():
            con.execute(f"SET {name} = {value}")
        con.execute("SET lock_configuration = true")
    if _settings(con) != _expected_settings():
        raise RuntimeError("this database instance was locked with other resource limits; refusing to serve")
    if con.execute("SELECT current_setting('enable_external_access')").fetchone()[0]:
        raise RuntimeError("external access is enabled on this database instance; refusing to serve")
    return con


def _settings(con):
    return {n: con.execute("SELECT current_setting(?)", [n]).fetchone()[0] for n in _LIMITS}


_EXPECTED = []


def _expected_settings():
    # how DuckDB reports the limits (e.g. '1GB' reads back as '953.6 MiB'), from a scratch in-memory instance
    if not _EXPECTED:
        scratch = duckdb.connect()
        for name, value in _LIMITS.items():
            scratch.execute(f"SET {name} = {value}")
        _EXPECTED.append(_settings(scratch))
        scratch.close()
    return _EXPECTED[0]


def _cell(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Executor:
    def __init__(self, db_path):
        self.db_path = db_path
        self.con = connect(db_path)
        # a warehouse built by analyticsreceipts.load carries snapshot_meta; any other warehouse is
        # fingerprinted by its file hash alone, and its data range comes from the semantic model
        has_meta = self.con.execute("SELECT count(*) FROM information_schema.tables "
                                    "WHERE table_name = 'snapshot_meta'").fetchone()[0]
        if has_meta:
            meta = self.con.execute("SELECT xlsx_sha256, max_invoice_ts FROM snapshot_meta").fetchone()
            self.snapshot = {"source_xlsx_sha256": meta[0], "max_invoice_ts": meta[1].isoformat(),
                             "db_file_sha256": file_sha256(db_path)}
        else:
            self.snapshot = {"db_file_sha256": file_sha256(db_path)}
        self.data_range = None  # (start_date, end_date, end_label), set by the server from the model

    def set_data_range(self, start, end):
        label = self.snapshot.get("max_invoice_ts") or end
        self.data_range = (start, end, label)

    def run(self, sql, params=(), cap=ROW_CAP, timeout_s=TIMEOUT_S):
        """Returns (columns, rows, truncated, error). Never raises for a bad statement.

        Each call runs on its own cursor (a separate connection to the same read-only database), and
        the timeout interrupts only that cursor. Concurrent calls (the MCP SDK runs sync tools on worker
        threads) therefore can neither read each other's results nor cancel each other's queries. At most
        MAX_CONCURRENT_RUNS calls run at once; a call that gets no slot within timeout_s returns an error.
        """
        if not _RUN_SLOTS.acquire(timeout=timeout_s):
            return [], [], False, f"Busy: {MAX_CONCURRENT_RUNS} queries already running; no slot within {timeout_s} s"
        try:
            return self._run(sql, params, cap, timeout_s)
        finally:
            _RUN_SLOTS.release()

    def _run(self, sql, params, cap, timeout_s):
        cur = self.con.cursor()
        timer = threading.Timer(timeout_s, cur.interrupt)
        timer.start()
        try:
            cur.execute(sql, list(params))
            cols = [d[0] for d in (cur.description or [])]
            rows = cur.fetchmany(cap + 1)
        except Exception as e:  # the statement failed; the caller records it
            return [], [], False, f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"
        finally:
            timer.cancel()
            cur.close()
        truncated = len(rows) > cap
        rows = [[_cell(v) for v in r] for r in rows[:cap]]
        return cols, rows, truncated, None


def result_sha256(columns, rows):
    return hashlib.sha256(json.dumps({"columns": columns, "rows": rows}, sort_keys=True, default=str).encode()).hexdigest()


def make_receipt(*, executor, kind, request, metric_id, metric_def_version, semantic_model_sha256, sql, params,
                 sql_sha256, columns, rows, truncated, error, checks, caveats, server_version, started, compiler=None):
    return {
        "receipt_version": RECEIPT_VERSION,
        "kind": kind,  # "governed_metric" (MCP query_metric), "control_metric" (planted compiler) or "raw_sql"
        "compiler": compiler,  # "governed", "planted:<bug>" for a control run, None for raw SQL
        "request": request,
        "metric_id": metric_id,
        "metric_def_version": metric_def_version,
        "semantic_model_sha256": semantic_model_sha256,
        "compiled_sql": sql,
        "params": list(params),
        "compiled_sql_sha256": sql_sha256 or hashlib.sha256((sql + "\n" + json.dumps(list(params))).encode()).hexdigest(),
        "engine": {"name": "duckdb", "version": duckdb.__version__},
        "snapshot": executor.snapshot,
        "result": {"columns": columns, "rows": rows},
        "result_sha256": None if error else result_sha256(columns, rows),
        "row_count": len(rows),
        "truncated": truncated,
        "error": error,
        "checks": checks,
        "uncertainty": {"caveats_applied": caveats},
        "run": {"request_id": uuid.uuid4().hex, "server_version": server_version, "started_at": started,
                "elapsed_s": round(time.time() - _epoch(started), 3)},
    }


def _epoch(iso):
    return dt.datetime.fromisoformat(iso).timestamp()


def now_iso():
    return dt.datetime.now().isoformat(timespec="milliseconds")


def period_checks(data_range, time_range, comparison_range=None):
    """Checks that make an incomplete or out-of-data period visible in the receipt.
    data_range = (first data date, last data date, label for the last data point)."""
    min_date, max_date, end_label = data_range
    out = []
    for name, r in (("time_range", time_range), ("comparison_range", comparison_range)):
        if not r:
            continue
        complete = r["end"] <= max_date
        out.append({"name": f"{name}_complete", "success": complete,
                    "expected": f"end <= last data date {max_date}", "actual": r["end"],
                    "note": None if complete else f"data ends {end_label}; the period is incomplete"})
        out.append({"name": f"{name}_starts_in_data", "success": r["start"] >= min_date,
                    "expected": f"start >= {min_date}", "actual": r["start"]})
    return out
