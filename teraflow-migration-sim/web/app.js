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
 catch{contact(false);throw new Error('console unreachable');}
 contact(true);
 const data=await response.json();if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);return data;
}
const yesNo=value=>value===true?'yes':value===false?'no':'—';

/* ---------- pages ---------- */
/* The console opens on the laboratory page; old #experiment links land there too. */
const PAGES=['lab','scenario','results'];
function showPage(){
 const requested=location.hash.slice(1),page=PAGES.includes(requested)?requested:'lab';
 for(const name of PAGES)$('page-'+name).hidden=name!==page;
 document.querySelectorAll('.tabs a').forEach(link=>link.setAttribute('aria-current',link.dataset.page===page?'page':'false'));
 /* The journey charts are sized on their panel: draw them again once it is visible */
 if(page==='scenario'&&typeof journey!=='undefined'&&journey)renderJourney();
}
window.addEventListener('hashchange',showPage);

/* ---------- scenario ---------- */
function renderProfile(){
 const box=$('profile');box.replaceChildren();
 if(!profile){box.append(node('p','No scenario profile. Create one with tools/build_scenario.py and install it with tools/install_scenario.py.','small'));return;}
 const s=profile.summary,stats=profile.statistics||{},laser=profile.laser_terminals||{},p=profile.event_parameters||{};
 box.append(node('h2','Installed profile'));
 const rows=[['Profile',profile.profile+(profile.installed?'':' · not installed')],
  ['Planes (RAAN)',s.raan_deg.map(value=>value.toFixed(1)+'°').join(' and ')],
  ['Satellites',`${s.satellites} (${s.per_plane.join(' + ')})`],
  ['Altitude',`${Math.round(s.altitude_km[0])}–${Math.round(s.altitude_km[1])} km`],
  ['Lasers per satellite',`${(laser.intra_plane||0)+(laser.inter_plane||0)}: ${laser.intra_plane} in the plane, ${laser.inter_plane} towards the other plane`],
  ['Link rate',(profile.rate_bps||[]).map(value=>value/1e9+' Gbit/s').join(', ')],
  ['Controller domain',`${s.domain} satellites (${profile.domain.plane_1.length} + ${profile.domain.plane_2.length})`],
  ['Topology changes over the day',stats.path_segments!==undefined?String(Math.max(0,stats.path_segments-1)):'—'],
  ['Controller software',profile.migration?.software_on_board?'on board every satellite: only the state migrates':'transferred at every migration'],
  ['Profile files',profile.integrity==='sizes_match'?'consistent with the manifest':'changed: '+(profile.changed_files||[]).join(', ')]];
 const list=node('dl');for(const [term,value] of rows)list.append(node('dt',term),node('dd',value));box.append(list);
 box.append(node('h2','Experiment events'));
 const table=node('table'),head=node('tr'),body=node('tbody');
 for(const title of ['No.','Migration','Hops','Destination','Time','Source light','Destination light'])head.append(node('th',title));
 const thead=node('thead');thead.append(head);
 profile.selected_events.forEach((event,index)=>{const tr=node('tr');tr.append(node('td',String(index+1)),node('td',`${event.source} → ${event.destination}`),node('td',String(event.hops)),node('td',event.other_plane?'other plane':'same plane'),node('td',clock(event.trigger_s)),node('td',Math.round(event.source_light_remaining_s/60)+' min'),node('td',Math.round(event.destination_light_remaining_s/60)+' min'));body.append(tr);});
 table.append(thead,body);const scroller=node('div',undefined,'table-scroll');scroller.append(table);box.append(scroller);
 if(profile.policy_events?.length){
  box.append(node('h2','Cost-policy events'));
  const policy=node('table'),policyHead=node('tr'),policyBody=node('tbody');
  for(const title of ['No.','Migration','Hops','Destination','Time','Stay','Control latency','Designed event'])policyHead.append(node('th',title));
  const policyThead=node('thead');policyThead.append(policyHead);
  profile.policy_events.forEach((event,index)=>{const tr=node('tr');tr.append(node('td',String(index+1)),node('td',`${event.source} → ${event.destination}`),node('td',String(event.hops)),node('td',event.other_plane?'other plane':'same plane'),node('td',clock(event.trigger_s)),node('td',event.stay_s!=null?Math.round(event.stay_s)+' s':'—'),node('td',event.control_latency_ms!=null?milliseconds(event.control_latency_ms):'—'),node('td',`${event.replaces_designed_entry?'replaces':'same entry as'} ${event.designed_event_id}`));policyBody.append(tr);});
  policy.append(policyThead,policyBody);const policyScroller=node('div',undefined,'table-scroll');policyScroller.append(policy);box.append(policyScroller);
  const minimum=profile.destination_policy?.minimum_stay_s;
  box.append(node('p',`Among the destinations where the controller stays available at least ${percent(profile.destination_policy?.availability_min??0.95)} of the time${minimum?` and stays at least ${Math.round(minimum/60)} min after the migration`:''}, the policy chooses the one with the lowest control latency.`,'small muted'));
 }
 box.append(node('p',`Each event starts ${Math.round(p.trigger_lead_s/60)} min before the source enters shadow. The events cover 1, 5 and 7 laser hops, the last towards the other plane; each hop towards the satellites that follow on the orbit gives the destination about 3 more minutes of sunlight. The destination must stay in sunlight for at least ${Math.round(p.minimum_destination_light_s/60)} min, with a path stable for at least ${Math.round(p.minimum_path_persistence_s/60)} min.`,'small muted'));
 renderPicker();
}
/* Event buttons: the preview goes through all the events by itself; a click jumps to one. */
function renderPicker(){
 const box=$('event-picker');box.replaceChildren();
 if(!profile)return;
 previewEvents().forEach((event,index)=>{const button=node('button',`Event ${index+1}`);button.type='button';button.dataset.index=String(index+1);button.setAttribute('aria-pressed',String(index===0));button.addEventListener('click',()=>jumpToEvent(index+1));box.append(button);});
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
/* Events the preview plays: those of the destination policy when its times come from an experiment
   run with it, otherwise the designed events */
function previewEvents(){return preview.source?.policy==='cost'&&profile?.policy_events?.length?profile.policy_events:profile?.selected_events||[];}
function previewNow(now){
 if(!previewEvents().length)return null;
 if(!preview.script)preview.script=previewScript(previewEvents(),preview.times,preview.speed);
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
const shortDate=iso=>new Date(iso).toLocaleString('en-GB',{dateStyle:'short',timeStyle:'short'});
function previewSources(){
 if(!profile)return [];
 const out=[];
 for(const job of jobs){
  const id=job.progress?.comparison_id;if(!id)continue;
  const policy=job.operation==='compare_events'&&job.parameters?.policy==='cost'?'cost':'designed';
  const ids=jobEvents(job).map(event=>event.event_id);
  if(job.operation==='functional'&&job.status==='completed'){
   const row=verificationRows.find(entry=>entry.comparison_id===id),index=row?ids.indexOf(row.event?.catalog_event_id):-1;
   if(index<0)continue;
   out.push({jobId:job.job_id,kind:'verification',policy,created:job.created_utc,map:{1:index+1},label:`Verification of ${shortDate(job.created_utc)} · event ${index+1}`});
  }else if(job.operation==='compare_events'){
   const row=comparisons.find(entry=>entry.comparison_id===id);if(!row)continue;
   const map={};for(const event of row.events||[]){const index=ids.indexOf(event.catalog_event_id);if(index>=0)map[event.index]=index+1;}
   if(!Object.keys(map).length)continue;
   out.push({jobId:job.job_id,kind:'experiment',policy,created:job.created_utc,map,
    label:`Experiment of ${shortDate(job.created_utc)} · ${POLICY_NAMES[policy]} · ${row.complete?'complete':`${row.completed_runs??0} of ${row.run_total??'?'} runs`}`});
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
  if(!sources.length)select.append(node('option','No run with these events: reference times'));
  select.disabled=!sources.length;
 }
 const source=sources.find(row=>row.jobId===preview.chosen);
 if(source&&preview.source?.jobId!==source.jobId)loadPreviewSource(source);
}
$('preview-source').addEventListener('change',event=>{preview.chosen=event.target.value;renderPreviewSources();lastPanel=0;});
/* Phase times of one job, read once from its event stream and kept for the session. */
function loadPreviewSource(source){
 const use=times=>{
  if(preview.chosen===source.jobId){
   /* Another set of events (designed or policy): the preview starts again from the first one */
   const changes=(preview.source?.policy||'designed')!==source.policy;
   if(changes){preview.times=times;preview.source=source;preview.script=null;preview.startMs=Date.now();sceneSample.eventId=null;renderPicker();}
   else rebuildPreview(()=>{preview.times=times;preview.source=source;});
  }
  lastPanel=0;};
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
 if(preview.loading)return 'Reading the times of the chosen run…';
 if(m.origin.measured)return `Times: ${source.kind} of ${shortDate(source.created)} · event ${m.eventIndex} · ${method}${m.origin.replica?` · replica ${m.origin.replica}`:''}${m.origin.attempt>1?` · attempt ${m.origin.attempt}`:''}`;
 return source?`Reference times: no successful run of event ${m.eventIndex} in ${method} in this ${source.kind}`:'Reference times from a verification of 8 November 2026';
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
 if(sceneSample.eventId!==view.event.event_id){if(sceneSample.error)orbitLoader('error','Orbit view unavailable: '+sceneSample.error);return;}
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
 $('scene-mode-text').textContent=view.live?'Live':`Preview ×${preview.speed}`;
 $('scene-mode').dataset.state=view.live?'live':'idle';
 $('mission-title').textContent=`Event ${m.eventIndex} of ${m.eventTotal}`;
 $('mission-method').textContent=methodLabel(m.method)||'';
 document.querySelectorAll('#event-picker button').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.index)===m.eventIndex)));
 const run=view.live&&m.run&&m.run.position?m.run:null;
 /* Live: which run of the job; preview: which verification or experiment the times come from */
 $('mission-run').hidden=!run&&!m.preview;
 if(run)$('mission-run').textContent=`Run ${run.position} of ${run.total} · ${run.warmup?'warm-up, excluded from the results':'replica '+run.replica+' of '+run.replicas}`;
 else if(m.preview)$('mission-run').textContent=previewOrigin(m);
 $('event-picker').hidden=view.live;$('preview-speed').hidden=view.live;$('preview-source-box').hidden=view.live;
 $('mission-clock').textContent=relativeClock(view.orbital,event.trigger_s);
 $('mission-start').textContent=migrationCountdown(view);$('mission-time').textContent=clock(view.orbital);
 const shadowAt=event.source_shadow_entry_s??(event.trigger_s+event.source_light_remaining_s);
 $('mission-shadow').textContent=view.orbital<shadowAt?`in ${minutes(shadowAt-view.orbital)}`:'source in shadow';
 $('mission-hops').textContent=String(event.hops);
 /* The route, satellite by satellite: who hosts the controller, who relays, who receives */
 const path=event.path||[event.source,event.destination],host=m.controller,hops=$('mission-path');
 hops.replaceChildren();hops.classList.toggle('talking',Boolean(m.communicating));
 path.forEach((id,position)=>{
  const role=id===host?'host':position===path.length-1?'target':'relay',li=node('li',undefined,role);
  li.title=role==='host'?'Controller':role==='target'?'Destination':'Relay';li.append(node('span',String(id)));hops.append(li);
 });
 let status='';
 if(m.preview){
  status=`${m.stage==='completed'?`Migration complete: the controller is now on ${event.destination}. `:''}Preview, no job running: ${preview.source?.policy==='cost'?'events chosen by the cost policy, ':''}each event in Hot and then in Cold, with the times of the run shown above; choose the source in the “Times from” menu. The shortest phases are slowed down to make them visible.`;
 }
 else if(m.stage==='waiting'||m.stage==='preparing')status=`Preparing the laboratory${m.preparation?': '+m.preparation.toLowerCase():''}. The orbit is held at T−30 s.`;
 else if(m.stage==='countdown')status='Laboratory ready: the orbit advances towards the trigger.';
 else if(m.stage==='completed')status=orbitRunning(m)?'Migration complete: the service stays under observation for 30 s.':'Run finished.';
 if(view.live&&m.failure){
  const reason=/interrupted by user/i.test(m.failure.reason)?'stop requested by the user':m.failure.reason||'cause not given';
  if(m.stage==='failed')status=`Run stopped${m.current?' during “'+m.current.label+'”':''}: ${reason}.${m.recoveryRequired?' The laboratory needs recovery.':m.cleanup?' '+m.cleanup+'.':''}`;
  else status=`Attempt ${m.failure.attempt||1} failed: ${reason}. ${m.rolledBack?'The source took back control; ':''}the path is being realigned for a new attempt.`;
 }
 if(sceneSample.error)status=`Orbit view unavailable: ${sceneSample.error}`;
 if(link.lostAt!==null){
  status=`Console unreachable since ${new Date(link.lostAt).toLocaleTimeString('en-GB')}: the view is held at that instant. A running job goes on in the worker; to resume, restart the console (tools/lab.py start --no-stack).`;
  $('scene-mode-text').textContent='View held';$('scene-mode').dataset.state='warn';
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
  $('route-meta').textContent=`${m.preview?'Preview · ':''}${methodLabel(m.method)} · phase ${number} of ${m.steps.length}${m.attempt>1?' · attempt '+m.attempt:''}${m.stage==='failed'?' · stopped':''}`;
  $('route-phase').textContent=m.current?m.current.label:'Waiting for the trigger';
  for(const step of m.steps)ticks.append(node('li',undefined,`${step.status}${step.downtime?' downtime':''}`));
  const down=m.downtime||{},box=$('route-downtime');
  if(m.preview){
   const d=m.previewDowntime;box.hidden=d.seconds===null;
   if(d.seconds!==null)box.textContent=`Controller down for ${duration(d.seconds)}${d.ended?'':' so far'}`;
  }else{
  box.hidden=!down.startMs;
  if(down.startMs)box.textContent=down.endMs?`Controller down for ${duration((down.endMs-down.startMs)/1000)}`:`Controller down for ${duration((wall-down.startMs)/1000)} so far`;
  }
 }else{
  $('route-meta').textContent='Planned path';
  $('route-phase').textContent=`${event.hops} laser hops to ${event.destination}`;
  $('route-downtime').hidden=true;
 }
 /* Before the trigger the label also says how long until the migration starts */
 const waiting=!m.linkActive;
 $('route-countdown').hidden=!waiting;if(waiting)$('route-countdown').textContent=`Migration ${migrationCountdown(view)}`;
}
/* Time to the migration: the trigger fires at the event's orbital instant. During the
   preparation the orbit is held, so the remaining 30 s start after the baseline. */
