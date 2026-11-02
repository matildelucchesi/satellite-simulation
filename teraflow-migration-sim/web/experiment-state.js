/* Pure presentation model shared by the console and browser regression tests. */
function experimentView(pair, job, now=Date.now(), operationLabels={}) {
 const p=job?.progress||pair?.progress||{}, terminal=pair?.phase==='finished';
 const age=value=>value?Math.max(0,Math.floor((now-Date.parse(value))/1000)):null;
 const phase=p.phase||pair?.phase||'configuration';
 const labels={configuration:'Configura il confronto',preparation:'Verifica laboratorio',calibration:'Calibrazione',planning:'Piano condiviso',hot:'Esecuzione Hot',resetting:'Ripristino',cold:'Esecuzione Cold',finished:'Risultati'};
 const recoveryFailed=job?.operation==='recover'&&['recovery_required','failed','interrupted'].includes(job.status);
 const error=pair?.error||(!terminal?p.error:null)||(recoveryFailed?{code:'recovery_failed',message:'Il recupero del laboratorio non è riuscito.',technical_detail:job.error}:null);
 const admissionRejected=!!(!Object.keys(pair?.sessions||{}).length&&(error?.code==='plan_not_admissible'||(terminal&&pair?.reason?.startsWith('No feasible sequence'))));
 const recovery=pair?.recovery_required||job?.status==='recovery_required';
 const failed=terminal&&!pair.success;
 const title=recovery?'Ripristino necessario':job?.operation==='recover'&&['queued','running'].includes(job.status)?'Ripristino laboratorio':job?.cancellation_requested&&!terminal?'Interruzione in corso':terminal?(pair.success?'Confronto completato':pair.outcome==='interrupted'?'Confronto interrotto':admissionRejected?'Sequenza non ammissibile':'Confronto non completato'):labels[phase]||'Preparazione laboratorio';
 let detail=p.label||operationLabels[p.subphase]||'La preparazione precede l’avvio del clock orbitale.';
 if(p.subphase==='restore_scenario'&&p.restore_counts&&!terminal){
  const c=p.restore_counts,entity=p.restore_entity?.name;
  detail=p.restore_verification==='running'?'Verifica finale dello scenario':p.restore_verification==='completed'?'Scenario caricato e verificato':
   `Caricamento satelliti: ${c.devices.completed}/${c.devices.total} · link: ${c.links.completed}/${c.links.total} · servizi: ${c.services.completed}/${c.services.total}${entity?` — ${entity}`:''}`;
 }
 if(['hot','cold'].includes(phase)&&!p.label)detail=`Il clock orbitale procede in tempo reale. Migrazioni verificate: ${p.completed_migrations??0}.`;
 if(p.calibration_index&&phase==='calibration') detail=`Test preliminare ${p.calibration_index}/${p.calibration_total||(p.calibration_index>2?6:2)} · ${(p.method||'').toUpperCase()} · ${detail}`;
 if(p.calibration_index&&phase==='calibration')detail+=' · Calibrazione separata: il confronto si avvia dalla configurazione quando le misure sono valide.';
 if(p.subphase==='departure_search'&&!terminal)detail=`Ricerca della partenza · ${p.examined_candidates??0} candidati · ${Math.floor(p.elapsed_s??0)} s / ${p.limit_s??600} s${p.selected?` · migliore NORAD ${p.selected.initial_satellite_id} a ${p.selected.start_orbital_s} s · margine ${p.selected.minimum_margin_s} s`:' · nessuna soluzione verificata finora'}.`+(p.rejections?' Esclusioni: '+Object.entries(p.rejections).map(([key,value])=>`${({service_path_window:'Percorso del servizio non continuo durante la migrazione',insufficient_contact:'Contatto troppo breve',future_dead_end:'Migrazioni successive non ammissibili',initial_shadow_outside_observation:'Ingresso in ombra iniziale non osservabile nei dati',initial_resource_or_shadow:'Partenza in ombra o risorse insufficienti',initial_service_path:'Percorso iniziale del servizio assente',destination_in_shadow:'Destinazione in ombra',destination_deadline:'Illuminazione destinazione insufficiente',source_deadline_before_safe_completion:'Tempo sorgente insufficiente per operazione e recupero',negative_safety_margin:'Margine di sicurezza insufficiente'})[key]||key}: ${value}`).join(', '):'');
 if(job?.cancellation_requested&&!terminal)detail='Richiesta ricevuta. Messa in sicurezza del laboratorio in corso; un nuovo avvio resta bloccato fino alla verifica.';
 if(!pair&&!['functional','calibrate','prepare_base'].includes(job?.operation)) detail='Scegli la velocità. Prima Hot, poi Cold sullo stesso piano: obiettivo 3 migrazioni verificate per modalità.';
 if(terminal) detail=pair.success?'Entrambe le modalità sono terminate. Verifica eventi confrontabili e provenienza nei risultati.':'Le misure mancanti non sono zero. Consulta la causa e lo stato del ripristino prima di riprovare.';
 if(job?.operation==='recover')detail=recoveryFailed?'Il recupero si è fermato. Il laboratorio resta bloccato e le evidenze sono conservate.':'Recupero del laboratorio in corso. Attendere la verifica prima di un nuovo confronto.';
 const explanations={dependency_unhealthy:'Una dipendenza del controller non supera il controllo di salute.',startup_failed:'Il controller non è riuscito ad avviarsi.',startup_timeout:'Il controller non è diventato disponibile entro il limite di avvio.',preparation_timeout:'La sottofase di preparazione ha raggiunto il suo limite di tempo.',p4_not_ready:'Mininet o l’autorità P4 non hanno superato la verifica iniziale.',invalid_baseline:'Il servizio iniziale non ha superato la verifica API, autorità e sonde.',preparation_failed:'Un’operazione di preparazione del laboratorio non è riuscita.',interrupted:'L’esecuzione è stata interrotta.'};
 return {phase,title,detail,failed,recovery,error,admissionRejected,recoveryFailed,
  errorTitle:job?.worker_lost?'Il processo si è interrotto senza concludere il lavoro. Ripristinare il laboratorio prima di un nuovo avvio.':pair?.outcome==='interrupted'?'Esecuzione interrotta su richiesta.':admissionRejected?'I vincoli di contatto, illuminazione e risorse non consentono il piano richiesto.':error?.code==='departure_search_incomplete'?'Ricerca interrotta dal limite di tempo: non è stata accertata l’assenza di soluzioni.':error?error.message||explanations[error.code]||'La preparazione non è riuscita.':pair?.reason||'Informazione non disponibile per questo confronto storico.',
  elapsed:age(pair?.created_utc||p.started_utc),age:age(p.last_progress_utc),
  heartbeatAge:age(job?.worker_heartbeat?.timestamp_utc),
  deadline:!terminal&&p.operation_status==='running'?p.deadline_utc:null,
  workerActive:['queued','running'].includes(job?.status),terminal};
}
if(typeof module!=='undefined')module.exports={experimentView};

