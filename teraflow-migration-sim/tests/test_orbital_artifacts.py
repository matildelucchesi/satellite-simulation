import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parents[1]


class OrbitalArtifactTests(unittest.TestCase):
    def test_frozen_tle_matches_source_manifest_and_selection(self):
        manifest = json.loads((ROOT / "data" / "source_manifest.json").read_text(encoding="utf-8"))
        tle = ROOT / "data" / manifest["file"]
        self.assertEqual(hashlib.sha256(tle.read_bytes()).hexdigest().upper(), manifest["sha256"])
        selection = json.loads((ROOT / "config" / "selected_constellation.json").read_text(encoding="utf-8"))
        self.assertEqual(selection["metadata"]["catalog_count"], manifest["records"])
        self.assertEqual(len(selection["satellites"]), 17)
        self.assertEqual(len({s["norad_id"] for s in selection["satellites"]}), 17)
        self.assertEqual(Counter(s["plane"] for s in selection["satellites"]), {1: 6, 2: 11})
        ages = [s["tle_age_hours_at_reference"] for s in selection["satellites"]]
        self.assertLess(max(ages), 24)

    def test_fso_preflight_has_no_sgp4_errors_and_contact_can_align(self):
        result = json.loads((ROOT / "results" / "direct_link_windows.json").read_text(encoding="utf-8"))
        self.assertEqual(result["sgp4_errors_by_norad"], {})
        self.assertEqual(result["window_count"], 168)
        self.assertEqual(result["windows_at_least_alignment_count"], 168)
        self.assertEqual(len({(w["sat_a"], w["sat_b"]) for w in result["windows"]}), 7)
        self.assertTrue(all(w["duration_s"] >= 60 for w in result["windows"]))


if __name__ == "__main__":
    unittest.main()
