"""Run the real three-rate acceptance sequence, stopping at the first failure.

No retries, simulated clocks or synthetic measurements are used by this tool.
Existing comparisons may also be checked without launching a laboratory job.
"""
import argparse
import csv
import hashlib
import json
import math
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.artifacts import canonical_bytes
from src.jobs import JobManager, process_running
from src.storage import atomic_json, utc_now


class EventTable(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.table=False;self.finished=False;self.cell=False;self.row=[];self.text=''

    def handle_starttag(self, tag, attrs):
        if tag=='table' and not self.finished:self.table=True
        if self.table and tag=='tr':self.row=[]
        if self.table and tag=='td':self.cell=True;self.text=''

    def handle_data(self, data):
        if self.cell:self.text+=data

    def handle_endtag(self, tag):
        if tag=='td' and self.cell:self.row.append(self.text.strip());self.cell=False
        if tag=='tr' and self.table and self.row:self.rows.append(self.row)
        if tag=='table' and self.table:self.table=False;self.finished=True


def check_comparison(root, identifier, count=3):
    directory=root/'results/continuous-comparisons'/identifier
    pair=json.loads((directory/'metadata.json').read_text())
    if not pair.get('success') or not pair.get('complete'):
        raise AssertionError(pair.get('reason') or 'Comparison incomplete')
    plan=json.loads((directory/'plan.json').read_text())
    digest=hashlib.sha256(canonical_bytes(plan)).hexdigest()
    assert pair['shared_plan_sha256']==digest, 'Shared plan digest mismatch'
    if pair.get('selection'):
        selected=pair['selection']['selected']
        assert plan['start_s']==selected['start_orbital_s'] and plan['initial_satellite_id']==selected['initial_satellite_id'], 'Automatic departure mismatch'
        assert plan.get('service_path_policy'), 'Missing geometric service continuity policy'
        assert all(event['service_path_end_s']>=event['trigger_s']+event['estimated_operation_s']
            for event in plan['migrations']), 'Service path does not cover migration'
    assert len(pair['events'])==count and all(row.get('comparable') for row in pair['events']), 'Invalid paired events'
    assert [e['event_id'] for e in pair['events']]==[e['event_id'] for e in plan['migrations']], 'Events differ from shared plan'
    with (directory/'events.csv').open(encoding='utf-8',newline='') as handle:
        csv_rows=list(csv.DictReader(handle))
    assert len(csv_rows)==count, 'CSV row count mismatch'
    by_id={row['event_id']:row for row in csv_rows}
    table=EventTable();table.feed((directory/'report.html').read_text(encoding='utf-8'))
    assert len(table.rows)==count, 'HTML event count mismatch'
    html_rows={row[0]:row for row in table.rows}
    sessions={}
    for mode in ('hot','cold'):
        session_dir=root/'results/simulations'/pair['sessions'][mode]
        child=json.loads((session_dir/'metadata.json').read_text())
        assert not child.get('report_error'), 'Session export failed'
        assert child['success'] and child['complete'] and child['baseline']['success'], mode+' session invalid'
        assert child['shared_plan_sha256']==digest, mode+' plan mismatch'
        assert child['parameters']['rate_bps']==pair['parameters']['rate_bps'], mode+' rate mismatch'
        assert json.loads((session_dir/'plans/initial.json').read_text())==plan, mode+' schedule changed'
        assert child['controller_history'][0]['satellite_id']==plan['initial_satellite_id'], mode+' start satellite mismatch'
        assert child['start_s']==plan['start_s'], mode+' start clock mismatch'
        assert len(child['migrations'])==count, mode+' migration count mismatch'
        for row in child['migrations']:
            assert row['success'] and row['experimental_valid'] is True and row['observation_complete'] is True, mode+' invalid measurement'
            assert row['service_verification']['success'] is True, mode+' forwarding not verified'
        sessions[mode]=child['simulation_id']
        assert pair['totals'][mode]['completed_migrations']==count, mode+' total count mismatch'
        total=sum(row[mode]['controller_downtime_s'] for row in pair['events'])
        assert math.isclose(pair['totals'][mode]['controller_downtime_s'],total,rel_tol=1e-9,abs_tol=1e-9), mode+' total mismatch'
    for event in pair['events']:
        row=by_id[event['event_id']]
        assert row['shared_plan_sha256']==digest and row['comparable']=='True', 'CSV provenance mismatch'
        for mode in ('hot','cold'):
            for metric in ('controller_downtime_s','service_verification_s','ping_recovery_s'):
                recorded=event[mode].get(metric); exported=row[mode+'_'+metric]
                assert (exported=='' if recorded is None else math.isclose(float(exported),recorded,rel_tol=1e-9,abs_tol=1e-9)), 'CSV metric mismatch'
        expected=event['cold']['controller_downtime_s']-event['hot']['controller_downtime_s']
        assert math.isclose(float(row['cold_minus_hot_s']),expected,rel_tol=1e-9,abs_tol=1e-9), 'False Hot/Cold difference'
        rendered=html_rows[event['event_id']]
        for index, recorded in ((4,event['hot']['controller_downtime_s']),(5,event['cold']['controller_downtime_s']),
                                (6,expected),(7,event['hot'].get('ping_recovery_s')),(8,event['cold'].get('ping_recovery_s'))):
            assert (rendered[index]=='—' if recorded is None else math.isclose(float(rendered[index]),recorded,rel_tol=1e-9,abs_tol=1e-9)), 'HTML metric mismatch'
    return {'comparison_id':identifier,'rate_bps':pair['parameters']['rate_bps'],
            'departure':{'initial_satellite_id':plan['initial_satellite_id'],'start_orbital_s':plan['start_s']},
            'shared_plan_sha256':digest,'sessions':sessions,'comparable_events':count,
            'totals':pair['totals'],'verified_utc':utc_now(),'success':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Explicitly launch the real laboratory sequence')
    parser.add_argument('--comparison',help='Only verify one existing comparison')
    parser.add_argument('--resume-job',help='Observe an already launched first-rate job; never restart it')
    parser.add_argument('--rates',type=int,nargs='+',default=[100000000,1000000000,10000000000],
                        choices=[100000000,1000000000,10000000000])
    args=parser.parse_args()
    if args.comparison:
        print(json.dumps(check_comparison(ROOT,args.comparison),indent=2));return 0
    if not args.live: parser.error('Choose --comparison or --live')
    folder=ROOT/'results/guided-validation'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    summary={'started_utc':utc_now(),'requested_rates':args.rates,'complete':False,'runs':[]}
    manager=JobManager(ROOT)
    try:
        for index, rate in enumerate(args.rates):
            if args.resume_job and index == 0:
                job=manager.get(args.resume_job)
                if job['parameters'].get('rate_bps')!=rate or job['parameters'].get('migration_count')!=3:
                    raise ValueError('Resumed job does not match the acceptance parameters')
            else:
                automatic={'selection_rates':args.rates} if index==0 else {'selection_id':summary['runs'][0]['comparison_id']}
                job=manager.start('compare_continuous',{'rate_bps':rate,'migration_count':3,**automatic})
            row={'job_id':job['job_id'],'rate_bps':rate};summary['runs'].append(row)
            atomic_json(folder/'summary.json',summary)
            print(json.dumps(row),flush=True)
            previous=None
            while job['status'] in ('queued','running'):
                time.sleep(2);job=manager.get(job['job_id'])
                progress=job.get('progress') or {}
                key=tuple(progress.get(k) for k in ('phase','subphase','method','replica','operation_status','completed_migrations'))
                if key!=previous:
                    print(json.dumps({'job_id':job['job_id'],'progress':progress},ensure_ascii=False),flush=True)
                    previous=key
                if job['status']=='running' and job.get('worker_pid') and not process_running(job['worker_pid']):
                    raise RuntimeError('Worker stopped without terminal evidence; explicit recovery required')
            result=json.loads((manager.directory/job['job_id']/'result.json').read_text())
            row.update(comparison_id=result.get('comparison_id'),worker_status=job['status'])
            checked=check_comparison(ROOT,result['comparison_id'])
            if index==0:summary['departure']=checked['departure']
            elif checked['departure']!=summary['departure']:
                raise AssertionError('The three rates do not share one automatic departure')
            row.update(checked);atomic_json(folder/'summary.json',summary)
        summary['complete']=True
    except Exception as exc:
        summary['failure']=str(exc)
        summary['failure_type']=type(exc).__name__
        summary['traceback']=traceback.format_exc()
        print(str(exc),file=sys.stderr,flush=True)
    finally:
        summary['finished_utc']=utc_now();atomic_json(folder/'summary.json',summary)
        print('Validation evidence: '+str(folder/'summary.json'),flush=True)
    return 0 if summary['complete'] else 2


if __name__=='__main__': raise SystemExit(main())
