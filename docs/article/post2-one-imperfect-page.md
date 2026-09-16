# One Imperfect Page per Hundred: I Ambushed My Pipeline with Data Nobody Tuned For

When I moved my pipeline off its own benchmark, brand-name reading accuracy fell from roughly 80% to **38%**.

The share of pages flagged for human review rose from 28% to **97%**.

And exactly **one imperfect page in a hundred** reached the record without a person looking at it.

This post is about why I count that as a pass.

## Where this started

In [part 1](https://dev.to/sohakanu/confidence-is-theater-benchmarking-nine-local-vlm-pipelines-on-handwritten-clinical-forms-38h6), I built Scribe — a local pipeline that turns handwritten clinical forms into structured data and, more importantly, learned when *not* to trust a model's answer. The headline was that model confidence carried no signal, and disagreement between two independent reads did.

But every number in part 1 had a quiet weakness.

I curated the gold answers. I wrote the extraction schema. I tuned the prompts against the same 23 pages I was scoring on. Even honestly done, that's a loop — the system and its examiner grew up together.

So I went looking for an exam nobody in the room had written.

## The ambush

I found a [public dataset of 100 handwritten Indian prescriptions](https://huggingface.co/datasets/chaithanyakota/100-handwritten-medical-records), where the ground truth — the list of medicines on each page — was written by the dataset's author, not by me.

The rules I set for myself:

* the extraction schema gets written once, from the task description, before seeing results
* the prompts stay frozen exactly as they were in part 1
* the author's answer conventions are the answer key, not mine

Two things make this set genuinely hostile. The handwriting is real doctors' cursive — not the careful volunteer writing my benchmark was built from. And the drug names are Indian brand names the models have little prior for.

Which is the point. A system built for clinics in one country will eventually meet a register from another.

## The reading collapsed

Brand names came back right 38% of the time.

*CEPODEM* became **Capelin**. *ESOTAB* became **Esotrib**. *NIVEOLI* became **Ulfah Niveoli**.

These are the same confident-cursive misreads that plagued patient names in part 1 — at triple the rate, because the handwriting is harder and the vocabulary is foreign.

I ran both of my best configurations, which differ only in which model does the second read. They produced **identical reading results**. Same primary model, same eyes; the verifier only changed how much got flagged.

That repeats part 1's central lesson in harsher light: **verification cannot fix reading. It can only catch it.**

No prompt I own fixes the reading either. This is roughly the frontier of what local vision models can do with hard cursive right now — a [recent benchmark on South African maternity records](https://arxiv.org/abs/2604.16504) found the same wall with frontier cloud models.

## But the system knew

Here's the part that mattered to me.

Faced with input it couldn't read, the pipeline didn't pretend. The calibrated confidence — the "if any character is ambiguous, say so" behavior from part 1 — dropped to 0.60–0.70 on almost every page. And **97–99% of pages routed to the human review queue.**

For this input, "a person must look at this" *is* the correct output.

## Auditing the escapes

Three pages out of a hundred skipped human review. I checked every one by hand.

* Two were **fully correct** — single-medicine prescriptions, read cleanly.
* One was an eleven-medicine page that got ten of them right — and **silently dropped one** (`BETNESOL INJ`).

One imperfect page per hundred, on the hardest input this system has ever seen, under total distribution shift.

Part 1 ended with a rule: *count what escapes, and you're grading the system.* This was the rule's first live test, and it's the only reason I can write a sentence as precise as the one above instead of waving at an accuracy number.

## The exam graded my grader too

One more thing the ambush caught — in my own tooling.

My first scoring pass penalized extracted rows for containing dose schedules like `(1-0-1)`, even when they named the right drug. The scorer's precision check compared token sets in the wrong direction. External data debugs your evaluator, not just your model.

## What I'm taking away

* **Reading skill doesn't travel; gate discipline does.** Every investment that held up under distribution shift was in the *system* — calibration, dual reads, the review queue. Everything invested in squeezing the reader stayed home.
* **My production target got context.** Part 1's benchmark sits at 96% trusted-output accuracy; this hostile set is unmeasurable against the 98% target. The real number for my actual target forms will land somewhere between the friendly bench and this ambush — and only the held-out set will say where.
* **A high flag rate is not failure.** 97% flags on unreadable input is the system telling the truth. The failure mode would have been 28% flags and a queue full of *Capelin*.

## What's next

The held-out evaluation: real target-form registers, hand-filled, photographed, never published, created after every model's training cutoff. That produces the only numbers I'll stand behind — and it's part 3 of this series.

And the checkbox problem from part 1 still needs its own detection stage, likely powered by the one model I found that refuses to invent.

<details>
<summary><strong>The numbers, for engineers</strong> (click to expand)</summary>

Both finalist configurations (same Qwen3.8-27B primary; Qwen3-VL-8B vs Gemma-3-12B verifier) against all 100 pages, scored on the medicines list:

| | Qwen-8B verifier | Gemma-3 verifier |
|---|--:|--:|
| Strict page-level exact | 1% | 1% |
| Medicine token-match F1 | 0.27 | 0.27 |
| Brand-name recall | 38% (136/359) | 38% |
| Page flag rate | 97% | 99% |

Token matching uses 60% gold-token coverage so word-order conventions don't count as misreads. Full scoring code: [`scripts/eval_rx100.py`](https://github.com/kod201/scribe/blob/main/scripts/eval_rx100.py).

Dataset: [100-handwritten-medical-records](https://huggingface.co/datasets/chaithanyakota/100-handwritten-medical-records) (CC-BY-ND-4.0), evaluated as-is and not redistributed.

</details>

---

**This is part 2 of a series.** Part 1: [*Confidence Is Theater: What I Learned Building Scribe*](https://dev.to/sohakanu/confidence-is-theater-benchmarking-nine-local-vlm-pipelines-on-handwritten-clinical-forms-38h6).

Code and methodology: [github.com/kod201/scribe](https://github.com/kod201/scribe) · My own benchmark gold set: [sohakanu/scribe-flow-gold](https://huggingface.co/datasets/sohakanu/scribe-flow-gold)

*All extraction ran locally on one machine; no page left it.*
