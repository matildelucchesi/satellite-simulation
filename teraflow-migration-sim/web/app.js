/* Console for the event-based Hot/Cold experiment. All data comes from the local API; commands
   carry the session CSRF token. Jobs keep running when the page is closed. */
const $=id=>document.getElementById(id);
let token='',state=null,jobs=[],profile=null,comparisons=[],verificationRows=[],artifacts=[];
let selectedComparison='',selectedEvent='',stream=null,streamJob='',streamEvents=[],refreshTimer=null;

function node(tag,text,className){const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(className)element.className=className;return element;}
function notice(message,error=false){const box=$('notice');box.textContent=message;box.dataset.state=error?'error':'ok';}
async function api(path,body){
 const response=await fetch('/api/v1'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(body)});
 const data=await response.json();if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);return data;
}
const yesNo=value=>value===true?'sì':value===false?'no':'—';

/* ---------- pages ---------- */
/* The console opens on the laboratory page; old #experiment links land there too. */
const PAGES=['lab','scenario','results'];
function showPage(){
 const requested=location.hash.slice(1),page=PAGES.includes(requested)?requested:'lab';
 for(const name of PAGES)$('page-'+name).hidden=name!==page;
 document.querySelectorAll('.tabs a').forEach(link=>link.setAttribute('aria-current',link.dataset.page===page?'page':'false'));
}
window.addEventListener('hashchange',showPage);

/* ---------- scenario ---------- */
function renderProfile(){
 const box=$('profile');box.replaceChildren();
 if(!profile){box.append(node('p','Nessun profilo di scenario. Si crea con tools/build_scenario.py e si installa con tools/install_scenario.py.','small'));return;}
 const s=profile.summary,stats=profile.statistics||{},laser=profile.laser_terminals||{},p=profile.event_parameters||{};
 box.append(node('h2','Profilo installato'));
 const rows=[['Profilo',profile.profile+(profile.installed?'':' · non installato')],
  ['Piani (RAAN)',s.raan_deg.map(value=>value.toFixed(1).replace('.',',')+'°').join(' e ')],
  ['Satelliti',`${s.satellites} (${s.per_plane.join(' + ')})`],
  ['Quota',`${Math.round(s.altitude_km[0])}–${Math.round(s.altitude_km[1])} km`],
  ['Laser per satellite',`${(laser.intra_plane||0)+(laser.inter_plane||0)}: ${laser.intra_plane} nel piano, ${laser.inter_plane} verso l’altro piano`],
  ['Velocità del collegamento',(profile.rate_bps||[]).map(value=>value/1e9+' Gbit/s').join(', ')],
  ['Dominio del controller',`${s.domain} satelliti (${profile.domain.plane_1.length} + ${profile.domain.plane_2.length})`],
  ['Cambi di topologia nel giorno',stats.path_segments!==undefined?String(Math.max(0,stats.path_segments-1)):'—'],
  ['Software del controller',profile.migration?.software_on_board?'a bordo di ogni satellite: migra solo lo stato':'trasferito a ogni migrazione'],
  ['File del profilo',profile.integrity==='sizes_match'?'coerenti con il manifest':'cambiati: '+(profile.changed_files||[]).join(', ')]];
 const list=node('dl');for(const [term,value] of rows)list.append(node('dt',term),node('dd',value));box.append(list);
 box.append(node('h2','Eventi dell’esperimento'));
 const table=node('table'),head=node('tr'),body=node('tbody');
 for(const title of ['N.','Migrazione','Salti','Destinazione','Ora','Luce sorgente','Luce destinazione'])head.append(node('th',title));
 const thead=node('thead');thead.append(head);
 profile.selected_events.forEach((event,index)=>{const tr=node('tr');tr.append(node('td',String(index+1)),node('td',`${event.source} → ${event.destination}`),node('td',String(event.hops)),node('td',event.other_plane?'altro piano':'stesso piano'),node('td',clock(event.trigger_s)),node('td',Math.round(event.source_light_remaining_s/60)+' min'),node('td',Math.round(event.destination_light_remaining_s/60)+' min'));body.append(tr);});
 table.append(thead,body);const scroller=node('div',undefined,'table-scroll');scroller.append(table);box.append(scroller);
 box.append(node('p',`Ogni evento parte ${Math.round(p.trigger_lead_s/60)} min prima che la sorgente entri in ombra. Gli eventi coprono 1, 5 e 7 salti laser, l’ultimo verso l’altro piano; ogni salto verso i satelliti che seguono sull’orbita dà circa 3 min di luce in più alla destinazione. La destinazione deve restare al sole almeno ${Math.round(p.minimum_destination_light_s/60)} min, con un percorso stabile per almeno ${Math.round(p.minimum_path_persistence_s/60)} min.`,'small muted'));
 renderPicker();
}
function renderPicker(){
 const box=$('event-picker');box.replaceChildren();
 if(!profile)return;
 if(!selectedEvent&&profile.selected_events.length)selectedEvent=profile.selected_events[0].event_id;
 profile.selected_events.forEach((event,index)=>{const button=node('button',`Evento ${index+1}`);button.type='button';button.setAttribute('aria-pressed',String(event.event_id===selectedEvent));button.addEventListener('click',()=>{selectedEvent=event.event_id;preview.eventId=null;renderPicker();});box.append(button);});
}

