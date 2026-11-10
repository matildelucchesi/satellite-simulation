/* Live state of the migration shown on the Scenario page, derived from the job's event stream.
   Pure functions shared by the console and the Node regression tests.

   Timeline of one run (see src/experiment.py): the laboratory is prepared with the orbit held at
   T−30 s; after the baseline the orbital clock runs one orbital second per second, the trigger
   fires at the event's instant and the orchestrator reports each phase with its orbital time. */
const MISSION_STEPS={
 hot:[
  {key:'trigger',label:'Trigger',hint:'la sorgente sta per entrare in ombra',where:'sorgente'},
  {key:'alignment',label:'Allineamento del percorso',hint:'60 s di contatto continuo su tutti i salti',where:'percorso'},
  {key:'snapshot',label:'Snapshot dello stato',where:'sorgente'},
  {key:'transfer',label:'Trasferimento dello stato',where:'percorso'},
  {key:'target_start',label:'Avvio del controller',where:'destinazione'},
  {key:'restore',label:'Ripristino dello stato',where:'destinazione'},
  {key:'freeze',label:'Freeze del controller',downtime:true,where:'sorgente'},
  {key:'delta',label:'Trasferimento del delta',downtime:true,where:'percorso, destinazione'},
  {key:'verify',label:'Verifica di equivalenza',downtime:true,where:'destinazione'},
  {key:'cutover',label:'Passaggio dell’autorità',downtime:true,where:'proxy P4'},
  {key:'completed',label:'Migrazione completata',where:''}],
 cold:[
  {key:'trigger',label:'Trigger',hint:'la sorgente sta per entrare in ombra',where:'sorgente'},
  {key:'alignment',label:'Allineamento del percorso',hint:'60 s di contatto continuo su tutti i salti',where:'percorso'},
  {key:'snapshot',label:'Quiete e snapshot',where:'sorgente'},
  {key:'source_stop',label:'Arresto del controller',downtime:true,where:'sorgente'},
  {key:'transfer',label:'Trasferimento dello stato',downtime:true,where:'percorso'},
  {key:'target_start',label:'Avvio del controller',downtime:true,where:'destinazione'},
  {key:'restore',label:'Ripristino dello stato',downtime:true,where:'destinazione'},
  {key:'verify',label:'Verifica di equivalenza',downtime:true,where:'destinazione'},
  {key:'cutover',label:'Passaggio dell’autorità',downtime:true,where:'proxy P4'},
  {key:'completed',label:'Migrazione completata',where:''}]};

const ORBIT_LEAD_S=30;
const NOISE=new Set(['restore_request','restore_progress','heartbeat','infrastructure_wait','source_startup']);

function stepFor(phase,method,reached){
 switch(phase){
  case 'trigger':return 'trigger';
  case 'alignment':return 'alignment';
  case 'quiescence':case 'snapshot_initial':return 'snapshot';
  case 'source_stop':case 'source_stopped':return 'source_stop';
  case 'software_on_board':case 'transfer':case 'transfer_verified':return method==='hot'&&reached.has('freeze')?'delta':'transfer';
  case 'target_start':return 'target_start';
  case 'restore_initial':return 'restore';
  case 'freeze':case 'source_frozen':return 'freeze';
  case 'restore_delta':return 'delta';
  case 'verify':return 'verify';
  case 'ack':case 'cutover':return 'cutover';
  case 'completed':case 'service_verified':case 'run_finished':return 'completed';
  default:return null;
 }
}

/* Events that matter for the mission view; the rest of the stream is dropped as it arrives. */
function missionRelevant(event){return Boolean(event&&event.phase&&!NOISE.has(event.phase));}

