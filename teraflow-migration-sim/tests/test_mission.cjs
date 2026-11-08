const {test}=require('node:test');
const assert=require('node:assert/strict');
const {missionRelevant,missionState,orbitalAt,orbitRunning,relativeClock,MISSION_STEPS}=require('../web/mission.js');

const selected=[{event_id:'60150-1557',source:60150,destination:68285,trigger_s:1557},{event_id:'e2',source:1,destination:2,trigger_s:5000}];
const at=seconds=>new Date(Date.UTC(2026,10,7,18,54,0)+seconds*1000).toISOString();
/* Shape of the verification job of 7 November 2026 (Hot run) */
const hot=[
 {phase:'comparison_run',method:'hot',timestamp_utc:at(-180)},
 {phase:'prepare',timestamp_utc:at(-176)},
 {phase:'preparation_operation',operation:'start_source',operation_status:'running',label:'Avvio controller sorgente',timestamp_utc:at(-120)},
 {phase:'restore_request',timestamp_utc:at(-100)},
 {phase:'preparation_operation',operation:'baseline',operation_status:'completed',timestamp_utc:at(23)},
 {phase:'trigger',orbital_s:1557,timestamp_utc:at(53)},
 {phase:'alignment',orbital_s:1558,timestamp_utc:at(54)},
 {phase:'snapshot_initial',orbital_s:1618,timestamp_utc:at(114)},
 {phase:'transfer',orbital_s:1619,timestamp_utc:at(115)},
 {phase:'target_start',orbital_s:1619,timestamp_utc:at(115)},
 {phase:'restore_initial',orbital_s:1683,timestamp_utc:at(179)},
 {phase:'freeze',orbital_s:1720,timestamp_utc:at(216)},
 {phase:'transfer',orbital_s:1722,timestamp_utc:at(218)}];

test('noise is dropped as events arrive',()=>{
 assert.equal(missionRelevant({phase:'restore_request'}),false);
 assert.equal(missionRelevant({phase:'freeze'}),true);
});

test('preparation holds the orbit thirty seconds before the trigger',()=>{
 const state=missionState(hot.slice(0,4),selected,'functional');
 assert.equal(state.stage,'preparing');
 assert.equal(state.preparation,'Avvio controller sorgente');
 assert.equal(state.event.event_id,'60150-1557');
 assert.equal(orbitalAt(state,Date.parse(at(0))),1527);
 assert.equal(orbitRunning(state),false);
 assert.equal(state.linkActive,false);
 assert.equal(state.controller,60150);
});

test('after the baseline the orbital clock runs one second per second',()=>{
 const state=missionState(hot.slice(0,5),selected,'functional');
 assert.equal(state.stage,'countdown');
 assert.equal(orbitalAt(state,Date.parse(at(33))),1537);
 assert.equal(orbitRunning(state),true);
});

test('a second transfer after the freeze is the Hot delta, inside the downtime',()=>{
 const state=missionState(hot,selected,'functional');
 assert.equal(state.method,'hot');
 assert.equal(state.current.key,'delta');
 assert.equal(state.transferring,true);
 assert.equal(state.controllerState,'frozen');
 assert.equal(state.controller,60150);
 assert.deepEqual(state.steps.filter(step=>step.status==='done').map(step=>step.key),
  ['trigger','alignment','snapshot','transfer','target_start','restore','freeze']);
 assert.equal(state.steps.find(step=>step.key==='alignment').duration_s,60);
 assert.equal(state.steps.find(step=>step.key==='freeze').offset_s,163);
 assert.equal(state.downtime.startMs,Date.parse(at(216)));
 assert.equal(orbitalAt(state,Date.parse(at(220))),1724);
});

test('cutover moves the controller to the destination; run end stops the orbit',()=>{
 const events=[...hot,{phase:'cutover',orbital_s:1727,timestamp_utc:at(223)},{phase:'completed',orbital_s:1727,timestamp_utc:at(223)},{phase:'run_finished',timestamp_utc:at(260)}];
 const state=missionState(events,selected,'functional');
 assert.equal(state.stage,'completed');
 assert.equal(state.controller,68285);
 assert.equal(state.controllerState,'active');
 assert.equal(state.downtime.endMs,Date.parse(at(223)));
 assert.equal(state.steps.at(-1).status,'done');
 assert.equal(orbitalAt(state,Date.parse(at(400))),1764);
 assert.equal(orbitRunning(state),false);
});

