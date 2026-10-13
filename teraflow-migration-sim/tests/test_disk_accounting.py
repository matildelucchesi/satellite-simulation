import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from src.measurements import disk_content


class DiskAccountingTests(unittest.TestCase):
    def test_dependency_images_are_included_and_content_is_cached(self):
        rows=[{'Image':name,'SizeRw':10,'Mounts':[],'State':{'Running':True}}
            for name in ('controller','database','broker','controller')]
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            def run(command,**kwargs):
                return SimpleNamespace(stdout='a b c d' if command[1]=='ps' else '')
            with patch('src.measurements.subprocess.run',side_effect=run) as calls, \
                 patch('src.measurements.subprocess.check_output',return_value=json.dumps(rows)), \
                 patch('src.measurements.unique_layer_bytes',return_value=1000):
                first=disk_content(root,'sat-a','unused-six-image-bundle')
                second=disk_content(root,'sat-a','unused-six-image-bundle')
            saves=[call.args[0] for call in calls.call_args_list if call.args[0][1:3]==['image','save']]
            self.assertEqual(len(saves),1)
            self.assertEqual(saves[0][-3:],['broker','controller','database'])
            self.assertEqual(first['unique_image_layer_bytes'],1000)
            self.assertEqual(first['disk_gib'],1040/1024**3)
            self.assertEqual(first,second)
