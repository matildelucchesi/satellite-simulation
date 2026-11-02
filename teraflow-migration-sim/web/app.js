'use strict';
const $=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg';
document.querySelector('.local').textContent=location.host;
const outcomeLabels={success:'Riuscita',running:'In corso',failed:'Fallita',experimental_failure:'Fallita',rejected:'Non ammissibile',interrupted:'Interrotta',recovery_required:'Ripristino necessario',invalid_lab:'Misure non valide',invalid_baseline:'Servizio iniziale non valido',worker_lost:'Esecuzione interrotta'};
const phaseLabels={comparison_run:'Prova della coppia FSO',service_verified:'Servizio Mininet verificato',planning:'Pianificazione',admission_rejected:'Sequenza non ammissibile',plan_admitted:'Piano ammesso',baseline_valid:'Baseline valida',baseline_check:'Verifica baseline',replanning:'Ripianificazione',simulation_finished:'Sessione terminata',trigger:'Trigger',alignment:'Allineamento FSO',quiescence:'Quiescenza',snapshot_initial:'Snapshot iniziale',source_stop:'Arresto sorgente',source_stopped:'Sorgente arrestata',transfer:'Trasferimento',transfer_verified:'Checksum verificato',target_start:'Importazione immagini e avvio destinazione',restore_initial:'Restore iniziale',freeze:'Freeze sorgente',source_frozen:'Sorgente congelata',restore_delta:'Applicazione delta',verify:'Verifica API',ack:'ACK',cutover:'Cutover hardware',completed:'Migrazione completata',attempt_failed:'Tentativo fallito',rollback:'Recupero sorgente',failed:'Migrazione fallita',prepare:'Preparazione fixture',run_finished:'Prova terminata',job_finished:'Job terminato',calibration:'Calibrazione',transport_capacity:'Verifica capacità TCP',workflow_stage:'Fase del workflow'};
const comparisonLabels={planning:'Ricerca di una sequenza comune',preparation:'Verifica iniziale Hot/Cold',calibration:'Calibrazione automatica',departure_search:'Ricerca della partenza',hot:'Esecuzione Hot',resetting:'Ripristino dello scenario iniziale',cold:'Esecuzione Cold',finished:'Confronto terminato'};
let token='',state=null,jobs=[],comparisons=[],simulations=[],artifacts=[];
let initialConfiguration=null;
let initialConfigurationRequest=null;
let initialViewRequested=false;
phaseLabels.controller_assigned='Controller assegnato e verificato';
let selectedComparison='',selectedSimulation='',selectedJob='',simulationTick=null,stream=null;
const selectedRun='',replayTick=null;
let events=new Map(),loading=false,following=false,manualComparison=false,pendingJob='',stoppingJob='',refreshTimer,liveView=null;
const number=(value,digits=2)=>value===null||value===undefined?'—':Number(value).toLocaleString('it-IT',{maximumFractionDigits:digits});
const seconds=value=>value===null||value===undefined?'—':number(value)+' s';
const clockText=value=>Number.isFinite(value)?new Date(Math.max(0,value)*1000).toISOString().slice(11,19):'—';
function notice(message,error=false){$('notice').textContent=message;$('notice').dataset.state=error?'error':'success';}
async function api(path,body){const response=await fetch('/api/v1'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);return data;}
function option(select,value,label){const node=document.createElement('option');node.value=value;node.textContent=label;select.append(node);}
function svg(tag,attrs={},parent){const node=document.createElementNS(ns,tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(parent)parent.append(node);return node;}
function svgText(parent,x,y,text,cls=''){const node=svg('text',{x,y,class:cls},parent);node.textContent=text;return node;}
const currentPair=()=>comparisons.find(row=>row.comparison_id===selectedComparison);
const operationName=op=>({compare_continuous:'Confronto continuo Hot/Cold',recover:'Ripristino laboratorio'}[op]||'Esecuzione del laboratorio');
function selectSimulation(identifier,follow=false){if(selectedSimulation!==identifier){resetOrbit();simulationTick=null;}selectedSimulation=identifier;following=follow;$('simulation-select').value=identifier;$('follow-current').hidden=following;$('live-progress').hidden=!identifier;}
function renderState(){
 const busy=jobs.find(row=>row.job_id===state.lock?.job_id),locked=!!state.lock;
 const configuration=busy?.operation==='recover'?jobs.find(row=>row.job_id===busy.previous_job_id)?.parameters:busy?.operation==='compare_continuous'?busy.parameters:null;
 const reachable=Object.values(state.components).filter(row=>row.reachable).length;
 $('console-health').textContent=locked?'Verifica requisiti per la fase corrente':'Laboratorio in attesa di verifica';$('console-health').dataset.offline=String(!state.components.mininet?.reachable||!state.components.p4_proxy?.reachable);
 $('console-operation').textContent=locked?operationName(busy?.operation):'Nessun confronto in corso';
 $('start').disabled=locked||!!pendingJob;$('stop').disabled=state.worker_alive===false||!busy||!['queued','running'].includes(busy.status)||stoppingJob===busy.job_id;
 $('channel-rate').disabled=locked;if(locked&&configuration?.rate_bps)$('channel-rate').value=String(configuration.rate_bps);
 const resolved=currentPair()?.resolved_configuration;
 initialConfigurationRequest=resolved?{initial_satellite_id:resolved.initial_satellite_id,start_orbital_s:resolved.start_orbital_s}:null;
 $('recover').hidden=!locked||!busy||(!['recovery_required','failed','interrupted'].includes(busy.status)&&state.worker_alive!==false);
 const components=$('components');components.replaceChildren();
 for(const [name,value]of [['Mininet / BMv2',state.components.mininet?.reachable?'Raggiungibile':'Non disponibile'],['Controller A',controllerRequirement('sat_a',busy)],['Controller B',controllerRequirement('sat_b',busy)],['Autorità P4',state.components.p4_proxy?.reachable?state.components.p4_proxy.data.active||'Nessuna · fenced':'Non disponibile']]){const li=document.createElement('li'),title=document.createElement('span'),status=document.createElement('span');title.textContent=name;status.textContent=value;status.className='component-value';li.append(title,status);components.append(li);}
 if(locked||currentPair()?.phase!=='finished')notice(locked?`Laboratorio occupato · ${operationName(busy?.operation)}${busy?.status==='recovery_required'?' · ripristino necessario':''}`:'Laboratorio libero. Avvia un confronto continuo Hot/Cold.');
}
function renderSelectors(){
 const select=$('comparison-select');select.replaceChildren();option(select,'','Nessun confronto');
 for(const row of comparisons)option(select,row.comparison_id,`${new Date(row.created_utc).toLocaleString('it-IT')} · ${outcomeLabels[row.outcome]||row.outcome}`);
 select.value=selectedComparison;
 const pair=currentPair(),sessions=$('simulation-select');sessions.replaceChildren();option(sessions,'','Nessuna esecuzione');
 for(const mode of ['hot','cold'])if(pair?.sessions[mode]){const result=pair.session_results[mode];option(sessions,pair.sessions[mode],`${mode.toUpperCase()} · ${result?outcomeLabels[result.outcome]||result.outcome:pair.current_method===mode?'In corso':'Preparazione'}`);}
 sessions.value=selectedSimulation;
}
function tableRow(parent,values,labels){const row=document.createElement('tr');values.forEach((value,index)=>{const cell=document.createElement('td');cell.dataset.label=labels[index];if(value instanceof Node)cell.append(value);else cell.textContent=value;row.append(cell);});parent.append(row);}
function sessionButton(mode,pair,label,tick=null){const button=document.createElement('button');button.type='button';button.textContent=label;button.disabled=!pair.sessions[mode];button.addEventListener('click',()=>{selectSimulation(pair.sessions[mode]);simulationTick=tick;topology();});return button;}
function renderComparison(){
 const pair=currentPair(),body=$('pair-rows'),eventRows=$('event-rows');body.replaceChildren();eventRows.replaceChildren();
 $('pair-title').textContent=pair?'Risultati del confronto selezionato · '+new Date(pair.created_utc).toLocaleString('it-IT'):'Risultati del confronto';
 if(!pair){$('pair-status').textContent='Nessun confronto disponibile. Scegli la velocità e avvia Hot/Cold.';$('plan-provenance').textContent='';$('comparison-phase').textContent='Preparazione → Hot → Ripristino → Cold → Risultati';return;}
 $('comparison-phase').textContent=`${comparisonLabels[pair.phase]||pair.phase}${pair.phase==='finished'?' · '+(outcomeLabels[pair.outcome]||pair.outcome):''}`;
 $('pair-status').textContent=`${pair.complete?'Confronto completato':pair.phase==='finished'?'Confronto incompleto':'Confronto in corso'} · ${pair.parameters.migration_count?'Obiettivo: '+pair.parameters.migration_count+' migrazioni per modalità':number(pair.parameters.duration_s,0)+' s per modalità'} · ${pair.events.length} eventi pianificati · ${pair.events.filter(row=>row.comparable).length} confrontabili`+(pair.reason?' · '+(pair.error?.code==='plan_not_admissible'?'Sequenza non ammissibile: dettagli nelle evidenze':pair.error?.code==='departure_search_incomplete'?'Ricerca incompleta: dettagli nelle evidenze':pair.success?'':'Confronto non completato: consultare causa ed evidenze'):'');
 const labels=['Modalità','Esito','Migrazioni tentate','Migrazioni riuscite','Downtime controller cumulativo','Tempo simulato trascorso'];
 for(const mode of ['hot','cold']){const result=pair.session_results[mode],total=pair.totals[mode];tableRow(body,[sessionButton(mode,pair,mode.toUpperCase()),result?outcomeLabels[result.outcome]||result.outcome:pair.current_method===mode?'In corso':pair.phase==='finished'?'Non eseguita':'In attesa',number(total?.attempted_migrations,0),total?`${total.completed_migrations}/${pair.events.length}`:'—',seconds(total?.controller_downtime_s),seconds(total?.real_elapsed_s)],labels);}
 if(pair.complete)tableRow(body,['Cold − Hot','Differenza','—','—',seconds(pair.totals.cold_minus_hot?.controller_downtime_s),seconds(pair.totals.cold_minus_hot?.real_elapsed_s)],labels);
 const eventLabels=['Evento / satelliti','Trigger orbitale','Downtime Hot','Downtime Cold','Cold − Hot','Esito'];
 for(const row of pair.events){tableRow(eventRows,[`${row.sat_a} → ${row.sat_b}`,seconds(row.trigger_s),row.hot?sessionButton('hot',pair,seconds(row.hot.controller_downtime_s),row.trigger_s):'—',row.cold?sessionButton('cold',pair,seconds(row.cold.controller_downtime_s),row.trigger_s):'—',seconds(row.cold_minus_hot?.controller_downtime_s),row.comparable?'Confrontabile':row.hot?.success===false||row.cold?.success===false?'Evento fallito':row.hot&&row.cold?'Non confrontabile · '+(row.exclusion_reason||'evidenze incomplete'):'In attesa'],eventLabels);}
 $('plan-provenance').textContent=pair.shared_plan_sha256?`Velocità ${number(pair.parameters.rate_bps/1e6,0)} Mbit/s · NORAD ${(pair.resolved_configuration?.initial_satellite_id??pair.parameters.initial_satellite_id)} · inizio ${seconds((pair.resolved_configuration?.start_orbital_s??pair.parameters.start_orbital_s))} · Piano condiviso SHA-256 ${pair.shared_plan_sha256}`:'Il piano comune verrà salvato prima delle due esecuzioni.';
}
function renderDownloads(){const list=$('downloads');list.replaceChildren();const pair=currentPair();if(!pair)return;const prefixes=[`results/continuous-comparisons/${pair.comparison_id}/`,...Object.values(pair.sessions).map(id=>`results/simulations/${id}/`)];for(const row of artifacts.filter(item=>prefixes.some(prefix=>item.label.startsWith(prefix))&&(/\.(html|csv)$/.test(item.label)||/(metadata|plan|report|selection)\.json$/.test(item.label)))){const li=document.createElement('li'),a=document.createElement('a');a.href=row.download_url;const filename=row.label.split('/').pop();const mode=row.label.includes('/simulations/')?' · esecuzione':'';a.textContent=({"report.html":'Report leggibile',"metadata.json":'Risultati e diagnostica JSON',"events.csv":'Eventi CSV',"selection.json":'Ricerca e selezione della partenza JSON',"plan.json":'Piano condiviso JSON',"report.json":'Misure JSON'}[filename]||filename)+mode+(pair.phase==='finished'?' · definitivo':' · parziale');a.title=row.label;li.append(a);list.append(li);}}
function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(refresh,250);}
async function refresh(){
 if(loading)return;loading=true;
 try{
  [state,{jobs},{comparisons},{simulations},{artifacts}]=await Promise.all([api('/state'),api('/jobs'),api('/continuous-comparisons'),api('/simulations'),api('/artifacts')]);
  if(pendingJob){const next=comparisons.find(row=>row.job_id===pendingJob);if(next){selectedComparison=next.comparison_id;pendingJob='';}}
  else if(!selectedComparison&&!manualComparison&&comparisons.length)selectedComparison=comparisons[0].comparison_id;
  if(!manualComparison&&!pendingJob){const active=comparisons.find(row=>row.job_id===state.lock?.job_id);if(active&&active.comparison_id!==selectedComparison){selectedComparison=active.comparison_id;selectSimulation('',true);}}
  const pair=currentPair();
  if(pair&&!selectedSimulation&&!initialViewRequested&&!manualComparison&&state.lock?.job_id===pair.job_id&&['hot','cold'].includes(pair.current_method))following=true;
  if(pair){if(following){const next=pair.sessions[pair.current_method]||pair.sessions.cold||pair.sessions.hot||'';selectSimulation(next,true);}const recoveryJob=jobs.find(row=>row.job_id===state.lock?.job_id&&row.operation==='recover');const targetJob=recoveryJob?.job_id||pair.job_id;if(targetJob&&targetJob!==selectedJob)selectJob(targetJob);}
  renderState();renderSelectors();renderComparison();renderExperiment();renderDownloads();
  await topology();
 }catch(error){notice('Impossibile leggere il laboratorio: '+error.message,true);$('console-health').textContent='Laboratorio irraggiungibile';$('console-health').dataset.offline='true';stopOrbit('Connessione al laboratorio interrotta');}
 finally{loading=false;}
}
function renderLiveProgress(data){
 const metadata=simulations.find(row=>row.simulation_id===selectedSimulation),sample=data.simulation||{},view=data.presentation||{};
 const panel=$('live-progress');panel.hidden=!metadata;if(!metadata){liveView=null;return;}
 const replay=view.mode==='replay',active=!replay&&metadata.phase!=='finished',duration=metadata.parameters.duration_s,target=metadata.target_migrations;
 const completed=sample.completed_migrations??metadata.migrations?.filter(row=>row.success).length??0;
 const elapsed=Number.isFinite(metadata.start_s)&&!['planning','preparation'].includes(metadata.phase)?Math.max(0,data.orbital_s-metadata.start_s):null;
 $('live-session').textContent=`· ${metadata.parameters.method.toUpperCase()}`;
 $('live-title').textContent=`${metadata.parameters.method.toUpperCase()} · ${metadata.phase==='finished'?(outcomeLabels[metadata.outcome]||metadata.outcome):(phaseLabels[view.phase]||comparisonLabels[view.phase]||'Simulazione continua')}`;
 $('live-badge').textContent=replay?'REPLAY':active?'LIVE · tempo reale':'Terminata';panel.dataset.live=String(active);
 $('live-description').textContent=metadata.failure_reason||'Sequenza condivisa con l’altra modalità. Il clock orbitale procede in tempo reale, senza ripianificazione.';
 const percent=target?Math.min(100,completed/target*100):elapsed===null?null:Math.min(100,elapsed/duration*100);
 $('live-percent').textContent=target?`${completed}/${target} migrazioni verificate`:percent===null?'Preparazione · clock orbitale non ancora avviato':number(percent,1)+'% della durata';$('live-bar').value=percent||0;
 $('live-bar').setAttribute('aria-label',target?'Migrazioni completate':'Durata completata');
 $('live-elapsed').textContent=clockText(elapsed);$('live-remaining-label').textContent=target?'Migrazioni residue':'Tempo residuo';$('live-remaining').textContent=target?String(Math.max(0,target-completed)):clockText(elapsed===null?null:Math.max(0,duration-elapsed));
 $('live-migrations').textContent=target?`${completed}/${target}`:String(completed);
 $('live-controller').textContent=pendingController(view)?`NORAD ${pendingController(view)} · in verifica`:!view.stale&&view.controller_satellite?`NORAD ${view.controller_satellite}`:'Nessuno confermato';
 $('live-service').textContent=metadata.controllers_fenced&&active?'Sonde terminate':view.forwarding_observed===true?'Ultima sonda riuscita':view.forwarding_observed===false?'Perdita osservata':'Non ancora misurato';
 $('live-next').textContent=sample.next_migration?`NORAD ${sample.next_migration.sat_b} · t = ${number(sample.next_migration.trigger_s,0)} s`:'Nessun passaggio residuo';
 liveView={active,replay,timestamp:view.updated_utc};updateLiveFreshness();
 const geometryStart=metadata.start_s,geometryEnd=metadata.final_orbital_s??data.orbital_s;
 $('simulation-replay-control').hidden=metadata.phase!=='finished'||!Number.isFinite(geometryStart)||!Number.isFinite(geometryEnd);
 if(Number.isFinite(geometryStart)&&Number.isFinite(geometryEnd)){$('simulation-replay').min=Math.floor(geometryStart);$('simulation-replay').max=Math.floor(geometryEnd);$('simulation-replay').value=simulationTick===null?Math.floor(geometryEnd):simulationTick;}
}
function updateLiveFreshness(){if(!liveView)return;const age=liveView.timestamp?Math.max(0,Math.floor((Date.now()-Date.parse(liveView.timestamp))/1000)):null;const stale=liveView.active&&age!==null&&age>10;$('live-progress').dataset.stale=String(stale);$('live-freshness').textContent=liveView.replay?'Consultazione dei dati salvati':age===null?'In attesa di telemetria':stale?`Nessun aggiornamento da ${age} s`:`Ultima evidenza ${age} s fa`;}
function renderTimeline(){const list=$('timeline'),bottom=list.scrollTop+list.clientHeight>=list.scrollHeight-30;list.replaceChildren();for(const event of [...events.values()].sort((a,b)=>a.id-b.id).slice(-400)){const li=document.createElement('li'),time=document.createElement('time'),label=document.createElement('span');time.dateTime=event.timestamp_utc;time.textContent=event.orbital_s==null?new Date(event.timestamp_utc).toLocaleTimeString('it-IT'):seconds(event.orbital_s);label.textContent=event.phase==='departure_search'?`Ricerca della partenza · ${event.examined_candidates} candidati · ${number(event.elapsed_s,0)} s`:event.phase==='continuous_comparison'?comparisonLabels[event.comparison_phase]:event.phase==='comparison_session'?`Avvio ${event.method.toUpperCase()}`:(event.phase==='preparation_operation'?`${event.label} · ${{running:'In corso',completed:'Completata',failed:'Fallita'}[event.operation_status]||event.operation_status}`:event.phase==='calibration'?`Calibrazione ${(event.method||'').toUpperCase()} · prova ${event.replica}/3`:phaseLabels[event.phase])||({comparison_finished:'Confronto terminato',simulation_finished:'Esecuzione terminata'}[event.phase])||event.phase;li.append(time,label);if(event.reason){const reason=document.createElement('span');reason.className='reason';reason.textContent=event.reason;li.append(reason);}list.append(li);}if(bottom)list.scrollTop=list.scrollHeight;}
function selectJob(identifier){selectedJob=identifier;events.clear();renderTimeline();if(stream)stream.close();if(!identifier)return;const source=new EventSource('/api/v1/jobs/'+identifier+'/events');stream=source;source.onopen=()=>{if(selectedJob!==identifier)return;orbitStreamDisconnected=false;$('stream-status').textContent='Aggiornamenti connessi';topology();};source.onmessage=message=>{if(selectedJob!==identifier)return;const event=JSON.parse(message.data);if(event.phase!=='session_tick'){events.set(event.id,event);renderTimeline();}if(event.phase==='session_tick'&&event.simulation_id===selectedSimulation&&simulationTick===null){clearTimeout(orbitalUpdateTimer);orbitalUpdateTimer=setTimeout(topology,150);}if(['continuous_comparison','comparison_session','comparison_finished','simulation_finished','preparation_operation','calibration','departure_search'].includes(event.phase))scheduleRefresh();};source.onerror=()=>{if(selectedJob!==identifier)return;orbitStreamDisconnected=true;$('stream-status').textContent='Connessione interrotta · riconnessione automatica';if(orbitData?.presentation?.mode==='live')stopOrbit('Stream disconnesso · riconnessione in corso');};source.addEventListener('end',()=>{source.close();if(selectedJob!==identifier)return;orbitStreamDisconnected=false;$('stream-status').textContent='Timeline completa';stoppingJob='';scheduleRefresh();});}
$('job-form').addEventListener('submit',async event=>{event.preventDefault();$('start').disabled=true;$('launch-error').hidden=true;try{const job=await api('/jobs',{operation:'compare_continuous',parameters:{migration_count:3,rate_bps:Number($('channel-rate').value)}});pendingJob=job.job_id;selectedComparison='';selectedSimulation='';simulationTick=null;following=true;manualComparison=false;resetOrbit();selectJob(job.job_id);notice('Confronto avviato · obiettivo: 3 migrazioni verificate per modalità');renderExperiment();await refresh();}catch(error){$('launch-error').textContent='Avvio non riuscito: '+error.message;$('launch-error').hidden=false;if(state)renderState();}});
$('stop').addEventListener('click',async()=>{const identifier=state?.lock?.job_id;if(!identifier)return;stoppingJob=identifier;$('stop').disabled=true;try{await api('/jobs/'+identifier+'/stop',{});notice('Interruzione richiesta · attendo la messa in sicurezza del laboratorio.');}catch(error){stoppingJob='';notice(error.message,true);renderState();}});
$('recover').addEventListener('click',async()=>{$('recover').disabled=true;try{const job=await api('/jobs',{operation:'recover',parameters:{}});selectJob(job.job_id);await refresh();}catch(error){notice('Ripristino non riuscito: '+error.message,true);}finally{$('recover').disabled=false;}});
$('comparison-select').addEventListener('change',()=>{manualComparison=true;pendingJob='';selectedComparison=$('comparison-select').value;following=true;selectSimulation('',true);selectJob(currentPair()?.job_id||'');refresh();});
$('simulation-select').addEventListener('change',()=>{selectSimulation($('simulation-select').value);simulationTick=null;topology();});
let replayDelay;$('simulation-replay').addEventListener('input',()=>{simulationTick=Number($('simulation-replay').value);following=false;clearTimeout(replayDelay);replayDelay=setTimeout(topology,100);});
$('follow-current').addEventListener('click',()=>{following=true;simulationTick=null;refresh();});

