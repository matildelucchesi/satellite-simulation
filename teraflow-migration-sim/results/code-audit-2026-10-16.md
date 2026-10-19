# Analisi del codice e delle responsabilità — 16 ottobre 2026

Il percorso FSO hot/cold è più comprensibile per chi lo usa. La semplificazione interna è invece parziale: esistono più coordinatori che applicano criteri diversi di successo e recupero. La raccomandazione è conservare l'implementazione e correggere questi confini prima di ampliare gli esperimenti. Non serve ripartire da zero.

## Perimetro e metodo

Analisi della copia di lavoro corrente, incluse modifiche non committate e nuovi moduli. Esaminati i flussi di migrazione, backend Docker/NBI, trasporto, proxy e autorità P4, emulazione, orbite, pianificazione, preparazione, campagne, job, API/console, metriche, report e script di gestione. Per il codice TeraFlow importato sono state esaminate le modifiche locali e i relativi test: questa analisi non certifica l'intero prodotto upstream o le dipendenze.

Nessuna modifica al codice applicativo, nessun riavvio del laboratorio e nessuna nuova migrazione live. I casi limite sono stati riprodotti in directory temporanee con backend simulati. Questo file è l'unico nuovo documento di consegna.

Verifiche eseguite:

- Suite locale: 96 test raccolti; 87 superati, 9 saltati perché richiedono i protobuf P4 del container.
- I medesimi 9 test P4 sono stati eseguiti nel container `p4-proxy` e sono tutti superati. Copertura complessiva di questa esecuzione: tutti i 96 test esistenti, senza fallimenti.
- Parsing AST di 84 file Python fra sorgenti, strumenti, test e patch locali: riuscito.
- `node --check web/app.js`: riuscito.
- Riproduzioni mirate aggiuntive: i risultati sono riportati sotto. Non sono nuovi test aggiunti alla suite.

La prima esecuzione nel sandbox aveva bloccato i socket di test. La ripetizione con accesso autorizzato è quella considerata nell'esito sopra.

Il passaggio dei test esistenti non esclude difetti: le riproduzioni hanno evidenziato scenari assenti dalla suite. Non sono state rieseguite l'intera campagna live, le sei calibrazioni o la validazione continua di tre handover per modalità.

## Problemi verificati, in ordine di priorità

P1 indica un problema da risolvere prima di affidarsi al percorso interessato. P2 indica una correzione necessaria per rendere coerenti procedure o risultati. P3 riguarda soprattutto leggibilità e diagnostica.

### A1 · P1 · La validazione continua può liberare il laboratorio quando serve recupero

Riferimenti: `src/experiment.py:375`, `src/jobs.py:156`, `src/simulation.py:202`.

Se la sessione continua restituisce `outcome='recovery_required'`, il contenitore `continuous_validation()` conserva soltanto identificatore, metodo e `passed=False`. Perde l'esito che segnala la mancata messa in sicurezza. `JobManager.work()` cerca quel segnale solo nei campi principali `outcome` o `reason`: conclude quindi il job e rimuove il lock.

Riproduzione: una sessione simulata ha restituito `recovery_required`; eseguendo il vero `JobManager.work()` con quel risultato si ottiene `status='completed'`, `application_success=False`, `lock_exists=False`.

Effetto: diventa possibile avviare un'altra operazione mentre la precedente richiede ancora recupero. Occorre propagare la necessità di recupero attraverso ogni operazione composta e mantenere il lock fino a conferma della messa in sicurezza.

### A2 · P1 · Il recupero di un job composto seleziona la prima prova

Riferimento: `src/experiment.py:69`.

`recover()` prende il primo `run_id` incontrato negli eventi del job, ma usa l'ultimo tempo orbitale disponibile. In una coppia hot/cold o campagna può quindi combinare snapshot e deadline di una prova precedente con il tempo della prova interrotta.

Riproduzione: job con prima prova avente deadline 1 e seconda prova avente deadline 99999; ultimo evento a tempo 200. Il recupero dichiara la sorgente scaduta e ferma A, benché la prova più recente abbia ancora una finestra valida.

