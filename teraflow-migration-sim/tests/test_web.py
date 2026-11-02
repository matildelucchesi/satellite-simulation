import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from src.web import make_server
from src.storage import atomic_json,append_json


class LocalWebTests(unittest.TestCase):
    def test_historical_geometry_uses_archived_constellation(self):
        from types import SimpleNamespace
        app=self.server.application;app.orbit=SimpleNamespace(ids=[1,2,3])
        directory=self.root/'historical';atomic_json(directory/'inputs.json',{'scenario':{'orbital':{'satellites_total':2}}})
        archive=self.root/'artifacts/constellation-profiles/old/original'
        atomic_json(archive/'config/selected_constellation.json',{'satellites':[{'norad_id':1},{'norad_id':2}]})
        replay=archive/'artifacts/orbit/replay.npz';replay.parent.mkdir(parents=True);replay.write_bytes(b'fixture')
        with patch('src.orbit.Orbit',return_value=SimpleNamespace(ids=[1,2])) as load:
            view=app.historical_geometry(directory)
        self.assertIsNot(view,app);self.assertEqual(view.orbit.ids,[1,2])
        self.assertEqual(app.orbit.ids,[1,2,3]);load.assert_called_once_with(replay)

    def test_dead_worker_is_exposed_without_releasing_the_lab_lock(self):
        import time
        app=self.server.application
        identifier='job-'+'e'*32
        atomic_json(self.root/'config/scenario.json',{})
        atomic_json(app.jobs.guard,{'job_id':identifier,'worker_pid':999999})
        atomic_json(app.jobs.directory/identifier/'job.json',{'job_id':identifier,'status':'running'})
        app.cached_status={};app.cached_at=time.monotonic()
        with patch('src.web.process_running',return_value=False):
            status=app.status()
        self.assertIs(status['worker_alive'],False)
        self.assertEqual(status['lock']['job_id'],identifier)
        self.assertTrue(app.jobs.guard.exists())

    def test_simulation_readiness_explains_missing_preparation_and_deleted_evidence(self):
        application=self.server.application
        readiness=application.simulation_readiness()
        self.assertFalse(readiness['ready'])
        self.assertEqual(readiness['next_operation'],'functional')
        identifiers=['run-'+'a'*32,'run-'+'b'*32]
        atomic_json(self.root/'results/functional-gate.json',{'complete':True,
            'runs':[{'run_id':identifier} for identifier in identifiers]})
        self.assertEqual(application.simulation_readiness()['next_operation'],'functional')
        for identifier in identifiers:
            atomic_json(self.root/'results/runs'/identifier/'metadata.json',{'success':True})
        self.assertEqual(application.simulation_readiness()['next_operation'],'calibrate')
        self.assertFalse(application.simulation_readiness()['ready'])

    def test_simulation_readiness_requires_current_calibration_and_all_six_baselines(self):
        identifiers=['run-'+str(index)*32 for index in range(6)]
        calibration={'complete':True,'engine_fingerprint':'current','runs':identifiers,
            'manifest':{'path':'manifest'}}
        atomic_json(self.root/'results/calibration.json',calibration)
        for identifier in identifiers:
            atomic_json(self.root/'results/runs'/identifier/'metadata.json',
                {'success':True,'baseline':{'success':True}})
        bundle=self.root/'bundle.tar';bundle.write_bytes(b'images')
        atomic_json(self.root/'config/artifact_manifest.json',{'image_bundle':{
            'path':str(bundle),'bytes':6}})
        with patch('src.simulation.engine_fingerprint',return_value='current'), patch('src.preconditions.verify_artifact') as verify:
            self.assertTrue(self.server.application.simulation_readiness()['ready'])
            verify.assert_called_once_with(calibration['manifest'])
            (self.root/'results/runs'/identifiers[0]/'metadata.json').unlink()
            self.assertFalse(self.server.application.simulation_readiness()['ready'])
        with patch('src.simulation.engine_fingerprint',return_value='changed'):
            self.assertFalse(self.server.application.simulation_readiness()['ready'])

    def test_failed_service_baseline_is_visible_before_simulation_start(self):
        identifier='run-'+'a'*32
        atomic_json(self.root/'results/functional-gate.json',{'complete':False,'runs':[
            {'run_id':identifier,'outcome':'invalid_baseline'}]})
        atomic_json(self.root/'results/runs'/identifier/'metadata.json',{'baseline':{
            'last_ping':{'successful_probes':0,'observed_probes':194},'udp_received':0}})
        readiness=self.server.application.simulation_readiness()
        self.assertFalse(readiness['ready'])
        self.assertIn('0/194',readiness['reason'])
        self.assertIn('UDP ricevuti 0',readiness['reason'])

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.server=make_server(self.root,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temporary.cleanup()

    def session(self):
        with urlopen(self.url+'/api/v1/session',timeout=5) as response:
            return json.load(response)['token'],response.headers['Set-Cookie'].split(';')[0]

    def command(self,token=None,cookie=None,origin=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-CSRF-Token']=token
        if cookie:headers['Cookie']=cookie
        if origin:headers['Origin']=origin
        request=Request(self.url+'/api/v1/jobs',data=b'{"operation":"environment"}',headers=headers)
        return urlopen(request,timeout=5)

    def test_commands_require_session_and_same_origin(self):
        token,cookie=self.session()
        for args in ({},{'token':token},{'token':token,'cookie':cookie,'origin':'https://foreign.example'}):
            with self.assertRaises(HTTPError) as caught:self.command(**args)
            self.assertEqual(caught.exception.code,403)
        with patch.object(self.server.application.jobs,'start',return_value={'job_id':'example'}) as start:
            with self.command(token,cookie,self.url) as response:self.assertEqual(response.status,202)
            start.assert_called_once_with('environment',None)

    def test_sse_reconnect_replays_only_events_after_cursor(self):
        identifier='job-'+'a'*32;directory=self.root/'results/jobs'/identifier;directory.mkdir()
        atomic_json(directory/'job.json',{'job_id':identifier,'status':'completed'})
        for index in range(1,4):append_json(directory/'events.jsonl',{'id':index,'phase':'test','timestamp_utc':'2026-10-08T00:00:00+00:00'})
        request=Request(self.url+'/api/v1/jobs/'+identifier+'/events',headers={'Last-Event-ID':'1'})
        with urlopen(request,timeout=5) as response:body=response.read().decode()
        self.assertNotIn('id: 1\n',body);self.assertIn('id: 2\n',body);self.assertIn('id: 3\n',body)
        self.assertIn('event: end\n',body)
        payloads=[json.loads(line[6:]) for line in body.splitlines() if line.startswith('data: ')]
        self.assertEqual([row['id'] for row in payloads[:-1]],[2,3])
        self.assertEqual(payloads[-1],{'status':'completed'})

    def test_selected_comparison_job_exposes_its_saved_pair_not_the_latest_pair(self):
        identifier='job-'+'a'*32;directory=self.root/'results/jobs'/identifier
        atomic_json(directory/'job.json',{'job_id':identifier,'operation':'functional','status':'completed'})
        pair={'comparison_id':'compare-one','complete':True,'runs':[{'run_id':'hot'},{'run_id':'cold'}]}
        atomic_json(directory/'result.json',pair)
        atomic_json(self.root/'results/functional-gate.json',{'comparison_id':'compare-other','complete':False})
        with urlopen(self.url+'/api/v1/jobs/'+identifier,timeout=5) as response:
            self.assertEqual(json.load(response)['comparison'],pair)

    def test_downloads_only_registered_artifacts(self):
        atomic_json(self.root/'results/campaign.json',{'complete':False})
        with urlopen(self.url+'/api/v1/artifacts',timeout=5) as response:rows=json.load(response)['artifacts']
        self.assertEqual(len(rows),1)
        with urlopen(self.url+rows[0]['download_url'],timeout=5) as response:
            self.assertEqual(json.load(response),{'complete':False})
            self.assertIn('attachment',response.headers['Content-Disposition'])
        for path in ('/api/v1/artifacts/../../config/scenario.json','/../../secret','/api/v1/artifacts/unregistered'):
            with self.assertRaises(HTTPError) as caught:urlopen(self.url+path,timeout=5)
            self.assertEqual(caught.exception.code,404)

    def test_host_header_rebinding_is_rejected(self):
        request=Request(self.url+'/api/v1/session',headers={'Host':'foreign.example'})
        with self.assertRaises(HTTPError) as caught:urlopen(request,timeout=5)
        self.assertEqual(caught.exception.code,403)

    def test_simulation_history_observations_and_registered_report(self):
        identifier='sim-'+'a'*32;directory=self.root/'results/simulations'/identifier
        atomic_json(directory/'inputs.json',{'parameters':{}})
        atomic_json(directory/'metadata.json',{'simulation_id':identifier,'created_utc':'2026-10-15','outcome':'rejected'})
        append_json(directory/'observations.jsonl',{'orbital_s':10,'controller_satellite':53848})
        (directory/'report.html').write_text('<h1>Partial report</h1>')
        with urlopen(self.url+'/api/v1/simulations',timeout=5) as response:
            self.assertEqual(json.load(response)['simulations'][0]['simulation_id'],identifier)
        with urlopen(self.url+'/api/v1/simulations/'+identifier+'/observations',timeout=5) as response:
            self.assertEqual(json.load(response)['observations'][0]['orbital_s'],10)
        with urlopen(self.url+'/api/v1/artifacts',timeout=5) as response:
            self.assertTrue(any(row['label'].endswith('/report.html') for row in json.load(response)['artifacts']))
        with self.assertRaises(HTTPError) as caught:urlopen(self.url+'/api/v1/simulations/invalid',timeout=5)
        self.assertEqual(caught.exception.code,400)

    def test_planned_topology_uses_admitted_start_without_live_clock(self):
        identifier='sim-'+'c'*32;directory=self.root/'results/simulations'/identifier
        atomic_json(directory/'inputs.json',{})
        atomic_json(directory/'metadata.json',{'start_s':100})
        atomic_json(directory/'plans/initial.json',{'initial_satellite_id':53848,'migrations':[]})
        with patch.object(self.server.application,'topology',return_value={}) as topology:
            with urlopen(self.url+'/api/v1/simulations/'+identifier+'/topology',timeout=5) as response:
                data=json.load(response)
        topology.assert_called_once_with(tick=100)
        self.assertEqual(data['simulation']['placement_status'],'planned')
        self.assertIsNone(data['simulation']['active_slot'])

    def test_initial_configuration_assigns_lit_connected_host_and_stays_stationary(self):
        from types import SimpleNamespace
        self.server.application.orbit=SimpleNamespace(duration=86400)
        fixture={'orbital_s':0,'links':[[11,22],[11,33]],'nodes':[
            {'norad':11,'eclipsed':False,'next_transition_s':20},
            {'norad':22,'eclipsed':True,'next_transition_s':500},
            {'norad':33,'eclipsed':False,'next_transition_s':90},
            {'norad':44,'eclipsed':False,'next_transition_s':900}]}
        with patch.object(self.server.application,'topology',side_effect=lambda **kwargs:dict(fixture)) as topology:
            views=[]
            for _ in range(2):
                with urlopen(self.url+'/api/v1/initial-topology',timeout=5) as response:
                    views.append(json.load(response))
        self.assertEqual(views[0],views[1])
        self.assertIsNone(views[0]['initial_configuration'])
        self.assertIsNone(views[0]['presentation']['assigned_controller_satellite'])
        self.assertEqual(views[0]['presentation']['mode'],'preview')
        self.assertIsNone(views[0]['presentation']['controller_satellite'])
        topology.assert_called_with(tick=0)

    def test_initial_configuration_without_lit_connected_host_blocks_preview(self):
        from types import SimpleNamespace
        self.server.application.orbit=SimpleNamespace(duration=86400)
        with patch.object(self.server.application,'topology',return_value={
            'links':[], 'nodes':[{'norad':11,'eclipsed':False,'next_transition_s':20}]}):
            self.assertIsNone(self.server.application.initial_topology()['initial_configuration'])

    def test_explicit_initial_configuration_is_preserved_and_invalid_choices_are_rejected(self):
        from types import SimpleNamespace
        app=self.server.application;app.orbit=SimpleNamespace(duration=86400)
        fixture={'orbital_s':2979,'links':[[51726,53913]],'nodes':[
            {'norad':51726,'eclipsed':False,'next_transition_s':4000},
            {'norad':53913,'eclipsed':True,'next_transition_s':3100}]}
        with patch.object(app,'topology',side_effect=lambda **kwargs:dict(fixture)) as topology:
            with urlopen(self.url+'/api/v1/initial-topology?initial_satellite_id=51726&start_orbital_s=2979') as response:
                data=json.load(response)
            self.assertEqual(data['initial_configuration'],{'initial_satellite_id':51726,'start_orbital_s':2979})
            topology.assert_called_with(tick=2979)
            for host,tick in ((53913,2979),(99999,2979),(51726,-1),(51726,86400)):
                with self.subTest(host=host,tick=tick),self.assertRaises(ValueError):app.initial_topology(host,tick)

    def test_simulation_topology_advances_during_migration_without_new_session_sample(self):
        directory=self.root/'simulation'
        atomic_json(directory/'inputs.json',{})
        atomic_json(directory/'metadata.json',{'start_s':100,'phase':'migrating'})
        append_json(directory/'observations.jsonl',{'orbital_s':100,
            'controller_satellite':53848,'active_slot':'sat-a',
            'next_migration':{'sat_a':53848,'sat_b':53913}})
        append_json(directory/'geometry.jsonl',{'orbital_s':120,'forwarding_observed':False})
        (directory/'migrations/one/operation').mkdir(parents=True)
        append_json(directory/'migrations/one/operation/events.jsonl',{'orbital_s':110,
            'phase':'transfer','source_satellite':53848,'target_satellite':53913,
            'source_slot':'sat-a','target_slot':'sat-b'})
        with patch.object(self.server.application,'topology',return_value={}) as topology:
            data=self.server.application.simulation_topology(directory)
        topology.assert_called_once_with(tick=120)
        self.assertEqual(data['presentation']['migration_status'],'transferring')
        self.assertTrue(data['clock_running'])
        self.assertFalse(data['presentation']['forwarding_observed'])
        with patch.object(self.server.application,'topology',return_value={}):
            replay=self.server.application.simulation_topology(directory,105)
        self.assertEqual(replay['presentation']['migration_status'],'planned')
        self.assertEqual(replay['presentation']['mode'],'replay')
        self.assertFalse(replay['clock_running'])

    def test_live_motion_looks_ahead_in_geometry_without_changing_controller_evidence(self):
        from types import SimpleNamespace
        self.server.application.orbit=SimpleNamespace(duration=122)
        directory=self.root/'motion-session'
        atomic_json(directory/'inputs.json',{})
        atomic_json(directory/'metadata.json',{'start_s':100,'phase':'running'})
        append_json(directory/'observations.jsonl',{'orbital_s':120,'controller_satellite':53848,'active_slot':'sat-a'})
        def geometry(tick):return {'orbital_s':tick,'nodes':[{'norad':53848,'orbital_angle_rad':tick/100}],
                                   'presentation':{'controller_satellite':None}}
        with patch.object(self.server.application,'topology',side_effect=geometry) as topology:
            data=self.server.application.simulation_topology(directory)
        self.assertEqual([call.kwargs['tick'] for call in topology.call_args_list],[120,121])
        self.assertEqual(data['presentation']['controller_satellite'],53848)
        self.assertEqual(data['motion_frames'][0]['orbital_s'],121)
        self.assertGreater(data['motion_frames'][0]['nodes'][0]['orbital_angle_rad'],data['nodes'][0]['orbital_angle_rad'])
        with patch.object(self.server.application,'topology',side_effect=geometry) as topology:
            replay=self.server.application.simulation_topology(directory,120)
        topology.assert_called_once_with(tick=120)
        self.assertNotIn('motion_frames',replay)
        self.assertFalse(replay['clock_running'])

    def test_schematic_orbit_angles_advance_with_frozen_positions(self):
        import numpy as np
        from types import SimpleNamespace
        positions=np.array([[[np.cos(t/100),np.sin(t/100),0],
                             [np.cos(t/100),0,np.sin(t/100)]] for t in range(61)])
        self.server.application.orbit=SimpleNamespace(positions=positions,ids=[53913,53848],
            index={53913:0,53848:1},graph=lambda tick:{53913:{53848:1},53848:{53913:1}},
            operational=lambda sid,tick:True,
            illumination_window=lambda sid,tick:{'phase_start_s':0,'next_transition_s':45})
        atomic_json(self.root/'config/selected_constellation.json',{'satellites':[
            {'norad_id':53913,'plane':1,'phase_rank':0},
            {'norad_id':53848,'plane':2,'phase_rank':0}]})
        initial=self.server.application.topology(tick=0)
        later=self.server.application.topology(tick=30)
        self.assertAlmostEqual(initial['nodes'][0]['orbital_angle_rad'],0)
        self.assertAlmostEqual(later['nodes'][0]['orbital_angle_rad'],.3)
        self.assertEqual(later['nodes'][0]['next_transition_s'],45)
        self.assertIsNone(later['presentation']['controller_satellite'])

    def test_continuous_comparison_history_details_artifacts_and_validation(self):
        identifier='pair-'+'d'*32
        directory=self.root/'results/continuous-comparisons'/identifier
        document={'comparison_id':identifier,'created_utc':'2026-10-19','outcome':'running'}
        atomic_json(directory/'metadata.json',document)
        (directory/'report.html').write_text('<h1>Confronto</h1>')
        with urlopen(self.url+'/api/v1/continuous-comparisons',timeout=5) as response:
            self.assertEqual(json.load(response)['comparisons'],[document])
        with urlopen(self.url+'/api/v1/continuous-comparisons/'+identifier,timeout=5) as response:
            self.assertEqual(json.load(response),document)
        with urlopen(self.url+'/api/v1/artifacts',timeout=5) as response:
            self.assertTrue(any(row['label'].endswith(identifier+'/report.html') for row in json.load(response)['artifacts']))
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url+'/api/v1/continuous-comparisons/not-a-pair',timeout=5)
        self.assertEqual(caught.exception.code,400)
        self.server.application.jobs.validate('compare_continuous',{'duration_s':600})
        with self.assertRaises(ValueError):
            self.server.application.jobs.validate('compare_continuous',{'method':'cold'})

    def test_console_serves_only_paired_launch_and_orbit_script(self):
        source=Path(__file__).parents[1]/'web'
        (self.root/'web').mkdir()
        for name in ('index.html','app.js','orbit-view.js','experiment-state.js'):
            (self.root/'web'/name).write_bytes((source/name).read_bytes())
        with urlopen(self.url+'/',timeout=5) as response:
            document=response.read().decode('utf-8')
            self.assertNotIn('id="duration"',document)
            self.assertNotIn('id="additional-data"',document)
            self.assertIn('id="channel-rate"',document)
            self.assertIn('3 migrazioni verificate per HOT e 3 per COLD',document)
            self.assertLess(document.index('class="control"'),document.index('id="topology"'))
            self.assertLess(document.index('id="timeline"'),document.index('id="topology"'))
            self.assertIn('/experiment-state.js',document)
            self.assertLess(document.index('class="control"'),document.index('class="timeline"'))
            self.assertNotIn('id="operation"',document)
            self.assertNotIn('Funzioni avanzate',document)
        for asset in ('app.js','orbit-view.js','experiment-state.js'):
            with urlopen(self.url+'/'+asset,timeout=5) as response:
                self.assertEqual(response.status,200)
