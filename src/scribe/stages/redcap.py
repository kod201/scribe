"""REDCap import adapter (M5, PRD 5.1 stage 6).

Design constraints, in order:

1. This is the ONE place the pipeline deliberately talks to something that is
   not loopback. It refuses to run unless the REDCap host is explicitly listed
   in security.allow_hosts -- pasting an api_url is not enough consent.
2. The API token comes from the environment (redcap.token_env), never from
   config or the database, and never appears in logs or error messages.
3. Only finalized records are eligible (the same rule as CSV/JSONL: nothing
   reaches a sink unreviewed).

Final verification against a real test REDCap project is the M5 exit
criterion and cannot happen on this laptop; everything up to the wire format
is tested with a mock transport.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from sqlite3 import Connection
from typing import Any
from urllib.parse import urlparse

import httpx

from scribe.config import Config


class RedcapConfigError(RuntimeError):
    pass


class RedcapImportError(RuntimeError):
    pass


@dataclass
class RedcapResult:
    imported: int
    record_ids: list[str]


def _require_allowed(api_url: str, allow_hosts: list[str]) -> None:
    host = urlparse(api_url).hostname or ""
    if host not in set(allow_hosts):
        raise RedcapConfigError(
            f"REDCap host '{host}' is not in security.allow_hosts. Exporting "
            f"sends extracted values off this machine (PRD 13); opt in "
            f"explicitly by adding the host to security.allow_hosts in "
            f"config.yaml."
        )


def _token(cfg: Config) -> str:
    var = cfg.redcap.token_env
    token = os.environ.get(var, "").strip()
    if not token:
        raise RedcapConfigError(
            f"No REDCap API token: set the {var} environment variable. The "
            f"token is never stored in config or the database."
        )
    return token


def build_redcap_rows(
    conn: Connection, cfg: Config, schema_id: str | None = None
) -> list[dict[str, Any]]:
    """Finalized records -> REDCap import rows (flat dicts of strings)."""
    q = "SELECT r.record_id, r.doc_id, r.final_json FROM records r"
    args: tuple[Any, ...] = ()
    if schema_id:
        q += " WHERE r.schema_id = ?"
        args = (schema_id,)
    rc = cfg.redcap
    rows: list[dict[str, Any]] = []
    for rec in conn.execute(q + " ORDER BY r.finalized_at", args):
        fields = json.loads(rec["final_json"])
        row: dict[str, Any] = {rc.record_id_field: rec["record_id"]}
        for name, value in fields.items():
            target = rc.field_map.get(name)
            if target is None:
                if rc.skip_unmapped and rc.field_map:
                    continue
                target = name
            if isinstance(value, (list, dict)):
                if not rc.table_fields_as_json:
                    continue
                row[target] = json.dumps(value, ensure_ascii=False)
            elif value is None:
                row[target] = ""
            else:
                row[target] = str(value)
        rows.append(row)
    return rows


def export_redcap(
    conn: Connection,
    cfg: Config,
    schema_id: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> RedcapResult:
    rc = cfg.redcap
    if not rc.api_url:
        raise RedcapConfigError(
            "redcap.api_url is not set in config.yaml (e.g. "
            "https://redcap.example.org/api/)."
        )
    _require_allowed(rc.api_url, cfg.security.allow_hosts)
    token = _token(cfg)

    rows = build_redcap_rows(conn, cfg, schema_id)
    if not rows:
        return RedcapResult(imported=0, record_ids=[])

    payload = {
        "token": token,
        "content": "record",
        "action": "import",
        "format": "json",
        "type": "flat",
        "overwriteBehavior": "overwrite" if rc.overwrite else "normal",
        "forceAutoNumber": "false",
        "data": json.dumps(rows, ensure_ascii=False),
        "returnContent": "count",
        "returnFormat": "json",
    }

    client = httpx.Client(transport=transport, timeout=60.0)
    try:
        resp = client.post(rc.api_url, data=payload)
    finally:
        client.close()

    if resp.status_code != 200:
        # REDCap returns error detail in the body; the token never appears
        # in our own message.
        raise RedcapImportError(
            f"REDCap import failed (HTTP {resp.status_code}): "
            f"{resp.text[:500]}"
        )
    try:
        count = int(resp.json().get("count", 0))
    except Exception as e:  # noqa: BLE001
        raise RedcapImportError(
            f"REDCap returned an unparseable response: {resp.text[:200]}"
        ) from e

    if count != len(rows):
        raise RedcapImportError(
            f"REDCap accepted {count} of {len(rows)} records; not marking "
            f"any as exported -- investigate before retrying."
        )

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "UPDATE records SET exported_at=?, export_target=? WHERE record_id=?",
        [(now, rc.api_url, r[cfg.redcap.record_id_field]) for r in rows],
    )
    return RedcapResult(imported=count,
                        record_ids=[r[rc.record_id_field] for r in rows])
