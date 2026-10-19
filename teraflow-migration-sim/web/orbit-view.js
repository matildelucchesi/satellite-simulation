let orbitalUpdateTimer;
let orbitData=null, selectedSatellite=null, topologyRequest=0, orbitReceivedAt=0, orbitDisconnected=false, orbitStreamDisconnected=false;
const orbitalPhaseLabels={...phaseLabels,...outcomeLabels,unknown:'Stato non disponibile',planned:'Passaggio pianificato',running:'Controller in servizio',recovery_failed:'Recupero non confermato',recovery_required:'Recupero richiesto'};
function stopOrbit(message){
 orbitDisconnected=true;
 $('topology').querySelectorAll('.transferring').forEach(node=>node.classList.remove('transferring'));
 $('topology').querySelectorAll('.source').forEach(node=>node.classList.remove('source'));
 $('orbit-controller').textContent='Stato sconosciuto';
 $('orbit-forwarding').textContent='Dato non aggiornato';
 $('orbit-phase').textContent='Stato non aggiornato';
 $('orbit-freshness').textContent=message;inspectSatellite(selectedSatellite);
}
function resetOrbit(){
 ++topologyRequest;orbitData=null;selectedSatellite=null;orbitReceivedAt=0;
 $('topology').replaceChildren();$('satellite-select').replaceChildren();
 $('satellite-detail').textContent='Seleziona un satellite sulla mappa o nell’elenco.';
 $('orbit-controller').textContent='Non disponibile';$('orbit-migration').textContent='Nessuna';
 $('orbit-forwarding').textContent='Non ancora misurato';$('orbit-phase').textContent='Caricamento…';
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
 const role=!orbitDisconnected&&!view.stale&&!(orbitStreamDisconnected&&view.mode==='live')&&node.norad===view.controller_satellite?'Controller attivo confermato':node.norad===view.target_satellite?'Destinazione · '+(orbitalPhaseLabels[view.phase]||view.phase):node.norad===view.source_satellite?'Sorgente del passaggio':'Nessun ruolo controller confermato';
 $('satellite-detail').textContent=`NORAD ${node.norad} · Piano ${node.plane} · ${node.eclipsed?'In ombra':'Illuminato'} · ${role}`;
}
function drawOrbit(data){
 orbitData=data;
 const graph=$('topology');const focus=graph.contains(document.activeElement)?document.activeElement.dataset.norad:null;
 graph.replaceChildren();
 const view=data.presentation||{}, stale=view.stale||orbitDisconnected||(view.mode==='live'&&orbitStreamDisconnected);
 const defs=svg('defs',{},graph);const marker=svg('marker',{id:'migration-head',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:5,markerHeight:5,orient:'auto-start-reverse'},defs);svg('path',{d:'M 0 0 L 10 5 L 0 10 z',class:'migration-head'},marker);
 const center={x:500,y:310},locations=new Map();
 const point=(angle,plane)=>{const rotation=(plane===1?-24:38)*Math.PI/180;const x=365*Math.cos(angle),y=174*Math.sin(angle);return {x:center.x+x*Math.cos(rotation)-y*Math.sin(rotation),y:center.y+x*Math.sin(rotation)+y*Math.cos(rotation)};};
 for(const plane of [1,2]){
  svg('ellipse',{cx:center.x,cy:center.y,rx:365,ry:174,transform:`rotate(${plane===1?-24:38} 500 310)`,class:'orbit-track'+(plane===2?' secondary':'')},graph);
  svgText(graph,plane===1?90:760,plane===1?88:65,`PIANO ${plane}`,'plane-label');
  const nodes=data.nodes.filter(row=>row.plane===plane).sort((a,b)=>a.phase_rank-b.phase_rank);
  const offset=Number.isFinite(nodes[0]?.orbital_angle_rad)?nodes[0].orbital_angle_rad:0;
  nodes.forEach((node,index)=>{
   const angle=offset+index*2*Math.PI/nodes.length+(plane===2?.25:0);
   // Schematic spacing: separate markers at the projected orbit crossings.
   let best=point(angle,plane),bestDistance=-1;
   for(const shift of [0,.04,-.04,.08,-.08,.12,-.12,.16,-.16,.20,-.20,.24,-.24,.28,-.28]){
    const candidate=point(angle+shift,plane);
    const distance=Math.min(...[...locations.values()].map(other=>Math.hypot(candidate.x-other.x,candidate.y-other.y)));
    if(distance>bestDistance){best=candidate;bestDistance=distance;}
    if(distance>=56)break;
   }
   locations.set(node.norad,best);
  });
 }
 svg('circle',{cx:500,cy:310,r:86,class:'earth'},graph);
 for(const rx of [32,63])svg('ellipse',{cx:500,cy:310,rx,ry:86,class:'earth-grid'},graph);
 for(const ry of [30,61])svg('ellipse',{cx:500,cy:310,rx:86,ry,class:'earth-grid'},graph);
 svgText(graph,500,315,'TERRA','earth-label');
 const key=(a,b)=>[a,b].sort((x,y)=>x-y).join('-');
 const pathEdges=new Set();for(let i=1;i<data.service_path.length;i++)pathEdges.add(key(data.service_path[i-1],data.service_path[i]));
 const links=svg('g',{'aria-label':'Collegamenti geometrici'},graph);
 for(const [a,b] of data.links){const p=locations.get(a),q=locations.get(b);if(!p||!q)continue;const service=pathEdges.has(key(a,b));if(service&&!$('show-service').checked)continue;svg('path',{d:`M ${p.x} ${p.y} L ${q.x} ${q.y}`,class:'edge'+(service?' service':'')},links);}
 const source=locations.get(view.source_satellite),target=locations.get(view.target_satellite);
 if(source&&target&&!['none','failed'].includes(view.migration_status)){
  const dx=target.x-source.x,dy=target.y-source.y,length=Math.hypot(dx,dy)||1;
  const end={x:target.x-dx/length*22,y:target.y-dy/length*22};
  svg('path',{d:`M ${source.x} ${source.y} Q ${(source.x+target.x)/2-dy*.12} ${(source.y+target.y)/2+dx*.12} ${end.x} ${end.y}`,class:'migration-arrow'+(view.migration_status==='completed'?' completed':'')+(view.migration_status==='transferring'&&view.mode==='live'&&!stale?' transferring':''),'marker-end':'url(#migration-head)'},graph);
 }
 const select=$('satellite-select');select.replaceChildren();option(select,'','Seleziona NORAD');
 for(const node of data.nodes){
  const p=locations.get(node.norad);if(!p)continue;
  const active=!stale&&node.norad===view.controller_satellite,destination=!active&&node.norad===view.target_satellite;
  const role=active?'Controller attivo':destination?'Destinazione':node.norad===view.source_satellite?'Sorgente':'';
  const label=`NORAD ${node.norad} · Piano ${node.plane} · ${node.eclipsed?'Ombra':'Luce'}${role?' · '+role:''}`;
  const group=svg('g',{class:'node'+(node.eclipsed?' shadow':'')+(active?' source':'')+(destination?' destination':''),tabindex:0,role:'button','aria-label':label,'aria-pressed':String(node.norad===selectedSatellite),'data-norad':node.norad},graph);
  svg('circle',{cx:p.x,cy:p.y,r:23,class:'selection-ring'},group);
  svg('circle',{cx:p.x,cy:p.y,r:11},group);
  if(node.eclipsed)svg('path',{d:`M ${p.x} ${p.y-7} L ${p.x} ${p.y+7}`,class:'shadow-mark'},group);
  const left=p.x<500,tx=p.x+(left?-20:20),anchor=left?'end':'start';
  const name=svgText(group,tx,p.y-1,String(node.norad));name.setAttribute('text-anchor',anchor);
  if(role){const tag=svgText(group,tx,p.y+14,role.toUpperCase(),'role-label');tag.setAttribute('text-anchor',anchor);}
  const title=svg('title',{},group);title.textContent=label;
  group.addEventListener('click',()=>{document.querySelector('.satellite-inspector').open=true;inspectSatellite(node.norad);});
  group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();document.querySelector('.satellite-inspector').open=true;inspectSatellite(node.norad);}});
  option(select,node.norad,label);
 }
 inspectSatellite(selectedSatellite);
 if(focus)graph.querySelector(`[data-norad="${focus}"]`)?.focus({preventScroll:true});
 $('console-mode').textContent=view.mode==='live'?'LIVE':view.mode==='replay'?'REPLAY':'GEOMETRIA';
 $('orbit-controller').textContent=stale?'Stato sconosciuto':view.controller_satellite?`NORAD ${view.controller_satellite}`:'Nessuno confermato';
 const statuses={none:'Nessuna',planned:'Pianificata',transferring:'Trasferimento',in_progress:'In corso',completed:'Completata',failed:'Fallita'};
 $('orbit-migration').textContent=view.source_satellite&&view.target_satellite?`${view.source_satellite} → ${view.target_satellite}`:statuses[view.migration_status]||'Nessuna';
 $('orbit-phase').textContent=stale?'Dati non aggiornati':(statuses[view.migration_status]||'')+' · '+(orbitalPhaseLabels[view.phase]||view.phase||'In attesa');
 $('orbit-forwarding').textContent=stale?'Dato non aggiornato':view.forwarding_observed===true?'Verificato dalle sonde':view.forwarding_observed===false?'Perdita osservata':'Non ancora misurato';
 $('orbit-freshness').textContent=(stale?'Telemetria non aggiornata · ':view.mode==='replay'?'Dati registrati · ':'')+(view.updated_utc?'Ultima evidenza '+new Date(view.updated_utc).toLocaleString('it-IT'):'Nessuna evidenza del controller disponibile')+' · Il percorso geometrico non conferma il forwarding.';
 $('orbital-time').textContent=`t = ${number(data.orbital_s,0)} s · geometria modellata`;
 $('replay-label').textContent=`t = ${number(data.orbital_s,0)} s · replay dei dati salvati`;
}
async function topology(){
 const request=++topologyRequest;
 try{
  const query=new URLSearchParams();if(selectedRun)query.set('run_id',selectedRun);if(replayTick!==null)query.set('orbital_s',replayTick);
  const data=selectedSimulation?await api('/simulations/'+selectedSimulation+'/topology'+(simulationTick!==null?'?orbital_s='+simulationTick:'')):await api('/topology?'+query);
  if(request!==topologyRequest)return;
  orbitReceivedAt=Date.now();orbitDisconnected=false;drawOrbit(data);renderLiveProgress(data);
 }catch(error){if(request===topologyRequest){stopOrbit('Topologia non disponibile: '+error.message);$('orbital-time').textContent='Geometria non disponibile';}}
}
$('map-zoom').addEventListener('click',()=>{const expanded=$('map-zoom').getAttribute('aria-pressed')!=='true';$('map-zoom').setAttribute('aria-pressed',String(expanded));$('map-zoom').textContent=expanded?'Riduci':'Ingrandisci';$('topology').parentElement.dataset.expanded=String(expanded);});
$('show-service').addEventListener('change',()=>{if(orbitData)drawOrbit(orbitData);});
$('satellite-select').addEventListener('change',()=>inspectSatellite($('satellite-select').value?Number($('satellite-select').value):null));
setInterval(()=>{if(orbitData?.presentation?.mode==='live'&&orbitReceivedAt&&Date.now()-orbitReceivedAt>15000)stopOrbit('Connessione non aggiornata · ultima risposta '+new Date(orbitReceivedAt).toLocaleTimeString('it-IT'));},1000);
