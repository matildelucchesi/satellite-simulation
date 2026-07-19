"""Application factory della dashboard."""

from flask import Flask

from common.http import health_response
from common.settings import ServiceSettings


def create_app() -> Flask:
    """Crea la base Flask; viste e asset verranno aggiunti in seguito."""

    app = Flask(__name__)
    settings = ServiceSettings.from_environment("dashboard")
    app.config["SERVICE_SETTINGS"] = settings

    @app.get("/health")
    def health():
        return health_response(settings.name)

    return app