/* ---------- live orbit view ----------
   During a verification or an experiment the view follows the run in progress (event, orbital
   time, migration phases). Without a job it previews the selected event, faster than real time. */
let scene=null,missionEvents=[],missionJob='',lastFrame=0,lastPanel=0;
let sceneSample={eventId:null,orbital:null,loading:false,error:''};
const preview={speed:10,startMs:0,eventId:null};
const PREVIEW_SPAN_S=1800;
const twoDigits=value=>String(value).padStart(2,'0');
const minutes=seconds=>`${twoDigits(Math.floor(Math.max(0,seconds)/60))}:${twoDigits(Math.floor(Math.max(0,seconds)%60))}`;

function sceneJob(){const job=activeJob();return job&&['functional','compare_events'].includes(job.operation)?job:null;}
function currentMission(){
 const job=sceneJob();
 if(!job||job.job_id!==missionJob||!profile)return null;
 return missionState(missionEvents,profile.selected_events,job.operation);
}
function sceneView(now){
 const mission=currentMission();
 if(mission&&mission.event)return {mission,event:mission.event,orbital:orbitalAt(mission,now),live:true};
 const event=profile?.selected_events.find(row=>row.event_id===selectedEvent)||profile?.selected_events[0];
 if(!event)return null;
 if(preview.eventId!==event.event_id){preview.eventId=event.event_id;preview.startMs=now;}
 const elapsed=((now-preview.startMs)/1000*preview.speed)%PREVIEW_SPAN_S;
 return {mission:null,event,orbital:event.trigger_s-ORBIT_LEAD_S+elapsed,live:false};
}
/* Loader of the first draw: shown until the first topology sample is on screen, never again. */
function orbitLoader(stateName,text){
 const box=$('orbit-loader');if(box.dataset.state==='done')return;
 box.dataset.state=stateName;
 if(stateName==='done'){box.setAttribute('aria-hidden','true');box.querySelector('svg').pauseAnimations?.();return;}
 if(text)$('orbit-loader-text').textContent=text;
}
async function ensureSample(event,orbital){
 const eventId=event.event_id;
 if(sceneSample.loading)return;
 if(sceneSample.eventId===eventId&&Math.abs(orbital-sceneSample.orbital)<45)return;
 sceneSample.loading=true;
 const tick=Math.max(0,Math.min(86399,Math.floor(orbital)));
 try{
  const topology=await api(`/topology?event=${encodeURIComponent(eventId)}&orbital_s=${tick}`);
  /* The route drawn is the one of the selected event in the profile: the general catalogue can
     hold an entry with the same name (source and instant) but a different destination. */
  scene.setTopology({...topology,migration_path:event.path||topology.migration_path});
  sceneSample={eventId,orbital:topology.orbital_s,loading:false,error:''};
 }catch(error){sceneSample={...sceneSample,loading:false,error:error.message};}
}
function frame(now){
 requestAnimationFrame(frame);
 if(!scene||$('page-scenario').hidden||document.hidden||now-lastFrame<33)return;
 lastFrame=now;
 const wall=Date.now(),view=sceneView(wall);if(!view)return;
 ensureSample(view.event,view.orbital);
 if(sceneSample.eventId!==view.event.event_id){if(sceneSample.error)orbitLoader('error','Vista orbitale non disponibile: '+sceneSample.error);return;}
 orbitLoader('done');
 const m=view.mission;
 const linkActive=m?m.linkActive:view.orbital>=view.event.trigger_s;
 const result=scene.update(view.orbital,{controller:m?m.controller:view.event.source,controllerState:m?m.controllerState:'active',
  linkActive,transferring:Boolean(m&&m.transferring),communicating:Boolean(m&&m.communicating),source:view.event.source,destination:view.event.destination});
 const label=$('route-label');
 label.hidden=!result?.anchor;
 if(!label.hidden){label.style.left=(result.anchor.x/result.size.width*100).toFixed(2)+'%';label.style.top=(result.anchor.y/result.size.height*100).toFixed(2)+'%';label.dataset.side=result.anchor.side;}
 if(wall-lastPanel>400){lastPanel=wall;renderMission(view,wall);}
}
function renderMission(view,wall){
 const m=view.mission,event=view.event,index=profile.selected_events.findIndex(row=>row.event_id===event.event_id)+1;
 $('scene-mode-text').textContent=view.live?'In diretta':`Anteprima ×${preview.speed}`;
 $('scene-mode').dataset.state=view.live?'live':'idle';
 $('mission-title').textContent=view.live?`Evento ${m.eventIndex} di ${m.eventTotal}`:`Evento ${index}`;
 $('mission-method').textContent=view.live?(methodLabel(m.method)||''):'';
 const run=view.live&&m.run&&m.run.position?m.run:null;
 $('mission-run').hidden=!run;
 if(run)$('mission-run').textContent=`Prova ${run.position} di ${run.total} · ${run.warmup?'riscaldamento, esclusa dai risultati':'replica '+run.replica+' di '+run.replicas}`;
 $('event-picker').hidden=view.live;$('preview-speed').hidden=view.live;
 $('mission-clock').textContent=relativeClock(view.orbital,event.trigger_s);
 $('mission-start').textContent=migrationCountdown(view);$('mission-time').textContent=clock(view.orbital);
 const shadowAt=event.source_shadow_entry_s??(event.trigger_s+event.source_light_remaining_s);
 $('mission-shadow').textContent=view.orbital<shadowAt?`fra ${minutes(shadowAt-view.orbital)}`:'sorgente in ombra';
 $('mission-hops').textContent=String(event.hops);
 /* The route, satellite by satellite: who hosts the controller, who relays, who receives */
 const path=event.path||[event.source,event.destination],host=m?m.controller:event.source,hops=$('mission-path');
 hops.replaceChildren();hops.classList.toggle('talking',Boolean(m&&m.communicating));
 path.forEach((id,position)=>{
  const role=id===host?'host':position===path.length-1?'target':'relay',li=node('li',undefined,role);
  li.title=role==='host'?'Controller':role==='target'?'Destinazione':'Relè';li.append(node('span',String(id)));hops.append(li);
 });
 let status='';
 if(!view.live)status='Nessun job in corso: la vista mostra l’evento scelto più veloce del reale. Le fasi compaiono quando parte una verifica o un esperimento.';
 else if(m.stage==='waiting'||m.stage==='preparing')status=`Preparazione del laboratorio${m.preparation?': '+m.preparation.toLowerCase():''}. L’orbita resta ferma a T−30 s.`;
 else if(m.stage==='countdown')status='Laboratorio pronto: l’orbita avanza verso il trigger.';
 else if(m.stage==='completed')status=orbitRunning(m)?'Migrazione completata: il servizio resta sotto osservazione per 30 s.':'Prova conclusa.';
 if(view.live&&m.failure){
  const reason=/interrupted by user/i.test(m.failure.reason)?'interruzione richiesta dall’utente':m.failure.reason||'causa non indicata';
  if(m.stage==='failed')status=`Prova interrotta${m.current?' durante «'+m.current.label+'»':''}: ${reason}.${m.recoveryRequired?' Serve il ripristino del laboratorio.':m.cleanup?' '+m.cleanup+'.':''}`;
  else status=`Tentativo ${m.failure.attempt||1} non riuscito: ${reason}. ${m.rolledBack?'La sorgente ha ripreso il controllo; ':''}il percorso viene riallineato per un nuovo tentativo.`;
 }
 if(sceneSample.error)status=`Vista orbitale non disponibile: ${sceneSample.error}`;
 $('mission-status').textContent=status;$('mission-status').hidden=!status;
 /* Phase list in the side panel */
 const list=$('mission-steps');list.replaceChildren();list.hidden=!view.live||!m.steps.length;
 if(view.live)for(const step of m.steps){
  const li=node('li',undefined,`step ${step.status}${step.downtime?' downtime':''}`);
  const time=step.status==='current'&&step.startMs!==null?duration((wall-step.startMs)/1000):step.duration_s!==null?duration(step.duration_s):step.offset_s!==null&&step.key==='completed'?relativeClock(event.trigger_s+step.offset_s,event.trigger_s):'';
  const name=node('span',undefined,'name');name.append(document.createTextNode(step.label));if(step.where)name.append(node('span',step.where,'where'));
  li.append(node('span',undefined,'mark'),name,node('span',time,'time'));list.append(li);
 }
 /* Label on the route */
 const ticks=$('route-ticks');ticks.replaceChildren();
 if(view.live&&m.steps.length){
  const number=m.current?m.steps.indexOf(m.current)+1:0;
  $('route-meta').textContent=`${methodLabel(m.method)} · fase ${number} di ${m.steps.length}${m.attempt>1?' · tentativo '+m.attempt:''}${m.stage==='failed'?' · interrotta':''}`;
  $('route-phase').textContent=m.current?m.current.label:'In attesa del trigger';
  for(const step of m.steps)ticks.append(node('li',undefined,`${step.status}${step.downtime?' downtime':''}`));
  const down=m.downtime,box=$('route-downtime');
  box.hidden=!down.startMs;
  if(down.startMs)box.textContent=down.endMs?`Controller fermo per ${duration((down.endMs-down.startMs)/1000)}`:`Controller fermo da ${duration((wall-down.startMs)/1000)}`;
 }else{
  $('route-meta').textContent='Percorso previsto';
  $('route-phase').textContent=`${event.hops} salti laser verso ${event.destination}`;
  $('route-downtime').hidden=true;
 }
 /* Before the trigger the label also says how long until the migration starts */
 const waiting=view.live?!m.linkActive:view.orbital<event.trigger_s;
 $('route-countdown').hidden=!waiting;if(waiting)$('route-countdown').textContent=`Migrazione ${migrationCountdown(view)}`;
}
/* Time to the migration: the trigger fires at the event's orbital instant. During the
   preparation the orbit is held, so the remaining 30 s start after the baseline. */