Occorre un checkpoint esplicito della prova attiva, con identità e tempo coerenti; non basta scegliere un identificatore dalla cronologia. Anche il semplice ultimo `run_id` va verificato rispetto alla prova effettivamente aperta e all'eventuale intervallo fra due prove.

### A3 · P1 · La simulazione continua non verifica il servizio dopo ciascun cutover

Riferimenti: `src/simulation.py:166`, `src/simulation.py:174`; confronto con `src/experiment.py:196` e `src/live_backend.py:207`.

Il percorso principale chiama `verify_service()`. Il continuo considera invece sufficiente il successo di `Migration.run()` e passa subito a `finish_handover()` e alla revisione del piano. Può quindi accumulare handover riusciti senza la conferma dei ping freschi sulla destinazione.

Riproduzione: backend con `forwarding_observed=False` e `verify_service()` predisposto per sollevare un errore. La sessione conclude tre migrazioni con `success=True`; chiamate alla verifica del servizio: zero.

Occorre una procedura comune di conclusione dell'handover: equivalenza API, autorità, cutover, conferma del servizio e gestione degli eventuali errori. Il percorso avanzato non è ancora equivalente al percorso FSO principale sul criterio concordato API + ping stabile.

### A4 · P2 · L'interruzione durante l'osservazione finale può lasciare la prova riuscita

Riferimento: `src/experiment.py:197`.

Il ciclo finale esce quando `backend.cancelled` è vero, ma non solleva `InterruptedError` né passa per il recupero. Inoltre non richiama `backend.check()`: un errore dell'osservatore in questa fase può non essere rilevato dal coordinatore.

Riproduzione: cancellazione impostata subito dopo la verifica del servizio. Risultato: `cancelled=True`, `success=True`, `outcome='success'`, zero chiamate a `recover_source()`. Il job può risultare interrotto mentre la prova salvata risulta riuscita.

Occorre definire una semantica unica di interruzione tardiva. Si può anche conservare il successo tecnico già raggiunto, ma l'osservazione interrotta deve essere esplicita e non confondersi con una prova completata secondo protocollo.

### A5 · P2 · Esito non valido e booleano di successo possono contraddirsi

Riferimento: `src/experiment.py:266`.

Quando una prova primaria misura meno del 90% del throughput richiesto, viene impostato `outcome='invalid_lab'` lasciando `success=True` e `ack=True`.

Riproduzione: richiesta 1 Gbit/s, ricevuta a 100 Mbit/s; risultato `success=True`, `ack=True`, `outcome='invalid_lab'`.

L'ACK storico può essere un fatto corretto, perché il cutover è avvenuto. Servono però campi distinti per migrazione tecnica riuscita e validità sperimentale. Tutti i consumatori devono usare lo stesso criterio di accettazione; oggi alcuni guardano soltanto `success`.

### A6 · P2 · Il report conta i casi senza verificarne l'appartenenza alla campagna

Riferimento: `src/analysis.py:75`.

`primary_complete` richiede 18 triple distinte evento/metodo/rate e nessun esito `running`. Non confronta quelle triple con gli eventi congelati e con la matrice attesa. Inoltre raccoglie tutte le prove primarie presenti nella directory, senza identità di campagna.

Riproduzione: 18 eventi diversi, tutti hot e tutti a 1 Gbit/s, producono `primary_complete=True`. Mancano cold e le altre due velocità. Anche aggiungere risultati di campagne diverse può alterare il conteggio.

Occorre costruire l'insieme atteso dal manifest e confrontarlo con i casi registrati della stessa campagna. Completezza della raccolta e numero di migrazioni riuscite devono restare concetti distinti: una campagna può essere completamente eseguita e contenere fallimenti sperimentali legittimi.

### A7 · P2 · La configurazione FSO non è sempre la fonte effettiva dei parametri

Riferimenti: `src/experiment.py:31`, `src/web.py:164`, `src/orbit.py:62`, `src/events.py:26`, `src/events.py:35`.

`Orbit` riceve normalmente solo il percorso del replay: usa quindi i default di 1700 km e del raggio terrestre, senza leggere i corrispondenti parametri dello scenario. Riproduzione in memoria: scenario con `max_range_km=1`; oggetto orbitale effettivo con `max_range=1700`.

