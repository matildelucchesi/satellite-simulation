'use strict';
const $=id=>document.getElementById(id);
const ns='http://www.w3.org/2000/svg';
const outcomeLabels={success:'Riuscita',experimental_failure:'Fallita',invalid_lab:'Non valida',interrupted:'Interrotta',recovery_required:'Recupero',running:'In corso'};
const phaseLabels={trigger:'Trigger',alignment:'Allineamento FSO',quiescence:'Quiescenza',snapshot_initial:'Snapshot iniziale',source_stop:'Arresto sorgente',source_stopped:'Sorgente arrestata',transfer:'Trasferimento',transfer_verified:'Checksum verificato',target_start:'Avvio destinazione',restore_initial:'Restore iniziale',freeze:'Freeze sorgente',source_frozen:'Sorgente congelata',restore_delta:'Applicazione delta',verify:'Verifica API',ack:'ACK',cutover:'Cutover hardware',completed:'Migrazione completata',attempt_failed:'Tentativo fallito',rollback:'Recupero sorgente',failed:'Migrazione fallita',prepare:'Preparazione fixture',run_finished:'Prova terminata',job_finished:'Job terminato',calibration:'Calibrazione',transport_capacity:'Verifica capacità TCP',workflow_stage:'Fase del workflow'};
let token='',state=null,runs=[],jobs=[],campaigns={},artifacts=[],selectedRun='',selectedJob='',stream=null,events=new Map(),replayTick=null,loading=false,stoppingJob='';
const number=(value,digits=2)=>value===null||value===undefined?'—':Number(value).toLocaleString('it-IT',{maximumFractionDigits:digits});
const seconds=value=>value===null||value===undefined?'—':number(value)+' s';
function notice(message,error=false){$('notice').textContent=message;$('notice').dataset.state=error?'error':'success';}
async function api(path,body){const response=await fetch('/api/v1'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);return data;}
function option(select,value,label){const element=document.createElement('option');element.value=value;element.textContent=label;select.append(element);}
function svg(tag,attrs={},parent){const element=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attrs))element.setAttribute(key,String(value));if(parent)parent.append(element);return element;}
function svgText(parent,x,y,text,cls=''){const element=svg('text',{x,y,class:cls},parent);element.textContent=text;return element;}
function metric(label,value){const term=document.createElement('dt');term.textContent=label;const definition=document.createElement('dd');definition.textContent=value;$('metrics').append(term,definition);}
function visibleRuns(){return runs.filter(row=>(!$('method-filter').value||row.method===$('method-filter').value)&&(!$('purpose-filter').value||row.purpose===$('purpose-filter').value));}