document.addEventListener('DOMContentLoaded',async()=>{try{token=(await api('/session')).token;await topology();await refresh();setInterval(refresh,5000);setInterval(()=>{updateLiveFreshness();renderExperiment();},1000);}catch(error){notice('Sessione locale non disponibile: '+error.message,true);}});

function renderExperiment(){
 if(!state)return;
 const pair=(state.lock?comparisons.find(row=>row.job_id===state.lock.job_id):null)||currentPair();let job=jobs.find(row=>row.job_id===(state.lock?.job_id||pair?.job_id));
 if(pendingJob&&pair?.job_id!==pendingJob){$('experiment-phase').textContent='Avvio del confronto';$('experiment-detail').textContent='Preparazione dello stato dell’esperimento. Il clock orbitale resta fermo.';$('experiment-error').hidden=true;return;}
 if(state.lock&&state.worker_alive===false&&['queued','running'].includes(job?.status))job={...job,status:'recovery_required',worker_lost:true};
 const view=experimentView(pair,job,Date.now(),phaseLabels);
 $('experiment-title').textContent=state.lock?'Esperimento attivo'+(pair?.comparison_id?' · '+pair.comparison_id:''):pair?'Ultimo confronto · '+new Date(pair.created_utc).toLocaleString('it-IT'):'Il tuo esperimento';
 const setText=(id,value)=>{if($(id).textContent!==value)$(id).textContent=value;};
 setText('experiment-phase',view.title);setText('experiment-detail',view.detail+(view.workerActive&&!view.terminal?' Il processo risponde separatamente dall’avanzamento; ogni passaggio si interrompe al proprio limite.':''));
 $('experiment-stop').disabled=$('stop').disabled;
 setText('console-phase',view.title);
 $('control-title').textContent=state.lock?'Configurazione di questo esperimento':'Avvia il confronto';
 $('experiment-elapsed').textContent=pair?.finished_utc?seconds((Date.parse(pair.finished_utc)-Date.parse(pair.created_utc))/1000):seconds(view.elapsed);
 $('experiment-freshness').textContent=view.age===null?'Informazione non disponibile':view.terminal?'Esecuzione terminata':view.age>15?`Nessun progresso da ${view.age} s`:`${view.age} s fa`;
 $('experiment-deadline').textContent=view.deadline?`${new Date(view.deadline).toLocaleTimeString('it-IT')} · ${Math.max(0,Math.ceil((Date.parse(view.deadline)-Date.now())/1000))} s residui`:'Nessuna sottofase temporizzata attiva';
 $('experiment-worker').textContent=view.terminal?'Terminato':view.workerActive?(view.heartbeatAge===null?'Segnale non ancora disponibile':view.heartbeatAge>10?'Nessun segnale recente':`Attivo · segnale ${view.heartbeatAge} s fa`):'Non avviato';
 const steps=[['preparation','Verifica'],['calibration','Calibrazione'],['planning','Piano condiviso'],['hot','Hot'],['resetting','Ripristino'],['cold','Cold'],['finished','Risultati']];
 const list=$('experiment-steps');if(list.dataset.phase!==view.phase){list.dataset.phase=view.phase;list.replaceChildren();for(const [key,label]of steps){const li=document.createElement('li');li.textContent=label;if(key===view.phase){li.setAttribute('aria-current','step');}list.append(li);}}
 $('experiment-error').hidden=!view.failed&&!view.recovery;
 setText('experiment-error-title',view.errorTitle);
 setText('experiment-error-detail',view.recoveryFailed?`Nessun nuovo confronto può iniziare finché il recupero non supera la verifica. ${view.error?.technical_detail||'Consultare il log del job di recupero per la causa.'}`:view.admissionRejected?'Fase raggiunta: piano condiviso. Hot e Cold non sono state avviate e non esistono misure confrontabili. Configurazione e soglie sono rimaste quelle richieste; i motivi tecnici sono nelle evidenze.':view.error?.code==='departure_search_incomplete'?'Nessuna partenza verificata entro il budget. Il clock è rimasto fermo; consulta le evidenze della ricerca.':view.error?`${view.error.label||view.error.message||'Diagnostica'}${view.error.unhealthy_services?.length?' · '+view.error.unhealthy_services.join(', '):''}. Tempo: ${seconds(view.error.elapsed_s)}; limite: ${seconds(view.error.limit_s)}. ${view.error.code==='startup_timeout'?'Verificare lo stato e i log Docker del controller indicato prima di un nuovo tentativo.':'Consultare le evidenze dell’operazione indicata prima di un nuovo tentativo.'}`:pair?.reason===view.errorTitle?'Consulta report ed evidenze per i dettagli dell’operazione.':pair?.reason||'Informazione non disponibile.');
 setText('experiment-recovery',view.recovery?'Ripristino necessario: il laboratorio resta bloccato. Usa Ripristina laboratorio.':view.admissionRejected?'Nessuna sessione Hot/Cold da recuperare. Il confronto si è fermato prima dell’avvio del clock orbitale.':view.failed?(pair?.cleanup_verified?'Messa in sicurezza verificata. Risolvi la causa prima di un nuovo tentativo.':'Verifica del recupero: informazione non disponibile per questo confronto. Consultare le evidenze; le misure mancanti restano assenti.'):'');
 $('map-explanation').textContent=selectedSimulation?'Orbite e risorse modellate; controller e forwarding verificati dalle evidenze live.':'Anteprima iniziale — clock orbitale fermo durante la preparazione.';
 if(view.failed||view.recovery)notice(view.title+' · '+view.errorTitle,true);
}

function controllerRequirement(name,job){
 if(state.components[name]?.reachable)return 'API pronta';
 const p=job?.progress,op=p?.operation;
 if(p?.operation_status==='running'&&((name==='sat_a'&&op==='start_source')||(name==='sat_b'&&op==='start_target')))return 'Avvio in corso';
 const target=p?.active_slot==='sat-a'?'sat_b':p?.active_slot==='sat-b'?'sat_a':null;
 if(p?.subphase==='target_start'&&name===target)return 'Avvio destinazione in corso · API non ancora pronta';
 if(!state.lock&&state.components.p4_proxy?.data?.active===null)return 'API non disponibile · autorità revocata';
 if(name==='sat_b'&&['baseline','stop_target'].includes(p?.subphase))return 'Arresto previsto in questa fase';
 return state.lock?'API non pronta · verifica in corso':'API non disponibile · verificare prima dell’esecuzione';
}

$('experiment-stop').addEventListener('click',()=>$('stop').click());
