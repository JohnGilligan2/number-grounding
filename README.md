# number-grounding

A deterministic check that every number in a model's answer came from the tool results it was
given. No model, no API key, standard library only.

When a model answers from report data, the failure that hurts is a number that isn't in the
data. It might be a forecast nobody asked for or a total it added up wrong, and it reads exactly
as confident as the real figures around it. A judge model catches some of these. This checks
every number the same way every time and prints how it traced each one.

## Where it came from

I built it for a reporting connector over a multi-office dental group's practice data, where
owners act on the figures Claude gives them. The eval was 17 questions, demo prompts plus
adversarial ones (forecasts, offices with no data, false premises), each run three times for 51
answers. An answer passed only if every number traced back to the data and a model judge found
no unsupported claim.

The first run passed 15 of 51. Among other things, every pass at a forecast question invented
figures for a month that hadn't happened yet. After three rounds of fixes to the server's
instructions and tool outputs, 45 of 51 passed, and the third run had no number that couldn't be
traced to the data. The six remaining failures were reasoning slips around correct numbers
("only one provider more than doubled" when two did), which is a judge's job.

All the data in this repo is synthetic: Office A, Provider B, made-up dollars.

## How a number is checked

Each number in the answer is read with the precision it's displayed at. `$2.35M` must round from
something between 2,345,000 and 2,355,000, and `$48.2k` from something between 48,149 and 48,251.
Then it's classified:

| Status | Meaning |
|---|---|
| GROUNDED | Rounds to a value in the tool results, or is a fraction from the results shown as a percent (0.7425 as 74.3%). |
| DERIVED | One arithmetic step from source numbers: a sum, a difference, a ratio as a percent, or a percent change. The formula is printed so a person can check it. |
| UNGROUNDED | Neither. One of these fails the answer. |

Dates, years, times and list numbering aren't claims and are skipped. So is any number that
appears in the user's own question, since echoing the question isn't a hallucination.

Derivations are only searched over summary-level numbers (summaries, top-level fields, row lists
of 60 or fewer). Pairwise sums over thousands of row values would match almost any figure and
make the check meaningless. Inside a single row it also tries sums and differences of two money
fields, since values with cents make a match specific. It doesn't try percent ratios inside rows.
I tried that, and a few hundred rows produced about 100,000 candidate percentages, enough to
explain any figure to one decimal place.

## Run it

```
python example/demo.py
python -m pytest -q
```

The demo grounds two answers against the same synthetic tool results (`example/tool_results.json`,
shaped by the tables in `example/schema.sql`). The faithful one passes. The invented one fails:

```
== answer_invented.txt: 6 numbers, FAIL (3 UNGROUNDED)
  DERIVED    $49k             9,105.66 + 39,874.62
  DERIVED    27%              a/b with a=0.8, b=3
  UNGROUNDED 37               not in the data and not one step from it
  UNGROUNDED $57,900          not in the data and not one step from it
  UNGROUNDED $600k            not in the data and not one step from it
  GROUNDED   $36,109          source value 36,109.45
```

Look at the two DERIVED lines. `$49k` is an aging bucket plus another office's production
average, and `27%` divides two small unrelated values. Both are coincidences, and
the printed formula is what lets a person see that in a second. So every DERIVED line needs a
person to read it before the answer counts as checked.

To check one answer from the command line:

```
python -m number_grounding.check_answer answer.txt tool_results.json [--question question.txt]
```

The results file can be the tool results themselves or a whole conversation in Messages API
shape, in which case every `tool_result` block is read out of it. Exit code 0 means every number
traced, 1 means at least one didn't.

In your own eval harness:

```python
from number_grounding import ground, tool_results_from_messages, format_report

rep = ground(answer_text, tool_results_from_messages(messages), question=user_question)
if not rep.ok():
    print(format_report(rep))
```

## Limits

- One step only. A sum of five daily rows comes back UNGROUNDED even when it's right. In the
  original eval a judge model recomputed those from the data and they were listed for a person.
- It can't tell a right number from the wrong row. If the answer gives Office B's figure under
  Office A's name, the number still grounds.
- Numbers inside strings in the tool results count as seen (a label like `0-30` gives 0 and 30).
  Dates and clock times inside strings are skipped, so `2026-11-09` doesn't hand the checker
  2026, -11 and -9 to build derivations from. Small values can still combine by chance, as the
  demo shows.
- With no access to the exact tool results (a chat UI doesn't hand them over), you can ground
  against a broad set of report outputs instead. That's weaker, since a number can match a value
  from an unrelated report, but an invented number usually has nothing to match.

## License

MIT
