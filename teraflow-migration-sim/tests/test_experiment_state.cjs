const {test}=require('node:test');
const assert=require('node:assert/strict');
const {experimentView}=require('../web/experiment-state.js');
const now=Date.parse('2026-10-20T14:00:30Z');
test('scenario loading shows completed entities after reconnect',()=>{
 const progress={phase:'preparation',subphase:'restore_scenario',restore_counts:{devices:{completed:20,total:64},links:{completed:0,total:120},services:{completed:0,total:1}},restore_entity:{name:'sat-53848'}};
 const view=experimentView({phase:'preparation'},{status:'running',progress},now);
 assert.match(view.detail,/20\/64/);assert.match(view.detail,/sat-53848/);
 assert.doesNotMatch(view.detail,/%/);
});
test('calibration exposes replica and a real operation deadline',()=>{
 const view=experimentView({phase:'calibration'},{status:'running',progress:{phase:'calibration',calibration_index:4,method:'hot',label:'Avvio controller',operation_status:'running',deadline_utc:'2026-10-20T14:03:00Z',last_progress_utc:'2026-10-20T14:00:00Z'},worker_heartbeat:{timestamp_utc:'2026-10-20T14:00:29Z'}},now);
 assert.match(view.detail,/4\/6.*HOT/);assert.equal(view.age,30);assert.equal(view.heartbeatAge,1);assert.ok(view.deadline);
});
test('worker completion does not turn a failed experiment into success',()=>{
 const view=experimentView({phase:'finished',success:false,reason:'invalid_baseline'},{status:'completed'},now);
 assert.equal(view.failed,true);assert.equal(view.title,'Confronto non completato');assert.equal(view.deadline,null);
});
test('legacy records do not invent progress or measurements',()=>{
 const view=experimentView({phase:'finished',success:false},{status:'completed'},now);
 assert.equal(view.age,null);assert.match(view.errorTitle,/Informazione non disponibile/);
});
test('cleanup failure keeps recovery visible',()=>{
 assert.equal(experimentView({phase:'finished',recovery_required:true},{status:'recovery_required'},now).recovery,true);
});
test('dead worker offers recovery without pretending the experiment completed',()=>{
 const view=experimentView({phase:'hot',success:false},{status:'recovery_required',worker_lost:true},now);
 assert.equal(view.title,'Ripristino necessario');assert.equal(view.recovery,true);assert.equal(view.terminal,false);
});
test('calibration displays the real operation after baseline preparation',()=>{
 const view=experimentView({phase:'calibration'},{progress:{phase:'calibration',calibration_index:1,method:'cold',subphase:'alignment'}},now,{alignment:'Allineamento FSO'});
 assert.match(view.detail,/Allineamento FSO/);
});
test('planning rejection has an Italian explanation without pretending recovery failed',()=>{
 const view=experimentView({phase:'finished',success:false,reason:'No feasible sequence in the requested frozen observation; inputs were not changed. Rejections: {}'},{status:'completed'},now);
 assert.equal(view.title,'Sequenza non ammissibile');assert.equal(view.admissionRejected,true);
 assert.equal(view.recovery,false);assert.match(view.errorTitle,/contatto, illuminazione e risorse/);
});
test('a failed recovery overrides the stale calibration phase and exposes its cause',()=>{
 const view=experimentView({phase:'calibration',success:false},{operation:'recover',status:'recovery_required',error:'Connection refused',progress:{worker_status:'recovery_required'}},now);
 assert.equal(view.title,'Ripristino necessario');assert.equal(view.recoveryFailed,true);
 assert.equal(view.error.technical_detail,'Connection refused');assert.match(view.detail,/laboratorio resta bloccato/);
});

