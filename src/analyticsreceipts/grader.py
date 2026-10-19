"""Four-axis grader. Deterministic: no model is used to grade.

Axes, graded per answer:
  a  metric          the governed receipt's metric_id and version equal gold (MCP arm). "N/A" for the
                     raw-SQL arm, which has no metric id; N/A is never counted as a failure or a pass.
  b  query           the last successful result table equals the expected table: same row count, every
                     expected cell matched (order- and column-name-invariant; extra columns allowed;
                     numbers within tolerance; dates normalised).
  c  number          every number the answer asserts (dates and numbers from the question excluded)
                     equals an expected cell within its rounding; at least one number is asserted.
  d  interpretation  the agent's resolved_spec equals gold field by field; on ambiguous or unanswerable
                     items, a clarification or an abstention passes.
Cells: correct · valid_wrong_question · valid_misreported · valid_misstated_spec · valid_metric_mismatch ·
invalid_right_intent · invalid_wrong · no_answer · correct_abstain · false_abstain · unwarranted_answer.
The headline count is valid_wrong_question: the query ran, and the EXECUTED query answered a different
question (axis b fails, or a trap is sprung). Rule ER-1, valid runs in order:
  not b, or trap_sprung       valid_wrong_question
  a ok, b, c, d               correct
  a ok, b, d, not c           valid_misreported
  a ok, b, not d              valid_misstated_spec   (right table; the stated reading differs from gold)
  not a ok, b                 valid_metric_mismatch  (right table; receipt metric id or version is not gold's)
Spec equivalences (axis d, ER-1): E1 a grain equals no grain when every period lies inside one bucket of
that grain; E2 `in [x]` equals `eq x`. Nothing data-dependent is treated as equivalent.
Trap items: trap_sprung is True when the result equals the trap's naive reading, or (interpretation trap)
when the incomplete flag is not raised, a missing resolved_spec included. It is None, with a reason, when
there is no answer to evaluate.
"""

import datetime as dt
import re

from .numbers import asserted, matches

ATOL, RTOL = 0.005, 1e-9   # a cell matches within min(ATOL, ATOL x |expected|): half a penny for money,
                           # 0.5 % relative for values under 1 (ratios); review finding 12
ANSWER_BEHAVIORS = ("answer", "answer_with_caveat")


# ---------------- table matching (axis b) ----------------
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")

def _norm_cell(v):
    if isinstance(v, bool):
        return ("s", str(v).lower())
    if isinstance(v, (int, float)):
        return ("n", float(v))
    s = str(v).strip()
    try:
        return ("n", float(s.replace(",", "")))
    except ValueError:
        pass
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return ("d", m.group(0))
    m = re.match(r"^(\d{4})-(\d{2})$", s)
    if m:
        return ("d", f"{m.group(1)}-{m.group(2)}-01")
    m = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{4})$", s)
    if m and m.group(1).lower()[:3] in _MONTHS:
        return ("d", f"{m.group(2)}-{_MONTHS.index(m.group(1).lower()[:3]) + 1:02d}-01")
    m = re.match(r"^(\d{4})\s*-?\s*Q([1-4])$", s, re.I) or re.match(r"^Q([1-4])\s+(\d{4})$", s, re.I)
    if m:
        y, q = (m.group(1), m.group(2)) if len(m.group(1)) == 4 else (m.group(2), m.group(1))
        return ("d", f"{y}-{(int(q) - 1) * 3 + 1:02d}-01")
    return ("s", s.lower())


def _cell_eq(e, a):
    if e[0] != a[0]:
        return False
    if e[0] == "n":
        return abs(e[1] - a[1]) <= max(min(ATOL, ATOL * abs(e[1])), RTOL * abs(e[1]))
    return e[1] == a[1]


def _row_covers(exp_row, agent_row):
    pool = list(agent_row)
    for e in exp_row:
        for i, a in enumerate(pool):
            if _cell_eq(e, a):
                pool.pop(i)
                break
        else:
            return False
    return True


def table_match(expected, columns, rows):
    """expected: {"columns", "rows"}. Rows match one-to-one, cells by value (extra agent columns allowed).

    Comparison tables carry a 'period' label ('current' / 'comparison'). If the agent's table also has a
    'period' column, the labels are compared like any other cell, so a table with the periods swapped
    fails. If it has no such column (e.g. raw SQL), rows are matched IN ORDER, current period first.
    """
    labelled = "period" in expected["columns"]
    agent_labelled = any(str(c).lower() == "period" for c in (columns or []))
    keep = [i for i, c in enumerate(expected["columns"]) if c != "period" or agent_labelled]
    exp = [[_norm_cell(r[i]) for i in keep] for r in expected["rows"]]
    got = [[_norm_cell(v) for v in r] for r in rows]
    if len(exp) != len(got):
        return False
    if labelled and not agent_labelled:
        return all(_row_covers(e, g) for e, g in zip(exp, got))

    return _perfect_matching([[j for j, g in enumerate(got) if _row_covers(e, g)] for e in exp], len(got))


