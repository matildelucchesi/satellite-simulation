/* Console for the event-based Hot/Cold experiment. All data comes from the local API; commands
   carry the session CSRF token. Jobs keep running when the page is closed. */
const $=id=>document.getElementById(id);
let token='',state=null,jobs=[],profile=null,comparisons=[],verificationRows=[],artifacts=[];
let selectedComparison='',stream=null,streamJob='',streamEvents=[],refreshTimer=null;

function node(tag,text,className){const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(className)element.className=className;return element;}
function notice(message,error=false){const box=$('notice');box.textContent=message;box.dataset.state=error?'error':'ok';}
/* Contact with the console server. A request that fails without an answer means the server is
   unreachable (an HTTP error does not); from then on the orbit view stays at the last instant the
   server answered instead of running ahead on a stale sample. */
const link={okAt:Date.now(),lostAt:null};
function contact(ok){
 if(ok){link.okAt=Date.now();if(link.lostAt!==null){link.lostAt=null;lastPanel=0;}}
 else if(link.lostAt===null){link.lostAt=link.okAt;lastPanel=0;}
}
async function api(path,body){
 let response;
 try{response=await fetch('/api/v1'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(body)});}
 catch{contact(false);throw new Error('console non raggiungibile');}
 contact(true);
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
/* Event buttons: the preview goes through all the events by itself; a click jumps to one. */
function renderPicker(){
 const box=$('event-picker');box.replaceChildren();
 if(!profile)return;
 profile.selected_events.forEach((event,index)=>{const button=node('button',`Evento ${index+1}`);button.type='button';button.dataset.index=String(index+1);button.setAttribute('aria-pressed',String(index===0));button.addEventListener('click',()=>jumpToEvent(index+1));box.append(button);});
}

/* ---------- live orbit view ----------
   During a verification or an experiment the view follows the run in progress (event, orbital
   time, migration phases). Without a job it plays a preview: every event, Hot then Cold, with the
   phase times of a verification or an experiment chosen in the panel, faster than real time
   (mission.js). */
let scene=null,missionEvents=[],missionJob='',lastFrame=0,lastPanel=0;
let sceneSample={eventId:null,orbital:null,loading:false,error:'',failedAt:0};
/* A topology sample moves the satellites at their angular speed and flips each one's light at most
   once: beyond this many orbital seconds from it the drawing would be wrong, so it is not drawn. */
const SAMPLE_REACH_S=120;
const preview={speed:10,startMs:Date.now(),script:null,times:null,source:null,chosen:'',loading:'',cache:{}};
const twoDigits=value=>String(value).padStart(2,'0');
const minutes=seconds=>`${twoDigits(Math.floor(Math.max(0,seconds)/60))}:${twoDigits(Math.floor(Math.max(0,seconds)%60))}`;

function sceneJob(){const job=activeJob();return job&&['functional','compare_events'].includes(job.operation)?job:null;}
/* Events a job runs: those of the destination policy for an experiment started with it */
function jobEvents(job){return job?.parameters?.policy==='cost'&&profile?.policy_events?.length?profile.policy_events:profile.selected_events;}
function currentMission(){
 const job=sceneJob();
 if(!job||job.job_id!==missionJob||!profile)return null;
 return missionState(missionEvents,jobEvents(job),job.operation);
}
function previewNow(now){
 if(!profile?.selected_events?.length)return null;
 if(!preview.script)preview.script=previewScript(profile.selected_events,preview.times,preview.speed);
 return previewPosition(preview.script,(now-preview.startMs)/1000);
}
/* Rebuild the script (new speed or new measured times) keeping the position on screen. */
function rebuildPreview(change){
 const now=Date.now(),position=previewNow(now),index=position?preview.script.segments.indexOf(position.segment):-1;
 change();preview.script=null;
 /* Same events and methods in the same order: the segment keeps its index */
 if(position&&previewNow(now))preview.startMs=now-1000*previewElapsed(preview.script,index,position.pieceIndex,position.inPiece);
}
function jumpToEvent(index){
 const now=Date.now();if(!previewNow(now))return;
 const segment=preview.script.segments.findIndex(row=>row.eventIndex===index);
 preview.startMs=now-1000*previewElapsed(preview.script,Math.max(0,segment),0,0);
 lastPanel=0;
}
/* Sources of the preview times: verifications and experiments whose events belong to the
   installed profile, newest first. `map` turns the job's event number into the profile's. */
