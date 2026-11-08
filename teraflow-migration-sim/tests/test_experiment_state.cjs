const {test}=require('node:test');
const assert=require('node:assert/strict');
const {phaseLabel,clock,duration,jobView,timeline,methodLabel,procedureDurations,experimentRuns,axisScale,hoursMinutes}=require('../web/experiment-state.js');

test('free laboratory has no job actions',()=>{
 const view=jobView(null,null);
 assert.equal(view.title,'Laboratorio libero');
 assert.equal(view.canStop,false);
 assert.equal(view.needsRecovery,false);
});

test('running event experiment shows event, mode, step and elapsed time',()=>{
 const job={operation:'compare_events',status:'running',started_utc:'2026-11-07T18:00:00Z',progress:{operation:'baseline'}};
 const comparison={event_total:3,current:{event:2,method:'cold'}};
 const view=jobView(job,comparison,Date.parse('2026-11-07T18:05:07Z'));
 assert.equal(view.title,'Esperimento a eventi · evento 2/3 · Cold · in corso');
 assert.match(view.detail,/Verifica di API, autorità e ping/);
 assert.match(view.detail,/00:05:07/);
 assert.equal(view.canStop,true);
 assert.equal(view.step,'Verifica di API, autorità e ping');
 assert.equal(view.elapsedSeconds,307);
});

test('stop is offered once and recovery when required',()=>{
 assert.equal(jobView({operation:'functional',status:'running',cancellation_requested:true,progress:{}},null).canStop,false);
 const recovery=jobView({operation:'compare_events',status:'recovery_required'},null);
 assert.equal(recovery.needsRecovery,true);
 assert.equal(recovery.active,false);
 assert.equal(jobView({operation:'functional',status:'completed',application_success:true},null).needsRecovery,false);
});

test('labels prefer explicit text and fall back to known phases',()=>{
 assert.equal(phaseLabel({phase:'event_comparison',label:'Evento 1/3 · HOT'}),'Evento 1/3 · HOT');
 assert.equal(phaseLabel({phase:'preparation_operation',operation:'clean_target'}),'Pulizia del database della destinazione');
 assert.equal(phaseLabel({phase:'cutover'}),'Passaggio dell’autorità');
 assert.equal(methodLabel('hot'),'Hot');
});

test('timeline skips noisy events and consecutive duplicates',()=>{
 const rows=timeline([
  {id:1,phase:'trigger',timestamp_utc:'2026-11-07T18:00:01Z'},
  {id:2,phase:'restore_request',timestamp_utc:'2026-11-07T18:00:02Z'},
  {id:3,phase:'trigger',timestamp_utc:'2026-11-07T18:00:03Z'},
  {id:4,phase:'preparation_operation',operation:'baseline',operation_status:'failed',timestamp_utc:'2026-11-07T18:00:04Z'}]);
 assert.deepEqual(rows.map(row=>row.text),['Trigger della migrazione','Verifica di API, autorità e ping']);
 assert.equal(rows[1].failed,true);
 assert.equal(rows[0].time,'18:00:01');
});

test('formatting keeps missing measures explicit',()=>{
 assert.equal(clock(3725),'01:02:05');
 assert.equal(clock(undefined),'—');
 assert.equal(duration(null),'non misurato');
 assert.equal(duration(20.56),'20,6 s');
 assert.equal(duration(123.7),'124 s');
});

test('the verification is measured and the experiment estimated from it',()=>{
 const jobs=[
  {operation:'functional',status:'failed',started_utc:'2026-11-07T19:00:00Z',finished_utc:'2026-11-07T19:01:00Z'},
  {operation:'functional',status:'completed',application_success:true,started_utc:'2026-11-07T18:51:00Z',finished_utc:'2026-11-07T19:04:36Z'}];
 const durations=procedureDurations(jobs,experimentRuns(3));
 assert.deepEqual(durations.functional,{seconds:816,measured:true});
 assert.equal(durations.compare_events.runs,19);
 assert.equal(durations.compare_events.seconds,408*19);
 assert.deepEqual(procedureDurations([]).functional,{seconds:900,measured:false});
});

test('the time axis keeps at most eight ticks',()=>{
 assert.deepEqual(axisScale([816,2436]),{maxSeconds:3000,ticks:[0,10,20,30,40,50],step:10});
 assert.deepEqual(axisScale([816,20808]).ticks,[0,60,120,180,240,300,360]);
 assert.equal(hoursMinutes(20808),'5 h 47 min');
 assert.equal(hoursMinutes(816),'14 min');
});

test('the experiment title gives run, event, replica and mode',()=>{
 const job={operation:'compare_events',status:'running',started_utc:'2026-11-07T18:00:00Z',progress:{operation:'baseline'}};
 const comparison={event_total:5,design:{replicas:5},current:{position:12,total:51,event:2,replica:3,method:'cold',warmup:false}};
 assert.equal(jobView(job,comparison,Date.parse('2026-11-07T18:01:00Z')).title,'Esperimento a eventi · prova 12/51 · evento 2/5 · replica 3/5 · Cold · in corso');
 comparison.current={position:1,total:51,event:1,replica:0,method:'hot',warmup:true};
 assert.match(jobView(job,comparison).title,/prova 1\/51 · evento 1\/5 · riscaldamento · Hot/);
});
