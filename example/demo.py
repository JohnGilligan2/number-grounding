"""Ground two sample answers against the same synthetic tool results and print every number's
classification. Runs offline in under a second.

    python example/demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from number_grounding import format_report, ground  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    sources = json.loads((HERE / "tool_results.json").read_text(encoding="utf-8"))
    question = "How did each office do last week, and how did February look by provider?"
    worst = 0
    for name in ("answer_faithful.txt", "answer_invented.txt"):
        answer = (HERE / name).read_text(encoding="utf-8")
        rep = ground(answer, sources, question)
        verdict = "PASS" if rep.ok() else f"FAIL ({len(rep.ungrounded)} UNGROUNDED)"
        print(f"== {name}: {len(rep.claims)} numbers, {verdict}")
        print(format_report(rep))
        print()
        worst = max(worst, 0 if rep.ok() else 1)
    return worst


if __name__ == "__main__":
    main()
