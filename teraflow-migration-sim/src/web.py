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
from .storage import atomic_json, utc_now, read_json
from .results import read_result


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

    def simulation_readiness(self):
        """Expose admission prerequisites before the user launches a worker."""
        try:
            functional_path=self.root/'results/functional-gate.json'
            functional=json.loads(functional_path.read_text()) if functional_path.exists() else {}
            functional_valid=functional.get('complete',False) and all(
                (self.root/'results/runs'/row['run_id']/'metadata.json').exists()
                for row in functional.get('runs',[]))
            next_operation='calibrate' if functional_valid else 'functional'
            path=self.root/'results/calibration.json'
            if not path.exists():
                failed=next((row for row in reversed(functional.get('runs',[]))
                    if row.get('outcome')=='invalid_baseline'),None)
                if failed:
                    evidence_path=self.root/'results/runs'/failed['run_id']/'metadata.json'
                    if evidence_path.exists():
                        baseline=json.loads(evidence_path.read_text()).get('baseline',{})
                        ping=baseline.get('last_ping',{})
                        return {'ready':False,'next_operation':'functional','reason':
                            'Simulazione bloccata: ultima verifica del servizio senza baseline valida. '
                            f"Ping riusciti {ping.get('successful_probes','—')}/{ping.get('observed_probes','—')}, "
                            f"pacchetti UDP ricevuti {baseline.get('udp_received','—')}. "
                            'Occorre ripristinare il servizio del laboratorio prima di procedere alle calibrazioni.'}
                return {'ready':False,'next_operation':next_operation,'reason':
                    'Prima di avviare la simulazione servono le verifiche hot/cold del servizio e sei calibrazioni live.'
                    if not functional_valid else 'Verifiche hot/cold completate. Eseguire le sei calibrazioni live prima della simulazione.'}
            from .preconditions import calibration_inputs
            calibration_inputs(self.root, full=False)
            return {'ready':True,'next_operation':None,
                'reason':'Calibrazione disponibile. Dopo l’avvio verranno verificate la sequenza orbitale e la baseline.'}
        except Exception:
            return {'ready':False,'next_operation':'functional',
                'reason':'Evidenze di preparazione mancanti o non valide. Ripetere le verifiche hot/cold e la calibrazione.'}

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
        guard=read_json(self.jobs.guard) if self.jobs.guard.exists() else None
        active_job=None;worker_alive=None
        if guard:
            try:
                active_job=self.jobs.get(guard['job_id'])
                worker_alive=process_running(guard.get('worker_pid',guard.get('launcher_pid')))
            except (OSError,ValueError): pass
        return {'timestamp_utc':utc_now(),'components':self.cached_status,'lock':guard,
            'progress':active_job.get('progress') if active_job else None,'worker_alive':worker_alive,
            'simulation_readiness':self.simulation_readiness(),
            'frozen':(self.root/'config/campaign-manifest.json').exists(),
            'scenario':json.loads((self.root/'config/scenario.json').read_text()),
            'controller_health_source':'per-run heartbeat.jsonl; missing values are not health confirmations'}

    def runs(self):
        result=[]
        for path in (self.root/'results/runs').glob('run-*/inputs.json'):
            metadata=path.parent/'metadata.json'
            if metadata.exists():row=read_result(json.loads(metadata.read_text()))
            else:
                inputs=json.loads(path.read_text())
                row={'run_id':path.parent.name,'outcome':'running','method':inputs['method'],
                    'configured_rate_bps':inputs['rate_bps'],'event':inputs['event'],'purpose':inputs['purpose'],
                    'execution_kind':'live-hybrid','created_utc':None}
            result.append({key:row.get(key) for key in ('run_id','outcome','method','configured_rate_bps',
                'event','purpose','execution_kind','created_utc','controller_downtime_s','total_operation_s',
                'image_throughput_bps','probes','success','ack','failure_reason','metrics','migration_completed',
                'experimental_valid','observation_complete','recovery_required')})
        return sorted(result,key=lambda row:row.get('created_utc') or '9999',reverse=True)

    def simulations(self):
        return sorted([read_json(p) for p in (self.root/'results/simulations').glob('sim-*/metadata.json')],
                      key=lambda row:row['created_utc'],reverse=True)

    def continuous_comparisons(self):
        rows = [read_json(path) for path in
            (self.root/'results/continuous-comparisons').glob('pair-*/metadata.json')]
        for row in rows:
            progress=self.root/'results/jobs'/str(row.get('job_id'))/'progress.json'
            if progress.exists(): row['progress']=read_json(progress)
        return sorted(rows,key=lambda row:row['created_utc'],reverse=True)

    def topology(self,identifier=None,tick=None):
        from .orbit import Orbit,shortest_paths
        from .topology_state import presentation
        import numpy as np
        replay=tick is not None
        if self.orbit is None:self.orbit=Orbit(self.root/'artifacts/orbit/replay.npz')
        event=None
        if identifier:
            directory=run_directory(self.root,identifier)
            historical=self.historical_geometry(directory)
            if historical is not self:return historical.topology(identifier,tick)
            event=json.loads((directory/'inputs.json').read_text())['event']
            observations=list(json_lines(directory/'geometry.jsonl'))
            if tick is None:tick=observations[-1]['orbital_s'] if observations else max(0,event['trigger_s']-30)
        if tick is None:tick=0
        tick=int(tick);graph=self.orbit.graph(tick)
        selection={row['norad_id']:row for row in json.loads(getattr(self,'selection_file',self.root/'config/selected_constellation.json').read_text())['satellites']}
        angles={}
        for plane in (1,2):
            ids=sorted((sid for sid in self.orbit.ids if selection[sid]['plane']==plane),
                       key=lambda sid:selection[sid]['phase_rank'])
            reference=self.orbit.positions[0,self.orbit.index[ids[0]]]
            later=self.orbit.positions[min(60,len(self.orbit.positions)-1),self.orbit.index[ids[0]]]
            u=reference/np.linalg.norm(reference)
            normal=np.cross(reference,later);normal=normal/np.linalg.norm(normal)
            v=np.cross(normal,u)
            for sid in ids:
                position=self.orbit.positions[tick,self.orbit.index[sid]]
                angles[sid]=float(np.arctan2(np.dot(position,v),np.dot(position,u)))
        display={'mode':'geometry','phase':'unknown','controller_satellite':None,'migration_status':'none'}
        if identifier:
            meta_path=directory/'metadata.json'
            metadata=json.loads(meta_path.read_text()) if meta_path.exists() else {}
            display=presentation(directory,tick,metadata=metadata,
                replay=replay or metadata.get('outcome') not in (None,'running'))
        path=[];distances=shortest_paths(graph,53913)
        if 53848 in distances:
            node=53848;path=[node]
            while node!=53913:
                neighbors=[(length+distances[neighbor],neighbor) for neighbor,length in graph[node].items() if neighbor in distances]
                node=min(neighbors)[1]
                if node in path:raise ValueError('Invalid service path loop')
                path.append(node)
        return {'execution_kind':'modeled-geometry','orbital_s':tick,'presentation':display,'sat_a':event.get('sat_a') if event else None,
            'sat_b':event.get('sat_b') if event else None,'nodes':[{'norad':sid,'eclipsed':not self.orbit.operational(sid,tick),
                **self.orbit.illumination_window(sid,tick),
                'plane':selection[sid]['plane'],'phase_rank':selection[sid]['phase_rank'],'orbital_angle_rad':angles[sid],
                'position_teme_km':self.orbit.positions[tick,self.orbit.index[sid]].tolist()} for sid in self.orbit.ids],
            'links':[[a,b] for a in graph for b in graph[a] if a<b],'service_path':path}

    def initial_topology(self, initial_satellite_id=None, start_orbital_s=0):
        """A stationary initial assignment; launching must preserve both host and epoch."""
        if self.orbit is None:
            from .orbit import Orbit
            self.orbit=Orbit(self.root/'artifacts/orbit/replay.npz')
        if isinstance(start_orbital_s,bool) or not isinstance(start_orbital_s,int) or not 0 <= start_orbital_s < self.orbit.duration:
            raise ValueError('Tempo iniziale fuori dall’osservazione orbitale')
        topology=self.topology(tick=start_orbital_s)
        if initial_satellite_id is None:
            topology['initial_configuration']=None
            topology['presentation']={'mode':'preview','phase':'departure_pending','stale':False,
                'controller_satellite':None,'assigned_controller_satellite':None,
                'placement_status':'unassigned','migration_status':'none','forwarding_observed':None}
            from .topology_state import candidate_presentation
            candidate_presentation(topology,controller=None)
            return topology
        connected={sid for edge in topology['links'] for sid in edge}
        candidates=[node for node in topology['nodes'] if not node['eclipsed'] and node['norad'] in connected]
        if not candidates:
            raise ValueError('Nessun satellite iniziale illuminato e collegato disponibile')
        if initial_satellite_id is not None:
            if type(initial_satellite_id) is not int or initial_satellite_id not in {node['norad'] for node in candidates}:
                raise ValueError('Il satellite scelto non è illuminato e collegato al tempo iniziale richiesto')
            host=initial_satellite_id
        else:
            host=max(candidates,key=lambda node:(node['next_transition_s'] if node['next_transition_s'] is not None
                                                   else self.orbit.duration,-node['norad']))['norad']
        topology['initial_configuration']={'initial_satellite_id':host,'start_orbital_s':start_orbital_s}
        topology['presentation']={'mode':'preview','phase':'initial_assignment','stale':False,
            'controller_satellite':None,'assigned_controller_satellite':host,'placement_status':'initial',
            'migration_status':'none','forwarding_observed':None}
        from .topology_state import candidate_presentation
        candidate_presentation(topology,controller=host)
        return topology

    def historical_geometry(self,directory):
        """Never add the new satellites to a historical experiment's replay."""
        inputs=json.loads((directory/'inputs.json').read_text())
        orbital=inputs.get('scenario',{}).get('orbital',{})
        count=orbital.get('satellites_total')
        if count is None:return self
        from .orbit import Orbit
        if self.orbit is None:self.orbit=Orbit(self.root/'artifacts/orbit/replay.npz')
        if len(self.orbit.ids)==count:return self
        import copy
        for selection_file in (self.root/'artifacts/constellation-profiles').glob('*/original/config/selected_constellation.json'):
            selection=json.loads(selection_file.read_text())
            if len(selection['satellites'])!=count:continue
            archive=selection_file.parents[1]
            replay=archive/'artifacts/orbit/replay.npz'
            if replay.exists():
                view=copy.copy(self);view.orbit=Orbit(replay);view.selection_file=selection_file
                return view
        raise ValueError('Geometria originale non disponibile per questo esperimento storico')

    def simulation_topology(self,directory,requested=None):
        historical=self.historical_geometry(directory)
        if historical is not self:return historical.simulation_topology(directory,requested)
        from .topology_state import presentation,candidate_presentation
        observations=list(json_lines(directory/'observations.jsonl'))
        metadata=json.loads((directory/'metadata.json').read_text())
        # Telemetry continues during handovers, while session observations pause.
        geometry=list(json_lines(directory/'geometry.jsonl'))
        latest=max([r['orbital_s'] for r in observations+geometry] or [metadata.get('start_s') or 0])
        tick=float(requested) if requested is not None else latest
        previous=[row for row in observations if row['orbital_s']<=tick]
        context=previous[-1] if previous else None
        plan_file=directory/'plans/initial.json'
        if context is None and plan_file.exists():
            plan=json.loads(plan_file.read_text())
            context={'controller_satellite':plan['initial_satellite_id'],
                'active_slot':None,'proposed_slot':'sat-a','placement_status':'planned',
                'next_migration':next(iter(plan['migrations']),None)}
        topology=self.topology(tick=tick)
        topology['simulation']=context
        topology['presentation']=presentation(directory,tick,context=context,metadata=metadata,
            replay=requested is not None or metadata.get('phase')=='finished')
        event=(context or {}).get('next_migration')
        if topology['presentation'].get('migration_status')=='completed':event=None
        candidate_presentation(topology,event,topology['presentation'].get('controller_satellite'))
        topology['clock_running']=requested is None and metadata.get('phase') in {'running','migrating'}
        if topology['clock_running'] and topology.get('nodes'):
            # Only modeled geometry is looked ahead; controller/forwarding evidence stays at tick.
            topology['motion_frames']=[
                self.topology(tick=int(tick)+offset) for offset in (1,2)
                if int(tick)+offset < self.orbit.duration]
        return topology

    def artifacts(self):
        paths=[]
        fixed=('results/environment.json','results/calibration.json','results/events.json','results/campaign.json',
            'results/fault-campaign.json','results/sensitivity.json','results/ranking-diagnostic.json',
            'results/workflow.json','results/functional-gate.json','config/campaign-manifest.json','config/selected_events.json')
        paths.extend(self.root/p for p in fixed)
        paths.extend((self.root/'results/comparisons').glob('compare-*/metadata.json'))
        for folder in (self.root/'results/continuous-comparisons').glob('pair-*'):
            paths.extend(p for p in folder.iterdir() if p.suffix in ('.json','.csv','.html'))
        for folder in (self.root/'results/simulations').glob('sim-*'):
            paths.extend(p for p in folder.rglob('*') if p.suffix in ('.json','.jsonl','.csv','.html','.svg','.log'))
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
                if job.get('operation') in ('functional','compare_continuous'):
                    result=application.jobs.directory/identifier/'result.json'
                    if result.exists():job['comparison']=json.loads(result.read_text())
                return self.send(job)
            if path=='/api/v1/runs':return self.send({'runs':application.runs()})
            if path=='/api/v1/simulations':return self.send({'simulations':application.simulations()})
            if path=='/api/v1/continuous-comparisons':
                return self.send({'comparisons':application.continuous_comparisons()})
            if path.startswith('/api/v1/continuous-comparisons/'):
                from .continuous_comparison import comparison_directory
                directory=comparison_directory(application.root,path.split('/')[-1])
                return self.send(json.loads((directory/'metadata.json').read_text()))
            if path.startswith('/api/v1/simulations/'):
                from .simulation import simulation_directory
                parts=path.split('/');directory=simulation_directory(application.root,parts[4])
                if len(parts)==6 and parts[5]=='observations':
                    return self.send({name:list(json_lines(directory/(name+'.jsonl')))
                        for name in ('observations','geometry','heartbeat','authority','resources','events')})
                if len(parts)==6 and parts[5]=='topology':
                    requested=query.get('orbital_s',[None])[0]
                    return self.send(application.simulation_topology(directory,requested))
                if len(parts)!=5:raise ValueError('Unknown simulation resource')
                return self.send(json.loads((directory/'metadata.json').read_text()))
            if path.startswith('/api/v1/runs/'):
                identifier=path.split('/')[4];directory=run_directory(application.root,identifier)
                if path.endswith('/observations'):
                    return self.send({name:list(json_lines(directory/(name+'.jsonl'))) for name in ('geometry','heartbeat','authority','operations','resources')})
                metadata=directory/'metadata.json'
                return self.send(read_result(json.loads(metadata.read_text())) if metadata.exists() else {'inputs':json.loads((directory/'inputs.json').read_text()),'outcome':'running'})
            if path=='/api/v1/topology':
                return self.send(application.topology(query.get('run_id',[None])[0],query.get('orbital_s',[None])[0]))
            if path=='/api/v1/initial-topology':
                if set(query)-{'initial_satellite_id','start_orbital_s'}:raise ValueError('Unknown initial configuration field')
                host=query.get('initial_satellite_id',[None])[0]
                return self.send(application.initial_topology(int(host) if host is not None else None,
                    int(query.get('start_orbital_s',[0])[0])))
            if path=='/api/v1/campaigns':
                return self.send({name:json.loads((application.root/file).read_text()) if (application.root/file).exists() else None
                    for name,file in [('primary','results/campaign.json'),('frozen','config/campaign-manifest.json'),
                        ('events','config/selected_events.json'),('faults','results/fault-campaign.json'),('workflow','results/workflow.json'),
                        ('functional','results/functional-gate.json')]})
            if path=='/api/v1/artifacts':return self.send({'artifacts':application.artifacts()})
            if path.startswith('/api/v1/artifacts/'):
                identifier=path.split('/')[-1];application.artifacts()
                file=application.registry.get(identifier)
                if file is None:raise FileNotFoundError(identifier)
                return self.send(file.read_bytes(),media=mimetypes.guess_type(file.name)[0] or 'application/octet-stream',
                    headers={'Content-Disposition':'attachment; filename="'+file.name+'"'})
            assets={'/':'web/index.html','/experiment-state.js':'web/experiment-state.js','/app.js':'web/app.js','/orbit-view.js':'web/orbit-view.js','/style.css':'web/style.css','/tokens.css':'web/tokens.css'}
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
