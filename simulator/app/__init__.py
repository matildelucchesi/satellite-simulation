"""Application factory del servizio Simulator."""

from flask import Flask

from common.http import health_response
from common.settings import ServiceSettings


def create_app() -> Flask:
    """Crea l'app Flask; la logica orbitale verrà aggiunta in seguito."""

    app = Flask(__name__)
    settings = ServiceSettings.from_environment("simulator")
    app.config["SERVICE_SETTINGS"] = settings

    @app.get("/health")
    def health():
        return health_response(settings.name)

    return app

