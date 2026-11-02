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
