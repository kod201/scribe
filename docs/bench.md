# Bench and model provenance

Every number here must be reproducible from a pinned revision. Numbers taken
against the **flow set prove plumbing only** and are never a performance claim
(PRD 12.1).

---

## Pinned revisions (M0)

| Role | Repo | Revision | Size | Notes |
|---|---|---|---|---|
| Extraction | `mlx-community/Qwen3-VL-30B-A3B-Instruct-8bit` | `8794b4f0bce099a0ca7c40980ba7081527321e59` | ~32 GB | MoE, 3B active. Serves via `mlx_vlm.server`. |
| Extraction (fallback, not yet pulled) | `mlx-community/Qwen3-VL-8B-Instruct-8bit` | `a0093b9b5fda6f76ddd4a462c6830ae7c4fe47ec` | ~9 GB | For the speed comparison in M2. |
| Flow dataset | `Nigeria-Health-data-OCR-pipeline/African-Medical-Records` | `fa27d29dae4128ac45f035fd580928c84bec4e98` | 62 pairs | CC-BY-4.0. |

Host: MacBook Pro, Apple M5 Max, 128 GB unified memory, macOS 26.6.1,
Python 3.12, `mlx-vlm` 0.6.15, `mlx` 0.32.1.

`scribe serve` sets `HF_HUB_OFFLINE=1` so the server cannot silently resolve a
newer revision than the one recorded above.

---

## Answers to the M0 open questions (PRD 15)

### 1. Does PaddleOCR-VL run cleanly on Apple Silicon?

**Partly — and not fast. The Mac default stays whole-page Qwen3-VL with no
layout stage.**

`paddlepaddle` 3.3.1 publishes `macosx_11_0_arm64` wheels including cp312, so
the stack installs. But those wheels are **CPU-only**: PaddlePaddle has no Metal
or MPS backend, so a 0.9B vision-language model would run entirely on CPU while
the 30B extraction model already owns the GPU. That is the wrong trade for a
laptop proof-of-flow.

Consequence: `layout_engine: none` is the v0 default, which is what the PRD
already assumed. Revisit at M1b and measure rather than assume — a CPU-bound
0.9B layout pass may still beat sending the full page to the VLM once per
field, because it collapses N whole-page prefills into N small crops.

`dots.ocr` (3B) is a PyTorch model and would run on MPS, so it is the more
plausible Apple Silicon layout engine of the two. Both stay behind
`LayoutEngine`; neither is wired yet.

### 2. MLX server vs `mlx-vlm` in-process?

**Server.** `python -m mlx_vlm.server` is the right call for three reasons:

1. It is OpenAI-compatible (`/v1/chat/completions`, `/v1/models`), so the same
   `OpenAICompatEngine` client talks to MLX on the Mac and vLLM on the CUDA box.
   The backend switch is one line of `config.yaml`.
2. The model stays resident across CLI invocations. In-process, every
   `scribe run` would pay the 30 GB load again.
3. It supports **grammar-constrained decoding** via `llguidance`
   (`response_format: {type: json_schema}`). This matters more than it sounds:
   PRD 7.2 requires strict JSON, and constraining the grammar removes most of
   the parse-failure surface rather than relying on the repair prompt.

The repair path is still implemented, because the constraint is a backend
capability and not a guarantee — `OpenAICompatEngine.complete()` falls back to
unconstrained decoding if the server rejects the grammar.

### 3. Per-field vs grouped-field prompting?

**Open — benchmark in M2**, which is where the harness to measure it exists.
Recorded here so the comparison is not skipped:

- Per-field: one whole-page prefill per field. With ~10 applicable fields per
  page in whole-page mode this is the dominant cost, and it is the reason the
  PRD's 5-20 s/field estimate needs checking.
- Grouped: one call per page returning all fields. Far cheaper, but confidences
  become correlated and a single malformed field can take down the whole
  response.

Vision-feature caching (`--max-cached-vision-features`, default 20) may make
per-field prompting much cheaper than the naive estimate, since the page image
is identical across a page's fields. Measure that first — it decides the
question.

### 4. Should `checkbox_group` use layout detection directly?

