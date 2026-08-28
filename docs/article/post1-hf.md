# Confidence is theater: benchmarking nine local VLM pipelines on handwritten clinical forms

> Median self-reported confidence was 0.95 when the model was right — and 0.95 when it was wrong. Everything useful we learned came from making models disagree with each other, not from asking one how sure it felt.

**Scribe** is a local pipeline that turns scanned or photographed handwritten clinical forms — vitals charts, prescriptions, lab requests, visit notes — into schema-conformant structured records. Every field carries provenance back to a region of the page, and anything uncertain is routed to a human instead of into the record. It is built for offline-first health settings, where the documents are paper, the connectivity is unreliable, and the data cannot leave the machine: `scribe run` holds a process-wide socket guard that blocks any connection off loopback, so "local" is enforced rather than intended.

This is the benchmark log from getting there: nine configurations of pipeline and model architecture, run on the same 23 handwritten pages against the same hand-curated gold set, including the experiments that failed.

**One disclaimer before any numbers.** The corpus is public — pages from the [African Medical Records](https://huggingface.co/datasets/Nigeria-Health-data-OCR-pipeline/African-Medical-Records) dataset (CC-BY-4.0), pinned at revision `fa27d29`. Public data may overlap the training corpora of every model tested, and one of the models tested was released *after* this dataset was published. So nothing here is a performance claim. These numbers compare configurations against each other under identical conditions — they measure the *pipeline*, not the models' true reading ability. Sign-off numbers will come from a held-out set of homemade pages on real target forms, created after the models' training cutoffs, which never leaves the machine.

## The setup

- **Host:** MacBook Pro, Apple M5 Max, 128 GB unified memory, [MLX](https://github.com/ml-explore/mlx) via `mlx-vlm`, models served OpenAI-compatible with grammar-constrained JSON decoding.
- **Corpus:** 23 pages — 20 from the [AMR dataset](https://huggingface.co/datasets/Nigeria-Health-data-OCR-pipeline/African-Medical-Records) plus 3 synthetic pages built to carry specific traps.
- **Gold:** 221 hand-curated field values. 51 of them (23%) are legitimately **null** — absent, illegible, or non-numeric where a number is required. Those 51 are the point of the set: each must reach the review queue rather than acquire a plausible value.

The traps are the interesting part. Real forms from this setting write an adult's age as `"Ad"` in an integer field; give an infant's age in months; use four different date formats; identify a patient only by hospital number and bed; and hand the model a tick-box grid with **nothing ticked**. The gold answer for each is null-plus-flag. A model that guesses politely is worse than a model that abstains, because a guessed value in a clinical record looks exactly like a real one.

## The pipeline

![Scribe pipeline: ingest, locate, read, validate, verify, then review queue or structured record](https://huggingface.co/datasets/sohakanu/scribe-article-assets/resolve/main/pipeline.png)

Six stages. A grounding call localizes every field on the page at once; extraction is **routed** — tables, dates, enums, and checkbox groups are read from margin-padded crops, scalars and prose from the whole page (finding #4 explains why); a validator enforces schema and types; then a **verify pass** re-reads every auto-accepted field with a *different* model, and disagreement flags the field for a human. The bench below is the story of how each of those stages earned its place.

## The scoreboard

Nine configurations, same 23 pages, same 221-value gold set. Column meanings:

- **s/field** — mean wall-clock seconds per field, including verify where present.
- **exact** — fields exactly matching gold, flagged or not. How well the models *read*.
- **auto-acc** — accuracy of only the fields the pipeline accepted *without* flagging. How much you can trust what skips human review. This is the number a production deployment lives on.
- **flags** — fraction of fields sent to the review queue (budget: ≤30%).
- **FN flags** — wrong values that were *not* flagged: silent errors, the worst category.
- **halluc** — values invented for fields whose gold is null.
- **halluc esc.** — inventions that were *not* flagged, so they reach the record with no human look. The clinically meaningful one (finding 6).

| # | Config | Primary | Verifier | s/field | exact | auto-acc | flags | FN flags | halluc | halluc esc. |
|---|---|---|---|--:|--:|--:|--:|--:|--:|--:|
| v1 | whole-page | [Qwen3-VL-30B-A3B](https://huggingface.co/mlx-community/Qwen3-VL-30B-A3B-Instruct-8bit) | — | 9.8 | 75% | 75% | 10% | 25% | 20% | 20% |
| v1c | crop-all | Qwen3-VL-30B-A3B | — | **4.0** | 70% | 71% | 13% | 29% | 18% | 18% |
| v1r | routed | Qwen3-VL-30B-A3B | — | 6.4 | 76% | 79% | 14% | 21% | 12% | 12% |
| v2 | + tuned prompts, same-model verify | Qwen3-VL-30B-A3B | itself | 9.9 | 76% | 93% | 32% | 7% | 12% | 6% |
| v3 | cross-model verify | Qwen3-VL-30B-A3B | [Qwen3-VL-8B](https://huggingface.co/mlx-community/Qwen3-VL-8B-Instruct-8bit) | 10.0 | 76% | 95% | 34% | 5% | 12% | 2% |
| v4 | cross-family verify | Qwen3-VL-30B-A3B | [GLM-4.5V](https://huggingface.co/mlx-community/GLM-4.5V-4bit) | 11.9 | 76% | 94% | 38% | 6% | 12% | 4% |
| v5 | new primary — **shipping default** | [Qwen3.8-27B](https://huggingface.co/mlx-community/Qwen3.8-27B-8bit) | Qwen3-VL-8B | 17.3 | **81%** | 96% | **28%** | 4% | **8%** | **2%** |
| v7 | out-of-family verifier | Qwen3.8-27B | [Gemma 3 12B](https://huggingface.co/mlx-community/gemma-3-12b-it-8bit) | 19.8 | 81% | **97%** | 30% | **3%** | 8% | 4% |
| v8 | next-gen verifier | Qwen3.8-27B | [Gemma 4 12B](https://huggingface.co/mlx-community/gemma-4-12B-it-qat-OptiQ-4bit) | 20.0 | 81% | 96% | 29% | 4% | 8% | 2% |
| v9 | third-family primary | [Muse Glimmer 30B](https://huggingface.co/Shiftedx/Muse-Glimmer-30B-MXFP8-Vision-MLX) | Qwen3-VL-8B | 24.6 | 74% | 84% | 42% | 16% | **0%** | **0%** |

*(v4 and v8 changed only the verifier, so their reading-accuracy columns track their primary's row, as expected.)*

The trajectory that matters is **auto-acc**: 75% → 96%. Exact accuracy barely moved (75% → 81%). The models never learned to read much better — the pipeline learned to *know when they were wrong*.

## Finding 1 — confidence is theater; agreement is evidence

The original plan for the accept/flag gate was threshold tuning on the models' self-reported confidence. Offline analysis killed it in one table: the median composite confidence was **0.95 for correct values and 0.95 for wrong ones**. Handwritten proper names misread with total confidence (Amaka → Anaelly, Okafor → Okaro) sailed straight into the record. There was no threshold to tune.

What worked instead was disagreement. The verify pass re-reads every auto-accepted field from the complementary source (crop if the first read was whole-page, and vice versa). In v2 that one change took auto-accepted accuracy from 79% to 93% and cut silent errors from 21% to 7% — with the model's reading ability *unchanged*.

## Finding 2 — the second reader must be a different model

Same-model verification cannot catch a bias both reads share. Switching the verifier to a different model ([Qwen3-VL-8B](https://huggingface.co/mlx-community/Qwen3-VL-8B-Instruct-8bit), running alongside the primary in 128 GB) caught 52 disagreements and pushed auto-acc to 95%. The decorrelation was visible field by field: every confidently misread patient name was now caught before auto-acceptance (94% → 100%), and systematic medication-column-splitting differences surfaced as flags instead of passing silently. For a clinical pipeline, 79% → 95% trusted-output accuracy for ~1.6× latency is not a close call.

## Finding 3 — four model families all tick the empty checkbox

The most stubborn failure in the bench. Here is the trap, from one of our synthetic pages — a lab request form where nothing is ticked and the gold answer is null:

![An untouched checkbox row: Specimen type — Blood, Urine, Stool, CSF, all boxes empty](https://huggingface.co/datasets/sohakanu/scribe-article-assets/resolve/main/checkbox_trap_syn003.png)

Qwen3-VL-30B says "blood". Qwen3-VL-8B says "blood". GLM-4.5V says "blood" on the real forms. Gemma 3 read the empty box glyph as a tick. **Four model families, three generations, one shared conviction that somebody must have wanted a blood test.** Hallucination on this field stayed at 75% under every model pairing tried — cross-model verification can't catch a bias when both readers share it, and this one appears to be how current VLMs treat printed option rows as such. The fix is not a better prompt; it is explicit checkbox-state detection, which is now a scheduled pipeline stage rather than a hope.

A coda earned after this section was first drafted: a fifth family finally broke the pattern. Meta's [Muse Glimmer 30B](https://huggingface.co/Shiftedx/Muse-Glimmer-30B-MXFP8-Vision-MLX) (v9), tried as a primary, invented **nothing** — 0% hallucination, on this field and every other — while losing badly everywhere else (74% exact, 42% flags). The bias is not universal to VLMs after all; it is absent in Meta's perception-encoder lineage. Muse doesn't get the primary seat, but its abstention discipline makes it the obvious candidate to *power* the checkbox-detection stage.

This generalizes: **a verifier only buys you accuracy on failures the two models don't share.** Know which of your failure modes are idiosyncratic and which are universal.

## Finding 4 — crops fix hallucination, whole pages fix context; route by field type

Reading each field from a cropped region (one grounding call per page localizes everything at once) was 2.45× faster and fixed exactly what it was supposed to fix: `document_date` hallucination fell from 67% to 17% — the model could no longer helpfully borrow a date from the observation table — and table extraction accuracy doubled. But crops *hurt* header-labeled scalars and prose (hospital number 87% → 65%): mislocalize the box and the value is gone.

So: route. Tables, dates, enums, and checkbox groups from crops; scalars and free text from the whole page. Routed mode beat both pure modes on every quality metric at 1.5× whole-page speed, which is why it's the default.

## Finding 5 — the verifier seat saturated; the negative results say where the ceiling is

v4, v7, and v8 are three attempts to buy more accuracy with a better verifier — a different family (GLM-4.5V), a fully out-of-family lineage (Gemma 3), and a next-generation model (Gemma 4). All three landed within ~2 fields of the 8B verifier: statistical ties on 221 values. GLM even flagged 100% of medication rows — review burden without accuracy gain.

The conclusion is worth keeping precisely *because* the experiments "failed": with a competent primary and this gate design, **any competent verifier lands at 94–97% auto-accepted accuracy.** Further gains live in the primary model, the gold conventions, and checkbox detection — not in verifier shopping. The 8B stays: smallest, fastest, same topline.

(One genuine signal: Gemma 4 was the first model to pass the synthetic empty-checkbox trap. Noted, and waiting for held-out data.)

## Finding 6 — count the hallucinations that *escape*, not the ones that happen

Late in the bench we split hallucination into **invented** (the model produced a value for an empty field) and **escaped** (the invention wasn't flagged, so it would reach the record with no human look). Only the second one matters clinically, and the pipeline had been quietly winning it all along:

| Config | invented | escaped |
|---|--:|--:|
| v1r routed, no verify | 12% | 12% |
| v2 same-model verify | 12% | 6% |
| v3 cross-model verify | 12% | **2%** |
| v5 shipping default | 8% | **2%** |
| v7 Gemma 3 verifier | 8% | 4% |
| v8 Gemma 4 verifier | 8% | 2% |
| v9 Muse Glimmer primary | **0%** | **0%** |

Models keep inventing — the checkbox bias never went away — but from v3 onward the pipeline catches all but one or two inventions per run. If your eval only reports raw hallucination rate, you are grading the model. Report what escapes, and you're grading the system, which is the thing you actually ship.

## What no benchmark on public data can settle

Three things this bench cannot honestly answer, and how each gets answered:

1. **Contamination.** The corpus is public and the current primary ([Qwen3.8-27B](https://huggingface.co/mlx-community/Qwen3.8-27B-8bit)) was released *after* the corpus was. Its v3 → v5 improvement could be reading or could be recall. A canary-based contamination check runs before any accuracy is reported per model revision, and the held-out set — created after training cutoffs, never published — is the only source of sign-off numbers.
2. **The production targets.** ≥98% auto-accepted accuracy and ≤2% escaped hallucination, held-out only. Flow data sits at 96% and 2%; the remaining distance is concentrated in checkbox detection and one gold-convention question about how to split medication dose/frequency columns — a judgment call two humans would also disagree on.
3. **Generalization.** Every number above was measured against gold we curated ourselves, on a schema we tuned. The next post in this series takes the two best configurations and ambushes them with an external set nobody here tuned against — 100 handwritten prescription pages with the dataset author's own gold. The results surprised us in both directions.

Everything that public flow data can teach has been extracted. That felt like the right moment to write it down.

---

**This is part 1 of a series.** Part 2 — *One imperfect page per hundred*, the external evaluation on data nobody tuned against — follows soon. The benchmark gold set from this post is available at [sohakanu/scribe-flow-gold](https://huggingface.co/datasets/sohakanu/scribe-flow-gold).

*Scribe runs entirely on one machine; adding a new form type means writing a schema YAML, never editing code. The bench methodology — pinned model revisions, trap-carrying gold sets, invented-vs-escaped hallucination accounting — is documented alongside the pipeline. Corpus: [African Medical Records](https://huggingface.co/datasets/Nigeria-Health-data-OCR-pipeline/African-Medical-Records) (CC-BY-4.0). The checkbox illustration above is from one of our synthetic pages; every name on every sample page shown or discussed is fictional.*
