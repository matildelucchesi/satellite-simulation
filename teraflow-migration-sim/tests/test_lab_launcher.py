import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import lab
from src.deployment import VOLUMES, compose_command
from tools.stack import UP_ARGUMENTS


class LabLauncherTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / 'results/jobs').mkdir(parents=True)

    def tearDown(self):
        self.directory.cleanup()

    def lock(self):
        (self.root / lab.LOCK).write_text('{}', encoding='utf-8')

    def test_start_refuses_without_docker_and_does_not_serve(self):
        with mock.patch.object(lab, 'docker_ready', return_value=False), \
                mock.patch.object(lab.subprocess, 'call') as call, \
                mock.patch.object(lab, 'serve_console') as serve:
            self.assertEqual(lab.main(['start'], root=self.root), 1)
        call.assert_not_called()
        serve.assert_not_called()

    def test_start_brings_stack_up_then_serves_console(self):
        with mock.patch.object(lab, 'docker_ready', return_value=True), \
                mock.patch.object(lab.subprocess, 'run') as run, \
                mock.patch.object(lab.subprocess, 'call', return_value=0) as call, \
                mock.patch.object(lab, 'serve_console', return_value=0) as serve:
            self.assertEqual(lab.main(['start'], root=self.root), 0)
        self.assertEqual([c.args[0][-1] for c in run.call_args_list], list(VOLUMES))
        call.assert_called_once_with(compose_command(*UP_ARGUMENTS), cwd=self.root)
        serve.assert_called_once_with(self.root, True)

    def test_failed_stack_start_does_not_serve_console(self):
        with mock.patch.object(lab, 'docker_ready', return_value=True), \
                mock.patch.object(lab.subprocess, 'run'), \
                mock.patch.object(lab.subprocess, 'call', return_value=3), \
                mock.patch.object(lab, 'serve_console') as serve:
            self.assertEqual(lab.main(['start'], root=self.root), 3)
        serve.assert_not_called()

    def test_lock_leaves_stack_untouched_but_serves_console(self):
        self.lock()
        with mock.patch.object(lab, 'docker_ready', return_value=True), \
                mock.patch.object(lab.subprocess, 'run') as run, \
                mock.patch.object(lab.subprocess, 'call') as call, \
                mock.patch.object(lab, 'serve_console', return_value=0) as serve:
            self.assertEqual(lab.main(['start', '--no-browser'], root=self.root), 0)
        run.assert_not_called()
        call.assert_not_called()
        serve.assert_called_once_with(self.root, False)

    def test_no_stack_skips_docker(self):
        with mock.patch.object(lab, 'docker_ready') as ready, \
                mock.patch.object(lab, 'serve_console', return_value=0) as serve:
            self.assertEqual(lab.main(['start', '--no-stack'], root=self.root), 0)
        ready.assert_not_called()
        serve.assert_called_once_with(self.root, True)

    def test_running_console_is_reused_and_browser_opened(self):
        with mock.patch.object(lab, 'console_running', return_value=True), \
                mock.patch.object(lab.webbrowser, 'open') as browser, \
                mock.patch('src.web.make_server') as make_server:
            self.assertEqual(lab.serve_console(self.root, True), 0)
        browser.assert_called_once_with(lab.URL)
        make_server.assert_not_called()

    def test_stop_respects_lock(self):
        self.lock()
        with mock.patch.object(lab.subprocess, 'call') as call:
            self.assertEqual(lab.main(['stop'], root=self.root), 1)
        call.assert_not_called()

    def test_stop_without_lock_stops_compose_group(self):
        with mock.patch.object(lab.subprocess, 'call', return_value=0) as call:
            self.assertEqual(lab.main(['stop'], root=self.root), 0)
        call.assert_called_once_with(compose_command('stop'), cwd=self.root)

    def test_docker_ready_requires_server_version(self):
        result = mock.Mock(returncode=0, stdout='\n')
        with mock.patch.object(lab.subprocess, 'run', return_value=result):
            self.assertFalse(lab.docker_ready())
        result.stdout = '27.3.1\n'
        with mock.patch.object(lab.subprocess, 'run', return_value=result):
            self.assertTrue(lab.docker_ready())
        with mock.patch.object(lab.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertFalse(lab.docker_ready())


if __name__ == '__main__':
    unittest.main()