function migrationCountdown(view){
 const m=view.mission,event=view.event,left=event.trigger_s-view.orbital;
 if(m){
  if(m.stage==='waiting'||m.stage==='preparing')return `after the preparation + ${minutes(ORBIT_LEAD_S)}`;
  if(!m.linkActive)return `in ${minutes(left)}`;
  const cutover=m.steps.find(step=>step.key==='cutover');
  if(m.stage==='completed'&&cutover&&cutover.offset_s!==null)return `completed in ${minutes(cutover.offset_s)}`;
  return `under way for ${minutes(-left)}`;
 }
 return left>0?`in ${minutes(left)}`:`started ${minutes(-left)} ago`;
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
 const label=slot.toUpperCase(),role=slot==='sat-a'?'source':'destination';
 let value,level;
 if(row?.reachable)[value,level]=active===slot?['controller active','ok']:['API ready, waiting','ok'];
 else if(active&&active!==slot)[value,level]=slot==='sat-a'?['off after the migration','idle']:['off, waiting','idle'];
 else [value,level]=['off',busy?'warn':'idle'];
 return [label,value,level,role];
}
function componentRows(){
 const c=state?.components||{},busy=Boolean(state?.lock),active=c.p4_proxy?.data?.active||null;
 return [['Mininet',...(c.mininet?.reachable?[`${c.mininet.data?.switch_count??'—'} switches${c.mininet.data?.switches_alive?' active':''}`,'ok']:['unreachable','error'])],
  ['P4 proxy',...(c.p4_proxy?.reachable?(active?['authority on '+active.toUpperCase(),'ok']:['no authority','idle']):['unreachable','error'])],
  controllerRow('sat-a',c.sat_a,active,busy),controllerRow('sat-b',c.sat_b,active,busy),
  ['Scenario',...(state?.scenario?.profile?[state.scenario.events_ready?`${profile?.selected_events?.length??''} events ready`.trim():'events missing',state.scenario.events_ready?'ok':'warn']:['not installed','error'])],
  ['Lock',...(busy?['busy','warn']:['free','ok'])]];
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
 const [text,level]=!(c.mininet?.reachable&&c.p4_proxy?.reachable)?['Unreachable','error']
  :state?.lock?[job?.operation==='recover'?'Recovery in progress':'Job running','busy']
  :!state?.scenario?.events_ready?['Scenario missing','warn']:['Ready','ok'];
 $('lab-state').textContent=text;$('lab-badge').dataset.state=level;
}
const when=value=>value?new Date(value).toLocaleString('en-GB',{dateStyle:'short',timeStyle:'short'}):'';
const mean=values=>{const known=values.filter(Number.isFinite);return known.length===values.length&&known.length?known.reduce((a,b)=>a+b,0)/known.length:null;};
function renderLatest(){
 const verification=verificationRows[0],run=method=>(verification?.runs||[]).find(row=>row.method===method);
 const ok=verification?.complete;
 $('verify-hot').textContent=ok?duration(run('hot')?.controller_downtime_s):'—';
 $('verify-cold').textContent=ok?duration(run('cold')?.controller_downtime_s):'—';
 $('verify-note').textContent=verification?`Latest verification: ${ok?'succeeded':'failed'} on ${when(verification.created_utc)}.`:'No verification recorded.';
 const experiment=comparisons.find(row=>row.complete);
 /* Median over every run of the experiment; schema 1 had one run per event, schema 2 has replicas */
 const values=method=>experiment?experiment.events.flatMap(row=>row.replicas?row.replicas.map(entry=>entry.runs?.[method]?.controller_downtime_s):[row.runs?.[method]?.controller_downtime_s]).filter(Number.isFinite):[];
 const middle=list=>{if(!list.length)return null;const sorted=[...list].sort((a,b)=>a-b),half=Math.floor(sorted.length/2);return sorted.length%2?sorted[half]:(sorted[half-1]+sorted[half])/2;};
 $('start-hot').textContent=experiment?duration(middle(values('hot'))):'—';
 $('start-cold').textContent=experiment?duration(middle(values('cold'))):'—';
 $('start-note').textContent=experiment?`Latest experiment completed on ${when(experiment.created_utc)}, ${values('hot').length+values('cold').length} runs.`:'No experiment completed.';
}
function renderAxis(view){
 const runs=experimentRuns(profile?.selected_events?.length||3,profile?.experiment?.replicas||3,profile?.experiment?.warmup_runs??1);
 const durations=procedureDurations(jobs,runs),scale=axisScale([durations.functional.seconds,durations.compare_events.seconds]);
 const axis=$('axis'),share=seconds=>Math.min(100,seconds/scale.maxSeconds*100).toFixed(2)+'%';
 /* Rebuild only when the durations change, so the bars' entry animation plays once. */
 const key=JSON.stringify([durations,scale.maxSeconds]);
 if(axis.dataset.key!==key){
  axis.dataset.key=key;axis.replaceChildren();
  for(const [operation,label,className] of [['functional','verification','v'],['compare_events','experiment','e']]){
   const item=durations[operation],bar=node('span',undefined,'span '+className);bar.append(node('b',`${label} · ${item.estimated?'about ':''}${hoursMinutes(item.seconds)}${item.estimated?' (estimate, '+item.runs+' runs)':item.measured?'':' (typical)'}`));
   bar.style.width=share(item.seconds);axis.append(bar);
  }
  for(const minutes of scale.ticks){const last=minutes===scale.ticks.at(-1),tick=node('span',String(minutes),last?'tick last':'tick');tick.style.left=share(minutes*60);axis.append(tick);}
  const cursor=node('span',undefined,'cursor');cursor.title='Elapsed time of the running job';axis.append(cursor);
 }
 const cursor=axis.querySelector('.cursor'),running=view?.active&&['functional','compare_events'].includes(view.operation)&&Number.isFinite(view.elapsedSeconds);
 cursor.hidden=!running;if(running)cursor.style.left=share(view.elapsedSeconds);
}
function renderJob(){
 const job=latestLabJob(),comparison=job?.operation==='compare_events'?comparisons.find(row=>!row.complete&&!row.reason)||comparisons[0]:null;
 const view=jobView(state?.lock?job:(job&&!['queued','running'].includes(job.status)?job:null),comparison);
 $('job').dataset.active=String(view.active);
 $('job-heading').textContent=view.active?'Job running':job?'Latest job':'Job';
 $('job-title').textContent=view.active?view.step:view.title;
 $('job-detail').textContent=view.active?view.title+(job?.cancellation_requested?' · stop requested, making the laboratory safe':''):view.detail;
 $('job-clock').hidden=!view.active;$('job-clock').textContent=view.elapsed||'';
 $('stop').hidden=!view.canStop;
 /* The log belongs to a running job; a finished one points to its results. */
 $('job-log').hidden=!view.active;$('job-results').hidden=view.active||!job;
 $('recover').hidden=!(view.needsRecovery||(state?.lock&&state.worker_alive===false));
 const free=state&&!state.lock&&state.scenario?.events_ready;
 $('verify').disabled=!free;$('start').disabled=!free;
 const timelineBox=$('timeline');timelineBox.replaceChildren();
 for(const row of timeline(streamEvents)){const li=node('li');li.append(node('time',row.time),node('span',row.text));if(row.failed)li.className='failed';timelineBox.append(li);}
 if(!streamEvents.length)timelineBox.append(node('li','No events to show.','muted'));
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
 if(!available){note.textContent='Cost policy unavailable: the installed catalogue has none of its events (tools/destination_policy.py).';note.hidden=false;}
 else if(select.value==='cost'){note.textContent='Events: '+profile.policy_events.map((event,index)=>`E${index+1} ${event.source} → ${event.destination} (${event.hops} hops)`).join(' · ');note.hidden=false;}
 else note.hidden=true;
}
$('policy-select').value=savedPolicy();
$('policy-select').addEventListener('change',()=>{try{localStorage.setItem(POLICY_KEY,$('policy-select').value);}catch{}renderPolicy();});
async function launch(operation){
 $('verify').disabled=true;$('start').disabled=true;$('launch-error').hidden=true;
 const parameters=operation==='compare_events'&&$('policy-select').value==='cost'?{policy:'cost'}:{};
 try{const job=await api('/jobs',{operation,parameters});notice({functional:'Verification started',compare_events:'Experiment started',recover:'Recovery started'}[operation]+': '+job.job_id);follow(job.job_id);await refresh();
  /* A verification or an experiment is followed on the orbit view */
  if(operation!=='recover')location.hash='scenario';}
 catch(error){$('launch-error').textContent='Start failed: '+error.message;$('launch-error').hidden=false;await refresh();}
}
$('verify').addEventListener('click',()=>launch('functional'));
$('start').addEventListener('click',()=>launch('compare_events'));
$('recover').addEventListener('click',()=>launch('recover'));
$('stop').addEventListener('click',()=>$('stop-dialog').showModal());
$('stop-dialog').addEventListener('close',async()=>{
 if($('stop-dialog').returnValue!=='stop')return;
 const job=activeJob();if(!job)return;
 try{await api('/jobs/'+job.job_id+'/stop',{});notice('Stop requested: making the laboratory safe.');}
 catch(error){notice('Stop failed: '+error.message,true);}
 scheduleRefresh();
});