const shortDate=iso=>new Date(iso).toLocaleString('it-IT',{dateStyle:'short',timeStyle:'short'});
function previewSources(){
 if(!profile)return [];
 const ids=profile.selected_events.map(event=>event.event_id),out=[];
 for(const job of jobs){
  const id=job.progress?.comparison_id;if(!id)continue;
  if(job.operation==='functional'&&job.status==='completed'){
   const row=verificationRows.find(entry=>entry.comparison_id===id),index=row?ids.indexOf(row.event?.catalog_event_id):-1;
   if(index<0)continue;
   out.push({jobId:job.job_id,kind:'verifica',created:job.created_utc,map:{1:index+1},label:`Verifica del ${shortDate(job.created_utc)} · evento ${index+1}`});
  }else if(job.operation==='compare_events'){
   const row=comparisons.find(entry=>entry.comparison_id===id);if(!row)continue;
   const map={};for(const event of row.events||[]){const index=ids.indexOf(event.catalog_event_id);if(index>=0)map[event.index]=index+1;}
   if(!Object.keys(map).length)continue;
   out.push({jobId:job.job_id,kind:'esperimento',created:job.created_utc,map,
    label:`Esperimento del ${shortDate(job.created_utc)} · ${row.complete?'completato':`${row.completed_runs??0} di ${row.run_total??'?'} prove`}`});
  }
 }
 return out;
}
function renderPreviewSources(){
 const select=$('preview-source'),sources=previewSources();
 if(!preview.chosen&&sources.length)preview.chosen=sources[0].jobId;
 const signature=sources.map(row=>row.jobId+row.label).join('|')+'#'+preview.chosen;
 if(select.dataset.signature!==signature){
  select.dataset.signature=signature;select.replaceChildren();
  for(const row of sources){const option=node('option',row.label);option.value=row.jobId;option.selected=row.jobId===preview.chosen;select.append(option);}
  if(!sources.length)select.append(node('option','Nessuna prova con questi eventi: tempi di riferimento'));
  select.disabled=!sources.length;
 }
 const source=sources.find(row=>row.jobId===preview.chosen);
 if(source&&preview.source?.jobId!==source.jobId)loadPreviewSource(source);
}
$('preview-source').addEventListener('change',event=>{preview.chosen=event.target.value;renderPreviewSources();lastPanel=0;});
/* Phase times of one job, read once from its event stream and kept for the session. */
function loadPreviewSource(source){
 const use=times=>{if(preview.chosen===source.jobId)rebuildPreview(()=>{preview.times=times;preview.source=source;});lastPanel=0;};
 if(preview.cache[source.jobId])return use(preview.cache[source.jobId]);
 if(preview.loading===source.jobId)return;
 preview.loading=source.jobId;lastPanel=0;
 const events=[],stream=new EventSource('/api/v1/jobs/'+source.jobId+'/events');
 const finish=()=>{stream.close();if(preview.loading===source.jobId)preview.loading='';
  preview.cache[source.jobId]=previewTimes(measuredRuns(events),index=>source.map[index]??null);use(preview.cache[source.jobId]);};
 stream.onmessage=message=>{try{const event=JSON.parse(message.data);if(event.phase==='comparison_run'||event.phase==='event_comparison'||missionRelevant(event))events.push(event);}catch{}};
 stream.addEventListener('end',finish);
 stream.onerror=()=>{if(stream.readyState===EventSource.CLOSED)finish();};
}
/* Where the times of the segment on screen come from */
function previewOrigin(m){
 const source=preview.source,method=methodLabel(m.method);
 if(preview.loading)return 'Lettura dei tempi della prova scelta…';
 if(m.origin.measured)return `Tempi: ${source.kind} del ${shortDate(source.created)} · evento ${m.eventIndex} · ${method}${m.origin.replica?` · replica ${m.origin.replica}`:''}${m.origin.attempt>1?` · tentativo ${m.origin.attempt}`:''}`;
 return source?`Tempi di riferimento: nessuna prova riuscita dell’evento ${m.eventIndex} in ${method} in questa ${source.kind}`:'Tempi di riferimento di una verifica dell’8/11/2026';
}
function sceneView(now){
 const mission=currentMission();
 if(mission&&mission.event)return {mission,event:mission.event,orbital:orbitalAt(mission,now),live:true};
 const position=previewNow(now);if(!position)return null;
 const m=previewMission(preview.script,position);
 return {mission:m,event:m.event,orbital:position.orbital,live:false};
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
 if(sceneSample.loading||(sceneSample.error&&Date.now()-sceneSample.failedAt<2000))return;
 if(sceneSample.eventId===eventId&&Math.abs(orbital-sceneSample.orbital)<45)return;
 sceneSample.loading=true;
 const tick=Math.max(0,Math.min(86399,Math.floor(orbital)));
 try{
  const topology=await api(`/topology?event=${encodeURIComponent(eventId)}&orbital_s=${tick}`);
  /* The route drawn is the one of the selected event in the profile: the general catalogue can
     hold an entry with the same name (source and instant) but a different destination. */
  scene.setTopology({...topology,migration_path:event.path||topology.migration_path});
  sceneSample={eventId,orbital:topology.orbital_s,loading:false,error:'',failedAt:0};
 }catch(error){sceneSample={...sceneSample,loading:false,error:error.message,failedAt:Date.now()};}
}
function frame(now){
 requestAnimationFrame(frame);
 if(!scene||$('page-scenario').hidden||document.hidden||now-lastFrame<33)return;
 lastFrame=now;
 /* While the console is unreachable the view stays at the last instant it answered */
 const real=Date.now(),wall=link.lostAt??real,view=sceneView(wall);if(!view)return;
 ensureSample(view.event,view.orbital);
 if(sceneSample.eventId!==view.event.event_id){if(sceneSample.error)orbitLoader('error','Vista orbitale non disponibile: '+sceneSample.error);return;}
 orbitLoader('done');
 const m=view.mission;
 if(Math.abs(view.orbital-sceneSample.orbital)>SAMPLE_REACH_S){if(real-lastPanel>400){lastPanel=real;renderMission(view,wall);}return;}
 const result=scene.update(view.orbital,{controller:m.controller,controllerState:m.controllerState,
  linkActive:m.linkActive,transferring:Boolean(m.transferring),communicating:Boolean(m.communicating),source:view.event.source,destination:view.event.destination});
 const label=$('route-label');
 label.hidden=!result?.anchor;
 if(!label.hidden){label.style.left=(result.anchor.x/result.size.width*100).toFixed(2)+'%';label.style.top=(result.anchor.y/result.size.height*100).toFixed(2)+'%';label.dataset.side=result.anchor.side;}
 if(real-lastPanel>400){lastPanel=real;renderMission(view,wall);}
}
function renderMission(view,wall){
 const m=view.mission,event=view.event;
 $('scene-mode-text').textContent=view.live?'In diretta':`Anteprima ×${preview.speed}`;
 $('scene-mode').dataset.state=view.live?'live':'idle';
 $('mission-title').textContent=`Evento ${m.eventIndex} di ${m.eventTotal}`;
 $('mission-method').textContent=methodLabel(m.method)||'';
 document.querySelectorAll('#event-picker button').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.index)===m.eventIndex)));
 const run=view.live&&m.run&&m.run.position?m.run:null;
 /* Live: which run of the job; preview: which verification or experiment the times come from */
 $('mission-run').hidden=!run&&!m.preview;
 if(run)$('mission-run').textContent=`Prova ${run.position} di ${run.total} · ${run.warmup?'riscaldamento, esclusa dai risultati':'replica '+run.replica+' di '+run.replicas}`;
 else if(m.preview)$('mission-run').textContent=previewOrigin(m);
 $('event-picker').hidden=view.live;$('preview-speed').hidden=view.live;$('preview-source-box').hidden=view.live;
 $('mission-clock').textContent=relativeClock(view.orbital,event.trigger_s);
 $('mission-start').textContent=migrationCountdown(view);$('mission-time').textContent=clock(view.orbital);
 const shadowAt=event.source_shadow_entry_s??(event.trigger_s+event.source_light_remaining_s);
 $('mission-shadow').textContent=view.orbital<shadowAt?`fra ${minutes(shadowAt-view.orbital)}`:'sorgente in ombra';
 $('mission-hops').textContent=String(event.hops);
 /* The route, satellite by satellite: who hosts the controller, who relays, who receives */
 const path=event.path||[event.source,event.destination],host=m.controller,hops=$('mission-path');
 hops.replaceChildren();hops.classList.toggle('talking',Boolean(m.communicating));
 path.forEach((id,position)=>{
  const role=id===host?'host':position===path.length-1?'target':'relay',li=node('li',undefined,role);
  li.title=role==='host'?'Controller':role==='target'?'Destinazione':'Relè';li.append(node('span',String(id)));hops.append(li);
 });
 let status='';
 if(m.preview){
  status=`${m.stage==='completed'?`Migrazione completata: il controller ora è su ${event.destination}. `:''}Anteprima, nessun job in corso: ogni evento in Hot e poi in Cold, con i tempi della prova indicata sopra; la fonte si sceglie nel menu «Tempi da». Le fasi più brevi sono rallentate per renderle visibili.`;
 }
 else if(m.stage==='waiting'||m.stage==='preparing')status=`Preparazione del laboratorio${m.preparation?': '+m.preparation.toLowerCase():''}. L’orbita resta ferma a T−30 s.`;
 else if(m.stage==='countdown')status='Laboratorio pronto: l’orbita avanza verso il trigger.';
 else if(m.stage==='completed')status=orbitRunning(m)?'Migrazione completata: il servizio resta sotto osservazione per 30 s.':'Prova conclusa.';
 if(view.live&&m.failure){
  const reason=/interrupted by user/i.test(m.failure.reason)?'interruzione richiesta dall’utente':m.failure.reason||'causa non indicata';
  if(m.stage==='failed')status=`Prova interrotta${m.current?' durante «'+m.current.label+'»':''}: ${reason}.${m.recoveryRequired?' Serve il ripristino del laboratorio.':m.cleanup?' '+m.cleanup+'.':''}`;
  else status=`Tentativo ${m.failure.attempt||1} non riuscito: ${reason}. ${m.rolledBack?'La sorgente ha ripreso il controllo; ':''}il percorso viene riallineato per un nuovo tentativo.`;
 }
 if(sceneSample.error)status=`Vista orbitale non disponibile: ${sceneSample.error}`;
 if(link.lostAt!==null){
  status=`Console non raggiungibile dalle ${new Date(link.lostAt).toLocaleTimeString('it-IT')}: la vista è ferma a quell’istante. Un job in corso prosegue sul worker; per riprendere riavviare la console (tools/lab.py start --no-stack).`;
  $('scene-mode-text').textContent='Vista ferma';$('scene-mode').dataset.state='warn';
 }
 $('mission-status').textContent=status;$('mission-status').hidden=!status;
 /* Phase list in the side panel */
 const list=$('mission-steps');list.replaceChildren();list.hidden=!m.steps.length;
 for(const step of m.steps){
  const li=node('li',undefined,`step ${step.status}${step.downtime?' downtime':''}`);
  const time=step.status==='current'&&step.elapsed_s!=null?duration(step.elapsed_s):step.status==='current'&&step.startMs!==null?duration((wall-step.startMs)/1000):step.duration_s!==null?duration(step.duration_s):step.offset_s!==null&&step.key==='completed'?relativeClock(event.trigger_s+step.offset_s,event.trigger_s):'';
  const name=node('span',undefined,'name');name.append(document.createTextNode(step.label));if(step.where)name.append(node('span',step.where,'where'));
  li.append(node('span',undefined,'mark'),name,node('span',time,'time'));list.append(li);
 }
 /* Label on the route */
 const ticks=$('route-ticks');ticks.replaceChildren();
 if(m.steps.length){
  const number=m.current?m.steps.indexOf(m.current)+1:0;
  $('route-meta').textContent=`${m.preview?'Anteprima · ':''}${methodLabel(m.method)} · fase ${number} di ${m.steps.length}${m.attempt>1?' · tentativo '+m.attempt:''}${m.stage==='failed'?' · interrotta':''}`;
  $('route-phase').textContent=m.current?m.current.label:'In attesa del trigger';
  for(const step of m.steps)ticks.append(node('li',undefined,`${step.status}${step.downtime?' downtime':''}`));
  const down=m.downtime||{},box=$('route-downtime');
  if(m.preview){
   const d=m.previewDowntime;box.hidden=d.seconds===null;
   if(d.seconds!==null)box.textContent=`Controller fermo ${d.ended?'per':'da'} ${duration(d.seconds)}`;
  }else{
  box.hidden=!down.startMs;
  if(down.startMs)box.textContent=down.endMs?`Controller fermo per ${duration((down.endMs-down.startMs)/1000)}`:`Controller fermo da ${duration((wall-down.startMs)/1000)}`;
  }
 }else{
  $('route-meta').textContent='Percorso previsto';
  $('route-phase').textContent=`${event.hops} salti laser verso ${event.destination}`;
  $('route-downtime').hidden=true;
 }
 /* Before the trigger the label also says how long until the migration starts */
 const waiting=!m.linkActive;
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
 rebuildPreview(()=>{preview.speed=Number(button.dataset.speed);});
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
 stream.onmessage=message=>{contact(true);try{const event=JSON.parse(message.data);streamEvents.push(event);if(missionRelevant(event))missionEvents.push(event);if(streamEvents.length>800)streamEvents=streamEvents.slice(-400);renderJob();}catch{}};
 stream.addEventListener('end',()=>{stream.close();scheduleRefresh();});
 stream.onerror=()=>{};
}
const POLICY_KEY='console.policy';
function savedPolicy(){try{return localStorage.getItem(POLICY_KEY)||'designed';}catch{return 'designed';}}
function renderPolicy(){
 const select=$('policy-select'),option=select.querySelector('option[value="cost"]'),available=Boolean(profile?.policy_events?.length);
 option.disabled=!available;
 if(!available&&select.value==='cost')select.value='designed';
 const note=$('policy-note');
 if(!available){note.textContent='Politica di costo non disponibile: il catalogo installato non ha i suoi eventi (tools/destination_policy.py).';note.hidden=false;}
 else if(select.value==='cost'){note.textContent='Eventi: '+profile.policy_events.map((event,index)=>`E${index+1} ${event.source} → ${event.destination} (${event.hops} salti)`).join(' · ');note.hidden=false;}
 else note.hidden=true;
}
$('policy-select').value=savedPolicy();
$('policy-select').addEventListener('change',()=>{try{localStorage.setItem(POLICY_KEY,$('policy-select').value);}catch{}renderPolicy();});
async function launch(operation){
 $('verify').disabled=true;$('start').disabled=true;$('launch-error').hidden=true;
 const parameters=operation==='compare_events'&&$('policy-select').value==='cost'?{policy:'cost'}:{};
 try{const job=await api('/jobs',{operation,parameters});notice({functional:'Verifica avviata',compare_events:'Esperimento avviato',recover:'Ripristino avviato'}[operation]+': '+job.job_id);follow(job.job_id);await refresh();
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
 for(const row of comparisons){const option=node('option',`${new Date(row.created_utc).toLocaleString('it-IT')} · ${row.complete?'completato':row.reason==='worker_stopped'?'interrotto':row.reason?'non completato':'in corso'}`);option.value=row.comparison_id;option.selected=row.comparison_id===current;select.append(option);}
 select.hidden=!comparisons.length;
}
$('comparison-select').addEventListener('change',event=>{selectedComparison=event.target.value;renderResults();});
function phaseText(run){
 const s=run.phases?.seconds||{};
 const parts=[['avvio controller','controller_startup'],['ripristino API','api_restore'],['delta','delta_apply'],['arresto sorgente','source_stop'],['verifica','api_verification'],['riconciliazione','queued_topology_apply'],['cutover','cutover']]
  .filter(([,key])=>s[key]!==undefined).map(([label,key])=>`${label} ${duration(s[key])}`);
 return parts.join(' · ')||'fasi non disponibili';
}
const POLICY_NAMES={designed:'eventi progettati',cost:'politica di costo'};
const REASONS={interrupted:'interrotto',worker_stopped:'il processo dell’esperimento si è fermato prima della fine',recovery_required:'serve il ripristino del laboratorio',too_many_failures:'3 prove non riuscite di fila',failed:'prova non riuscita',service_not_verified:'servizio non verificato'};
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
/* Dettagli per evento aperti dall'utente: restano aperti anche quando la sezione viene ricostruita al refresh. */
const openEventDetails=new Set();
function renderDesignResults(comparison,box,status){
 const design=comparison.design||{};
 status.textContent=`${comparison.complete?'':comparison.reason?'Non completato: '+(REASONS[comparison.reason]||comparison.reason)+' · ':'In corso · '}${comparison.completed_runs} di ${comparison.run_total} prove${comparison.failed_runs?`, ${comparison.failed_runs} non ${comparison.failed_runs===1?'riuscita':'riuscite'}`:''} · ${design.replicas} repliche per evento e modalità · ${POLICY_NAMES[design.destination_policy||'designed']} · ${comparison.rate_bps/1e9} Gbit/s`;
 box.append(table(['Evento','Percorso','Salti','Destinazione','Hot · mediana e quartili','Cold · mediana e quartili','Cold − Hot · mediana e IC 95 %','Coppie'],
  comparison.events.map(row=>{const s=row.statistics?.controller_downtime_s;return [`E${row.index}`,`${row.source} → ${row.destination}`,String(row.hops),row.other_plane?'altro piano':'stesso piano',
   spread(s?.hot),spread(s?.cold),interval(s?.cold_minus_hot),String(s?.cold_minus_hot?.n??0)];})));
 for(const row of comparison.events){
  const key=`${comparison.comparison_id}:${row.index}`;
  const card=node('details',undefined,'event-detail'),summary=node('summary');
  card.open=openEventDetails.has(key);
  card.addEventListener('toggle',()=>{if(card.open)openEventDetails.add(key);else openEventDetails.delete(key);});
  summary.append(node('span',`E${row.index} · ${row.source} → ${row.destination}`,'event-name'),node('span',`${row.hops} salti · ${row.other_plane?'altro piano':'stesso piano'} · ${clock(row.trigger_s)}${row.replaces_designed_entry?` · sostituisce ${row.designed_event_id}`:''}`,'small muted'));
  card.append(summary);
  const rows=[...row.replicas].sort((a,b)=>a.replica-b.replica).map(entry=>{
   const hot=entry.runs.hot,cold=entry.runs.cold;
   const outcome=[hot,cold].every(run=>run&&run.success)?'riuscite':[hot,cold].map(run=>run?(run.success?'':methodLabel(run.method)+' non riuscita'):'').filter(Boolean).join(', ')||'incompleta';
   return [String(entry.replica),duration(hot?.controller_downtime_s),duration(cold?.controller_downtime_s),
    duration(entry.cold_minus_hot?.controller_downtime_s),duration(hot?.total_operation_s),duration(cold?.total_operation_s),outcome];
  });
  card.append(table(['Replica','Downtime controller Hot','Downtime controller Cold','Cold − Hot (downtime)','Durata migrazione Hot','Durata migrazione Cold','Esito'],rows));
  box.append(card);
 }
}
function renderResults(){
 renderComparisonSelect();
 const box=$('results'),status=$('results-status');box.replaceChildren();
 const comparison=comparisons.find(row=>row.comparison_id===selectedComparison)||comparisons[0];
 if(!comparison){status.textContent='Nessun esperimento registrato.';}
 else{
  if(comparison.schema_version>=2){renderDesignResults(comparison,box,status);renderDownloads(comparison);return;}
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
  renderComponents();renderLatest();renderJob();renderResults();renderPreviewSources();
 }catch(error){$('health').textContent='Console non collegata: '+error.message;$('health').dataset.state='error';}
}
async function loadProfile(){
 try{const {profiles}=await api('/scenario-profiles');profile=profiles.find(row=>row.installed&&row.summary)||profiles.find(row=>row.summary)||null;}catch{profile=null;}
 preview.script=null;renderProfile();renderPolicy();
 if(!profile)orbitLoader('error','Nessuno scenario installato: la vista orbitale resta vuota.');
}
document.addEventListener('DOMContentLoaded',async()=>{
 showPage();
 if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){$('orbit-loader').querySelector('svg').pauseAnimations?.();preview.speed=1;document.querySelectorAll('#preview-speed button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.speed==='1')));}
 scene=createOrbitScene($('orbit'));requestAnimationFrame(frame);
 try{token=(await api('/session')).token;}catch(error){notice('Sessione locale non disponibile: '+error.message,true);return;}
 await loadProfile();await refresh();setInterval(refresh,5000);setInterval(renderJob,1000);
});