test('automatic search exposes truthful progress and Italian exclusions',()=>{
 const view=experimentView({phase:'planning'},{status:'running',progress:{phase:'planning',subphase:'departure_search',examined_candidates:12,elapsed_s:3,limit_s:600,rejections:{insufficient_contact:2}}},now);
 assert.match(view.detail,/12 candidati/);assert.match(view.detail,/Contatto troppo breve/);
 assert.doesNotMatch(view.detail,/insufficient_contact/);
});
test('a session failure cannot be displayed as a plan refusal from old progress',()=>{
 const view=experimentView({phase:'finished',success:false,sessions:{hot:'sim-a'},reason:'Forwarding failed'},{status:'completed',progress:{error:{code:'plan_not_admissible'}}},now);
 assert.equal(view.admissionRejected,false);assert.equal(view.error,null);
 assert.match(view.errorTitle,/Forwarding failed/);
});
test('search timeout is not a proof of infeasibility',()=>{
 const view=experimentView({phase:'finished',success:false,error:{code:'departure_search_incomplete'}},{status:'completed'},now);
 assert.equal(view.admissionRejected,false);assert.match(view.errorTitle,/assenza di soluzioni/);
});

const {experimentPage}=require('../web/experiment-state.js');
test('guided pages wait for a verified controller and retain simulation during cutover',()=>{
 const pair={phase:'hot',sessions:{hot:'sim-1'}};
 assert.equal(experimentPage(null,null,null,null),'configuration');
 assert.equal(experimentPage(null,null,null,'job-1'),'preparation');
 assert.equal(experimentPage(pair,null,{presentation:{mode:'live'}},null),'preparation');
 assert.equal(experimentPage(pair,null,{presentation:{mode:'live',placement_status:'planned',assigned_controller_satellite:11}},null),'preparation');
 assert.equal(experimentPage(pair,null,{presentation:{mode:'live',initial_controller_ready:true}},null),'simulation');
 assert.equal(experimentPage(pair,null,{presentation:{mode:'live'}},null,'simulation'),'simulation');
 assert.equal(experimentPage({...pair,phase:'finished'},null,null,null),'results');
 assert.equal(experimentPage({...pair,phase:'finished'},{operation:'recover',status:'running'},null,null),'preparation');
});

const {experimentRoute}=require('../web/experiment-state.js');
test('simulation and results routes require a successfully launched comparison',()=>{
 for(const page of ['simulation','results']){
  assert.equal(experimentRoute(page,false),'configuration');
  assert.equal(experimentRoute(page,true),page);
 }
 assert.equal(experimentRoute('configuration',false),'configuration');
});

const {groupTimelineEvents}=require('../web/experiment-state.js');
test('restore timeline groups counters and merges request start and completion',()=>{
 const rows=groupTimelineEvents([
  {id:1,phase:'calibration'},
  {id:2,phase:'preparation_operation',operation:'restore_scenario',operation_status:'running'},
  {id:3,phase:'restore_request',request_status:'running',request:{started_monotonic:1,method:'POST',path:'/devices'}},
  {id:4,phase:'restore_progress',counts:{devices:{completed:1,total:64}}},
  {id:5,phase:'restore_request',request_status:'completed',request:{started_monotonic:1,method:'POST',path:'/devices',status:200}},
  {id:6,phase:'restore_progress',verification:'completed'},
  {id:7,phase:'preparation_operation',operation:'restore_scenario',operation_status:'completed'},
  {id:8,phase:'calibration'},
  {id:9,phase:'restore_progress',counts:{devices:{completed:0,total:64}}}
 ]);
 assert.equal(rows.length,4);
 assert.equal(rows[1].phase,'restore_group');assert.equal(rows[1].status,'completed');
 assert.equal(rows[1].counts.devices.completed,1);
 assert.equal(rows[1].requests.length,1);assert.equal(rows[1].requests[0].status,200);
 assert.equal(rows[3].counts.devices.completed,0);assert.equal(rows[3].id,9);
});
test('restore failure remains visible even with incomplete replay data',()=>{
 const rows=groupTimelineEvents([{id:5,phase:'restore_request',request_status:'failed',request:{error:'timeout'}}]);
 assert.equal(rows[0].status,'failed');assert.equal(rows[0].counts,null);
 assert.equal(rows[0].requests[0].error,'timeout');
});