Analogamente, la generazione degli eventi usa 40% e 45% come carichi candidati fissi e usa i default della rampa delle risorse, mentre il planner legge parte di questi valori dallo scenario. Oggi i valori standard coincidono; modificare la configurazione può però non modificare l'esperimento atteso.

Occorre una costruzione comune del modello a partire dalla configurazione validata. I parametri non supportati devono essere rifiutati o dichiarati fissi, invece di essere silenziosamente ignorati.

### A8 · P2 · Il restore non usa i file di stato ricevuti via TCP

Riferimenti: `src/orchestrator.py:102`, `src/orchestrator.py:108`, `src/orchestrator.py:123`.

Snapshot e delta sono effettivamente trasferiti e il ricevitore verifica il checksum. Il restore usa però `initial` e `changes` già presenti nella memoria del coordinatore; la ricevuta dello snapshot è assegnata e poi non utilizzata. Le immagini, al contrario, sono caricate dal percorso ricevuto.

È un limite della dimostrazione della procedura end-to-end, non la prova di una perdita di stato nelle due prove salvate: il trasferimento verifica comunque l'integrità. La destinazione dovrebbe caricare e validare il documento dal percorso della ricevuta, così il ripristino dipende realmente dall'artefatto consegnato.

### A9 · P2 · Alcuni strumenti operativi aggirano il controllo esclusivo del laboratorio

Riferimenti: `tools/live_preflight.py:23`, `tools/check_tfs_hosts.py:26`, `tools/stack.py:16`.

`stack.py` controlla il lock per le operazioni mutanti. `live_preflight.py --reset-fixture`, ancora documentato, modifica link, stato NBI e sonde senza quel controllo. Anche il test opzionale di isolamento modifica temporaneamente la NBI senza passare dal gestore dei job. Possono interferire con un esperimento in corso.

Il preflight mantiene inoltre un criterio di successo con UDP obbligatorio, diverso dalla regola attuale API + ping. Va ricondotto alle procedure condivise, oppure marcato e protetto come strumento di manutenzione esclusiva.

### A10 · P3 · Un retry riuscito conserva il motivo del fallimento precedente

Riferimenti: `src/orchestrator.py:134`, `src/orchestrator.py:145`.

Riproduzione: primo trasferimento fallisce, secondo tentativo riesce. Risultato finale: `success=True`, `attempt=2`, `failure_reason='first attempt failed'`, `failure_phase='transfer'`.

Il guasto precedente appartiene alla cronologia dei tentativi. I campi del fallimento finale dovrebbero essere vuoti in caso di successo, o avere un nome che indichi esplicitamente l'ultimo errore storico. La console oggi può presentarlo come motivo del risultato corrente.

## Ulteriori osservazioni statiche

- `environment()` registra `transport_capacity[].supported` ma non lo include nel proprio `success` (`src/experiment.py:134` e `:138`). Una capacità insufficiente resta visibile nei dati, ma non blocca quel gate. Conviene restituire chiaramente capacità per rate e rate utilizzabili.
- `engine_fingerprint()` include anche moduli di UI/report, ma esclude replay, finestre di contatto e selezione della costellazione. Il manifest di campagna congela più artefatti, ma non `results/direct_link_windows.json`. Provenienza delle calibrazioni e degli ingressi del planner va resa uniforme. Non è stato riprodotto qui un cambiamento live di tali artefatti.
- Launcher e worker riscrivono entrambi il lock del job. La finestra tra `Popen()` e la scrittura del PID nel launcher merita un test di concorrenza con worker che termina immediatamente; non è classificata qui come guasto runtime già riprodotto.
- Nei report continui il minimo throughput comprende anche snapshot/delta piccoli. Non è confrontabile direttamente con il throughput del bundle immagini del report principale.
- Il riepilogo ping continuo copre l'intera sessione: non fornisce una misura di recupero separata per ogni migrazione. Il downtime del controller è invece per tentativo riuscito; le indisponibilità dei tentativi falliti restano nella cronologia e non sono sommate a quella misura.
- Alcune stringhe del report continuo hanno caratteri già alterati nell'origine, per esempio `non Ã¨`. È una correzione editoriale minore.
- La guida deployment afferma che lo stato standby non è persistente, mentre `SwitchState.persist()` salva pipeline e stato dei due slot. La procedura documentata di riavvio va riallineata al comportamento attuale.

