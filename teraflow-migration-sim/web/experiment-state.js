/* Pure presentation model shared by the console and browser regression tests. */
function experimentView(pair, job, now=Date.now(), operationLabels={}) {
 const p=job?.progress||pair?.progress||{}, terminal=pair?.phase==='finished';
 const age=value=>value?Math.max(0,Math.floor((now-Date.parse(value))/1000)):null;
 const phase=p.phase||pair?.phase||'configuration';
 const labels={configuration:'Configura il confronto',preparation:'Verifica laboratorio',calibration:'Calibrazione',planning:'Piano condiviso',hot:'Esecuzione Hot',resetting:'Ripristino',cold:'Esecuzione Cold',finished:'Risultati'};
 const recoveryFailed=job?.operation==='recover'&&['recovery_required','failed','interrupted'].includes(job.status);
 const error=pair?.error||(!terminal?p.error:null)||(recoveryFailed?{code:'recovery_failed',message:'Il recupero del laboratorio non è riuscito.',technical_detail:job.error}:null);
 const admissionRejected=!!(!Object.keys(pair?.sessions||{}).length&&(error?.code==='plan_not_admissible'||(terminal&&pair?.reason?.startsWith('No feasible sequence'))));
 const recovery=pair?.recovery_required||job?.status==='recovery_required';
 const failed=terminal&&!pair.success;
 const title=recovery?'Ripristino necessario':job?.operation==='recover'&&['queued','running'].includes(job.status)?'Ripristino laboratorio':job?.cancellation_requested&&!terminal?'Interruzione in corso':terminal?(pair.success?'Confronto completato':pair.outcome==='interrupted'?'Confronto interrotto':admissionRejected?'Sequenza non ammissibile':'Confronto non completato'):labels[phase]||'Preparazione laboratorio';
 let detail=p.label||operationLabels[p.subphase]||'La preparazione precede l’avvio del clock orbitale.';
 if(p.subphase==='restore_scenario'&&p.restore_counts&&!terminal){
  const c=p.restore_counts,entity=p.restore_entity?.name;
  detail=p.restore_verification==='running'?'Verifica finale dello scenario':p.restore_verification==='completed'?'Scenario caricato e verificato':
   `Caricamento satelliti: ${c.devices.completed}/${c.devices.total} · link: ${c.links.completed}/${c.links.total} · servizi: ${c.services.completed}/${c.services.total}${entity?` — ${entity}`:''}`;
 }
 if(['hot','cold'].includes(phase)&&!p.label)detail=`Il clock orbitale procede in tempo reale. Migrazioni verificate: ${p.completed_migrations??0}.`;
 if(p.calibration_index&&phase==='calibration') detail=`Test preliminare ${p.calibration_index}/6 · ${(p.method||'').toUpperCase()} · ${detail}`;
 if(p.calibration_index&&phase==='calibration')detail+=' · Il confronto Hot → Cold inizierà dopo il piano condiviso.';
 if(p.subphase==='departure_search'&&!terminal)detail=`Ricerca della partenza · ${p.examined_candidates??0} candidati · ${Math.floor(p.elapsed_s??0)} s / ${p.limit_s??600} s${p.selected?` · migliore NORAD ${p.selected.initial_satellite_id} a ${p.selected.start_orbital_s} s · margine ${p.selected.minimum_margin_s} s`:' · nessuna soluzione verificata finora'}.`+(p.rejections?' Esclusioni: '+Object.entries(p.rejections).map(([key,value])=>`${({service_path_window:'Percorso del servizio non continuo durante la migrazione',insufficient_contact:'Contatto troppo breve',future_dead_end:'Migrazioni successive non ammissibili',initial_resource_or_shadow:'Partenza in ombra o risorse insufficienti',initial_service_path:'Percorso iniziale del servizio assente',destination_in_shadow:'Destinazione in ombra',destination_deadline:'Illuminazione destinazione insufficiente',source_deadline_before_safe_completion:'Tempo sorgente insufficiente per operazione e recupero',negative_safety_margin:'Margine di sicurezza insufficiente'})[key]||key}: ${value}`).join(', '):'');
 if(job?.cancellation_requested&&!terminal)detail='Richiesta ricevuta. Messa in sicurezza del laboratorio in corso; un nuovo avvio resta bloccato fino alla verifica.';
 if(!pair) detail='Scegli la velocità. Prima Hot, poi Cold sullo stesso piano: obiettivo 3 migrazioni verificate per modalità.';
 if(terminal) detail=pair.success?'Entrambe le modalità sono terminate. Verifica eventi confrontabili e provenienza nei risultati.':'Le misure mancanti non sono zero. Consulta la causa e lo stato del ripristino prima di riprovare.';
 if(job?.operation==='recover')detail=recoveryFailed?'Il recupero si è fermato. Il laboratorio resta bloccato e le evidenze sono conservate.':'Recupero del laboratorio in corso. Attendere la verifica prima di un nuovo confronto.';
 const explanations={dependency_unhealthy:'Una dipendenza del controller non supera il controllo di salute.',startup_failed:'Il controller non è riuscito ad avviarsi.',startup_timeout:'Il controller non è diventato disponibile entro il limite di avvio.',preparation_timeout:'La sottofase di preparazione ha raggiunto il suo limite di tempo.',p4_not_ready:'Mininet o l’autorità P4 non hanno superato la verifica iniziale.',invalid_baseline:'Il servizio iniziale non ha superato la verifica API, autorità e sonde.',preparation_failed:'Un’operazione di preparazione del laboratorio non è riuscita.',interrupted:'L’esecuzione è stata interrotta.'};
 return {phase,title,detail,failed,recovery,error,admissionRejected,recoveryFailed,
  errorTitle:job?.worker_lost?'Il processo si è interrotto senza concludere il lavoro. Ripristinare il laboratorio prima di un nuovo avvio.':pair?.outcome==='interrupted'?'Esecuzione interrotta su richiesta.':admissionRejected?'I vincoli di contatto, illuminazione e risorse non consentono il piano richiesto.':error?.code==='departure_search_incomplete'?'Ricerca interrotta dal limite di tempo: non è stata accertata l’assenza di soluzioni.':error?error.message||explanations[error.code]||'La preparazione non è riuscita.':pair?.reason||'Informazione non disponibile per questo confronto storico.',
  elapsed:age(pair?.created_utc||p.started_utc),age:age(p.last_progress_utc),
  heartbeatAge:age(job?.worker_heartbeat?.timestamp_utc),
  deadline:!terminal&&p.operation_status==='running'?p.deadline_utc:null,
  workerActive:['queued','running'].includes(job?.status),terminal};
}
if(typeof module!=='undefined')module.exports={experimentView};