const {preparationView}=require('../web/experiment-state.js');
test('preparation distinguishes calibration, controller selection and API activation',()=>{
 const preliminary=preparationView({phase:'calibration'},null,null);
 assert.equal(preliminary.chosen,false);assert.match(preliminary.detail,/calibrazioni/);
 const selected={resolved_configuration:{initial_satellite_id:11},sessions:{hot:'sim-1'}};
 const pending=preparationView(selected,null,{presentation:{mode:'live',placement_status:'planned'}});
 assert.equal(pending.title,'Attivazione API controller');assert.equal(pending.ready,false);assert.equal(pending.satellite,11);
 const ready=preparationView(selected,null,{presentation:{mode:'live',initial_controller_ready:true}});
 assert.equal(ready.title,'Controller pronto');assert.equal(ready.ready,true);
 assert.equal(preparationView(selected,null,{presentation:{mode:'preview',initial_controller_ready:true}}).ready,false);
});

test('cancellation overrides selection and readiness until cleanup finishes',()=>{
 const pair={phase:'hot',sessions:{hot:'sim-1'},resolved_configuration:{initial_satellite_id:11}};
 const ready={presentation:{mode:'live',initial_controller_ready:true}};
 const stopping={status:'running',cancellation_requested:true};
 assert.equal(experimentPage(pair,stopping,ready,null,'simulation'),'preparation');
 assert.equal(preparationView(pair,stopping,ready).title,'Interruzione in corso');
 assert.equal(preparationView(pair,stopping,ready).stopping,true);
 assert.equal(experimentPage({...pair,phase:'finished',outcome:'interrupted'},stopping,ready,null),'preparation');
 const finished={status:'interrupted',cancellation_requested:true};
 assert.equal(experimentPage({...pair,phase:'finished',outcome:'interrupted'},finished,ready,null),'configuration');
 assert.equal(!!preparationView(pair,finished,ready).stopping,false);
 assert.equal(experimentPage({...pair,phase:'finished',outcome:'recovery_required'},{status:'recovery_required',cancellation_requested:true},ready,null),'configuration');
});

test('loader titles follow actual source startup and scenario preparation stages',()=>{
 for(const label of ['Avvio dipendenze del controller sorgente','Attivazione API del controller sorgente','Caricamento scenario iniziale','Verifica API, autorità e sonde']){
  const view=preparationView({phase:'calibration'}, {progress:{phase:'calibration',operation_status:'running',label}},null);
  assert.equal(view.title,label);
 }
});

test('calibration stays in preparation even with an interrupted historical comparison',()=>{
 const historical={phase:'finished',outcome:'interrupted',job_id:'old'};
 for(const operation of ['functional','calibrate']){
  assert.equal(experimentPage(historical,{job_id:'new',operation,status:'running'},null,null),'preparation');
  assert.equal(experimentPage(historical,{job_id:'new',operation,status:'running',cancellation_requested:true},null,null),'preparation');
 }
});


test('scenario creation shows preparation through every stage then returns to configuration',()=>{
 const historical={phase:'finished',outcome:'interrupted',sessions:{hot:'old'}};
 const oldOrbit={presentation:{initial_controller_ready:true,mode:'live'}};
 for(const phase of ['preparation','calibration','planning','scenario_creation']){
  const job={operation:'prepare_base',status:'running',progress:{phase,label:'Fase '+phase}};
  assert.equal(experimentPage(historical,job,oldOrbit,null),'preparation');
  assert.equal(preparationView(historical,job,oldOrbit).title,phase==='calibration'?'Calibrazione  · prova 1/3':'Fase '+phase);
  assert.equal(preparationView(historical,job,oldOrbit).ready,false);
 }
 for(const status of ['completed','interrupted'])assert.equal(experimentPage(historical,{operation:'prepare_base',status},oldOrbit,null),'configuration');
 for(const status of ['failed','recovery_required'])assert.equal(experimentPage(historical,{operation:'prepare_base',status},oldOrbit,null),'preparation');
 const stopping={operation:'prepare_base',status:'running',cancellation_requested:true};
 assert.equal(experimentPage(historical,stopping,oldOrbit,null),'preparation');
 assert.equal(preparationView(historical,stopping,oldOrbit).title,'Interruzione in corso');
 assert.equal(experimentPage(historical,{...stopping,status:'interrupted'},oldOrbit,null),'configuration');
});


