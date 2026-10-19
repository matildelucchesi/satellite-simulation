"""Reports derived from saved evidence, including interrupted/admission failures."""
import csv
import html
import json
from pathlib import Path
from .probes import json_lines, ping_observations, classify_observations, analyze_directory
from .storage import atomic_json
from .results import read_result, summary_metrics


def report(directory, root):
    directory, root = Path(directory), Path(root)
    result = json.loads((directory/'metadata.json').read_text())
    probe = root/'results/lab'/result['simulation_id']
    geometry = list(json_lines(directory/'geometry.jsonl'))
    heartbeat = list(json_lines(directory/'heartbeat.jsonl'))
    classifications = []
    if (probe/'ping.log').exists():
        rows = ping_observations((probe/'ping.log').read_text())
        classifications = classify_observations(rows, geometry, heartbeat)
        atomic_json(directory/'classified-probes.json', classifications)
        result['service'] = analyze_directory(probe,
            baseline_path_available=bool((result.get('baseline') or {}).get('success')))
        result['probe_classifications'] = {name: sum(row['classification']==name for row in classifications)
            for name in ('service_available','no_geometric_path','loss_with_path','unknown_geometry')}
    else:
        result['service'] = None
    migrations = []
    for item in result['migrations']:
        evidence=directory/'migrations'/item['migration_id']/'handover.json'
        if not evidence.exists():evidence=directory/'migrations'/item['migration_id']/'operation/metadata.json'
        if evidence.exists():
            saved=json.loads(evidence.read_text())
            item={**saved,**item}
        item=read_result(item)
        if item.get('migration_start_unix_s') is not None and (probe/'ping.log').exists():
            item['probes']=analyze_directory(probe,migration_start_unix_s=item['migration_start_unix_s'],
                observation_end_unix_s=item.get('probe_window_end_unix_s'),
                baseline_path_available=bool((result.get('baseline') or {}).get('success')))
        event = item['event']
        transfers = [r['receipt'] for r in item.get('events',[]) if r['phase']=='transfer_verified']
        finished = next((r['orbital_s'] for r in reversed(item.get('events',[])) if r['phase']=='completed'), None)
        migrations.append({key: value for key,value in dict(
            migration_id=item['migration_id'], source_norad=event['sat_a'], target_norad=event['sat_b'],
            source_slot=item['source_slot'], target_slot=item['target_slot'], success=item['success'],
            attempts=item.get('attempt'), controller_downtime_s=item.get('controller_downtime_s'),
            total_operation_s=item.get('total_operation_s'), deadline_margin_s=event['deadline_s']-finished if finished is not None else None,
            payload_received_bytes=sum(t['received_bytes'] for t in transfers),
            minimum_payload_throughput_bps=min((t['useful_throughput_bps'] for t in transfers),default=None),
            failure_reason=item.get('failure_reason'),
            migration_completed=item.get('migration_completed'),experimental_valid=item.get('experimental_valid'),
            observation_complete=item.get('observation_complete'),recovery_required=item.get('recovery_required'),
            **{key:value for key,value in summary_metrics(item).items() if key not in ('controller_downtime_s','total_operation_s')}).items()})
    physical=[]
    for sample in json_lines(directory/'resources.jsonl'):
        for slot,values in sample['hosts'].items():
            physical.append({'timestamp_utc':sample['timestamp_utc'],'slot':slot,**values})
    with (directory/'physical-resources.csv').open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,['timestamp_utc','slot','running_containers','cpu_cores','ram_gib'])
        writer.writeheader();writer.writerows(physical)
    result['physical_slot_resources']={slot:{
        'peak_cpu_cores':max((r['cpu_cores'] for r in physical if r['slot']==slot),default=None),
        'peak_ram_gib':max((r['ram_gib'] for r in physical if r['slot']==slot),default=None)}
        for slot in ('sat-a','sat-b')}
    result['migration_summary'] = migrations
    result['metric_provenance'] = {
        'controller_downtime_s': {'origin':'measured', 'unit':'s', 'definition':'Successful attempt stop/freeze to confirmed cutover; failed attempts and rollback remain in timeline'},
        'service': {'origin':'measured', 'units':{'ping':'ms','udp_throughput':'bit/s'},
            'limits':'Probe sampling bounds outages; ten successes confirm recovery and are not exact downtime. Geometry gaps are classified separately; loss with a path does not establish migration causality.'},
        'modeled_satellite_resources': {'origin':'modeled','unit':'fraction','policy_version':result['policy_version']},
        'resources.jsonl': {'origin':'measured','scope':'two physical Docker slots, not seventeen satellite machines'},
        'missing_values': 'null/empty CSV cells, never inferred zero'}
    atomic_json(directory/'report.json', result)
    with (directory/'migrations.csv').open('w',encoding='utf-8',newline='') as handle:
        fields = list(migrations[0]) if migrations else ['migration_id','source_norad','target_norad','success']
        writer = csv.DictWriter(handle, fields); writer.writeheader(); writer.writerows(migrations)
    with (directory/'observations.csv').open('w',encoding='utf-8',newline='') as handle:
        fields = ['orbital_s','real_elapsed_s','controller_satellite','active_slot','elapsed_s','remaining_s','completed_migrations']
        writer=csv.DictWriter(handle, fields, extrasaction='ignore'); writer.writeheader()
        writer.writerows(json_lines(directory/'observations.jsonl'))
    # Resource samples include the satellite identity and policy; physical samples stay separate.
    with (directory/'modeled-resources.csv').open('w',encoding='utf-8',newline='') as handle:
        fields=['orbital_s','satellite_id','projected_cpu_fraction','projected_ram_fraction','projected_disk_fraction','policy_version']
        writer=csv.DictWriter(handle,fields,extrasaction='ignore');writer.writeheader()
        for observation in json_lines(directory/'observations.jsonl'):
            for node in observation['modeled_satellite_resources']:
                writer.writerow({'orbital_s':observation['orbital_s'],**node})
    try:
        from .simulation_plots import plots
        plots(directory,result)
    except Exception as exc:
        result['plot_error']=str(exc)
        for name in ('downtime.svg','controller-history.svg'):
            (directory/name).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 100"><text x="10" y="40">Grafico non disponibile: '+html.escape(str(exc))+'</text></svg>',encoding='utf-8')
        atomic_json(directory/'report.json',result)
    escaped=lambda value:html.escape(str(value))
    rows=''.join('<tr>'+''.join('<td>'+escaped(row.get(k) if row.get(k) is not None else 'â€”')+'</td>' for k in ('source_norad','target_norad','source_slot','target_slot','success','controller_downtime_s','deadline_margin_s'))+'</tr>' for row in migrations)
    document=f'''<!doctype html><html lang="it"><meta charset="utf-8"><title>Sessione {escaped(result['simulation_id'])}</title>
<h1>Simulazione continua TeraFlow</h1><p>{escaped(result['simulation_id'])}</p>
<p>Esito: {escaped(result['outcome'])}. {escaped(result.get('failure_reason',''))}</p>
<p>Baseline: {escaped(result.get('baseline'))}</p><h2>Cronologia del controller</h2>
<pre>{escaped(json.dumps(result['controller_history'],indent=2))}</pre><h2>Migrazioni</h2>
<table border="1"><tr><th>NORAD sorgente</th><th>NORAD destinazione</th><th>Slot sorgente</th><th>Slot destinazione</th><th>Riuscita</th><th>Downtime controller (s)</th><th>Margine (s)</th></tr>{rows}</table>
<img src="downtime.svg" alt="Downtime del controller per migrazione"><h2>Servizio e attribuzione</h2>
<pre>{escaped(json.dumps(result.get('service'),indent=2))}</pre><p>Le interruzioni geometriche sono distinte dalle perdite con percorso disponibile. Il tempo di conferma di dieci risposte non Ã¨ il downtime esatto.</p>
<h2>Metriche, unitÃ  e limiti</h2><pre>{escaped(json.dumps(result['metric_provenance'],indent=2))}</pre>
<p>Report JSON completo: report.json. Tabelle: migrations.csv, observations.csv e modeled-resources.csv. Risorse fisiche: resources.jsonl. Piano iniziale e revisioni: plans/. Dettagli di errori, ricevute e recuperi: migrations/.</p></html>'''
    (directory/'report.html').write_text(document,encoding='utf-8')
    return result