function migrationCountdown(view){
 const m=view.mission,event=view.event,left=event.trigger_s-view.orbital;
 if(m){
  if(m.stage==='waiting'||m.stage==='preparing')return `dopo la preparazione + ${minutes(ORBIT_LEAD_S)}`;
  if(!m.linkActive)return `fra ${minutes(left)}`;
  const cutover=m.steps.find(step=>step.key==='cutover');
  if(m.stage==='completed'&&cutover&&cutover.offset_s!==null)return `completata in ${minutes(cutover.offset_s)}`;
  return `in corso da ${minutes(-left)}`;
 }
 return left>0?`fra ${minutes(left)}`:`avviata da ${minutes(-left)}`;
}
document.querySelectorAll('#preview-speed button').forEach(button=>button.addEventListener('click',()=>{
 const now=Date.now(),elapsed=((now-preview.startMs)/1000*preview.speed)%PREVIEW_SPAN_S;
 preview.speed=Number(button.dataset.speed);preview.startMs=now-elapsed/preview.speed*1000;
 document.querySelectorAll('#preview-speed button').forEach(other=>other.setAttribute('aria-pressed',String(other===button)));
}));

/* ---------- laboratory ---------- */
function activeJob(){const id=state?.lock?.job_id;return id?(state.job&&state.job.job_id===id?state.job:jobs.find(row=>row.job_id===id)):null;}
function latestLabJob(){return activeJob()||jobs.find(row=>['functional','compare_events','recover'].includes(row.operation))||null;}
/* Each migration goes from SAT-A (source) to SAT-B (destination). The controller rows say what
   each one is doing now, from the P4 authority and the API health. */