test('all six calibration trials use the preparation page and show mode and repetition',()=>{
 for(const operation of ['calibrate','prepare_base'])for(const method of ['cold','hot'])for(const replica of [1,2,3]){
  const job={operation,status:'running',progress:{phase:'calibration',method,replica,label:'Avvio controller sorgente'}};
  assert.equal(experimentPage(null,job,null,null),'preparation');
  assert.equal(preparationView(null,job,null).title,`Calibrazione ${method.toUpperCase()} · prova ${replica}/3`);
  assert.match(preparationView(null,job,null).detail,/Avvio controller sorgente/);
 }
});


test('calibration progress counts successful trials without counting loaded satellites',()=>{
 const {scenarioCreationProgress}=require('../web/experiment-state.js');
 const job={operation:'prepare_base',status:'running',progress:{phase:'calibration',method:'cold',replica:1,calibration_index:1,restore_counts:{devices:{completed:64,total:64}}}};
 const events=[{id:1,phase:'run_finished',run_id:'functional',outcome:'success'},{id:2,phase:'calibration',method:'cold',replica:1}];
 let view=scenarioCreationProgress(job,events);
 assert.equal(view.calibration,true);assert.equal(view.completed,0);assert.equal(view.trials[0].status,'In corso');
 events.push({id:3,phase:'run_finished',run_id:'cold-1',outcome:'success'});
 view=scenarioCreationProgress(job,events);assert.equal(view.completed,1);assert.equal(view.trials[0].status,'Completata');
 job.progress={phase:'calibration',method:'hot',replica:2,calibration_index:5};
 view=scenarioCreationProgress(job,events);assert.equal(view.completed,4);assert.equal(view.trials[4].status,'In corso');
});

test('base preparation replaces calibration progress and starts its own timeline',()=>{
 const {scenarioCreationProgress}=require('../web/experiment-state.js');
 const events=[{id:1,phase:'calibration',method:'hot',replica:3},{id:2,phase:'scenario_creation',label:'Preparazione della base comune'},{id:3,phase:'scenario_creation',label:'Attivazione del controller sorgente'}];
 const view=scenarioCreationProgress({operation:'prepare_base',progress:{phase:'scenario_creation',subphase:'restore_scenario'}},events);
 assert.equal(view.calibration,false);assert.equal(view.timelineStartId,2);
 assert.equal(scenarioCreationProgress({operation:'compare_continuous'},[]).calibration,false);
});


test('short calibration reports one cold and one hot trial',()=>{
 const {scenarioCreationProgress}=require('../web/experiment-state.js');
 const job={operation:'prepare_base',status:'running',progress:{phase:'calibration',method:'hot',replica:1,replicas_per_mode:1,calibration_total:2,calibration_index:2}};
 const view=scenarioCreationProgress(job,[{id:1,phase:'calibration',method:'cold',replica:1,replicas_per_mode:1},{id:2,phase:'run_finished',run_id:'cold',outcome:'success'}]);
 assert.equal(view.total,2);assert.equal(view.completed,1);assert.equal(view.trials.length,2);
 assert.equal(view.trials[0].label,'COLD · prova 1/1');assert.equal(view.trials[1].status,'In corso');
 assert.equal(preparationView(null,job,null).title,'Calibrazione HOT · prova 1/1');
});


test('newly queued scenario opens preparation before laboratory lock refresh arrives',()=>{
 const {experimentLandingPage}=require('../web/experiment-state.js');
 const job={operation:'prepare_base',status:'queued'};
 const page=experimentPage(null,job,null,null);
 assert.equal(page,'preparation');
 assert.equal(experimentLandingPage(page,'preparation',true),'preparation');
 assert.equal(experimentLandingPage(page,'configuration',true),'preparation');
 assert.equal(experimentLandingPage(page,'results',true),'preparation');
 assert.equal(experimentLandingPage('configuration','results',true),'results');
 assert.equal(experimentLandingPage('configuration','preparation',true),'configuration');
 assert.equal(experimentLandingPage('configuration','preparation',false),'configuration');
});
