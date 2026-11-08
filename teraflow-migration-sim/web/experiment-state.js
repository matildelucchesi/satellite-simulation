/* Pure presentation helpers shared by the console and the Node regression tests. */
const PHASE_LABELS={
 infrastructure:'Attesa di Mininet e proxy P4',stop_target:'Arresto della destinazione',clean_target:'Pulizia del database della destinazione',
 start_source:'Avvio del controller sorgente',clean_source:'Pulizia dello scenario sorgente',restore_scenario:'Configurazione e verifica della rete',
 restore_authority:'Ripristino dell’autorità P4',baseline:'Verifica di API, autorità e ping',baseline_check:'Controllo della baseline',trigger:'Trigger della migrazione',
 alignment:'Allineamento del percorso laser',quiescence:'Quiete della sorgente',snapshot_initial:'Snapshot dello stato',source_stop:'Arresto della sorgente',
 source_stopped:'Sorgente arrestata',software_on_board:'Software già a bordo della destinazione',transfer:'Trasferimento dello stato',
 transfer_verified:'Trasferimento verificato',target_start:'Avvio del controller destinazione',restore_initial:'Ripristino dello stato sulla destinazione',
 freeze:'Freeze della sorgente',source_frozen:'Sorgente in freeze',restore_delta:'Applicazione del delta',verify:'Verifica di equivalenza API',
 ack:'ACK della destinazione',cutover:'Passaggio dell’autorità',completed:'Migrazione completata',service_verified:'Servizio verificato',
 run_finished:'Prova conclusa',cleanup:'Messa in sicurezza del laboratorio',cleanup_verified:'Laboratorio in sicurezza',job_finished:'Job concluso',
 event_comparison:'Nuova prova',comparison_run:'Nuova prova',prepare:'Preparazione della prova'};
const OPERATION_LABELS={functional:'Verifica',compare_events:'Esperimento a eventi',recover:'Ripristino del laboratorio',environment:'Controllo dell’ambiente'};
const STATUS_LABELS={queued:'in coda',running:'in corso',completed:'concluso',failed:'non riuscito',interrupted:'interrotto',recovery_required:'ripristino necessario',recovered:'ripristinato'};

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
 if(seconds===null||seconds===undefined||!Number.isFinite(seconds))return 'non misurato';
 return seconds<100?`${seconds.toFixed(1).replace('.',',')} s`:`${Math.round(seconds)} s`;
}

/* Headline for the laboratory job shown on the experiment page. */
function jobView(job,comparison,now=Date.now()){
 if(!job)return {title:'Laboratorio libero',detail:'Nessun job in corso.',active:false,canStop:false,needsRecovery:false};
 const active=['queued','running'].includes(job.status);
 const operation=OPERATION_LABELS[job.operation]||job.operation;
 const progress=job.progress||{};
 const current=comparison&&comparison.current;
 /* Experiment position: run n of N, event, replica (or warm-up), mode. Schema 1 had no replicas. */
 const where=job.operation==='compare_events'&&current?(current.position?` · prova ${current.position}/${current.total} · evento ${current.event}/${comparison.event_total} · ${current.warmup?'riscaldamento':'replica '+current.replica+'/'+comparison.design.replicas} · ${methodLabel(current.method)}`:` · evento ${current.event}/${comparison.event_total} · ${methodLabel(current.method)}`):'';
 const step=phaseLabel(progress);
 const started=Date.parse(job.started_utc||job.created_utc||'');
 const elapsed=Number.isFinite(started)?clock((now-started)/1000):'—';
 const needsRecovery=job.status==='recovery_required'||(job.application_success===false&&job.result&&job.result.recovery_required===true);
 let detail;
 if(active)detail=(job.cancellation_requested?'Interruzione richiesta: messa in sicurezza in corso. ':'')+(step||'Avvio')+` · tempo trascorso ${elapsed}`;
 else if(needsRecovery)detail='Il laboratorio va ripristinato prima di un nuovo job.';
 else detail=job.error?`Esito: ${job.error}`:job.application_success===false?'Il job non ha completato la prova: vedi i risultati per la causa.':'Il job si è concluso.';
 const elapsedSeconds=Number.isFinite(started)?Math.max(0,(now-started)/1000):null;
 return {title:`${operation}${where} · ${STATUS_LABELS[job.status]||job.status}`,detail,active,canStop:active&&!job.cancellation_requested,needsRecovery,
  operation:job.operation,step:step||'Avvio',elapsed,elapsedSeconds};
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