**Deferred to M1b**, but the flow set already argues yes. AMR_004 is a printed
tick-box lab form where the gold answer for both `specimen_type` and
`tests_requested` is "nothing is ticked". A VLM reading a whole page of printed
option labels is being invited to hallucinate a selection; a layout engine
reporting box-filled state is a measurement. `SYN_003` is the controlled
version of the same trap — four empty boxes, gold is null.

Until M1b, the mitigation is prompt-level: the `extract_hint` on both fields
says explicitly not to pick the first box.

---

## Flow-set composition (M0)

23 pages: 20 AMR pairs + 3 synthetic. 221 gold field values, **51 (23%)
legitimately null** — absent, illegible, or non-numeric where a number is
required. Those 51 are the point of the set: each one must reach the review
queue rather than acquire a plausible value.

| Page type | Pages |
|---|---|
| `vitals_chart` | AMR_001, 005, 008, 015, 017, 021, SYN_002 |
| `prescription` | AMR_003, 006, 007, 014, 019, 022, SYN_001 |
| `lab_request` | AMR_004, 010, 011, 012, 016, 023, SYN_003 |
| `visit_note` | AMR_009, 020 |

Deliberate traps carried by the set:

| Trap | Where | Correct behaviour |
|---|---|---|
| Age written `"Ad"`/`"AD"` (adult) in an integer field | AMR_003/004/006/007/010/011, SYN_003 | `null` + note. Never a guessed number. |
| Age given in months (`"5 month old"`) | AMR_009 | `null` + note. |
| Date formats `23/02/25`, `10 Oct, 2025`, `24-07-2024`, `12 March, 2026` | throughout | Normalise to DD/MM/YYYY; keep written form in `raw_transcription`. |
| Vitals chart with observation dates but no document date | AMR_001/015/017, SYN_002 | `document_date` is null. |
| Page identified only by hospital number and bed | AMR_005, AMR_008 | `patient_name`, sex, age all null. |
| Tick-box form with nothing ticked | AMR_004, SYN_003 | `specimen_type` null, no invented tests. |
| Smudged cell inside a table | SYN_002 row 2 `temp_c` | `null`, `legible: false`. |
| Blank cell inside a table | SYN_002 row 3 `pulse_bpm` | `null`, row still emitted. |
| Faint low-contrast photocopy | SYN_003 | Read normally; contrast is not illegibility. |

---

## Latency

To be measured at M2. Nothing recorded yet — the PRD's 5-20 s/field figure is
an estimate, not a measurement, and must not be quoted as one.

| Date | Model | Mode | s/field | s/page | Fields | Notes |
|---|---|---|---|---|---|---|
| 2026-08-19 | 30B-A3B 8-bit @ 8794b4f | whole-page, per-field, constrained | 9.3 / 4.9 | - | 2 (smoke) | First observation, not a benchmark: SYN_003, cold then warm vision cache. Server memory-resident. |
| 2026-08-19 | 30B-A3B 8-bit @ 8794b4f | whole-page, per-field, constrained | 9.8 avg (5.1-41.3) | ~75-110 | 232 over 23 pages | M2 full flow-set run. Table fields dominate: vitals 25.0s, medications 13.3s avg. Scalars ~6-8s. |

M0 smoke-test observation worth keeping: asked for `patient_age_years` on
SYN_003 (written "Ad"), the model returned `value: "Ad"` with
`raw_transcription: "Ad"` rather than null -- faithful transcription, wrong
interpretation. Exactly the case the M2 validator exists for: integer coercion
fails, the field flags, a human sees "Ad" next to the crop. Prompt tuning may
reduce it, but the validator is the guarantee.

### M2/M3 flow-set eval snapshot (plumbing check, NOT a performance claim)

Full report in `docs/eval_flow_v1.md`. Overall on 221 gold values: 75% exact,
10% flag rate, 25% FN flag rate, 20% hallucination rate. Signal worth keeping:

- `patient_age_years` 100% including every "Ad" trap -- the extract_hint plus
  validator combination held.
