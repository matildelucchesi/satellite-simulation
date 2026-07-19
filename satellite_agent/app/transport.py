"""Porta HTTP e adapter urllib del Satellite Agent."""

from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.request import Request, urlopen


class AgentHttpTransport(Protocol):
    """Contratto minimo richiesto dai casi d'uso del Satellite Agent."""

    def get_json(self, url: str, timeout: float) -> dict[str, Any]: ...

    def post_json(
        self, url: str, payload: dict[str, Any], timeout: float
    ) -> int: ...


class UrllibAgentHttpTransport:
    """Implementazione di produzione basata esclusivamente sulla standard library."""

    def get_json(self, url: str, timeout: float) -> dict[str, Any]:
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("La risposta HTTP deve essere un oggetto JSON")
        return payload

    def post_json(
        self, url: str, payload: dict[str, Any], timeout: float
    ) -> int:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            return response.status
