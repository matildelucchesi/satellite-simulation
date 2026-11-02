'use strict';
const $=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg';
document.querySelector('.local').textContent=location.host;
const outcomeLabels={success:'Riuscita',running:'In corso',failed:'Fallita',experimental_failure:'Fallita',rejected:'Non ammissibile',interrupted:'Interrotta',recovery_required:'Ripristino necessario',invalid_lab:'Misure non valide',invalid_baseline:'Servizio iniziale non valido',worker_lost:'Esecuzione interrotta'};
const phaseLabels={comparison_run:'Prova della coppia FSO',service_verified:'Servizio Mininet verificato',planning:'Pianificazione',admission_rejected:'Sequenza non ammissibile',plan_admitted:'Piano ammesso',baseline_valid:'Baseline valida',baseline_check:'Verifica baseline',replanning:'Ripianificazione',simulation_finished:'Sessione terminata',trigger:'Trigger',alignment:'Allineamento FSO',quiescence:'Quiescenza',snapshot_initial:'Snapshot iniziale',source_stop:'Arresto sorgente',source_stopped:'Sorgente arrestata',transfer:'Trasferimento',transfer_verified:'Checksum verificato',target_start:'Importazione immagini e avvio destinazione',restore_initial:'Restore iniziale',freeze:'Freeze sorgente',source_frozen:'Sorgente congelata',restore_delta:'Applicazione delta',verify:'Verifica API',ack:'ACK',cutover:'Cutover hardware',completed:'Migrazione completata',attempt_failed:'Tentativo fallito',rollback:'Recupero sorgente',failed:'Migrazione fallita',prepare:'Preparazione fixture',run_finished:'Prova terminata',job_finished:'Job terminato',calibration:'Calibrazione',transport_capacity:'Verifica capacità TCP',workflow_stage:'Fase del workflow'};
const comparisonLabels={planning:'Ricerca di una sequenza comune',preparation:'Verifica iniziale Hot/Cold',calibration:'Calibrazione separata',departure_search:'Ricerca della partenza',hot:'Esecuzione Hot',resetting:'Ripristino dello scenario iniziale',cold:'Esecuzione Cold',finished:'Confronto terminato'};
let timelineRenderTimer=null,calibrationJobId='';
let token='',state=null,jobs=[],comparisons=[],simulations=[],artifacts=[],commonBase=null;
let launchedComparisonJob='';
try{launchedComparisonJob=sessionStorage.getItem('teraflow-launched-comparison')||'';}catch{}
function hasLaunchedExperiment(){return !stoppingJob&&!jobs.some(job=>job.job_id===(launchedComparisonJob||selectedJob)&&job.cancellation_requested)&&(!!launchedComparisonJob||!!pendingJob||jobs.some(job=>job.job_id===state?.lock?.job_id&&job.operation==='compare_continuous'&&!job.cancellation_requested));}
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
const isCancelledPair=pair=>!!pair&&(pair.outcome==='interrupted'||pair.job_id===stoppingJob||jobs.some(job=>job.job_id===pair.job_id&&job.cancellation_requested));
const operationName=op=>({compare_continuous:'Confronto continuo Hot/Cold',recover:'Ripristino laboratorio'}[op]||'Esecuzione del laboratorio');
function selectSimulation(identifier,follow=false){if(selectedSimulation!==identifier){resetOrbit();simulationTick=null;}selectedSimulation=identifier;following=follow;$('simulation-select').value=identifier;$('follow-current').hidden=following;$('live-progress').hidden=!identifier;}
function renderState(){
 const busy=jobs.find(row=>row.job_id===state.lock?.job_id),locked=!!state.lock;
 const configuration=busy?.operation==='recover'?jobs.find(row=>row.job_id===busy.previous_job_id)?.parameters:busy?.operation==='compare_continuous'?busy.parameters:null;
 const reachable=Object.values(state.components).filter(row=>row.reachable).length;
 $('console-health').textContent=locked?'Verifica requisiti per la fase corrente':'Laboratorio in attesa di verifica';$('console-health').dataset.offline=String(!state.components.mininet?.reachable||!state.components.p4_proxy?.reachable);
 $('console-operation').textContent=locked?operationName(busy?.operation):'Nessun confronto in corso';
 $('start').disabled=locked||!!pendingJob||state.simulation_readiness?.ready!==true||commonBase?.ready!==true;$('stop').disabled=state.worker_alive===false||!busy||!['queued','running'].includes(busy.status)||stoppingJob===busy.job_id;
 $('channel-rate').disabled=locked;if(locked&&configuration?.rate_bps)$('channel-rate').value=String(configuration.rate_bps);
 const resolved=currentPair()?.resolved_configuration;
 initialConfigurationRequest=resolved?{initial_satellite_id:resolved.initial_satellite_id,start_orbital_s:resolved.start_orbital_s}:null;
 $('recover').hidden=!locked||!busy||(!['recovery_required','failed','interrupted'].includes(busy.status)&&state.worker_alive!==false);
 renderMigrationData(state.migration_data);renderCalibrationSetup();renderCommonBase();
 const components=$('components');components.replaceChildren();
 for(const [name,value]of [['Mininet / BMv2',state.components.mininet?.reachable?'Raggiungibile':'Non disponibile'],['Controller A',controllerRequirement('sat_a',busy)],['Autorità P4',state.components.p4_proxy?.reachable?state.components.p4_proxy.data.active||'Nessuna · fenced':'Non disponibile']]){const li=document.createElement('li'),title=document.createElement('span'),status=document.createElement('span');title.textContent=name;status.textContent=value;status.className='component-value';li.append(title,status);components.append(li);}
 if(locked||currentPair()?.phase!=='finished')notice(locked?`Laboratorio occupato · ${operationName(busy?.operation)}${busy?.status==='recovery_required'?' · ripristino necessario':''}`:'Laboratorio libero. Avvia un confronto continuo Hot/Cold.');
}
function renderSelectors(){
 const select=$('comparison-select');select.replaceChildren();option(select,'','Nessun confronto');
 for(const row of comparisons.filter(row=>!isCancelledPair(row)))option(select,row.comparison_id,`${new Date(row.created_utc).toLocaleString('it-IT')} · ${outcomeLabels[row.outcome]||row.outcome}`);
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
 if(isCancelledPair(pair)){$('pair-status').textContent='Confronto interrotto: nessun risultato di confronto.';$('plan-provenance').textContent='';return;}
 $('comparison-phase').textContent=`${comparisonLabels[pair.phase]||pair.phase}${pair.phase==='finished'?' · '+(outcomeLabels[pair.outcome]||pair.outcome):''}`;
 $('pair-status').textContent=`${pair.complete?'Confronto completato':pair.phase==='finished'?'Confronto incompleto':'Confronto in corso'} · ${pair.parameters.migration_count?'Obiettivo: '+pair.parameters.migration_count+' migrazioni per modalità':number(pair.parameters.duration_s,0)+' s per modalità'} · ${pair.events.length} eventi pianificati · ${pair.events.filter(row=>row.comparable).length} confrontabili`+(pair.reason?' · '+(pair.error?.code==='plan_not_admissible'?'Sequenza non ammissibile: dettagli nelle evidenze':pair.error?.code==='departure_search_incomplete'?'Ricerca incompleta: dettagli nelle evidenze':pair.success?'':'Confronto non completato: consultare causa ed evidenze'):'');
 const labels=['Modalità','Esito','Migrazioni tentate','Migrazioni riuscite','Downtime controller cumulativo','Tempo simulato trascorso'];
 for(const mode of ['hot','cold']){const result=pair.session_results[mode],total=pair.totals[mode];tableRow(body,[sessionButton(mode,pair,mode.toUpperCase()),result?outcomeLabels[result.outcome]||result.outcome:pair.current_method===mode?'In corso':pair.phase==='finished'?'Non eseguita':'In attesa',number(total?.attempted_migrations,0),total?`${total.completed_migrations}/${pair.events.length}`:'—',seconds(total?.controller_downtime_s),seconds(total?.real_elapsed_s)],labels);}
 if(pair.complete)tableRow(body,['Cold − Hot','Differenza','—','—',seconds(pair.totals.cold_minus_hot?.controller_downtime_s),seconds(pair.totals.cold_minus_hot?.real_elapsed_s)],labels);
 const eventLabels=['Evento / satelliti','Trigger orbitale','Downtime Hot','Downtime Cold','Cold − Hot','Esito'];
 for(const row of pair.events){tableRow(eventRows,[`${row.sat_a} → ${row.sat_b}`,seconds(row.trigger_s),row.hot?sessionButton('hot',pair,seconds(row.hot.controller_downtime_s),row.trigger_s):'—',row.cold?sessionButton('cold',pair,seconds(row.cold.controller_downtime_s),row.trigger_s):'—',seconds(row.cold_minus_hot?.controller_downtime_s),row.comparable?'Confrontabile':row.hot?.success===false||row.cold?.success===false?'Evento fallito':row.hot&&row.cold?'Non confrontabile · '+(row.exclusion_reason||'evidenze incomplete'):'In attesa'],eventLabels);}
 $('plan-provenance').textContent=pair.shared_plan_sha256?`Velocità ${number(pair.parameters.rate_bps/1e6,0)} Mbit/s · NORAD ${(pair.resolved_configuration?.initial_satellite_id??pair.parameters.initial_satellite_id)} · inizio ${seconds((pair.resolved_configuration?.start_orbital_s??pair.parameters.start_orbital_s))} · Piano condiviso SHA-256 ${pair.shared_plan_sha256}`:'Il piano comune verrà salvato prima delle due esecuzioni.';
}
function renderDownloads(){const list=$('downloads');list.replaceChildren();const pair=currentPair();if(!pair||isCancelledPair(pair))return;const prefixes=[`results/continuous-comparisons/${pair.comparison_id}/`,...Object.values(pair.sessions).map(id=>`results/simulations/${id}/`)];for(const row of artifacts.filter(item=>prefixes.some(prefix=>item.label.startsWith(prefix))&&(/\.(html|csv)$/.test(item.label)||/(metadata|plan|report|selection)\.json$/.test(item.label)))){const li=document.createElement('li'),a=document.createElement('a');a.href=row.download_url;const filename=row.label.split('/').pop();const mode=row.label.includes('/simulations/')?' · esecuzione':'';a.textContent=({"report.html":'Report leggibile',"metadata.json":'Risultati e diagnostica JSON',"events.csv":'Eventi CSV',"selection.json":'Ricerca e selezione della partenza JSON',"plan.json":'Piano condiviso JSON',"report.json":'Misure JSON'}[filename]||filename)+mode+(pair.phase==='finished'?' · definitivo':' · parziale');a.title=row.label;li.append(a);list.append(li);}}
function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(refresh,250);}
async function refresh(){
 if(loading)return;loading=true;
 try{
  [state,{jobs},{comparisons},{simulations},{artifacts},commonBase]=await Promise.all([api('/state'),api('/jobs'),api('/continuous-comparisons'),api('/simulations'),api('/artifacts'),api('/common-base')]);
  if(pendingJob){const next=comparisons.find(row=>row.job_id===pendingJob);if(next){selectedComparison=next.comparison_id;pendingJob='';}}
  else if(!selectedComparison&&!manualComparison&&comparisons.length)selectedComparison=comparisons[0].comparison_id;
  if(!manualComparison&&!pendingJob){const active=comparisons.find(row=>row.job_id===state.lock?.job_id);if(active&&active.comparison_id!==selectedComparison){selectedComparison=active.comparison_id;selectSimulation('',true);}}
  const pair=currentPair();
  const separate=jobs.find(job=>job.job_id===state.lock?.job_id&&['functional','calibrate','prepare_base'].includes(job.operation));if(separate)calibrationJobId=separate.job_id;
  if(separate&&selectedJob!==separate.job_id)selectJob(separate.job_id);
  if(pair&&!selectedSimulation&&!initialViewRequested&&!manualComparison&&state.lock?.job_id===pair.job_id&&['hot','cold'].includes(pair.current_method))following=true;
  if(pair){if(following){const next=pair.sessions[pair.current_method]||pair.sessions.cold||pair.sessions.hot||'';selectSimulation(next,true);}const recoveryJob=jobs.find(row=>row.job_id===state.lock?.job_id&&row.operation==='recover');const targetJob=recoveryJob?.job_id||separate?.job_id||(!state.lock?calibrationJobId:'')||pair.job_id;if(targetJob&&targetJob!==selectedJob)selectJob(targetJob);}
  renderState();renderSelectors();renderComparison();renderExperiment();renderDownloads();
  await topology();
  syncExperimentPage();
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
let latestRestoreGroup=null;
function renderTimeline(){const list=$('timeline'),creation=scenarioCreationProgress(jobs.find(row=>row.job_id===selectedJob),[...events.values()]),timelineGroups=groupTimelineEvents([...events.values()].filter(row=>!creation.timelineStartId||row.id>=creation.timelineStartId)),bottom=list.scrollTop+list.clientHeight>=list.scrollHeight-30;list.replaceChildren();latestRestoreGroup=timelineGroups.filter(event=>event.phase==='restore_group').at(-1)||null;renderScenarioLoading(latestRestoreGroup);for(const event of timelineGroups.slice(-400)){if(event.phase==='restore_group'){list.append(renderRestoreGroup(event));continue;}const li=document.createElement('li'),time=document.createElement('time'),label=document.createElement('span');time.dateTime=event.timestamp_utc;time.textContent=event.orbital_s==null?new Date(event.timestamp_utc).toLocaleTimeString('it-IT'):seconds(event.orbital_s);label.textContent=event.phase==='scenario_creation'?event.label:event.phase==='infrastructure_wait'?`${event.label} · ${event.detail}`:event.phase==='source_startup'?`${event.label} · ${{running:'In corso',completed:'Completata',failed:'Fallita'}[event.operation_status]||event.operation_status}`:event.phase==='departure_search'?`Ricerca della partenza · ${event.examined_candidates} candidati · ${number(event.elapsed_s,0)} s`:event.phase==='continuous_comparison'?comparisonLabels[event.comparison_phase]:event.phase==='comparison_session'?`Avvio ${event.method.toUpperCase()}`:(event.phase==='preparation_operation'?`${event.label} · ${{running:'In corso',completed:'Completata',failed:'Fallita'}[event.operation_status]||event.operation_status}`:event.phase==='calibration'?`Calibrazione ${(event.method||'').toUpperCase()} · prova ${event.replica}/${event.replicas_per_mode||3}`:phaseLabels[event.phase])||({comparison_finished:'Confronto terminato',simulation_finished:'Esecuzione terminata'}[event.phase])||event.phase;li.append(time,label);if(event.reason){const reason=document.createElement('span');reason.className='reason';reason.textContent=event.reason;li.append(reason);}list.append(li);}if(bottom)list.scrollTop=list.scrollHeight;renderCalibrationEvents();renderScenarioCreationProgress(jobs.find(row=>row.job_id===selectedJob));updateScenarioLoadingVisibility();}
function selectJob(identifier){selectedJob=identifier;events.clear();renderTimeline();if(stream)stream.close();if(!identifier)return;const source=new EventSource('/api/v1/jobs/'+identifier+'/events');stream=source;source.onopen=()=>{if(selectedJob!==identifier)return;orbitStreamDisconnected=false;$('stream-status').textContent='Aggiornamenti connessi';topology();};source.onmessage=message=>{if(selectedJob!==identifier)return;const event=JSON.parse(message.data);if(event.phase!=='session_tick'){events.set(event.id,event);if(timelineRenderTimer===null)timelineRenderTimer=setTimeout(()=>{timelineRenderTimer=null;renderTimeline();},100);}if(event.phase==='session_tick'&&event.simulation_id===selectedSimulation&&simulationTick===null){clearTimeout(orbitalUpdateTimer);orbitalUpdateTimer=setTimeout(topology,150);}if(['continuous_comparison','comparison_session','comparison_finished','simulation_finished','scenario_creation','preparation_operation','infrastructure_wait','source_startup','calibration','departure_search'].includes(event.phase))scheduleRefresh();};source.onerror=()=>{if(selectedJob!==identifier)return;orbitStreamDisconnected=true;$('stream-status').textContent='Connessione interrotta · riconnessione automatica';if(orbitData?.presentation?.mode==='live')stopOrbit('Stream disconnesso · riconnessione in corso');};source.addEventListener('end',()=>{source.close();if(selectedJob!==identifier)return;orbitStreamDisconnected=false;$('stream-status').textContent='Timeline completa';scheduleRefresh();});}
$('job-form').addEventListener('submit',async event=>{event.preventDefault();if(!commonBase?.ready){$('launch-error').hidden=false;$('launch-error').textContent='Prepara una base comune valida prima di avviare il confronto.';return;}$('start').disabled=true;$('launch-error').hidden=true;try{const job=await api('/jobs',{operation:'compare_continuous',parameters:{migration_count:3,rate_bps:Number($('channel-rate').value),base_id:commonBase.base_id}});pendingJob=job.job_id;calibrationJobId='';launchedComparisonJob=job.job_id;try{sessionStorage.setItem('teraflow-launched-comparison',job.job_id);}catch{}selectedComparison='';selectedSimulation='';simulationTick=null;following=true;manualComparison=false;resetOrbit();showExperimentPage('preparation',true);selectJob(job.job_id);notice('Confronto avviato · obiettivo: 3 migrazioni verificate per modalità');renderExperiment();await refresh();}catch(error){$('launch-error').textContent='Avvio non riuscito: '+error.message;$('launch-error').hidden=false;if(state)renderState();}});
async function requestExperimentStop(){const identifier=state?.lock?.job_id;if(!identifier)return;stoppingJob=identifier;$('stop').disabled=true;syncExperimentPage();showExperimentPage('preparation',true);try{await api('/jobs/'+identifier+'/stop',{});notice('Interruzione richiesta · attendo la messa in sicurezza del laboratorio.');scheduleRefresh();}catch(error){stoppingJob='';notice(error.message,true);renderState();syncExperimentPage();}}
$('recover').addEventListener('click',async()=>{$('recover').disabled=true;try{const job=await api('/jobs',{operation:'recover',parameters:{}});selectJob(job.job_id);await refresh();}catch(error){notice('Ripristino non riuscito: '+error.message,true);}finally{$('recover').disabled=false;}});
$('comparison-select').addEventListener('change',()=>{manualComparison=true;pendingJob='';selectedComparison=$('comparison-select').value;following=true;selectSimulation('',true);selectJob(currentPair()?.job_id||'');refresh();});
$('simulation-select').addEventListener('change',()=>{selectSimulation($('simulation-select').value);simulationTick=null;topology();});
let replayDelay;$('simulation-replay').addEventListener('input',()=>{simulationTick=Number($('simulation-replay').value);following=false;clearTimeout(replayDelay);replayDelay=setTimeout(topology,100);});
$('follow-current').addEventListener('click',()=>{following=true;simulationTick=null;refresh();});

document.addEventListener('DOMContentLoaded',async()=>{try{token=(await api('/session')).token;await topology();await refresh();setInterval(refresh,5000);setInterval(()=>{updateLiveFreshness();renderExperiment();},1000);}catch(error){notice('Sessione locale non disponibile: '+error.message,true);}});

function renderExperiment(){
 if(!state)return;
 let pair=(state.lock?comparisons.find(row=>row.job_id===state.lock.job_id):null)||currentPair();let job=jobs.find(row=>row.job_id===(state.lock?.job_id||pair?.job_id));
 if(['functional','calibrate','prepare_base'].includes(job?.operation))pair=null;
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
 setText('experiment-error-detail',view.recoveryFailed?`Nessun nuovo confronto può iniziare finché il recupero non supera la verifica. ${view.error?.technical_detail||'Consultare il log del job di recupero per la causa.'}`:view.admissionRejected?'Fase raggiunta: piano condiviso. Hot e Cold non sono state avviate e non esistono misure confrontabili. Configurazione e soglie sono rimaste quelle richieste; i motivi tecnici sono nelle evidenze.':view.error?.code==='departure_search_incomplete'?'Nessuna partenza verificata entro il budget. Il clock è rimasto fermo; consulta le evidenze della ricerca.':view.error?`${view.error.startup_label||view.error.label||view.error.message||'Diagnostica'}${view.error.unhealthy_services?.length?' · '+view.error.unhealthy_services.join(', '):''}. Tempo: ${seconds(view.error.elapsed_s)}; limite: ${seconds(view.error.limit_s)}. ${view.error.code==='startup_timeout'?'Verificare lo stato e i log Docker del controller indicato prima di un nuovo tentativo.':'Consultare le evidenze dell’operazione indicata prima di un nuovo tentativo.'}`:pair?.reason===view.errorTitle?'Consulta report ed evidenze per i dettagli dell’operazione.':pair?.reason||'Informazione non disponibile.');
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
 if(name==='sat_b'&&['infrastructure','stop_target','start_source','clean_source','restore_scenario','restore_authority','baseline'].includes(p?.subphase))return 'Arrestato · avvio durante la migrazione';
 return state.lock?'API non pronta · verifica in corso':'API non disponibile · verificare prima dell’esecuzione';
}

function confirmExperimentStop(){if($('stop').disabled)return;$('stop-confirmation').showModal();}
$('stop').addEventListener('click',confirmExperimentStop);
$('experiment-stop').addEventListener('click',confirmExperimentStop);
$('stop-cancel').addEventListener('click',()=>$('stop-confirmation').close());
$('stop-confirm').addEventListener('click',()=>{$('stop-confirmation').close();if(!$('stop').disabled)void requestExperimentStop();});

// The worker owns execution; navigation never launches a duplicate job.
const pageMain=document.querySelector('main');
const configurationPage=document.createElement('section');configurationPage.id='configuration-page';
const simulationPage=document.createElement('section');simulationPage.id='simulation-page';
const resultsPage=document.createElement('section');resultsPage.id='results-page';
pageMain.append(configurationPage,simulationPage,resultsPage);
configurationPage.append(document.querySelector('.control'));
const configurationInformation=document.createElement('aside');configurationInformation.className='configuration-information';configurationInformation.setAttribute('aria-label','Preparazione e laboratorio');
configurationInformation.append(...configurationPage.querySelectorAll('.configuration-info'));configurationPage.append(configurationInformation);
configurationPage.querySelector('.control').prepend(configurationInformation.querySelector('.common-base-info'));
configurationInformation.append(document.querySelector('.migration-data'));
const spaceStars=document.createElement('div');spaceStars.className='space-stars';spaceStars.setAttribute('aria-hidden','true');
for(let i=0;i<400;i++){const star=document.createElement('i');star.style.left=(Math.random()*100)+'%';star.style.top=(Math.random()*100)+'%';star.style.setProperty('--star-size',i%13===0?'2.5px':i%5===0?'1.5px':'1px');star.style.setProperty('--star-opacity',String([.16,.28,.45,.65,.9,1][i%6]));spaceStars.append(star);}document.body.prepend(spaceStars);
simulationPage.append(document.querySelector('.workbench'),$('live-progress'));
resultsPage.append(...document.querySelectorAll('main > .section'));
const diagnostics=document.createElement('details');diagnostics.className='experiment-diagnostics';
const diagnosticsSummary=document.createElement('summary');diagnosticsSummary.textContent='Dettagli del laboratorio e timeline';diagnostics.append(diagnosticsSummary);
const diagnosticsContent=document.createElement('div');diagnosticsContent.className='diagnostics-content';
diagnosticsContent.append(document.querySelector('.experiment-times'),document.querySelector('.timeline'));diagnostics.append(diagnosticsContent);
document.querySelector('.experiment-console').append(diagnostics,$('recover'));
$('experiment-error').querySelector('a').href='#results';
const experimentConsole=document.querySelector('.experiment-console');
const calibrationLayout=document.createElement('div');calibrationLayout.className='calibration-layout';
const calibrationMain=document.createElement('div');calibrationMain.className='calibration-main';
calibrationMain.append(...$('preparation-page').children);calibrationLayout.append(calibrationMain);$('preparation-page').prepend(calibrationLayout);
let previousAutomaticPage='',automaticPair='';
function showExperimentPage(page,replace=false){
 const valid=['configuration','preparation','simulation','results'];if(!valid.includes(page))page='configuration';
 page=experimentRoute(page,hasLaunchedExperiment());
 if(page==='simulation'&&orbitData?.presentation?.initial_controller_ready!==true)page=currentPair()?.phase==='finished'?'results':'preparation';
 if(document.body.dataset.stopping==='true')page='preparation';
 const changed=document.body.dataset.page!==page;
 document.body.dataset.page=page;
 if(page==='preparation')diagnostics.open=true;
 const heading=document.querySelector('h1');heading.textContent={configuration:'Configura il confronto',preparation:'Preparazione della simulazione',simulation:'Simulazione Hot / Cold',results:'Risultati Hot / Cold'}[page];
 if(page==='preparation'&&document.body.dataset.stopping==='true')heading.textContent='Interruzione in corso';
 if(changed){heading.tabIndex=-1;heading.focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});}
 if(page==='simulation')simulationPage.insertBefore(experimentConsole,$('live-progress'));
 else if(page==='results')resultsPage.prepend(experimentConsole);
 else if(page==='preparation')$('preparation-page').append(experimentConsole);
 else configurationPage.prepend(experimentConsole);
 for(const [key,element]of Object.entries({configuration:configurationPage,preparation:$('preparation-page'),simulation:simulationPage,results:resultsPage}))element.hidden=key!==page;
 document.querySelectorAll('[data-route]').forEach(link=>{const locked=link.dataset.route!=='configuration'&&!hasLaunchedExperiment();link.setAttribute('aria-disabled',String(locked));link.tabIndex=locked?-1:0;link.title=locked?'Disponibile dopo Avvia':'';if(link.dataset.route===page)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
 if(location.hash!=='#'+page)history[replace?'replaceState':'pushState'](null,'','#'+page);
}
function syncExperimentPage(){
 if(!state)return;
 let pair=currentPair();let job=jobs.find(row=>row.job_id===(state?.lock?.job_id||calibrationJobId||pair?.job_id||stoppingJob));
 if(['functional','calibrate','prepare_base'].includes(job?.operation))pair=null;
 if(stoppingJob&&job?.job_id===stoppingJob)job={...job,cancellation_requested:true};
 if(state?.lock&&state.worker_alive===false&&['queued','running'].includes(job?.status))job={...job,status:'recovery_required'};
 if(pair?.comparison_id!==automaticPair){automaticPair=pair?.comparison_id;previousAutomaticPage='';}
 const page=experimentPage(pair,job,orbitData,pendingJob,previousAutomaticPage);
 if(page==='configuration'&&(job?.cancellation_requested||pair?.outcome==='interrupted')){stoppingJob='';pendingJob='';launchedComparisonJob='';following=false;try{sessionStorage.removeItem('teraflow-launched-comparison');}catch{}}
 document.querySelectorAll('[data-route]').forEach(link=>{const locked=link.dataset.route!=='configuration'&&!hasLaunchedExperiment();link.setAttribute('aria-disabled',String(locked));link.tabIndex=locked?-1:0;link.title=locked?'Disponibile dopo Avvia':'';});
 const preparation=preparationView(pair,job,orbitData);
 document.body.dataset.stopping=String(!!preparation.stopping);
 renderScenarioCreationProgress(job);
 updateScenarioLoadingVisibility();
 if(preparation.stopping&&document.body.dataset.page==='preparation')document.querySelector('h1').textContent='Interruzione in corso';
 $('preparation-title').textContent=preparation.title;
 $('preparation-label').textContent=preparation.title;
 $('preparation-explanation').textContent=preparation.detail;
 $('preparation-operation').textContent=$('experiment-phase').textContent+' · '+(job?.progress?.label||pair?.progress?.label||'Verifica dello stato in corso');
 $('preparation-assignment').hidden=preparation.satellite===undefined||preparation.satellite===null;
 $('preparation-assignment').textContent='Satellite iniziale: NORAD '+preparation.satellite;
 $('preparation-selection-status').textContent=preparation.chosen?'Completata':'In corso';
 $('preparation-api-status').textContent=preparation.ready?'Pronto':preparation.chosen?'In corso':'In attesa';
 for(const [id,complete,current]of [['preparation-selection',preparation.chosen,!preparation.chosen],['preparation-api',preparation.ready,preparation.chosen&&!preparation.ready]]){const step=$(id);step.dataset.state=complete?'complete':current?'current':'pending';if(current)step.setAttribute('aria-current','step');else step.removeAttribute('aria-current');}
 $('preparation-stop').disabled=$('stop').disabled;
 if(page!==previousAutomaticPage){
  const initial=!previousAutomaticPage&&!state?.lock&&!pendingJob&&!job?.cancellation_requested&&pair?.outcome!=='interrupted';
  previousAutomaticPage=page;
  showExperimentPage(experimentLandingPage(page,location.hash.slice(1),initial),true);
 }
}
document.querySelector('.page-navigation').addEventListener('click',event=>{if(event.target.closest('[aria-disabled=true]'))event.preventDefault();});
window.addEventListener('hashchange',()=>showExperimentPage(location.hash.slice(1),true));
$('preparation-stop').addEventListener('click',confirmExperimentStop);
showExperimentPage(location.hash.slice(1)||'configuration',true);

function renderMigrationData(data){
 const list=$('migration-data-sizes');list.replaceChildren();
 const size=value=>Number.isFinite(value)?number(value/(value>=1e9?1e9:1e3),2)+(value>=1e9?' GB':' kB'):'Non disponibile';
 const rows=[['Immagini del controller',data?.image_bytes],['Snapshot Cold',data?.cold_state_bytes],['Stato iniziale Hot',data?.hot_initial_state_bytes],['Delta finale Hot',data?.hot_final_delta_bytes]];
 for(const [label,value]of rows){const row=document.createElement('div'),term=document.createElement('dt'),amount=document.createElement('dd');term.textContent=label;amount.textContent=size(value);if(Number.isFinite(value))amount.title=number(value,0)+' byte';row.append(term,amount);list.append(row);}
}

$('experiment-info').addEventListener('click',()=>$('experiment-info-dialog').showModal());
$('experiment-info-dialog').addEventListener('click',event=>{if(event.target!==event.currentTarget)return;const box=event.currentTarget.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)event.currentTarget.close();});

function renderRestoreGroup(event){
 const row=document.createElement('li'),time=document.createElement('time'),label=document.createElement('span');
 time.dateTime=event.timestamp_utc;time.textContent=new Date(event.timestamp_utc).toLocaleTimeString('it-IT');
 label.textContent='Caricamento scenario iniziale · '+(event.status==='failed'?'Fallito':event.status==='completed'?'Completato':event.verification==='running'?'Verifica finale in corso':'In corso');
 row.append(time,label);return row;
}
function renderScenarioCreationProgress(job){
 const view=scenarioCreationProgress(job,[...events.values()]);
 document.body.dataset.calibrationStage=String(view.calibration);
 $('calibration-progress').hidden=!view.calibration||document.body.dataset.stopping==='true';
 const timeline=document.querySelector('.timeline');timeline.hidden=false;
 if(view.calibration){if(timeline.parentElement!==calibrationLayout)calibrationLayout.append(timeline);}else if(timeline.parentElement!==diagnosticsContent)diagnosticsContent.append(timeline);
 $('timeline-title').textContent=view.calibration?'Timeline della calibrazione':view.creation?'Timeline della preparazione della base':'Timeline del confronto';
 $('preparation-next').textContent=view.creation?'Al termine tornerai alla configurazione con lo scenario fermo. Il confronto partirà solo premendo Avvia.':'Il clock orbitale parte dopo la verifica del controller. La situazione orbitale si aprirà automaticamente.';
 if(!view.calibration)return;
 $('calibration-progress-summary').textContent=`${view.completed}/${view.total} prove completate`+(view.index?` · ${view.trials[view.index-1].label}`:' · Verifiche preliminari');
 $('calibration-progress-bar').max=view.total;
 $('calibration-progress-bar').value=view.completed;
 $('calibration-progress-bar').setAttribute('aria-valuetext',`${view.completed} prove completate su ${view.total}`);
 const list=$('calibration-trials');list.replaceChildren();
 for(const trial of view.trials){const row=document.createElement('li'),label=document.createElement('span'),status=document.createElement('strong');label.textContent=trial.label;status.textContent=trial.status;row.dataset.status=trial.status;if(trial.status==='In corso')row.setAttribute('aria-current','step');row.append(label,status);list.append(row);}
}
function updateScenarioLoadingVisibility(){
 const p=jobs.find(job=>job.job_id===(state?.lock?.job_id||currentPair()?.job_id))?.progress||currentPair()?.progress||{};
 $('scenario-loading').hidden=document.body.dataset.calibrationStage==='true'||!latestRestoreGroup||document.body.dataset.stopping==='true'||p.subphase!=='restore_scenario'||p.operation_status!=='running';
}
function renderScenarioLoading(event){
 updateScenarioLoadingVisibility();
 const left=$('scenario-loading-counts'),right=$('scenario-loading-api');
 const previousList=right.querySelector('.restore-requests');
 const previous={scroll:previousList?.scrollTop||0,id:right.dataset.group};
 left.replaceChildren();right.replaceChildren();if(!event)return;
 right.dataset.group=String(event.id);
 const content=document.createElement('div');content.className='restore-content';
 const heading=document.createElement('h3');heading.textContent='Avanzamento';
 const status=document.createElement('p');status.className='small muted';
 status.textContent=event.status==='failed'?'Fallito':event.status==='completed'?'Completato':event.verification==='running'?'Verifica finale in corso':event.verification==='completed'?'Scenario verificato':'In corso';
 const counts=document.createElement('dl');counts.className='restore-counts';
 for(const [key,label]of [['devices','Satelliti'],['links','Collegamenti'],['services','Servizi']]){
  const cell=document.createElement('div'),term=document.createElement('dt'),value=document.createElement('dd'),count=event.counts?.[key];term.textContent=label;value.textContent=count?`${count.completed}/${count.total}`:'—';cell.append(term,value);counts.append(cell);
 }
 const completed=Object.values(event.counts||{}).reduce((sum,count)=>sum+count.completed,0),total=Object.values(event.counts||{}).reduce((sum,count)=>sum+count.total,0);
 const progress=document.createElement('progress');progress.max=total||1;progress.value=completed;progress.setAttribute('aria-label','Elementi dello scenario caricati');progress.setAttribute('aria-valuetext',total?`${completed} su ${total}`:'Conteggi non ancora disponibili');
 const detail=document.createElement('div');detail.className='restore-api-details';
 const summary=document.createElement('p');summary.className='small muted';summary.textContent=`${event.requests.length} richieste registrate`;
 const requests=document.createElement('ul');requests.className='restore-requests';
 if(event.entity){const entity=document.createElement('p');entity.className='small muted';entity.textContent='Ultimo elemento: '+(event.entity.name||event.entity.id||event.entity.kind);detail.append(entity);}
 for(const request of event.requests){const item=document.createElement('li');const stamp=new Date(request.timestamp_utc).toLocaleTimeString('it-IT');item.textContent=`${stamp} · ${request.method||'API'} ${request.path||''} · ${{running:'In corso',completed:'Completata',failed:'Fallita'}[request.request_status]||'Stato non disponibile'}${request.status?' · HTTP '+request.status:''}${Number.isFinite(request.elapsed_s)?' · '+seconds(request.elapsed_s):''}${request.error?' · '+request.error:''}`;requests.append(item);}
 if(!event.requests.length){const empty=document.createElement('li');empty.textContent='Nessuna richiesta registrata finora.';requests.append(empty);}
 detail.prepend(summary);detail.append(requests);content.append(heading,status,counts,progress);right.append(detail);
 if(event.error){const error=document.createElement('p');error.className='error';error.textContent=event.error;content.append(error);}
 left.append(content);
 if(previous.id===String(event.id))requests.scrollTop=previous.scroll;
}

function renderCalibrationSetup(){
 const readiness=state?.simulation_readiness;
 $('calibration-readiness').textContent=readiness?.ready?'Misure valide: puoi preparare la simulazione.':readiness?.reason||'Verifica delle misure in corso.';
 const button=$('calibration-start');button.hidden=readiness?.ready===true;
 button.disabled=!!state?.lock||!readiness;
 button.textContent=readiness?.next_operation==='functional'?'Esegui verifica preliminare':'Esegui calibrazione';
 const job=jobs.find(row=>row.job_id===calibrationJobId&&['functional','calibrate'].includes(row.operation));
 const setup=jobs.find(row=>row.job_id===calibrationJobId);
 document.body.dataset.calibrating=String(!!setup&&['queued','running'].includes(setup.status));
 $('calibration-status').hidden=!job;
 if(job){const p=job.progress||{};const active=['queued','running'].includes(job.status);$('calibration-status').textContent=active?(job.operation==='functional'?'Verifica preliminare del laboratorio':'Calibrazione separata')+(p.method?' · '+p.method.toUpperCase():'')+(p.replica?' · prova '+p.replica+'/'+(p.replicas_per_mode||3):'')+' · '+(p.label||phaseLabels[p.subphase]||'Avvio in corso'):job.application_success?'Operazione completata. '+(readiness?.ready?'Misure pronte.':'Prosegui con la calibrazione separata.'):'Operazione non completata: '+(p.error?.message||job.error||'consulta la diagnostica e verifica il laboratorio.');}
 renderCalibrationEvents();
}
function renderCalibrationEvents(){
 const list=$('calibration-events');list.replaceChildren();list.hidden=!calibrationJobId||selectedJob!==calibrationJobId||jobs.find(job=>job.job_id===calibrationJobId)?.operation==='prepare_base';
 if(!list.hidden)for(const row of [...$('timeline').children].slice(-16))list.append(row.cloneNode(true));
}
$('calibration-start').addEventListener('click',async()=>{
 const button=$('calibration-start');button.disabled=true;
 try{const operation=state.simulation_readiness?.next_operation==='functional'?'functional':'calibrate';const job=await api('/jobs',{operation,parameters:{}});calibrationJobId=job.job_id;jobs=[job,...jobs.filter(row=>row.job_id!==job.job_id)];selectJob(job.job_id);previousAutomaticPage='';showExperimentPage('preparation',true);syncExperimentPage();await refresh();}
 catch(error){$('calibration-status').hidden=false;$('calibration-status').textContent='Avvio non riuscito: '+error.message;button.disabled=!!state?.lock;}
});

function renderCommonBase(){
 const job=jobs.find(row=>row.job_id===calibrationJobId&&row.operation==='prepare_base');
 const active=job&&['queued','running'].includes(job.status);
 $('common-base-start').disabled=!!state?.lock||!state;
 $('common-base-start').textContent='Crea scenario iniziale';
 $('common-base-status').textContent=active?'Creazione scenario · '+(job.progress?.phase==='calibration'?'Calibrazione '+(job.progress.method||'').toUpperCase()+' · prova '+(job.progress.replica||1)+'/'+(job.progress.replicas_per_mode||3)+' · ':'')+(job.progress?.label||phaseLabels[job.progress?.subphase]||'Avvio in corso'):job&&!job.application_success&&!['queued','running'].includes(job.status)?'Creazione non completata: '+(job.progress?.error?.message||job.error||'verifica la diagnostica del laboratorio.'):commonBase?.reason||'Base comune non disponibile.';
 if(commonBase?.ready){const selected=commonBase.selected;$('common-base-status').textContent+=' NORAD '+selected.initial_satellite_id+' · t = '+seconds(selected.start_orbital_s)+' · ombra fra '+seconds(selected.initial_time_to_shadow_s)+'.';}
}
$('common-base-start').addEventListener('click',async()=>{
 $('common-base-start').disabled=true;
 try{const job=await api('/jobs',{operation:'prepare_base',parameters:{}});calibrationJobId=job.job_id;jobs=[job,...jobs.filter(row=>row.job_id!==job.job_id)];selectJob(job.job_id);previousAutomaticPage='';showExperimentPage('preparation',true);syncExperimentPage();await refresh();}
 catch(error){$('common-base-status').textContent='Preparazione non riuscita: '+error.message;$('common-base-start').disabled=!!state?.lock||!state;}
});