/* ---------- results ---------- */
function renderComparisonSelect(){
 const select=$('comparison-select'),current=selectedComparison||comparisons[0]?.comparison_id||'';
 select.replaceChildren();
 for(const row of comparisons){const option=node('option',`${new Date(row.created_utc).toLocaleString('en-GB')} · ${POLICY_NAMES[row.design?.destination_policy||'designed']} · ${row.complete?'complete':row.reason==='worker_stopped'?'stopped':row.reason?'not complete':'in progress'}`);option.value=row.comparison_id;option.selected=row.comparison_id===current;select.append(option);}
 select.hidden=!comparisons.length;
}
$('comparison-select').addEventListener('change',event=>{selectedComparison=event.target.value;renderResults();});
function phaseText(run){
 const s=run.phases?.seconds||{};
 const parts=[['controller startup','controller_startup'],['API restore','api_restore'],['delta','delta_apply'],['source stop','source_stop'],['verification','api_verification'],['reconciliation','queued_topology_apply'],['cutover','cutover']]
  .filter(([,key])=>s[key]!==undefined).map(([label,key])=>`${label} ${duration(s[key])}`);
 return parts.join(' · ')||'phases unavailable';
}
const POLICY_NAMES={designed:'designed events',cost:'cost policy'};
const REASONS={interrupted:'stopped',worker_stopped:'the experiment process stopped before the end',recovery_required:'the laboratory needs recovery',too_many_failures:'3 failed runs in a row',failed:'run failed',service_not_verified:'service not verified'};
const spread=stat=>stat&&stat.n?`${duration(stat.median)}${stat.n>1?` · ${duration(stat.q1)}–${duration(stat.q3)}`:''}`:'—';
const interval=stat=>stat&&stat.n?`${duration(stat.median)}${stat.ci95?` · CI ${duration(stat.ci95[0])}–${duration(stat.ci95[1])}`:''}`:'—';
function table(headers,rows,rowClass){
 const element=node('table'),thead=node('thead'),head=node('tr'),body=node('tbody');
 for(const title of headers)head.append(node('th',title));
 thead.append(head);
 for(const cells of rows){const tr=node('tr',undefined,rowClass?rowClass(cells):undefined);cells.forEach((cell,index)=>tr.append(node(index===0?'th':'td',cell)));body.append(tr);}
 element.append(thead,body);const scroller=node('div',undefined,'table-scroll');scroller.append(element);return scroller;
}
/* The destination policy the experiment ran with: its rule, its parameters and, per event, what it chose */
const percent=value=>`${(value*100).toLocaleString('en-GB',{maximumFractionDigits:1})}%`;
const milliseconds=value=>`${value.toLocaleString('en-GB',{maximumFractionDigits:1})} ms`;
function policySummary(comparison){
 const design=comparison.design||{},policy=design.destination_policy||'designed',parameters=design.destination_policy_parameters;
 const section=node('section',undefined,'policy-summary');
 section.append(node('h3',`Destination policy: ${POLICY_NAMES[policy]||policy}`));
 if(policy!=='cost'||!parameters){
  section.append(node('p','Destinations fixed by the catalogue of designed events.','small muted'));
  return section;
 }
 const mode=parameters.selection_mode||'hot',source=parameters.downtime_source||{};
 section.append(node('p',`A destination is admissible if its ${methodLabel(mode)} availability is at least ${percent(parameters.availability_min)}: downtime ${duration(parameters.downtime_s?.[mode])} over the stay counted from the end of the longest migration (${duration(Math.max(...Object.values(parameters.duration_s||{0:0})))})${parameters.minimum_stay_s?`, and a stay of at least ${duration(parameters.minimum_stay_s)}`:''}. Among the admissible ones the lowest control latency wins, then fewer hops, then the lower NORAD id.`,'small'));
 if(source.experiment)section.append(node('p',`Times measured in ${source.experiment.slice(0,15)}…: Hot ${duration(parameters.downtime_s?.hot)} downtime and ${duration(parameters.duration_s?.hot)} duration, Cold ${duration(parameters.downtime_s?.cold)} and ${duration(parameters.duration_s?.cold)}.`,'small muted'));
 const designed=Object.fromEntries((profile?.selected_events||[]).map(event=>[event.event_id,event]));
 section.append(table(['Event','Policy choice','Designed event','Stay',`Expected ${methodLabel(mode)} availability`,'Control latency'],
  comparison.events.map(row=>{
   const original=designed[row.designed_event_id],stay=row.stay_s,downtime=parameters.downtime_s?.[mode];
   const was=original?`${row.designed_event_id} (${original.source} → ${original.destination}, ${original.hops} ${original.hops===1?'hop':'hops'})`:row.designed_event_id||'—';
   return [`E${row.index}`,`${row.source} → ${row.destination} · ${row.hops} hops`,row.replaces_designed_entry?`replaces ${was}`:`same shadow entry as ${was}`,
    stay?duration(stay):'—',stay&&downtime!==undefined?percent(1-downtime/stay):'—',row.control_latency_ms!==undefined?milliseconds(row.control_latency_ms):'—'];
  })));
 return section;
}
/* Schema 2: replicas per event. Overview first, then each event with its replicas. */
/* Per-event details opened by the user stay open when the section is rebuilt on refresh. */
const openEventDetails=new Set();
function renderDesignResults(comparison,box,status){
 const design=comparison.design||{};
 status.textContent=`${comparison.complete?'':comparison.reason?'Not complete: '+(REASONS[comparison.reason]||comparison.reason)+' · ':'In progress · '}${comparison.completed_runs} of ${comparison.run_total} runs${comparison.failed_runs?`, ${comparison.failed_runs} failed`:''} · ${design.replicas} replicas per event and mode · ${POLICY_NAMES[design.destination_policy||'designed']} · ${comparison.rate_bps/1e9} Gbit/s`;
 box.append(policySummary(comparison));
 box.append(table(['Event','Path','Hops','Destination','Hot · median and quartiles','Cold · median and quartiles','Cold − Hot · median and 95% CI','Pairs'],
  comparison.events.map(row=>{const s=row.statistics?.controller_downtime_s;return [`E${row.index}`,`${row.source} → ${row.destination}`,String(row.hops),row.other_plane?'other plane':'same plane',
   spread(s?.hot),spread(s?.cold),interval(s?.cold_minus_hot),String(s?.cold_minus_hot?.n??0)];})));
 for(const row of comparison.events){
  const key=`${comparison.comparison_id}:${row.index}`;
  const card=node('details',undefined,'event-detail'),summary=node('summary');
  card.open=openEventDetails.has(key);
  card.addEventListener('toggle',()=>{if(card.open)openEventDetails.add(key);else openEventDetails.delete(key);});
  summary.append(node('span',`E${row.index} · ${row.source} → ${row.destination}`,'event-name'),node('span',`${row.hops} hops · ${row.other_plane?'other plane':'same plane'} · ${clock(row.trigger_s)}${row.replaces_designed_entry?` · replaces ${row.designed_event_id}`:''}`,'small muted'));
  card.append(summary);
  const rows=[...row.replicas].sort((a,b)=>a.replica-b.replica).map(entry=>{
   const hot=entry.runs.hot,cold=entry.runs.cold;
   const outcome=[hot,cold].every(run=>run&&run.success)?'succeeded':[hot,cold].map(run=>run?(run.success?'':methodLabel(run.method)+' failed'):'').filter(Boolean).join(', ')||'incomplete';
   return [String(entry.replica),duration(hot?.controller_downtime_s),duration(cold?.controller_downtime_s),
    duration(entry.cold_minus_hot?.controller_downtime_s),duration(hot?.total_operation_s),duration(cold?.total_operation_s),outcome];
  });
  card.append(table(['Replica','Controller downtime Hot','Controller downtime Cold','Cold − Hot (downtime)','Migration duration Hot','Migration duration Cold','Outcome'],rows));
  box.append(card);
 }
}
function renderResults(){
 renderComparisonSelect();
 const box=$('results'),status=$('results-status');box.replaceChildren();
 const comparison=comparisons.find(row=>row.comparison_id===selectedComparison)||comparisons[0];
 if(!comparison){status.textContent='No experiment recorded.';}
 else{
  if(comparison.schema_version>=2){renderDesignResults(comparison,box,status);renderDownloads(comparison);return;}
  status.textContent=`${comparison.complete?'Complete':comparison.reason?'Not complete: '+comparison.reason:'In progress'} · ${comparison.rate_bps/1e9} Gbit/s · ${comparison.software_on_board?'only the state migrates':'with image transfer'} · one replica per event and mode, values per event.`;
  for(const row of comparison.events){
   const card=node('article',undefined,'event-card');
   card.append(node('h3',`Event ${row.index}: ${row.source} → ${row.destination} · ${row.hops} hops · ${clock(row.trigger_s)} · order ${row.order.map(methodLabel).join(' → ')}`));
   const table=node('table'),thead=node('thead'),head=node('tr'),body=node('tbody');
   for(const title of ['','Controller downtime','Duration','Lost pings','Before shadow','Path valid','Outcome'])head.append(node('th',title));
   thead.append(head);
   for(const method of ['hot','cold']){
    const run=row.runs[method],tr=node('tr');tr.append(node('th',methodLabel(method)));
    if(!run){for(let i=0;i<6;i++)tr.append(node('td','—'));body.append(tr);continue;}
    tr.append(node('td',duration(run.controller_downtime_s)),node('td',duration(run.total_operation_s)),
     node('td',run.lost_pings===null||run.lost_pings===undefined?'not measured':`${run.lost_pings} of ${run.observed_pings}`),
     node('td',yesNo(run.feasibility?.fits_before_shadow)),node('td',yesNo(run.feasibility?.multi_hop_path_whole_operation)),
     node('td',run.success?'succeeded':(run.outcome||'failed')));
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
 const names={'metadata.json':'Experiment results (JSON)','summary.csv':'Per-migration table (CSV)'};
 const files=artifacts.filter(item=>prefixes.some(prefix=>item.label.startsWith(prefix))||item.label==='results/functional-gate.json');
 for(const file of files){const li=node('li'),name=file.label.split('/').pop(),link=node('a',names[name]||(name==='functional-gate.json'?'Latest verification (JSON)':name));link.href=file.download_url;link.title=file.label;li.append(link,node('span',Math.ceil(file.bytes/1024)+' kB'));list.append(li);}
 if(!files.length)list.append(node('li','No files available.','muted'));
}

/* ---------- refresh ---------- */
function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(refresh,300);}
async function refresh(){
 try{
  [state,{jobs},{comparisons},{verifications:verificationRows},{artifacts}]=await Promise.all([api('/state'),api('/jobs'),api('/event-comparisons'),api('/verifications'),api('/artifacts')]);
  const c=state.components||{},ready=c.mininet?.reachable&&c.p4_proxy?.reachable;
  $('health').textContent=(ready?'Laboratory reachable':'Laboratory unreachable')+(state.lock?' · job running':'');
  $('health').dataset.state=ready?'ok':'error';
  renderComponents();renderLatest();renderJob();renderResults();renderPreviewSources();
 }catch(error){$('health').textContent='Console not connected: '+error.message;$('health').dataset.state='error';}
}
/* ---------- the controller over the day (model) ----------
   From tools/sliding_domain.py: the cost policy follows the controller from one shadow entry to
   the next, in the laboratory's fixed domain or in a domain rebuilt around it. Three charts share
   the time of day: which satellite hosts the controller, the control latency and the stay at each
   migration. Every mark has a tooltip; the table lists the same migrations. */
const JOURNEY_KEY='console.journey',SVG='http://www.w3.org/2000/svg';
const STOPS={replay_end:'end of the replay',no_admissible_destination:'no admissible destination'};
let journey=null,journeyChoice='';
try{journeyChoice=localStorage.getItem(JOURNEY_KEY)||'';}catch{}
function svgNode(tag,attributes,text){const element=document.createElementNS(SVG,tag);for(const [key,value] of Object.entries(attributes||{}))element.setAttribute(key,value);if(text!==undefined)element.textContent=text;return element;}
const hourLabel=seconds=>`${String(Math.floor(seconds/3600)).padStart(2,'0')}:00`;
async function loadJourney(){
 try{journey=await api('/controller-journey');}catch{journey={available:false,error:true};}
 renderJourney();
}
/* Name of a domain variant, from its key: reports written before the English console carry Italian labels */
function journeyLabel(row){const following=/^following-(\d+)$/.exec(row.key||'');return row.key==='fixed'?'Fixed domain (laboratory)':following?`Domain following the controller, ${following[1]} satellites behind`:row.label;}
function journeyVariant(){
 const variants=journey?.journeys?.variants||[];
 return variants.find(row=>row.key===journeyChoice)||variants.find(row=>row.key==='following-7')||variants[0]||null;
}
function stepText(step){
 return `${clock(step.trigger_s)} · ${step.source} → ${step.destination} · ${step.hops} hops, ${step.other_plane?'other plane':'same plane'}\n`+
  `Stay ${duration(step.stay_s)} · latency ${milliseconds(step.control_latency_ms)} · ${step.admissible_destinations} admissible destinations`+
  (step.switches_changed?`\n${step.switches_changed} satellites change domain (joining: ${step.joined.join(', ')})`:'');
}
/* One chart: time of day on x, a measure on y, a dot per migration (filled: same plane; ring:
   other plane). `lanes` draws the hosting satellite as a band per plane instead of dots. */
function journeyChart(box,title,steps,{value,unit,lanes,end,stopAt,format},tip){
 const figure=node('figure',undefined,'journey-chart');figure.append(node('figcaption',unit?`${title} (${unit})`:title));box.append(figure);
 const width=Math.max(320,figure.clientWidth||box.clientWidth||720),height=lanes?92:150,left=56,right=12,top=10,bottom=26;
 const plotW=width-left-right,plotH=height-top-bottom,x=seconds=>left+seconds/86400*plotW;
 const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,width:'100%',height,role:'img','aria-label':title});
 for(let hour=0;hour<=24;hour+=3){
  svg.append(svgNode('line',{x1:x(hour*3600),x2:x(hour*3600),y1:top,y2:top+plotH,class:'grid'}));
  svg.append(svgNode('text',{x:x(hour*3600),y:height-6,'text-anchor':hour===0?'start':hour===24?'end':'middle',class:'tick'},hourLabel(hour*3600)));
 }
 let y;
 if(lanes){
  y=plane=>top+(plane===0?plotH*.25:plotH*.75);
  ['Plane 1','Plane 2'].forEach((label,plane)=>svg.append(svgNode('text',{x:left-8,y:y(plane)+4,'text-anchor':'end',class:'tick'},label)));
 }else{
  const values=steps.map(value),max=Math.max(...values,1),grain=max>100?200:10,nice=Math.ceil(max/grain)*grain;
  y=v=>top+plotH-v/nice*plotH;
  for(const v of [0,nice/2,nice]){svg.append(svgNode('line',{x1:left,x2:left+plotW,y1:y(v),y2:y(v),class:v===0?'baseline':'grid'}));svg.append(svgNode('text',{x:left-8,y:y(v)+4,'text-anchor':'end',class:'tick'},format(v)));}
   }
 steps.forEach((step,index)=>{
  const cx=x(step.trigger_s);let mark;
  if(lanes){
   /* The controller sits on the destination from this migration to the next one */
   const until=index+1<steps.length?steps[index+1].trigger_s:end;
   const plane=step.destination_plane??0;
   mark=svgNode('rect',{x:cx,y:y(plane)-7,width:Math.max(2,x(until)-cx-2),height:14,rx:2,class:'lane'});
  }else{
   mark=svgNode('circle',{cx,cy:y(value(step)),r:4,class:step.other_plane?'dot ring':'dot'});
  }
  const hit=lanes?mark:svgNode('circle',{cx,cy:mark.getAttribute('cy'),r:10,class:'hit'});
  hit.addEventListener('pointerenter',event=>tip(event,stepText(step)));hit.addEventListener('pointermove',event=>tip(event,stepText(step)));
  hit.addEventListener('pointerleave',()=>tip(null));
  svg.append(mark);if(hit!==mark)svg.append(hit);
 });
 if(stopAt!==null){svg.append(svgNode('line',{x1:x(stopAt),x2:x(stopAt),y1:top,y2:top+plotH,class:'stop'}));}
 figure.append(svg);
}
function renderJourney(){
 const box=$('journey');if(!box)return;box.replaceChildren();
 box.append(node('h2','The controller over time'));
 box.append(node('p','Analysis of the orbital model, not of the laboratory: the cost policy decides at every shadow entry of the satellite hosting the controller and follows it for the whole day, with the fixed domain of the laboratory or with a domain rebuilt around the controller at every migration.','small muted'));
 if(!journey?.available||!journey.journeys){box.append(node('p',journey?.error?'Analysis unreadable.':'Analysis not run yet: tools/sliding_domain.py.','small'));return;}
 if(journey.stale)box.append(node('p','The catalogue changed after the analysis: run tools/sliding_domain.py again.','small error'));
 const variant=journeyVariant(),head=node('div',undefined,'journey-head'),label=node('label',undefined,'select'),select=node('select');
 label.append('Domain ',select);
 for(const row of journey.journeys.variants){const option=node('option',`${journeyLabel(row)} · ${row.summary.migrations} ${row.summary.migrations===1?'migration':'migrations'}`);option.value=row.key;option.selected=row.key===variant?.key;select.append(option);}
 select.addEventListener('change',()=>{journeyChoice=select.value;try{localStorage.setItem(JOURNEY_KEY,journeyChoice);}catch{}renderJourney();});
 const start=journey.journeys.start,policy=journey.policy||{};
 head.append(label,node('p',`Start: ${start.source} at ${clock(start.trigger_s)} · Hot availability ≥ ${percent(policy.availability_min??0.95)}${policy.minimum_stay_s?` · stay ≥ ${duration(policy.minimum_stay_s)}`:''}`,'small muted'));
 box.append(head);
 const s=variant.summary,steps=variant.steps;
 const tiles=node('dl',undefined,'journey-tiles');
 const tile=(term,value)=>{const item=node('div');item.append(node('dt',term),node('dd',value));tiles.append(item);};
 tile('Migrations',String(s.migrations));
 tile('End',s.migrations?`${clock(s.first_trigger_s+s.span_s)} · ${STOPS[s.stop]||s.stop}`:STOPS[s.stop]||s.stop);
 tile('One migration every',s.migrations>1?`${Math.round(s.mean_interval_s/60)} min`:'—');
 tile('Mean stay',s.migrations?duration(s.mean_stay_s):'—');
 tile('Mean latency',s.migrations?milliseconds(s.mean_control_latency_ms):'—');
 tile('Satellites changing domain',s.mean_switches_changed!=null?`${Math.round(s.mean_switches_changed)} of ${variant.domain?.length??16} per migration`:'none (fixed domain)');
 box.append(tiles);
 if(!steps.length){box.append(node('p','The policy finds no admissible destination already at the start: with this domain the controller cannot migrate.','small'));return;}
 const charts=node('div',undefined,'journey-charts'),tipBox=node('div',undefined,'chart-tip');tipBox.hidden=true;charts.append(tipBox);box.append(charts);
 const tip=(event,text)=>{if(!event){tipBox.hidden=true;return;}const area=charts.getBoundingClientRect();tipBox.textContent=text;tipBox.hidden=false;
  const x=Math.min(event.clientX-area.left+12,area.width-tipBox.offsetWidth-4);tipBox.style.left=Math.max(0,x)+'px';tipBox.style.top=(event.clientY-area.top+14)+'px';};
 const placed=steps;
 const end=s.first_trigger_s+s.span_s,stopAt=s.stop==='no_admissible_destination'?end:null;
 journeyChart(charts,'Satellite hosting the controller',placed,{lanes:true,end,stopAt},tip);
 journeyChart(charts,'Control latency of the destination',placed,{value:step=>step.control_latency_ms,unit:'ms',format:v=>String(Math.round(v)),stopAt},tip);
 journeyChart(charts,'Stay after the migration',placed,{value:step=>step.stay_s,unit:'s',format:v=>String(Math.round(v)),stopAt},tip);
 const legend=node('p',undefined,'small muted journey-legend');
 legend.append(node('span','●','key'),'destination on the same plane',node('span','○','key'),'on the other plane',node('span','▬','key'),'period in which the controller stays on a satellite of the plane'+(stopAt!==null?' · the dashed line marks where the policy stops':''));
 box.append(legend);
 const details=node('details',undefined,'event-detail'),summary=node('summary');summary.append(node('span','All migrations','event-name'));details.append(summary);
 details.append(table(['Time','Migration','Hops','Plane','Stay','Latency','Admissible','Changing domain'],
  steps.map(step=>[clock(step.trigger_s),`${step.source} → ${step.destination}`,String(step.hops),step.other_plane?'other':'same',duration(step.stay_s),milliseconds(step.control_latency_ms),String(step.admissible_destinations),step.switches_changed==null?'—':String(step.switches_changed)])));
 box.append(details);
}
let journeyWidth=0;
new ResizeObserver(entries=>{const width=Math.round(entries[0].contentRect.width);if(journey&&Math.abs(width-journeyWidth)>40){journeyWidth=width;renderJourney();}}).observe(document.documentElement);

async function loadProfile(){
 try{const {profiles}=await api('/scenario-profiles');profile=profiles.find(row=>row.installed&&row.summary)||profiles.find(row=>row.summary)||null;}catch{profile=null;}
 preview.script=null;renderProfile();renderPolicy();loadJourney();
 if(!profile)orbitLoader('error','No scenario installed: the orbit view stays empty.');
}
document.addEventListener('DOMContentLoaded',async()=>{
 showPage();
 if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){$('orbit-loader').querySelector('svg').pauseAnimations?.();preview.speed=1;document.querySelectorAll('#preview-speed button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.speed==='1')));}
 scene=createOrbitScene($('orbit'));requestAnimationFrame(frame);
 try{token=(await api('/session')).token;}catch(error){notice('Local session unavailable: '+error.message,true);return;}
 await loadProfile();await refresh();setInterval(refresh,5000);setInterval(renderJob,1000);
});