async function refresh(){
 if(loading)return;loading=true;$('refresh').dataset.state='loading';
 try{
  [state,{runs},{jobs},campaigns,{artifacts}]=await Promise.all([api('/state'),api('/runs'),api('/jobs'),api('/campaigns'),api('/artifacts')]);
  renderState();renderSelections();renderMatrix();renderResults();renderDownloads();
  if(!selectedRun&&runs.length)await selectRun(runs[0].run_id);
  if(!selectedJob&&jobs.length)selectJob(state.lock?.job_id||jobs[0].job_id);
  if(selectedRun&&!replayTick)await topology();
  $('refresh').dataset.state='success';
 }catch(error){notice('Impossibile leggere il laboratorio: '+error.message,true);$('refresh').dataset.state='error';}
 finally{loading=false;}
}
function renderState(){
 const components=$('components');components.replaceChildren();
 const rows=[['Mininet / BMv2',state.components.mininet?.reachable?(state.components.mininet.data.switches_alive?'17 switch attivi':'Switch da verificare'):'Irraggiungibile'],
 ['Controller A',state.components.sat_a?.reachable?'API disponibile':'API irraggiungibile'],
 ['Controller B',state.components.sat_b?.reachable?'API disponibile':'API irraggiungibile'],
 ['Proxy P4',state.components.p4_proxy?.reachable?'Raggiungibile':'Irraggiungibile'],
 ['Autorità',state.components.p4_proxy?.data?.active||'Nessuna · fenced'],
 ['ACK corrente',state.components.p4_proxy?.data?.ack?'Valido':'Assente']];
 for(const [name,value] of rows){const li=document.createElement('li');const label=document.createElement('span');label.textContent=name;const status=document.createElement('span');status.className='component-value';status.textContent=value;li.append(label,status);components.append(li);}
 $('frozen-status').textContent=state.frozen?'Configurazione principale congelata. Parametri scientifici bloccati.':'Configurazione principale in preparazione.';
 $('start').disabled=!!state.lock&&$('operation').value!=='recover';
 const busy=jobs.find(job=>job.job_id===state.lock?.job_id);
 $('stop').disabled=!busy||!['queued','running'].includes(busy.status)||stoppingJob===busy.job_id;
 notice(state.lock?`Laboratorio occupato · ${busy?.operation||state.lock.job_id} · ${busy?.status||'verifica recupero'}`:'Laboratorio libero. Seleziona un’operazione per avviare un job.');
}
function renderSelections(){
 const runSelect=$('run-select');runSelect.replaceChildren();option(runSelect,'','Geometria iniziale');
 for(const run of runs)option(runSelect,run.run_id,`${run.method} · ${number(run.configured_rate_bps/1e6,0)} Mbit/s · ${outcomeLabels[run.outcome]||run.outcome} · ${run.run_id.slice(-6)}`);
 runSelect.value=selectedRun;
 const jobSelect=$('job-select');jobSelect.replaceChildren();option(jobSelect,'','Nessun job');
 for(const job of jobs)option(jobSelect,job.job_id,`${job.operation} · ${job.status} · ${job.job_id.slice(-6)}`);
 jobSelect.value=selectedJob;
 const old=$('event').value;$('event').replaceChildren();option($('event'),'','Contatto diagnostico funzionale');
 for(const event of campaigns.events?.events||[])option($('event'),event.event_id,`${event.percentile_case} · ${event.sat_a} → ${event.sat_b}`);
 $('event').value=old;
 const job=jobs.find(row=>row.job_id===selectedJob);
 $('job-state').textContent=job?`${job.status}${job.error?' · '+job.error:''}`:'';
}
function renderMatrix(){
 const selected=campaigns.events?.events||[];$('matrix').replaceChildren();
 const count=runs.filter(row=>row.purpose==='primary').length;
 $('campaign-status').textContent=selected.length?`${count}/18 prove principali registrate. Esiti live, compresi fallimenti e limiti del laboratorio.`:'Nessun evento principale congelato. Eseguire calibrazione e selezione.';
 for(const event of selected){const section=document.createElement('section');section.className='matrix-case';const heading=document.createElement('h3');heading.textContent=`${event.percentile_case} · ${event.sat_a} → ${event.sat_b}`;section.append(heading);const grid=document.createElement('div');grid.className='matrix-grid';grid.append(document.createElement('span'));
  for(const label of ['100 M','1 G','10 G']){const cell=document.createElement('span');cell.className='column';cell.textContent=label;grid.append(cell);}
  for(const method of ['cold','hot']){const label=document.createElement('span');label.textContent=method;grid.append(label);for(const rate of [1e8,1e9,1e10]){const run=runs.find(row=>row.purpose==='primary'&&row.event.event_id===event.event_id&&row.method===method&&row.configured_rate_bps===rate);const button=document.createElement('button');button.textContent=run?(outcomeLabels[run.outcome]||run.outcome):'—';button.disabled=!run;button.dataset.outcome=run?.outcome||'missing';button.title=`${method} · ${rate/1e6} Mbit/s · ${run?.outcome||'Non eseguita'}`;if(run)button.addEventListener('click',()=>selectRun(run.run_id));grid.append(button);}}
  section.append(grid);$('matrix').append(section);
 }
}
function renderResults(){
 const filtered=visibleRuns();$('run-rows').replaceChildren();$('empty-results').hidden=filtered.length>0;
 const labels=['Prova','Esito','Modalità','Downtime controller','Throughput effettivo'];
 for(const run of filtered){const tr=document.createElement('tr');const values=[run.run_id.slice(-6),outcomeLabels[run.outcome]||run.outcome,`${run.method} · ${number(run.configured_rate_bps/1e6,0)} M`,seconds(run.controller_downtime_s),run.image_throughput_bps?number(run.image_throughput_bps/1e6,1)+' Mbit/s':'—'];values.forEach((value,index)=>{const td=document.createElement('td');td.dataset.label=labels[index];if(index===0){const button=document.createElement('button');button.textContent=value;button.addEventListener('click',()=>selectRun(run.run_id));td.append(button);}else td.textContent=value;tr.append(td);});$('run-rows').append(tr);}
 const graph=$('comparison');graph.replaceChildren();const measured=filtered.filter(row=>row.controller_downtime_s!==null&&row.controller_downtime_s!==undefined).slice(0,12).reverse();
 if(!measured.length){svgText(graph,20,80,'Nessun downtime misurato disponibile.');return;}
 const max=Math.max(1,...measured.map(row=>row.controller_downtime_s));svg('line',{x1:55,x2:780,y1:250,y2:250,class:'chart-axis'},graph);
 for(let index=0;index<=4;index++){const y=250-index*50;svgText(graph,5,y+4,number(max*index/4,0));}
 svgText(graph,5,28,'s');const width=700/measured.length;
 measured.forEach((run,index)=>{const height=run.controller_downtime_s/max*200;const bar=svg('rect',{x:65+index*width,y:250-height,width:Math.max(5,width-10),height,class:'bar '+run.method,tabindex:0,role:'button','aria-label':`${run.method} ${run.run_id.slice(-6)}: ${seconds(run.controller_downtime_s)}`},graph);const title=svg('title',{},bar);title.textContent=`${run.method} · ${seconds(run.controller_downtime_s)} · ${outcomeLabels[run.outcome]||run.outcome}`;bar.addEventListener('click',()=>selectRun(run.run_id));bar.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectRun(run.run_id);}});svgText(graph,65+index*width,275,run.run_id.slice(-4));});
}
async function selectRun(identifier){
 selectedRun=identifier;replayTick=null;$('run-select').value=identifier;$('metrics').replaceChildren();
 if(!identifier){$('replay-control').hidden=true;await topology();return;}
 try{const [run,observations]=await Promise.all([api('/runs/'+identifier),api('/runs/'+identifier+'/observations')]);
  if(selectedRun!==identifier)return;
  $('detail-title').textContent=`Prova ${identifier.slice(-6)}`;
  const inputs=run.inputs||{};metric('Tipo',run.execution_kind||'live-hybrid');metric('Finalità',run.purpose||inputs.purpose||'—');metric('Esito',outcomeLabels[run.outcome]||run.outcome);metric('Downtime controller',seconds(run.controller_downtime_s));metric('Downtime servizio',run.probes?.ping?.time_to_stable_recovery_s===null?'Non attribuibile':seconds(run.probes?.ping?.time_to_stable_recovery_s));metric('Baseline servizio',run.baseline_service_available===undefined?'—':run.baseline_service_available?'Disponibile':'Già indisponibile');metric('Ping persi',run.probes?.ping?.loss_fraction===undefined?'—':number(run.probes.ping.loss_fraction*100)+'%');metric('Retry',run.attempt===undefined?'—':String(Math.max(0,run.attempt-1)));metric('Byte ricevuti',number(run.bytes_received,0));metric('Byte reinviati',number(run.restarted_payload_bytes,0));metric('Ritrasmissioni TCP',run.tcp_retransmissions===null?'Misura non disponibile':number(run.tcp_retransmissions,0));
  $('failure').textContent=run.failure_reason||run.invalid_reason||'';
  $('raw-detail').textContent=JSON.stringify({event:run.event||inputs.event,operations:run.operations,
    transfers:run.events?.filter(row=>row.phase==='transfer_verified'),shared_docker_daemon:run.shared_docker_daemon,probes:run.probes},null,2);
  const geometry=observations.geometry||[];const finished=run.outcome!=='running';$('replay-control').hidden=!finished||!geometry.length;
  if(geometry.length){$('replay').min=geometry[0].orbital_s;$('replay').max=geometry.at(-1).orbital_s;$('replay').value=geometry.at(-1).orbital_s;}
  await topology();renderDownloads();
 }catch(error){notice('Dettaglio non disponibile: '+error.message,true);}
}
async function topology(){
 try{const query=new URLSearchParams();if(selectedRun)query.set('run_id',selectedRun);if(replayTick!==null)query.set('orbital_s',replayTick);
  const data=await api('/topology?'+query);const graph=$('topology');graph.replaceChildren();const locations=new Map();
  for(const plane of [1,2]){const nodes=data.nodes.filter(row=>row.plane===plane).sort((a,b)=>a.phase_rank-b.phase_rank);const x=plane===1?225:640;svgText(graph,x-55,30,`Piano ${plane}`,'plane-label');nodes.forEach((node,index)=>locations.set(node.norad,{x,y:65+index*420/Math.max(1,nodes.length-1)}));}
  const pathEdges=new Set();for(let i=1;i<data.service_path.length;i++)pathEdges.add([data.service_path[i-1],data.service_path[i]].sort((a,b)=>a-b).join('-'));
  for(const [a,b] of data.links){const p=locations.get(a),q=locations.get(b);const arc=p.x===q.x?`M ${p.x} ${p.y} Q ${p.x-70} ${(p.y+q.y)/2} ${q.x} ${q.y}`:`M ${p.x} ${p.y} L ${q.x} ${q.y}`;svg('path',{d:arc,class:'edge'+(pathEdges.has([a,b].join('-'))?' service':'')},graph);}
  for(const node of data.nodes){const p=locations.get(node.norad);const group=svg('g',{class:'node'+(node.eclipsed?' shadow':'')+(node.norad===data.sat_a?' source':'')+(node.norad===data.sat_b?' destination':''),tabindex:0,'aria-label':`${node.norad}, piano ${node.plane}, ${node.eclipsed?'in ombra':'illuminato'}`},graph);svg('circle',{cx:p.x,cy:p.y,r:13},group);svgText(group,p.x+24,p.y+5,String(node.norad));if(node.norad===data.sat_a||node.norad===data.sat_b)svgText(group,p.x-5,p.y+5,node.norad===data.sat_a?'A':'B','role-label');const title=svg('title',{},group);title.textContent=`NORAD ${node.norad} · ${node.eclipsed?'ombra':'luce'} · TEME ${node.position_teme_km.map(v=>number(v,1)).join(', ')} km`;}
  $('orbital-time').textContent=`t = ${number(data.orbital_s,0)} s · geometria modellata`;$('replay-label').textContent=`t = ${number(data.orbital_s,0)} s · replay dei dati salvati`;
 }catch(error){$('orbital-time').textContent='Geometria non disponibile: '+error.message;}
}
function selectJob(identifier){
 selectedJob=identifier;$('job-select').value=identifier;events.clear();$('timeline').replaceChildren();if(stream)stream.close();
 if(!identifier)return;
 $('stream-status').textContent='Recupero timeline persistente…';
 stream=new EventSource('/api/v1/jobs/'+identifier+'/events');
 stream.onmessage=message=>{const event=JSON.parse(message.data);events.set(event.id,event);renderTimeline();const live=jobs.some(job=>job.job_id===identifier&&['queued','running'].includes(job.status));if(live&&event.phase==='prepare'&&event.run_id){selectRun(event.run_id);refresh();}if(event.phase==='run_finished'){refresh();if(event.run_id===selectedRun)selectRun(selectedRun);}};
 stream.onopen=()=>{$('stream-status').textContent='Stream connesso · riconnessione automatica con cursore evento';};
 stream.onerror=()=>{$('stream-status').textContent='Stream disconnesso · tentativo di riconnessione…';};
 stream.addEventListener('end',message=>{$('stream-status').textContent='Timeline completa · '+JSON.parse(message.data).status;stream.close();stoppingJob='';refresh();if(selectedRun)selectRun(selectedRun);});
}
function renderTimeline(){const list=$('timeline');const bottom=list.scrollTop+list.clientHeight>=list.scrollHeight-30;list.replaceChildren();for(const event of [...events.values()].sort((a,b)=>a.id-b.id)){const li=document.createElement('li');const time=document.createElement('time');time.dateTime=event.timestamp_utc;time.textContent=event.orbital_s===undefined?new Date(event.timestamp_utc).toLocaleTimeString('it-IT'):`${number(event.orbital_s,1)} s`;const label=document.createElement('span');label.textContent=phaseLabels[event.phase]||event.phase;li.append(time,label);if(event.reason){const reason=document.createElement('span');reason.className='reason';reason.textContent=event.reason.slice(0,300);li.append(reason);}list.append(li);}if(bottom)list.scrollTop=list.scrollHeight;}
function renderDownloads(){const list=$('downloads');list.replaceChildren();const filtered=artifacts.filter(row=>$('artifact-filter').value==='all'||row.label.includes(selectedRun||'__none__')||!row.label.includes('/runs/')&&!row.label.includes('/lab/'));for(const row of filtered){const li=document.createElement('li');const link=document.createElement('a');link.href=row.download_url;link.download='';link.textContent=row.label;link.title=row.label;const size=document.createElement('span');size.textContent=number(row.bytes/1024,1)+' KiB';li.append(link,size);list.append(li);}}

