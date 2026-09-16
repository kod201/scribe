# Confidence Is Theater: What I Learned Building Scribe

I'm building Scribe, a local pipeline that turns handwritten clinical forms into structured data.

The obvious problem is reading the handwriting.

The harder problem turned out to be this:

**How do you know when the model is wrong?**

My first idea was simple: ask the model how confident it was.

That failed almost immediately.

Median confidence when the answer was correct: **0.95**.
Median confidence when the answer was wrong: **0.95**.

So confidence wasn't giving me a useful signal.

That sent the project in a different direction: instead of asking a model whether I should trust it, I started comparing two independent reads of each field and treating disagreement as the signal to send it to a person.

This is the engineering log of what happened next.

## What Scribe does

Scribe takes scanned or photographed handwritten clinical forms and converts them into structured records.

The pipeline runs entirely on one machine. That matters for environments where connectivity is unreliable or the data should not leave the device.

Each extracted value keeps a link back to where it came from on the page. If the system is not comfortable with a value, it sends that field for human review instead of quietly writing it into the record.

The basic flow is:

**page → find fields → read → validate → second read → human review if needed → structured record**

There are more technical names for those stages, but that is really what the system is doing.

## A quick note about the numbers

I tested nine pipeline configurations on the same 23 handwritten pages and the same 221 hand-curated field values.

