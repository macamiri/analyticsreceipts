"""The frozen inputs (golden expected tables, fixtures, expected grades) still match their committed hashes."""

import hashlib
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_files_unchanged():
    lines = (ROOT / "FREEZE-v1.sha256").read_text().split("\n")
    entries = [l.split() for l in lines if l.strip()]
    assert len(entries) == 3
    for digest, rel in entries:
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel


def test_golden_hash_unchanged():
    digest, name = (ROOT / "golden" / "golden-v1.json.sha256").read_text().split()
    assert hashlib.sha256((ROOT / "golden" / name).read_bytes()).hexdigest() == digest


def test_expected_v2_hash_unchanged():
    digest, name = (ROOT / "golden" / "expected-v2.json.sha256").read_text().split()
    assert hashlib.sha256((ROOT / "golden" / name).read_bytes()).hexdigest() == digest


DB = os.environ.get("ANALYTICSRECEIPTS_DB")


def _v1_divergence(v1_path, db_path):
    """Recompile and re-run all 15 golden specs with the shipped compiler; compare with a v1-shaped file."""
    from analyticsreceipts.compiler import compile_request
    from analyticsreceipts.execution import Executor, result_sha256
    from analyticsreceipts.materialise import spec_to_request
    from analyticsreceipts.model import default_model_path, load

    golden = json.loads((ROOT / "golden" / "golden-v1.json").read_text())["items"]
    v1 = json.loads(Path(v1_path).read_text())["items"]
    model, ex = load(default_model_path()), Executor(db_path)
    sql, result, n = set(), set(), 0
    for item in golden:
        if not item.get("resolved_spec"):
            continue
        n += 1
        q = compile_request(model, spec_to_request(item["resolved_spec"]))
        cols, rows, trunc, err = ex.run(q.sql, q.params)
        assert not err and not trunc, (item["id"], err)
        if q.sha256 != v1[item["id"]]["compiled_sql_sha256"]:
            sql.add(item["id"])
        if result_sha256(cols, rows) != v1[item["id"]]["result_sha256"]:
            result.add(item["id"])
    return n, sql, result


@pytest.mark.skipif(not DB or not Path(DB).exists(), reason="ANALYTICSRECEIPTS_DB not built")
def test_expected_v1_known_sql_divergence():
    """expected-v1 is the frozen pre-registration. Its SQL hashes predate two compiler fixes for exactly
    G02, G03 and G07 (golden/EXPECTED-V1-DIVERGENCE.md); every result hash still matches. Any other
    divergence fails."""
    n, sql, result = _v1_divergence(ROOT / "golden" / "expected-v1.json", DB)
    assert n == 15
    assert sql == {"G02", "G03", "G07"}
    assert result == set()


def _broken_replay_receipts(path):
    return [rc for run in json.loads(Path(path).read_text())["runs"] for rc in run["receipts"]]


def _assert_broken_replay_is_receipt_v1(path):
    """The as-run record: format v1, recorded before receipts carried `compiler`, so the planted control's
    MCP receipts say kind governed_metric with the governed model hash."""
    from analyticsreceipts.model import default_model_path, load

    receipts = _broken_replay_receipts(path)
    assert len(receipts) == 20
    assert all(rc["receipt_version"] == "1" and "compiler" not in rc for rc in receipts)
    mcp = [rc for rc in receipts if rc["kind"] != "raw_sql"]
    assert len(mcp) == 12
    assert {rc["kind"] for rc in mcp} == {"governed_metric"}
    assert {rc["semantic_model_sha256"] for rc in mcp} == {load(default_model_path()).sha256}


def test_broken_control_replay_is_receipt_v1():
    _assert_broken_replay_is_receipt_v1(ROOT / "replays" / "fixtures-v1-broken.json")


@pytest.mark.skipif(not DB or not Path(DB).exists(), reason="ANALYTICSRECEIPTS_DB not built")
def test_planted_control_run_today_labels_its_receipts():
    """The same planted control run now, through analyticsreceipts.control_server (offline, no model):
    every receipt says kind control_metric, names the planted compiler, and does not claim the governed model."""
    import anyio

    from analyticsreceipts.fixtures import execute_mcp
    from analyticsreceipts.model import default_model_path, load

    fixtures = [f for f in json.loads((ROOT / "fixtures" / "transcripts-v1.json").read_text())["fixtures"]
                if f["arm"] == "mcp"]
    runs = anyio.run(execute_mcp, fixtures, DB, "drop_c1")
    receipts = [rc for run in runs for rc in run["receipts"]]
    assert len(receipts) == 12
    assert all(rc["receipt_version"] == "2" for rc in receipts)
    assert {rc["kind"] for rc in receipts} == {"control_metric"}
    assert {rc["compiler"] for rc in receipts} == {"planted:drop_c1"}
    assert load(default_model_path()).sha256 not in {rc["semantic_model_sha256"] for rc in receipts}
