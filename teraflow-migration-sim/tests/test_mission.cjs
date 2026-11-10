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

/* ---------- preview ---------- */
const preview=require('../web/mission.js');
const finished=[...hot,
 {phase:'restore_delta',orbital_s:1722,timestamp_utc:at(219)},{phase:'verify',orbital_s:1725,timestamp_utc:at(222)},
 {phase:'ack',orbital_s:1726,timestamp_utc:at(223)},{phase:'completed',orbital_s:1727,timestamp_utc:at(224)},
 {phase:'run_finished',timestamp_utc:at(260)},
 {phase:'comparison_run',method:'cold',timestamp_utc:at(300)},{phase:'prepare',timestamp_utc:at(301)},
 {phase:'trigger',orbital_s:1557,timestamp_utc:at(400)},{phase:'alignment',orbital_s:1557,timestamp_utc:at(401)},
 {phase:'source_stop',orbital_s:1620,timestamp_utc:at(463)},
 {phase:'attempt_failed',reason:'x',timestamp_utc:at(470)},{phase:'failed',timestamp_utc:at(471)}];

test('measured preview times come from finished runs only',()=>{
 const runs=preview.measuredRuns(finished);
 assert.deepEqual(runs.map(run=>[run.method,run.eventIndex]),[['hot',1]]);
 const offsets=runs[0].offsets;
 assert.equal(offsets.trigger,0);assert.equal(offsets.freeze,163);assert.equal(offsets.delta,165);assert.equal(offsets.cutover,170);
});

test('experiment runs: first replica per event and method, warm-up excluded, mapped on the profile',()=>{
 const run=(event_index,method,replica,warmup)=>[
  {phase:'event_comparison',event_index,method,replica,warmup,timestamp_utc:at(0)},
  {phase:'trigger',timestamp_utc:at(10)},{phase:'alignment',timestamp_utc:at(11+replica)},
  {phase:'ack',timestamp_utc:at(100)},{phase:'completed',timestamp_utc:at(101)}];
 const runs=preview.measuredRuns([...run(1,'hot',0,true),...run(1,'hot',2,false),...run(1,'hot',1,false),...run(2,'cold',1,false),...run(3,'cold',1,false)]);
 assert.equal(runs.length,5);
 /* Job event 2 is profile event 1; job event 3 is not in the profile */
 const times=preview.previewTimes(runs,index=>({1:2,2:1})[index]??null);
 assert.deepEqual(Object.keys(times).sort(),['1:cold','2:hot']);
 assert.equal(times['2:hot'].replica,1);assert.equal(times['2:hot'].offsets.alignment,2);
 const script=preview.previewScript(selected,times,10);
 assert.deepEqual(script.segments.map(row=>row.origin.measured),[false,true,true,false]);
 assert.equal(script.segments[2].offsets.cutover,90);assert.equal(script.segments[2].origin.replica,1);
});

test('the preview plays every event, Hot then Cold, and loops',()=>{
 const script=preview.previewScript(selected,null,10);
 assert.deepEqual(script.segments.map(row=>[row.eventIndex,row.method]),[[1,'hot'],[1,'cold'],[2,'hot'],[2,'cold']]);
 /* The lead before the trigger: 30 orbital seconds in 3 s of screen time at ×10 */
 const start=preview.previewPosition(script,1.5);
 assert.equal(start.pieceIndex,0);
 assert.equal(start.orbital,1557-15);
 const mission=preview.previewMission(script,start);
 assert.equal(mission.stage,'countdown');assert.equal(mission.controller,60150);assert.equal(mission.linkActive,false);
 assert.equal(preview.previewPosition(script,script.wall+1.5).orbital,start.orbital);
});

test('short phases last at least the minimum screen time',()=>{
 const script=preview.previewScript(selected,null,60),hot1=script.segments[0];
 const transfer=hot1.pieces.find(piece=>piece.key==='transfer');
 assert.equal(transfer.wall,preview.PREVIEW_MIN_STEP_S);
 const alignment=preview.previewScript(selected,null,10).segments[0].pieces.find(piece=>piece.key==='alignment');
 assert.ok(Math.abs(alignment.wall-(60.41-.34)/10)<1e-9);
});

test('the preview mission moves the controller and counts the downtime',()=>{
 const script=preview.previewScript(selected,null,10),hot1=script.segments[0];
 const index=key=>hot1.pieces.findIndex(piece=>piece.key===key);
 const during=preview.previewMission(script,preview.previewPosition(script,hot1.pieces[index('transfer')].wallStart+.1));
 assert.equal(during.current.key,'transfer');assert.equal(during.transferring,true);assert.equal(during.communicating,true);
 assert.equal(during.steps.find(step=>step.key==='snapshot').status,'done');
 const frozen=preview.previewMission(script,preview.previewPosition(script,hot1.pieces[index('verify')].wallStart+.5));
 assert.equal(frozen.controllerState,'frozen');assert.equal(frozen.previewDowntime.ended,false);assert.ok(frozen.previewDowntime.seconds>4);
 const done=preview.previewMission(script,preview.previewPosition(script,hot1.pieces[index('completed')].wallStart+.5));
 assert.equal(done.stage,'completed');assert.equal(done.controller,selected[0].destination);
 assert.ok(Math.abs(done.previewDowntime.seconds-(180.82-174.93))<1e-9);assert.equal(done.previewDowntime.ended,true);
 const cold=preview.previewMission(script,preview.previewPosition(script,script.segments[1].pieces[4].wallStart+.1));
 assert.equal(cold.method,'cold');assert.equal(cold.controllerState,'stopped');
});

test('a position survives a change of speed',()=>{
 const slow=preview.previewScript(selected,null,10),fast=preview.previewScript(selected,null,60);
 const position=preview.previewPosition(slow,40);
 const again=preview.previewPosition(fast,preview.previewElapsed(fast,slow.segments.indexOf(position.segment),position.pieceIndex,position.inPiece));
 assert.ok(Math.abs(again.orbital-position.orbital)<1e-6);
});
