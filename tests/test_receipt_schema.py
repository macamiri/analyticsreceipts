"""Finding 14: receipts have a JSON Schema. Every committed receipt validates; mutated receipts fail."""

import copy
import json
import os
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
DB = os.environ.get("ANALYTICSRECEIPTS_DB")


def _schema():
    from analyticsreceipts.receipts import receipt_schema

    return receipt_schema()


def _committed_receipts():
    out = []
    for name in ("fixtures-v1.json", "fixtures-v1-broken.json"):
        for r in json.loads((ROOT / "replays" / name).read_text())["runs"]:
            out += [(f"{name}:{r['id']}", rc) for rc in r["receipts"] if rc]
    for name in ("live-lite-v1.jsonl", "live-lite-v2.jsonl"):
        for line in (ROOT / "replays" / name).read_text().splitlines():
            r = json.loads(line)
            if r.get("kind") == "run":
                out += [(f"{name}:{r['item']}/{r['arm']}", rc) for rc in r.get("receipts", []) if rc]
    return out


def test_every_committed_receipt_validates():
    v = jsonschema.Draft202012Validator(_schema())
    rs = _committed_receipts()
    assert len(rs) >= 20
    bad = {rid: [e.message for e in v.iter_errors(rc)][:2] for rid, rc in rs if not v.is_valid(rc)}
    assert not bad, bad


@pytest.mark.skipif(not DB or not Path(DB).exists(), reason="ANALYTICSRECEIPTS_DB not built")
def test_a_fresh_server_receipt_validates_as_version_2():
    import anyio

    from analyticsreceipts.server import build_server

    async def go():
        return await build_server(db_path=DB).call_tool(
            "query_metric", {"metric": "net_product_revenue", "time_range": {"start": "2010-12-01", "end": "2010-12-31"}})

    rc = json.loads(anyio.run(go).content[0].text)["receipt"]
    jsonschema.validate(rc, _schema())
    assert rc["receipt_version"] == "2" and rc["compiler"] == "governed"


def _mutants(base):
    def m(fn):
        r = copy.deepcopy(base)
        fn(r)
        return r
    return {
        "missing result_sha256": m(lambda r: r.pop("result_sha256")),
        "row_count is a string": m(lambda r: r.update(row_count="1")),
        "unknown top-level key": m(lambda r: r.update(extra=1)),
        "unknown kind": m(lambda r: r.update(kind="governed")),
        "check without success": m(lambda r: r["checks"][0].pop("success")),
        "short model hash": m(lambda r: r.update(semantic_model_sha256="d1d2cd0a")),
        "v2 without compiler": m(lambda r: (r.update(receipt_version="2"), r.pop("compiler", None))),
        "governed kind from a planted compiler": m(lambda r: r.update(receipt_version="2", compiler="planted:drop_c1")),
    }


MUTANTS = ("missing result_sha256", "row_count is a string", "unknown top-level key", "unknown kind",
           "check without success", "short model hash", "v2 without compiler", "governed kind from a planted compiler")


@pytest.mark.parametrize("name", MUTANTS)
def test_a_mutated_receipt_fails(name):
    base = next(rc for _, rc in _committed_receipts() if rc.get("kind") == "governed_metric" and not rc.get("error"))
    jsonschema.validate(base, _schema())              # the unmutated base is valid
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_mutants(base)[name], _schema())
