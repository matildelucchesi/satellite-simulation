import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

from src.storage import append_json, atomic_json
from src.web import make_server


class LocalWebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = make_server(self.root, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def get(self, path):
        with urlopen(self.url + path, timeout=5) as response:
            return json.load(response)

    def session(self):
        with urlopen(self.url + '/api/v1/session', timeout=5) as response:
            return json.load(response)['token'], response.headers['Set-Cookie'].split(';')[0]

    def command(self, token=None, cookie=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-CSRF-Token'] = token
        if cookie:
            headers['Cookie'] = cookie
        if origin:
            headers['Origin'] = origin
        request = Request(self.url + '/api/v1/jobs', data=b'{"operation":"functional"}', headers=headers)
        return urlopen(request, timeout=5)

    def test_commands_require_session_and_same_origin(self):
        token, cookie = self.session()
        for args in ({}, {'token': token}, {'token': token, 'cookie': cookie, 'origin': 'https://foreign.example'}):
            with self.assertRaises(HTTPError) as caught:
                self.command(**args)
            self.assertEqual(caught.exception.code, 403)
        with patch.object(self.server.application.jobs, 'start', return_value={'job_id': 'example'}) as start:
            with self.command(token, cookie, self.url) as response:
                self.assertEqual(response.status, 202)
            start.assert_called_once_with('functional', None)

    def test_host_header_rebinding_is_rejected(self):
        request = Request(self.url + '/api/v1/session', headers={'Host': 'foreign.example'})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 403)

    def test_dead_worker_is_exposed_without_releasing_the_lab_lock(self):
        app = self.server.application
        identifier = 'job-' + 'e' * 32
        atomic_json(self.root / 'config/scenario.json', {'orbital': {'constellation_profile': 'p'}, 'fso': {'useful_throughput_bps': [1]}})
        atomic_json(app.jobs.guard, {'job_id': identifier, 'worker_pid': 999999})
        atomic_json(app.jobs.directory / identifier / 'job.json', {'job_id': identifier, 'status': 'running'})
        app.cached_status = {}
        app.cached_at = time.monotonic()
        with patch('src.web.process_running', return_value=False):
            status = app.status()
        self.assertIs(status['worker_alive'], False)
        self.assertEqual(status['lock']['job_id'], identifier)
        self.assertEqual(status['job']['status'], 'running')
        self.assertEqual(status['scenario']['profile'], 'p')
        self.assertFalse(status['scenario']['events_ready'])
        self.assertTrue(app.jobs.guard.exists())

    def test_sse_reconnect_replays_only_events_after_cursor(self):
        identifier = 'job-' + 'a' * 32
        directory = self.root / 'results/jobs' / identifier
        atomic_json(directory / 'job.json', {'job_id': identifier, 'status': 'completed'})
        for index in range(1, 4):
            append_json(directory / 'events.jsonl', {'id': index, 'phase': 'test', 'timestamp_utc': '2026-10-08T00:00:00+00:00'})
        request = Request(self.url + '/api/v1/jobs/' + identifier + '/events', headers={'Last-Event-ID': '1'})
        with urlopen(request, timeout=5) as response:
            body = response.read().decode()
        self.assertNotIn('id: 1\n', body)
        self.assertIn('id: 2\n', body)
        self.assertIn('event: end\n', body)
        payloads = [json.loads(line[6:]) for line in body.splitlines() if line.startswith('data: ')]
        self.assertEqual([row['id'] for row in payloads[:-1]], [2, 3])
        self.assertEqual(payloads[-1], {'status': 'completed'})

    def test_job_exposes_its_own_saved_result(self):
        identifier = 'job-' + 'a' * 32
        directory = self.root / 'results/jobs' / identifier
        atomic_json(directory / 'job.json', {'job_id': identifier, 'operation': 'compare_events', 'status': 'completed'})
        atomic_json(directory / 'result.json', {'comparison_id': 'events-one', 'complete': True})
        self.assertEqual(self.get('/api/v1/jobs/' + identifier)['result']['comparison_id'], 'events-one')

    def test_verifications_and_event_comparisons_are_listed_newest_first(self):
        atomic_json(self.root / 'results/comparisons/compare-a/metadata.json', {'comparison_id': 'compare-a', 'created_utc': '2026-11-01T00:00:00+00:00'})
        atomic_json(self.root / 'results/comparisons/compare-b/metadata.json', {'comparison_id': 'compare-b', 'created_utc': '2026-11-02T00:00:00+00:00'})
        self.assertEqual([row['comparison_id'] for row in self.get('/api/v1/verifications')['verifications']], ['compare-b', 'compare-a'])
        atomic_json(self.root / 'results/event-comparisons/events-x/metadata.json', {'comparison_id': 'events-x', 'events': []})
        self.assertEqual(self.get('/api/v1/event-comparisons')['comparisons'][0]['comparison_id'], 'events-x')

    def test_downloads_only_registered_artifacts(self):
        atomic_json(self.root / 'results/event-comparisons/events-x/metadata.json', {'complete': False})
        (self.root / 'results/event-comparisons/events-x/summary.csv').write_text('a\n')
        atomic_json(self.root / 'results/campaign.json', {'legacy': True})
        rows = self.get('/api/v1/artifacts')['artifacts']
        self.assertEqual(sorted(row['label'] for row in rows),
                         ['results/event-comparisons/events-x/metadata.json', 'results/event-comparisons/events-x/summary.csv'])
        with urlopen(self.url + rows[0]['download_url'], timeout=5) as response:
            self.assertIn('attachment', response.headers['Content-Disposition'])
        for path in ('/api/v1/artifacts/../../config/scenario.json', '/../../secret', '/api/v1/artifacts/unregistered'):
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.url + path, timeout=5)
            self.assertEqual(caught.exception.code, 404)

    def test_topology_for_a_catalogue_event(self):
        ids = [1, 2, 3, 4]
        ticks = 120
        theta = np.radians([0, 10, 20, 30])
        positions = np.zeros((ticks, 4, 3))
        inclination = np.radians(53.0)
        for column, angle in enumerate(theta):
            phase = angle + 1e-3 * np.arange(ticks)
            positions[:, column] = 6841 * np.stack([np.cos(phase), np.sin(phase) * np.cos(inclination), np.sin(phase) * np.sin(inclination)], -1)
        (self.root / 'artifacts/orbit').mkdir(parents=True)
        np.savez_compressed(self.root / 'artifacts/orbit/replay.npz', ids=np.array(ids), positions=positions, eclipsed=np.zeros((ticks, 4), dtype=bool))
        links = [{'sat_a': a, 'sat_b': b, 'start_s': 0, 'end_s': ticks, 'kind': 'intra'} for a, b in ((1, 2), (2, 3), (3, 4))]
        atomic_json(self.root / 'results/direct_link_windows.json', {'windows': links})
        atomic_json(self.root / 'config/scenario.json', {'fso': {'laser_terminals': {'intra_plane': 2}, 'max_range_km': 1700}})
        atomic_json(self.root / 'config/domain.json', {'plane_1': [1, 2, 3], 'plane_2': []})
        atomic_json(self.root / 'config/selected_constellation.json', {'satellites': [{'norad_id': sid, 'plane': 1, 'phase_rank': sid} for sid in ids]})
        atomic_json(self.root / 'config/fixture.json', {'emulator': {'hosts': [{'satellite': 1}, {'satellite': 3}]}})
        event = {'event_id': '1-50', 'source': 1, 'destination': 4, 'path': [1, 2, 3, 4], 'trigger_s': 50, 'hops': 3}
        atomic_json(self.root / 'config/migration_events.json', {'selected': [event], 'events': [event]})
        topology = self.get('/api/v1/topology?event=1-50')
        self.assertEqual(topology['orbital_s'], 50)
        self.assertEqual(topology['service_path'], [1, 2, 3])
        self.assertEqual(topology['migration_path'], [1, 2, 3, 4])
        self.assertEqual(topology['domain'], [1, 2, 3])
        self.assertEqual(sorted(tuple(link[:2]) for link in topology['links']), [(1, 2), (2, 3), (3, 4)])
        self.assertEqual([node['in_domain'] for node in topology['nodes']], [True, True, True, False])
        self.assertAlmostEqual(topology['nodes'][1]['argument_of_latitude_deg'], 10 + np.degrees(50e-3), places=3)
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url + '/api/v1/topology?event=missing', timeout=5)
        self.assertEqual(caught.exception.code, 400)

    def test_console_serves_the_three_pages_and_scripts(self):
        source = Path(__file__).parents[1] / 'web'
        (self.root / 'web').mkdir()
        for name in ('index.html', 'app.js', 'orbit-view.js', 'experiment-state.js', 'style.css', 'tokens.css'):
            (self.root / 'web' / name).write_bytes((source / name).read_bytes())
        with urlopen(self.url + '/', timeout=5) as response:
            document = response.read().decode('utf-8')
        for identifier in ('page-scenario', 'page-experiment', 'page-results', 'id="orbit"', 'id="start"', 'id="verify"', 'id="timeline"'):
            self.assertIn(identifier, document)
        for legacy in ('channel-rate', 'common-base', 'Crea scenario iniziale', 'live-progress'):
            self.assertNotIn(legacy, document)
        for asset in ('app.js', 'orbit-view.js', 'experiment-state.js', 'style.css', 'tokens.css'):
            with urlopen(self.url + '/' + asset, timeout=5) as response:
                self.assertEqual(response.status, 200)
        for legacy in ('/api/v1/continuous-comparisons', '/api/v1/common-base', '/api/v1/simulations'):
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.url + legacy, timeout=5)
            self.assertEqual(caught.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
