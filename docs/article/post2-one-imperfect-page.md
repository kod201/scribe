# One imperfect page per hundred: ambushing our pipeline with data nobody tuned

> Brand-name reading accuracy fell from ~80% to 38% the moment we left our own benchmark. The flag rate rose from 28% to 97%. Exactly one imperfect page in a hundred reached the record unreviewed. This post is about why we consider that a pass.

*Part 2 of a series. [Part 1](post1-confidence-is-theater.md) benchmarked nine configurations of **Scribe** — a fully local pipeline that turns handwritten clinical forms into structured records, flags what it can't trust, and lets nothing unreviewed into a record unless two models independently agree. It ended with a caveat: every number was measured against gold we curated ourselves, on a schema we tuned, on public data our models may have seen. This post removes as much of that as public data allows.*

## The ambush

We took the two best configurations from part 1 — the same primary ([Qwen3.8-27B](https://huggingface.co/mlx-community/Qwen3.8-27B-8bit)) with each of the two best verifiers — and ran them against [100 handwritten Indian prescriptions](https://huggingface.co/datasets/chaithanyakota/100-handwritten-medical-records) (CC-BY-ND-4.0), whose ground truth was curated by the dataset author, not by us. The task: extract the medicines list. Nothing was tuned: the schema was written once from the task description, the prompts were frozen from part 1, and the gold conventions were the author's, held apart from ours.

Two things make this set brutal. The handwriting is real doctors' cursive — not the legible volunteer writing of part 1's corpus — and the drug names are Indian brand names the models have little prior for. Which is exactly the point: a system built for clinics in one country will someday meet a register from another.

## The results

| | config A (Qwen-8B verifier) | config B (Gemma-3 verifier) |
|---|--:|--:|
| strict page-level exact | 1% | 1% |
| medicine token-match F1 | 0.27 | 0.27 |
| brand-name recall | 38% | 38% |
| page flag rate | **97%** | **99%** |

Both configurations read identically — same primary, so same extractions; the verifier only changes how much gets flagged. That is itself a finding, and it repeats part 1's: **verification cannot fix reading. It can only catch it.**

## Reading collapsed

Brand names came back right 38% of the time. `CEPODEM` became *Capelin*; `ESOTAB` became *Esotrib*; `NIVEOLI` became *Ulfah Niveoli*. These are the same confident-cursive-misread failures from part 1's patient names, at triple the rate, because the handwriting is harder and the vocabulary is foreign. No prompt we own fixes this; it is the frontier of what current local VLMs can read, and it matches what the [South African maternity-record benchmark](https://arxiv.org/abs/2604.16504) found on comparable material with frontier cloud models.

## The safety system did not

Here is what the pipeline did with input it could not read: the calibrated confidence (part 1, finding 1: "any ambiguous character → ≤0.7") dropped to 0.60–0.70 on nearly every page, and **97–99% of pages routed to the human review queue.** The system's answer to "extract this" was overwhelmingly "a person must look at this" — which, for this input, is the correct answer.

And the pages that skipped the human? We audited every one. Of the three auto-accepted pages in config A:

- Two were **fully correct** — including an 11-medicine page transcribed almost perfectly.
- One was correct on every medicine it listed but **dropped one item** (`BETNESOL INJ`).

One imperfect page escaped per hundred, under total distribution shift, on the hardest input this pipeline has ever seen. The part-1 thesis — *report what escapes, and you're grading the system* — is the reason we can say precisely that, rather than gesture at an accuracy number.

## What we changed because of this

- **A scoring lesson.** Our first pass at medicine-level scoring had a directional bug: extracted rows carrying dose schedules (`1-0-1`) were penalized as spurious even when they named the right drug. External evaluation debugs your evaluator too.
- **Expectation-setting for sign-off.** Our production target (≥98% auto-accepted accuracy) was measured at 96% on the friendly corpus and is unmeasurable on this hostile one — the true number for our actual target forms will land between, and only the held-out set of real register pages will say where.
- **Confidence in the gate, not the reader.** Every investment that generalized was in the *system* — calibration, dual-read verification, the review queue. Every investment that didn't was in squeezing the reader.

## What's next

The held-out evaluation: real target-form registers, hand-filled and photographed, never published, created after every model's training cutoff — the only data that can produce sign-off numbers. And one engineering item part 1 predicted and this post reinforces: explicit checkbox-state detection, likely powered by the one model family we found that refuses to invent.

---

*Corpus: [100-handwritten-medical-records](https://huggingface.co/datasets/chaithanyakota/100-handwritten-medical-records) (CC-BY-ND-4.0), evaluated as-is and not redistributed. Our own benchmark gold from part 1 is published at [sohakanu/scribe-flow-gold](https://huggingface.co/datasets/sohakanu/scribe-flow-gold). All extraction ran locally on one machine; no page left it.*
