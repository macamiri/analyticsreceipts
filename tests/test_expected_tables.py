"""The canonical expected tables agree with the shipped compiler: every golden item recompiles to the
recorded compiled_sql_sha256. (golden/expected-v1.json recorded SQL from before the GROUP BY and `ne`
compiler fixes for G02, G03 and G07; it stays byte-identical as the record, and v2 is canonical.)"""

import json
from pathlib import Path

from analyticsreceipts.compiler import compile_request
from analyticsreceipts.materialise import spec_to_request
from analyticsreceipts.model import default_model_path, load
from analyticsreceipts.report import EXPECTED_TABLES

ROOT = Path(__file__).resolve().parents[1]


def _sql_mismatches(path):
    golden = {i["id"]: i for i in json.loads((ROOT / "golden" / "golden-v1.json").read_text())["items"]}
    expected = json.loads(Path(path).read_text())["items"]
    model = load(default_model_path())
    out = set()
    for item_id, e in expected.items():
        q = compile_request(model, spec_to_request(golden[item_id]["resolved_spec"]))
        if q.sha256 != e["compiled_sql_sha256"]:
            out.add(item_id)
    return out


def test_canonical_expected_tables_match_the_shipped_compiler():
    assert _sql_mismatches(EXPECTED_TABLES) == set()


def test_v1_differs_for_exactly_g02_g03_g07():
    """The record: v1's SQL hashes are stale for exactly these three items, and no others."""
    assert _sql_mismatches(ROOT / "golden" / "expected-v1.json") == {"G02", "G03", "G07"}
