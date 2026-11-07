/* Pure presentation helpers shared by the console and the Node regression tests. */
const PHASE_LABELS={
 infrastructure:'Attesa di Mininet e proxy P4',stop_target:'Arresto della destinazione',clean_target:'Pulizia del database della destinazione',
 start_source:'Avvio del controller sorgente',clean_source:'Pulizia dello scenario sorgente',restore_scenario:'Configurazione e verifica della rete',
 restore_authority:'Ripristino dell’autorità P4',baseline:'Verifica di API, autorità e ping',baseline_check:'Controllo della baseline',trigger:'Trigger della migrazione',
 alignment:'Allineamento del laser',quiescence:'Quiete della sorgente',snapshot_initial:'Snapshot dello stato',source_stop:'Arresto della sorgente',
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
 const where=job.operation==='compare_events'&&current?` · evento ${current.event}/${comparison.event_total} · ${methodLabel(current.method)}`:'';
 const step=phaseLabel(progress);
 const started=Date.parse(job.started_utc||job.created_utc||'');
 const elapsed=Number.isFinite(started)?clock((now-started)/1000):'—';
 const needsRecovery=job.status==='recovery_required'||(job.application_success===false&&job.result&&job.result.recovery_required===true);
 let detail;
 if(active)detail=(job.cancellation_requested?'Interruzione richiesta: messa in sicurezza in corso. ':'')+(step||'Avvio')+` · tempo trascorso ${elapsed}`;
 else if(needsRecovery)detail='Il laboratorio va ripristinato prima di un nuovo job.';
 else detail=job.error?`Esito: ${job.error}`:job.application_success===false?'Il job non ha completato la prova: vedi i risultati per la causa.':'Il job si è concluso.';
 return {title:`${operation}${where} · ${STATUS_LABELS[job.status]||job.status}`,detail,active,canStop:active&&!job.cancellation_requested,needsRecovery};
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

if(typeof module!=='undefined')module.exports={phaseLabel,clock,duration,jobView,timeline,methodLabel};
