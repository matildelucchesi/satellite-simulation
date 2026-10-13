"""Saved-data analysis, explicitly separate from live observations."""
import copy
import csv
import html
import json
import math
from dataclasses import asdict
from .events import generate_events
from .event_sampling import select_percentile_events
from .migration_model import evaluate
from .storage import atomic_json, utc_now


def variations(scenario):
    for name,profile in [('limited',{'cpu_cores':4,'ram_gib':8,'disk_gib':60}),
                         ('ample',{'cpu_cores':8,'ram_gib':32,'disk_gib':120})]:
        changed=copy.deepcopy(scenario);changed['controller']['resource_profile']=profile
        yield 'profile_'+name,changed
    for field,values in [('resource_reserve_fraction',(.1,.3)),('resource_clear_fraction',(.65,.75)),
                         ('resource_forecast_horizon_factor',(1.,1.5))]:
        for value in values:
            changed=copy.deepcopy(scenario);changed['controller'][field]=value
            yield field+'_'+str(value),changed
    weights=scenario['score']['weights']
    for name,weight in weights.items():
        for delta in (-.05,.05):
            changed=copy.deepcopy(scenario)
            changed['score']['weights']={key:weight+delta if key==name else value*(1-weight-delta)/(1-weight)
                for key,value in weights.items()}
            yield 'weight_'+name+'_'+str(delta),changed


