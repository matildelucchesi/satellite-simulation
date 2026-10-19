'use strict';
const $=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg';
document.querySelector('.local').textContent=location.host;
const outcomeLabels={success:'Riuscita',running:'In corso',failed:'Fallita',experimental_failure:'Fallita',rejected:'Non ammissibile',interrupted:'Interrotta',recovery_required:'Ripristino necessario',invalid_lab:'Misure non valide',invalid_baseline:'Servizio iniziale non valido',worker_lost:'Esecuzione interrotta'};
const phaseLabels={comparison_run:'Prova della coppia FSO',service_verified:'Servizio Mininet verificato',planning:'Pianificazione',admission_rejected:'Sequenza non ammissibile',plan_admitted:'Piano ammesso',baseline_valid:'Baseline valida',baseline_check:'Verifica baseline',replanning:'Ripianificazione',simulation_finished:'Sessione terminata',trigger:'Trigger',alignment:'Allineamento FSO',quiescence:'Quiescenza',snapshot_initial:'Snapshot iniziale',source_stop:'Arresto sorgente',source_stopped:'Sorgente arrestata',transfer:'Trasferimento',transfer_verified:'Checksum verificato',target_start:'Importazione immagini e avvio destinazione',restore_initial:'Restore iniziale',freeze:'Freeze sorgente',source_frozen:'Sorgente congelata',restore_delta:'Applicazione delta',verify:'Verifica API',ack:'ACK',cutover:'Cutover hardware',completed:'Migrazione completata',attempt_failed:'Tentativo fallito',rollback:'Recupero sorgente',failed:'Migrazione fallita',prepare:'Preparazione fixture',run_finished:'Prova terminata',job_finished:'Job terminato',calibration:'Calibrazione',transport_capacity:'Verifica capacità TCP',workflow_stage:'Fase del workflow'};
const comparisonLabels={planning:'Ricerca di una sequenza comune',preparation:'Verifica iniziale Hot/Cold',calibration:'Calibrazione automatica',hot:'Esecuzione Hot',resetting:'Ripristino dello scenario iniziale',cold:'Esecuzione Cold',finished:'Confronto terminato'};
let token='',state=null,jobs=[],comparisons=[],simulations=[],artifacts=[];
let selectedComparison='',selectedSimulation='',selectedJob='',simulationTick=null,stream=null;
const selectedRun='',replayTick=null;
let events=new Map(),loading=false,following=true,manualComparison=false,pendingJob='',stoppingJob='',refreshTimer,liveView=null;
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
 const reachable=Object.values(state.components).filter(row=>row.reachable).length;
 $('console-health').textContent=`Servizi disponibili ${reachable}/${Object.keys(state.components).length}`;$('console-health').dataset.offline=String(!reachable);
 $('console-operation').textContent=locked?operationName(busy?.operation):'Nessun confronto in corso';
 $('start').disabled=locked;$('stop').disabled=!busy||!['queued','running'].includes(busy.status)||stoppingJob===busy.job_id;
 $('recover').hidden=!locked||!busy||!['recovery_required','failed','interrupted'].includes(busy.status);
 const components=$('components');components.replaceChildren();
 for(const [name,value]of [['Mininet / BMv2',state.components.mininet?.reachable?'Raggiungibile':'Non disponibile'],['Controller A',state.components.sat_a?.reachable?'API disponibile':'Workload fermo o API non disponibile'],['Controller B',state.components.sat_b?.reachable?'API disponibile':'Workload fermo o API non disponibile'],['Autorità P4',state.components.p4_proxy?.reachable?state.components.p4_proxy.data.active||'Nessuna · fenced':'Non disponibile']]){const li=document.createElement('li'),title=document.createElement('span'),status=document.createElement('span');title.textContent=name;status.textContent=value;status.className='component-value';li.append(title,status);components.append(li);}
 notice(locked?`Laboratorio occupato · ${operationName(busy?.operation)}${busy?.status==='recovery_required'?' · ripristino necessario':''}`:'Laboratorio libero. Avvia un confronto continuo Hot/Cold.');
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
 if(!pair){$('pair-status').textContent='Nessun confronto disponibile. Scegli la durata e avvia Hot/Cold.';$('plan-provenance').textContent='';$('comparison-phase').textContent='Preparazione → Hot → Ripristino → Cold → Risultati';return;}
 $('comparison-phase').textContent=`${comparisonLabels[pair.phase]||pair.phase}${pair.phase==='finished'?' · '+(outcomeLabels[pair.outcome]||pair.outcome):''}`;
 $('pair-status').textContent=`${pair.complete?'Confronto completato':pair.phase==='finished'?'Confronto incompleto':'Confronto in corso'} · ${number(pair.parameters.duration_s,0)} s per modalità · ${pair.events.length} eventi condivisi`+(pair.reason?' · '+pair.reason:'');
 const labels=['Modalità','Esito','Migrazioni riuscite','Downtime controller cumulativo','Tempo simulato trascorso'];
 for(const mode of ['hot','cold']){const result=pair.session_results[mode],total=pair.totals[mode];tableRow(body,[sessionButton(mode,pair,mode.toUpperCase()),result?outcomeLabels[result.outcome]||result.outcome:pair.current_method===mode?'In corso':pair.phase==='finished'?'Non eseguita':'In attesa',total?`${total.completed_migrations}/${pair.events.length}`:'—',seconds(total?.controller_downtime_s),seconds(total?.real_elapsed_s)],labels);}
 if(pair.complete)tableRow(body,['Cold − Hot','Differenza','—',seconds(pair.totals.cold_minus_hot?.controller_downtime_s),seconds(pair.totals.cold_minus_hot?.real_elapsed_s)],labels);
 const eventLabels=['Evento / satelliti','Trigger orbitale','Downtime Hot','Downtime Cold','Cold − Hot','Esito'];
 for(const row of pair.events){tableRow(eventRows,[`${row.sat_a} → ${row.sat_b}`,seconds(row.trigger_s),row.hot?sessionButton('hot',pair,seconds(row.hot.controller_downtime_s),row.trigger_s):'—',row.cold?sessionButton('cold',pair,seconds(row.cold.controller_downtime_s),row.trigger_s):'—',seconds(row.cold_minus_hot?.controller_downtime_s),row.comparable?'Confrontabile':row.hot?.success===false||row.cold?.success===false?'Evento fallito':row.hot&&row.cold?'Non confrontabile':'In attesa'],eventLabels);}
 $('plan-provenance').textContent=pair.shared_plan_sha256?'Piano condiviso verificabile · SHA-256 '+pair.shared_plan_sha256:'Il piano comune verrà salvato prima delle due esecuzioni.';
}
function renderDownloads(){const list=$('downloads');list.replaceChildren();const pair=currentPair();if(!pair)return;const prefixes=[`results/continuous-comparisons/${pair.comparison_id}/`,...Object.values(pair.sessions).map(id=>`results/simulations/${id}/`)];for(const row of artifacts.filter(item=>prefixes.some(prefix=>item.label.startsWith(prefix))&&(/\.(html|csv)$/.test(item.label)||/(metadata|plan|report)\.json$/.test(item.label)))){const li=document.createElement('li'),a=document.createElement('a');a.href=row.download_url;a.textContent=row.label;a.title=row.label;li.append(a);list.append(li);}}
function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(refresh,250);}
async function refresh(){
 if(loading)return;loading=true;
 try{
  [state,{jobs},{comparisons},{simulations},{artifacts}]=await Promise.all([api('/state'),api('/jobs'),api('/continuous-comparisons'),api('/simulations'),api('/artifacts')]);
  if(pendingJob){const next=comparisons.find(row=>row.job_id===pendingJob);if(next){selectedComparison=next.comparison_id;pendingJob='';}}
  else if(!selectedComparison&&!manualComparison&&comparisons.length)selectedComparison=comparisons[0].comparison_id;
  const pair=currentPair();
  if(pair){if(following){const next=pair.sessions[pair.current_method]||pair.sessions.cold||pair.sessions.hot||'';selectSimulation(next,true);}const recoveryJob=jobs.find(row=>row.job_id===state.lock?.job_id&&row.operation==='recover');const targetJob=recoveryJob?.job_id||pair.job_id;if(targetJob&&targetJob!==selectedJob)selectJob(targetJob);}
  renderState();renderSelectors();renderComparison();renderDownloads();
  await topology();
 }catch(error){notice('Impossibile leggere il laboratorio: '+error.message,true);$('console-health').textContent='Laboratorio irraggiungibile';$('console-health').dataset.offline='true';stopOrbit('Connessione al laboratorio interrotta');}
 finally{loading=false;}
}
function renderLiveProgress(data){
 const metadata=simulations.find(row=>row.simulation_id===selectedSimulation),sample=data.simulation||{},view=data.presentation||{};
 const panel=$('live-progress');panel.hidden=!metadata;if(!metadata){liveView=null;return;}
 const replay=view.mode==='replay',active=!replay&&metadata.phase!=='finished',duration=metadata.parameters.duration_s;
 const elapsed=Number.isFinite(metadata.start_s)&&!['planning','preparation'].includes(metadata.phase)?Math.max(0,data.orbital_s-metadata.start_s):null;
 $('live-session').textContent=`· ${metadata.parameters.method.toUpperCase()}`;
 $('live-title').textContent=`${metadata.parameters.method.toUpperCase()} · ${metadata.phase==='finished'?(outcomeLabels[metadata.outcome]||metadata.outcome):(phaseLabels[view.phase]||comparisonLabels[view.phase]||'Simulazione continua')}`;
 $('live-badge').textContent=replay?'REPLAY':active?'LIVE · tempo reale':'Terminata';panel.dataset.live=String(active);
 $('live-description').textContent=metadata.failure_reason||'Sequenza condivisa con l’altra modalità. Il clock orbitale procede in tempo reale, senza ripianificazione.';
 const percent=elapsed===null?null:Math.min(100,elapsed/duration*100);
 $('live-percent').textContent=percent===null?'Preparazione · clock orbitale non ancora avviato':number(percent,1)+'% della durata';$('live-bar').value=percent||0;
 $('live-elapsed').textContent=clockText(elapsed);$('live-remaining').textContent=clockText(elapsed===null?null:Math.max(0,duration-elapsed));
 $('live-migrations').textContent=String(sample.completed_migrations??metadata.migrations?.filter(row=>row.success).length??0);
 $('live-controller').textContent=!view.stale&&view.controller_satellite?`NORAD ${view.controller_satellite}`:'Nessuno confermato';
 $('live-service').textContent=metadata.controllers_fenced&&active?'Sonde terminate':view.forwarding_observed===true?'Ultima sonda riuscita':view.forwarding_observed===false?'Perdita osservata':'Non ancora misurato';
 $('live-next').textContent=sample.next_migration?`NORAD ${sample.next_migration.sat_b} · t = ${number(sample.next_migration.trigger_s,0)} s`:'Nessun passaggio residuo';
 liveView={active,replay,timestamp:view.updated_utc};updateLiveFreshness();
 const geometryStart=metadata.start_s,geometryEnd=metadata.final_orbital_s??data.orbital_s;
 $('simulation-replay-control').hidden=metadata.phase!=='finished'||!Number.isFinite(geometryStart)||!Number.isFinite(geometryEnd);
 if(Number.isFinite(geometryStart)&&Number.isFinite(geometryEnd)){$('simulation-replay').min=Math.floor(geometryStart);$('simulation-replay').max=Math.floor(geometryEnd);$('simulation-replay').value=simulationTick===null?Math.floor(geometryEnd):simulationTick;}
}
function updateLiveFreshness(){if(!liveView)return;const age=liveView.timestamp?Math.max(0,Math.floor((Date.now()-Date.parse(liveView.timestamp))/1000)):null;const stale=liveView.active&&age!==null&&age>10;$('live-progress').dataset.stale=String(stale);$('live-freshness').textContent=liveView.replay?'Consultazione dei dati salvati':age===null?'In attesa di telemetria':stale?`Nessun aggiornamento da ${age} s`:`Ultima evidenza ${age} s fa`;}
function renderTimeline(){const list=$('timeline'),bottom=list.scrollTop+list.clientHeight>=list.scrollHeight-30;list.replaceChildren();for(const event of [...events.values()].sort((a,b)=>a.id-b.id).slice(-400)){const li=document.createElement('li'),time=document.createElement('time'),label=document.createElement('span');time.dateTime=event.timestamp_utc;time.textContent=event.orbital_s==null?new Date(event.timestamp_utc).toLocaleTimeString('it-IT'):seconds(event.orbital_s);label.textContent=event.phase==='continuous_comparison'?comparisonLabels[event.comparison_phase]:event.phase==='comparison_session'?`Avvio ${event.method.toUpperCase()}`:phaseLabels[event.phase]||({comparison_finished:'Confronto terminato',simulation_finished:'Esecuzione terminata'}[event.phase])||event.phase;li.append(time,label);if(event.reason){const reason=document.createElement('span');reason.className='reason';reason.textContent=event.reason;li.append(reason);}list.append(li);}if(bottom)list.scrollTop=list.scrollHeight;}
function selectJob(identifier){selectedJob=identifier;events.clear();renderTimeline();if(stream)stream.close();if(!identifier)return;const source=new EventSource('/api/v1/jobs/'+identifier+'/events');stream=source;source.onopen=()=>{if(selectedJob!==identifier)return;orbitStreamDisconnected=false;$('stream-status').textContent='Aggiornamenti connessi';topology();};source.onmessage=message=>{if(selectedJob!==identifier)return;const event=JSON.parse(message.data);if(event.phase!=='session_tick'){events.set(event.id,event);renderTimeline();}if(event.phase==='session_tick'&&event.simulation_id===selectedSimulation&&simulationTick===null){clearTimeout(orbitalUpdateTimer);orbitalUpdateTimer=setTimeout(topology,150);}if(['continuous_comparison','comparison_session','comparison_finished','simulation_finished'].includes(event.phase))scheduleRefresh();};source.onerror=()=>{if(selectedJob!==identifier)return;orbitStreamDisconnected=true;$('stream-status').textContent='Connessione interrotta · riconnessione automatica';if(orbitData?.presentation?.mode==='live')stopOrbit('Stream disconnesso · riconnessione in corso');};source.addEventListener('end',()=>{source.close();if(selectedJob!==identifier)return;orbitStreamDisconnected=false;$('stream-status').textContent='Timeline completa';stoppingJob='';scheduleRefresh();});}
$('job-form').addEventListener('submit',async event=>{event.preventDefault();$('start').disabled=true;$('launch-error').hidden=true;try{const job=await api('/jobs',{operation:'compare_continuous',parameters:{duration_s:Number($('duration').value),rate_bps:1000000000}});pendingJob=job.job_id;selectedComparison='';selectedSimulation='';simulationTick=null;following=true;manualComparison=false;resetOrbit();selectJob(job.job_id);notice('Confronto avviato · preparazione automatica');await refresh();}catch(error){$('launch-error').textContent='Avvio non riuscito: '+error.message;$('launch-error').hidden=false;if(state)renderState();}});
$('stop').addEventListener('click',async()=>{const identifier=state?.lock?.job_id;if(!identifier)return;stoppingJob=identifier;$('stop').disabled=true;try{await api('/jobs/'+identifier+'/stop',{});notice('Interruzione richiesta · attendo la messa in sicurezza del laboratorio.');}catch(error){stoppingJob='';notice(error.message,true);renderState();}});
$('recover').addEventListener('click',async()=>{$('recover').disabled=true;try{const job=await api('/jobs',{operation:'recover',parameters:{}});selectJob(job.job_id);await refresh();}catch(error){notice('Ripristino non riuscito: '+error.message,true);}finally{$('recover').disabled=false;}});
$('comparison-select').addEventListener('change',()=>{manualComparison=true;pendingJob='';selectedComparison=$('comparison-select').value;following=true;selectSimulation('',true);selectJob(currentPair()?.job_id||'');refresh();});
$('simulation-select').addEventListener('change',()=>{selectSimulation($('simulation-select').value);simulationTick=null;topology();});
let replayDelay;$('simulation-replay').addEventListener('input',()=>{simulationTick=Number($('simulation-replay').value);following=false;clearTimeout(replayDelay);replayDelay=setTimeout(topology,100);});
$('follow-current').addEventListener('click',()=>{following=true;simulationTick=null;refresh();});
function durationEstimate(){const duration=Number($('duration').value);$('duration-estimate').textContent=Number.isFinite(duration)&&duration>0?`Circa ${number(duration*2/60,1)} minuti totali, più preparazione e ripristino.`:'Indica una durata positiva per ciascuna modalità.';}
$('duration').addEventListener('input',durationEstimate);durationEstimate();
document.addEventListener('DOMContentLoaded',async()=>{try{token=(await api('/session')).token;await Promise.all([topology(),refresh()]);setInterval(refresh,5000);setInterval(updateLiveFreshness,1000);}catch(error){notice('Sessione locale non disponibile: '+error.message,true);}});