def _perfect_matching(adj, n_right):
    """True iff every left node can be matched to a distinct right node (Kuhn's augmenting paths, written
    with an explicit stack: polynomial time and no recursion, so 1,000-row tables are fine)."""
    match_right = [-1] * n_right      # right node -> left node
    match_left = [-1] * len(adj)      # left node -> right node
    for start in range(len(adj)):
        seen = [False] * n_right
        parent = {}                   # right node -> left node it was reached from
        stack = [(start, 0)]          # (left node, index of its next candidate)
        found = None
        while stack:
            u, k = stack.pop()
            if k >= len(adj[u]):
                continue
            stack.append((u, k + 1))
            v = adj[u][k]
            if seen[v]:
                continue
            seen[v] = True
            parent[v] = u
            if match_right[v] == -1:
                found = v
                break
            stack.append((match_right[v], 0))
        if found is None:
            return False
        v = found                     # flip the augmenting path back to `start`
        while v != -1:
            u = parent[v]
            prev = match_left[u]
            match_left[u], match_right[v] = v, u
            v = prev
    return True


# ---------------- spec comparison (axis d) ----------------
def _norm_filters(fs):
    out = []
    for f in fs or []:
        op = f.get("op")
        v = f.get("value")
        if op == "in" and isinstance(v, list) and len(v) == 1:  # ER-1 E2
            op, v = "eq", v[0]
        if op in ("is_null", "not_null"):
            v = None
        elif op == "in" and isinstance(v, list):
            v = sorted(str(x) for x in v)
        elif v is not None:
            v = str(v)
        out.append((f.get("dim"), op, v if not isinstance(v, list) else tuple(v)))
    return sorted(out, key=repr)


def _norm_period(p):
    if not p:
        return None
    return (str(p.get("start")), str(p.get("end")))


def _flag(v):
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1")
    return bool(v)


def norm_spec(s):
    if not isinstance(s, dict):
        return None
    comp = s.get("comparison")
    rk = s.get("ranking")
    return {
        "metric": s.get("metric"),
        "filters": _norm_filters(s.get("filters")),
        "period": _norm_period(s.get("period")),
        "incomplete": _flag((s.get("period") or {}).get("incomplete", False)),
        "comparison": _norm_period(comp.get("period")) if isinstance(comp, dict) else None,
        "grain": s.get("grain"),
        "dimensions": sorted(s.get("dimensions") or []),
        "ranking": (rk.get("by", s.get("metric")), rk.get("direction", "desc"), rk.get("limit")) if isinstance(rk, dict) else None,
    }


