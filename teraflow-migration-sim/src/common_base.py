"""Frozen initial scenario and one conservative schedule for the three useful rates."""
import copy
import hashlib
import json
import uuid
from pathlib import Path
from .artifacts import canonical_bytes, file_digest
from .preconditions import calibration_inputs
from .storage import atomic_json, utc_now

RATES=[100000000,1000000000,10000000000]
POLICY='common-orbital-base-v1'

def directory(root, identifier):
    if not isinstance(identifier,str) or len(identifier)!=37 or not identifier.startswith('base-') or any(c not in '0123456789abcdef' for c in identifier[5:]):
        raise ValueError('Identificativo base comune non valido')
    return Path(root)/'results/common-bases'/identifier

def identity(root):
    from .simulation import engine_fingerprint
    return {'engine_fingerprint':engine_fingerprint(root),'files':{name:file_digest(Path(root)/name) for name in
        ('config/scenario.json','config/fixture.json','config/selected_constellation.json',
         'config/artifact_manifest.json','results/calibration.json','results/direct_link_windows.json','artifacts/orbit/replay.json')}}

def load(root, identifier, *, full=False):
    path=directory(root,identifier)
    metadata=json.loads((path/'metadata.json').read_text(encoding='utf-8'))
    if metadata.get('policy_version')!=POLICY or not metadata.get('complete'):raise ValueError('Base comune incompleta')
    calibration_inputs(Path(root),full=full)
    if metadata['identity']!=identity(root):raise ValueError('Base comune non valida: configurazione o misure cambiate. Prepararla nuovamente.')
    for name,digest in metadata['artifacts'].items():
        if name not in ('plan.json','initial-state.json','scenario.json','fixture.json','selected-constellation.json','calibration.json','artifact-manifest.json'):
            raise ValueError('Artefatto della base non ammesso')
        if file_digest(path/name)!=digest:raise ValueError('Artefatto della base comune alterato: '+name)
    if full:
        replay=json.loads((Path(root)/'artifacts/orbit/replay.json').read_text(encoding='utf-8'))
        if file_digest(Path(root)/'artifacts/orbit/replay.npz')!=replay['artifact']['sha256']:raise ValueError('Replay orbitale alterato')
    return metadata,json.loads((path/'plan.json').read_text(encoding='utf-8'))

def status(root):
    files=sorted((Path(root)/'results/common-bases').glob('base-*/metadata.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not files:return {'ready':False,'exists':False,'reason':'Scenario iniziale da creare. La calibrazione necessaria è inclusa.'}
    identifier=files[0].parent.name
    try:
        metadata,_=load(root,identifier)
        from .prepared_source import readiness
        source=readiness(root,identifier)
        return {'ready':source['ready'],'plan_ready':True,'exists':True,**{key:metadata[key] for key in ('base_id','created_utc','rates','selected','schedule_sha256')},'reason':'Base pronta: stesso scenario e stesse tre migrazioni per tutte le velocità.'}
    except (ValueError,OSError,KeyError) as exc:return {'ready':False,'exists':True,'base_id':identifier,'reason':str(exc)}

def prepare(app):
    existing=status(app.root)
    if existing.get('plan_ready'):
        metadata,_=load(app.root,existing['base_id'],full=True)
        return metadata
    from .continuous_comparison import ContinuousComparison, validate_parameters
    from .automatic_start import select_start
    from .fixture import state
    calibration,manifest=calibration_inputs(app.root,full=True)
    before=identity(app.root)
    identifier='base-'+uuid.uuid4().hex
    path=directory(app.root,identifier);path.mkdir(parents=True)
    coordinator=ContinuousComparison(app);coordinator.identifier=identifier;coordinator.directory=path
    coordinator.result={'phase':'preparation','preparation':[]}
    from .planner import Planner,OrbitIndex
    from .migration_model import workload_from_manifest
    calibrated=copy.deepcopy(calibration)
    calibrated['manifest_resources']={key:manifest['resources']['measured_controller_'+key] for key in ('cpu_cores','ram_gib','disk_gib')}
    windows=json.loads((app.root/'results/direct_link_windows.json').read_text(encoding='utf-8'))['windows']
    coordinator.planner=Planner(app.orbit,OrbitIndex(app.orbit,windows),app.scenario,calibrated,workload_from_manifest(manifest),cancel=app.cancel,publish=app.publish)
    atomic_json(path/'calibration.json',calibration);atomic_json(path/'artifact-manifest.json',manifest)
    parameters=validate_parameters({'migration_count':3,'rate_bps':min(RATES)})
    app.publish({'phase':'planning','label':'Ricerca della base comune per tre velocità'})
    evidence,plans=select_start(coordinator.planner,parameters,[min(RATES)],budget_s=app.scenario.get('live',{}).get('departure_search_budget_s',600))
    plan=copy.deepcopy(plans[str(min(RATES))]);plan['common_base_id']=identifier
    plan['admission_rate_bps']=min(RATES);plan['supported_rates']=RATES
    from .continuous_comparison import SharedPlanner
    conservative=SharedPlanner(coordinator.planner.orbit,coordinator.planner.index,coordinator.planner.scenario,
        {'horizon_s':coordinator.planner.horizon,'manifest_resources':coordinator.planner.resources},coordinator.planner.workload)
    for rate in RATES:
        operation,recovery=conservative.estimate('hot',rate)
        if any(operation>event['estimated_operation_s'] or recovery>event['recovery_reserve_s'] for event in plan['migrations']):
            raise ValueError('La base non è sicura per tutte le velocità')
    replay=json.loads((app.root/'artifacts/orbit/replay.json').read_text(encoding='utf-8'))
    if file_digest(app.root/'artifacts/orbit/replay.npz')!=replay['artifact']['sha256']:raise ValueError('Replay orbitale non integro')
    from .orbit import lab_graph
    snapshot=state(json.loads((app.root/'config/fixture.json').read_text(encoding='utf-8')),lab_graph(app.orbit,plan['start_s']))
    if identity(app.root)!=before:raise ValueError('Input cambiati durante la preparazione della base')
    atomic_json(path/'plan.json',plan);atomic_json(path/'initial-state.json',snapshot)
    for name,source in [('scenario.json','config/scenario.json'),('fixture.json','config/fixture.json'),
                        ('selected-constellation.json','config/selected_constellation.json')]:
        atomic_json(path/name,json.loads((app.root/source).read_text(encoding='utf-8')))
    names=('plan.json','initial-state.json','scenario.json','fixture.json','selected-constellation.json','calibration.json','artifact-manifest.json')
    metadata={'schema_version':1,'execution_kind':'modeled-common-base','base_id':identifier,'policy_version':POLICY,'complete':True,'created_utc':utc_now(),
        'rates':RATES,'migration_count':3,'identity':before,'selected':evidence['selected'],'search':evidence,
        'schedule_sha256':hashlib.sha256(canonical_bytes(plan['migrations'])).hexdigest(),
        'artifacts':{name:file_digest(path/name) for name in names}}
    atomic_json(path/'metadata.json',metadata)
    app.publish({'phase':'scenario_creation','label':'Piano comune pronto: attivazione della sorgente','base_id':identifier})
    return metadata
