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

/* Signed "T±mm:ss" relative to the trigger. */
function relativeClock(orbital,trigger){
 if(!Number.isFinite(orbital)||!Number.isFinite(trigger))return '—';
 const delta=Math.round(orbital-trigger),sign=delta<0?'−':'+',total=Math.abs(delta);
 return `T${sign}${String(Math.floor(total/60)).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`;
}

if(typeof module!=='undefined')module.exports={MISSION_STEPS,ORBIT_LEAD_S,missionRelevant,missionState,orbitalAt,orbitRunning,relativeClock,stepFor};
