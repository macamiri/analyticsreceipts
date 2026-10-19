"""Extract the numbers an answer asserts, and match them against result cells with rounding tolerance.

Dates and periods are removed first (ISO dates, "November 2011", "Q1 2011", bare years), and so is any
number that already appears in the question, so "revenue in 2011 was £1.2m" asserts only 1.2m.
A number written with d decimals matches a value within half a unit of its last digit, but never more
loosely than 5 % of the value (a stated number must carry about two significant figures).
Not asserted values (review finding 11): counts in rank phrases ("top 5"), durations ("9 days",
"11 months"), ordinals ("3rd"). A bare integer 1900-2100 is a year only in a year context (after "in",
"since", "between", ... or before "and"/"to"/a dash) or when it is a number in the question; otherwise it
is checked like any other value.
"""

import re

MONTHS = ("january|february|march|april|may|june|july|august|september|october|november|december|"
          "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")
_DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?\b"),
    re.compile(r"\b\d{4}-\d{2}\b"),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS})\.?(?:\s+\d{{4}})?\b", re.I),
    re.compile(rf"\b(?:{MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.I),
    re.compile(rf"\b(?:{MONTHS})\.?\s+\d{{4}}\b", re.I),
    re.compile(r"\bQ[1-4]\s*(?:of\s+)?\d{4}\b", re.I),
    re.compile(r"\b\d{4}\s*-?\s*Q[1-4]\b", re.I),
    re.compile(r"\bQ[1-4]\b", re.I),
    re.compile(r"\b\d{1,2}:\d{2}\b"),
]
_NUM = re.compile(r"(?<![\w.])([-−]?)[£$€]?(\d{1,3}(?:,\d{3})+|\d+|(?=\.\d))(\.\d+)?\s*(%|percent\b|per cent\b|k\b|thousand\b|m\b|mn\b|million\b|bn\b|billion\b)?", re.I)
_NOT_VALUES = [
    re.compile(r"\b(?:top|bottom|first|last)\s+\d+\b", re.I),
    re.compile(r"\b\d+\s+(?:days?|weeks?|months?|quarters?|years?)\b", re.I),
    re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.I),
]
_YEAR_BEFORE = re.compile(r"\b(?:in|of|during|since|from|to|until|through|between|and|for|year|fy|calendar|vs\.?|versus|than)\s*$", re.I)
_YEAR_AFTER = re.compile(r"^\s*(?:and\b|to\b|-|–|—)", re.I)
MAX_REL_TOL = 0.05
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}


def _strip_dates(text):
    for p in _DATE_PATTERNS + _NOT_VALUES:
        text = p.sub(" ", text)
    return text


def extract(text, years=()):
    """[(value, tolerance, is_percent)] for every asserted number. `years`: year numbers from the question."""
    out = []
    text = _strip_dates(text or "")
    for m in _NUM.finditer(text):
        sign, whole, frac, unit = m.groups()
        unit = (unit or "").lower().strip()
        v = float((whole or "0").replace(",", "") + (frac or ""))
        if sign:
            v = -v
        dp = len(frac) - 1 if frac else 0
        tol = 0.5 * 10 ** (-dp)
        pct = unit in ("%", "percent", "per cent")
        if unit in _SCALE:
            v *= _SCALE[unit]
            tol *= _SCALE[unit]
        if not frac and not unit and not sign and "," not in whole and 1900 <= v <= 2100 and (
                v in years or _YEAR_BEFORE.search(text[:m.start()]) or _YEAR_AFTER.search(text[m.end():])):
            continue  # a bare year
        out.append((v, tol + 1e-9, pct))
    return out


def _question_years(question):
    return {float(y) for y in re.findall(r"(?<![\d,.])(19\d\d|20\d\d|2100)(?![\d,.])", question or "")}


def asserted(answer, question):
    """Numbers in the answer that are not dates and not already in the question."""
    years = _question_years(question)
    q = {round(v, 9) for v, _, _ in extract(question, years)}
    return [n for n in extract(answer, years) if round(n[0], 9) not in q]


def _within(diff, tol, target):
    return diff <= min(tol, MAX_REL_TOL * abs(target)) + 1e-9 if target else diff <= tol


def matches(n, allowed):
    v, tol, pct = n
    for a in allowed:
        if _within(abs(v - a), tol, a):
            return True
        if pct and _within(abs(v / 100 - a), tol / 100, a):
            return True
        if pct and _within(abs(v - a * 100), tol, a * 100):  # a ratio cell stated as a percentage
            return True
    return False
