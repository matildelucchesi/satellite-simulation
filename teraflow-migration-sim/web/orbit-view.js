let orbitalUpdateTimer;
let orbitLocations=new Map();
let orbitAnimation=0,orbitAnimationEpoch=0,topologyInFlight=false,topologyQueued=false;
const orbitMotion=()=>!window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let orbitData=null, selectedSatellite=null, topologyRequest=0, orbitReceivedAt=0, orbitDisconnected=false, orbitStreamDisconnected=false;
const orbitalPhaseLabels={...phaseLabels,...outcomeLabels,controller_assigned:'Controller assegnato e verificato',unknown:'Stato non disponibile',planned:'Passaggio pianificato',running:'Controller in servizio',recovery_failed:'Recupero non confermato',recovery_required:'Recupero richiesto'};
const candidateReasons={eligible:'Candidato ammissibile per questo evento',current_controller:'Ospita il controller di riferimento',awaiting_plan:'Score disponibile dopo la preparazione del piano',not_eligible:'Non candidato per questo evento',no_direct_contact:'Nessun collegamento diretto con il controller',destination_in_shadow:'Destinazione in ombra al momento della migrazione',resource_reserve_at_arrival:'Risorse insufficienti all’arrivo',destination_deadline:'Ingresso in ombra prima del completamento',insufficient_contact:'Collegamento troppo breve per completare la migrazione',future_dead_end:'Non permette di completare la sequenza delle migrazioni'};
function candidateLabel(node){return Number.isFinite(node.candidate_score)?`Score ${number(node.candidate_score,1)}`:'Score —';}
function pendingController(view){return !orbitDisconnected&&!(orbitStreamDisconnected&&view.mode==='live')&&['initial','planned'].includes(view.placement_status)?view.assigned_controller_satellite:null;}
function stopOrbit(message){
 cancelAnimationFrame(orbitAnimation);orbitAnimationEpoch=0;
 orbitDisconnected=true;
 $('topology').classList.remove('service-live');
 $('orbit-activity').textContent=message;
 $('topology').querySelectorAll('.transferring').forEach(node=>node.classList.remove('transferring'));
 $('topology').querySelectorAll('.source').forEach(node=>node.classList.remove('source'));
 $('orbit-controller').textContent='Stato sconosciuto';
 $('orbit-forwarding').textContent='Dato non aggiornato';
 $('orbit-phase').textContent='Stato non aggiornato';
 $('orbit-freshness').textContent=message;inspectSatellite(selectedSatellite);
}
function resetOrbit(){
 cancelAnimationFrame(orbitAnimation);orbitAnimationEpoch=0;
 ++topologyRequest;orbitData=null;selectedSatellite=null;orbitReceivedAt=0;
 orbitLocations=new Map();
 $('topology').replaceChildren();$('satellite-select').replaceChildren();
 $('satellite-detail').textContent='Seleziona un satellite sulla mappa o nell’elenco.';
 $('orbit-controller').textContent='Non disponibile';$('orbit-migration').textContent='Nessuna';
 $('orbit-forwarding').textContent='Non ancora misurato';$('orbit-phase').textContent='Caricamento…';
 $('orbit-activity').textContent='In attesa della simulazione';
 $('phase-countdowns').replaceChildren();
}
function inspectSatellite(identifier){
 selectedSatellite=identifier;
 const node=orbitData?.nodes.find(row=>row.norad===identifier);
 $('satellite-select').value=identifier??'';
 $('topology').querySelectorAll('.node').forEach(group=>{
  const selected=Number(group.dataset.norad)===identifier;group.classList.toggle('selected',selected);group.setAttribute('aria-pressed',String(selected));
 });
 if(!node){$('satellite-detail').textContent='Seleziona un satellite sulla mappa o nell’elenco.';return;}
 const view=orbitData.presentation||{};
 if(node.norad===pendingController(view)){$('satellite-detail').textContent=`NORAD ${node.norad} · Piano ${node.plane} · ${node.eclipsed?'In ombra':'Illuminato'} · ${view.mode==='preview'?'Controller iniziale · pronto per la preparazione':'Controller assegnato, verifica iniziale in corso'}`;return;}
 const role=!orbitDisconnected&&!view.stale&&!(orbitStreamDisconnected&&view.mode==='live')&&node.norad===view.controller_satellite?'Controller attivo confermato':node.norad===view.target_satellite?'Destinazione · '+(orbitalPhaseLabels[view.phase]||view.phase):node.norad===view.source_satellite?'Sorgente del passaggio':'Nessun ruolo controller confermato';
 $('satellite-detail').textContent=`NORAD ${node.norad} · Piano ${node.plane} · ${node.eclipsed?'In ombra':'Illuminato'} · ${role}`;
}
function drawOrbit(data){
 cancelAnimationFrame(orbitAnimation);
 const previousData=orbitData,previousLocations=orbitLocations;
 const moving=previousData&&data.orbital_s>previousData.orbital_s&&data.orbital_s-previousData.orbital_s<=10&&data.presentation?.mode==='live'&&!orbitDisconnected;
 orbitData=data;
 const graph=$('topology');graph.setAttribute('aria-label',`Schema interattivo delle orbite e dei ${data.nodes.length} satelliti`);const focus=graph.contains(document.activeElement)?document.activeElement.dataset.norad:null;
 graph.replaceChildren();
 graph.classList.toggle('dense-constellation',data.nodes.length>32);
 $('map-density-note').hidden=data.nodes.length<=32;
 const view=data.presentation||{}, stale=view.stale||orbitDisconnected||(view.mode==='live'&&orbitStreamDisconnected);
 graph.classList.toggle('service-live',view.mode==='live'&&!stale&&view.forwarding_observed===true);
 const defs=svg('defs',{},graph);const marker=svg('marker',{id:'migration-head',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:5,markerHeight:5,orient:'auto-start-reverse'},defs);svg('path',{d:'M 0 0 L 10 5 L 0 10 z',class:'migration-head'},marker);
 const center={x:500,y:310},locations=orbitLayout(data.nodes);
 for(const plane of [1,2]){
  svg('ellipse',{cx:center.x,cy:center.y,rx:365,ry:174,transform:`rotate(${plane===1?-24:38} 500 310)`,class:'orbit-track'+(plane===2?' secondary':'')},graph);
  svgText(graph,plane===1?90:760,plane===1?88:65,`PIANO ${plane}`,'plane-label');
 }
 svg('circle',{cx:500,cy:310,r:86,class:'earth'},graph);
 for(const rx of [32,63])svg('ellipse',{cx:500,cy:310,rx,ry:86,class:'earth-grid'},graph);
 for(const ry of [30,61])svg('ellipse',{cx:500,cy:310,rx:86,ry,class:'earth-grid'},graph);
 svgText(graph,500,315,'TERRA','earth-label');
 const lit=data.nodes.filter(node=>!node.eclipsed).length;
 svgText(graph,28,573,`${lit} IN LUCE · ${data.nodes.length-lit} IN OMBRA`,'illumination-caption');
 svgText(graph,28,596,'Luce / ombra: stato orbitale calcolato per ciascun satellite','illumination-note');
 const key=(a,b)=>[a,b].sort((x,y)=>x-y).join('-');
 const pathEdges=new Set();for(let i=1;i<data.service_path.length;i++)pathEdges.add(key(data.service_path[i-1],data.service_path[i]));
 const links=svg('g',{'aria-label':'Collegamenti geometrici'},graph);
 for(const [a,b] of data.links){const p=locations.get(a),q=locations.get(b);if(!p||!q)continue;const service=pathEdges.has(key(a,b));svg('path',{d:`M ${p.x} ${p.y} L ${q.x} ${q.y}`,'data-a':a,'data-b':b,class:'edge'+(service&&$('show-service').checked?' service':'')},links);}
 const source=locations.get(view.source_satellite),target=locations.get(view.target_satellite);
 if(source&&target&&!['none','failed'].includes(view.migration_status)){
  const dx=target.x-source.x,dy=target.y-source.y,length=Math.hypot(dx,dy)||1;
  const end={x:target.x-dx/length*22,y:target.y-dy/length*22};
  svg('path',{id:'orbital-migration',d:`M ${source.x} ${source.y} Q ${(source.x+target.x)/2-dy*.12} ${(source.y+target.y)/2+dx*.12} ${end.x} ${end.y}`,class:'migration-arrow'+(view.migration_status==='completed'?' completed':'')+(view.migration_status==='transferring'&&view.mode==='live'&&!stale?' transferring':''),'marker-end':'url(#migration-head)'},graph);
 }
 const select=$('satellite-select');select.replaceChildren();option(select,'','Seleziona NORAD');
 for(const node of data.nodes){
  const p=locations.get(node.norad);if(!p)continue;
  const pending=node.norad===pendingController(view);
  const active=pending||(!stale&&node.norad===view.controller_satellite),destination=!active&&node.norad===view.target_satellite;
  const role=pending?(view.mode==='preview'?'Controller iniziale':'Controller · in verifica'):active?'Controller attivo':destination?'Destinazione':node.norad===view.source_satellite?'Sorgente':'';
  const label=`NORAD ${node.norad} · Piano ${node.plane} · ${node.eclipsed?'Ombra':'Luce'}${role?' · '+role:''} · ${candidateLabel(node)}${node.next_controller?' · Prossimo controller':''}`;
  const group=svg('g',{class:'node'+(node.eclipsed?' shadow':'')+(active?' source':'')+(pending&&view.mode!=='preview'?' assignment-pending':'')+(destination?' destination':''),tabindex:0,role:'button','aria-label':label,'aria-pressed':String(node.norad===selectedSatellite),'data-norad':node.norad},graph);
  svg('circle',{cx:p.x,cy:p.y,r:23,class:'selection-ring'},group);
  svg('circle',{cx:p.x,cy:p.y,r:11,class:'satellite-body'},group);
  if(node.next_controller)svg('circle',{cx:p.x,cy:p.y,r:17,class:'next-controller-ring'},group);
  if(active){
   svgText(group,p.x,p.y+4,'C','controller-letter');
  }
  const old=previousLocations.get(node.norad);
  if(moving&&old){const trail=svg('path',{d:`M ${old.x} ${old.y} L ${p.x} ${p.y}`,class:'satellite-trail'},graph);graph.insertBefore(trail,links);}
  const left=p.x<500,tx=p.x+(left?-20:20),anchor=left?'end':'start';
  const name=svgText(group,tx,p.y-1,String(node.norad),'satellite-id');name.setAttribute('text-anchor',anchor);
  if(role){const tag=svgText(group,tx,p.y+14,role.toUpperCase(),'role-label');tag.setAttribute('text-anchor',anchor);}
  svgText(group,p.x,p.y+31,candidateLabel(node),'score-label'+(node.next_controller?' chosen':'')+(Number.isFinite(node.candidate_score)?'':' unavailable'));
  if(node.next_controller)svgText(group,p.x,p.y+45,'PROSSIMO','next-controller-label');
  const title=svg('title',{},group);title.textContent=label+(node.candidate_reason?' · '+(candidateReasons[node.candidate_reason]||node.candidate_reason):'');
  group.addEventListener('click',()=>{document.querySelector('.satellite-inspector').open=true;inspectSatellite(node.norad);});
  group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();document.querySelector('.satellite-inspector').open=true;inspectSatellite(node.norad);}});
  option(select,node.norad,label);
 }
 inspectSatellite(selectedSatellite);
 renderPhaseCountdowns(data,stale);
 orbitLocations=locations;
 const ranking=data.ranking;
 $('ranking-description').textContent=ranking?.available?`Score su 100 del prossimo evento, rispetto al controller su NORAD ${ranking.source_satellite}, previsti al trigger t = ${number(ranking.trigger_s,0)} s. Prossimo: NORAD ${ranking.target_satellite}. La scelta considera anche la fattibilità delle migrazioni successive.`:'Score —: in attesa del piano della prossima migrazione. Il controller attuale non viene valutato come destinazione.';
 if(view.mode==='preview'){
  initialConfiguration=data.initial_configuration;
  $('initial-assignment').textContent=initialConfiguration?`Partenza automatica: NORAD ${initialConfiguration.initial_satellite_id} · tempo orbitale ${initialConfiguration.start_orbital_s} s. Identica per Hot e Cold.`:'Partenza determinata automaticamente dopo la calibrazione.';
  if(state)renderState();
 }
 $('orbit-activity').textContent=pendingController(view)?`Controller assegnato al satellite ${pendingController(view)} · verifica iniziale in corso, clock non ancora avviato`:stale?'Aggiornamenti interrotti · attività non confermata':view.migration_status==='transferring'?`Trasferimento controller ${view.source_satellite} → ${view.target_satellite}`:view.controller_satellite?`Controller su ${view.controller_satellite} · ${view.forwarding_observed===true?'ultima sonda del servizio riuscita':view.forwarding_observed===false?'perdita del servizio osservata':'in attesa delle sonde'}`:'Il satellite del controller viene assegnato automaticamente prima dell’avvio del clock.';
 if(focus)graph.querySelector(`[data-norad="${focus}"]`)?.focus({preventScroll:true});
 $('console-mode').textContent=view.mode==='live'?'Vista orbitale live':view.mode==='replay'?'Vista orbitale replay':'Vista geometrica';
 $('orbit-controller').textContent=pendingController(view)?`NORAD ${pendingController(view)} · in verifica`:stale?'Stato sconosciuto':view.controller_satellite?`NORAD ${view.controller_satellite}`:'Assegnazione prima dell’avvio';
 const statuses={none:'Nessuna',planned:'Pianificata',transferring:'Trasferimento',in_progress:'In corso',completed:'Completata',failed:'Fallita'};
 $('orbit-migration').textContent=view.source_satellite&&view.target_satellite?`${view.source_satellite} → ${view.target_satellite}`:statuses[view.migration_status]||'Nessuna';
 $('orbit-phase').textContent=pendingController(view)?'Verifica iniziale del controller assegnato':stale?'Dati non aggiornati':(statuses[view.migration_status]||'')+' · '+(orbitalPhaseLabels[view.phase]||view.phase||'In attesa');
 $('orbit-forwarding').textContent=stale?'Dato non aggiornato':view.forwarding_observed===true?'Verificato dalle sonde':view.forwarding_observed===false?'Perdita osservata':'Non ancora misurato';
 $('orbit-freshness').textContent=(stale?'Telemetria non aggiornata · ':view.mode==='replay'?'Dati registrati · ':'')+(view.updated_utc?'Ultima evidenza '+new Date(view.updated_utc).toLocaleString('it-IT'):'Nessuna evidenza del controller disponibile')+' · Il percorso geometrico non conferma il forwarding.';
 $('orbital-time').textContent=`t = ${number(data.orbital_s,0)} s · geometria modellata`;
 if(pendingController(view))$('orbit-freshness').textContent='Assegnazione dal piano ammesso · il clock partirà dopo la verifica iniziale del controller.';
 if(view.mode==='preview'){
  $('console-mode').textContent='Vista orbitale iniziale';
  $('orbit-controller').textContent=pendingController(view)?`NORAD ${pendingController(view)} · iniziale`:'Partenza da determinare';
  $('orbit-activity').textContent=pendingController(view)?`Partenza dal satellite ${pendingController(view)} · configurazione ferma fino all’avvio.`:'Il simulatore sceglierà automaticamente la partenza dopo la calibrazione.';
  $('orbit-phase').textContent='In attesa dell’avvio';
  $('orbit-freshness').textContent=pendingController(view)?'Partenza selezionata dal modello · servizio live da verificare.':'Nessun controller iniziale assegnato · clock fermo.';
  $('orbital-time').textContent=`t = ${number(data.orbital_s,0)} s · configurazione iniziale · clock fermo`;
 }
 $('replay-label').textContent=`t = ${number(data.orbital_s,0)} s · replay dei dati salvati`;
 if(data.clock_running&&view.mode==='live'&&!stale&&data.motion_frames?.length){
  const sameClock=orbitAnimationEpoch>0&&previousData?.clock_running&&data.orbital_s>=previousData.orbital_s&&data.orbital_s-previousData.orbital_s<=2;
  orbitAnimationEpoch=sameClock?orbitAnimationEpoch+(data.orbital_s-previousData.orbital_s)*1000:performance.now();
  animateOrbit(data,locations);
 }
}
function renderPhaseCountdowns(data,stale){
 const list=$('phase-countdowns'),scroll=list.scrollTop,focus=list.contains(document.activeElement)?document.activeElement.dataset.norad:null;list.replaceChildren();
 const nodes=[...data.nodes].sort((a,b)=>(a.next_transition_s??Infinity)-(b.next_transition_s??Infinity)||a.norad-b.norad);
 for(const node of (showAllPhases?nodes:nodes.slice(0,3))){
  const row=document.createElement('li'),button=document.createElement('button');
  button.type='button';button.className='phase-row'+(node.eclipsed?' shadow':'')+((!stale&&node.norad===data.presentation?.controller_satellite)||node.norad===pendingController(data.presentation||{})?' controller':'');
  button.dataset.norad=node.norad;
  const name=document.createElement('span');name.className='phase-name';name.textContent=String(node.norad)+(button.classList.contains('controller')?' · C':'');
  const countdown=document.createElement('strong'),label=document.createElement('span');label.className='phase-next';
  const remaining=Number.isFinite(node.next_transition_s)?Math.max(0,node.next_transition_s-data.orbital_s):null;
  countdown.textContent=phaseCountdown(remaining);
  label.textContent=remaining===null?'Nessun cambio nei dati disponibili':`all’ingresso in ${node.eclipsed?'luce':'ombra'}`;
  const track=document.createElement('span');track.className='phase-track';
  const fill=document.createElement('span');
  const duration=node.next_transition_s-node.phase_start_s;
  fill.style.width=remaining!==null&&duration>0?`${Math.max(0,Math.min(100,remaining/duration*100))}%`:'0%';track.append(fill);
  button.append(name,countdown,label,track);button.addEventListener('click',()=>{document.querySelector('.satellite-inspector').open=true;inspectSatellite(node.norad);});
  row.append(button);list.append(row);
 }
 list.scrollTop=scroll;if(focus)list.querySelector(`[data-norad="${focus}"]`)?.focus({preventScroll:true});
}
function phaseCountdown(remaining){if(remaining===null)return '—';const value=Math.max(0,Math.ceil(remaining));return `${Math.floor(value/60)}m ${String(value%60).padStart(2,'0')}s`;}
function orbitLayout(nodes){
 const locations=new Map();
 for(const plane of [1,2]){
  const rows=nodes.filter(node=>node.plane===plane).sort((a,b)=>a.phase_rank-b.phase_rank);
  rows.forEach((node,index)=>{
   const angle=Number.isFinite(node.orbital_angle_rad)?node.orbital_angle_rad:index*2*Math.PI/rows.length;
   let best,bestDistance=-1;
   for(const shift of [0,.04,-.04,.08,-.08,.12,-.12,.16,-.16,.20,-.20,.24,-.24,.28,-.28]){
    const rotation=(plane===1?-24:38)*Math.PI/180,x=365*Math.cos(angle+shift),y=174*Math.sin(angle+shift);
    const candidate={x:500+x*Math.cos(rotation)-y*Math.sin(rotation),y:310+x*Math.sin(rotation)+y*Math.cos(rotation)};
    const distance=Math.min(...[...locations.values()].map(other=>Math.hypot(candidate.x-other.x,candidate.y-other.y)));
    if(distance>bestDistance){best=candidate;bestDistance=distance;}
    if(distance>=56)break;
   }
   locations.set(node.norad,best);
  });
 }
 return locations;
}
function animateOrbit(data,baseLocations){
 const graph=$('topology'),view=data.presentation;
 const frames=[data,...data.motion_frames].map(frame=>({...frame,locations:orbitLayout(frame.nodes)}));
 const last=frames[frames.length-1],groups=[...graph.querySelectorAll('.node')],edges=[...graph.querySelectorAll('.edge')];
 const phaseRows=new Map([...$('phase-countdowns').querySelectorAll('.phase-row')].map(row=>[Number(row.dataset.norad),row]));
 let lastPaint=-Infinity;
 function paint(now){
  if(orbitDisconnected||orbitStreamDisconnected)return;
  if(now-lastPaint<(orbitMotion()?33:1000)){orbitAnimation=requestAnimationFrame(paint);return;}lastPaint=now;
  const tick=Math.min(last.orbital_s,data.orbital_s+Math.max(0,(now-orbitAnimationEpoch)/1000));
  const source=[...frames].reverse().find(frame=>frame.orbital_s<=tick)||data;
  const next=frames.find(frame=>frame.orbital_s>tick)||source;
  const fraction=orbitMotion()&&next!==source?(tick-source.orbital_s)/(next.orbital_s-source.orbital_s):0;
  const locations=new Map();
  for(const node of source.nodes){
   const p=source.locations.get(node.norad),q=next.locations.get(node.norad)||p;
   locations.set(node.norad,{x:p.x+(q.x-p.x)*fraction,y:p.y+(q.y-p.y)*fraction});
   const row=phaseRows.get(node.norad);if(!row)continue;
   const remaining=Number.isFinite(node.next_transition_s)?Math.max(0,node.next_transition_s-tick):null;
   row.querySelector('strong').textContent=phaseCountdown(remaining);
   row.querySelector('.phase-next').textContent=remaining===null?'Nessun cambio nei dati disponibili':`all’ingresso in ${node.eclipsed?'luce':'ombra'}`;
   row.classList.toggle('shadow',node.eclipsed);
   const duration=node.next_transition_s-node.phase_start_s;
   row.querySelector('.phase-track>span').style.width=remaining!==null&&duration>0?`${Math.max(0,Math.min(100,remaining/duration*100))}%`:'0%';
  }
  const shadow=new Set(source.nodes.filter(node=>node.eclipsed).map(node=>node.norad));
  for(const group of groups){const id=Number(group.dataset.norad),p=locations.get(id),base=baseLocations.get(id);if(!p||!base)continue;group.setAttribute('transform',`translate(${p.x-base.x} ${p.y-base.y})`);group.classList.toggle('shadow',shadow.has(id));}
  for(const edge of edges){const p=locations.get(Number(edge.dataset.a)),q=locations.get(Number(edge.dataset.b));if(p&&q)edge.setAttribute('d',`M ${p.x} ${p.y} L ${q.x} ${q.y}`);}
  const arrow=$('orbital-migration'),sourcePoint=locations.get(view.source_satellite),targetPoint=locations.get(view.target_satellite);
  if(arrow&&sourcePoint&&targetPoint){const dx=targetPoint.x-sourcePoint.x,dy=targetPoint.y-sourcePoint.y,length=Math.hypot(dx,dy)||1;arrow.setAttribute('d',`M ${sourcePoint.x} ${sourcePoint.y} Q ${(sourcePoint.x+targetPoint.x)/2-dy*.12} ${(sourcePoint.y+targetPoint.y)/2+dx*.12} ${targetPoint.x-dx/length*22} ${targetPoint.y-dy/length*22}`);}
  $('orbital-time').textContent=`t = ${number(tick,1)} s · LIVE · tempo reale${tick===last.orbital_s?' · in attesa di aggiornamento':''}`;
  orbitAnimation=requestAnimationFrame(paint);
 }
 paint(performance.now());
}
async function topology(queueLatest=false){
 if(topologyInFlight){if(queueLatest)topologyQueued=true;return;}topologyInFlight=true;
 const request=++topologyRequest;
 try{
  const query=new URLSearchParams();if(selectedRun)query.set('run_id',selectedRun);if(replayTick!==null)query.set('orbital_s',replayTick);
  const data=selectedSimulation?await api('/simulations/'+selectedSimulation+'/topology'+(simulationTick!==null?'?orbital_s='+simulationTick:'')):selectedRun||replayTick!==null?await api('/topology?'+query):await api('/initial-topology'+(initialConfigurationRequest?'?'+new URLSearchParams(initialConfigurationRequest):''));
  if(request!==topologyRequest)return;
  orbitReceivedAt=Date.now();orbitDisconnected=false;drawOrbit(data);renderLiveProgress(data);
 }catch(error){if(request===topologyRequest){stopOrbit('Topologia non disponibile: '+error.message);$('orbital-time').textContent='Geometria non disponibile';if(!selectedSimulation){initialConfiguration=null;$('initial-assignment').textContent='Partenza non valida: '+error.message;if(state)renderState();}}}
 finally{topologyInFlight=false;if(topologyQueued){topologyQueued=false;void topology();}}
}
$('map-zoom').addEventListener('click',()=>{const expanded=$('map-zoom').getAttribute('aria-pressed')!=='true';$('map-zoom').setAttribute('aria-pressed',String(expanded));$('map-zoom').textContent=expanded?'Riduci':'Ingrandisci';$('topology').parentElement.dataset.expanded=String(expanded);});
$('show-initial').addEventListener('click',()=>{initialViewRequested=true;selectSimulation('',false);simulationTick=null;topology();});
$('show-service').addEventListener('change',()=>{if(orbitData)drawOrbit(orbitData);});
$('satellite-select').addEventListener('change',()=>inspectSatellite($('satellite-select').value?Number($('satellite-select').value):null));
setInterval(()=>{if(orbitData?.presentation?.mode==='live'&&orbitReceivedAt&&Date.now()-orbitReceivedAt>15000)stopOrbit('Connessione non aggiornata · ultima risposta '+new Date(orbitReceivedAt).toLocaleTimeString('it-IT'));},1000);
setInterval(()=>{const session=simulations.find(row=>row.simulation_id===selectedSimulation);if(selectedSimulation&&simulationTick===null&&session&&session.phase!=='finished')topology();},1000);

let showAllPhases=false;
$('show-all-phases').addEventListener('click',()=>{showAllPhases=!showAllPhases;$('show-all-phases').setAttribute('aria-expanded',String(showAllPhases));$('show-all-phases').textContent=showAllPhases?'Mostra solo i 3 più vicini':`Mostra tutti i ${orbitData?.nodes?.length??''} satelliti`;if(orbitData)renderPhaseCountdowns(orbitData,false);});