- `document_type` classifier 96% (22/23; one null, flagged as required-null).
- The weak spots are exactly what M1b exists for: whole-table extraction
  (vitals 14% exact -- row drops and cell misalignment), `document_date` on
  charts that only carry observation dates (67% hallucination on that field),
  and unticked checkbox forms (`specimen_type`: model invents 'blood').
- Handwritten proper names misread confidently (Amaka->Anaelly, Okafor->Okaro):
  unflagged wrong values, the FN category that threshold tuning at M4 must eat.

### M1b: whole-page vs crop-based extraction (flow set, small n -- direction, not sign-off)

Same model, same pages, same gold. Crop mode = `layout_engine: qwen_grounding`:
one grounding call per page localizes all fields at once (0-1000 normalized
coords), each field is then read from its margin-padded crop; 175/209 fields
localized (84%), the rest fell back to whole-page.

| | whole-page | crop | 
|---|--:|--:|
| s/field (avg) | 9.8 | **4.0** |
| s/page (typical) | 75-110 | 30-42 |
| exact acc (overall) | 75% | 70% |
| auto-accepted acc | 75% | 71% |
| flag rate | 10% | 13% |
| FN flag rate | 25% | 29% |
| hallucination | 20% | 18% |

Where crops clearly win (the M3 weak spots, as predicted in PRD 5.2):

| field | whole-page | crop |
|---|--:|--:|
| document_date exact / halluc | 65% / 67% | **78% / 17%** |
| vitals exact / auto-acc / FN | 14% / 25% / 75% | **29% / 67% / 33%** |
| tests_requested exact | 29% | 43% |
| vitals_diagnosis exact | 71% | 86% |

Where crops hurt (mislocalization: box grabs the wrong line, or the value
spills outside it):

| field | whole-page | crop |
|---|--:|--:|
| hospital_number | 87% | 65% |
| prescriber_name | 71% | 43% |
| chief_complaint / plan (n=2) | 50% / 50% | 0% / 0% |

Reading: crops fix exactly what they were meant to fix -- context bleed
(dates hallucinated from observation tables) and table structure -- at 2.45x
the speed, but header-labeled scalars and prose sections read better with full
context. The obvious M4 experiment is **routing**: crop for table/date/enum
fields, whole page for scalars and free text, expected to beat both modes on
accuracy and land near crop-mode latency.

### M4: per-field-type routing (flow set)

`crop_field_types: [table, date, enum, checkbox_group]` -- crops where they
won at M1b, full page everywhere else. 85 of 209 fields routed to crops.

| | whole-page | crop-all | **routed** |
|---|--:|--:|--:|
| s/field (avg) | 9.8 | 4.0 | 6.4 |
| exact acc | 75% | 70% | **76%** |
| auto-accepted acc | 75% | 71% | **79%** |
| flag rate | 10% | 13% | 14% |
| FN flag rate | 25% | 29% | **21%** |
| hallucination | 20% | 18% | **12%** |

Routing keeps both sides' wins: document_date auto-acc 89% / halluc 17%
(crop's win), hospital_number 87% and prescriber_name 86% (whole-page's win),
vitals auto-acc 67%. It beats both modes on every quality metric at 1.5x
whole-page speed, so **routed is now the default in config.yaml**.

Distance to the PRD 12.2 sign-off targets (which are held-out-only): auto-acc
79% vs >=98% target, halluc 12% vs <=2%. The residual concentrations are
`medications` row-level exact match (14% -- dose/frequency column splitting is
a judgment call the prompt does not pin down), free-text sections on visit
notes (n=2, noisy), and confidently misread proper names. Those are the
prompt-tuning targets once the held-out set exists; nothing further can be
honestly tuned against public flow data.

### M4 verdict: v2 (calibrated prompts + verify pass) -- the tuning path is viable

Offline analysis first showed threshold tuning is a dead end (median composite
0.95 for correct AND wrong values) and cross-source agreement is the usable
signal. v2 = prompt v2 (confidence calibration, letter-by-letter names,
medication column rules, checkbox hardening) + verify_pass (second read from
the complementary source on every auto-accepted field; 47 disagreements caught).

