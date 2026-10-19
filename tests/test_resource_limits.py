"""0.0.2 security review, MEDIUM finding 1: one read-only connection could use all memory, every core and
up to 90% of the disk for temp files, and any number of queries could run at once. Needs no warehouse.

Written before the fix and shown to FAIL on 0.0.1."""

import threading

import duckdb
import pytest

from analyticsreceipts import execution
from analyticsreceipts.execution import Executor


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE TABLE t AS SELECT range AS x FROM range(10)")
    con.close()
    return str(p)


def _setting(con, name):
    return con.execute(f"SELECT current_setting('{name}')").fetchone()[0]


def _expected_memory_limit():
    scratch = duckdb.connect()
    scratch.execute(f"SET memory_limit = '{execution.MEMORY_LIMIT}'")
    return _setting(scratch, "memory_limit")


def test_resource_settings_are_applied_and_locked(db):
    ex = Executor(db)
    assert _setting(ex.con, "memory_limit") == _expected_memory_limit()
    assert _setting(ex.con, "threads") == execution.THREADS
    assert _setting(ex.con, "max_temp_directory_size") == "0 bytes"
    assert _setting(ex.con, "lock_configuration") is True
    for stmt in ("SET memory_limit = '64GB'", "SET threads = 64", "SET max_temp_directory_size = '100GB'"):
        with pytest.raises(duckdb.Error):
            ex.con.execute(stmt)
    _, _, _, err = ex.run("SET threads = 64")   # the same refusal through the execution path
    assert err is not None


def test_a_second_executor_on_the_same_file_sees_the_same_limits(db):
    a, b = Executor(db), Executor(db)
    for name in ("memory_limit", "threads", "max_temp_directory_size"):
        assert _setting(b.con, name) == _setting(a.con, name)


def test_the_timeout_is_unchanged():
    assert execution.TIMEOUT_S == 20.0


class _BlockingCursor:
    """Stands in for a DuckDB cursor: execute() blocks until released, so concurrency is observable."""

    def __init__(self, state):
        self.state = state

    def execute(self, sql, params):
        with self.state["lock"]:
            self.state["running"] += 1
            self.state["peak"] = max(self.state["peak"], self.state["running"])
        self.state["entered"].release()
        self.state["release"].wait(10)
        with self.state["lock"]:
            self.state["running"] -= 1

    description = [("x",)]

    def fetchmany(self, n):
        return [[1]]

    def interrupt(self):
        pass

    def close(self):
        pass


class _FakeCon:
    def __init__(self, state):
        self.state = state

    def cursor(self):
        return _BlockingCursor(self.state)


def test_n_plus_one_concurrent_calls_queue(db):
    ex = Executor(db)
    state = {"lock": threading.Lock(), "running": 0, "peak": 0, "entered": threading.Semaphore(0),
             "release": threading.Event()}
    ex.con = _FakeCon(state)
    n = execution.MAX_CONCURRENT_RUNS
    out = []
    ts = [threading.Thread(target=lambda: out.append(ex.run("SELECT 1"))) for _ in range(n + 1)]
    [t.start() for t in ts]
    for _ in range(n):
        assert state["entered"].acquire(timeout=5)
    assert not state["entered"].acquire(timeout=0.5), "call N+1 started before a slot was free"
    assert state["running"] == n
    state["release"].set()
    [t.join(10) for t in ts]
    assert len(out) == n + 1 and all(err is None for *_, err in out)
    assert state["peak"] == n


def test_a_call_that_cannot_get_a_slot_in_time_returns_an_error(db):
    ex = Executor(db)
    state = {"lock": threading.Lock(), "running": 0, "peak": 0, "entered": threading.Semaphore(0),
             "release": threading.Event()}
    ex.con = _FakeCon(state)
    n = execution.MAX_CONCURRENT_RUNS
    ts = [threading.Thread(target=ex.run, args=("SELECT 1",)) for _ in range(n)]
    [t.start() for t in ts]
    for _ in range(n):
        assert state["entered"].acquire(timeout=5)
    cols, rows, truncated, err = ex.run("SELECT 1", timeout_s=0.2)
    state["release"].set()
    [t.join(10) for t in ts]
    assert (cols, rows, truncated) == ([], [], False) and err and "busy" in err.lower()
