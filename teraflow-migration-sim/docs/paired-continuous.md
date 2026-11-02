# Confronto continuo Hot/Cold

La console `http://127.0.0.1:18092/` separa calibrazione e confronto orbitale. Scegliere la velocità del canale e preparare il confronto con tre migrazioni verificate per modalità. Il confronto usa una calibrazione valida già disponibile; non esegue migrazioni preliminari automaticamente.

## Esecuzione

1. Verificare la presenza di una calibrazione valida per l’implementazione corrente. Se manca, il confronto viene bloccato prima della creazione del job: dalla sezione «Calibrazione separata» eseguire la verifica preliminare eventualmente richiesta, poi una calibrazione Cold e una Hot. Il loro completamento non avvia automaticamente il confronto. Una campagna già congelata non viene cancellata per forzare la calibrazione.
2. Cercare una sequenza con almeno una migrazione, fattibile per Hot e Cold. Il margine di ammissione comprende il caso più lento, la verifica del servizio e una riserva per il ripristino.
3. Salvare `plan.json` e il suo SHA-256 prima delle esecuzioni. Partenza orbitale, satellite iniziale, trigger, sorgenti, destinazioni e deadline sono condivisi. Anche l’identità del bundle di immagini, la configurazione dello scenario e la fixture iniziale vengono fissate e controllate.
4. Eseguire l'intera sessione Hot, arrestare e mettere in sicurezza i workload, quindi ricostruire lo stato iniziale e verificare nuovamente la baseline prima di Cold.
5. Eseguire Cold sullo stesso piano. Nessuna ripianificazione è consentita; un evento mancato di oltre un secondo, una deadline superata o una verifica fallita ferma il confronto. Non si cambia evento per ottenere un esito positivo.

Nella console le due sessioni terminano dopo le tre migrazioni richieste e verificate. La CLI mantiene anche la modalità a durata prefissata. Sono esecuzioni live sequenziali a velocità 1×, non due processi contemporanei e non un'animazione accelerata.

## Risultati e controllo

La mappa segue automaticamente la modalità in corso. Nello storico si possono selezionare Hot o Cold e consultare il replay; «Segui esecuzione in corso» riattiva l'inseguimento automatico. I pulsanti delle misure per evento aprono il replay al relativo trigger.

La tabella confronta gli eventi e mostra Cold meno Hot solo quando entrambe le prove dell'evento sono valide. Il totale del downtime del controller somma le migrazioni riuscite di una sessione completata: non rappresenta il downtime del servizio. Il forwarding deriva dalle sonde, separatamente dalla geometria e dalla conferma di autorità del controller. Valori assenti restano vuoti o `—`.

Risultati, piano, CSV e report HTML sono in `results/continuous-comparisons/pair-*/`. I dettagli delle due esecuzioni rimangono in `results/simulations/sim-*/`; i loro identificativi e lo SHA-256 comune sono registrati nel confronto. Le evidenze parziali sono conservate anche in caso di errore o interruzione. Il ripristino dopo perdita del worker conclude il confronto interrotto; non riprende il vecchio clock.

## CLI e API

```powershell
.\.venv\Scripts\python.exe tools/experiment.py compare_continuous --duration-s 600 --wait
```

`POST /api/v1/jobs` accetta `operation: "compare_continuous"` e `parameters: {"duration_s": 600, "rate_bps": 1000000000}` con la normale sessione same-origin. Il confronto non accetta un parametro `method` indipendente. La CLI conserva le opzioni di partenza, satellite iniziale e limite migrazioni; un limite incompatibile con la durata viene rifiutato.

`GET /api/v1/continuous-comparisons` elenca i confronti; `GET /api/v1/continuous-comparisons/pair-ID` restituisce lo stato e le misure. Le API precedenti di sessioni singole e prove funzionali restano disponibili per compatibilità e diagnostica da CLI, ma non compaiono più come operazioni nella console.

## Preferenza di partenza vicino all’ombra

