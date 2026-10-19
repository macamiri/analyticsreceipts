"""Grade a replay offline and write the report. Needs no warehouse and no network.

  python -m analyticsreceipts.report fixtures replays/fixtures-v1.json [--broken replays/fixtures-v1-broken.json] --out reports/m1-fixtures.md
  python -m analyticsreceipts.report live replays/live-lite.jsonl --out reports/m1-live-lite.md

Rates are counts over the answers an axis applies to; N/A is excluded from both numerator and
denominator and printed separately. Nulls are printed as nulls.
"""

import argparse
import collections
import json
import math
from pathlib import Path

from .grader import grade
from .paths import find_root

ROOT = find_root() or Path.cwd()  # eval data: see paths.py (a clone's root, or $ANALYTICSRECEIPTS_ROOT)
# The canonical expected tables. Frozen files are never edited; a provably wrong one is superseded by a new
# version and this pointer moves (golden/expected-v1.json stays byte-identical as the record).
EXPECTED_TABLES = ROOT / "golden" / "expected-v2.json"  # v1 SQL hashes are stale for G02/G03/G07 (pre-fix compiler)
AXES = ("a", "b", "c", "d")
CELLS = ("correct", "valid_wrong_question", "valid_misreported", "valid_misstated_spec", "valid_metric_mismatch",
         "invalid_right_intent", "invalid_wrong", "no_answer", "correct_abstain", "false_abstain", "unwarranted_answer")


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def load_refs():
    golden = {i["id"]: i for i in json.loads((ROOT / "golden" / "golden-v1.json").read_text())["items"]}
    expected = json.loads(EXPECTED_TABLES.read_text())["items"]
    return golden, expected


def grade_runs(runs):
    golden, expected = load_refs()
    out = []
    for r in runs:
        item = golden[r["item"]]
        g = grade(item, expected.get(r["item"]), {"arm": r["arm"], "final_text": r["final_text"],
                                                   "receipts": r["receipts"]})
        g["run_id"] = r.get("id")
        out.append(g)
    return out


def axis_table(grades, arms=("mcp", "raw")):
    rows = []
    for arm in arms:
        gs = [g for g in grades if g["arm"] == arm]
        if not gs:
            continue
        cells = []
        for ax in AXES:
            vals = [g[ax] for g in gs]
            app = [v for v in vals if v != "N/A"]
            k = sum(1 for v in app if v is True)
            na = len(vals) - len(app)
            cells.append(f"{k}/{len(app)}" + (f" (N/A {na})" if na else ""))
        rows.append(f"| {arm} | {len(gs)} | " + " | ".join(cells) + " |")
    return "| arm | answers | a metric | b query | c number | d interpretation |\n|---|---|---|---|---|---|\n" + "\n".join(rows)


def cell_table(grades):
    arms = sorted({g["arm"] for g in grades})
    cnt = {a: collections.Counter(g["cell"] for g in grades if g["arm"] == a) for a in arms}
    head = "| cell | " + " | ".join(arms) + " |\n|---|" + "---|" * len(arms)
    body = "\n".join(f"| {c} | " + " | ".join(str(cnt[a][c]) for a in arms) + " |" for c in CELLS)
    return head + "\n" + body