$('job-form').addEventListener('submit',async event=>{event.preventDefault();const button=$('start');button.disabled=true;button.dataset.state='loading';try{const operation=$('operation').value;const parameters=operation==='run'?{method:$('method').value,rate_bps:Number($('rate').value),...($('event').value?{event_id:$('event').value}:{})}:{};const job=await api('/jobs',{operation,parameters});selectedJob='';selectJob(job.job_id);notice('Job avviato · '+job.job_id);button.dataset.state='success';await refresh();}catch(error){button.dataset.state='error';notice('Avvio rifiutato: '+error.message,true);button.disabled=false;}});
$('stop').addEventListener('click',async()=>{const job=state?.lock?.job_id;if(!job)return;$('stop').disabled=true;try{await api('/jobs/'+job+'/stop',{});stoppingJob=job;notice('Interruzione richiesta. Attendo fencing e recupero della sorgente.');}catch(error){notice('Interruzione non inviata: '+error.message,true);}});
$('operation').addEventListener('change',()=>{$('run-parameters').hidden=$('operation').value!=='run';if(state)renderState();});
$('run-select').addEventListener('change',()=>selectRun($('run-select').value));$('job-select').addEventListener('change',()=>selectJob($('job-select').value));
for(const id of ['method-filter','purpose-filter'])$(id).addEventListener('change',renderResults);
$('artifact-filter').addEventListener('change',renderDownloads);$('refresh').addEventListener('click',refresh);
let replayDelay;$('replay').addEventListener('input',()=>{replayTick=Number($('replay').value);clearTimeout(replayDelay);replayDelay=setTimeout(topology,100);});
(async()=>{try{token=(await api('/session')).token;await refresh();setInterval(refresh,5000);}catch(error){notice('Sessione locale non disponibile: '+error.message,true);}})();