La politica `automatic-start-shadow-v3` minimizza il tempo residuo in luce del satellite iniziale, misurato dall’istante di partenza selezionato al suo successivo ingresso in ombra. Si confrontano soltanto sequenze già ammesse per entrambe le modalità e per tutte le migrazioni richieste: restano invariati maggiorazioni temporali, riserve di recupero, contatti, risorse e continuità geometrica del servizio.

A parità di tempo residuo si preferisce il margine minimo di sicurezza maggiore, poi l’istante orbitale precedente e il NORAD minore. La fine dell’osservazione non viene interpretata come ingresso in ombra: una partenza senza transizione osservabile viene esclusa. Le evidenze includono `initial_time_to_shadow_s`, `initial_shadow_entry_s`, `minimum_margin_s` e `selection_objective`.

Il criterio sceglie il migliore fra i candidati esaminati. Solo `exhaustive: true` indica che la ricerca ha coperto tutto il replay alla risoluzione prevista; un limite di tempo non dimostra l’ottimalità globale. Le selezioni congelate con politiche precedenti devono essere rigenerate.

## Preparazione della sorgente

Durante il reset iniziale il workload della destinazione viene arrestato senza accedere alle sue API. Non vengono più eseguiti l’avvio e la pulizia preventiva della destinazione. La pulizia del suo scenario resta nel percorso `start_target`, dopo il trasferimento iniziale e l’avvio previsto dalla migrazione Hot/Cold.

L’avvio della sorgente procede per comandi Compose separati con attesa di salute: dipendenze (database, NATS e Kafka), contesto, dispositivi, calcolo percorsi, gestione servizi e API NBI. Gli eventi `source_startup` riportano sottofase, etichetta, esito e durata. Tutti i comandi condividono il limite esistente della fase `start_source`; i limiti non ripartono a ogni sottofase. Un errore interrompe la sequenza e conserva il nome della sottofase fallita.

La timeline mostra questi eventi con etichette leggibili. Il titolo centrale del loader segue il passaggio corrente, incluso il successivo caricamento dello scenario e la verifica di API, autorità e traffico. La destinazione viene avviata soltanto durante la migrazione; lo stato finale della sorgente deve comunque superare la baseline prima di avviare il clock orbitale.

## Attesa dell’infrastruttura

La fase `infrastructure` ripete le verifiche di Mininet e del proxy P4 entro il proprio budget (15 secondi predefiniti). Ogni richiesta HTTP usa al massimo 2 secondi, sempre limitati dal tempo residuo; tra i tentativi l’attesa interrompibile è al massimo di 1 secondo. Connessioni temporaneamente chiuse, risposte non valide, switch mancanti o arbitraggio incompleto non causano un fallimento immediato.

Si prosegue soltanto con tutti gli switch Mininet attivi, il numero previsto di connessioni P4 confermate e un indirizzo del proxy disponibile. Non è richiesta la disponibilità delle API della destinazione. Gli eventi `infrastructure_wait` vengono emessi al cambiamento dello stato, per evitare di riempire la timeline con richieste identiche. Alla scadenza l’errore `p4_not_ready` conserva l’ultimo stato di ogni componente. L’interruzione dell’utente resta distinta dal timeout.

## Passaggio dal loader alla vista orbitale

La preparazione del confronto contiene soltanto la pianificazione condivisa, l’attivazione della sorgente, il caricamento dello scenario e la verifica della baseline. L’evento `controller_assigned` con `baseline_verified: true` abilita la vista orbitale e il clock della sessione. Le migrazioni Hot/Cold appartengono a questa vista; nessuna calibrazione viene eseguita nel loader del confronto.

Le operazioni indipendenti `functional` e `calibrate` sono avviate esplicitamente dalla configurazione, hanno avanzamento dedicato e non sbloccano da sole la simulazione orbitale. Se le misure diventano non valide tra l’ammissione e l’esecuzione del worker, il worker si ferma senza avviare controlli funzionali, calibrazioni o sessioni orbitale.

## Base comune per tre velocità

