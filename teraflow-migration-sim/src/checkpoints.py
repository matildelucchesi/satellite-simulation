"""Durable identity of the currently mutating child of a composite job."""
from .storage import atomic_json, utc_now


class ActiveCheckpoint:
    def __init__(self, path): self.path = path

    def __call__(self, **context):
        atomic_json(self.path, {'schema_version': 1, 'timestamp_utc': utc_now(), **context})
