"""Lettura centralizzata delle impostazioni infrastrutturali."""

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class ServiceSettings:
    """Impostazioni minime comuni a ogni servizio."""

    name: str
    port: int
    log_level: str
    config_path: str

    @classmethod
    def from_environment(cls, default_name: str) -> "ServiceSettings":
        return cls(
            name=os.getenv("SERVICE_NAME", default_name),
            port=int(os.getenv("SERVICE_PORT", "5000")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            config_path=os.getenv(
                "CONFIG_PATH", "/app/config/constellation.json"
            ),
        )