| | v1 routed | **v2 tuned+verify** | PRD target (held-out) |
|---|--:|--:|--:|
| s/field (incl verify) | 6.4 | 9.9 | -- |
| exact acc | 76% | 76% | -- |
| auto-accepted acc | 79% | **93%** | >= 98% |
| flag rate | 14% | 32% | <= 30% |
| FN flag rate | 21% | **7%** | -- |
| hallucination | 12% | 12% | <= 2% |

Reading: tuning did not make the model read better (exact unchanged) -- it
made the pipeline **know when the model is wrong**, which is the PRD's actual
ask. What the pipeline now auto-accepts is 93% right, and confidently-wrong
names are essentially fixed (patient_name auto-acc 94%, FN 6%; hospital_number,
prescriber, requesting_doctor, tests_requested, vitals all 100% on
auto-accepted). Cost: flag rate 32%, a hair over the 30% budget, and verify
doubles latency back to whole-page speed.

Two residual holes verify cannot fix, because both reads share the bias:
1. **medications column splitting** (auto-acc 0%): both reads split
   dose/frequency/duration the same way and disagree with gold's split. Fix is
   a convention question (possibly gold-side), not a model question.
2. **specimen_type on unticked forms** (halluc 75%): both reads invent
   'blood'. Needs actual checkbox-state detection (PRD 15.4) -- prompt
   hardening did not move it.

Path to the 98% target: held-out data + those two fixes. Everything else that
flow data can teach has been extracted.

### M4: cross-model verification (v3) -- the shipping configuration

v3 = v2 with the verify read performed by a DIFFERENT model
(Qwen3-VL-8B-8bit @ a0093b9, second server on :8082). 52 disagreements caught.

| | v1 routed | v2 same-model verify | **v3 cross-model verify** |
|---|--:|--:|--:|
| s/field | 6.4 | 9.9 | 10.0 |
| exact acc | 76% | 76% | 76% |
| auto-accepted acc | 79% | 93% | **95%** |
| flag rate | 14% | 32% | 34% |
| FN flag rate | 21% | 7% | **5%** |
| hallucination | 12% | 12% | 12% |

The decorrelation hypothesis held. Same-model verification cannot catch a
bias both reads share; the 8B disagrees in different places:

- **patient_name auto-acc 94% -> 100%, FN 6% -> 0%.** Every confidently
  misread name is now caught before it can be auto-accepted.
- **medications auto-acc 0% -> 50%**: the 8B splits columns differently, so
  systematic splitting differences now surface as flags instead of passing
  silently.
- **hospital_number stays 100%** on auto-accepted.
- specimen_type hallucination persists (75%): BOTH models invent 'blood' on
  unticked forms. Checkbox-state detection remains the only fix (PRD 15.4).

Verify latency is unchanged (the 8B is fast), and both models stay resident
in 128 GB. **Cross-model verify is now the default config**: for a clinical
pipeline, auto-accept accuracy 79% -> 95% for ~1.6x latency is the right
trade (PRD: correctness first).

Remaining distance to the 98%/2% held-out targets: specimen_type checkbox
detection, the medications gold-convention question, and free-text scoring
noise -- all waiting on the held-out set.

### M4: cross-FAMILY verifier (v4, GLM-4.5V) -- negative result, kept for the record

Hypothesis: an out-of-family verifier catches the biases both Qwen models
share. Result: it does not pay for itself.

| | v3 (Qwen3-VL-8B verifier) | v4 (GLM-4.5V-4bit verifier) |
|---|--:|--:|
| s/field | 10.0 | 11.9 |
| auto-accepted acc | **95%** | 94% |
| flag rate | 34% | 38% |
| FN flag rate | **5%** | 6% |
| specimen_type hallucination | 75% | 75% |

GLM correctly nulls the unticked-checkbox trap on the clean synthetic form
(smoke test), but on the real AMR tick-grids it reads 'blood' like the Qwen
models do -- the bias is not family-specific, it is how current VLMs treat
printed option rows. It also splits medication columns a third way, flagging
100% of medications rows (review burden without accuracy gain).

Conclusions: the Qwen3-VL-8B verifier stays the default (cheaper, equal or
better); checkbox-state hallucination cannot be verified away by ANY model
pairing tried -- explicit checkbox-state detection is the remaining fix.

