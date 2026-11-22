"""Check one answer for numbers that cannot be traced to the tool results.

    python -m number_grounding.check_answer ANSWER.txt RESULTS.json [--question QUESTION.txt]

ANSWER.txt   the model's answer, as plain text (pasted from a chat is fine).
RESULTS.json either the tool results themselves (one JSON object, or a list of them), or a
             conversation in Messages API shape ({"messages": [...]} or a bare list of
             messages), in which case every tool_result block is read out of it.
--question   optional; numbers that echo the user's question are not counted as invented.

Exit 0 when every number is GROUNDED or DERIVED, 1 when at least one is UNGROUNDED, 2 on bad
input. When you only have the answer and not the exact tool results (a chat UI does not hand
them over), pass a broad set of report outputs instead. That is weaker, because a number can
match a value from an unrelated report by coincidence, but an invented number usually has
nothing to match.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .grounding import format_report, ground, tool_results_from_messages


def load_sources(raw: Any) -> list[Any]:
    """Tool results from either a results file or a conversation."""
    if isinstance(raw, dict) and isinstance(raw.get("messages"), list):
        return tool_results_from_messages(raw["messages"])
    if (isinstance(raw, list) and raw and all(isinstance(m, dict) for m in raw)
            and all("role" in m and "content" in m for m in raw)):
        return tool_results_from_messages(raw)
    return raw if isinstance(raw, list) else [raw]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("answer", type=Path)
    ap.add_argument("results", type=Path)
    ap.add_argument("--question", type=Path)
    a = ap.parse_args(argv)
    try:
        answer = a.answer.read_text(encoding="utf-8")
        sources = load_sources(json.loads(a.results.read_text(encoding="utf-8")))
        question = a.question.read_text(encoding="utf-8") if a.question else ""
    except (OSError, ValueError) as e:
        print(f"cannot read input: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    rep = ground(answer, sources, question)
    n_ok = sum(c.status == "GROUNDED" for c in rep.claims)
    print(f"numbers: {len(rep.claims)}  grounded: {n_ok}  derived: {len(rep.derived)}  "
          f"UNGROUNDED: {len(rep.ungrounded)}")
    print(format_report(rep))
    return 0 if rep.ok() else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
