"""Image import must honor the orbital deadline and fail before target startup."""
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.live_backend import LiveBackend


class ImageLoadTests(unittest.TestCase):
    def backend(self, remaining):
        backend = LiveBackend.__new__(LiveBackend)
        backend.root = Path('.')
        backend.fault = None
        backend.event = {'deadline_s': 1000}
        backend.clock = SimpleNamespace(orbital=lambda: 1000 - remaining)
        backend.check = lambda: None
        backend.measure = lambda name, operation: operation()
        backend.compose = SimpleNamespace(start=Mock())
        backend.target_started = False
        return backend

    def test_short_orbital_window_bounds_import_and_failure_prevents_startup(self):
        backend = self.backend(7)
        with patch('src.live_backend.subprocess.run', side_effect=subprocess.TimeoutExpired('docker load', 7)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                backend.start_target({'path': 'images.tar'})
        self.assertEqual(run.call_args.kwargs['timeout'], 7)
        self.assertFalse(backend.target_started)
        backend.compose.start.assert_not_called()

    def test_successful_slow_import_can_start_target(self):
        backend = self.backend(900)
        with patch('src.live_backend.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
            backend.start_target({'path': 'images.tar'})
        self.assertEqual(run.call_args.kwargs['timeout'], 600)
        backend.compose.start.assert_called_once_with('sat-b')

    def test_rejected_import_cannot_start_target(self):
        backend = self.backend(900)
        with patch('src.live_backend.subprocess.run', return_value=SimpleNamespace(returncode=1, stderr='invalid bundle')):
            with self.assertRaisesRegex(RuntimeError, 'invalid bundle'):
                backend.start_target({'path': 'images.tar'})
        backend.compose.start.assert_not_called()
