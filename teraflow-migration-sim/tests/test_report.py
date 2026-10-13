import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from src.analysis import Analysis
from src.storage import atomic_json


class ReportTests(unittest.TestCase):
    def test_repeated_primary_case_does_not_complete_eighteen_case_matrix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for index in range(18):
                atomic_json(root/f'results/runs/run-{index}/metadata.json',{
                    'run_id':f'run-{index}','purpose':'primary','method':'cold',
                    'configured_rate_bps':1000000000,'outcome':'experimental_failure',
                    'event':{'event_id':'same-event'}})
            result=Analysis.report(SimpleNamespace(root=root))
            self.assertFalse(result['primary_complete'])
            document=json.loads((root/'results/report/report.json').read_text())
            self.assertEqual(document['unique_primary_cases'],1)
            self.assertEqual(document['primary_count'],18)
