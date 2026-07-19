"""Risposte HTTP condivise, prive di logica di dominio."""

from flask import jsonify


def health_response(service_name: str):
    """Restituisce lo stato minimo necessario ai health check Docker."""

    return jsonify({"service": service_name, "status": "ok"}), 200

