"""Scribe command line (PRD 11).

Commands that belong to a later milestone exit with a clear notice rather than
a stack trace, so the skeleton is walkable end to end from M0.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from scribe import __version__
from scribe.config import Config, load_config

app = typer.Typer(
    name="scribe",
    help="Local handwriting-to-structured-data pipeline. Nothing leaves the machine.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

ConfigOpt = Annotated[
    Optional[Path],
    typer.Option("--config", "-c", help="Path to config.yaml"),
]


def _cfg(path: Optional[Path]) -> Config:
    try:
        cfg = load_config(path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from None
    cfg.paths.mkdirs()
    return cfg


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------


@app.command()
def status(config: ConfigOpt = None) -> None:
    """Show engine health, offline posture, schemas and database state."""
    from scribe.db import counts, init_db
    from scribe.engines import build_extraction_engine, build_layout_engine
    from scribe.net import OfflineAssertionError, assert_offline
    from scribe.schema import list_schemas

    cfg = _cfg(config)
    console.print(f"[bold]scribe {__version__}[/bold]  config={cfg.source_path}")

    # Offline posture
    try:
        assert_offline(
            cfg.extraction_engine.server_url, cfg.security.allow_hosts
        )
        console.print("[green]offline check   OK[/green]  no cloud endpoint in environment")
    except OfflineAssertionError as e:
        console.print(f"[red]offline check   FAIL[/red]\n{e}")

    # Engines
    t = Table(show_header=True, header_style="bold")
    t.add_column("component")
    t.add_column("status")
    t.add_column("detail", overflow="fold")

    lay = build_layout_engine(cfg)
    t.add_row("layout", "[green]ok[/green]" if lay.health().ok else "[red]down[/red]",
              f"{lay.name}: {lay.health().detail}")

    eng = build_extraction_engine(cfg)
    h = eng.health()
    lat = f" ({h.latency_ms:.0f} ms)" if h.latency_ms else ""
    t.add_row(
        "extraction",
        "[green]healthy[/green]" if h.ok else "[red]unhealthy[/red]",
        f"{h.backend}:{h.model}\nrev {eng.version[:12]}\n{h.detail}{lat}",
    )
    console.print(t)

    # Schemas
    schemas = list_schemas()
    if schemas:
        st = Table(show_header=True, header_style="bold")
        st.add_column("schema_id")
        st.add_column("v")
        st.add_column("page types")
        st.add_column("fields")
        for _p, s in schemas:
            st.add_row(s.schema_id, str(s.version),
                       ", ".join(s.page_type_ids) or "-", str(len(s.fields)))
        console.print(st)
    else:
        console.print("[yellow]no schemas found in ./schemas[/yellow]")

    # Database
    conn = init_db(cfg.paths.db)
    c = counts(conn)
    console.print(
        f"db {cfg.paths.db}  "
        + "  ".join(f"{k}={v}" for k, v in c.items())
    )
    raise typer.Exit(0 if h.ok else 1)


# --------------------------------------------------------------------------
# serve
# --------------------------------------------------------------------------


@app.command()
def serve(
    config: ConfigOpt = None,
    host: str = typer.Option("127.0.0.1", help="Bind address; keep it loopback."),
    port: Optional[int] = typer.Option(None, help="Override the port in config.yaml."),
    verify: bool = typer.Option(
        False, "--verify", help="Serve the verify_engine model instead."
    ),
) -> None:
    """Start the local model server and block. Run this in its own terminal."""
    import os
    import subprocess
    from urllib.parse import urlparse

    cfg = _cfg(config)
    if verify:
        if cfg.verify_engine is None:
            console.print("[red]no verify_engine configured in config.yaml[/red]")
            raise typer.Exit(2)
        ec = cfg.verify_engine
    else:
        ec = cfg.extraction_engine
    url = urlparse(ec.server_url)
    bind_port = port or url.port or 8081

    if ec.backend == "mlx":
        import sys

        # sys.executable, not "python": scribe itself may be launched via its
        # venv entry point from a shell where bare `python` resolves elsewhere
        # (or nowhere).
        cmd = [
            sys.executable, "-m", "mlx_vlm.server",
            "--host", host,
            "--port", str(bind_port),
            "--model", ec.model,
        ] + ec.extra_serve_args
    elif ec.backend == "vllm":
        cmd = [
            "vllm", "serve", ec.model,
            "--host", host, "--port", str(bind_port),
        ]
        if ec.revision:
            cmd += ["--revision", ec.revision]
        cmd += ec.extra_serve_args
    else:
        console.print(f"[red]Unknown backend '{ec.backend}'[/red]")
        raise typer.Exit(2)

    env = dict(os.environ)
    if ec.revision and ec.backend == "mlx":
        # Pin the snapshot so the server cannot silently pick up a newer
        # revision than the one recorded in docs/bench.md.
        env["HF_HUB_OFFLINE"] = env.get("HF_HUB_OFFLINE", "1")

    console.print(f"[bold]starting {ec.backend} server[/bold] on {host}:{bind_port}")
    console.print(f"model {ec.model}")
    if ec.revision:
        console.print(f"rev   {ec.revision}")
    console.print(f"[dim]{' '.join(cmd)}[/dim]\n")
    try:
        raise typer.Exit(subprocess.call(cmd, env=env))
    except FileNotFoundError:
        console.print(
            f"[red]{cmd[0]} not found.[/red] Install the serving extra:\n"
            f"  uv sync --extra mlx"
        )
        raise typer.Exit(2) from None
    except KeyboardInterrupt:
        raise typer.Exit(0) from None


# --------------------------------------------------------------------------
# pipeline commands
# --------------------------------------------------------------------------


@app.command()
def ingest(
    path: Annotated[Path, typer.Argument(help="Image, PDF, or folder of them")],
    config: ConfigOpt = None,
    schema_id: Optional[str] = typer.Option(None, "--schema", help="Schema to bind"),
) -> None:
    """Add files to the pipeline: hash, dedupe, split pages, deskew."""
    from scribe.db import init_db
    from scribe.schema import find_schema
    from scribe.stages.ingest import ingest_path

    cfg = _cfg(config)
    if not path.exists():
        console.print(f"[red]{path} does not exist[/red]")
        raise typer.Exit(2)
    if schema_id:
        try:
            find_schema(schema_id)   # fail before ingesting, not at run time
        except KeyError as e:
            console.print(f"[red]{e.args[0]}[/red]")
            raise typer.Exit(2) from None

    conn = init_db(cfg.paths.db)
    res = ingest_path(conn, cfg, path, schema_id)

    for doc_id in res.ingested:
        row = conn.execute(
            "SELECT source_path, page_count FROM documents WHERE doc_id = ?",
            (doc_id,),
        ).fetchone()
        console.print(
            f"[green]+[/green] {doc_id}  {Path(row['source_path']).name}"
            f"  ({row['page_count']} page{'s' if row['page_count'] != 1 else ''})"
        )
    for src in res.skipped_duplicate:
        console.print(f"[yellow]=[/yellow] duplicate, skipped: {Path(src).name}")
    for src in res.skipped_unsupported:
        console.print(f"[yellow]?[/yellow] unsupported type: {src}")
    for src, err in res.failed:
        console.print(f"[red]![/red] {Path(src).name}: {err}")

    console.print(
        f"\n{len(res.ingested)} ingested, {len(res.skipped_duplicate)} duplicates,"
        f" {len(res.failed)} failed"
    )
    raise typer.Exit(1 if res.failed else 0)


@app.command("prep-register")
def prep_register(
    path: Annotated[Path, typer.Argument(help="Photo or folder of photos")],
    out: Path = typer.Option(
        Path("./data/register_prep"), "--out", help="Output root for band crops"
    ),
    bands: int = typer.Option(4, help="Vertical bands per photo"),
    overlap: float = typer.Option(0.12, help="Band overlap fraction"),
    rotate: str = typer.Option(
        "auto", help="Portrait handling: auto | cw | ccw | none"
    ),
) -> None:
    """Slice wide register photos into column bands ready for ingest."""
    from scribe.stages.register_prep import prep_folder

    if not path.exists():
        console.print(f"[red]{path} does not exist[/red]")
        raise typer.Exit(2)
    results = prep_folder(path, out, bands, overlap, rotate)
    failed = 0
    for src, r in results.items():
        if isinstance(r, Exception):
            console.print(f"[red]![/red] {src.name}: {r}")
            failed += 1
            continue
        rot = f" rotated {r.rotated}" if r.rotated else ""
        console.print(
            f"[green]+[/green] {src.name}: {len(r.band_paths)} bands{rot}"
            f" -> {r.band_paths[0].parent}"
        )
    console.print(
        f"\n{len(results) - failed} prepped, {failed} failed."
        f"  Next: scribe ingest {out}/<stem> --schema cabla_register_v1"
    )
    raise typer.Exit(1 if failed else 0)


@app.command()
def run(
    config: ConfigOpt = None,
    doc: Optional[str] = typer.Option(None, "--doc", help="Limit to one document"),
    schema_id: Optional[str] = typer.Option(
        None, "--schema", help="Schema for documents that were ingested without one"
    ),
) -> None:
    """Run extraction + validation. Idempotent and resumable."""
    from urllib.parse import urlparse

    from scribe.db import init_db
    from scribe.engines import build_extraction_engine, build_layout_engine
    from scribe.engines.registry import build_verify_engine
    from scribe.net import assert_offline, no_outbound_network
    from scribe.schema import find_schema
    from scribe.stages.extract import (
        extract_page,
        mark_document_extracted,
        pages_to_extract,
    )

    cfg = _cfg(config)

    # PRD 13: fail before doing anything if the environment points anywhere
    # but this machine, then hold the socket guard for the entire run.
    if cfg.security.assert_offline:
        assert_offline(cfg.extraction_engine.server_url, cfg.security.allow_hosts)

    engine = build_extraction_engine(cfg)
    h = engine.health()
    if not h.ok:
        console.print(f"[red]extraction engine unhealthy:[/red] {h.detail}")
        raise typer.Exit(1)
    layout = build_layout_engine(cfg)
    if layout.name != "none":
        console.print(f"[bold]layout:[/bold] {layout.name} (crop-based extraction)")
    verify_engine = build_verify_engine(cfg)
    if verify_engine is not None:
        vh = verify_engine.health()
        if not vh.ok:
            console.print(f"[red]verify engine unhealthy:[/red] {vh.detail}")
            console.print("start it with `scribe serve --verify` in another terminal")
            raise typer.Exit(1)
        console.print(f"[bold]verify:[/bold] {verify_engine.model} (cross-model)")

    conn = init_db(cfg.paths.db)
    pages = pages_to_extract(conn, doc)
    if not pages:
        console.print("nothing to extract -- ingest something first")
        raise typer.Exit(0)

    # Resolve each document's schema once, up front.
    schemas = {}
    def _schema_for(row):
        sid = row["doc_schema_id"] or schema_id
        if not sid:
            raise KeyError(
                f"document {row['doc_id']} has no schema; re-ingest with"
                f" --schema or pass --schema to run"
            )
        if sid not in schemas:
            schemas[sid] = find_schema(sid)
        return schemas[sid]

    allow = set(cfg.security.allow_hosts)
    allow.add(urlparse(cfg.extraction_engine.server_url).hostname or "127.0.0.1")
    if cfg.verify_engine is not None:
        allow.add(urlparse(cfg.verify_engine.server_url).hostname or "127.0.0.1")

    done_docs: set[str] = set()
    failures = 0
    with no_outbound_network(allow):
        for row in pages:
            try:
                schema = _schema_for(row)
            except KeyError as e:
                console.print(f"[red]{e.args[0]}[/red]")
                failures += 1
                continue
            label = f"{row['doc_id']} p{row['page_no']}"
            console.print(f"[bold]{label}[/bold]")
            t0 = __import__("time").perf_counter()
            n_fields = 0

            def _progress(name: str) -> None:
                nonlocal n_fields
                n_fields += 1
                console.print(f"  {name} ...", end="\r")

            try:
                extract_page(conn, cfg, engine, schema, row, _progress,
                             layout=layout, verify_engine=verify_engine)
            except Exception as e:  # noqa: BLE001 -- keep the batch going
                console.print(f"  [red]failed:[/red] {e}")
                failures += 1
                continue
            dt = __import__("time").perf_counter() - t0
            flags = conn.execute(
                "SELECT COUNT(*) FROM extractions WHERE page_id=? AND flagged=1",
                (row["page_id"],),
            ).fetchone()[0]
            per = f", {dt / n_fields:.1f}s/field" if n_fields else " (cached)"
            console.print(
                f"  {n_fields} extracted in {dt:.0f}s{per}, {flags} flagged"
            )
            done_docs.add(row["doc_id"])

    for d in done_docs:
        mark_document_extracted(conn, d)

    total = conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0]
    queue = conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0]
    console.print(f"\nextractions={total}  review_queue={queue}")
    raise typer.Exit(1 if failures else 0)


@app.command()
def review(
    config: ConfigOpt = None,
    port: int = typer.Option(8666, help="Port for the local review UI"),
) -> None:
    """Launch the local workbench UI: ingest, run, browse results, review."""
    import uvicorn

    from scribe.db import init_db
    from scribe.review.app import create_app

    cfg = _cfg(config)
    conn = init_db(cfg.paths.db)
    n = conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0]
    console.print(f"[bold]review queue:[/bold] {n} flagged fields")
    console.print(f"open [bold]http://127.0.0.1:{port}[/bold]  (Ctrl-C to stop)")
    uvicorn.run(create_app(conn, cfg), host="127.0.0.1", port=port,
                log_level="warning")


@app.command()
def export(
    config: ConfigOpt = None,
    format: str = typer.Option("csv", "--format", "-f", help="csv | jsonl | redcap"),
    schema_id: Optional[str] = typer.Option(None, "--schema"),
    out: Optional[Path] = typer.Option(None, "--out", help="Output file"),
) -> None:
    """Export finalized records."""
    from datetime import datetime

    from scribe.db import init_db
    from scribe.stages.export import export_csv, export_jsonl

    cfg = _cfg(config)
    conn = init_db(cfg.paths.db)
    if format == "redcap":
        from scribe.stages.redcap import (
            RedcapConfigError,
            RedcapImportError,
            export_redcap,
        )

        try:
            res = export_redcap(conn, cfg, schema_id)
        except (RedcapConfigError, RedcapImportError) as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from None
        if res.imported == 0:
            console.print("[yellow]no finalized records to import[/yellow]")
            raise typer.Exit(1)
        console.print(
            f"[green]imported {res.imported} records[/green] into REDCap at "
            f"{cfg.redcap.api_url}"
        )
        return
    if format not in ("csv", "jsonl"):
        console.print("[red]--format must be csv, jsonl or redcap[/red]")
        raise typer.Exit(2)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out or Path(cfg.paths.exports) / f"records_{stamp}.{format}"
    n = (export_csv if format == "csv" else export_jsonl)(conn, path, schema_id)
    if n == 0:
        console.print("[yellow]no finalized records to export -- finalize "
                      "documents in the review UI first[/yellow]")
        path.unlink(missing_ok=True)
        raise typer.Exit(1)
    console.print(f"[green]exported {n} records[/green] -> {path}")


@app.command("eval")
def eval_cmd(
    gold: Annotated[Path, typer.Option("--gold", help="Path to gold.csv")],
    config: ConfigOpt = None,
    set_name: str = typer.Option(
        "flow", "--set", help="flow | heldout -- labels the report"
    ),
    out: Optional[Path] = typer.Option(None, "--out", help="Write markdown here"),
) -> None:
    """Score extractions against a gold set."""
    from rich.markdown import Markdown

    from scribe.db import init_db
    from scribe.stages.evaluate import evaluate, render_markdown

    cfg = _cfg(config)
    if set_name not in ("flow", "heldout"):
        console.print("[red]--set must be 'flow' or 'heldout'[/red]")
        raise typer.Exit(2)
    if not gold.exists():
        console.print(f"[red]no gold file at {gold}[/red]")
        raise typer.Exit(2)

    conn = init_db(cfg.paths.db)
    report = evaluate(conn, gold, set_name)
    md = render_markdown(report)
    console.print(Markdown(md))
    if out:
        out.write_text(md + "\n")
        console.print(f"\nwritten to {out}")


@app.command()
def purge(
    config: ConfigOpt = None,
    doc: Annotated[str, typer.Option("--doc", help="Document id to erase")] = "",
) -> None:
    """Remove every artifact for a document: rows, page images, crops."""
    from scribe.db import init_db
    from scribe.stages.ingest import purge_document

    cfg = _cfg(config)
    if not doc:
        console.print("[red]--doc is required[/red]")
        raise typer.Exit(2)
    conn = init_db(cfg.paths.db)
    if purge_document(conn, cfg, doc):
        console.print(f"[green]purged[/green] {doc}: rows and work artifacts removed")
    else:
        console.print(f"[yellow]no document with id {doc}[/yellow]")
        raise typer.Exit(1)


@app.command("schema")
def schema_cmd(
    schema_id: Optional[str] = typer.Argument(None, help="Show one schema"),
) -> None:
    """List schemas, or show one field by field."""
    from scribe.schema import find_schema, list_schemas

    if schema_id is None:
        for p, s in list_schemas():
            console.print(f"[bold]{s.schema_id}[/bold] v{s.version}  {p}")
            console.print(f"  {len(s.fields)} fields, page types: "
                          f"{', '.join(s.page_type_ids) or '-'}")
        return

    s = find_schema(schema_id)
    t = Table(show_header=True, header_style="bold", title=f"{s.schema_id} v{s.version}")
    for col in ("field", "type", "page type", "req", "constraints"):
        t.add_column(col, overflow="fold")
    for f in s.fields:
        cons = []
        if f.values:
            cons.append("values=" + "|".join(f.values))
        if f.min is not None or f.max is not None:
            cons.append(f"range={f.min}..{f.max}")
        if f.format:
            cons.append(f"format={f.format}")
        if f.regex:
            cons.append(f"regex={f.regex}")
        if f.columns:
            cons.append("cols=" + ",".join(c.name for c in f.columns))
        t.add_row(f.name, f.type, f.page_type or "-", "yes" if f.required else "",
                  "; ".join(cons))
    console.print(t)
    for r in s.cross_field_rules:
        console.print(f"[dim]rule:[/dim] {r.rule}  -> {r.on_fail}")


@app.command()
def version() -> None:
    """Print the version."""
    console.print(__version__)


if __name__ == "__main__":
    app()
