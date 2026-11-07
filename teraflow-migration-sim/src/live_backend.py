"""Real Docker/NBI/TCP backend. Geometry is modeled; operations are measured."""
from __future__ import annotations
import copy
import contextlib
import json
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from .artifacts import canonical_bytes
from .fixture import state, for_role, with_endpoint_rules, service_endpoints
from .orbit import lab_graph, shortest_paths
from .snapshot import apply_delta
from .storage import append_json, utc_now
from .tfs_adapter import TfsAdapter, route, service_intent
from .transport import Receiver, transfer
from .measurements import resources
from .deployment import compose_command, role_services
from .processes import run_process
from .probes import ping_observations, json_lines, summarize_ping, baseline_ready
from .preparation_budget import PreparationBudget

WORKLOAD = ('nbiservice', 'serviceservice', 'deviceservice', 'pathcompservice',
            'pathcomp-backend', 'contextservice')

SOURCE_STARTUP = (
    ('dependencies', 'Avvio dipendenze del controller sorgente', ('cockroachdb', 'nats', 'kafka')),
    ('context', 'Avvio servizio di contesto sorgente', ('contextservice',)),
    ('devices', 'Avvio gestione dispositivi sorgente', ('deviceservice',)),
    ('paths', 'Avvio calcolo percorsi sorgente', ('pathcomp-backend', 'pathcompservice')),
    ('services', 'Avvio gestione servizi sorgente', ('serviceservice',)),
    ('api', 'Attivazione API del controller sorgente', ('nbiservice',)),
)