## Responsabilità attuali e confini da chiarire

| Area | Componenti attuali | Responsabilità da mantenere | Sovrapposizione da risolvere |
|---|---|---|---|
| Accesso utente | `web.py`, `web/app.js`, `tools/experiment.py` | Presentare dati e inviare comandi | Il web ricostruisce i requisiti di calibrazione che il motore verifica già |
| Esecuzione dei job | `jobs.py` | Esclusività, worker, annullamento, stato persistente | Dipende da dizionari di risultato non uniformi per capire se serve recupero |
| Coordinamento degli esperimenti | `experiment.py`, `simulation.py`, mixin `Preparation` e `Analysis` | Coppia, campagna, sessione, preparazione | Conclusione, accettazione e recupero non condivisi; mixin dipendono implicitamente dallo stesso oggetto |
| Protocollo di migrazione | `orchestrator.py` | Ordine hot/cold, allineamento, tentativi, trasferimenti, ACK | Il suo `success` precede la verifica del servizio applicata solo da alcuni chiamanti |
| Operazioni del laboratorio | `live_backend.py`, `deployment.py`, `processes.py` | Docker, API, aggiornamento topologia, osservatori | Il backend incorpora anche misure, trasporto, stato del protocollo e criteri di accettazione |
| Stato TeraFlow | `tfs_adapter.py`, `snapshot.py`, `fixture.py` | Export/restore/reconcile, equivalenza, identità stabili | Lo snapshot ricevuto non è la fonte del restore; parte della topologia è riconciliata anche nel backend |
| Autorità e hardware | `authority.py`, `p4_proxy.py` | Un solo scrittore, staging, fencing, read-back | Separazione utile da conservare: politica dell'autorità e meccanica gRPC non vanno fuse |
| Trasporto | `transport.py` | Byte reali, pacing, timeout, checksum, ricevute | Deve consegnare artefatti consumati dal restore; non deve decidere l'esito scientifico |
| Geometria e decisioni | `orbit.py`, `events.py`, `planner.py`, modelli e campionamento | Orbite, contatti, risorse sintetiche, eleggibilità | Calcolo contatti, trigger e carichi ripetuto con lettura diversa della configurazione |
| Misure e risultati | `probes.py`, `measurements.py`, report e grafici | Misure con provenienza, aggregazioni, esportazioni | Schemi e criteri di completezza divergono fra prova, sessione e campagna |

La modifica architetturale utile è attribuire a un'unica procedura la conclusione verificata di una migrazione, mantenendo coordinatori distinti per coppia e sessione. Non serve introdurre un nuovo framework o distribuire tutto in molti nuovi servizi.

## Duplicazioni da eliminare o ridurre

| Duplicazione | Esempi | Intervento consigliato |
|---|---|---|
| Criterio di successo e gestione finale | `Experiment.run`, `Simulation.run`, `functional`, `continuous_validation`, `JobManager.work` | Risultato strutturato comune con esito tecnico, servizio verificato, validità, interruzione e necessità di recupero; procedura condivisa per la conclusione |
| Requisiti di preparazione | `Application.simulation_readiness` e `Simulation.prepare_planner` | Verificatore comune che restituisca motivi utilizzabili da UI e motore; preservare la verifica checksum completa nel worker senza ripeterla a ogni polling |
| Geometria dei contatti | `tools/check_direct_links.py` e `Orbit._graph` | Calcolo condiviso e finestre derivate dallo stesso replay, con medesimi parametri |
| Trigger e risorse | `events.py`, `Planner.trigger`, `Planner.node`, costanti di `Analysis.sensitivity` | Unificare formule e configurazione; preservare la distinzione voluta fra caso rappresentativo e carico persistente nelle sessioni |
| Conversione manifest → workload | `Preparation.workload` e `tools/run_matrix.load_workload` | Un solo caricatore validato |
| Policy di recupero astratta | `failure_model.py` e macchina a stati reale | `failure_model` risulta usato dai test, non dal percorso operativo; eliminarlo se non serve come modello esplicitamente separato. Oggi promette azioni diverse quando A è scaduto |
| Preflight separato | `tools/live_preflight.py` rispetto a reset/baseline del backend | Riutilizzare il flusso condiviso e la stessa esclusività, con gate coerenti |
| Report e metriche comuni | `analysis.py`, `simulation_report.py`, due moduli grafici e aggregazioni nel coordinatore | Condividere estrazione e definizione delle metriche; conservare report distinti per prova e sessione |
| Identità e parametri del laboratorio | Nomi slot, porte, componenti, commit e soglie ripetuti | Usare le costanti esistenti e una configurazione validata; evitare ulteriori valori duplicati |

