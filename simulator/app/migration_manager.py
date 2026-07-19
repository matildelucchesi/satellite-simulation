"""Ricezione delle raccomandazioni di migrazione prodotte dallo score manager."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any


class MigrationManager:
    """Coda thread-safe delle migrazioni raccomandate dal coordinatore."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._notifications: list[dict[str, Any]] = []

    def notify_migration(self, recommendation: dict[str, Any]) -> None:
        with self._lock:
            self._notifications.append(deepcopy(recommendation))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "count": len(self._notifications),
                "latest": (
                    deepcopy(self._notifications[-1])
                    if self._notifications
                    else None
                ),
                "notifications": deepcopy(self._notifications),
            }