def http(port, path='/', body=None, timeout=30):
    request = Request(f'http://127.0.0.1:{port}{path}',
        data=None if body is None else canonical_bytes(body), headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
        return json.loads(data) if data else None


class Compose:
    def __init__(self, root): self.root = Path(root); self.guard = None; self.remaining = None

    def command(self, role, *arguments, timeout=180):
        if role not in ('sat-a', 'sat-b'): raise ValueError('Unknown laboratory host')
        command = compose_command(*arguments)
        if self.guard: self.guard()
        if self.remaining: timeout = min(timeout, self.remaining())
        if timeout <= 0: raise TimeoutError('No budget left before Docker command')
        result = run_process(command, cwd=self.root, timeout=timeout, check=self.guard)
        if result.returncode: raise RuntimeError(result.stderr[-4000:] or result.stdout[-4000:])
        return result.stdout

    def start(self, role): self.command(role, 'up', '-d', '--wait', '--wait-timeout', '120', *role_services(role, WORKLOAD))
    def stop(self, role): self.command(role, 'stop', '-t', '10', *role_services(role, WORKLOAD))


class LiveBackend:
    source_slot = 'sat-a'
    target_slot = 'sat-b'
    recovery_mode = False
    preparation_deadline = None
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
        self.recovery_mode = False
        self.preparation_deadline = None
        self.preparation_budget = None
        self.proxy_generation = None
        self.event_context = {}
        self.attempt = 0
        self.received_images = []
        self.cutover_unix_s = None
        self.logical_host = event.get('sat_a')
        self.compose.guard, self.compose.remaining = self.check, self.remaining
        for adapter in (self.a, self.b):
            adapter.guard, adapter.remaining = self.check, self.remaining

    @property
    def source(self): return self.a if self.source_slot == 'sat-a' else self.b

    @property
    def target(self): return self.a if self.target_slot == 'sat-a' else self.b

    def remaining(self):
        if self.clock:
            reserve = 0 if self.recovery_mode else self.event.get('recovery_reserve_s', 0)
            deadline=self.event['deadline_s']-reserve
            if not self.recovery_mode: deadline=min(deadline,self.event.get('contact_end_s',deadline))
            return max(0, deadline - self.clock.orbital())
        if self.preparation_budget: return self.preparation_budget.remaining()
        if self.preparation_deadline: return max(0, self.preparation_deadline-time.monotonic())
        return 180

    def admin(self, path, *, recovery=False, **checks):
        if not recovery: self.check()
        body = {'source_slot': self.source_slot, 'target_slot': self.target_slot, **checks}
        if self.proxy_generation is not None: body['generation'] = self.proxy_generation
        result = http(18091, path, body, timeout=max(.1, min(30, self.remaining())))
        if 'generation' in result: self.proxy_generation = result['generation']
        return result

    @property
    def cancelled(self): return self.cancel.is_set()

    def check(self):
        if self.cancelled and not self.recovery_mode: raise InterruptedError('Job interrupted by user')
        if self.telemetry_errors and not self.recovery_mode: raise RuntimeError('Observer failed: '+self.telemetry_errors[-1])
        if self.remaining() <= 0:
            raise TimeoutError('Operational deadline reached')

    def measure(self, operation, function):
        started = time.monotonic()
        collector=getattr(self,'resource_collector',None)
        slot=self.source_slot if operation in ('snapshot','freeze','source_stop') else self.target_slot
        try:
            with collector.operation(operation,slot) if collector else contextlib.nullcontext():
                return function()
        finally:
            item = {'operation': operation, 'elapsed_s': time.monotonic()-started, 'timestamp_utc': utc_now()}
            self.measurements.append(item)
            append_json(self.directory/'operations.jsonl', item)

    def start_source(self):
        """Start the source in dependency order within the existing overall startup budget."""
        for name, label, services in SOURCE_STARTUP:
            self.check()
            started=time.monotonic()
            event={'phase':'source_startup','startup_stage':name,'label':label,
                   'controller_slot':self.source_slot,'phase_started_utc':utc_now(),**self.event_context}
            def publish(status, **extra):
                row={**event,'operation_status':status,'elapsed_s':time.monotonic()-started,**extra}
                append_json(self.directory/'source-startup.jsonl',{**row,'timestamp_utc':utc_now()})
                self.notify(row)
            publish('running')
            try:
                self.compose.command(self.source_slot,'up','-d','--wait','--wait-timeout','120',
                                     *role_services(self.source_slot,services))
                self.check()
            except Exception as exc:
                exc.startup_stage=name
                exc.startup_label=label
                publish('failed',error=str(exc))
                raise
            publish('completed')

    def wait_infrastructure(self):
        """Wait for both infrastructure endpoints within the current preparation budget."""
        fixture=getattr(self,'fixture',None)
        expected=len(fixture['emulator']['devices']) if fixture else len(self.orbit.ids)
        last={}
        previous=None
        def expired():
            detail='; '.join(name+': '+row['detail'] for name,row in last.items()) or 'nessuna risposta disponibile'
            error=TimeoutError('Infrastruttura non pronta entro il limite. '+detail)
            error.infrastructure_status=last
            return error
        def check():
            try:self.check()
            except TimeoutError as exc:raise expired() from exc
        while True:
            check()
            proxy=None
            for name,port in (('Mininet',18090),('Proxy P4',18091)):
                if self.remaining()<=0:raise expired()
                check()
                try:
                    data=http(port,timeout=min(2,self.remaining()))
                    if name=='Mininet':
                        count=data['switch_count']
                        ready=count==expected and data['switches_alive'] is True
                        detail=f'{count}/{expected} switch; '+('attivi' if data['switches_alive'] else 'non tutti attivi')
                    else:
                        states=data['states']
                        masters=sum(row.get('upstream_master') is True for row in states)
                        ready=len(states)==expected and masters==expected and isinstance(data.get('ipv4'),str) and bool(data['ipv4'])
                        detail=f'{masters}/{expected} connessioni agli switch confermate'
                        if not data.get('ipv4'):detail+='; indirizzo del proxy non disponibile'
                        proxy=data
                    last[name]={'ready':ready,'detail':detail}
                except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
                    last[name]={'ready':False,'detail':str(exc) or type(exc).__name__}
            if self.remaining()<=0:raise expired()
            check()
            ready=all(row['ready'] for row in last.values())
            if last!=previous:
                self.notify({'phase':'infrastructure_wait','label':'Attesa disponibilità Mininet e proxy P4',
                    'operation_status':'completed' if ready else 'running',
                    'detail':'; '.join(name+': '+row['detail'] for name,row in last.items()),
                    'infrastructure_status':copy.deepcopy(last),**self.event_context})
                previous=copy.deepcopy(last)
            if ready:return proxy
            if self.cancel.wait(min(1,self.remaining())):raise InterruptedError('Job interrupted by user')

    def reset(self, *, reuse_inventory=False):
        initial_tick = self.event.get('start_s', max(0, self.event['trigger_s']-30))
        self.initial_tick = initial_tick
        graph = lab_graph(self.orbit, initial_tick)
        def initial_state():
            document = state(self.fixture, graph)
            if not self.service_path(graph): document['entities']['services'] = []
            return document
        initial = initial_state()
        self.preparation_budget = PreparationBudget(self.directory, self.scenario, self.notify,
                                                    self.preparation_status, document=initial)
        stage = self.preparation_budget.stage
        with stage('infrastructure'):
            proxy=self.wait_infrastructure()
            self.fixture['controller_proxy'] = proxy['ipv4']
        with stage('stop_target'): self.compose.stop('sat-b')
        self.target_started = False
        if self.scenario.get('migration', {}).get('clean_target_store_before_trigger'):
            with stage('clean_target'): self.clean_target_store()
        with stage('start_source'): self.start_source()
        incremental = False
        if reuse_inventory:
            from .snapshot import identity, snapshot
            initial = initial_state()
            current = self.a.export()
            wanted = {identity('devices', row): row for row in initial['entities']['devices']}
            def connection(row):
                return {r.get('custom', {}).get('resource_key'): r
                        for r in row.get('device_config', {}).get('config_rules', [])
                        if r.get('custom', {}).get('resource_key', '').startswith('_connect/')}
            incremental = all(connection(row) == connection(wanted[identity('devices', row)])
                              for row in current['entities']['devices']
                              if identity('devices', row) in wanted)
            if incremental:
                # Recreate the service intent so its generated forwarding rules
                # cannot survive with a stale path. Keep the expensive devices.
                with stage('reset_service'):
                    self.a.cleanup(snapshot({'services': current['entities']['services']}))
            else:
                self.notify({'phase':'scenario_creation',
                             'label':'Connessioni dispositivi cambiate: ripristino completo necessario'})
        if not incremental:
            with stage('clean_source'): self.a.cleanup(self.a.export())
        with stage('restore_scenario'):
            self.set_links(graph)
            initial = initial_state()  # infrastructure resolved the proxy address
            def restoring(event):
                event = {**event, **self.event_context}
                append_json(self.directory/'restore-operations.jsonl', {**event,'timestamp_utc':utc_now()})
                self.notify(event)
            self.a.notify = restoring
            try:
                if incremental:
                    initial = with_endpoint_rules(initial)
                    self.a.reconcile(initial)
                else:
                    self.a.restore(initial)
                restoring({'phase':'restore_progress', 'counts':self.a.restore_progress,
                           'verification':'running'})
                self.source_snapshot = self.a.export()
                from .snapshot import identity
                mismatched = [kind for kind in ('contexts','topologies','devices','links','services')
                    if {identity(kind,row) for row in initial['entities'][kind]} !=
                       {identity(kind,row) for row in self.source_snapshot['entities'][kind]}]
                if mismatched:
                    raise RuntimeError('Initial inventory verification failed: '+str(mismatched))
                restoring({'phase':'restore_progress', 'counts':self.a.restore_progress,
                           'verification':'completed'})
            finally:
                self.a.notify = None
            from .storage import atomic_json
            atomic_json(self.directory/'prepared-snapshot.json', self.source_snapshot)
        # Explicit reconciliation also restores authority after a proxy restart.
        with stage('restore_authority'):
            self.admin('/recover')
            self.admin('/clear-standby')
        self.graph_signature = self.signature(graph)

    def preparation_status(self):
        """Bounded, read-only evidence even after the operation budget expires."""
        evidence = {}
        for name, port in (('mininet',18090), ('p4_proxy',18091)):
            try: evidence[name] = http(port, timeout=1)
            except Exception as exc: evidence[name] = {'error':str(exc)}
        result = run_process(compose_command('ps','--all','--format','json'), cwd=self.root, timeout=5)
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        evidence['containers'] = [{'name':row.get('Name'), 'state':row.get('State'),
                                  'health':row.get('Health'), 'service':row.get('Service')} for row in rows]
        return evidence

    def establish_baseline(self, identifier):
        """Fresh probe process, fixed preparation geometry; orbital clock not started."""
        if self.preparation_budget:
            with self.preparation_budget.stage('baseline'):
                result = self._establish_baseline(identifier)
            self.preparation_budget = None
            return result
        return self._establish_baseline(identifier)

    def _establish_baseline(self, identifier):
        probe_id = 'baseline-' + identifier
        directory = self.root/'results/lab'/probe_id
        started = time.time()
        last_progress = -1
        http(18090, '/probes/start', {'run_id': probe_id})
        try:
            while True:
                self.check()
                status = http(18091, timeout=min(2, self.remaining()))
                rows = ping_observations((directory/'ping.log').read_text(encoding='utf-8')) if (directory/'ping.log').exists() else []
                fresh = [row for row in rows if row['unix_s'] >= started]
                summary = summarize_ping(fresh)
                udp = list(json_lines(directory/'udp-received.jsonl'))
                elapsed = int(time.time()-started)
                if elapsed != last_progress:
                    self.notify({'phase':'baseline_check','fresh_ping_successes':summary['longest_consecutive_successes'],
                        'udp_packets':len(udp),'active_slot':status.get('active'),
                        'preparation_remaining_s':self.remaining(),**self.event_context})
                    last_progress=elapsed
                if baseline_ready(fresh,udp,status,started,self.source_slot,now=time.time()):
                    with urlopen(self.source.base_url.removesuffix('/tfs-api')+'/healthz', timeout=min(2, self.remaining())) as response:
                        if response.status != 200: raise RuntimeError('Source API not ready')
                    result = {'success': True, 'probe_id': probe_id, 'started_unix_s': started,
                              'verified_unix_s': time.time(), 'ping': summary, 'udp_received': len(udp),
                              'criteria': 'source_api+authority+10_fresh_consecutive_pings'}
                    from .storage import atomic_json
                    atomic_json(self.directory/'baseline.json', result)
                    self.preparation_deadline = None
                    return result
                if self.cancel.wait(.2): self.check()
        except Exception as exc:
            from .storage import atomic_json
            atomic_json(self.directory/'baseline.json', {'success':False,'probe_id':probe_id,
                'started_unix_s':started,'failure_reason':'Baseline API/P4/ping non valida: '+str(exc),'verified_unix_s':None,
                'last_ping':locals().get('summary'),'udp_received':len(locals().get('udp',[])),
                'last_authority':locals().get('status')})
            raise
        finally:
            http(18090, '/probes/stop', {})

    def verify_service(self, timeout_s=30, *, evidence_directory=None):
        """Confirm target ownership and fresh forwarding after the real cutover."""
        from .storage import atomic_json
        started = self.cutover_unix_s
        if started is None: raise RuntimeError('No confirmed cutover to verify')
        deadline = time.monotonic() + min(timeout_s, self.remaining(), self.orbit.duration-self.clock.orbital())
        evidence = {'success':False, 'cutover_unix_s':started, 'target_slot':self.target_slot,
                    'criteria':'target_api+authority+10_fresh_consecutive_pings'}
        try:
            while time.monotonic() < deadline:
                self.check()
                path = self.root/'results/lab'/self.probe_id/'ping.log'
                rows = ping_observations(path.read_text(encoding='utf-8')) if path.exists() else []
                status = http(18091, timeout=max(.1,min(2,self.remaining())))
                evidence['ping'] = summarize_ping([row for row in rows if row['unix_s'] >= started])
                evidence['active_slot'] = status.get('active')
                if baseline_ready(rows,[],status,started,self.target_slot,now=time.time()):
                    with urlopen(self.target.base_url.removesuffix('/tfs-api')+'/healthz',
                                 timeout=max(.1,min(2,self.remaining()))) as response:
                        if response.status != 200: raise RuntimeError('Target API not ready')
                    evidence.update(success=True,verified_unix_s=time.time())
                    self.notify({'phase':'service_verified',**evidence,**self.event_context})
                    return evidence
                if self.cancel.wait(.2): self.check()
            raise TimeoutError('Target service did not reach ten fresh consecutive pings after cutover')
        except Exception as exc:
            evidence['failure_reason'] = str(exc)
            raise
        finally:
            atomic_json((evidence_directory or self.directory)/'service-verification.json',evidence)

    def begin_attempt(self, attempt):
        if self.receiver:
            self.receiver.__exit__(None, None, None)
            self.discard_images()
        self.attempt = attempt
        base = self.directory/'migrations'/self.event_context['migration_id'] if 'migration_id' in self.event_context else self.directory
        self.receiver = Receiver(base/'attempts'/str(attempt)/'received', progress_timeout_s=self.scenario['fso']['progress_timeout_s'])
        self.receiver.__enter__()

    def set_migration(self, event, migration_id, simulation_id):
        self.event = event
        self.source_slot = self.active_role
        self.target_slot = 'sat-b' if self.source_slot=='sat-a' else 'sat-a'
        self.target_started = False
        self.event_context = {'simulation_id': simulation_id, 'migration_id': migration_id,
            'source_slot': self.source_slot, 'target_slot': self.target_slot,
            'source_satellite': event['sat_a'], 'target_satellite': event['sat_b']}

    def finish_handover(self):
        self.logical_host = self.event['sat_b']
        self.recovery_mode = True
        try: self.compose.stop(self.source_slot)
        finally: self.recovery_mode = False
        self.discard_images()

    def discard_images(self):
        from .storage import atomic_json
        if self.receiver:
            atomic_json(self.receiver.directory.parent/'receiver-receipts.json',self.receiver.receipts)
            self.received_images.extend(Path(row['path']) for row in self.receiver.receipts if Path(row['path']).suffix=='.tar')
        for path in self.received_images:
            if path.resolve().is_relative_to(self.directory.resolve()): path.unlink(missing_ok=True)
        self.received_images.clear()

    def signature(self, graph):
        return canonical_bytes(state(self.fixture, graph)['entities']['services']) + canonical_bytes(
            [(a,b) for a in graph for b in graph[a] if a < b])

    def start_observation(self, clock, run_id):
        self.clock = clock
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
        path = self.service_path(graph)
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
                    collector=getattr(self,'resource_collector',None)
                    with collector.operation('topology_update',self.active_role) if collector else contextlib.nullcontext():
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
                graph = lab_graph(self.orbit, tick)
                self.set_links(graph)
                path = self.service_path(graph)
                links = [(a,b) for a in graph for b in graph[a] if a < b]
                forwarding=None
                probe=self.root/'results/lab'/self.probe_id/'ping.log'
                if probe.exists():
                    with probe.open('rb') as handle:
                        handle.seek(max(0,probe.stat().st_size-4096))
                        samples=ping_observations(handle.read().decode(errors='replace'))
                    if samples and time.time()-samples[-1]['unix_s'] <= 2: forwarding=samples[-1]['success']
                self.service_status={'orbital_s':tick,'unix_s':time.time(),
                    'geometric_path_available':path,'forwarding_observed':forwarding,
                    'active_slot':self.active_role,'origin':'geometry modeled, forwarding measured by ping'}
                append_json(self.directory/'geometry.jsonl', {'orbital_s': tick, 'unix_s': time.time(),
                    'controller_satellite': self.logical_host, 'active_slot': self.active_role,
                    'service_path_available': path, 'forwarding_observed':forwarding, 'links': links,
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

    def clean_target_store(self):
        """A real destination satellite holds no state from earlier trials. Remove the laboratory
        residue from the stopped target's Context database before the trigger, so that the
        measured perimeter cleanup only verifies an empty destination."""
        from .storage import atomic_json
        role = self.target_slot
        service = role + '-contextservice'
        script = self.root/'tools/tfs_context_cleanup.py'
        self.compose.command(role, 'up', '-d', '--no-deps', '--wait', '--wait-timeout', '60', service, timeout=90)
        try:
            container = self.compose.command(role, 'ps', '-q', service, timeout=30).strip()
            if not container: raise RuntimeError('Target context service not running')
            result = None
            for command in (['docker', 'cp', str(script), container+':/tmp/tfs_context_cleanup.py'],
                            ['docker', 'exec', '-e', 'PYTHONPATH=/var/teraflow', '-w', '/var/teraflow', container,
                             'python', '/tmp/tfs_context_cleanup.py', '--remove']):
                result = run_process(command, cwd=self.root, timeout=min(120, self.remaining()), check=self.check)
                if result.returncode: raise RuntimeError((result.stderr or result.stdout)[-2000:])
            report = json.loads(result.stdout.strip().splitlines()[-1])
            if report.get('after', {}).get('devices') or report.get('after', {}).get('links'):
                raise RuntimeError('Target context still holds laboratory inventory after cleanup')
            atomic_json(self.directory/'target-store-cleanup.json', report)
            self.target_store_cleanup = report
        finally:
            self.compose.command(role, 'stop', '-t', '10', service, timeout=60)

    def prepare_target(self):
        self.check()
        if self.target_started: raise RuntimeError('Target not clean after previous attempt')
        self.admin('/clear-standby')

    def contact(self, tick):
        method = getattr(self.orbit, 'migration_link', self.orbit.contact)
        return method(self.event['sat_a'], self.event['sat_b'], tick)

    def service_path(self, graph):
        source, target = service_endpoints(self.fixture)
        return source in graph and target in shortest_paths(graph, source)

    def quiesce_source(self):
        with self.lock:
            self.paused_updates = True

    def export_source(self):
        with self.lock:
            self.source_snapshot = self.measure('snapshot', self.source.export)
            return self.source_snapshot

    def stop_source(self):
        self.quiesce_source()
        self.admin('/freeze')
        self.measure('source_stop', lambda: self.compose.stop(self.source_slot))

    def freeze_source(self):
        self.quiesce_source()
        self.measure('freeze', lambda: self.admin('/freeze'))

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
            deadline_monotonic=time.monotonic()+self.remaining(),
            progress_timeout_s=self.scenario['fso']['progress_timeout_s'],
            corrupt_checksum=self.fault == 'checksum')
        receipt['tcp_retransmissions'] = None
        receipt['tcp_retransmission_measurement'] = 'unavailable on host transport'
        if Path(path).suffix == '.tar': self.received_images.append(Path(receipt['path']))
        return receipt

    def start_target(self, receipt):
        self.check()
        if self.fault == 'target_start': raise RuntimeError('Injected SAT-B startup failure')
        if receipt.get('mode') == 'software-on-board':
            # Images are part of the satellite's installed software: nothing to import.
            self.target_started = True
            self.measure('controller_startup', lambda: self.compose.start(self.target_slot))
            self.measure('target_perimeter_cleanup', lambda: self.target.cleanup(self.target.export()))
            return
        path = Path(receipt['path'])
        def load():
            # Docker Desktop may spend several minutes importing a verified
            # bundle even when its layers are already present locally.
            remaining = max(0, self.event['deadline_s'] - self.clock.orbital()) if self.clock else 600
            result = run_process(['docker','load','-i',str(path)], cwd=self.root,
                                 timeout=min(600, self.remaining()), check=self.check)
            if result.returncode: raise RuntimeError(result.stderr)
        self.measure('image_load_shared_daemon', load)
        self.check()
        self.target_started = True
        self.measure('controller_startup', lambda: self.compose.start(self.target_slot))
        self.measure('target_perimeter_cleanup', lambda: self.target.cleanup(self.target.export()))

    def restore_target(self, initial):
        self.check()
        target = for_role(initial, self.fixture, self.target_slot)
        injection = 'services' if self.fault == 'restore_api' else None
        self.measure('api_restore', lambda: self.target.restore(target, inject_failure_at=injection))

    def apply_target_delta(self, initial, changes):
        final = for_role(apply_delta(initial, changes), self.fixture, self.target_slot)
        self.measure('delta_apply', lambda: self.target.reconcile(final))

    def verify_target(self, expected):
        self.check()
        target = for_role(expected, self.fixture, self.target_slot)
        return self.measure('api_verification', lambda: self.target.verify(target))

    def staged_ready(self):
        with self.lock:
            if self.paused_updates and self.pending_graph is not None:
                graph = self.pending_graph
                self.measure('queued_topology_apply', lambda: self._update_controller(graph, self.target_slot))
                self.graph_signature = self.signature(graph)
                if self.pending_graph is graph: self.pending_graph = None
        status = http(18091)
        return all(row.get('ready_by_slot', {}).get(self.target_slot, row.get('standby_ready') if self.target_slot=='sat-b' else False)
                   and row['upstream_master'] for row in status['states'])

    def ack(self, **checks):
        self.check()
        self.admin('/ready', **checks)

    def cutover(self):
        self.check()
        with self.lock:
            # Physical changes continue during freeze. Reconcile queued intents
            # on standby before ownership can change.
            if not self.staged_ready(): raise RuntimeError('Standby not ready after queued topology')
            self.admin('/ready', images=True, api=True)
            self.measure('cutover', lambda: self.admin('/cutover'))
            self.cutover_unix_s = time.time()
            self.active_role = self.target_slot
            self.logical_host = self.event['sat_b']
            self.paused_updates = False

    def abort_target(self):
        self.recovery_mode = True
        # Fencing must be attempted even if the normal operation deadline expired.
        result = http(18091, '/revoke', {})
        self.proxy_generation = result.get('generation')
        # Stop first: even an expired API cleanup must never leave the revoked
        # workload running. Preparation of the next attempt clears API state.
        if self.target_started:
            guard, remaining = self.compose.guard, self.compose.remaining
            self.compose.guard = self.compose.remaining = None
            try: self.compose.stop(self.target_slot)
            finally: self.compose.guard, self.compose.remaining = guard, remaining
            self.target_started = False

    def recover_source(self):
        if self.clock and self.clock.orbital() >= self.event['deadline_s']:
            raise RuntimeError('Source expired; controllers remain fenced')
        self.recovery_mode = True
        try:
            self.compose.start(self.source_slot)
            if self.source_snapshot is None: raise RuntimeError('No verified source snapshot available for recovery')
            self.source.reconcile(self.source_snapshot)
            self.admin('/recover', recovery=True)
            self.active_role = self.source_slot
            self.paused_updates = False
        finally: self.recovery_mode = False

    def shutdown(self):
        try: self.notify({'phase':'cleanup','label':'Messa in sicurezza del laboratorio'})
        except OSError: pass
        self.recovery_mode = True
        self.preparation_deadline = None
        self.preparation_budget = None
        errors = []
        self.stopping.set()
        try: http(18091, '/revoke', {})
        except Exception as exc: errors.append(str(exc))
        try:
            self.close()
        except Exception as exc: errors.append(str(exc))
        self.compose.guard = None; self.compose.remaining = None
        for slot in ('sat-a', 'sat-b'):
            try: self.compose.stop(slot)
            except Exception as exc: errors.append(str(exc))
        try:
            status = http(18091)
            if status.get('active') is not None: errors.append('P4 authority remains active after fencing')
            for slot in ('sat-a', 'sat-b'):
                if self.compose.command(slot, 'ps', '--status', 'running', '-q', *role_services(slot, WORKLOAD)).strip():
                    errors.append('Controller workload still running: '+slot)
        except Exception as exc: errors.append('Cleanup verification: '+str(exc))
        if errors: raise RuntimeError('; '.join(errors))
        try: self.notify({'phase':'cleanup_verified','label':'Autorità revocata e controller arrestati: verifica conclusa'})
        except OSError: pass

    def close(self):
        self.stopping.set()
        if self.observer: self.observer.join(timeout=40)
        if self.controller_worker: self.controller_worker.join(timeout=40)
        if self.resource_worker: self.resource_worker.join(timeout=25)
        if self.probe_id: http(18090, '/probes/stop', {})
        if self.probe_id:
            try:
                lines=subprocess.check_output(['docker','logs','--timestamps','--since',self.started_utc,'teraflow-p4-proxy-1'],
                    cwd=self.root,stderr=subprocess.STDOUT,text=True,timeout=20)
                (self.directory/'p4-proxy.log').write_text(lines,encoding='utf-8')
            except Exception as exc:
                append_json(self.directory/'resource-errors.jsonl',{'timestamp_utc':utc_now(),'error':'Proxy log capture: '+str(exc)})
        if self.receiver: self.receiver.__exit__(None,None,None)
        self.discard_images()
        if self.observer and self.observer.is_alive(): raise RuntimeError('Observer did not stop safely')
        if self.controller_worker and self.controller_worker.is_alive(): raise RuntimeError('Controller worker did not stop safely')
