import json
import tempfile
import unittest
import threading
from pathlib import Path
from unittest.mock import patch, Mock

from src.resource_diagnostic import Collector, DiagnosticClock, identity, number, stats, run_pair, analyze, parse_stats_line, plot_points
from src.deployment import PROJECT, ROLE_LABEL


class ResourceDiagnosticTests(unittest.TestCase):
    def test_plot_never_interpolates_stopped_or_replaced_containers(self):
        rows=[{'monotonic_s':t,'cpu_cores':1,'container_id':cid} for t,cid in
              [(1,'a'),(2,'a'),(20,'a'),(21,'b')]]
        xs,ys=plot_points(rows,1)
        self.assertEqual(ys,[1,1,None,1,None,1])
    def test_slow_inventory_does_not_block_stream_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Collector(tmp,tmp)
            c.identities={'a':{'container_id':'a','slot':'sat-a','service':'sat-a-kafka','category':'dependency'}}
            accepted=threading.Event(); release=threading.Event(); refreshing=threading.Event()
            original=c.accept
            def accept(row): original(row);accepted.set()
            c.accept=accept
            count=[0]
            def refresh():
                count[0]+=1
                if count[0]>1: refreshing.set();release.wait(5)
            c.refresh=refresh
            class Stream:
                def __iter__(self):
                    refreshing.wait(4)
                    yield '{"ID":"a","CPUPerc":"100%","MemUsage":"1GiB / 8GiB"}'
                    release.wait(5)
                def close(self): pass
            process=Mock();process.stdout=Stream();process.poll.return_value=None
            with patch('src.resource_diagnostic.subprocess.Popen',return_value=process):
                c.start()
                try:
                    self.assertTrue(refreshing.wait(4))
                    self.assertTrue(accepted.wait(1),'inventory blocked resource samples')
                finally:
                    release.set();c.close()
    def test_docker_stream_separators_and_malformed_data(self):
        self.assertIsNone(parse_stats_line('\x1b[2J\x1b[H\n'))
        self.assertIsNone(parse_stats_line('\n'))
        self.assertEqual(parse_stats_line('{"ID":"a"}\n'),{'ID':'a'})
        with self.assertRaises(ValueError): parse_stats_line('bad json')

    def test_historical_detail_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=analyze(tmp)
            self.assertFalse(result['complete']);self.assertFalse(result['detail_available'])
    def test_conversion_missing_values_and_percentile(self):
        self.assertAlmostEqual(number('408.17%'),4.0817)
        self.assertEqual(number('1GiB / 8GiB',True),1)
        self.assertIsNone(number('--'))
        self.assertIsNone(number(None,True))
        self.assertEqual(stats([None,1,2,3,4])['p95'],3)

    def test_label_identity_excludes_foreign_and_classifies_dependencies(self):
        row={'Id':'abc','Config':{'Labels':{'com.docker.compose.project':PROJECT,
            ROLE_LABEL:'sat-a','com.docker.compose.service':'sat-a-contextservice'}}}
        self.assertEqual(identity(row)['category'],'workload')
        row['Config']['Labels']['com.docker.compose.service']='sat-a-kafka'
        self.assertEqual(identity(row)['category'],'dependency')
        row['Config']['Labels']['com.docker.compose.project']='other'
        self.assertIsNone(identity(row))

    def test_replacement_overlap_missing_and_foreign_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Collector(tmp,tmp)
            c.identities={'old':{'container_id':'old','slot':'sat-a','service':'sat-a-contextservice','category':'workload'}}
            with c.operation('restore','sat-b'):
                with c.operation('topology_update','sat-a'):
                    c.accept({'ID':'old','CPUPerc':'120%','MemUsage':'1GiB / 8GiB'})
            c.identities={'new':{**c.identities['old'],'container_id':'new'}}
            c.accept({'ID':'old','CPUPerc':'500%'})
            c.accept({'ID':'new','CPUPerc':'--','MemUsage':'--'})
            rows=[json.loads(l) for l in (Path(tmp)/'container-resources.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),2)
            self.assertEqual(len(rows[0]['operations']),2)
            self.assertIsNone(rows[1]['cpu_cores'])
            self.assertTrue(c.errors)

    def test_frozen_orbit_does_not_freeze_wall_clock(self):
        with patch('src.resource_diagnostic.time.monotonic',return_value=100) as t:
            c=DiagnosticClock(400)
            t.return_value=280
            self.assertEqual(c.orbital(),400)
            self.assertEqual(c.now(),180)
            c.resume();t.return_value=310
            self.assertEqual(c.orbital(),430)
            c.freeze();t.return_value=430
            self.assertEqual(c.orbital(),430)

    def test_close_terminates_and_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Collector(tmp,tmp);c.process=Mock();c.thread=Mock()
            c.process.poll.return_value=None;c.thread.is_alive.return_value=False
            c.close();c.process.terminate.assert_called_once();c.process.wait.assert_called_once()
            c.thread.join.assert_called_once()

    def test_recovery_stops_pair_and_preserves_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Mock();app.root=Path(tmp);app.scenario={}
            app.functional_event.return_value={};app.bundle.return_value={}
            app.run.return_value={'success':False,'recovery_required':True,'method':'hot','run_id':'r','directory':tmp}
            with patch('src.simulation.engine_fingerprint',return_value='fingerprint'):
                result=run_pair(app)
            app.run.assert_called_once()
            self.assertTrue(result['recovery_required']);self.assertFalse(result['complete'])

    def test_analysis_windows_gap_and_csv_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);events=[];rows=[]
            for phase,slot,start in [('settling','sat-a',0),('source_stable','sat-a',60),('target_stable','sat-b',180)]:
                duration=60 if phase=='settling' else 120
                events.extend([{'kind':'phase_start','phase':phase,'monotonic_s':start},
                               {'kind':'phase_end','phase':phase,'monotonic_s':start+duration}])
                ids=[slot+str(i) for i in range(9)]
                for t in range(start+1,start+duration,2):
                    for cid in ids:
                        rows.append(dict(container_id=cid,expected_container_ids=ids,batch=t,slot=slot,
                            service=cid,phase=phase,monotonic_s=t,timestamp_utc='2026-01-01T00:00:00Z',
                            cpu_cores=8 if phase=='settling' else .1,ram_gib=.1,category='workload'))
            (p/'container-resources.jsonl').write_text('\n'.join(map(json.dumps,rows)))
            (p/'resource-phases.jsonl').write_text('\n'.join(map(json.dumps,events)))
            (p/'resource-collection.json').write_text('{"errors":[]}')
            result=analyze(p)
            self.assertTrue(result['complete'])
            stable=[r for r in result['slot_summaries'] if r['phase']=='source_stable'][0]
            self.assertAlmostEqual(stable['maximum'],.9)
            import csv
            with (p/'resource-slot-summary.csv').open(encoding='utf-8') as handle:
                csvrows=list(csv.DictReader(handle))
            self.assertAlmostEqual(float(next(r for r in csvrows if r['phase']=='source_stable')['maximum']),stable['maximum'])
            self.assertTrue((p/'resource-timeline.svg').exists())
            rows=[r for r in rows if not (r['phase']=='source_stable' and 90<r['monotonic_s']<100)]
            (p/'container-resources.jsonl').write_text('\n'.join(map(json.dumps,rows)))
            self.assertFalse(analyze(p)['complete'])


if __name__=='__main__':unittest.main()
