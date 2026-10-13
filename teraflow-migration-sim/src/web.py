"""Loopback-only HTTP/SSE facade over the shared durable job service."""
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
from urllib.parse import urlsplit,parse_qs
from .artifacts import canonical_bytes
from .jobs import JobManager, BusyError, process_running
from .live_backend import http
from .probes import json_lines
from .storage import atomic_json, utc_now


TERMINAL={'completed','failed','interrupted','recovery_required','recovered'}


def run_directory(root,identifier):
    if len(identifier)!=36 or not identifier.startswith('run-') or any(c not in '0123456789abcdef' for c in identifier[4:]):
        raise ValueError('Invalid run identifier')
    directory=root/'results/runs'/identifier
    if not (directory/'inputs.json').is_file():raise FileNotFoundError(identifier)
    return directory


def events_after(path,after):
    if not path.exists():return []
    result=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        try:row=json.loads(line)
        except json.JSONDecodeError:continue # a concurrent append is retried
        if row['id']>after:result.append(row)
    return result


class Application:
    def __init__(self,root):
        self.root=Path(root).resolve();self.jobs=JobManager(self.root)
        self.sessions={};self.lock=threading.RLock();self.registry={}
        self.cached_status=None;self.cached_at=0
        self.orbit=None

    def session(self,cookie):
        cookies=SimpleCookie()
        try:cookies.load(cookie or '')
        except Exception:pass
        identifier=cookies.get('tfs_session')
        identifier=identifier.value if identifier else None
        with self.lock:
            self.sessions={key:value for key,value in self.sessions.items() if value['expires']>time.monotonic()}
            if identifier not in self.sessions:
                identifier=secrets.token_urlsafe(32)
                self.sessions[identifier]={'token':secrets.token_urlsafe(32),'expires':time.monotonic()+28800}
            return identifier,self.sessions[identifier]['token']

    def authorized(self,cookie,token):
        cookies=SimpleCookie()
        try:cookies.load(cookie or '')
        except Exception:return False
        identifier=cookies.get('tfs_session')
        session=self.sessions.get(identifier.value) if identifier else None
        return bool(session and session['expires']>time.monotonic() and token
                    and hmac.compare_digest(session['token'],token))

    def status(self):
        with self.lock:
            if time.monotonic()-self.cached_at>3:
                components={}
                for name,port in [('mininet',18090),('p4_proxy',18091)]:
                    try:components[name]={'reachable':True,'data':http(port,timeout=2)}
                    except Exception as exc:components[name]={'reachable':False,'error':str(exc)}
                from urllib.request import urlopen
                for name,port in [('sat_a',18080),('sat_b',18081)]:
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/healthz',timeout=1) as response:
                            components[name]={'reachable':response.status==200}
                    except Exception as exc:components[name]={'reachable':False,'error':str(exc)}
                self.cached_status=components;self.cached_at=time.monotonic()
        guard=json.loads(self.jobs.guard.read_text()) if self.jobs.guard.exists() else None
        return {'timestamp_utc':utc_now(),'components':self.cached_status,'lock':guard,
            'frozen':(self.root/'config/campaign-manifest.json').exists(),
            'scenario':json.loads((self.root/'config/scenario.json').read_text()),
            'controller_health_source':'per-run heartbeat.jsonl; missing values are not health confirmations'}

    def runs(self):
        result=[]
        for path in (self.root/'results/runs').glob('run-*/inputs.json'):
            metadata=path.parent/'metadata.json'
            if metadata.exists():row=json.loads(metadata.read_text())
            else:
                inputs=json.loads(path.read_text())
                row={'run_id':path.parent.name,'outcome':'running','method':inputs['method'],
                    'configured_rate_bps':inputs['rate_bps'],'event':inputs['event'],'purpose':inputs['purpose'],
                    'execution_kind':'live-hybrid','created_utc':None}
            result.append({key:row.get(key) for key in ('run_id','outcome','method','configured_rate_bps',
                'event','purpose','execution_kind','created_utc','controller_downtime_s','total_operation_s',
                'image_throughput_bps','probes','success','ack','failure_reason')})
        return sorted(result,key=lambda row:row.get('created_utc') or '9999',reverse=True)

    def topology(self,identifier=None,tick=None):
        from .orbit import Orbit,shortest_paths
        if self.orbit is None:self.orbit=Orbit(self.root/'artifacts/orbit/replay.npz')
        event=None
        if identifier:
            directory=run_directory(self.root,identifier)
            event=json.loads((directory/'inputs.json').read_text())['event']
            observations=list(json_lines(directory/'geometry.jsonl'))
            if tick is None:tick=observations[-1]['orbital_s'] if observations else max(0,event['trigger_s']-30)
        if tick is None:tick=0
        tick=int(tick);graph=self.orbit.graph(tick)
        selection={row['norad_id']:row for row in json.loads((self.root/'config/selected_constellation.json').read_text())['satellites']}
        path=[];distances=shortest_paths(graph,53913)
        if 53848 in distances:
            node=53848;path=[node]
            while node!=53913:
                neighbors=[(length+distances[neighbor],neighbor) for neighbor,length in graph[node].items() if neighbor in distances]
                node=min(neighbors)[1]
                if node in path:raise ValueError('Invalid service path loop')
                path.append(node)
        return {'execution_kind':'modeled-geometry','orbital_s':tick,'sat_a':event.get('sat_a') if event else None,
            'sat_b':event.get('sat_b') if event else None,'nodes':[{'norad':sid,'eclipsed':not self.orbit.operational(sid,tick),
                'plane':selection[sid]['plane'],'phase_rank':selection[sid]['phase_rank'],
                'position_teme_km':self.orbit.positions[tick,self.orbit.index[sid]].tolist()} for sid in self.orbit.ids],
            'links':[[a,b] for a in graph for b in graph[a] if a<b],'service_path':path}

    def artifacts(self):
        paths=[]
        fixed=('results/environment.json','results/calibration.json','results/events.json','results/campaign.json',
            'results/fault-campaign.json','results/sensitivity.json','results/ranking-diagnostic.json',
            'results/workflow.json','config/campaign-manifest.json','config/selected_events.json')
        paths.extend(self.root/p for p in fixed)
        for folder in (self.root/'results/runs').glob('run-*'):
            paths.extend(p for p in folder.iterdir() if p.suffix in ('.json','.jsonl','.csv','.log'))
            operation=folder/'operation'
            if operation.exists():paths.extend(p for p in operation.iterdir() if p.suffix in ('.json','.jsonl'))
            probe=self.root/'results/lab'/folder.name
            if probe.exists():paths.extend(p for p in probe.iterdir() if p.suffix in ('.jsonl','.log'))
        report=self.root/'results/report'
        if report.exists():paths.extend(p for p in report.iterdir() if p.suffix in ('.json','.csv','.html','.svg'))
        rows=[];registry={}
        for path in paths:
            if not path.is_file():continue
            resolved=path.resolve()
            if not resolved.is_relative_to(self.root):continue
            relative=resolved.relative_to(self.root).as_posix()
            identifier=hashlib.sha256(relative.encode()).hexdigest()[:32]
            registry[identifier]=resolved
            rows.append({'artifact_id':identifier,'label':relative,'bytes':resolved.stat().st_size,
                'download_url':'/api/v1/artifacts/'+identifier})
        with self.lock:self.registry=registry
        return rows


