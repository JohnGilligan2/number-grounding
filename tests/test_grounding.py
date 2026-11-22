"""The checker must catch invented numbers and pass faithful answers.

Each planted case is an answer with one made-up figure; the checker must flag exactly that one.
All figures are synthetic.

    python -m pytest -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import number_grounding as g
from number_grounding.check_answer import load_sources, main as check_main

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "example"

WEEKLY = {"tool": "weekly_summary", "params": {"week_start": "2026-03-09", "threshold_pct": 10},
          "summary": {"offices": [
              {"office": "Office A",
               "collections": {"this_week": {"value": 48210.37}, "trailing_8wk_avg": {"value": 41980.12},
                               "pct_vs_avg": 14.8, "flag": True},
               "net_production": {"this_week": {"value": 61377.50}, "trailing_8wk_avg": {"value": 59420.08},
                                  "pct_vs_avg": 3.3},
               "fill": {"fill_rate": {"value": 0.7425}}}]},
          "notes": ["Days with fewer than 11 patients are hidden", "8-week average"]}
AR = {"rows": [{"office": "Office A", "bal_over_90": 1204388.40, "debit_balances": 2351204.18,
                "credit_balances": -1904512.07, "bal_total": 446692.11}]}


def statuses(answer, sources, q=""):
    return {c.text: c.status for c in g.ground(answer, sources, q).claims}


def test_faithful_answer_is_fully_grounded():
    ans = ("For the week of 9-15 March, Office A collections were $48,210, 14.8% above its "
           "8-week average of $41,980 ($42.0k). Net production was $61.4k (+3.3%). March fill is 74.3%. "
           "Cells under 11 patients are hidden.")
    rep = g.ground(ans, [WEEKLY])
    assert rep.ok(), g.format_report(rep)


def test_invented_number_is_caught():
    ans = "Office A collections were $48,210, and the office saw 412 new patients that week."
    st = statuses(ans, [WEEKLY])
    assert st["412"] == "UNGROUNDED" and st["$48,210"] == "GROUNDED"


def test_wrong_rounding_is_caught():
    # $48.2k is right; $51k is not a rounding of 48,210.37
    assert statuses("Collections were $51k.", [WEEKLY])["$51k"] == "UNGROUNDED"
    assert statuses("Collections were $48.2k.", [WEEKLY])["$48.2k"] == "GROUNDED"


def test_invented_percent_is_caught_and_true_derivation_is_shown():
    assert statuses("Collections rose 31% on the average.", [WEEKLY])["31%"] == "UNGROUNDED"
    rep = g.ground("The gap is $6,230 (collections 114.8% of the average).", [WEEKLY])
    by = {c.text: c for c in rep.claims}
    assert by["$6,230"].status == "DERIVED" and "-" in by["$6,230"].how
    assert by["114.8%"].status in ("GROUNDED", "DERIVED")


def test_millions_and_negative_credit_balances():
    ans = "Owed: $2.35M, of which $1.20M is over 90 days. Credits: -$1.90M. Net $446,692."
    rep = g.ground(ans, [AR])
    assert rep.ok(), g.format_report(rep)
    assert statuses("Credits total -$4.9M.", [AR])["-$4.9M"] == "UNGROUNDED"


def test_dates_years_and_list_numbers_are_not_claims():
    ans = "1. In 2026-02 and on 9 March 2026 at 6:31 am, see week 11.\n2. Mar 9-15 is the window."
    assert g.extract_claims(ans) == []


def test_numbers_from_the_question_are_not_hallucinations():
    st = statuses("Claims over 90 days: none visible.", [AR], q="Which claims are over 90 days?")
    assert st["90"] == "GROUNDED"


def test_no_data_office_any_figure_is_ungrounded():
    office_c = {"offices_without_data": [{"office": "Office C", "status": "unknown: no data"}], "rows": []}
    st = statuses("Office C's net production in February was $418,750.", [office_c])
    assert st["$418,750"] == "UNGROUNDED"


def test_tool_results_are_read_from_the_conversation():
    msgs = [{"role": "user", "content": "q"},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": '{"a": 5}'}]}]
    assert g.tool_results_from_messages(msgs) == [{"a": 5}]


def test_cli_reads_results_files_and_conversations(tmp_path, capsys):
    results = EXAMPLE / "tool_results.json"
    assert check_main([str(EXAMPLE / "answer_faithful.txt"), str(results)]) == 0
    assert check_main([str(EXAMPLE / "answer_invented.txt"), str(results)]) == 1
    out = capsys.readouterr().out
    assert "UNGROUNDED $57,900" in " ".join(out.split())
    # The same results wrapped in a conversation, as a Messages API transcript holds them.
    convo = {"messages": [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": f"t{i}", "content": json.dumps(r)}
        for i, r in enumerate(json.loads(results.read_text(encoding="utf-8")))]}]}
    assert len(load_sources(convo)) == 3
    p = tmp_path / "convo.json"
    p.write_text(json.dumps(convo), encoding="utf-8")
    assert check_main([str(EXAMPLE / "answer_faithful.txt"), str(p)]) == 0
    assert check_main([str(tmp_path / "missing.txt"), str(p)]) == 2


def test_example_demo_runs_and_prints_every_class():
    r = subprocess.run([sys.executable, str(EXAMPLE / "demo.py")], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    for word in ("GROUNDED", "DERIVED", "UNGROUNDED", "answer_faithful.txt: 15 numbers, PASS"):
        assert word in r.stdout


def test_dates_and_times_inside_strings_are_not_numbers():
    from number_grounding.grounding import numbers_in

    vals = numbers_in({"as_of": "2026-11-09T06:30:00Z", "week": "Nov 9", "at": "14:05", "band": "0-30"})
    assert vals == [0.0, 30.0]


def test_invented_figure_cannot_borrow_a_date_part():
    from number_grounding.grounding import ground

    rep = ground("Collections fell 11 percent.", [{"day": "2026-11-09", "collections": 48210.37}])
    assert [c.status for c in rep.claims] == ["UNGROUNDED"]