function missionState(events,selected,operation){
 const state={operation,eventIndex:1,eventTotal:operation==='compare_events'?(selected||[]).length:1,method:null,
  stage:'waiting',preparation:'',steps:[],reached:new Map(),anchor:null,frozenAt:null,ended:false,failure:null,cleanup:'',attempt:1,retrying:false};
 const begin=()=>{state.stage='preparing';state.preparation='';state.reached=new Map();state.anchor=null;state.frozenAt=null;state.failure=null;state.cleanup='';state.attempt=1;state.retrying=false;};
 for(const event of events||[]){
  const ms=Date.parse(event.timestamp_utc||'');
  switch(event.phase){
   case 'event_comparison':state.eventIndex=event.event_index||1;state.eventTotal=event.event_total||state.eventTotal;state.method=event.method||state.method;state.stage='waiting';
    state.run={position:event.position??null,total:event.run_total??null,replica:event.replica??null,replicas:event.replica_total??null,warmup:Boolean(event.warmup)};break;
   case 'comparison_run':state.method=event.method||state.method;state.stage='waiting';break;
   case 'prepare':begin();break;
   case 'preparation_operation':
    if(event.operation_status==='running')state.preparation=event.label||event.operation||'';
    if(event.operation==='baseline'&&event.operation_status==='completed'&&Number.isFinite(ms)){state.stage='countdown';state.anchor={orbital:null,ms};}
    break;
   case 'job_finished':state.ended=true;if(state.frozenAt===null&&Number.isFinite(ms))state.frozenAt=ms;break;
   /* A failed attempt may be retried; a failed run is over and the laboratory is made safe */
   case 'attempt_failed':state.failure={reason:event.reason||'',ms,attempt:event.attempt||1};state.retrying=true;break;
   case 'rollback':state.rolledBack=true;break;
   case 'failed':case 'recovery_required':
    state.stage='failed';state.recoveryRequired=event.phase==='recovery_required';
    if(!state.failure)state.failure={reason:event.reason||'',ms};if(state.frozenAt===null&&Number.isFinite(ms))state.frozenAt=ms;break;
   case 'recovery_failed':state.recoveryFailure=event.reason||event.operation||'';break;
   case 'cleanup':case 'cleanup_verified':state.cleanup=event.label||'';break;
   default:{
    const key=stepFor(event.phase,state.method,state.reached);
    if(!key)break;
    /* A new attempt starts again from the alignment: the trigger stays, the rest of the failed attempt is discarded */
    if(state.retrying&&state.stage!=='failed'){const trigger=state.reached.get('trigger');state.reached=new Map(trigger?[['trigger',trigger]]:[]);state.attempt=(state.failure?.attempt||state.attempt)+1;state.failure=null;state.retrying=false;state.rolledBack=false;}
    if(!state.reached.has(key))state.reached.set(key,{ms,orbital:Number.isFinite(event.orbital_s)?event.orbital_s:null});
    if(Number.isFinite(event.orbital_s)&&Number.isFinite(ms))state.anchor={orbital:event.orbital_s,ms};
    if(state.stage!=='failed')state.stage=key==='completed'?'completed':'migrating';
    if(event.phase==='run_finished'&&Number.isFinite(ms))state.frozenAt=ms;
   }
  }
 }
 state.event=(selected||[])[state.eventIndex-1]||null;
 if(state.anchor&&state.anchor.orbital===null&&state.event)state.anchor.orbital=state.event.trigger_s-ORBIT_LEAD_S;
 const steps=MISSION_STEPS[state.method]||[];
 const reachedKeys=steps.filter(step=>state.reached.has(step.key)).map(step=>step.key);
 const current=reachedKeys.length?reachedKeys[reachedKeys.length-1]:null;
 const currentIndex=current?steps.findIndex(step=>step.key===current):-1;
 const trigger=state.reached.get('trigger');
 state.steps=steps.map((step,index)=>{
  const info=state.reached.get(step.key);
  const next=steps.slice(index+1).map(row=>state.reached.get(row.key)).find(Boolean);
  const failedHere=index===currentIndex&&state.failure;
  const status=index<currentIndex?'done':index===currentIndex?(step.key==='completed'?'done':failedHere?'failed':'current'):'pending';
  const end=next?next.ms:failedHere?state.failure.ms:null;
  return {...step,status,startMs:info?.ms??null,
   offset_s:info&&trigger&&Number.isFinite(info.ms)?(info.ms-trigger.ms)/1000:null,
   duration_s:info&&Number.isFinite(info.ms)&&Number.isFinite(end)?(end-info.ms)/1000:null};
 });
 state.current=currentIndex>=0?state.steps[currentIndex]:null;
 const after=key=>state.reached.has(key);
 /* Where the controller is and what it is doing */
 state.controller=state.event?(after('cutover')?state.event.destination:state.event.source):null;
 state.controllerState=after('cutover')?'active':after('source_stop')?'stopped':after('freeze')?'frozen':'active';
 state.linkActive=after('trigger');
 state.transferring=Boolean(state.current&&['transfer','delta'].includes(state.current.key));
 /* The route is in use while it is being aligned and while state crosses it */
 state.communicating=Boolean(state.current&&['alignment','transfer','delta'].includes(state.current.key));
 const downtimeStep=state.steps.find(step=>step.downtime&&step.startMs!==null);
 state.downtime={startMs:downtimeStep?downtimeStep.startMs:null,endMs:state.reached.get('cutover')?.ms??(state.failure&&downtimeStep?state.failure.ms:null)};
 return state;
}

