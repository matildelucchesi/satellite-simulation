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
function showPage(){
 const page=['scenario','experiment','results'].includes(location.hash.slice(1))?location.hash.slice(1):'scenario';
 for(const name of ['scenario','experiment','results'])$('page-'+name).hidden=name!==page;
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
 for(const title of ['N.','Migrazione','Salti','Ora','Luce sorgente','Luce destinazione'])head.append(node('th',title));
 const thead=node('thead');thead.append(head);
 profile.selected_events.forEach((event,index)=>{const tr=node('tr');tr.append(node('td',String(index+1)),node('td',`${event.source} → ${event.destination}`),node('td',String(event.hops)),node('td',clock(event.trigger_s)),node('td',Math.round(event.source_light_remaining_s/60)+' min'),node('td',Math.round(event.destination_light_remaining_s/60)+' min'));body.append(tr);});
 table.append(thead,body);const scroller=node('div',undefined,'table-scroll');scroller.append(table);box.append(scroller);
 box.append(node('p',`Ogni evento parte ${Math.round(p.trigger_lead_s/60)} min prima che la sorgente entri in ombra. Destinazione: il satellite raggiungibile con meno salti che resta al sole almeno ${Math.round(p.minimum_destination_light_s/60)} min, con un percorso stabile per almeno ${Math.round(p.minimum_path_persistence_s/60)} min.`,'small muted'));
 renderPicker();
}
function renderPicker(){
 const box=$('event-picker');box.replaceChildren();
 if(!profile)return;
 if(!selectedEvent&&profile.selected_events.length)selectedEvent=profile.selected_events[0].event_id;
 profile.selected_events.forEach((event,index)=>{const button=node('button',`Evento ${index+1}`);button.type='button';button.setAttribute('aria-pressed',String(event.event_id===selectedEvent));button.addEventListener('click',()=>{selectedEvent=event.event_id;renderPicker();loadTopology();});box.append(button);});
}
async function loadTopology(){
 if(!selectedEvent)return;
 try{
  const topology=await api('/topology?event='+encodeURIComponent(selectedEvent));
  renderOrbit($('orbit'),topology);
  const event=topology.event;
  $('orbit-caption').textContent=`Istante ${clock(topology.orbital_s)}: la sorgente ${event.source} entrerà in ombra fra ${Math.round(event.source_light_remaining_s/60)} min; il controller migra verso ${event.destination} in ${event.hops} salti laser. Geometria modellata, non in scala.`;
 }catch(error){$('orbit-caption').textContent='Vista orbitale non disponibile: '+error.message;}
}

/* ---------- experiment ---------- */
function activeJob(){const id=state?.lock?.job_id;return id?(state.job&&state.job.job_id===id?state.job:jobs.find(row=>row.job_id===id)):null;}
function latestLabJob(){return activeJob()||jobs.find(row=>['functional','compare_events','recover'].includes(row.operation))||null;}
function renderComponents(){
 const list=$('components');list.replaceChildren();
 const c=state?.components||{};
 const rows=[['Mininet / BMv2',c.mininet?.reachable?`${c.mininet.data?.switch_count??'—'} switch${c.mininet.data?.switches_alive?' attivi':''}`:'non raggiungibile'],
  ['Proxy P4',c.p4_proxy?.reachable?(c.p4_proxy.data?.active?'autorità a '+c.p4_proxy.data.active:'nessuna autorità attiva'):'non raggiungibile'],
  ['Controller SAT-A',c.sat_a?.reachable?'API pronte':'fermo'],['Controller SAT-B',c.sat_b?.reachable?'API pronte':'fermo'],
  ['Scenario',state?.scenario?.profile||'non installato'],['Lock del laboratorio',state?.lock?'occupato da '+state.lock.job_id:'libero']];
 for(const [name,value] of rows){const li=node('li');li.append(node('span',name),node('strong',value));list.append(li);}
}
function renderJob(){
 const job=latestLabJob(),comparison=job?.operation==='compare_events'?comparisons.find(row=>!row.complete&&!row.reason)||comparisons[0]:null;
 const view=jobView(state?.lock?job:(job&&!['queued','running'].includes(job.status)?job:null),comparison);
 $('job-title').textContent=view.title;$('job-detail').textContent=view.detail;
 $('stop').hidden=!view.canStop;
 $('recover').hidden=!(view.needsRecovery||(state?.lock&&state.worker_alive===false));
 const free=state&&!state.lock&&state.scenario?.events_ready;
 $('verify').disabled=!free;$('start').disabled=!free;
 const timelineBox=$('timeline');timelineBox.replaceChildren();
 for(const row of timeline(streamEvents)){const li=node('li');li.append(node('time',row.time),node('span',row.text));if(row.failed)li.className='failed';timelineBox.append(li);}
 if(!streamEvents.length)timelineBox.append(node('li','Nessun evento da mostrare.','muted'));
 if(job&&job.job_id!==streamJob)follow(job.job_id);
}
function follow(identifier){
 if(stream)stream.close();
 streamJob=identifier;streamEvents=[];
 stream=new EventSource('/api/v1/jobs/'+identifier+'/events');
 stream.onmessage=message=>{try{streamEvents.push(JSON.parse(message.data));if(streamEvents.length>800)streamEvents=streamEvents.slice(-400);renderJob();}catch{}};
 stream.addEventListener('end',()=>{stream.close();scheduleRefresh();});
 stream.onerror=()=>{};
}
async function launch(operation){
 $('verify').disabled=true;$('start').disabled=true;$('launch-error').hidden=true;
 try{const job=await api('/jobs',{operation,parameters:{}});notice({functional:'Verifica avviata',compare_events:'Esperimento avviato',recover:'Ripristino avviato'}[operation]+': '+job.job_id);follow(job.job_id);await refresh();}
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
function renderResults(){
 renderComparisonSelect();
 const box=$('results'),status=$('results-status');box.replaceChildren();
 const comparison=comparisons.find(row=>row.comparison_id===selectedComparison)||comparisons[0];
 if(!comparison){status.textContent='Nessun esperimento registrato.';}
 else{
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
  renderComponents();renderJob();renderResults();
 }catch(error){$('health').textContent='Console non collegata: '+error.message;$('health').dataset.state='error';}
}
async function loadProfile(){
 try{const {profiles}=await api('/scenario-profiles');profile=profiles.find(row=>row.installed&&row.summary)||profiles.find(row=>row.summary)||null;}catch{profile=null;}
 renderProfile();loadTopology();
}
document.addEventListener('DOMContentLoaded',async()=>{
 showPage();
 try{token=(await api('/session')).token;}catch(error){notice('Sessione locale non disponibile: '+error.message,true);return;}
 await loadProfile();await refresh();setInterval(refresh,5000);setInterval(renderJob,1000);
});