def _bucket_key(day, grain):
    d = dt.date.fromisoformat(str(day)[:10])
    return {"day": (d.year, d.month, d.day), "month": (d.year, d.month),
            "quarter": (d.year, (d.month - 1) // 3), "year": (d.year,)}[grain]


def _one_bucket(period, grain):
    """True when the period [start, end] lies inside one bucket of `grain` (ER-1 E1)."""
    try:
        return _bucket_key(period[0], grain) == _bucket_key(period[1], grain)
    except (KeyError, TypeError, ValueError):
        return False


def _grain_equivalent(a, g):
    if a["grain"] == g["grain"]:
        return True
    if None not in (a["grain"], g["grain"]) or not g["period"]:
        return False
    grain = a["grain"] or g["grain"]
    return all(_one_bucket(p, grain) for p in (g["period"], g["comparison"]) if p)


def spec_mismatches(agent_spec, gold_spec):
    a, g = norm_spec(agent_spec), norm_spec(gold_spec)
    if a is None:
        return ["resolved_spec missing"]
    return [k for k in g if a[k] != g[k] and not (k == "grain" and _grain_equivalent(a, g))]


# ---------------- grading ----------------
UP_WORDS = re.compile(r"\b(rose|rise|rises|risen|increase[sd]?|grew|grow[sn]?|growth|higher|gain(?:ed|s)?|up(?! to\b))\b", re.I)
DOWN_WORDS = re.compile(r"\b(fell|fall(?:s|en)?|decrease[sd]?|declin(?:e|ed|es)|drop(?:ped|s)?|lower|down|shr[au]nk)\b", re.I)


def _comparison_values(expected):
    """(current, comparison) for a two-row comparison table, else None. Rows are current first."""
    cells = [float(v) for r in expected["rows"] for v in r if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return tuple(cells) if len(cells) == 2 else None


def _allowed_numbers(expected, comparison):
    cells = [float(v) for r in expected["rows"] for v in r if isinstance(v, (int, float)) and not isinstance(v, bool)]
    pair = _comparison_values(expected) if comparison else None
    if pair:
        cur, prev = pair
        # magnitudes of the change are allowed; its direction is checked separately (direction_error)
        cells += [cur - prev, abs(cur - prev)]
        if prev:
            cells += [(cur - prev) / prev, abs(cur - prev) / abs(prev), cur / prev]
    return cells


def direction_error(answer, expected, comparison):
    """A reason string if the answer's direction word contradicts the actual change, else None."""
    pair = _comparison_values(expected) if comparison else None
    if not pair or pair[0] == pair[1]:
        return None
    up, down = bool(UP_WORDS.search(answer or "")), bool(DOWN_WORDS.search(answer or ""))
    actual = "up" if pair[0] > pair[1] else "down"
    if (up and not down and actual == "down") or (down and not up and actual == "up"):
        return f"answer says {'up' if up else 'down'} but the change is {actual}"
    return None


def grade(item, expected, transcript):
    """item: golden item. expected: materialised entry or None. transcript: {arm, final_text, receipts[]}.
    Returns the grade dict (axes, cell, trap_sprung, reasons)."""
    from .contract import parse_final

    arm = transcript["arm"]
    final, why = parse_final(transcript.get("final_text"))
    ok = [r for r in transcript.get("receipts", []) if r and not r.get("error")]
    last = ok[-1] if ok else None
    want_answer = item["expected_behavior"] in ANSWER_BEHAVIORS
    g = {"item": item["id"], "arm": arm, "a": None, "b": None, "c": None, "d": None, "cell": None,
         "trap_sprung": None, "reasons": [], "contract_error": why, "valid": bool(ok)}

    behavior = final.get("behavior") if final else None
    if final is None:
        g["cell"] = "no_answer"
        g["reasons"].append(why)
        for k in "abcd":
            g[k] = "N/A" if (k == "a" and arm == "raw") else False
        return _trap_not_evaluated(item, g)

    if not want_answer:
        if behavior in ("clarify", "abstain"):
            g.update(a="N/A", b="N/A", c="N/A", d=True, cell="correct_abstain")
        else:
            g.update(a="N/A" if arm == "raw" else False, b=False, c=False, d=False, cell="unwarranted_answer")
            g["reasons"].append(f"answered a question that expects {item['expected_behavior']}")
        return _trap_not_evaluated(item, g)

    gold = item["resolved_spec"]
    if behavior in ("clarify", "abstain"):
        g.update(a="N/A" if arm == "raw" else False, b=False, c=False, d=False, cell="false_abstain")
        g["reasons"].append(f"{behavior} on an answerable item")
        return _trap_not_evaluated(item, g)

    # axis a
    if arm == "raw":
        g["a"] = "N/A"
    else:
        gov = [r for r in ok if r.get("kind") in ("governed_metric", "control_metric")]  # metric identity is read the same way
        r = gov[-1] if gov else None
        g["a"] = bool(r and r["metric_id"] == gold["metric"] and r["metric_def_version"] == expected["metric_def_version"])
        if not g["a"]:
            if r and r["metric_id"] == gold["metric"]:
                g["reasons"].append(f"metric version {r['metric_def_version']} != {expected['metric_def_version']}")
            else:
                g["reasons"].append(f"metric {r['metric_id'] if r else None} != {gold['metric']}")
    # axis b
    g["b"] = bool(last and table_match(expected, last["result"]["columns"], last["result"]["rows"]))
    if not g["b"]:
        g["reasons"].append("result table does not match the expected table")
    # axis c
    nums = asserted(final.get("answer") or "", item["question"])
    allowed = _allowed_numbers(expected, gold.get("comparison"))
    g["c"] = bool(nums) and all(matches(n, allowed) for n in nums)
    if not g["c"]:
        g["reasons"].append("no number asserted" if not nums else "an asserted number matches no expected cell")
    derr = direction_error(final.get("answer") or "", expected, gold.get("comparison"))
    if derr:
        g["c"] = False
        g["reasons"].append(derr)
    # axis d
    mm = spec_mismatches(final.get("resolved_spec"), gold)
    g["d"] = not mm
    if mm:
        g["reasons"].append("spec fields differ: " + ", ".join(mm))
    # trap first
    if item.get("trap"):
        naive = expected.get("naive")
        if naive is not None:
            g["trap_sprung"] = bool(last and table_match(naive, last["result"]["columns"], last["result"]["rows"]))
        else:  # interpretation trap (incomplete period): sprung if the flag was not raised
            g["trap_sprung"] = "incomplete" in mm or "resolved_spec missing" in mm
    a_ok = g["a"] in (True, "N/A")
    if not g["valid"]:
        g["cell"] = "invalid_right_intent" if g["d"] else "invalid_wrong"
        g["reasons"].append("no query succeeded")
    elif not g["b"] or g["trap_sprung"]:
        g["cell"] = "valid_wrong_question"
    elif a_ok and g["c"] and g["d"]:
        g["cell"] = "correct"
    elif a_ok and g["d"]:
        g["cell"] = "valid_misreported"
    elif a_ok:
        g["cell"] = "valid_misstated_spec"
    else:
        g["cell"] = "valid_metric_mismatch"
    return g


def _trap_not_evaluated(item, g):
    if item.get("trap"):
        g["reasons"].append("trap not evaluated: no answer to evaluate")
    return g
