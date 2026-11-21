"""A hand-written candidate, used to exercise the verifier without any API."""
from pathlib import Path

from ..common.jsonio import atomic_json, load_json


class FileProvider:
    model_id = 'manual-candidate'

    def __init__(self, path):
        self.path = Path(path)

    def propose(self, normal, requested, classes, feedback, directory, existing=()):
        value = load_json(self.path)
        atomic_json(directory / 'api-response.json', value)
        return value