function controllerRow(slot,row,active,busy){
 const label=slot.toUpperCase(),role=slot==='sat-a'?'sorgente':'destinazione';
 let value,level;
 if(row?.reachable)[value,level]=active===slot?['controller attivo','ok']:['API pronte, in attesa','ok'];
 else if(active&&active!==slot)[value,level]=slot==='sat-a'?['spento dopo la migrazione','idle']:['spento, in attesa','idle'];
 else [value,level]=['spento',busy?'warn':'idle'];
 return [label,value,level,role];
}
function componentRows(){
 const c=state?.components||{},busy=Boolean(state?.lock),active=c.p4_proxy?.data?.active||null;
 return [['Mininet',...(c.mininet?.reachable?[`${c.mininet.data?.switch_count??'—'} switch${c.mininet.data?.switches_alive?' attivi':''}`,'ok']:['non raggiungibile','error'])],
  ['Proxy P4',...(c.p4_proxy?.reachable?(active?['autorità a '+active.toUpperCase(),'ok']:['nessuna autorità','idle']):['non raggiungibile','error'])],
  controllerRow('sat-a',c.sat_a,active,busy),controllerRow('sat-b',c.sat_b,active,busy),
  ['Scenario',...(state?.scenario?.profile?[state.scenario.events_ready?`${profile?.selected_events?.length??''} eventi pronti`.trim():'eventi mancanti',state.scenario.events_ready?'ok':'warn']:['non installato','error'])],
  ['Lock',...(busy?['occupato','warn']:['libero','ok'])]];
}
function renderComponents(){
 const list=$('components');list.replaceChildren();
 componentRows().forEach(([name,value,level,role])=>{
  const li=node('li',undefined,'channel');li.dataset.state=level;
  const label=node('span',undefined,'name');label.append(node('span',undefined,'led'),document.createTextNode(name));
  if(role)label.append(node('span',role,'role'));
  li.append(label,node('span',undefined,'leader'),node('span',value,'value'));list.append(li);
 });
 /* Laboratory status, top right of its block */
 const c=state?.components||{},job=activeJob();
 const [text,level]=!(c.mininet?.reachable&&c.p4_proxy?.reachable)?['Non raggiungibile','error']
  :state?.lock?[job?.operation==='recover'?'Ripristino in corso':'Job in corso','busy']
  :!state?.scenario?.events_ready?['Scenario mancante','warn']:['Pronto','ok'];
 $('lab-state').textContent=text;$('lab-badge').dataset.state=level;
}
const when=value=>value?new Date(value).toLocaleString('it-IT',{dateStyle:'short',timeStyle:'short'}):'';
const mean=values=>{const known=values.filter(Number.isFinite);return known.length===values.length&&known.length?known.reduce((a,b)=>a+b,0)/known.length:null;};
function renderLatest(){
 const verification=verificationRows[0],run=method=>(verification?.runs||[]).find(row=>row.method===method);
 const ok=verification?.complete;
 $('verify-hot').textContent=ok?duration(run('hot')?.controller_downtime_s):'—';
 $('verify-cold').textContent=ok?duration(run('cold')?.controller_downtime_s):'—';
 $('verify-note').textContent=verification?`Ultima verifica: ${ok?'riuscita':'non riuscita'} il ${when(verification.created_utc)}.`:'Nessuna verifica registrata.';
 const experiment=comparisons.find(row=>row.complete);
 /* Median over every run of the experiment; schema 1 had one run per event, schema 2 has replicas */
 const values=method=>experiment?experiment.events.flatMap(row=>row.replicas?row.replicas.map(entry=>entry.runs?.[method]?.controller_downtime_s):[row.runs?.[method]?.controller_downtime_s]).filter(Number.isFinite):[];
 const middle=list=>{if(!list.length)return null;const sorted=[...list].sort((a,b)=>a-b),half=Math.floor(sorted.length/2);return sorted.length%2?sorted[half]:(sorted[half-1]+sorted[half])/2;};
 $('start-hot').textContent=experiment?duration(middle(values('hot'))):'—';
 $('start-cold').textContent=experiment?duration(middle(values('cold'))):'—';
 $('start-note').textContent=experiment?`Ultimo esperimento completato il ${when(experiment.created_utc)}, ${values('hot').length+values('cold').length} prove.`:'Nessun esperimento completato.';
}
function renderAxis(view){
 const runs=experimentRuns(profile?.selected_events?.length||3,profile?.experiment?.replicas||3,profile?.experiment?.warmup_runs??1);
 const durations=procedureDurations(jobs,runs),scale=axisScale([durations.functional.seconds,durations.compare_events.seconds]);
 const axis=$('axis'),share=seconds=>Math.min(100,seconds/scale.maxSeconds*100).toFixed(2)+'%';
 /* Rebuild only when the durations change, so the bars' entry animation plays once. */
 const key=JSON.stringify([durations,scale.maxSeconds]);
 if(axis.dataset.key!==key){
  axis.dataset.key=key;axis.replaceChildren();
  for(const [operation,label,className] of [['functional','verifica','v'],['compare_events','esperimento','e']]){
   const item=durations[operation],bar=node('span',undefined,'span '+className);bar.append(node('b',`${label} · ${item.estimated?'circa ':''}${hoursMinutes(item.seconds)}${item.estimated?' (stima, '+item.runs+' prove)':item.measured?'':' (tipico)'}`));
   bar.style.width=share(item.seconds);axis.append(bar);
  }
  for(const minutes of scale.ticks){const last=minutes===scale.ticks.at(-1),tick=node('span',String(minutes),last?'tick last':'tick');tick.style.left=share(minutes*60);axis.append(tick);}
  const cursor=node('span',undefined,'cursor');cursor.title='Tempo trascorso del job in corso';axis.append(cursor);
 }
 const cursor=axis.querySelector('.cursor'),running=view?.active&&['functional','compare_events'].includes(view.operation)&&Number.isFinite(view.elapsedSeconds);
 cursor.hidden=!running;if(running)cursor.style.left=share(view.elapsedSeconds);
}
function renderJob(){
 const job=latestLabJob(),comparison=job?.operation==='compare_events'?comparisons.find(row=>!row.complete&&!row.reason)||comparisons[0]:null;
 const view=jobView(state?.lock?job:(job&&!['queued','running'].includes(job.status)?job:null),comparison);
 $('job').dataset.active=String(view.active);
 $('job-heading').textContent=view.active?'Job in corso':job?'Ultimo job':'Job';
 $('job-title').textContent=view.active?view.step:view.title;
 $('job-detail').textContent=view.active?view.title+(job?.cancellation_requested?' · interruzione richiesta, messa in sicurezza in corso':''):view.detail;
 $('job-clock').hidden=!view.active;$('job-clock').textContent=view.elapsed||'';
 $('stop').hidden=!view.canStop;
 /* The log belongs to a running job; a finished one points to its results. */
 $('job-log').hidden=!view.active;$('job-results').hidden=view.active||!job;
 $('recover').hidden=!(view.needsRecovery||(state?.lock&&state.worker_alive===false));
 const free=state&&!state.lock&&state.scenario?.events_ready;
 $('verify').disabled=!free;$('start').disabled=!free;
 const timelineBox=$('timeline');timelineBox.replaceChildren();
 for(const row of timeline(streamEvents)){const li=node('li');li.append(node('time',row.time),node('span',row.text));if(row.failed)li.className='failed';timelineBox.append(li);}
 if(!streamEvents.length)timelineBox.append(node('li','Nessun evento da mostrare.','muted'));
 renderAxis(view);
 if(job&&job.job_id!==streamJob)follow(job.job_id);
}
/* Information points: one open at a time; Escape or a click elsewhere closes them. */
function closePops(except){document.querySelectorAll('[data-pop][aria-expanded="true"]').forEach(button=>{if(button!==except){button.setAttribute('aria-expanded','false');$(button.dataset.pop).classList.remove('open');}});}
document.addEventListener('click',event=>{
 const button=event.target.closest('[data-pop]');
 if(button){const open=button.getAttribute('aria-expanded')!=='true';closePops(button);button.setAttribute('aria-expanded',String(open));$(button.dataset.pop).classList.toggle('open',open);return;}
 if(!event.target.closest('.pop'))closePops();
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closePops();});
function follow(identifier){
 if(stream)stream.close();
 streamJob=identifier;streamEvents=[];missionJob=identifier;missionEvents=[];
 stream=new EventSource('/api/v1/jobs/'+identifier+'/events');
 stream.onmessage=message=>{try{const event=JSON.parse(message.data);streamEvents.push(event);if(missionRelevant(event))missionEvents.push(event);if(streamEvents.length>800)streamEvents=streamEvents.slice(-400);renderJob();}catch{}};
 stream.addEventListener('end',()=>{stream.close();scheduleRefresh();});
 stream.onerror=()=>{};
}
async function launch(operation){
 $('verify').disabled=true;$('start').disabled=true;$('launch-error').hidden=true;
 try{const job=await api('/jobs',{operation,parameters:{}});notice({functional:'Verifica avviata',compare_events:'Esperimento avviato',recover:'Ripristino avviato'}[operation]+': '+job.job_id);follow(job.job_id);await refresh();
  /* A verification or an experiment is followed on the orbit view */
  if(operation!=='recover')location.hash='scenario';}
 catch(error){$('launch-error').textContent='Avvio non riuscito: '+error.message;$('launch-error').hidden=false;await refresh();}
}
$('verify').addEventListener('click',()=>launch('functional'));
$('start').addEventListener('click',()=>launch('compare_events'));
$('recover').addEventListener('click',()=>launch('recover'));
$('stop').addEventListener('click',()=>$('stop-dialog').showModal());
$('stop-dialog').addEventListener('close',async()=>{
 if($('stop-dialog').returnValue!=='stop')return;
 const job=activeJob();if(!job)return;
 try{await api('/jobs/'+job.job_id+'/stop',{});notice('Interruzione richiesta: messa in sicurezza del laboratorio in corso.');}
 catch(error){notice('Interruzione non riuscita: '+error.message,true);}
 scheduleRefresh();
});