/* Orbital time shown for a mission at a wall-clock instant. The orbit is held during the
   preparation and stops when the run's observation ends. */
function orbitalAt(state,nowMs){
 if(!state||!state.event)return null;
 if(!state.anchor)return state.event.trigger_s-ORBIT_LEAD_S;
 const until=state.frozenAt!==null?Math.min(nowMs,state.frozenAt):nowMs;
 return state.anchor.orbital+Math.max(0,until-state.anchor.ms)/1000;
}

function orbitRunning(state){return Boolean(state&&state.anchor&&state.frozenAt===null);}

/* ---------- preview ----------
   Without a job the Scenario page plays a migration of every event, Hot then Cold, with the phase
   times (seconds from the trigger) of a chosen verification or experiment; an event and method
   without a finished run there uses the reference times. The orbit advances with the measured
   times; phases shorter than PREVIEW_MIN_STEP_S of screen time are slowed down to be readable. */
const PREVIEW_METHODS=['hot','cold'];
const PREVIEW_OBSERVE_S=30;
const PREVIEW_MIN_STEP_S=1.2;
/* Reference times: verification of 8 November 2026 (job-7ae8932f…), event 1 */
const PREVIEW_REFERENCE={
 hot:{trigger:0,alignment:.34,snapshot:60.41,transfer:61.75,target_start:61.97,restore:134.06,freeze:174.93,delta:176.43,verify:179.67,cutover:180.82,completed:181.33},
 cold:{trigger:0,alignment:.37,snapshot:60.44,source_stop:63.09,transfer:85.14,target_start:85.36,restore:159.17,verify:211.29,cutover:212.46,completed:212.91}};

/* Finished runs in the event stream of a verification or an experiment job: for each run the
   event index in that job, method, replica and the seconds from the trigger of each phase. Only
   runs that reached the passage of authority and the end are kept. */
function measuredRuns(events){
 const runs=[];let current=null;
 for(const event of events||[]){
  if(event.phase==='comparison_run'||event.phase==='event_comparison'){
   current={meta:{eventIndex:event.event_index||1,method:event.method,replica:event.replica??null,warmup:Boolean(event.warmup)},events:[]};
   runs.push(current);
  }
  if(current&&(event.phase==='comparison_run'||event.phase==='event_comparison'||missionRelevant(event)))current.events.push(event);
 }
 return runs.flatMap(({meta,events:segment})=>{
  const state=missionState(segment,[],'functional');
  if(!state.method||!state.reached.has('cutover')||!state.reached.has('completed'))return [];
  const offsets={};
  for(const step of state.steps)if(step.offset_s!==null)offsets[step.key]=Math.max(0,step.offset_s);
  return [{...meta,method:state.method,attempt:state.attempt,offsets}];
 });
}

/* Times for the preview, keyed "event:method" on the events of the installed profile.
   `profileIndex(i)` gives the profile's event number for event i of the job (null when the job's
   event is not in the profile). Per event and method: the first replica, warm-up excluded. */
function previewTimes(runs,profileIndex){
 const out={};
 const ordered=[...(runs||[])].filter(run=>!run.warmup).sort((a,b)=>(a.replica??0)-(b.replica??0));
 for(const run of ordered){
  const index=profileIndex(run.eventIndex);
  if(index==null)continue;
  const key=`${index}:${run.method}`;
  if(!out[key])out[key]=run;
 }
 return out;
}

/* The preview script: one segment per event and method, each made of pieces (the lead before the
   trigger, then one piece per phase; the last phase is the observation after the migration). */
function previewScript(selected,times,speed){
 const segments=[];let wall=0;
 (selected||[]).forEach((event,index)=>{for(const method of PREVIEW_METHODS){
  const run=times&&times[`${index+1}:${method}`];
  const offsets=run?run.offsets:PREVIEW_REFERENCE[method];
  const keys=MISSION_STEPS[method].map(step=>step.key).filter(key=>Number.isFinite(offsets[key]));
  const pieces=[{key:null,start:-ORBIT_LEAD_S,orbital:ORBIT_LEAD_S}];
  keys.forEach((key,position)=>{
   const end=position+1<keys.length?offsets[keys[position+1]]:offsets[key]+PREVIEW_OBSERVE_S;
   pieces.push({key,start:offsets[key],orbital:Math.max(0,end-offsets[key])});
  });
  const segment={eventIndex:index+1,event,method,offsets,keys,pieces,wallStart:wall,
   origin:run?{measured:true,replica:run.replica,attempt:run.attempt}:{measured:false}};
  for(const piece of pieces){
   piece.wall=Math.max(piece.orbital/speed,piece.key&&piece.key!=='completed'?PREVIEW_MIN_STEP_S:0);
   piece.wallStart=wall;wall+=piece.wall;
  }
  segment.wallEnd=wall;segments.push(segment);
 }});
 return {segments,wall};
}

