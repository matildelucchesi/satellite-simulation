/* Pure presentation helpers shared by the console and the Node regression tests. */
const PHASE_LABELS={
 infrastructure:'Waiting for Mininet and the P4 proxy',stop_target:'Stopping the destination',clean_target:'Cleaning the destination database',
 start_source:'Starting the source controller',clean_source:'Cleaning the source scenario',restore_scenario:'Configuring and checking the network',
 restore_authority:'Restoring the P4 authority',baseline:'Checking API, authority and pings',baseline_check:'Baseline check',trigger:'Migration trigger',
 alignment:'Laser path alignment',quiescence:'Source quiescence',snapshot_initial:'State snapshot',source_stop:'Stopping the source',
 source_stopped:'Source stopped',software_on_board:'Software already on board the destination',transfer:'State transfer',
 transfer_verified:'Transfer verified',target_start:'Starting the destination controller',restore_initial:'Restoring the state on the destination',
 freeze:'Source freeze',source_frozen:'Source frozen',restore_delta:'Applying the delta',verify:'API equivalence check',
 ack:'Destination ACK',cutover:'Authority handover',completed:'Migration complete',service_verified:'Service verified',
 run_finished:'Run finished',cleanup:'Making the laboratory safe',cleanup_verified:'Laboratory safe',job_finished:'Job finished',
 event_comparison:'New run',comparison_run:'New run',prepare:'Preparing the run'};
const OPERATION_LABELS={functional:'Verification',compare_events:'Event experiment',recover:'Laboratory recovery',environment:'Environment check'};
const STATUS_LABELS={queued:'queued',running:'running',completed:'finished',failed:'failed',interrupted:'stopped',recovery_required:'recovery required',recovered:'recovered'};

function methodLabel(method){return method==='hot'?'Hot':method==='cold'?'Cold':method||'';}

function phaseLabel(event){
 if(!event)return '';
 if(event.label)return event.label;
 const key=event.operation||event.subphase||event.phase;
 return PHASE_LABELS[key]||PHASE_LABELS[event.phase]||key||'';
}

function clock(seconds){
 if(!Number.isFinite(seconds))return '—';
 const total=Math.max(0,Math.round(seconds)),h=Math.floor(total/3600),m=Math.floor(total%3600/60),s=total%60;
 return [h,m,s].map(value=>String(value).padStart(2,'0')).join(':');
}

function duration(seconds){
 if(seconds===null||seconds===undefined||!Number.isFinite(seconds))return 'not measured';
 return seconds<100?`${seconds.toFixed(1)} s`:`${Math.round(seconds)} s`;
}

/* Headline for the laboratory job shown on the experiment page. */
function jobView(job,comparison,now=Date.now()){
 if(!job)return {title:'Laboratory free',detail:'No job running.',active:false,canStop:false,needsRecovery:false};
 const active=['queued','running'].includes(job.status);
 const operation=OPERATION_LABELS[job.operation]||job.operation;
 const progress=job.progress||{};
 const current=comparison&&comparison.current;
 /* Experiment position: run n of N, event, replica (or warm-up), mode. Schema 1 had no replicas. */
 const where=job.operation==='compare_events'&&current?(current.position?` · run ${current.position}/${current.total} · event ${current.event}/${comparison.event_total} · ${current.warmup?'warm-up':'replica '+current.replica+'/'+comparison.design.replicas} · ${methodLabel(current.method)}`:` · event ${current.event}/${comparison.event_total} · ${methodLabel(current.method)}`):'';
 const step=phaseLabel(progress);
 const started=Date.parse(job.started_utc||job.created_utc||'');
 const elapsed=Number.isFinite(started)?clock((now-started)/1000):'—';
 const needsRecovery=job.status==='recovery_required'||(job.application_success===false&&job.result&&job.result.recovery_required===true);
 let detail;
 if(active)detail=(job.cancellation_requested?'Stop requested: making the laboratory safe. ':'')+(step||'Starting')+` · elapsed ${elapsed}`;
 else if(needsRecovery)detail='The laboratory must be recovered before a new job.';
 else detail=job.error?`Outcome: ${job.error}`:job.application_success===false?'The job did not complete the run: see the results for the cause.':'The job finished.';
 const elapsedSeconds=Number.isFinite(started)?Math.max(0,(now-started)/1000):null;
 return {title:`${operation}${where} · ${STATUS_LABELS[job.status]||job.status}`,detail,active,canStop:active&&!job.cancellation_requested,needsRecovery,
  operation:job.operation,step:step||'Starting',elapsed,elapsedSeconds};
}

/* Duration of the verification: the latest successful one, else the typical 15 min measured on
   7 November 2026. The experiment is estimated from it: a verification is two runs, the
   experiment runs `runs` of them (warm-up included). */
const TYPICAL_VERIFICATION_S=15*60;
function procedureDurations(jobs,runs=19){
 const job=(jobs||[]).find(row=>row.operation==='functional'&&row.status==='completed'&&row.application_success!==false&&row.started_utc&&row.finished_utc);
 const measured=job?(Date.parse(job.finished_utc)-Date.parse(job.started_utc))/1000:NaN;
 const functional=Number.isFinite(measured)&&measured>0?{seconds:measured,measured:true}:{seconds:TYPICAL_VERIFICATION_S,measured:false};
 return {functional,compare_events:{seconds:functional.seconds/2*runs,estimated:true,runs}};
}

/* Runs of an experiment: warm-up, then each event in Hot and Cold for every replica. */
function experimentRuns(events,replicas=3,warmup=1){return warmup+events*replicas*2;}

/* Time axis in minutes with at most 8 ticks: steps of 10, 30 or 60 minutes. */
function axisScale(seconds){
 const span=Math.max(10,Math.max(...seconds,0)/60);
 const step=[10,30,60,120].find(value=>Math.ceil(span/value)<=7)||240;
 const minutes=Math.ceil(span/step)*step;
 const ticks=[];for(let value=0;value<=minutes;value+=step)ticks.push(value);
 return {maxSeconds:minutes*60,ticks,step};
}

/* Long durations as hours and minutes. */
function hoursMinutes(seconds){
 if(!Number.isFinite(seconds))return '—';
 const total=Math.round(seconds/60),h=Math.floor(total/60),m=total%60;
 return h?`${h} h${m?' '+m+' min':''}`:`${m} min`;
}

/* Readable timeline from raw job events: consecutive duplicates removed, newest last. */
function timeline(events,limit=14){
 const rows=[];
 for(const event of events){
  if(['restore_request','restore_progress','infrastructure_wait','source_startup','heartbeat'].includes(event.phase))continue;
  const text=phaseLabel(event);
  if(!text)continue;
  if(rows.length&&rows[rows.length-1].text===text)continue;
  rows.push({id:event.id,time:(event.timestamp_utc||'').slice(11,19),text,failed:event.operation_status==='failed'||!!event.error});
 }
 return rows.slice(-limit);
}

if(typeof module!=='undefined')module.exports={phaseLabel,clock,duration,jobView,timeline,methodLabel,procedureDurations,experimentRuns,axisScale,hoursMinutes};