function experimentPage(pair,job,orbit,pending,previous){
 if(['functional','calibrate','prepare_base'].includes(job?.operation))return job.cancellation_requested?(['queued','running'].includes(job.status)?'preparation':'configuration'):['queued','running','failed','recovery_required'].includes(job.status)?'preparation':'configuration';
 if(job?.cancellation_requested||pair?.outcome==='interrupted')return ['queued','running'].includes(job?.status)?'preparation':'configuration';
 if(pending||job?.operation==='recover'&&['queued','running'].includes(job.status))return 'preparation';
 if(pair?.phase==='finished')return 'results';
 if(job&&['failed','interrupted','recovery_required'].includes(job.status))return 'results';
 if(!pair)return 'configuration';
 if(previous==='simulation'&&Object.keys(pair.sessions||{}).length)return 'simulation';
 const view=orbit?.presentation;
 return Object.keys(pair.sessions||{}).length&&view?.initial_controller_ready===true&&view?.mode!=='preview'?'simulation':'preparation';
}
if(typeof module!=='undefined')module.exports.experimentPage=experimentPage;

function experimentRoute(page,started){
 return !started&&['simulation','results'].includes(page)?'configuration':page;
}
if(typeof module!=='undefined')module.exports.experimentRoute=experimentRoute;

// Group each restore separately, including after an SSE reconnect/replay.
function groupTimelineEvents(events){
 const rows=[];let active=null,requestIndex=new Map();
 for(const event of [...events].sort((a,b)=>a.id-b.id)){
  const operation=event.phase==='preparation_operation'&&event.operation==='restore_scenario';
  if(operation||['restore_request','restore_progress'].includes(event.phase)){
   if(!active){requestIndex=new Map();active={phase:'restore_group',id:event.id,timestamp_utc:event.timestamp_utc,status:'running',counts:null,verification:null,entity:null,requests:[]};rows.push(active);}
   if(event.counts)active.counts=event.counts;
   if(event.entity)active.entity=event.entity;
   if(event.verification)active.verification=event.verification;
   if(event.phase==='restore_request'){
    const request=event.request||{};
    const key=String(request.started_monotonic??request.started_utc??event.id)+' '+request.method+' '+request.path;
    const previous=requestIndex.get(key);
    const value={...request,key,request_status:event.request_status,timestamp_utc:event.timestamp_utc};
    if(previous)Object.assign(previous,value);else{active.requests.push(value);requestIndex.set(key,value);}
    if(event.request_status==='failed')active.status='failed';
   }
   if(operation){active.status=event.operation_status||active.status;if(event.error)active.error=event.error.message||event.error.code;if(['completed','failed'].includes(event.operation_status))active=null;}
  }else{rows.push(event);active=null;}
 }
 return rows;
}
if(typeof module!=='undefined')module.exports.groupTimelineEvents=groupTimelineEvents;

