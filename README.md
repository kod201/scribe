# Scribe

Local handwriting-to-structured-data pipeline. Scanned or photographed clinical
forms in, schema-conformant JSON out, with every field carrying provenance and
anything uncertain routed to a human.

**No document image or extracted value leaves the machine.** `scribe run` holds
a process-wide socket guard that blocks any connection off loopback, so this is
enforced rather than intended.

## Status

Pipeline complete and benchmarked end to end: ingest, VLM-grounding layout,
routed crop/whole-page extraction, validation, cross-model verify pass,
human review workbench, CSV/JSONL export (REDCap adapter prepped). Nine
model/pipeline configurations benchmarked plus an external-dataset check —
see `docs/bench.md` for methodology and every number, and
`docs/article/` for the write-up series. Benchmark gold set:
[sohakanu/scribe-flow-gold](https://huggingface.co/datasets/sohakanu/scribe-flow-gold).

Shipping configuration: Qwen3.8-27B primary + Qwen3-VL-8B verifier, routed
extraction — 96% auto-accepted accuracy / 2% escaped hallucination on the
flow benchmark (public data; held-out sign-off pending).

## Setup

```bash
uv sync --extra mlx
uv run python scripts/pull_model.py     # ~32 GB, once
```

## Running

```bash
uv run scribe serve                     # terminal 1: model server, blocks
uv run scribe status                    # terminal 2: engine health
```

Once M1–M3 land:

```bash
uv run scribe ingest ./samples/flow/images
uv run scribe run
uv run scribe review
uv run scribe export --format csv
uv run scribe eval --gold samples/flow/gold.csv --set flow
```

## Sample sets

`samples/flow/` — 20 pairs from the [African Medical Records][amr] corpus
(CC-BY-4.0) plus 3 synthetic pages. Proves the pipeline works. **Never a
performance claim**: the data is public and may overlap model training.

`samples/heldout/` — gitignored, and stays that way. Homemade pages on real
target forms, created after the model's training cutoff. All sign-off metrics
come from here.

Rebuild the flow set:

```bash
uv run python scripts/pull_amr.py --limit 20    # needs network
uv run python scripts/make_synthetic.py         # no network
uv run python scripts/make_gold.py
```

## Layout

```
src/scribe/
  config.py      typed view over config.yaml
  db.py          SQLite provenance schema
  schema.py      YAML form schemas -> typed field definitions
  net.py         offline assertion + socket guard
  cli.py         command line
  engines/       LayoutEngine and ExtractionEngine, and their backends
  stages/        ingest, layout, extract, validate, export  (M1-M3)
  review/        local review UI                            (M3)
schemas/         form schemas; amr_flow_v1.yaml is the flow set's
scripts/         model pull, dataset pull, synthetic pages, gold set
docs/bench.md    pinned revisions, open-question findings, latency
```

Adding a form means writing a schema YAML. It should never mean editing code.

[amr]: https://huggingface.co/datasets/Nigeria-Health-data-OCR-pipeline/African-Medical-Records
