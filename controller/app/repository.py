"""Porta di persistenza e adapter file JSON per i checkpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class CheckpointRepository(Protocol):
    @property
    def path(self) -> Path: ...

    def save(self, serialized_state: str) -> None: ...

    def load(self) -> str: ...


class JsonFileCheckpointRepository:
    """Persistenza atomica del checkpoint su filesystem."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def save(self, serialized_state: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary_path.write_text(serialized_state + "\n", encoding="utf-8")
        temporary_path.replace(self.path)

    def load(self) -> str:
        if not self.path.is_file():
            raise FileNotFoundError(f"Checkpoint non trovato: {self.path}")
        return self.path.read_text(encoding="utf-8")