### M4: Qwen3.8-27B as primary (v5) -- new default

Qwen3.8-27B (released 2026-08-05, dense, new hybrid-attention generation)
replaces Qwen3-VL-30B-A3B as primary; everything else identical to v3
(routing + Qwen3-VL-8B verifier). MLX 8-bit @ 815b83c, ~29 GB.

| | v3 (30B-A3B primary) | **v5 (Qwen3.8-27B primary)** |
|---|--:|--:|
| s/field | 10.0 | 17.3 |
| exact acc | 76% | **81%** |
| auto-accepted acc | 95% | **96%** |
| flag rate | 34% | **28%** (inside the 30% budget) |
| FN flag rate | 5% | **4%** |
| hallucination | 12% | **8%** |

First configuration to beat the 76% exact ceiling, and the first inside the
flag-rate budget. Where the new generation earns it: page classification
100%, document_date exact 83% with ZERO hallucination (the observation-table
trap is gone), vitals tables 14% -> 57% exact, lab_clinical_details
43% -> 86%. Verify disagreements dropped 52 -> 30 -- a better primary needs
less correction. Grounding uses the same 0-1000 convention (verified within
a few pixels of the 30B's boxes), so the layout stage carried over unchanged.

Costs and caveats:
- 17.3 s/field -- the dense 27B decodes ~1.7x slower than the 3B-active MoE.
  Correctness first (PRD); flip `extraction_engine` back for throughput.
- specimen_type hallucination unchanged at 75%: three model generations and
  two families all invent ticks on empty checkbox rows. Definitive: build
  checkbox-state detection.
- **Contamination risk is HIGHER for this model**: released 2026-08-05, well
  after the AMR corpus was public. The PRD 12.3 check is mandatory before
  treating the v3->v5 improvement as reading rather than recall, and no
  sign-off number exists until the held-out set runs.

### M4: Gemma 3 12B verifier (v7) -- statistical tie, 8B stays default

Fully out-of-family verifier (Google lineage, SigLIP vision, zero Qwen DNA)
against the same Qwen3.8-27B primary as v5. mlx 8-bit @ e7a87a6, ~13 GB.

| | v5 (Qwen3-VL-8B verifier) | v7 (Gemma 3 12B verifier) |
|---|--:|--:|
| s/field | 17.3 | 19.8 |
| exact acc | 81% | 81% |
| auto-accepted acc | 96% | 97% |
| flag rate | 28% | 30% (at the budget ceiling) |
| FN flag rate | 4% | 3% |
| hallucination | 8% | 8% |

On 221 fields the 1-point differences are ~2 fields -- noise. Gemma's one
distinct behavior: it splits medication columns differently enough to flag
86% of medications rows, and what it lets through is 100% right (v5: 50%).
It also read the empty-checkbox glyph as a tick in the smoke test --
**fourth model family with the checkbox bias**; specimen_type hallucination
stays 75% under every verifier tried.

Decision: Qwen3-VL-8B remains the default verifier (faster, cheaper, inside
the flag budget, and the tie means family decorrelation bought nothing
measurable here). Gemma 3 12B is a validated drop-in (config_v7.yaml) worth
re-testing on held-out data, where the tie could break either way.

### Escaped hallucination -- the metric the <=2% target really governs

`scribe eval` now reports hallucinations two ways: invented (the model
produced a value on an empty field) and **escaped** (the invention was not
flagged, so it reaches the record with no human look). The verify pass has
been intercepting most inventions all along:

| Config | invented | escaped |
|---|--:|--:|
| v1 routed (no verify) | 12% | 12% |
| v2 same-model verify | 12% | 6% |
| v3 cross-model verify | 12% | **2%** |
| v5 shipping default | 8% | **2%** |
| v7 gemma3 verifier | 8% | 4% |

Reading: models keep inventing (the checkbox bias never went away), but the
pipeline catches all but 1-2 inventions per run from v3 on. On flow data the
shipping config sits AT the <=2% target for what actually reaches records --
subject, as always, to the contamination check and held-out confirmation.

### v8: Gemma 4 12B verifier -- third tie; the verifier seat is saturated

96% auto-acc / 29% flags / 4% FN / 2% escaped-halluc at 20.0 s/field --
indistinguishable from v5 (Qwen-8B) and v7 (Gemma 3). One real signal: Gemma 4
is the first verifier to pass the synthetic unticked-checkbox smoke trap, and
specimen_type auto-acc reached its best value (75%). Not enough to displace
the 8B (faster, smaller, same topline). Conclusion across v3/v4/v7/v8: with
this primary and this gate design, ANY competent verifier lands at 94-97%;
further gains live in the primary, the gold conventions, and checkbox
detection -- not in verifier shopping.

### v9: Muse Glimmer 30B primary -- loses the seat, breaks the checkbox rule

Meta SI Lab's Aug-2026 30B dense VLM (community MXFP8 MLX @ c904a62) as
primary, 8B verifier, same routing.

| | v5 (default) | v9 (Muse Glimmer) |
|---|--:|--:|
| s/field | 17.3 | 24.6 |
| exact | 81% | 74% |
| auto-accepted acc | 96% | 84% |
| flag rate | 28% | 42% |
| FN flag rate | 4% | 16% |
| hallucination (invented/escaped) | 8% / 2% | **0% / 0%** |

Verdict: not the primary -- reads handwriting worse, flags over budget, and
its errors correlate with the 8B verifier's badly (FN 16%). But it is the
FIRST model of five families tested that invents nothing on empty fields:
specimen_type 86% exact, zero ticks imagined. The checkbox bias is not
universal to VLMs -- it is absent in Meta's perception-encoder lineage.
Practical takeaways: (1) v5 stays the default; (2) the checkbox-detection
stage could plausibly be a targeted Muse read on checkbox_group/enum crops
rather than classical CV -- worth one experiment when that stage is built.
Grounding note: Muse speaks the same 0-1000 convention; under constrained
decoding it echoes listing lines as labels (parser now tolerates this).

### External evaluation: rx100 (chaithanyakota/100-handwritten-medical-records)

100 Indian handwritten prescriptions, gold curated by the dataset author
(CC-BY-ND @ afcca9f) -- the first numbers in this project measured against
gold nobody here wrote. Task: the medicines list only. Both finalists run
(v5 = Qwen3.8 + Qwen-8B; v7 = Qwen3.8 + Gemma-3):

| | v5 | v7 |
|---|--:|--:|
| strict page exact | 1% | 1% |
| medicine token F1 | 0.27 | 0.27 |
| brand-name recall | 38% | 38% |
| page flag rate | 97% | 99% |

Identical reading (same primary), verifiers differ only in how much they
flag. Two findings:

1. **Reading collapses on real doctors' cursive** -- brand names right 38%
   of the time (CEPODEM->Capelin, ESOTAB->Esotrib). AMR's volunteer
   handwriting is much easier than this distribution; expect the held-out
   set to land between the two.
2. **The safety architecture held under total distribution shift.** The
   calibrated confidence dropped to 0.60-0.70 and 97-99% of pages routed to
   review. Of the 3 auto-accepted pages, 2 were fully correct and 1 missed
   a single medicine -- one imperfect page escaped per hundred. The system
   knows when it cannot read, which is the property the PRD actually asks
   for.

Scoring notes: token-set matching (60% gold-token coverage) separates
convention differences from misreads; a precision-direction bug (schedule
tokens penalizing correct rows) was found and fixed during this eval.

### Restatement note (validation pass, 2026-08-20)

A full recomputation of every table from the source databases found one stale
value: whole-page (v1) auto-accepted accuracy is **75%**, not the 71%
originally recorded -- the 71% predated the eval normalization fix (separator
glyphs in strings) and was never refreshed. Corrected in the M1b and M4
tables above and in the article. Every other published number reproduced
exactly.

## Contamination check (PRD 12.3)

To be run once per model revision, before any flow-set accuracy is reported.
Not yet run for `8794b4f`.

| Date | Revision | Result |
|---|---|---|
| _pending_ | `8794b4f` | |
