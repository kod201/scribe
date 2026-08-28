# M5 deployment runbook — CUDA box + REDCap

M5 exit criterion (PRD 14): a record imported into a **test** REDCap project,
with the vLLM backend verified on the target GPU box. Everything below is
prepared and unit-tested on the laptop; the two final verifications require
the actual machine and a test project.

## A. vLLM backend on the GPU box

1. Install (Python 3.12 venv on the box):
   ```bash
   uv venv && uv pip install -e . && uv pip install vllm
   ```
2. Copy `config.cuda.example.yaml` → `config.yaml`. Choose and **pin** the
   model revision (`huggingface-cli download Qwen/Qwen3-VL-30B-A3B-Instruct`,
   note the snapshot sha, write it into `extraction_engine.revision` **and**
   `docs/bench.md`).
3. `scribe serve` (terminal 1) — it runs
   `vllm serve <model> --host 127.0.0.1 --port 8081 --revision <sha> <extra_serve_args>`.
4. `scribe status` (terminal 2) must show the engine healthy — the same check
   as on the Mac, including the foreign-model guard.
5. Smoke: ingest 2–3 flow pages, `scribe run`, confirm extractions and that
   `structured: true` requests succeed (watch the vLLM log for guided-decoding
   errors; the client falls back to unconstrained + repair automatically, so a
   parse-failure-free run does not by itself prove constrained decoding —
   check the log).
6. Re-run the **contamination check** (PRD 12.3) for the CUDA model revision —
   it is a different set of weights than the MLX 8-bit conversion; the flow-set
   caveats apply per revision.
7. Record throughput (s/field, whole-page vs routed) in `docs/bench.md` —
   expect very different numbers from the Mac; revisit `verify_pass` once
   measured.

## B. REDCap import

Design: the adapter (`src/scribe/stages/redcap.py`) refuses to run unless the
REDCap host is explicitly listed under `security.allow_hosts` — pasting an
`api_url` is not consent. The token comes only from the environment variable
named by `redcap.token_env` and never appears in config, the database, logs,
or error messages. Only finalized records are eligible. A count mismatch from
REDCap marks nothing as exported.

1. In the test REDCap project, create a data dictionary whose field names
   match the schema (or fill `redcap.field_map` to translate). Table fields
   arrive as JSON strings — give them a Notes-type field, or set
   `table_fields_as_json: false` to drop them from the import.
2. Configure:
   ```yaml
   security:
     allow_hosts: [127.0.0.1, localhost, redcap.example.org]
   redcap:
     api_url: https://redcap.example.org/api/
     field_map: {}          # or scribe_field: redcap_field
   ```
3. `export REDCAP_API_TOKEN=...` (the project-scoped API token).
4. Dry-run the payload shape first:
   ```bash
   uv run python -c "
   import sys; sys.path.insert(0,'src')
   from scribe.config import load_config; from scribe.db import connect
   from scribe.stages.redcap import build_redcap_rows
   import json
   cfg = load_config(); conn = connect(cfg.paths.db)
   print(json.dumps(build_redcap_rows(conn, cfg)[:2], indent=2))"
   ```
5. `scribe export --format redcap` — the M5 exit is this succeeding against
   the test project and the record showing up in REDCap's record status
   dashboard.

## C. What stays true on both machines

- One `config.yaml` switch between backends; no code changes (PRD 16).
- `scribe run` still refuses to start with cloud endpoints in the environment
  and holds the socket guard; the REDCap call happens only in `scribe export`,
  under the explicit allowlist.
- The MLX and CUDA models are different quantizations of different conversions:
  never mix their bench numbers or eval reports without labeling the backend.