test('Cold downtime starts at the source stop; the event index selects the catalogue entry',()=>{
 const events=[{phase:'event_comparison',event_index:2,event_total:2,method:'cold',timestamp_utc:at(0)},{phase:'prepare',timestamp_utc:at(1)},
  {phase:'trigger',orbital_s:5000,timestamp_utc:at(200)},{phase:'source_stop',orbital_s:5061,timestamp_utc:at(261)}];
 const state=missionState(events,selected,'compare_events');
 assert.equal(state.event.event_id,'e2');
 assert.equal(state.eventTotal,2);
 assert.equal(state.controllerState,'stopped');
 assert.equal(state.current.key,'source_stop');
 assert.equal(MISSION_STEPS.cold.find(step=>step.key==='transfer').downtime,true);
});

test('relative clock is signed around the trigger',()=>{
 assert.equal(relativeClock(1527,1557),'T−00:30');
 assert.equal(relativeClock(1727,1557),'T+02:50');
 assert.equal(relativeClock(undefined,1557),'—');
});

test('an interrupted run stops the phase timer and closes the downtime at the failure',()=>{
 const events=[...hot,{phase:'attempt_failed',attempt:1,reason:'Job interrupted by user',orbital_s:1730,timestamp_utc:at(226)},
  {phase:'rollback',timestamp_utc:at(240)},{phase:'failed',timestamp_utc:at(300)},{phase:'cleanup',label:'Messa in sicurezza del laboratorio',timestamp_utc:at(305)}];
 const state=missionState(events,selected,'functional');
 assert.equal(state.stage,'failed');
 assert.equal(state.current.key,'delta');
 assert.equal(state.current.status,'failed');
 assert.equal(state.current.duration_s,8);
 assert.equal(state.downtime.endMs,Date.parse(at(226)));
 assert.equal(state.cleanup,'Messa in sicurezza del laboratorio');
 assert.equal(orbitRunning(state),false);
});

test('a failed attempt followed by progress is a retry, not a failure',()=>{
 const events=[...hot.slice(0,8),{phase:'attempt_failed',attempt:1,reason:'link lost',timestamp_utc:at(120)},{phase:'alignment',orbital_s:1630,timestamp_utc:at(130)}];
 const state=missionState(events,selected,'functional');
 assert.equal(state.failure,null);
 assert.equal(state.stage,'migrating');
});

test('a retry restarts from the alignment and counts the attempt',()=>{
 const events=[...hot.slice(0,11),{phase:'attempt_failed',attempt:1,reason:'link lost',timestamp_utc:at(200)},{phase:'rollback',timestamp_utc:at(205)},
  {phase:'alignment',orbital_s:1712,timestamp_utc:at(210)}];
 const state=missionState(events,selected,'functional');
 assert.equal(state.attempt,2);
 assert.equal(state.current.key,'alignment');
 assert.deepEqual(state.steps.filter(step=>step.status==='done').map(step=>step.key),['trigger']);
 assert.equal(state.controllerState,'active');
});

test('a run that needs recovery is over and says so',()=>{
 const events=[...hot,{phase:'attempt_failed',attempt:1,reason:'fencing failed',timestamp_utc:at(230)},{phase:'recovery_failed',operation:'abort_target',reason:'timeout',timestamp_utc:at(231)},{phase:'recovery_required',timestamp_utc:at(232)}];
 const state=missionState(events,selected,'functional');
 assert.equal(state.stage,'failed');
 assert.equal(state.recoveryRequired,true);
 assert.equal(state.recoveryFailure,'timeout');
});

test('the experiment position comes with the event',()=>{
 const state=missionState([{phase:'event_comparison',event_index:2,event_total:2,method:'cold',replica:3,replica_total:5,warmup:false,position:12,run_total:51,timestamp_utc:at(0)}],selected,'compare_events');
 assert.deepEqual(state.run,{position:12,total:51,replica:3,replicas:5,warmup:false});
});
