"""Real Docker/NBI/TCP backend. Geometry is modeled; operations are measured."""
from __future__ import annotations
import copy
import json
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from .artifacts import canonical_bytes
from .fixture import state, for_destination
from .orbit import shortest_paths
from .snapshot import apply_delta
from .storage import append_json, utc_now
from .tfs_adapter import TfsAdapter, route, service_intent
from .transport import Receiver, transfer
from .measurements import resources

WORKLOAD = ('nbiservice', 'serviceservice', 'deviceservice', 'pathcompservice',
            'pathcomp-backend', 'contextservice')


def http(port, path='/', body=None, timeout=30):
    request = Request(f'http://127.0.0.1:{port}{path}',
        data=None if body is None else canonical_bytes(body), headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
        return json.loads(data) if data else None


class Compose:
    def __init__(self, root): self.root = Path(root)

    def command(self, role, *arguments, timeout=180):
        if role not in ('sat-a', 'sat-b'): raise ValueError('Unknown laboratory host')
        command = ['docker', 'compose', '--env-file', f'deploy/{role}.env', '-p', role,
                   '-f', 'deploy/compose.yaml', '-f', 'deploy/lab-controller.yaml',
                   '-f', 'deploy/l2-patched.yaml', *arguments]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=timeout)
        if result.returncode: raise RuntimeError(result.stderr[-4000:] or result.stdout[-4000:])
        return result.stdout

    def start(self, role): self.command(role, 'up', '-d', '--wait', '--wait-timeout', '120', *WORKLOAD)
    def stop(self, role): self.command(role, 'stop', '-t', '10', *WORKLOAD)