/* Position in the script after `elapsed` seconds of screen time (the script loops). */
function previewPosition(script,elapsed){
 if(!script||!script.wall)return null;
 const t=((elapsed%script.wall)+script.wall)%script.wall;
 const segment=script.segments.find(row=>t<row.wallEnd)||script.segments[script.segments.length-1];
 const pieceIndex=Math.max(0,segment.pieces.findIndex(piece=>t<piece.wallStart+piece.wall));
 const piece=segment.pieces[pieceIndex],fraction=piece.wall?Math.min(1,(t-piece.wallStart)/piece.wall):1;
 return {segment,pieceIndex,inPiece:piece.orbital*fraction,orbital:segment.event.trigger_s+piece.start+piece.orbital*fraction};
}
/* Screen time of a position, to keep it when the speed changes and to jump to an event. */
function previewElapsed(script,segmentIndex,pieceIndex,inPiece){
 const segment=script.segments[segmentIndex];if(!segment)return 0;
 const piece=segment.pieces[pieceIndex]||segment.pieces[0];
 return piece.wallStart+(piece.orbital?piece.wall*Math.min(1,inPiece/piece.orbital):0);
}

/* Mission state shown by the preview, with the same fields the live view reads. */
function previewMission(script,position){
 const {segment,pieceIndex,inPiece}=position,event=segment.event;
 const currentIndex=pieceIndex-1,reached=new Set(segment.keys.slice(0,currentIndex+1));
 const steps=MISSION_STEPS[segment.method].filter(step=>segment.keys.includes(step.key)).map((step,index)=>{
  const piece=segment.pieces[index+1];
  const status=index<currentIndex?'done':index===currentIndex?(step.key==='completed'?'done':'current'):'pending';
  return {...step,status,startMs:null,offset_s:segment.offsets[step.key],duration_s:status==='done'&&step.key!=='completed'?piece.orbital:null,
   elapsed_s:status==='current'?inPiece:null};
 });
 const current=currentIndex>=0?steps[currentIndex]:null,after=key=>reached.has(key);
 const firstDown=steps.find(step=>step.downtime);
 let downtime={seconds:null,ended:false};
 if(firstDown&&after(firstDown.key)){
  const start=segment.offsets[firstDown.key],now=segment.offsets[current.key]+inPiece;
  downtime=after('cutover')?{seconds:segment.offsets.cutover-start,ended:true}:{seconds:now-start,ended:false};
 }
 return {preview:true,operation:'preview',event,method:segment.method,eventIndex:segment.eventIndex,eventTotal:script.segments.length/PREVIEW_METHODS.length,
  segmentIndex:script.segments.indexOf(segment),origin:segment.origin,stage:currentIndex<0?'countdown':after('completed')?'completed':'migrating',
  steps,current,attempt:1,failure:null,
  controller:after('cutover')?event.destination:event.source,
  controllerState:after('cutover')?'active':after('source_stop')?'stopped':after('freeze')?'frozen':'active',
  linkActive:after('trigger'),
  transferring:Boolean(current&&['transfer','delta'].includes(current.key)),
  communicating:Boolean(current&&['alignment','transfer','delta'].includes(current.key)),
  previewDowntime:downtime};
}

/* Signed "T±mm:ss" relative to the trigger. */
function relativeClock(orbital,trigger){
 if(!Number.isFinite(orbital)||!Number.isFinite(trigger))return '—';
 const delta=Math.round(orbital-trigger),sign=delta<0?'−':'+',total=Math.abs(delta);
 return `T${sign}${String(Math.floor(total/60)).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`;
}

if(typeof module!=='undefined')module.exports={MISSION_STEPS,ORBIT_LEAD_S,PREVIEW_MIN_STEP_S,PREVIEW_REFERENCE,missionRelevant,missionState,orbitalAt,orbitRunning,relativeClock,stepFor,
 measuredRuns,previewTimes,previewScript,previewPosition,previewElapsed,previewMission};
