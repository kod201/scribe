---
license: cc-by-4.0
language:
  - en
task_categories:
  - image-to-text
  - image-text-to-text
tags:
  - handwriting-recognition
  - ocr
  - htr
  - clinical
  - healthcare
  - medical-records
  - structured-extraction
  - evaluation
  - benchmark
pretty_name: Scribe Flow Gold
size_categories:
  - n<1K
configs:
  - config_name: gold
    data_files: gold.csv
    default: true
  - config_name: pages
    data_files: pages.csv
---

# Scribe Flow Gold

A small, hand-curated evaluation set for **handwriting-to-structured-data extraction on clinical forms**: 23 handwritten pages (vitals charts, prescriptions, lab requests, visit notes), 221 gold field values, and the extraction schema that defines them.

This is the gold set behind the Scribe bench — nine pipeline configurations evaluated on these exact pages. Its distinguishing feature is that **51 of the 221 values (23%) are legitimately null**: absent, illegible, or non-numeric where a number is required. Most extraction benchmarks measure whether a model can read what is there. This one also measures whether it can *refrain from inventing what is not* — which, for clinical records, is the property that matters most. A guessed value in a medical record looks exactly like a real one.

## The traps

The set deliberately carries the failure modes that real forms from this setting produce:

| Trap | Where | Correct behaviour |
|---|---|---|
| Age written `"Ad"`/`"AD"` (adult) in an integer field | AMR_003/004/006/007/010/011, SYN_003 | null + note — never a guessed number |
| Age given in months (`"5 month old"`) | AMR_009 | null + note |
| Date formats `23/02/25`, `10 Oct, 2025`, `24-07-2024`, `12 March, 2026` | throughout | normalise to DD/MM/YYYY |
| Vitals chart with observation dates but no document date | AMR_001/015/017, SYN_002 | `document_date` is null (context-bleed trap) |
| Page identified only by hospital number and bed | AMR_005, AMR_008 | name, sex, age all null |
| Tick-box form with **nothing ticked** | AMR_004, SYN_003 | null — no invented specimen or tests |
| Smudged cell inside a table | SYN_002 row 2 `temp_c` | null, marked illegible |
| Blank cell inside a table | SYN_002 row 3 `pulse_bpm` | null, row still emitted |
| Faint low-contrast photocopy | SYN_003 | read normally — contrast is not illegibility |

In the Scribe bench, the unticked checkbox row proved the most stubborn trap in the set: four model families across three generations all invented a selection ("blood") for the empty `specimen_type` row, under every prompt and verifier pairing tried.

## Contents

| File | What it is |
|---|---|
| `gold.csv` | 221 gold field values — one row per (page, field) |
| `pages.csv` | the 23 pages: image path, page type, source, contributor |
| `images/` | the 23 page images (PNG) |
| `amr_flow_v1.yaml` | the extraction schema: field types, null rules, per-field extraction hints |

### `gold.csv` columns

- `pair_id` — page identifier (`AMR_*` = corpus page, `SYN_*` = synthetic page)
- `page_no` — page number within the pair (always 1 here)
- `field_name` — field from the schema (`patient_name`, `document_date`, `vitals`, …)
- `page_type` — `vitals_chart` / `prescription` / `lab_request` / `visit_note`
- `is_null` — `true` for the 51 values whose correct answer is null
- `gold_json` — the gold value as JSON: string, number, `null`, or structured (arrays of rows for tables such as `vitals` and `medications`)

### Composition

| Page type | Pages |
|---|---|
| vitals_chart | 7 |
| prescription | 7 |
| lab_request | 7 |
| visit_note | 2 |

## Loading

```python
from datasets import load_dataset

gold = load_dataset("sohakanu/scribe-flow-gold", "gold")["train"]
pages = load_dataset("sohakanu/scribe-flow-gold", "pages")["train"]
```

Images are plain PNGs under `images/`, keyed by `pages.csv:file_name`.

## Scoring, as used in the Scribe bench

Beyond exact match, the bench scores each configuration on how it *handles* uncertainty, using this set's nulls:

- **auto-accepted accuracy** — accuracy of only the values the pipeline accepted without flagging for human review
- **false-negative flag rate** — wrong values that were *not* flagged (silent errors)
- **invented vs escaped hallucination** — a value produced for a null field, vs. such a value that additionally went unflagged and would reach the record

Any of these can be computed from `is_null` plus a system's (value, flagged) output pairs.

## Provenance and license

- The 20 `AMR_*` pages and their base transcriptions come from the [African Medical Records](https://huggingface.co/datasets/Nigeria-Health-data-OCR-pipeline/African-Medical-Records) dataset (CC-BY-4.0), pinned at revision `fa27d29`. Page contributors are credited per page in `pages.csv` (Amal Pantami, Arnold Kaura, Chukwufumnaya Alekwe, Fatukasi Sarah, and Isaac Peace, as recorded upstream).
- The 3 `SYN_*` pages are original synthetic pages created for this set to carry controlled versions of the traps. All patient and clinician names on every page are fictional.
- The 221-value gold annotation, the null/flag conventions, and the schema are original work, released CC-BY-4.0.

**Contamination note:** the AMR pages are public and may appear in VLM training corpora. Results on this set are suitable for comparing configurations under identical conditions, not for absolute performance claims. The Scribe project's sign-off numbers come from a private held-out set for exactly this reason; treat this set the same way.

## Known convention questions

One field is a known judgment call rather than a clean gold: `medications` row splitting (what goes in dose vs. frequency vs. duration when the handwriting runs them together). Three model families each split these columns a different way, and reasonable human annotators can too. If your system disagrees with gold only on column boundaries there, you are measuring a convention, not a reading error.