The dataset used for this development bench is [public](https://huggingface.co/datasets/Nigeria-Health-data-OCR-pipeline/African-Medical-Records), which means some models may have seen similar material during training.

So I'm treating these numbers as engineering comparisons between configurations, not as claims about the absolute performance of the models.

Production sign-off will use a private held-out set created after model training cutoffs.

## 1. Whole page or crop?

One of the first questions was whether the model should read the whole page or just the area containing the field.

Both approaches had problems.

Reading the whole page preserved context. Names, IDs and header-labeled fields were easier to interpret.

But the extra context also created hallucinations. A model looking for a document date could "borrow" another date from a nearby table.

Reading only a crop fixed some of that. For example, document-date hallucination dropped from 67% to 17%.

But crops sometimes removed too much context. Hospital-number accuracy, for example, dropped from 87% to 65%.

So I stopped trying to choose one.

Scribe now routes by field type:

* tables, dates, enums and checkbox groups → crop
* scalars and free text → whole page

That hybrid approach beat both pure modes on the combined quality measures and became the default.

## 2. Confidence didn't work

The next problem was deciding which extracted values could safely skip human review. I initially planned to use the model's own confidence score for this, but as the opening numbers showed, confidence did not separate correct answers from mistakes on this test: even badly misread handwritten names came back at 0.95, and there was no threshold worth tuning. So instead of asking the model how sure it was, I tried reading each field a second time and flagging the ones where the two reads disagreed.

## 3. A second read helped much more than confidence

The first verification approach simply re-read every field that would otherwise have been accepted automatically.

The second read used the complementary source:

* first read from crop → verify from whole page
* first read from whole page → verify from crop

If the two reads disagreed, the field went to human review.

That one change moved the accuracy of automatically accepted fields from 79% to 93%, while silent errors dropped from 21% to 7%.

The underlying model had not suddenly become a better reader.

The pipeline had become better at recognizing when it should not trust the answer.

That became the main design principle of Scribe.

## 4. Then I tried a different model for the second read

There was still an obvious problem.

If the same model has the same bias twice, two reads can agree on the same wrong answer.

So I switched the verifier to a smaller, different model.

That moved auto-accepted accuracy again, from 93% to 95%.

More importantly, confidently misread patient names were now caught before they passed through automatically.

The smaller model was not necessarily a better reader.

Sometimes it was useful precisely because it was wrong in a different way.

That was enough to surface disagreements.

## 5. Some mistakes were shared by nearly everyone

The most stubborn example involved checkboxes.

One synthetic form contained a lab-request section where nothing was checked. The correct answer was null.

![An untouched checkbox row: Specimen type — Blood, Urine, Stool, CSF, all boxes empty](https://huggingface.co/datasets/sohakanu/scribe-article-assets/resolve/main/checkbox_trap_syn003.png)

Several model families still confidently chose an option.

Qwen selected `"blood"`. GLM showed the same kind of behavior. Gemma interpreted an empty box as a tick.

Cross-model verification did not help much because both readers could share the same bias.

That changed the engineering plan. Checkboxes stopped being treated as "just another prompt." They became their own detection problem.

Later, Muse Glimmer produced an interesting counterexample: it hallucinated nothing in that run, but performed much worse overall. That makes it potentially useful as a specialist rather than as the main reader.

That was a useful reminder:

**A second model only helps when the models fail differently.**

## 6. Changing the verifier eventually stopped helping

After the initial gains, I tested several different verifier families.

GLM-4.5V. Gemma 3. Gemma 4.

They all ended up within roughly two fields of the small Qwen verifier on this 221-value set.

GLM was actually worse operationally because it sent far more fields to review without improving the overall result much.

That told me something useful. The next improvement probably wasn't hiding in yet another verifier.

The remaining gains were more likely to come from:

* a better primary model
* explicit checkbox detection
* resolving a few annotation conventions

So I stopped testing new verifiers.

## 7. The metric I care about changed too

At first I tracked hallucination as one number: did the model invent a value where the correct answer was empty?

Later I split that into two questions:

1. Did the model invent something?
2. Did that invention escape all the safety checks?

The second one matters much more to the final system.

For the routed pipeline without verification, 12% of null fields were invented and 12% escaped.

With cross-model verification, the model still invented values, but only 2% escaped.

That distinction changed how I think about evaluation.

If you only measure raw hallucination, you are grading the model.

If you measure what survives validation, verification and review, you are grading the system.

And the system is what actually goes into production.

## Where the bench ended up

Across the nine configurations, raw exact accuracy only moved from roughly 75% to 81%.

But the accuracy of fields allowed to bypass human review reached 96% in the current default configuration.

That is the result I find most interesting.

The project did not succeed because I found a model that suddenly became perfect at handwriting.

It improved because the surrounding pipeline got better at recognizing when the model should not be trusted.

## What still needs to be tested

There are still three important open questions.

**Contamination.** The development corpus is public, so the next evaluation needs data the models could not have seen.

**Production targets.** The target is at least 98% accuracy on automatically accepted fields and no more than 2% escaped hallucination, measured only on the private held-out set.

**Generalization.** This one already has a first answer: in [part 2 of this series](https://dev.to/sohakanu/one-imperfect-page-per-hundred-ambushing-our-pipeline-with-data-nobody-tuned-fh8), I ran the two best configurations against 100 independently labeled handwritten prescription pages I had no hand in. Reading accuracy dropped sharply; the review system held.

So the next useful number should come from genuinely unseen data, not from squeezing another decimal point out of this development set.

## What I'm taking away from it

A few things changed my thinking while building Scribe:

* model confidence was not useful for deciding whether an answer was safe
* disagreement between independent reads was much more useful
* crops and whole-page context solve different problems
* changing models does not fix every failure mode
* some problems need deterministic engineering rather than another prompt
* the most important hallucinations are the ones that escape the system

Scribe now runs locally, and new form types are defined through schema YAML rather than custom extraction code. The evaluation setup also keeps model revisions, provenance and review decisions tied to each result.

I'm still testing it.

But the central lesson so far is simple:

**The goal is not to build a model that never makes mistakes. It is to build a system that knows when a model's answer needs another look.**

<details>
<summary><strong>The full scoreboard, for engineers</strong> (click to expand)</summary>

All nine configurations, same 23 pages, same 221-value gold set. *Trusted-output acc* = accuracy of fields accepted without human review. *Escaped* = invented values that passed every check.

| Config | Primary | Verifier | s/field | Exact | Trusted-output acc | Flags | Escaped |
|---|---|---|--:|--:|--:|--:|--:|
| whole-page | Qwen3-VL-30B-A3B | — | 9.8 | 75% | 75% | 10% | 20% |
| crop-all | Qwen3-VL-30B-A3B | — | 4.0 | 70% | 71% | 13% | 18% |
| routed | Qwen3-VL-30B-A3B | — | 6.4 | 76% | 79% | 14% | 12% |
| + same-model verify | Qwen3-VL-30B-A3B | itself | 9.9 | 76% | 93% | 32% | 6% |
| + cross-model verify | Qwen3-VL-30B-A3B | Qwen3-VL-8B | 10.0 | 76% | 95% | 34% | 2% |
| GLM verifier | Qwen3-VL-30B-A3B | GLM-4.5V | 11.9 | 76% | 94% | 38% | 4% |
| **new primary (shipping)** | **Qwen3.8-27B** | **Qwen3-VL-8B** | **17.3** | **81%** | **96%** | **28%** | **2%** |
| Gemma 3 verifier | Qwen3.8-27B | Gemma-3-12B | 19.8 | 81% | 97% | 30% | 4% |
| Gemma 4 verifier | Qwen3.8-27B | Gemma-4-12B | 20.0 | 81% | 96% | 29% | 2% |

A tenth run (Muse Glimmer 30B as primary) read worse across the board (74% exact, 42% flags) but invented nothing: 0% hallucination.

The pipeline in one picture:

![Scribe pipeline: locate fields, read each from crop or page by type, validate, second-model check, then human review or record](https://huggingface.co/datasets/sohakanu/scribe-article-assets/resolve/main/pipeline.png)

Hardware, pinned model revisions, per-field tables, metric definitions and one documented restatement: [`docs/bench.md`](https://github.com/kod201/scribe/blob/main/docs/bench.md).

</details>

---

**This is part 1 of a series.** Part 2: [*One imperfect page per hundred*](https://dev.to/sohakanu/one-imperfect-page-per-hundred-ambushing-our-pipeline-with-data-nobody-tuned-fh8) — testing Scribe on an external prescription dataset.

Code and methodology: [github.com/kod201/scribe](https://github.com/kod201/scribe) · Benchmark gold set: [sohakanu/scribe-flow-gold](https://huggingface.co/datasets/sohakanu/scribe-flow-gold)

*Every name on every sample page shown or discussed is fictional. All extraction ran locally on one machine; no page left it.*
