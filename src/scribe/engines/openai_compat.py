"""OpenAI-compatible chat-completions client.

Both supported backends speak this protocol -- `mlx_vlm.server` on the Mac and
vLLM on the CUDA box -- so the pipeline talks one wire format regardless of
where the weights live (PRD 10).
"""

from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path
from typing import Any

import httpx

from scribe.engines.base import EngineHealth, ExtractionEngine, RawCompletion


def image_data_url(path: Path) -> str:
    """Inline an image as a data URL. Nothing is uploaded anywhere -- the
    request goes to loopback."""
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    b64 = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


class OpenAICompatEngine(ExtractionEngine):
    def __init__(
        self,
        *,
        server_url: str,
        model: str,
        backend: str = "mlx",
        revision: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.0,
        timeout_s: float = 300.0,
        structured_output: bool = True,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.model = model
        self.name = backend
        self.version = revision or "unpinned"
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout_s = timeout_s
        self.structured_output = structured_output

    # -- health ---------------------------------------------------------

    def health(self) -> EngineHealth:
        t0 = time.perf_counter()
        try:
            r = httpx.get(f"{self.server_url}/models", timeout=10.0)
            r.raise_for_status()
        except httpx.ConnectError:
            return EngineHealth(
                ok=False,
                backend=self.name,
                model=self.model,
                detail=(
                    f"no server at {self.server_url} -- start it with "
                    f"`scribe serve`"
                ),
            )
        except Exception as e:  # noqa: BLE001 -- surface whatever went wrong
            return EngineHealth(
                ok=False, backend=self.name, model=self.model, detail=str(e)
            )

        dt = (time.perf_counter() - t0) * 1000
        try:
            ids = [m.get("id") for m in r.json().get("data", [])]
        except Exception:  # noqa: BLE001
            ids = []
        if self.model in ids:
            return EngineHealth(
                ok=True, backend=self.name, model=self.model, latency_ms=dt,
                detail="server up; configured model loaded",
            )
        if ids:
            # Something else owns this port. Never report healthy here: a
            # foreign model would silently answer extraction requests and the
            # provenance rows would name a model that never ran.
            return EngineHealth(
                ok=False, backend=self.name, model=self.model, latency_ms=dt,
                detail=(
                    f"a different server owns {self.server_url} -- it serves "
                    f"{ids}, not the configured model. Change "
                    f"extraction_engine.server_url or stop that server."
                ),
            )
        return EngineHealth(
            ok=True, backend=self.name, model=self.model, latency_ms=dt,
            detail="server up; no model advertised yet (loads on first request)",
        )

    # -- completion -----------------------------------------------------

    def complete(
        self,
        *,
        system: str,
        user: str,
        images: list[Path],
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> RawCompletion:
        content: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": image_data_url(p)}}
            for p in images
        ]
        content.append({"type": "text", "text": user})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
            "stream": False,
        }

        structured = False
        if json_schema and self.structured_output:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "field_extraction",
                    "schema": json_schema,
                    "strict": True,
                },
            }
            structured = True

        t0 = time.perf_counter()
        r = httpx.post(
            f"{self.server_url}/chat/completions",
            json=payload,
            timeout=self.timeout_s,
        )
        dt = (time.perf_counter() - t0) * 1000

        if r.status_code >= 400 and structured:
            # Backend rejected the grammar; retry unconstrained and let the
            # JSON-repair path handle the output.
            payload.pop("response_format", None)
            structured = False
            t0 = time.perf_counter()
            r = httpx.post(
                f"{self.server_url}/chat/completions",
                json=payload,
                timeout=self.timeout_s,
            )
            dt = (time.perf_counter() - t0) * 1000

        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""

        return RawCompletion(
            text=text if isinstance(text, str) else str(text),
            model=data.get("model", self.model),
            latency_ms=dt,
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage") or {},
            structured=structured,
        )