/* ---------- results ---------- */
function renderComparisonSelect(){
 const select=$('comparison-select'),current=selectedComparison||comparisons[0]?.comparison_id||'';
 select.replaceChildren();
 for(const row of comparisons){const option=node('option',`${new Date(row.created_utc).toLocaleString('it-IT')} · ${row.complete?'completato':row.reason?'non completato':'in corso'}`);option.value=row.comparison_id;option.selected=row.comparison_id===current;select.append(option);}
 select.hidden=!comparisons.length;
}
$('comparison-select').addEventListener('change',event=>{selectedComparison=event.target.value;renderResults();});
function phaseText(run){
 const s=run.phases?.seconds||{};
 const parts=[['avvio controller','controller_startup'],['ripristino API','api_restore'],['delta','delta_apply'],['arresto sorgente','source_stop'],['verifica','api_verification'],['riconciliazione','queued_topology_apply'],['cutover','cutover']]
  .filter(([,key])=>s[key]!==undefined).map(([label,key])=>`${label} ${duration(s[key])}`);
 return parts.join(' · ')||'fasi non disponibili';
}
const REASONS={interrupted:'interrotto',recovery_required:'serve il ripristino del laboratorio',too_many_failures:'3 prove non riuscite di fila',failed:'prova non riuscita',service_not_verified:'servizio non verificato'};
const spread=stat=>stat&&stat.n?`${duration(stat.median)}${stat.n>1?` · ${duration(stat.q1)}–${duration(stat.q3)}`:''}`:'—';
const interval=stat=>stat&&stat.n?`${duration(stat.median)}${stat.ci95?` · IC ${duration(stat.ci95[0])}–${duration(stat.ci95[1])}`:''}`:'—';
function table(headers,rows,rowClass){
 const element=node('table'),thead=node('thead'),head=node('tr'),body=node('tbody');
 for(const title of headers)head.append(node('th',title));
 thead.append(head);
 for(const cells of rows){const tr=node('tr',undefined,rowClass?rowClass(cells):undefined);cells.forEach((cell,index)=>tr.append(node(index===0?'th':'td',cell)));body.append(tr);}
 element.append(thead,body);const scroller=node('div',undefined,'table-scroll');scroller.append(element);return scroller;
}
/* Schema 2: replicas per event. Overview first, then each event with its replicas. */
function renderDesignResults(comparison,box,status){
 const design=comparison.design||{};
 status.textContent=`${comparison.complete?'Completato':comparison.reason?'Non completato: '+(REASONS[comparison.reason]||comparison.reason):'In corso'} · ${comparison.completed_runs} di ${comparison.run_total} prove${comparison.failed_runs?`, ${comparison.failed_runs} non ${comparison.failed_runs===1?'riuscita':'riuscite'}`:''} · ${design.replicas} repliche per evento e modalità, riscaldamento escluso · seme ${design.seed} · ${comparison.rate_bps/1e9} Gbit/s`;
 box.append(node('h3','Downtime del controller per evento'));
 box.append(table(['Evento','Percorso','Salti','Destinazione','Hot · mediana e quartili','Cold · mediana e quartili','Cold − Hot · mediana e IC 95 %','Coppie'],
  comparison.events.map(row=>{const s=row.statistics?.controller_downtime_s;return [`E${row.index}`,`${row.source} → ${row.destination}`,String(row.hops),row.other_plane?'altro piano':'stesso piano',
   spread(s?.hot),spread(s?.cold),interval(s?.cold_minus_hot),String(s?.cold_minus_hot?.n??0)];})));
 box.append(node('p','IC 95 %: intervallo bootstrap della mediana delle differenze appaiate, sulle repliche con entrambe le misure. Misure mancanti escluse.','small muted'));
 if(comparison.warmup?.run){const w=comparison.warmup;box.append(node('p',`Riscaldamento (escluso): evento ${w.event}, ${methodLabel(w.method)}, downtime ${duration(w.run.controller_downtime_s)}, ${w.run.success?'riuscita':'non riuscita'}.`,'small muted'));}
 for(const row of comparison.events){
  const card=node('details',undefined,'event-detail'),summary=node('summary');
  summary.append(node('span',`E${row.index} · ${row.source} → ${row.destination}`,'event-name'),node('span',`${row.hops} salti · ${row.other_plane?'altro piano':'stesso piano'} · ${clock(row.trigger_s)}`,'small muted'));
  card.append(summary);
  const s=row.statistics||{};
  card.append(node('p',`Durata della migrazione: Hot ${spread(s.total_operation_s?.hot)}, Cold ${spread(s.total_operation_s?.cold)}; Cold − Hot ${interval(s.total_operation_s?.cold_minus_hot)}.`,'small'));
  const rows=[...row.replicas].sort((a,b)=>a.replica-b.replica).map(entry=>{
   const hot=entry.runs.hot,cold=entry.runs.cold,lost=run=>run?(run.lost_pings??'—'):'—';
   const outcome=[hot,cold].every(run=>run&&run.success)?'riuscite':[hot,cold].map(run=>run?(run.success?'':methodLabel(run.method)+' non riuscita'):'').filter(Boolean).join(', ')||'incompleta';
   return [String(entry.replica),entry.order.map(methodLabel).join(' → '),duration(hot?.controller_downtime_s),duration(cold?.controller_downtime_s),
    duration(entry.cold_minus_hot?.controller_downtime_s),duration(hot?.total_operation_s),duration(cold?.total_operation_s),`${lost(hot)} / ${lost(cold)}`,
    hot?.transfer_one_way_delay_s!=null?`${(hot.transfer_one_way_delay_s*1000).toFixed(1).replace('.',',')} ms`:'—',outcome];
  });
  card.append(table(['Replica','Ordine','Hot Δt','Cold Δt','Cold − Hot','Hot durata','Cold durata','Ping persi H / C','Ritardo del percorso','Esito'],rows));
  box.append(card);
 }
}
function renderResults(){
 renderComparisonSelect();
 const box=$('results'),status=$('results-status');box.replaceChildren();
 const comparison=comparisons.find(row=>row.comparison_id===selectedComparison)||comparisons[0];
 if(!comparison){status.textContent='Nessun esperimento registrato.';}
 else{
  if(comparison.schema_version>=2){renderDesignResults(comparison,box,status);renderVerifications();renderDownloads(comparison);return;}
  status.textContent=`${comparison.complete?'Completato':comparison.reason?'Non completato: '+comparison.reason:'In corso'} · ${comparison.rate_bps/1e9} Gbit/s · ${comparison.software_on_board?'migra solo lo stato':'con trasferimento delle immagini'} · una replica per evento e modalità, valori per evento.`;
  for(const row of comparison.events){
   const card=node('article',undefined,'event-card');
   card.append(node('h3',`Evento ${row.index}: ${row.source} → ${row.destination} · ${row.hops} salti · ${clock(row.trigger_s)} · ordine ${row.order.map(methodLabel).join(' → ')}`));
   const table=node('table'),thead=node('thead'),head=node('tr'),body=node('tbody');
   for(const title of ['','Downtime del controller','Durata','Ping persi','Entro l’ombra','Percorso valido','Esito'])head.append(node('th',title));
   thead.append(head);
   for(const method of ['hot','cold']){
    const run=row.runs[method],tr=node('tr');tr.append(node('th',methodLabel(method)));
    if(!run){for(let i=0;i<6;i++)tr.append(node('td','—'));body.append(tr);continue;}
    tr.append(node('td',duration(run.controller_downtime_s)),node('td',duration(run.total_operation_s)),
     node('td',run.lost_pings===null||run.lost_pings===undefined?'non misurato':`${run.lost_pings} su ${run.observed_pings}`),
     node('td',yesNo(run.feasibility?.fits_before_shadow)),node('td',yesNo(run.feasibility?.multi_hop_path_whole_operation)),
     node('td',run.success?'riuscita':(run.outcome||'non riuscita')));
    body.append(tr);
   }
   if(row.cold_minus_hot){const d=row.cold_minus_hot,tr=node('tr','', 'difference');tr.append(node('th','Cold − Hot'),node('td',duration(d.controller_downtime_s)),node('td',duration(d.total_operation_s)),node('td',d.lost_pings===null||d.lost_pings===undefined?'—':String(d.lost_pings)),node('td',''),node('td',''),node('td',''));body.append(tr);}
   table.append(thead,body);const scroller=node('div',undefined,'table-scroll');scroller.append(table);card.append(scroller);
   for(const method of ['hot','cold'])if(row.runs[method])card.append(node('p',`${methodLabel(method)} · ${phaseText(row.runs[method])}`,'small muted'));
   box.append(card);
  }
 }
 renderVerifications();renderDownloads(comparison);
}
function renderVerifications(){
 const box=$('verifications');box.replaceChildren();
 if(!verificationRows.length){box.append(node('p','Nessuna verifica registrata.','small'));return;}
 const table=node('table'),thead=node('thead'),head=node('tr'),body=node('tbody');
 for(const title of ['Data','Esito','Hot: downtime','Cold: downtime','Cold − Hot'])head.append(node('th',title));
 thead.append(head);
 for(const row of verificationRows.slice(0,5)){
  const hot=(row.runs||[]).find(run=>run.method==='hot'),cold=(row.runs||[]).find(run=>run.method==='cold'),tr=node('tr');
  tr.append(node('td',row.created_utc?new Date(row.created_utc).toLocaleString('it-IT'):'—'),node('td',row.complete?'riuscita':row.reason||'non completata'),
   node('td',duration(hot?.controller_downtime_s)),node('td',duration(cold?.controller_downtime_s)),node('td',duration(row.cold_minus_hot?.controller_downtime_s)));
  body.append(tr);
 }
 table.append(thead,body);const scroller=node('div',undefined,'table-scroll');scroller.append(table);box.append(scroller);
}
function renderDownloads(comparison){
 const list=$('downloads');list.replaceChildren();
 const prefixes=comparison?[`results/event-comparisons/${comparison.comparison_id}/`]:[];
 const names={'metadata.json':'Risultati dell’esperimento (JSON)','summary.csv':'Tabella per migrazione (CSV)'};
 const files=artifacts.filter(item=>prefixes.some(prefix=>item.label.startsWith(prefix))||item.label==='results/functional-gate.json');
 for(const file of files){const li=node('li'),name=file.label.split('/').pop(),link=node('a',names[name]||(name==='functional-gate.json'?'Ultima verifica (JSON)':name));link.href=file.download_url;link.title=file.label;li.append(link,node('span',Math.ceil(file.bytes/1024)+' kB'));list.append(li);}
 if(!files.length)list.append(node('li','Nessun file disponibile.','muted'));
}

