# Held-out evaluation: decision rules

Committed before the run, so the rules can't be fitted to the result. Written on
2026-10-18, after the tuning work in
[part 3](https://dev.to/sohakanu/one-packet-to-tune-two-to-check-tuning-scribe-without-fooling-myself-51m5)
and before any held-out packet has been processed.

This file covers the held-out evaluation of the 14-page questionnaire pipeline
from part 3: what runs, on what, how it is scored, and what counts as a pass. The
first two targets in section 5 are the ones part 1 set; the third caps how much
goes to review.

## 1. What runs

The configuration called "current" in part 3 (the last row of its results
table), unchanged. Its files are not in this repository. Their hashes are fixed
here, so a changed file would no longer match them.

| Item | Identifier |
|---|---|
| Pipeline code | commit `82619b27d23885162f13f627774c45c84430c42d` (not in this repository); a later commit may be used only if nothing under `src/` or `schemas/`, and not the configuration file, has changed since |
| Configuration file | SHA-256 `428c14504e5aab9b9cc124d2410b4c125c069d049e490f56e189a81b9bd7ef02` |
| Schema file | SHA-256 `4794b1566fad8d82842aed8ac75e3febfb7524375428c55abbe4629193fd3b92` |
| Reading-skills file | SHA-256 `6aa9452933dfda5eb9503edf64ca4a65151684d9189bfddda2b0e21809dffea1` |
| Main model | `mlx-community/Qwen3.8-27B-8bit` at revision `815b83c0df8ffd1d1b5244cf75fd6ef14fca9ef9` |
| Second model | `mlx-community/Qwen3-VL-8B-Instruct-8bit` at revision `a0093b9b5fda6f76ddd4a462c6830ae7c4fe47ec` |
| Serving | mlx-vlm 0.6.15, mlx 0.32.1, prefix caching as set in the configuration file |

Only input and output paths may differ from the configuration file. The run's
copy, and its diff against the hashed file, are kept with the run.

## 2. What it runs on

- At least 4 complete packets (56 pages, 708 answers), in at least 3 different
  hands (judged from the handwriting). A complete packet is all 14 pages, one
  image each, in packet order, because page position decides page type.
- None of them used in parts 1-3: not for the schema, the hints, the reading
  skills or the answer-key conventions, and not looked at while tuning.
- No packet is chosen, or left out, because of the kinds of marks it contains.
- The only reason to exclude a packet is a missing or duplicated page; nothing
  is excluded for image quality or handwriting. Exclusions happen before the
  image list below is committed, and each is reported with its reason.
- Before the first page is processed, I commit here the SHA-256 of a list of
  every evaluation image's file name and SHA-256 (`shasum -a 256` output, sorted
  by file name). The list is kept with the run. That fixes both the set and the
  page order.

## 3. The answer key

- Built without access to Scribe's output for these packets. If a machine draft
  is used, it comes from models other than the two in section 1. Two people,
  one of them me, review every value against the page; I settle the
  disagreements before the run and report how many there were.
- Finished, and its SHA-256 committed here, before the run.
- Scored with `values_match` from the pinned commit (exact match after ignoring
  case, spacing and separator punctuation), with an empty tick list counted as
  blank, as in part 3.
- Every answer in the key is scored. An answer with no output counts as wrong
  and as sent to review, and the number of such answers is reported.
- The score against this frozen key is the result. If key errors turn up
  afterwards, I report how many there were and a corrected score next to it,
  never in place of it.

## 4. The run

- One run of the frozen configuration over the whole set. Both models run at
  temperature 0 (set in the configuration file), but batching can still make
  repeat runs differ slightly (part 3), so this run is one draw and it is the
  result. Any later repeat run is reported as secondary and never replaces it.
- A crash or server failure is resumed from where it stopped, never started
  over. Answers that already have an output are not run again, so each answer
  has exactly one output. Every restart is reported.

## 5. What counts as a pass

Primary measures, all from that one run:

| Measure | Target |
|---|---|
| Accuracy of answers accepted without review | ≥ 98% |
| Invented answers that escape review: blank-key answers that got a value marked legible and were not sent to review, as a share of all blank-key answers | ≤ 2% |
| Share of answers sent to review | ≤ 30% |

These are the scorer's definitions, as used in parts 1 and 3.

- **Pass:** all three meet their targets, checked on the counts, not on rounded
  percentages.
- Each measure is reported with its counts and an exact (Clopper-Pearson)
  two-sided 95% interval. If the interval for accepted accuracy reaches below
  98%, the result is reported as "pass, not confirmed at this sample size"; at
  about 550 accepted answers, that means more than 4 wrong. The interval treats
  answers as independent. They aren't (errors cluster by page and writer), so it
  is narrower than it should be.
- **Fail:** any target missed. Reported as a fail, with the breakdown below.

Reported either way, not used for the decision: exact accuracy over all answers;
the count of wrong answers of any kind that escaped review; results by packet
and by page number; minutes per packet.

## 6. After the run

- Nothing learned from these packets counts toward this evaluation. A change made
  because of them would need a new held-out set to be tested.
- A configuration changed after a fail does not get a second try on this set.
- A comparison with another configuration on these packets is reported as
  secondary, with all four answer-by-answer counts (right in both, wrong in
  both, fixed, broken) and an exact McNemar test. Only comparisons named and
  frozen here before the run count as planned; any other is labelled
  exploratory.
- I publish the results whatever they are, with this file's commit hash, the
  counts behind every percentage, and the number of key corrections. No answer
  values from these packets are published.

## Amendments

Changes are allowed until the first evaluation page is processed. Each one is a
dated commit to this file, listed here. After that, the file doesn't change.

- 2026-10-18: first version.