function preparationView(pair,job,orbit){
 const p=job?.progress||pair?.progress||{};
 if(job?.cancellation_requested&&['queued','running'].includes(job.status))return {chosen:false,ready:false,stopping:true,title:'Interruzione in corso',detail:'Richiesta ricevuta. Messa in sicurezza del laboratorio in corso; al termine tornerai alla configurazione.'};
 if(['functional','calibrate','prepare_base'].includes(job?.operation))return {chosen:false,ready:false,
  title:['failed','recovery_required'].includes(job.status)?'Preparazione non completata':p.phase==='calibration'||job.operation==='calibrate'?`Calibrazione ${(p.method||'').toUpperCase()} · prova ${p.replica||1}/${p.replicas_per_mode||3}`:p.label||({calibration:'Calibrazione dello scenario iniziale',planning:'Scelta del controller',scenario_creation:'Creazione scenario iniziale'})[p.phase]||'Creazione scenario iniziale',
  detail:['failed','recovery_required'].includes(job.status)?'Consulta i dettagli del laboratorio e la timeline per la causa e l’eventuale recupero.':p.phase==='calibration'||job.operation==='calibrate'?`Prove preliminari Hot/Cold per misurare i tempi di migrazione. ${p.label||'Calibrazione in corso'}. Il confronto finale non è ancora avviato.`:'Preparazione dello scenario e del controller sorgente. Al termine tornerai alla configurazione per scegliere la velocità e premere Avvia.'};
 const selected=pair?.resolved_configuration?.initial_satellite_id;
 const chosen=selected!==undefined&&selected!==null||Object.keys(pair?.sessions||{}).length>0;
 const ready=orbit?.presentation?.initial_controller_ready===true&&orbit?.presentation?.mode!=='preview';
 const preliminary=['preparation','calibration'].includes(p.phase||pair?.phase);
 return {chosen,ready,satellite:selected,
  title:ready?'Controller pronto':p.operation_status==='running'&&p.label?p.label:chosen?'Attivazione API controller':preliminary?'Calibrazione preliminare':'Scelta del controller',
  detail:ready?'API, autorità P4 e servizio verificati. Avvio della simulazione.':chosen?'Avvio delle API, caricamento dello scenario e verifica del servizio prima di avviare il clock orbitale.':preliminary?'Verifiche e calibrazioni preliminari: misuriamo i tempi necessari per scegliere una partenza sicura.':'Ricerca della partenza più vicina all’ombra che rispetta i vincoli di sicurezza per Hot e Cold.'};
}
if(typeof module!=='undefined')module.exports.preparationView=preparationView;


function scenarioCreationProgress(job,events=[]){
 const rows=[...events].sort((a,b)=>a.id-b.id),p=job?.progress||{};
 const baseStart=rows.find(row=>row.phase==='scenario_creation'&&/Preparazione della base comune|Attivazione del controller sorgente|Piano comune pronto/.test(row.label||''));
 const creation=['prepare_base','functional','calibrate'].includes(job?.operation);
 const calibration=creation&&!baseStart&&(job.operation!=='prepare_base'||!['planning','common_base_ready'].includes(p.phase));
 const trials=rows.filter(row=>row.phase==='calibration');
 const first=trials[0]?.id??Infinity;
 const successful=new Set(rows.filter(row=>row.id>first&&row.phase==='run_finished'&&['success','completed'].includes(row.outcome)).map(row=>row.run_id));
 const replicas=p.replicas_per_mode||trials.at(-1)?.replicas_per_mode||(p.calibration_total===6||p.calibration_index>2||trials.some(row=>row.replica>1)?3:1),total=2*replicas;
 const index=p.phase==='calibration'?p.calibration_index||((p.replica||1)+(p.method==='hot'?replicas:0)):trials.length?((trials.at(-1).replica||1)+(trials.at(-1).method==='hot'?replicas:0)):0;
 const completed=Math.min(total,Math.max(successful.size,index?index-1:0));
 return {creation,calibration,completed,total,index:calibration?index:0,timelineStartId:baseStart?.id,
  trials:Array.from({length:total},(_,i)=>({label:(i<replicas?'COLD':'HOT')+' · prova '+(i%replicas+1)+'/'+replicas,status:i<completed?'Completata':i===index-1?(['failed','recovery_required','interrupted'].includes(job?.status)?'Interrotta':'In corso'):'In attesa'}))};
}
if(typeof module!=='undefined')module.exports.scenarioCreationProgress=scenarioCreationProgress;


function experimentLandingPage(page,requested,initial){
 return initial&&page!=='preparation'?(['configuration','simulation','results'].includes(requested)?requested:'configuration'):page;
}
if(typeof module!=='undefined')module.exports.experimentLandingPage=experimentLandingPage;