def make_server(root,port=18092):
    application=Application(root)
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'

        def same_origin(self):
            port=self.server.server_address[1]
            allowed={f'127.0.0.1:{port}',f'localhost:{port}'}
            host=self.headers.get('Host','')
            origin=self.headers.get('Origin')
            return (host in allowed and (origin is None or origin=='http://'+host)
                and self.headers.get('Sec-Fetch-Site') not in ('cross-site',))

        def send(self,data,status=200,media='application/json',headers=None):
            if not isinstance(data,bytes):data=canonical_bytes(data)
            self.send_response(status)
            self.send_header('Content-Type',media)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            for key,value in (headers or {}).items():self.send_header(key,value)
            self.end_headers();self.wfile.write(data)

        def do_GET(self):
            if not self.same_origin():return self.send({'error':'Same-origin access required'},403)
            try:self.get()
            except (ValueError,KeyError) as exc:self.send({'error':str(exc)},400)
            except FileNotFoundError:self.send({'error':'Resource not found'},404)
            except (BrokenPipeError,ConnectionResetError):pass
            except Exception as exc:self.send({'error':str(exc)},500)

        def get(self):
            url=urlsplit(self.path);path=url.path;query=parse_qs(url.query)
            if path=='/api/v1/session':
                identifier,token=application.session(self.headers.get('Cookie'))
                return self.send({'token':token},headers={'Set-Cookie':f'tfs_session={identifier}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'})
            if path=='/api/v1/state':return self.send(application.status())
            if path=='/api/v1/jobs':return self.send({'jobs':application.jobs.list()})
            if path.startswith('/api/v1/jobs/'):
                parts=path.split('/');identifier=parts[4];job=application.jobs.get(identifier)
                if len(parts)==6 and parts[5]=='events':
                    after=int(self.headers.get('Last-Event-ID',query.get('after',['0'])[0]))
                    if after<0:raise ValueError('Invalid event cursor')
                    self.send_response(200);self.send_header('Content-Type','text/event-stream')
                    self.send_header('Cache-Control','no-cache');self.send_header('Connection','close');self.end_headers()
                    self.close_connection=True
                    last_heartbeat=0
                    while True:
                        for event in events_after(application.jobs.directory/identifier/'events.jsonl',after):
                            payload=json.dumps(event,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
                            self.wfile.write(b'id: '+str(event['id']).encode()+b'\ndata: '+payload+b'\n\n')
                            after=event['id']
                        job=application.jobs.get(identifier)
                        if job['status'] in TERMINAL:
                            payload=json.dumps({'status':job['status']},separators=(',',':')).encode('utf-8')
                            self.wfile.write(b'event: end\ndata: '+payload+b'\n\n');self.wfile.flush();return
                        if time.monotonic()-last_heartbeat>10:
                            self.wfile.write(b': heartbeat\n\n');last_heartbeat=time.monotonic()
                        self.wfile.flush();time.sleep(.25)
                return self.send(job)
            if path=='/api/v1/runs':return self.send({'runs':application.runs()})
            if path.startswith('/api/v1/runs/'):
                identifier=path.split('/')[4];directory=run_directory(application.root,identifier)
                if path.endswith('/observations'):
                    return self.send({name:list(json_lines(directory/(name+'.jsonl'))) for name in ('geometry','heartbeat','authority','operations','resources')})
                metadata=directory/'metadata.json'
                return self.send(json.loads(metadata.read_text()) if metadata.exists() else {'inputs':json.loads((directory/'inputs.json').read_text()),'outcome':'running'})
            if path=='/api/v1/topology':
                return self.send(application.topology(query.get('run_id',[None])[0],query.get('orbital_s',[None])[0]))
            if path=='/api/v1/campaigns':
                return self.send({name:json.loads((application.root/file).read_text()) if (application.root/file).exists() else None
                    for name,file in [('primary','results/campaign.json'),('frozen','config/campaign-manifest.json'),
                        ('events','config/selected_events.json'),('faults','results/fault-campaign.json'),('workflow','results/workflow.json')]})
            if path=='/api/v1/artifacts':return self.send({'artifacts':application.artifacts()})
            if path.startswith('/api/v1/artifacts/'):
                identifier=path.split('/')[-1];application.artifacts()
                file=application.registry.get(identifier)
                if file is None:raise FileNotFoundError(identifier)
                return self.send(file.read_bytes(),media=mimetypes.guess_type(file.name)[0] or 'application/octet-stream',
                    headers={'Content-Disposition':'attachment; filename="'+file.name+'"'})
            assets={'/':'web/index.html','/app.js':'web/app.js','/style.css':'web/style.css','/tokens.css':'web/tokens.css'}
            if path.startswith('/fonts/') and Path(path).name in {'SpaceGrotesk.ttf','Inter.ttf'}:
                assets[path]='web/fonts/'+Path(path).name
            if path not in assets:raise FileNotFoundError(path)
            file=application.root/assets[path]
            return self.send(file.read_bytes(),media=mimetypes.guess_type(file.name)[0] or 'application/octet-stream')

        def do_POST(self):
            if not self.same_origin() or not application.authorized(self.headers.get('Cookie'),self.headers.get('X-CSRF-Token')):
                return self.send({'error':'Valid same-origin session token required'},403)
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=16384:raise ValueError('Invalid request size')
                body=json.loads(self.rfile.read(size))
                if self.path=='/api/v1/jobs':
                    return self.send(application.jobs.start(body['operation'],body.get('parameters')),202)
                parts=self.path.split('/')
                if len(parts)==6 and parts[:4]==['','api','v1','jobs'] and parts[5]=='stop':
                    application.jobs.stop(parts[4]);return self.send({'interruption_requested':True},202)
                raise ValueError('Unknown command')
            except BusyError as exc:self.send({'error':str(exc)},409)
            except (ValueError,KeyError,json.JSONDecodeError) as exc:self.send({'error':str(exc)},400)
            except Exception as exc:self.send({'error':str(exc)},500)

        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.application=application
    server.daemon_threads=True
    return server