La configurazione offre «Crea scenario iniziale». Il job `prepare_base`, esposto nella dashboard come «Crea scenario iniziale», riutilizza misure valide oppure esegue la verifica funzionale eventualmente mancante e le due calibrazioni prima di pianificare e salvare la base. Le migrazioni preliminari appartengono alla calibrazione; i tre confronti non vengono avviati. La ricerca usa 100 Mbit/s, il caso più lento, e verifica che le stime per 1 e 10 Gbit/s rientrino nello stesso programma conservativo.

La base in `results/common-bases/base-*/` conserva calibrazione, scenario, fixture, costellazione, stato iniziale desiderato e un unico piano con tre migrazioni. Satellite sorgente, istante iniziale, satelliti destinazione, trigger e deadline restano identici per tutte le velocità. Il riferimento al replay è protetto dalla sua impronta e l’integrità viene verificata prima dell’esecuzione. La ricerca resta limitata al budget dichiarato e non afferma l’ottimalità globale quando non esaustiva.

La dashboard invia `base_id` al confronto e cambia solo `rate_bps`. La CLI supporta `prepare_base --wait` e `compare_continuous --base-id base-... --rate-bps 100000000 --wait`. I risultati registrano `common_base_id` e `common_schedule_sha256` per documentare la sequenza comune. Una base alterata o non più compatibile con input e calibrazione viene rifiutata senza ripianificazione silenziosa.

La base è una configurazione e un piano riproducibili, non un’istantanea completa della macchina Docker. Il ripristino completo resta necessario tra Hot e Cold e prima di un nuovo confronto; la prima sessione Hot adotta la sorgente predisposta da «Crea scenario iniziale» dopo i controlli finali. Le sole modifiche a `web.py`, `jobs.py` e al salvataggio `common_base.py` non invalidano le misure: rimangono nell’impronta le implementazioni che incidono sulle operazioni misurate e le configurazioni della prova.

## Pulsante unico di creazione

La dashboard mostra un solo pulsante di preparazione della base: «Crea scenario iniziale». La calibrazione è inclusa in questa operazione, mentre «Avvia» continua a non avviare calibrazioni. Una verifica funzionale valida viene riutilizzata; una calibrazione valida evita nuove prove preliminari. Errori e necessità di recupero interrompono la catena senza pubblicare una base pronta. I comandi CLI `functional` e `calibrate` rimangono disponibili per uso tecnico.


## Sorgente pronta prima di Avvia

«Crea scenario iniziale» include calibrazione quando necessaria, riusa un piano comune ancora valido e prepara realmente la sorgente: avvio dei servizi, caricamento e verifica dello scenario, autorità P4 e baseline API/traffico. La destinazione resta arrestata. A successo il job termina lasciando la sorgente accesa, senza avviare il clock orbitale. Il record `source-ready.json` conserva generazione P4 e impronta dello snapshot verificato.

«Avvia» richiede anche la disponibilità corrente di API e autorità, consuma il record una sola volta, confronta l’inventario reale con lo snapshot e ripete sonde fresche prima del clock. Non ripete avvio, pulizia o caricamento per la prima sessione Hot se la sorgente è ancora valida. Se il controllo fallisce il clock resta fermo e il laboratorio viene messo in sicurezza. Cold continua a richiedere il ripristino tra le modalità. Dopo un confronto, il piano e la calibrazione restano riutilizzabili, ma la sorgente va predisposta di nuovo tramite «Crea scenario iniziale», perché le migrazioni ne modificano lo stato. Il pulsante non rappresenta una garanzia permanente contro arresti esterni di Docker o del PC.


## Calibrazione abbreviata

La creazione dello scenario richiede ora una sola prova Cold e una sola Hot a 1 Gbit/s. Eventi, metadati e avanzamento dichiarano `replicas_per_mode: 1` e `calibration_total: 2`. L’ammissione verifica due run distinti, una per modalità, entrambe con baseline valida; le vecchie calibrazioni complete a sei prove rimangono leggibili se compatibili con l’impronta dell’implementazione. Le stime restano maggiorate dal pianificatore, ma una singola osservazione per modalità non misura la variabilità tra ripetizioni. Le verifiche funzionali eventualmente mancanti restano un prerequisito separato all’interno della creazione.
