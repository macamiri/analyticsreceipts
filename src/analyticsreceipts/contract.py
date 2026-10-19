"""The output contract both arms must follow, and its parser.

The agent's last message is one JSON object:
  {"behavior": "answer" | "clarify" | "abstain",
   "resolved_spec": {metric, filters, period{start, end, incomplete}, comparison, grain, dimensions, ranking} | null,
   "answer": "<one or two sentences stating the number>" | null,
   "clarification_question": "<question>" | null,
   "abstain_reason": "<reason>" | null}
"""

import json
import re

BEHAVIORS = ("answer", "clarify", "abstain")

CONTRACT_TEXT = (
    "When you are done, reply with ONLY one JSON object and nothing else:\n"
    '{"behavior": "answer" | "clarify" | "abstain",\n'
    ' "resolved_spec": {"metric": str, "filters": [{"dim": str, "op": "eq"|"ne"|"in"|"is_null", "value": ...}],\n'
    '                   "period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "incomplete": bool},\n'
    '                   "comparison": {"period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}} | null,\n'
    '                   "grain": "day"|"month"|"quarter"|"year"|null, "dimensions": [str],\n'
    '                   "ranking": {"by": str, "direction": "asc"|"desc", "limit": int} | null} | null,\n'
    ' "answer": str | null, "clarification_question": str | null, "abstain_reason": str | null}\n'
    "Use behavior \"clarify\" when the question is ambiguous and \"abstain\" when the data cannot answer it; "
    "then resolved_spec is null. Set period.incomplete to true when the period extends past the end of the data."
)


def parse_final(text):
    """Returns (dict, None) or (None, reason). Accepts a fenced ```json block or the first JSON object."""
    if not text or not text.strip():
        return None, "empty final message"
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [m.group(1)] if m else []
    start = text.find("{")
    if start >= 0:  # the first JSON object, decoded properly (braces inside strings do not count)
        try:
            candidates.append(json.JSONDecoder().raw_decode(text, start)[0])
        except json.JSONDecodeError:
            pass
    for c in candidates:
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except json.JSONDecodeError:
                continue
        if isinstance(c, dict) and c.get("behavior") in BEHAVIORS:
            return c, None
    return None, "final message is not a contract JSON object"