/* ---------- refresh ---------- */
function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(refresh,300);}
async function refresh(){
 try{
  [state,{jobs},{comparisons},{verifications:verificationRows},{artifacts}]=await Promise.all([api('/state'),api('/jobs'),api('/event-comparisons'),api('/verifications'),api('/artifacts')]);
  const c=state.components||{},ready=c.mininet?.reachable&&c.p4_proxy?.reachable;
  $('health').textContent=(ready?'Laboratorio raggiungibile':'Laboratorio non raggiungibile')+(state.lock?' · job in corso':'');
  $('health').dataset.state=ready?'ok':'error';
  renderComponents();renderLatest();renderJob();renderResults();
 }catch(error){$('health').textContent='Console non collegata: '+error.message;$('health').dataset.state='error';}
}
async function loadProfile(){
 try{const {profiles}=await api('/scenario-profiles');profile=profiles.find(row=>row.installed&&row.summary)||profiles.find(row=>row.summary)||null;}catch{profile=null;}
 renderProfile();
 if(!profile)orbitLoader('error','Nessuno scenario installato: la vista orbitale resta vuota.');
}
document.addEventListener('DOMContentLoaded',async()=>{
 showPage();
 if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){$('orbit-loader').querySelector('svg').pauseAnimations?.();preview.speed=1;document.querySelectorAll('#preview-speed button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.speed==='1')));}
 scene=createOrbitScene($('orbit'));requestAnimationFrame(frame);
 try{token=(await api('/session')).token;}catch(error){notice('Sessione locale non disponibile: '+error.message,true);return;}
 await loadProfile();await refresh();setInterval(refresh,5000);setInterval(renderJob,1000);
});