def fixtures_report(replay_path, broken_path=None):
    replay = json.loads(Path(replay_path).read_text())
    exp = json.loads((ROOT / "fixtures" / "expected-grades-v1.json").read_text())
    grades = grade_runs(replay["runs"])
    keys = ("a", "b", "c", "d", "cell", "trap_sprung")
    agree, disagree = 0, []
    for g in grades:
        e = exp["grades"][g["run_id"]]
        diff = {k: (e[k], g[k]) for k in keys if e[k] != g[k]}
        if diff:
            disagree.append((g["run_id"], diff, g["reasons"]))
        else:
            agree += 1
    lines = [f"# M1 FIXTURES report", "",
             "**Label: FIXTURES.** Recorded transcripts with planted failures, executed against the real server, "
             "raw-SQL tools and grader. These are not model outputs and say nothing about any model.", "",
             f"Inputs: transcripts `{replay['inputs']['transcripts_sha256'][:12]}`, expected grades "
             f"`{replay['inputs']['expected_grades_sha256'][:12]}`, golden `{replay['inputs']['golden_sha256'][:12]}`, "
             f"expected tables `{replay['inputs']['expected_tables_sha256'][:12]}`, semantic model "
             f"`{replay['inputs']['semantic_model_sha256'][:12]}`.", "",
             "## Grader vs pre-registered expected grades", "",
             f"Agreement: **{agree}/{len(grades)}** fixtures match on every field (a, b, c, d, cell, trap_sprung).", ""]
    if disagree:
        lines += ["Disagreements (reported, not resolved by editing the expected grades):", ""]
        for rid, diff, reasons in disagree:
            lines.append(f"- {rid}: " + "; ".join(f"{k} expected {e!r}, got {v!r}" for k, (e, v) in diff.items())
                         + f" — grader reasons: {reasons}")
        lines.append("")
    lines += ["## Per-axis results", "", axis_table(grades), "", "## Cells", "", cell_table(grades), "",
              f"Valid SQL, wrong question (headline count): **{sum(g['cell'] == 'valid_wrong_question' for g in grades)}**.", "",
              f"Traps sprung: {sum(1 for g in grades if g['trap_sprung'] is True)} of "
              f"{sum(1 for g in grades if g['trap_sprung'] is not None)} trap answers.", "",
              "## Controls", "",
              f"- Canary (known answer {replay['canary']['known_answer']}): result {replay['canary']['result']}, "
              f"**{'PASS' if replay['canary']['pass'] else 'FAIL'}**."]
    if broken_path:
        b = json.loads(Path(broken_path).read_text())
        bg = {g["run_id"]: g for g in grade_runs(b["runs"])}
        gg = {g["run_id"]: g for g in grades}
        changed = {rid: {k: (gg[rid][k], bg[rid][k]) for k in keys if gg[rid][k] != bg[rid][k]} for rid in gg}
        changed = {k: v for k, v in changed.items() if v}
        exp_change = exp["controls"]["planted_broken_compiler"]["expected_grade_changes"]
        match = set(changed) == set(exp_change) and all(
            all(bg[rid][k] == v for k, v in exp_change[rid].items()) for rid in exp_change)
        lines += [f"- Planted broken compiler (`{b['planted_bug']}`): canary result {b['canary']['result']}, "
                  f"**{'FAIL (as required)' if not b['canary']['pass'] else 'PASS (CONTROL FAILED: the eval cannot see the bug)'}**.",
                  f"- Grades that changed under the broken compiler: "
                  + (", ".join(f"{rid} {d}" for rid, d in changed.items()) or "none")
                  + f". Pre-registered change: {list(exp_change)}. **{'As pre-registered' if match else 'DIFFERS from pre-registration'}**."]
    lines += ["", "## Per-fixture grades", "", "| fixture | arm | item | planted | a | b | c | d | cell | trap |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    planted = {r["id"]: r["planted"] for r in replay["runs"]}
    for g in grades:
        lines.append(f"| {g['run_id']} | {g['arm']} | {g['item']} | {planted[g['run_id']]} | {g['a']} | {g['b']} | "
                     f"{g['c']} | {g['d']} | {g['cell']} | {g['trap_sprung']} |")
    return "\n".join(lines) + "\n", grades, agree, disagree


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["fixtures", "live"])
    ap.add_argument("replay")
    ap.add_argument("--broken")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default=None, help="a line printed under the report title (e.g. which grader)")
    a = ap.parse_args()
    if a.kind == "fixtures":
        md, grades, agree, dis = fixtures_report(a.replay, a.broken)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md)
        Path(a.out).with_suffix(".grades.json").write_text(json.dumps(grades, indent=1) + "\n")
        print(f"agreement {agree}/{len(grades)}; disagreements {len(dis)} -> {a.out}")
    else:
        from .live import live_report
        md = live_report(a.replay, a.label)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md)
        print(f"-> {a.out}")


if __name__ == "__main__":
    main()
