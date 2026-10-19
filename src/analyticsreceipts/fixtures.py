"""FIXTURES harness: replay recorded transcripts through the real server and raw-SQL tools.

Phase 1 (execute, needs the warehouse): every step is executed for real (MCP arm over stdio against
`python -m analyticsreceipts.server`, raw arm through RawTools), so every receipt is real. The final
answer's {{rIcJ}} templates are filled from the last successful result. The executed transcripts are
written to a replay file, together with the canary result.
Phase 2 (grade, offline): the replay is graded against golden + expected tables and compared with the
frozen expected grades. `report.py` regenerates everything from the replay with no warehouse and no network.

Usage:
  python -m analyticsreceipts.fixtures --db retail.duckdb --out replays/fixtures-v1.json [--planted-bug drop_c1]
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .compiler import compile_request
from .execution import Executor
from .model import default_model_path, load
from .paths import data_root, find_root
from .rawtools import RawTools
from .report import EXPECTED_TABLES

ROOT = find_root() or Path.cwd()  # eval data: see paths.py (a clone's root, or $ANALYTICSRECEIPTS_ROOT)
TEMPLATE = re.compile(r"\{\{r(\d+)c(\d+)(\*[0-9.]+)?(%)?\}\}")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _numeric_cells(row):
    return [v for v in row if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _fmt(v, pct):
    if pct:
        return f"{v * 100:.2f}%"
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:,.2f}"


def fill(text, last):
    if text is None:
        return None

    def sub(m):
        if last is None:
            return "[no result]"
        rows = last["rows"]
        i, j = int(m.group(1)), int(m.group(2))
        if i >= len(rows) or j >= len(_numeric_cells(rows[i])):
            return "[missing cell]"
        v = _numeric_cells(rows[i])[j]
        if m.group(3):
            v = v * float(m.group(3)[1:])
        return _fmt(v, bool(m.group(4)))

    return TEMPLATE.sub(sub, text)


def final_text_of(fx, last):
    if "final_text" in fx:
        return fx["final_text"]
    final = dict(fx["final"])
    final["answer"] = fill(final.get("answer"), last)
    return json.dumps(final)


async def execute_mcp(fixtures, db, planted_bug):
    env = {"ANALYTICSRECEIPTS_DB": str(Path(db).resolve())}
    args = (["-I", "-m", "analyticsreceipts.control_server", "--bug", planted_bug] if planted_bug
            else ["-I", "-m", "analyticsreceipts.server"])
    p = StdioServerParameters(command=sys.executable, args=args, env=env)
    out = []
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for fx in fixtures:
                steps, receipts, last = [], [], None
                for st in fx["steps"]:
                    res = await s.call_tool(st["tool"], st["args"])
                    text = res.content[0].text if res.content else ""
                    rec = {"tool": st["tool"], "args": st["args"], "tool_error": bool(res.is_error)}
                    if not res.is_error:
                        body = json.loads(text)
                        rc = body.get("receipt") if isinstance(body, dict) else None
                        rec["result_type"] = body.get("result_type") if isinstance(body, dict) else None
                        if rc:
                            receipts.append(rc)
                            if not rc.get("error"):
                                last = rc["result"]
                    else:
                        rec["error_text"] = text[:300]
                    steps.append(rec)
                out.append({"id": fx["id"], "arm": "mcp", "item": fx["item"], "planted": fx["planted"],
                            "steps": steps, "receipts": receipts, "final_text": final_text_of(fx, last)})
    return out


def execute_raw(fixtures, db):
    tools = RawTools(Executor(db))
    out = []
    for fx in fixtures:
        steps, receipts, last = [], [], None
        for st in fx["steps"]:
            body = tools.call(st["tool"], st["args"])
            rc = body.get("receipt")
            steps.append({"tool": st["tool"], "args": st["args"], "tool_error": False,
                          "result_type": body.get("result_type"), "error_text": body.get("error")})
            if rc:
                receipts.append(rc)
                if not rc.get("error"):
                    last = rc["result"]
        out.append({"id": fx["id"], "arm": "raw", "item": fx["item"], "planted": fx["planted"],
                    "steps": steps, "receipts": receipts, "final_text": final_text_of(fx, last)})
    return out


def run_canary(db, controls, planted_bug):
    model = load(default_model_path())
    fn = compile_request
    if planted_bug:
        from .broken import compile_request_broken
        fn = compile_request_broken
    q = fn(model, controls["canary"]["request"])
    _, rows, _, err = Executor(db).run(q.sql, q.params)
    got = None if err else rows[0][0]
    ok = got is not None and abs(got - controls["canary"]["known_answer"]) <= controls["canary"]["tolerance"]
    return {"result": got, "known_answer": controls["canary"]["known_answer"], "pass": ok, "error": err}


def execute(db, out_path, planted_bug=None):
    tpath = ROOT / "fixtures" / "transcripts-v1.json"
    gpath = ROOT / "fixtures" / "expected-grades-v1.json"
    transcripts = json.loads(tpath.read_text())
    controls = json.loads(gpath.read_text())["controls"]
    fixtures = transcripts["fixtures"]
    mcp = anyio.run(execute_mcp, [f for f in fixtures if f["arm"] == "mcp"], db, planted_bug)
    raw = execute_raw([f for f in fixtures if f["arm"] == "raw"], db)
    order = {f["id"]: i for i, f in enumerate(fixtures)}
    replay = {
        "label": "FIXTURES" + (f" — PLANTED BROKEN COMPILER ({planted_bug})" if planted_bug else ""),
        "planted_bug": planted_bug,
        "inputs": {"transcripts_sha256": sha(tpath), "expected_grades_sha256": sha(gpath),
                   "golden_sha256": sha(ROOT / "golden" / "golden-v1.json"),
                   "expected_tables_sha256": sha(EXPECTED_TABLES),
                   "semantic_model_sha256": load(default_model_path()).sha256},
        "canary": run_canary(db, controls, planted_bug),
        "runs": sorted(mcp + raw, key=lambda r: order[r["id"]]),
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(replay, indent=1, default=str) + "\n")
    return replay


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("ANALYTICSRECEIPTS_DB"), required=False)
    ap.add_argument("--out", required=True)
    ap.add_argument("--planted-bug", default=None)
    a = ap.parse_args()
    if not a.db:
        raise SystemExit("--db or ANALYTICSRECEIPTS_DB is required")
    data_root()  # a clear error when the eval data is not reachable
    r = execute(a.db, a.out, a.planted_bug)
    print(f"{r['label']}: {len(r['runs'])} fixtures executed; canary pass={r['canary']['pass']} -> {a.out}")


if __name__ == "__main__":
    main()
