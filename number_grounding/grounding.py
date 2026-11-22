"""Number-grounding checker: every number Claude writes must come from the report data.

A hallucination check that needs no model. Each number in an answer is extracted with its
displayed precision ($2.35M means 2,345,000-2,355,000) and classified:

  GROUNDED    rounds to a number in the source data (tool results) at the precision shown, or a
              source fraction shown as a percent (0.628 -> 62.8%).
  DERIVED     one arithmetic step from source numbers: a+b, a-b, a/b as a percent, or a percent
              change (a-b)/b. Reported with the formula so a person can check it.
  UNGROUNDED  neither. One of these fails the case: the number came from nowhere in the data.

Derivations are searched only over summary-level numbers (summary, trend, top-level fields,
small row lists). Pairwise sums over thousands of row values would match almost any number
and make the check meaningless.

Dates, years, times and list numbering are not claims and are skipped. Numbers that appear in
the user's own question are skipped (echoing the question is not a hallucination).
"""
from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

MONTHS = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
          r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
# Spans that are dates/times, not claims. Removed before number extraction.
DATE_PATTERNS = [
    re.compile(r"\b(19|20)\d{2}-\d{2}(-\d{2})?\b"),                                   # 2026-11-09, 2026-11
    re.compile(r"\b\d{1,2}\s*[-–—]\s*\d{1,2}\s+" + MONTHS + r"\b", re.I),   # 9-15 November
    # day-before-month first: in "Week of 9 Nov\n8-week" the 9 belongs to Nov, not the 8
    re.compile(r"\b\d{1,2}(st|nd|rd|th)?\s+(of\s+)?" + MONTHS + r"\b", re.I),        # 9 November
    re.compile(r"\b" + MONTHS + r"\.?[ \t]+\d{1,2}(\s*[-–—]\s*\d{1,2})?(st|nd|rd|th)?\b", re.I),  # Nov 9-15
    re.compile(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b"),                                    # 11/9/2026
    re.compile(r"\b\d{1,2}:\d{2}(\s*[ap]\.?m\.?)?\b", re.I),                          # 6:31 am
    re.compile(r"\b(19|20)\d{2}\b"),                                                  # bare years
    re.compile(r"(?m)^\s*\d+[.)]\s"),                                                 # "1. " list numbering
    re.compile(r"\bweek\s+\d{1,2}\b", re.I),
]
NUM = re.compile(
    r"(?P<sign>[-−])?\s?(?P<cur>\$)?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s?(?P<suf>%|k\b|K\b|M\b|m\b|million\b|thousand\b|bn\b)?"
)
MULT = {"k": 1e3, "K": 1e3, "thousand": 1e3, "M": 1e6, "m": 1e6, "million": 1e6, "bn": 1e9}


@dataclass
class Claim:
    text: str
    value: float
    tol: float
    percent: bool
    status: str = ""
    how: str = ""


@dataclass
class GroundingReport:
    claims: list[Claim] = field(default_factory=list)

    @property
    def ungrounded(self) -> list[Claim]:
        return [c for c in self.claims if c.status == "UNGROUNDED"]

    @property
    def derived(self) -> list[Claim]:
        return [c for c in self.claims if c.status == "DERIVED"]

    def ok(self) -> bool:
        return not self.ungrounded


ISO_DATETIME = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b")
CLOCK_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
STRING_DATE_PATTERNS = [ISO_DATETIME, CLOCK_TIME, *DATE_PATTERNS]


def _blank(text: str, patterns: Iterable[re.Pattern]) -> str:
    for p in patterns:
        text = p.sub(lambda m: " " * len(m.group(0)), text)
    return text


def extract_claims(text: str) -> list[Claim]:
    """Numbers in an answer with the tolerance their display precision implies."""
    clean = _blank(text, DATE_PATTERNS)
    out = []
    for m in NUM.finditer(clean):
        raw = m.group("num")
        if not raw:
            continue
        val = float(raw.replace(",", ""))
        dec = len(raw.split(".")[1]) if "." in raw else 0
        suf = m.group("suf") or ""
        mult = MULT.get(suf, 1.0)
        # half a unit of the last displayed digit: the value must ROUND to what is shown
        # (a full unit let unrelated neighbours match; 2% slack covers float noise)
        tol = 0.51 * (10 ** -dec) * mult
        if m.group("sign") and m.group("cur"):
            val = -val
        out.append(Claim(text=m.group(0).strip(), value=val * mult, tol=tol, percent=(suf == "%")))
    return out


def numbers_in(obj: Any) -> list[float]:
    """Every number in a JSON-like structure, including numbers inside strings ('0-30', '11')."""
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        # Dates and times inside strings are not quantities: "2026-11-09" used to yield
        # 2026, -11 and -9, which then "explained" invented figures as derivations.
        s = _blank(obj.replace(",", ""), STRING_DATE_PATTERNS)
        # A minus sign only counts when it is not a range or date separator ("0-30").
        for m in re.finditer(r"(?:(?<![\w.])-)?\d+(?:\.\d+)?", s):
            try:
                out.append(float(m.group(0)))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(numbers_in(str(k)))  # 'bal_over_90', 'bal_31_60' name real concepts
            out.extend(numbers_in(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(numbers_in(v))
    return out


def summary_numbers(result: Any, small_rows: int = 60) -> list[float]:
    """Numbers eligible for one-step derivations: everything except long row lists."""
    if not isinstance(result, dict):
        return numbers_in(result)
    out: list[float] = []
    for k, v in result.items():
        if k == "rows" and isinstance(v, list) and len(v) > small_rows:
            continue
        out.extend(numbers_in(v))
    return out


def _row_dicts(obj: Any):
    """Every dict in a JSON structure (each report row is one)."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _row_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _row_dicts(v)


def row_derivations(sources: list[Any]) -> dict[float, str]:
    """Sums and differences of two money fields inside one row, e.g. 'collections = patient +
    insurance' for a month. Money values carry cents, so a match is specific.

    Percent ratios inside rows are deliberately NOT generated: tried 2026-11-20, a few hundred
    rows produced ~100k candidate percentages, enough to 'explain' any figure to one decimal.
    Such percentages are left to the judge (JUDGE-ONLY) or reported UNGROUNDED."""
    out: dict[float, str] = {}
    for d in (x for s in sources for x in _row_dicts(s)):
        nums = [(k, float(v)) for k, v in d.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool) and k not in ("n", "weekday")]
        if not 2 <= len(nums) <= 12:
            continue
        for i, (ka, a) in enumerate(nums):
            for kb, b in nums[i + 1:]:
                out.setdefault(round(a + b, 6), f"{ka}+{kb} in one row")
                out.setdefault(round(a - b, 6), f"{ka}-{kb} in one row")
                out.setdefault(round(b - a, 6), f"{kb}-{ka} in one row")
    return out


class _Index:
    def __init__(self, vals: Iterable[float]):
        self.v = sorted(set(round(x, 6) for x in vals))

    def near(self, lo: float, hi: float) -> float | None:
        i = bisect.bisect_left(self.v, lo)
        return self.v[i] if i < len(self.v) and self.v[i] <= hi else None


def _fmt(x: float) -> str:
    return f"{x:,.4f}".rstrip("0").rstrip(".")


def ground(answer: str, sources: list[Any], question: str = "", extra_ok: Iterable[float] = ()) -> GroundingReport:
    """Classify every number in `answer` against the tool results in `sources`."""
    src = [n for s in sources for n in numbers_in(s)]
    src += [abs(n) for n in src if n < 0]  # "$1.9M of credits" for a stored -1,904,512
    direct = _Index([*src, *extra_ok])
    deriv_vals = sorted(set(round(n, 6) for s in sources for n in summary_numbers(s)))
    deriv = _Index(deriv_vals)
    rowd = row_derivations(sources)
    rowd_idx = _Index(rowd.keys())
    asked = {round(c.value, 6) for c in extract_claims(question)}
    rep = GroundingReport()
    for c in extract_claims(answer):
        lo, hi = c.value - c.tol, c.value + c.tol
        if round(c.value, 6) in asked:
            c.status, c.how = "GROUNDED", "in the question"
        elif (m := direct.near(lo, hi)) is not None:
            c.status, c.how = "GROUNDED", f"source value {_fmt(m)}"
        elif c.percent and (m := direct.near(lo / 100, hi / 100)) is not None:
            c.status, c.how = "GROUNDED", f"source fraction {_fmt(m)} as a percent"
        elif abs(c.value) < 1e-9:
            c.status, c.how = "GROUNDED", "zero"
        elif (m := rowd_idx.near(lo, hi)) is not None:
            c.status, c.how = "DERIVED", f"{rowd[m]} = {_fmt(m)}"
        elif c.value < 0 and (m := rowd_idx.near(-hi, -lo)) is not None:
            c.status, c.how = "DERIVED", f"-({rowd[m]}) = {_fmt(-m)}"
        else:
            c.status, c.how = "UNGROUNDED", "not in the data and not one step from it"
            for a in deriv_vals:
                if c.percent:
                    # c = 100*a/b  or  c = 100*(a-b)/b  ->  b = 100a/c  or  b = 100a/(c+100)
                    for denom_c, label in ((c.value, "a/b"), (c.value + 100, "(a-b)/b")):
                        if denom_c <= 0 or a == 0:
                            continue
                        b_lo, b_hi = sorted((100 * a / (denom_c + c.tol), 100 * a / max(denom_c - c.tol, 1e-9)))
                        b = deriv.near(b_lo, b_hi)
                        if b:
                            c.status = "DERIVED"
                            c.how = (f"{label} with a={_fmt(a)}, b={_fmt(b)}" if label == "a/b"
                                     else f"(a-b)/b with a={_fmt(a)}, b={_fmt(b)}")
                            break
                else:
                    b = deriv.near(lo - a, hi - a)
                    if b is not None and a != 0 and b != 0:
                        c.status, c.how = "DERIVED", f"{_fmt(a)} + {_fmt(b)}"
                    else:
                        b = deriv.near(a - hi, a - lo)
                        if b is not None and b != 0:
                            c.status, c.how = "DERIVED", f"{_fmt(a)} - {_fmt(b)}"
                if c.status == "DERIVED":
                    break
        rep.claims.append(c)
    return rep


def format_report(rep: GroundingReport) -> str:
    lines = []
    for c in rep.claims:
        lines.append(f"  {c.status:<10} {c.text:<16} {c.how}")
    return "\n".join(lines)


def tool_results_from_messages(messages: list[dict[str, Any]]) -> list[Any]:
    """The JSON payload of every tool_result in a conversation (what Claude actually saw)."""
    out = []
    for m in messages:
        if m.get("role") != "user" or not isinstance(m.get("content"), list):
            continue
        for b in m["content"]:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                try:
                    out.append(json.loads(b.get("content") or "null"))
                except (TypeError, ValueError):
                    out.append(b.get("content"))  # error text: its numbers still count as seen
    return out
