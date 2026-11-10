"""Loopback-only HTTP/SSE console over the shared durable job service.

Read endpoints serve the installed scenario, laboratory state, jobs (with an SSE event stream
that replays after a cursor), verifications, event experiments and registered downloads.
Commands (start or stop a job) require a same-origin request with the session CSRF token.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import mimetypes
import secrets
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from urllib.request import urlopen
from .artifacts import canonical_bytes
from .jobs import JobManager, BusyError, process_running
from .live_backend import http
from .storage import utc_now, read_json


TERMINAL = {'completed', 'failed', 'interrupted', 'recovery_required', 'recovered'}
ASSETS = {'/': 'web/index.html', '/experiment-state.js': 'web/experiment-state.js', '/app.js': 'web/app.js',
          '/orbit-view.js': 'web/orbit-view.js', '/mission.js': 'web/mission.js', '/stars.js': 'web/stars.js', '/style.css': 'web/style.css', '/tokens.css': 'web/tokens.css'}
FONTS = {'IBMPlexSans.ttf', 'STIXTwoText.ttf', 'IBMPlexMono-Regular.ttf', 'IBMPlexMono-Medium.ttf'}


def events_after(path, after):
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a concurrent append is retried
        if row['id'] > after:
            result.append(row)
    return result


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def scenario_profiles(root):
    """Summaries of offline scenario profiles built by tools/build_scenario.py (phase 0)."""
    profiles = []
    installed_name = None
    try:
        installed_name = _json(Path(root, 'config/scenario.json')).get('orbital', {}).get('constellation_profile')
    except (OSError, ValueError):
        pass
    for manifest_path in sorted(Path(root, 'artifacts/constellation-profiles').glob('*/manifest.json')):
        directory = manifest_path.parent
        try:
            manifest = _json(manifest_path)
            events = _json(directory / 'events.json')
            domain = _json(directory / 'domain.json')
            scenario = _json(directory / 'scenario.json')
        except (OSError, ValueError):
            profiles.append({'profile': directory.name, 'integrity': 'unreadable'})
            continue
        missing = [name for name, item in manifest.get('outputs', {}).items()
                   if not (directory / name).is_file() or (directory / name).stat().st_size != item.get('bytes')]
        keys = ('event_id', 'source', 'destination', 'hops', 'path', 'trigger_s', 'source_shadow_entry_s',
                'source_light_remaining_s', 'destination_light_remaining_s', 'light_gained_s', 'other_plane')
        profiles.append({'profile': manifest.get('profile', directory.name), 'created_utc': manifest.get('created_utc'),
            'installed': scenario.get('orbital', {}).get('constellation_profile') == installed_name,
            'integrity': 'changed' if missing else 'sizes_match', 'changed_files': missing,
            'summary': manifest.get('summary'), 'statistics': manifest.get('statistics'),
            'laser_terminals': scenario.get('fso', {}).get('laser_terminals'),
            'rate_bps': scenario.get('fso', {}).get('useful_throughput_bps'),
            'migration': scenario.get('migration'), 'experiment': scenario.get('experiment'),
            'alignment_hypothesis': scenario.get('fso', {}).get('alignment_hypothesis'),
            'event_parameters': events.get('parameters'), 'hops_histogram': events.get('hops_histogram'),
            'domain': {'plane_1': domain.get('plane_1'), 'plane_2': domain.get('plane_2')},
            'selected_events': [{key: event.get(key) for key in keys} for event in events.get('selected', [])]})
    return {'profiles': profiles}


def verifications(root):
    """Functional verifications (one Hot and one Cold on the first catalogue event), newest first."""
    rows = []
    for path in Path(root, 'results/comparisons').glob('compare-*/metadata.json'):
        try:
            rows.append(_json(path))
        except (OSError, ValueError):
            continue
    return sorted(rows, key=lambda row: row.get('created_utc') or '', reverse=True)


class Application:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.jobs = JobManager(self.root)
        self.sessions = {}
        self.lock = threading.RLock()
        self.registry = {}
        self.cached_status = None
        self.cached_at = 0
        self.orbit = None
        self.link_kinds = None

    def session(self, cookie):
        cookies = SimpleCookie()
        try:
            cookies.load(cookie or '')
        except Exception:
            pass
        identifier = cookies.get('tfs_session')
        identifier = identifier.value if identifier else None
        with self.lock:
            self.sessions = {key: value for key, value in self.sessions.items() if value['expires'] > time.monotonic()}
            if identifier not in self.sessions:
                identifier = secrets.token_urlsafe(32)
                self.sessions[identifier] = {'token': secrets.token_urlsafe(32), 'expires': time.monotonic() + 28800}
            return identifier, self.sessions[identifier]['token']

    def authorized(self, cookie, token):
        cookies = SimpleCookie()
        try:
            cookies.load(cookie or '')
        except Exception:
            return False
        identifier = cookies.get('tfs_session')
        session = self.sessions.get(identifier.value) if identifier else None
        return bool(session and session['expires'] > time.monotonic() and token
                    and hmac.compare_digest(session['token'], token))

    def status(self):
        with self.lock:
            if time.monotonic() - self.cached_at > 3:
                components = {}
                for name, port in [('mininet', 18090), ('p4_proxy', 18091)]:
                    try:
                        components[name] = {'reachable': True, 'data': http(port, timeout=2)}
                    except Exception as exc:
                        components[name] = {'reachable': False, 'error': str(exc)}
                for name, port in [('sat_a', 18080), ('sat_b', 18081)]:
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/healthz', timeout=1) as response:
                            components[name] = {'reachable': response.status == 200}
                    except Exception as exc:
                        components[name] = {'reachable': False, 'error': str(exc)}
                self.cached_status = components
                self.cached_at = time.monotonic()
        guard = read_json(self.jobs.guard) if self.jobs.guard.exists() else None
        active_job = None
        worker_alive = None
        if guard:
            try:
                active_job = self.jobs.get(guard['job_id'])
                worker_alive = process_running(guard.get('worker_pid', guard.get('launcher_pid')))
            except (OSError, ValueError):
                pass
        scenario = {}
        try:
            scenario = _json(self.root / 'config/scenario.json')
        except (OSError, ValueError):
            pass
        return {'timestamp_utc': utc_now(), 'components': self.cached_status, 'lock': guard,
                'job': active_job, 'worker_alive': worker_alive,
                'scenario': {'profile': scenario.get('orbital', {}).get('constellation_profile'),
                             'rate_bps': scenario.get('fso', {}).get('useful_throughput_bps'),
                             'migration': scenario.get('migration'), 'experiment': scenario.get('experiment'),
            'alignment_hypothesis': scenario.get('fso', {}).get('alignment_hypothesis'),
                             'events_ready': (self.root / 'config/migration_events.json').exists()}}

    def _orbit(self):
        if self.orbit is None:
            from .orbit import load_orbit
            self.orbit = load_orbit(self.root)
        return self.orbit

    def _kinds(self):
        if self.link_kinds is None:
            windows = _json(self.root / 'results/direct_link_windows.json')['windows']
            self.link_kinds = {tuple(sorted((row['sat_a'], row['sat_b']))): row.get('kind') for row in windows}
        return self.link_kinds

    def topology(self, tick=None, event_id=None):
        """Modeled geometry at one second: satellites, laser links, domain, service path, migration path."""
        from .fixture import service_endpoints
        from .orbit import shortest_paths
        from .starlink_scenario import argument_of_latitude
        orbit = self._orbit()
        catalogue = _json(self.root / 'config/migration_events.json') if (self.root / 'config/migration_events.json').exists() else {}
        event = None
        if event_id is not None:
            event = next((row for row in catalogue.get('events', []) if row['event_id'] == event_id), None)
            if event is None:
                raise ValueError('Unknown catalogue event')
            if tick is None:
                tick = event['trigger_s']
        tick = int(tick or 0)
        if not 0 <= tick < orbit.duration:
            raise ValueError('Orbital time outside the replay')
        positions = orbit.positions[tick:min(tick + 2, orbit.duration)]
        if len(positions) < 2:
            positions = orbit.positions[tick - 1:tick + 1]
        series = argument_of_latitude(positions)
        angles = series[-1 if tick == orbit.duration - 1 else 0]
        # Angular speed over the same two seconds: lets the console move satellites between samples.
        rates = (series[1] - series[0] + 180.0) % 360.0 - 180.0
        selection = {row['norad_id']: row for row in _json(self.root / 'config/selected_constellation.json')['satellites']}
        graph = orbit.graph(tick)
        kinds = self._kinds()
        fixture = _json(self.root / 'config/fixture.json')
        source, target = service_endpoints(fixture)
        lab = orbit.lab_graph(tick)
        distances = shortest_paths(lab, target) if target in lab else {}
        service = []
        if source in distances:
            node = source
            service = [node]
            while node != target:
                node = min((length + distances[n], n) for n, length in lab[node].items() if n in distances)[1]
                service.append(node)
        domain = set(orbit.domain or [])
        nodes = []
        for sid in orbit.ids:
            nodes.append({'norad': sid, 'plane': selection[sid]['plane'], 'phase_rank': selection[sid]['phase_rank'],
                          'in_domain': sid in domain, 'eclipsed': not orbit.operational(sid, tick),
                          'argument_of_latitude_deg': float(angles[orbit.index[sid]]),
                          'argument_of_latitude_rate_deg_s': float(rates[orbit.index[sid]]),
                          **orbit.illumination_window(sid, tick)})
        links = [[a, b, kinds.get((a, b))] for a in graph for b in graph[a] if a < b]
        return {'execution_kind': 'modeled-geometry', 'orbital_s': tick, 'nodes': nodes, 'links': links,
                'domain': sorted(domain), 'service_path': service,
                'event': event, 'migration_path': event['path'] if event else None,
                'selected_events': [row['event_id'] for row in catalogue.get('selected', [])]}

    def artifacts(self):
        paths = [self.root / name for name in ('results/environment.json', 'results/functional-gate.json')]
        paths.extend((self.root / 'results/comparisons').glob('compare-*/metadata.json'))
        for folder in (self.root / 'results/event-comparisons').glob('events-*'):
            paths.extend(p for p in folder.iterdir() if p.suffix in ('.json', '.csv'))
        for folder in (self.root / 'results/runs').glob('run-*'):
            paths.extend(p for p in folder.iterdir() if p.suffix in ('.json', '.jsonl', '.csv', '.log'))
            operation = folder / 'operation'
            if operation.exists():
                paths.extend(p for p in operation.iterdir() if p.suffix in ('.json', '.jsonl'))
            probe = self.root / 'results/lab' / folder.name
            if probe.exists():
                paths.extend(p for p in probe.iterdir() if p.suffix in ('.jsonl', '.log'))
        rows, registry = [], {}
        for path in paths:
            if not path.is_file():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(self.root):
                continue
            relative = resolved.relative_to(self.root).as_posix()
            identifier = hashlib.sha256(relative.encode()).hexdigest()[:32]
            registry[identifier] = resolved
            rows.append({'artifact_id': identifier, 'label': relative, 'bytes': resolved.stat().st_size,
                         'download_url': '/api/v1/artifacts/' + identifier})
        with self.lock:
            self.registry = registry
        return rows


def make_server(root, port=18092):
    application = Application(root)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def same_origin(self):
            port = self.server.server_address[1]
            allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            return (host in allowed and (origin is None or origin == 'http://' + host)
                    and self.headers.get('Sec-Fetch-Site') not in ('cross-site',))

        def send(self, data, status=200, media='application/json', headers=None):
            if not isinstance(data, bytes):
                data = canonical_bytes(data)
            self.send_response(status)
            self.send_header('Content-Type', media)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.same_origin():
                return self.send({'error': 'Same-origin access required'}, 403)
            try:
                self.get()
            except (ValueError, KeyError) as exc:
                self.send({'error': str(exc)}, 400)
            except FileNotFoundError:
                self.send({'error': 'Resource not found'}, 404)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self.send({'error': str(exc)}, 500)

        def stream(self, identifier, after):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            last_heartbeat = 0
            while True:
                for event in events_after(application.jobs.directory / identifier / 'events.jsonl', after):
                    payload = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
                    self.wfile.write(b'id: ' + str(event['id']).encode() + b'\ndata: ' + payload + b'\n\n')
                    after = event['id']
                job = application.jobs.get(identifier)
                if job['status'] in TERMINAL:
                    payload = json.dumps({'status': job['status']}, separators=(',', ':')).encode('utf-8')
                    self.wfile.write(b'event: end\ndata: ' + payload + b'\n\n')
                    self.wfile.flush()
                    return
                if time.monotonic() - last_heartbeat > 10:
                    self.wfile.write(b': heartbeat\n\n')
                    last_heartbeat = time.monotonic()
                self.wfile.flush()
                time.sleep(.25)

        def get(self):
            url = urlsplit(self.path)
            path, query = url.path, parse_qs(url.query)
            root = application.root
            if path == '/api/v1/session':
                identifier, token = application.session(self.headers.get('Cookie'))
                return self.send({'token': token}, headers={
                    'Set-Cookie': f'tfs_session={identifier}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'})
            if path == '/api/v1/state':
                return self.send(application.status())
            if path == '/api/v1/scenario-profiles':
                return self.send(scenario_profiles(root))
            if path == '/api/v1/verifications':
                return self.send({'verifications': verifications(root)})
            if path == '/api/v1/event-comparisons':
                from .event_comparison import list_comparisons
                running_since = None
                if application.jobs.guard.exists():
                    try:
                        holder = application.jobs.get(read_json(application.jobs.guard)['job_id'])
                        if holder.get('operation') == 'compare_events':
                            running_since = holder.get('created_utc', '')
                    except (OSError, ValueError, KeyError):
                        running_since = ''  # lock unreadable: never call an experiment stopped
                return self.send({'comparisons': list_comparisons(root, running_since)})
            if path == '/api/v1/topology':
                if set(query) - {'orbital_s', 'event'}:
                    raise ValueError('Unknown topology field')
                tick = query.get('orbital_s', [None])[0]
                return self.send(application.topology(int(tick) if tick is not None else None, query.get('event', [None])[0]))
            if path == '/api/v1/jobs':
                return self.send({'jobs': application.jobs.list()})
            if path.startswith('/api/v1/jobs/'):
                parts = path.split('/')
                identifier = parts[4]
                job = application.jobs.get(identifier)
                if len(parts) == 6 and parts[5] == 'events':
                    after = int(self.headers.get('Last-Event-ID', query.get('after', ['0'])[0]))
                    if after < 0:
                        raise ValueError('Invalid event cursor')
                    return self.stream(identifier, after)
                if len(parts) != 5:
                    raise ValueError('Unknown job resource')
                result = application.jobs.directory / identifier / 'result.json'
                if job.get('operation') in ('functional', 'compare_events') and result.exists():
                    job['result'] = _json(result)
                return self.send(job)
            if path == '/api/v1/artifacts':
                return self.send({'artifacts': application.artifacts()})
            if path.startswith('/api/v1/artifacts/'):
                identifier = path.split('/')[-1]
                application.artifacts()
                file = application.registry.get(identifier)
                if file is None:
                    raise FileNotFoundError(identifier)
                return self.send(file.read_bytes(), media=mimetypes.guess_type(file.name)[0] or 'application/octet-stream',
                                 headers={'Content-Disposition': 'attachment; filename="' + file.name + '"'})
            assets = dict(ASSETS)
            if path.startswith('/fonts/') and Path(path).name in FONTS:
                assets[path] = 'web/fonts/' + Path(path).name
            if path not in assets:
                raise FileNotFoundError(path)
            file = root / assets[path]
            return self.send(file.read_bytes(), media=mimetypes.guess_type(file.name)[0] or 'application/octet-stream')

        def do_POST(self):
            if not self.same_origin() or not application.authorized(self.headers.get('Cookie'), self.headers.get('X-CSRF-Token')):
                return self.send({'error': 'Valid same-origin session token required'}, 403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(size))
                if self.path == '/api/v1/jobs':
                    return self.send(application.jobs.start(body['operation'], body.get('parameters')), 202)
                parts = self.path.split('/')
                if len(parts) == 6 and parts[:4] == ['', 'api', 'v1', 'jobs'] and parts[5] == 'stop':
                    application.jobs.stop(parts[4])
                    return self.send({'interruption_requested': True}, 202)
                raise ValueError('Unknown command')
            except BusyError as exc:
                self.send({'error': str(exc)}, 409)
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self.send({'error': str(exc)}, 400)
            except Exception as exc:
                self.send({'error': str(exc)}, 500)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.application = application
    server.daemon_threads = True
    return server