class Analysis:
    def sensitivity(self):
        manifest=json.loads((self.root/'config/artifact_manifest.json').read_text())
        workload=self.workload(manifest)
        frozen=json.loads((self.root/'config/selected_events.json').read_text())['events']
        resources={key:manifest['resources']['measured_controller_'+key] for key in ('cpu_cores','ram_gib','disk_gib')}
        slowest=max(evaluate(workload,mode,rate,self.scenario['fso']['alignment_s'],1e12,1e12).total_operation_s
            for mode in ('cold','hot') for rate in self.scenario['fso']['useful_throughput_bps'])
        output={'execution_kind':'calibrated-model-sensitivity','created_utc':utc_now(),'variations':[]}
        for name,scenario in variations(self.scenario):
            if self.cancel and self.cancel.is_set():return {**output,'complete':False,'reason':'interrupted'}
            horizon=math.ceil(slowest*scenario['controller']['resource_forecast_horizon_factor'])
            self.publish({'phase':'sensitivity','variation':name})
            events=generate_events(self.orbit,scenario,horizon,resources)
            eligible=[row for row in events if row['migrable']]
            selected=select_percentile_events(eligible) if len(eligible)>=3 else []
            # Main frozen events retain A/B/trigger. Report changed eligibility
            # separately; never silently replace a paired destination.
            free=min(1-.4-resources['cpu_cores']/scenario['controller']['resource_profile']['cpu_cores'],
                1-.45-resources['ram_gib']/scenario['controller']['resource_profile']['ram_gib'],
                1-resources['disk_gib']/scenario['controller']['resource_profile']['disk_gib'])
            comparison=[]
            for event in frozen:
                for mode in ('cold','hot'):
                    for rate in scenario['fso']['useful_throughput_bps']:
                        comparison.append({'event_id':event['event_id'],'frozen_destination_eligible':
                            free>=scenario['controller']['resource_reserve_fraction'],
                            **asdict(evaluate(workload,mode,rate,scenario['fso']['alignment_s'],
                                event['contact_window_s'],event['deadline_window_s']))})
            output['variations'].append({'name':name,'horizon_s':horizon,'scenario':scenario,
                'event_count':len(events),'eligible_count':len(eligible),'selected_events':selected,
                'events':events,'frozen_event_comparison':comparison,
                'note':'Clear threshold has no effect on a monotone ramp with one first event per period'
                    if name.startswith('resource_clear_fraction') else None})
            atomic_json(self.root/'results/sensitivity.json',output)
        output['complete']=True;atomic_json(self.root/'results/sensitivity.json',output)
        return {'complete':True,'variations':len(output['variations']),'path':str(self.root/'results/sensitivity.json')}

    def report(self):
        runs=[json.loads(p.read_text()) for p in sorted((self.root/'results/runs').glob('run-*/metadata.json'))]
        primary=[row for row in runs if row['purpose']=='primary']
        combinations={(r.get('event',{}).get('event_id'),r['method'],r['configured_rate_bps']) for r in primary}
        primary_complete=len(combinations)==18 and all(r.get('outcome')!='running' for r in primary)
        fields=['run_id','purpose','method','configured_rate_bps','outcome','success','ack',
                'total_operation_s','controller_downtime_s','image_throughput_bps','attempt',
                'bytes_sent','bytes_received','restarted_payload_bytes','failure_reason']
        directory=self.root/'results/report';directory.mkdir(parents=True,exist_ok=True)
        with (directory/'runs.csv').open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
            writer.writerows({key:row.get(key) for key in fields} for row in runs)
        summary={'schema_version':1,'created_utc':utc_now(),'runs':runs,'primary_count':len(primary),
            'expected_primary_count':18,'primary_complete':primary_complete,'unique_primary_cases':len(combinations),
            'interpretation':'Representative cases with one replica per combination; no statistical significance claim',
            'measurement_limits':['Shared Docker daemon: image load may reuse local layers',
                'TCP retransmission counters unavailable; payload restart bytes measured separately',
                'Orbit, FSO and synthetic source load modeled; operations and probes measured live']}
        atomic_json(directory/'report.json',summary)
        columns=['run_id','purpose','method','configured_rate_bps','outcome','controller_downtime_s']
        rows=''.join('<tr>'+''.join('<td>'+html.escape(str(row.get(key,'—')))+'</td>' for key in columns)+'</tr>' for row in runs)
        document='<!doctype html><html lang="it"><meta charset="utf-8"><title>Risultati TeraFlow</title><style>body{font:16px system-ui;margin:3rem;color:#172b34}table{border-collapse:collapse;width:100%}td,th{padding:.7rem;text-align:left;border-bottom:1px solid #ddd}img{max-width:100%}</style><h1>Esperimento di migrazione TeraFlowSDN</h1>'
        document+=f'<p>Prove principali registrate: {len(primary)}/18. Una replica per caso rappresentativo.</p>'
        document+='<p>'+html.escape(summary['interpretation'])+'</p><ul>'+''.join('<li>'+html.escape(x)+'</li>' for x in summary['measurement_limits'])+'</ul>'
        document+='<table><thead><tr>'+''.join('<th>'+html.escape(x)+'</th>' for x in columns)+'</tr></thead><tbody>'+rows+'</tbody></table>'
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            measured=[row for row in runs if row.get('controller_downtime_s') is not None]
            if measured:
                figure,axis=plt.subplots(figsize=(max(7,len(measured)*.5),4))
                axis.bar(range(len(measured)),[r['controller_downtime_s'] for r in measured],
                    color=['#176b66' if r['method']=='hot' else '#a35435' for r in measured])
                axis.set_ylabel('Controller downtime (s)');axis.set_xticks(range(len(measured)),
                    [r['method']+' '+r['run_id'][-6:] for r in measured],rotation=60,ha='right')
                axis.set_ylim(bottom=0);axis.grid(axis='y',alpha=.25);figure.tight_layout()
                figure.savefig(directory/'controller-downtime.svg');plt.close(figure)
                document+='<h2>Downtime misurato del controller</h2><img src="controller-downtime.svg" alt="Downtime controller in secondi per run">'
            from .report_plots import plots
            for filename,label in plots(directory,runs):
                document+='<h2>'+html.escape(label)+'</h2><img src="'+filename+'" alt="'+html.escape(label)+'">'
        except ImportError:summary['plot_unavailable']='matplotlib is not installed'
        atomic_json(directory/'report.json',summary)
        (directory/'index.html').write_text(document+'</html>',encoding='utf-8')
        return {'complete':True,'primary_complete':primary_complete,'path':str(directory/'index.html'),'run_count':len(runs)}