class LiveBackend:
    def __init__(self, root, directory, event, rate, orbit, scenario, cancel=None, fault=None, notify=None):
        self.root, self.directory = Path(root), Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.event, self.rate, self.orbit, self.scenario = event, rate, orbit, scenario
        self.cancel = cancel or threading.Event()
        self.fault = fault
        self.notify = notify or (lambda event: None)
        self.compose = Compose(root)
        self.a, self.b = TfsAdapter('http://127.0.0.1:18080'), TfsAdapter('http://127.0.0.1:18081')
        self.fixture = json.loads((self.root/'config/fixture.json').read_text())
        self.fixture['controller_proxy'] = http(18091)['ipv4']
        self.clock = None
        self.lock = threading.RLock()
        self.paused_updates = False
        self.stopping = threading.Event()
        self.observer = None
        self.controller_worker = None
        self.resource_worker = None
        self.active_role = 'sat-a'
        self.receiver = None
        self.target_started = False
        self.source_snapshot = None
        self.pending_graph = None
        self.graph_signature = None
        self.telemetry_errors = []
        self.measurements = []
        self.probe_id = None
        self.transfer_attempts = 0
        self.started_utc = utc_now()

    @property
    def cancelled(self): return self.cancel.is_set()

    def check(self):
        if self.cancelled: raise InterruptedError('Job interrupted by user')
        if self.telemetry_errors: raise RuntimeError('Observer failed: '+self.telemetry_errors[-1])
        if self.clock and self.clock.orbital() >= self.event['deadline_s']:
            raise TimeoutError('Operational deadline reached')

    def measure(self, operation, function):
        started = time.monotonic()
        try: return function()
        finally:
            item = {'operation': operation, 'elapsed_s': time.monotonic()-started, 'timestamp_utc': utc_now()}
            self.measurements.append(item)
            append_json(self.directory/'operations.jsonl', item)

    def reset(self):
        self.compose.start('sat-a'); self.compose.start('sat-b')
        # API cleanup is only applied to the explicit migration perimeter.
        self.b.cleanup(self.b.export())
        self.a.cleanup(self.a.export())
        initial_tick = max(0, self.event['trigger_s']-30)
        graph = self.orbit.graph(initial_tick)
        self.set_links(graph)
        initial = state(self.fixture, graph)
        if 53913 not in shortest_paths(graph, 53848): initial['entities']['services'] = []
        self.a.restore(initial)
        self.source_snapshot = self.a.export()
        # Explicit reconciliation also restores authority after a proxy restart.
        http(18091, '/recover', {})
        http(18091, '/clear-standby', {})
        self.compose.stop('sat-b')
        self.target_started = False
        self.graph_signature = self.signature(graph)

    def signature(self, graph):
        return canonical_bytes(state(self.fixture, graph)['entities']['services']) + canonical_bytes(
            [(a,b) for a in graph for b in graph[a] if a < b])

    def start_observation(self, clock, run_id):
        self.clock = clock
        self.receiver = Receiver(self.directory/'received', progress_timeout_s=self.scenario['fso']['progress_timeout_s'])
        self.receiver.__enter__()
        self.probe_id = run_id
        http(18090, '/probes/start', {'run_id': run_id})
        self.observer = threading.Thread(target=self._observe, daemon=True)
        self.observer.start()
        self.controller_worker = threading.Thread(target=self._control_updates, daemon=True)
        self.controller_worker.start()
        def collect():
            while not self.stopping.is_set():
                try: append_json(self.directory/'resources.jsonl', resources(self.root))
                except Exception as exc:
                    append_json(self.directory/'resource-errors.jsonl', {'timestamp_utc': utc_now(), 'error': str(exc)})
                self.stopping.wait(5)
        self.resource_worker = threading.Thread(target=collect, daemon=True)
        self.resource_worker.start()

    def set_links(self, graph):
        pairs = [[a, b] for a in graph for b in graph[a] if a < b]
        http(18090, '/links', {'pairs': pairs})

    def _update_controller(self, graph, role=None):
        role = role or self.active_role
        adapter = self.a if role == 'sat-a' else self.b
        desired = state(self.fixture, graph, role)
        current = adapter.export()
        desired_service = desired['entities']['services'][0]
        path = 53913 in shortest_paths(graph, 53848)
        old_services = current['entities']['services']
        changed = not old_services or service_intent(old_services[0]) != service_intent(desired_service)
        if changed or not path:
            for row in old_services: adapter.request('DELETE', route('services', row))
        desired_links = {canonical_bytes(row['link_id']): row for row in desired['entities']['links']}
        current_links = {canonical_bytes(row['link_id']): row for row in current['entities']['links']}
        for key in current_links.keys()-desired_links.keys():
            adapter.request('DELETE', route('links', current_links[key]))
        for key in desired_links.keys()-current_links.keys():
            adapter.request('POST', '/links', {'links': [desired_links[key]]})
        for row in desired['entities']['topologies']:
            adapter.request('PUT', route('topologies', row), row)
        if path and changed:
            # Existing device configurations remain owned by TeraFlow.
            patch = copy.deepcopy(desired)
            patch['entities']['devices'] = []
            patch['entities']['links'] = []
            adapter.restore(patch)
        actual = adapter.export()['entities']
        wanted_services = [service_intent(row) for row in desired['entities']['services']] if path else []
        if sorted(canonical_bytes(service_intent(row)) for row in actual['services']) != sorted(map(canonical_bytes,wanted_services)):
            raise RuntimeError('Queued service intent did not reconcile')
        if sorted(canonical_bytes(row['link_id']) for row in actual['links']) != sorted(desired_links):
            raise RuntimeError('Queued links did not reconcile')

    def _control_updates(self):
        while not self.stopping.wait(.05):
            if self.paused_updates or self.pending_graph is None: continue
            with self.lock:
                if self.paused_updates or self.pending_graph is None: continue
                graph = self.pending_graph
                try:
                    self._update_controller(graph)
                    self.graph_signature = self.signature(graph)
                    if self.pending_graph is graph: self.pending_graph = None
                except Exception as exc:
                    self.telemetry_errors.append(str(exc)); return

    def _observe(self):
        previous = None
        next_heartbeat = 0
        while not self.stopping.is_set():
            tick = int(self.clock.orbital())
            if tick >= self.orbit.duration: return
            if tick == previous:
                self.stopping.wait(.05); continue
            previous = tick
            try:
                graph = self.orbit.graph(tick)
                self.set_links(graph)
                path = 53913 in shortest_paths(graph, 53848)
                links = [(a,b) for a in graph for b in graph[a] if a < b]
                append_json(self.directory/'geometry.jsonl', {'orbital_s': tick, 'unix_s': time.time(),
                    'service_path_available': path, 'links': links,
                    'eclipsed': [sid for sid in self.orbit.ids if not self.orbit.operational(sid, tick)]})
                signature = self.signature(graph)
                if signature != self.graph_signature:
                    self.pending_graph = graph
                if tick >= next_heartbeat:
                    status = {}
                    for role, port in [('sat-a',18080),('sat-b',18081)]:
                        try:
                            with urlopen(f'http://127.0.0.1:{port}/healthz', timeout=1) as response:
                                status[role] = response.status == 200
                        except Exception: status[role] = False
                    append_json(self.directory/'heartbeat.jsonl', {'orbital_s': tick, 'unix_s': time.time(), 'controllers': status})
                    append_json(self.directory/'authority.jsonl',{'orbital_s':tick,'unix_s':time.time(),
                        'proxy':http(18091,timeout=2)})
                    next_heartbeat = tick+5
            except Exception as exc:
                self.telemetry_errors.append(str(exc)); return

    def prepare_target(self):
        self.check()
        if self.target_started: raise RuntimeError('Target not clean after previous attempt')
        http(18091, '/clear-standby', {})

    def contact(self, tick):
        return self.orbit.contact(self.event['sat_a'], self.event['sat_b'], tick)

    def quiesce_source(self):
        with self.lock:
            self.paused_updates = True

    def export_source(self):
        with self.lock:
            self.source_snapshot = self.measure('snapshot', self.a.export)
            return self.source_snapshot

    def stop_source(self):
        self.quiesce_source()
        http(18091, '/freeze', {})
        self.measure('source_stop', lambda: self.compose.stop('sat-a'))

    def freeze_source(self):
        self.quiesce_source()
        self.measure('freeze', lambda: http(18091, '/freeze', {}))

    def transfer(self, path, event):
        self.transfer_attempts += 1
        started = time.monotonic()
        def link():
            if self.cancelled: return False
            if self.fault == 'fso_loss' and time.monotonic()-started > .2: return False
            return self.contact(self.clock.orbital())
        if self.fault == 'no_progress':
            # Real receiver remains connected but does not consume payload bytes.
            import socket
            server = socket.socket(); server.bind(('127.0.0.1',0)); server.listen(1)
            address = server.getsockname()
            def stall():
                connection, _ = server.accept()
                with connection: self.stopping.wait(self.scenario['fso']['progress_timeout_s']+2)
                server.close()
            threading.Thread(target=stall, daemon=True).start()
        else: address = self.receiver.address
        receipt = transfer(path, address, self.rate, link=link,
            deadline_monotonic=time.monotonic()+max(0,event['deadline_s']-self.clock.orbital()),
            progress_timeout_s=self.scenario['fso']['progress_timeout_s'],
            corrupt_checksum=self.fault == 'checksum')
        receipt['tcp_retransmissions'] = None
        receipt['tcp_retransmission_measurement'] = 'unavailable on host transport'
        return receipt

    def start_target(self, receipt):
        self.check()
        if self.fault == 'target_start': raise RuntimeError('Injected SAT-B startup failure')
        path = Path(receipt['path'])
        def load():
            # Docker Desktop may spend several minutes importing a verified
            # bundle even when its layers are already present locally.
            remaining = max(0, self.event['deadline_s'] - self.clock.orbital()) if self.clock else 600
            result = subprocess.run(['docker','load','-i',str(path)], cwd=self.root,
                                    capture_output=True, text=True, timeout=min(600, remaining))
            if result.returncode: raise RuntimeError(result.stderr)
        self.measure('image_load_shared_daemon', load)
        self.target_started = True
        self.measure('controller_startup', lambda: self.compose.start('sat-b'))

    def restore_target(self, initial):
        self.check()
        target = for_destination(initial, self.fixture)
        injection = 'services' if self.fault == 'restore_api' else None
        self.measure('api_restore', lambda: self.b.restore(target, inject_failure_at=injection))

    def apply_target_delta(self, initial, changes):
        final = for_destination(apply_delta(initial, changes), self.fixture)
        self.measure('delta_apply', lambda: self.b.reconcile(final))

    def verify_target(self, expected):
        self.check()
        target = for_destination(expected, self.fixture)
        return self.measure('api_verification', lambda: self.b.verify(target))

    def staged_ready(self):
        with self.lock:
            if self.paused_updates and self.pending_graph is not None:
                graph = self.pending_graph
                self.measure('queued_topology_apply', lambda: self._update_controller(graph, 'sat-b'))
                self.graph_signature = self.signature(graph)
                if self.pending_graph is graph: self.pending_graph = None
        status = http(18091)
        return all(row.get('standby_ready') and row['upstream_master'] for row in status['states'])

    def ack(self, **checks):
        self.check()
        http(18091, '/ready', checks)

    def cutover(self):
        self.check()
        with self.lock:
            # Physical changes continue during freeze. Reconcile queued intents
            # on standby before ownership can change.
            if not self.staged_ready(): raise RuntimeError('Standby not ready after queued topology')
            http(18091, '/ready', {'images': True, 'api': True})
            self.measure('cutover', lambda: http(18091, '/cutover', {}))
            self.active_role = 'sat-b'
            self.paused_updates = False

    def abort_target(self):
        http(18091, '/revoke', {})
        if self.target_started:
            try: self.b.cleanup(self.b.export())
            finally:
                self.compose.stop('sat-b')
                self.target_started = False

    def recover_source(self):
        if self.clock and self.clock.orbital() >= self.event['deadline_s']:
            raise RuntimeError('Source expired; controllers remain fenced')
        self.compose.start('sat-a')
        if self.source_snapshot is None: raise RuntimeError('No verified source snapshot available for recovery')
        self.a.restore(self.source_snapshot)
        http(18091, '/recover', {})
        self.active_role = 'sat-a'
        self.paused_updates = False

    def close(self):
        self.stopping.set()
        if self.observer: self.observer.join(timeout=40)
        if self.controller_worker: self.controller_worker.join(timeout=40)
        if self.resource_worker: self.resource_worker.join(timeout=25)
        if self.probe_id: http(18090, '/probes/stop', {})
        if self.probe_id:
            try:
                lines=subprocess.check_output(['docker','logs','--timestamps','--since',self.started_utc,'tfs-lab-p4-proxy-1'],
                    cwd=self.root,stderr=subprocess.STDOUT,text=True,timeout=20)
                (self.directory/'p4-proxy.log').write_text(lines,encoding='utf-8')
            except Exception as exc:
                append_json(self.directory/'resource-errors.jsonl',{'timestamp_utc':utc_now(),'error':'Proxy log capture: '+str(exc)})
        if self.receiver: self.receiver.__exit__(None,None,None)
        if self.observer and self.observer.is_alive(): raise RuntimeError('Observer did not stop safely')
        if self.controller_worker and self.controller_worker.is_alive(): raise RuntimeError('Controller worker did not stop safely')
