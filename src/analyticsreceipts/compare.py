"""Side-by-side table of two LIVE-LITE replays graded with the same grader. Descriptive only.

  python -m analyticsreceipts.compare replays/live-lite-v1.jsonl replays/live-lite-v2.jsonl --names v1,v2

Prints a markdown table: per arm, answers, axis passes, cells, tool calls, query calls, and the count of
answerable MCP runs ending in a well-formed query_metric call plus a final numeric answer. Both replays are
graded by the grader installed now, so a difference comes from the runs, not from grading.
"""

import argparse
import collections
import json

from .live import read_jsonl
from .report import CELLS, grade_runs, load_refs

AXES = ("a", "b", "c", "d")


def summarize(path):
    golden, _ = load_refs()
    runs = [r for r in read_jsonl(path) if r.get("kind", "run") == "run" and not r.get("incomplete")]
    for r in runs:
        r["id"] = f"{r['item']}/{r['arm']}"
    grades = {g["run_id"]: g for g in grade_runs(runs)}
    out = {}
    for arm in ("mcp", "raw"):
        rs = [r for r in runs if r["arm"] == arm]
        gs = [grades[r["id"]] for r in rs]
        answerable = [r for r in rs if golden[r["item"]]["expected_behavior"] in ("answer", "answer_with_caveat")]
        tool = "query_metric" if arm == "mcp" else "run_sql"
        wf = sum(1 for r in answerable if any(c["name"] == tool and not c["tool_error"] and c["result_type"] == "ok"
                                              for c in r["tool_calls"]) and grades[r["id"]]["c"] is True)
        row = {"answers": len(gs), "answerable": len(answerable), "well_formed_call_plus_numeric": wf,
               "tool_calls": sum(len(r["tool_calls"]) for r in rs),
               "primary_tool_calls (query_metric or run_sql)": sum(1 for r in rs for c in r["tool_calls"] if c["name"] == tool),
               "median_seconds": sorted(r["seconds"] for r in rs)[len(rs) // 2] if rs else None}
        for ax in AXES:
            app = [g[ax] for g in gs if g[ax] != "N/A"]
            row[ax] = f"{sum(1 for v in app if v is True)}/{len(app)}"
        cnt = collections.Counter(g["cell"] for g in gs)
        for c in CELLS:
            row[c] = cnt[c]
        out[arm] = row
    return out


def table(a, b, names):
    keys = list(next(iter(a.values())).keys())
    lines = [f"| measure | {names[0]} mcp | {names[1]} mcp | {names[0]} raw | {names[1]} raw |", "|---|---|---|---|---|"]
    for k in keys:
        lines.append(f"| {k} | {a['mcp'][k]} | {b['mcp'][k]} | {a['raw'][k]} | {b['raw'][k]} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--names", default="v1,v2")
    x = ap.parse_args()
    names = x.names.split(",")
    print(table(summarize(x.a), summarize(x.b), names))


if __name__ == "__main__":
    main()
