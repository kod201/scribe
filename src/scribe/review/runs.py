"""Background extraction runs for the workbench UI.

One run at a time, executed in a daemon thread against the same (serialized)
SQLite connection the UI uses. Progress is an append-only event list the
frontend polls with a `since` cursor -- no websockets, nothing to reconnect.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from sqlite3 import Connection
from urllib.parse import urlparse

from scribe.config import Config


class RunManager:
    def __init__(self, conn: Connection, cfg: Config) -> None:
        self._conn = conn
        self._cfg = cfg
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._events: list[dict] = []
        self.running = False
        self.counters: dict = {}

    # -- events ---------------------------------------------------------------

    def _emit(self, kind: str, **data) -> None:
        with self._lock:
            self._events.append({
                "seq": len(self._events),
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                **data,
            })

    def status(self, since: int = 0) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "n_events": len(self._events),
                "events": self._events[since:],
                "counters": dict(self.counters),
            }

    # -- lifecycle ------------------------------------------------------------

    def start(self, doc_id: str | None = None,
              schema_id: str | None = None) -> tuple[bool, str]:
        with self._lock:
            if self.running:
                return False, "a run is already in progress"
            self.running = True
            self._events.clear()
            self.counters = {
                "pages_total": 0, "pages_done": 0,
                "fields_done": 0, "flagged": 0, "failures": 0,
            }
        self._thread = threading.Thread(
            target=self._run, args=(doc_id, schema_id), daemon=True
        )
        self._thread.start()
        return True, "started"

    # -- the run itself -------------------------------------------------------

    def _run(self, doc_id: str | None, schema_id: str | None) -> None:
        try:
            self._run_inner(doc_id, schema_id)
        except Exception as e:  # noqa: BLE001 -- surface, never crash the server
            self._emit("error", message=str(e))
        finally:
            with self._lock:
                self.running = False
            self._emit("run_done", counters=dict(self.counters))

    def _run_inner(self, doc_id: str | None, schema_id: str | None) -> None:
        from scribe.engines import build_extraction_engine, build_layout_engine
        from scribe.engines.registry import build_verify_engine
        from scribe.net import assert_offline, no_outbound_network
        from scribe.schema import find_schema
        from scribe.stages.extract import (
            extract_page,
            mark_document_extracted,
            pages_to_extract,
        )

        cfg, conn = self._cfg, self._conn
        if cfg.security.assert_offline:
            assert_offline(cfg.extraction_engine.server_url,
                           cfg.security.allow_hosts)

        self._emit("phase", message="checking engines")
        engine = build_extraction_engine(cfg)
        h = engine.health()
        if not h.ok:
            raise RuntimeError(f"extraction engine unhealthy: {h.detail}")
        layout = build_layout_engine(cfg)
        verify_engine = build_verify_engine(cfg)
        if verify_engine is not None:
            vh = verify_engine.health()
            if not vh.ok:
                raise RuntimeError(
                    f"verify engine unhealthy: {vh.detail} -- start it with"
                    " `scribe serve --verify`"
                )

        pages = pages_to_extract(conn, doc_id)
        if not pages:
            self._emit("phase", message="nothing to extract -- ingest first")
            return
        self.counters["pages_total"] = len(pages)
        self._emit("run_started", pages=len(pages),
                   model=cfg.extraction_engine.model,
                   verify=verify_engine.model if verify_engine else None,
                   layout=layout.name)

        schemas: dict = {}

        def _schema_for(row):
            sid = row["doc_schema_id"] or schema_id
            if not sid:
                raise KeyError(
                    f"document {row['doc_id']} has no schema bound; re-ingest"
                    " with a schema selected"
                )
            if sid not in schemas:
                schemas[sid] = find_schema(sid)
            return schemas[sid]

        allow = set(cfg.security.allow_hosts)
        allow.add(urlparse(cfg.extraction_engine.server_url).hostname
                  or "127.0.0.1")
        if cfg.verify_engine is not None:
            allow.add(urlparse(cfg.verify_engine.server_url).hostname
                      or "127.0.0.1")

        done_docs: set[str] = set()
        with no_outbound_network(allow):
            for row in pages:
                try:
                    schema = _schema_for(row)
                except KeyError as e:
                    self._emit("page_failed", doc_id=row["doc_id"],
                               page_no=row["page_no"], message=e.args[0])
                    self.counters["failures"] += 1
                    continue
                self._emit("page_started", doc_id=row["doc_id"],
                           page_no=row["page_no"])
                t0 = time.perf_counter()
                n_fields = 0

                def _progress(name: str) -> None:
                    nonlocal n_fields
                    n_fields += 1
                    self.counters["fields_done"] += 1
                    self._emit("field", doc_id=row["doc_id"],
                               page_no=row["page_no"], field=name)

                try:
                    extract_page(conn, cfg, engine, schema, row, _progress,
                                 layout=layout, verify_engine=verify_engine)
                except Exception as e:  # noqa: BLE001 -- keep the batch going
                    self._emit("page_failed", doc_id=row["doc_id"],
                               page_no=row["page_no"], message=str(e))
                    self.counters["failures"] += 1
                    continue
                dt = time.perf_counter() - t0
                flags = conn.execute(
                    "SELECT COUNT(*) FROM extractions WHERE page_id=?"
                    " AND flagged=1", (row["page_id"],),
                ).fetchone()[0]
                self.counters["pages_done"] += 1
                self.counters["flagged"] = conn.execute(
                    "SELECT COUNT(*) FROM review_queue"
                ).fetchone()[0]
                self._emit("page_done", doc_id=row["doc_id"],
                           page_no=row["page_no"], n_fields=n_fields,
                           seconds=round(dt, 1), flagged=flags)
                done_docs.add(row["doc_id"])

        for d in done_docs:
            mark_document_extracted(conn, d)
