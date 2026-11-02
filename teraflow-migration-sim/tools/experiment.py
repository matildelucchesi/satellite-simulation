"""Shared CLI for genuine live operations, calibration and analyses."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).absolute().parents[1]
sys.path.insert(0,str(ROOT))
from src.jobs import JobManager,OPERATIONS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',nargs='?',choices=sorted(OPERATIONS|{'jobs','stop'}))
    parser.add_argument('--worker')
    parser.add_argument('--method',choices=['cold','hot'],default='hot')
    parser.add_argument('--rate-bps',type=int,choices=[100000000,1000000000,10000000000],default=1000000000)
    parser.add_argument('--event-id')
    parser.add_argument('--base-id')
    parser.add_argument('--duration-s',type=int,default=3600)
    parser.add_argument('--start-orbital-s',type=int)
    parser.add_argument('--initial-satellite-id',type=int)
    parser.add_argument('--max-migrations',type=int)
    parser.add_argument('--job-id')
    parser.add_argument('--wait',action='store_true')
    args=parser.parse_args();manager=JobManager(ROOT)
    if args.worker:manager.work(args.worker);return 0
    if args.operation=='jobs':print(json.dumps(manager.list(),indent=2));return 0
    if args.operation=='stop':manager.stop(args.job_id);return 0
    if not args.operation:parser.error('Choose an operation')
    parameters={'method':args.method,'rate_bps':args.rate_bps}
    if args.event_id:parameters['event_id']=args.event_id
    if args.operation=='simulate':
        parameters.update(duration_s=args.duration_s,start_orbital_s=args.start_orbital_s,
            initial_satellite_id=args.initial_satellite_id,max_migrations=args.max_migrations)
    if args.operation=='compare_continuous':
        if args.start_orbital_s is not None or args.initial_satellite_id is not None:
            parser.error('La partenza è esclusivamente automatica')
        parameters={'rate_bps':args.rate_bps,'migration_count':3}
        if args.base_id:parameters['base_id']=args.base_id
    job=manager.start(args.operation,parameters if args.operation in ('run','simulate','compare_continuous') else {})
    print(json.dumps(job,indent=2),flush=True)
    if args.wait:
        previous=None
        while job['status'] in ('queued','running'):
            time.sleep(1);job=manager.get(job['job_id'])
            path=manager.directory/job['job_id']/'events.jsonl'
            if path.exists():
                lines=path.read_text(encoding='utf-8').splitlines()
                if lines and lines[-1]!=previous:print(lines[-1],flush=True);previous=lines[-1]
        print(json.dumps(job,indent=2))
        return 0 if job['status']=='completed' and job.get('application_success') else 2
    return 0


if __name__=='__main__':raise SystemExit(main())