Non sono duplicazioni da cancellare automaticamente:

- I due stack A/B hanno correttamente database, broker e identità separati. Sono due slot esecutivi riutilizzabili, non le due orbite.
- `stack.yaml` è generato dai template: la ripetizione delle definizioni A/B nel file prodotto è intenzionale e già verificata dai test.
- Diff, manifest e file TeraFlow patchati sono artefatti di provenienza/build. Non bisogna eliminare una copia senza aggiornare il processo che la produce e la verifica.
- Modello dei tempi e operazioni live rispondono a domande diverse. Non vanno fusi facendo apparire una stima come misura.

## Correttezza scientifica e limiti da preservare espliciti

Il sistema esegue una migrazione applicativa dello stato TeraFlow via API con trasferimento delle immagini; non trasferisce l'intera memoria di un processo o di una VM. Le dipendenze sono preinstallate e indipendenti sui due slot.

Il TCP è reale, ma viaggia fra socket locali del laboratorio e riceve pacing e disponibilità dal modello FSO. Non attraversa il collegamento satellitare Mininet come un flusso ottico fisico. Mininet verifica separatamente il servizio dati h1↔h2. La geometria chiude i contatti; rumore ottico, puntamento dettagliato, BER e un modello radio non risultano implementati. La voce TeraFlow `LINKTYPE_RADIO` nella fixture è un'etichetta di schema: non equivale a una simulazione radio.

Il ping può continuare anche durante l'arresto del controller perché le regole già installate restano nei dispositivi. Perciò cold con ping continuo non contraddice un downtime del controller elevato. Allo stesso modo una perdita con percorso geometrico disponibile non prova da sola che la migrazione ne sia la causa.

Dieci ping freschi dimostrano che il percorso provato inoltra dopo il cutover, insieme a evidenze API/autorità. Non dimostrano da soli che il nuovo controller sappia reagire correttamente a un cambiamento successivo: per tale affermazione serve una prova controllata di riconfigurazione dopo il trasferimento.

La coppia salvata `compare-3367d7d511574e6798a7a4a6f08c4285` risulta completa nelle evidenze: stesso evento, 1 Gbit/s, baseline e servizio verificati, un tentativo per modalità. È evidenza di funzionamento del percorso allora eseguito, non certificazione dell'intera campagna né replica del codice attuale bit per bit. Una sola coppia, ordine sempre hot→cold e Docker daemon condiviso non permettono conclusioni statistiche o un confronto non influenzato dalla cache. Le risorse dei 17 satelliti sono modellate; CPU/RAM misurate appartengono ai due slot Docker reali.

## Sequenza di intervento proposta

1. Correggere A1 e A2: propagazione del recupero e checkpoint della prova attiva. Aggiungere test per job composti e worker perso.
2. Correggere A3: la simulazione continua deve applicare la stessa verifica del servizio e conservarne le evidenze per ogni handover.
3. Rendere coerenti risultato, interruzione e validità; correggere A4–A6 e A10 con test mirati.
4. Collegare il restore agli artefatti ricevuti e centralizzare configurazione, geometria e requisiti di preparazione; proteggere gli strumenti di manutenzione.
5. Ridurre le duplicazioni individuate, senza cambiare nello stesso intervento le ipotesi scientifiche.
6. Ripetere la coppia FSO sul codice corretto. Validare separatamente il continuo prima di sbloccare la campagna avanzata. Valutare il radio solo dopo questo consolidamento.

La semplificazione utile consiste soprattutto nell'avere un significato unico di «riuscito», «verificato», «interrotto» e «da recuperare». Eliminare file o rinominare classi prima di chiarire questi contratti ridurrebbe poco la difficoltà di gestione.
