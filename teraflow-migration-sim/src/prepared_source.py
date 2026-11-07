"""A prepared source survives the preparation worker; the orbital clock stays stopped."""
import json
import time
from urllib.request import urlopen
from .artifacts import file_digest
from .storage import atomic_json, utc_now


def record_path(root, base_id):
    from .common_base import directory
    return directory(root, base_id)/'source-ready.json'


def readiness(root, base_id):
    """Cheap live evidence for the UI; full inventory is checked again at handoff."""
    from .live_backend import http
    try:
        record=json.loads(record_path(root,base_id).read_text(encoding='utf-8'))
        if not record.get('ready'):raise ValueError('Sorgente non predisposta o scenario già utilizzato.')
        status=http(18091,timeout=1)
        if (status.get('generation')!=record['generation'] or status.get('active')!='sat-a'
            or status.get('frozen',True) or not status.get('states')
            or not all(row.get('upstream_master') for row in status['states'])):
            raise ValueError('Autorità P4 cambiata o non disponibile.')
        with urlopen('http://127.0.0.1:18080/healthz',timeout=1) as response:
            if response.status!=200:raise ValueError('API sorgente non disponibile.')
        return {'ready':True,'reason':'Sorgente pronta: API, autorità P4 e sonde verificate. Avvia esegue una nuova verifica finale.'}
    except FileNotFoundError:
        return {'ready':False,'reason':'Crea lo scenario iniziale per predisporre il controller sorgente.'}
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
        return {'ready':False,'reason':'Ricrea lo scenario iniziale: '+str(exc)}


def prepare(app, metadata):
    from .common_base import directory, load
    from .live_backend import LiveBackend, http
    base_id=metadata['base_id'];path=directory(app.root,base_id)
    _,plan=load(app.root,base_id,full=True)
    ready_path=record_path(app.root,base_id)
    atomic_json(ready_path,{'ready':False})
    event={'sat_a':plan['initial_satellite_id'],'sat_b':None,'start_s':plan['start_s'],
           'trigger_s':plan['start_s'],'deadline_s':plan['end_s']}
    backend=LiveBackend(app.root,path/'source-preparation',event,min(metadata['rates']),
                        app.orbit,app.scenario,app.cancel,notify=app.publish)
    app.checkpoint(kind='between_runs',phase='source_preparation',base_id=base_id)
    try:
        app.publish({'phase':'scenario_creation','label':'Attivazione del controller sorgente'})
        if getattr(app, '_calibration_network_ready', False):
            backend.reset(reuse_inventory=True)
        else:
            backend.reset()
        baseline=backend.establish_baseline(base_id)
        if not baseline.get('success'):raise RuntimeError('Verifica API, autorità e sonde non riuscita')
        backend.check()
        status=http(18091,timeout=2)
        snapshot=backend.directory/'prepared-snapshot.json'
        record={'ready':True,'base_id':base_id,'verified_utc':utc_now(),
                'generation':status['generation'],'baseline':baseline,
                'snapshot_sha256':file_digest(snapshot)}
        atomic_json(ready_path,record)
        evidence=readiness(app.root,base_id)
        if not evidence['ready']:raise RuntimeError(evidence['reason'])
        backend.check()
        app.publish({'phase':'common_base_ready','label':'Scenario iniziale e controller sorgente pronti','base_id':base_id})
        return {**metadata,'execution_kind':'live-prepared-common-base','source_ready':True,'baseline':baseline}
    except Exception as exc:
        atomic_json(ready_path,{'ready':False,'reason':str(exc)})
        app.publish({'phase':'scenario_creation','label':'Creazione scenario non completata: '+str(exc)})
        cleanup_error=None
        try:backend.shutdown()
        except Exception as cleanup:cleanup_error=str(cleanup)
        return {**metadata,'complete':False,'source_ready':False,'reason':str(exc),
                'recovery_required':bool(cleanup_error),'cleanup_error':cleanup_error}


def adopt(backend, base_id, plan):
    """Consume once, verify the actual source, then let Simulation run fresh probes."""
    from .common_base import directory, load
    load(backend.root,base_id,full=True)
    evidence=readiness(backend.root,base_id)
    if not evidence['ready']:raise ValueError(evidence['reason'])
    path=directory(backend.root,base_id)
    ready_path=record_path(backend.root,base_id)
    record=json.loads(ready_path.read_text(encoding='utf-8'))
    record['ready']=False;record['consumed_utc']=utc_now()
    atomic_json(ready_path,record)
    backend.preparation_deadline=time.monotonic()+60
    proxy=backend.wait_infrastructure()
    backend.fixture['controller_proxy']=proxy['ipv4']
    if proxy.get('generation')!=record['generation']:raise ValueError('Autorità P4 cambiata durante la verifica finale')
    snapshot_path=path/'source-preparation/prepared-snapshot.json'
    if file_digest(snapshot_path)!=record['snapshot_sha256']:raise ValueError('Snapshot sorgente alterato')
    snapshot=json.loads(snapshot_path.read_text(encoding='utf-8'))
    backend.notify({'phase':'scenario_creation','label':'Verifica finale dello scenario iniziale'})
    verification=backend.a.verify(snapshot)
    if not verification['equivalent']:raise ValueError('Scenario sorgente cambiato: ricrea lo scenario iniziale')
    backend.source_snapshot=snapshot
    backend.proxy_generation=record['generation']
    backend.initial_tick=plan['start_s']
    from .orbit import lab_graph
    graph=lab_graph(backend.orbit,plan['start_s'])
    backend.set_links(graph)
    backend.graph_signature=backend.signature(graph)
