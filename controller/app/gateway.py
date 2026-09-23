"""Gateway REST che inoltra le API all'istanza Controller attiva su un satellite."""

from __future__ import annotations

import json
from threading import RLock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .service import ControllerStateError


class ControllerGateway:
    """Compatibilità REST: inoltra le operazioni al Controller del satellite host."""

    def __init__(self, agent_url_template: str, timeout: float = 3.0) -> None:
        self.agent_url_template = agent_url_template.rstrip("/")
        self.timeout = timeout
        self._lock = RLock()
        self._host_satellite_id = "UNASSIGNED"

    @property
    def host_satellite_id(self) -> str:
        with self._lock:
            return self._host_satellite_id

    @property
    def checkpoint_path(self):
        return "satellite-local"

    @property
    def active(self) -> bool:
        # L'API del gateway resta pronta anche prima dell'elezione iniziale.
        return True

    @property
    def quiesced(self) -> bool:
        try:
            return bool(self._request("GET", "/health").get("quiesced"))
        except (RuntimeError, ControllerStateError):
            return False

    def _url(self, suffix: str) -> str:
        host = self.host_satellite_id
        if host == "UNASSIGNED":
            raise RuntimeError("Nessun satellite ospita il Controller")
        number = host.removeprefix("SAT-")
        return f"{self.agent_url_template.format(satellite_number=number)}/controller{suffix}"

    def _request(self, method: str, suffix: str, payload: dict[str, Any] | None = None):
        url = self._url(suffix)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in {409, 503}:
                raise RuntimeError(detail or f"Controller locale: HTTP {exc.code}") from exc
            raise ControllerStateError(detail or f"Controller locale: HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"Controller su {self.host_satellite_id} non raggiungibile: {exc}") from exc
        return json.loads(body.decode("utf-8")) if body else {}

    def heartbeat_snapshot(self, satellite_id: str | None = None) -> dict[str, Any]:
        if self.host_satellite_id == "UNASSIGNED":
            return {"sequence_number": 0, "timestamp": None, "heartbeats": {}}
        suffix = "/heartbeat"
        if satellite_id is not None:
            suffix += "?" + urlencode({"id": satellite_id})
        return self._request("GET", suffix)

    def record_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/heartbeat", payload).get("heartbeat", {})

    def snapshot(self) -> dict[str, Any]:
        if self.host_satellite_id == "UNASSIGNED":
            return {
                "topology": {"nodes": {}, "links": []},
                "routing_table": {},
                "heartbeats": {},
                "sequence_number": 0,
                "timestamp": "",
            }
        return self._request("GET", "/state")

    def set_host_satellite(self, satellite_id: Any) -> dict[str, Any]:
        if not isinstance(satellite_id, str) or not satellite_id.strip().upper().startswith("SAT-"):
            raise ControllerStateError("satellite_id deve avere formato SAT-N")
        normalized = satellite_id.strip().upper()
        if not normalized[4:].isdigit():
            raise ControllerStateError("satellite_id deve avere formato SAT-N")
        with self._lock:
            previous = self._host_satellite_id
            self._host_satellite_id = normalized
        return {
            "status": "updated",
            "previous_host_satellite_id": previous,
            "host_satellite_id": normalized,
        }

    def reset_simulation(self) -> dict[str, Any]:
        try:
            result = self._request("POST", "/reset_simulation")
        except RuntimeError:
            result = None
        with self._lock:
            self._host_satellite_id = "UNASSIGNED"
        return {"status": "reset", "host_satellite_id": "UNASSIGNED", "local": result}

    def checkpoint(self) -> dict[str, Any]:
        return self._request("POST", "/checkpoint").get("checkpoint", {})

    def restore(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", "/restore", payload or {}).get("state", {})

    def shutdown(self) -> dict[str, Any]:
        return self._request("POST", "/shutdown")

    def quiesce(self) -> dict[str, Any]:
        return self._request("POST", "/quiesce")

    def resume(self) -> dict[str, Any]:
        return self._request("POST", "/resume")
