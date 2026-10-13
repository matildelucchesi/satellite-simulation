import json
import unittest
from pathlib import Path
from tools.validate_artifact_manifest import validate


class ManifestTests(unittest.TestCase):
    def test_invalid_resources_cannot_unlock_campaign(self):
        document = json.loads((Path(__file__).parents[1]/'config/artifact_manifest.template.json').read_text())
        document['resources']['measured_controller_cpu_cores'] = float('nan')
        document['resources']['measured_controller_ram_gib'] = -1
        document['resources']['measured_controller_disk_gib'] = True
        issues = validate(document)
        self.assertTrue(any('cpu_cores' in issue for issue in issues))
        self.assertTrue(any('ram_gib' in issue for issue in issues))
        self.assertTrue(any('disk_gib' in issue for issue in issues))

    def test_fractional_bytes_and_invalid_hashes_are_rejected(self):
        document = json.loads((Path(__file__).parents[1]/'config/artifact_manifest.template.json').read_text())
        document['operational_state']['cold_snapshot_bytes'] = 0.5
        document['operational_state']['sha256'] = 'not-a-checksum'
        issues = validate(document)
        self.assertTrue(any('cold_snapshot_bytes: nonnegative' in issue for issue in issues))
        self.assertTrue(any('operational_state.sha256: SHA-256' in issue for issue in issues))
