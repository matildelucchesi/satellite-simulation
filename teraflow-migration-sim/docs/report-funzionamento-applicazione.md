# Report sul funzionamento dell'applicazione TeraFlow

Data: 14 ottobre 2026. Questa guida descrive il codice presente nel repository, dopo la rimozione della precedente simulazione. I percorsi qui riportati sono relativi a `teraflow-migration-sim/`.

## 1. Scopo e natura dell'esperimento

L'applicazione confronta la migrazione **cold** e **hot** di un controller TeraFlowSDN 7.0.0 da un host SAT-A a un host SAT-B. La rete orbitale comprende 17 satelliti, distribuiti su due piani: 6 nel primo e 11 nel secondo. A e B identificano i ruoli sorgente e destinazione della prova; non sono due satelliti aggiuntivi.

Il laboratorio combina componenti reali e modelli:

| Elemento | Funzionamento |
| --- | --- |
| Orbite | TLE congelati, propagazione SGP4 e replay orbitale con passo di 1 secondo. |
| Collegamento FSO | Contatto diretto modellato entro 1.700 km, senza occultazione della Terra sferica, con 60 secondi consecutivi di allineamento. |
| Carico di fondo | Rampa sintetica deterministica di CPU/RAM, utilizzata nella previsione degli eventi. |
| Controller | Due stack Docker TeraFlow distinti, con API e operazioni effettive di avvio, export e restore. |
| Trasferimento | TCP reale nel laboratorio, regolato al throughput utile selezionato e verificato dal ricevitore tramite checksum. Non è un terminale laser fisico. |
| Servizio | Mininet/BMv2/P4, con sonde ping e UDP reali tra endpoint. |

L'eclissi è una scadenza operativa del modello. Non dimostra di per sé che un apparato reale perderebbe alimentazione o collegamento radio in ombra.

## 2. Componenti e flusso dei dati

Il frontend (`web/index.html`, `web/app.js`) comunica con il server locale `src/web.py`. Il server espone API HTTP, download registrati e timeline SSE, e delega le operazioni a `src/jobs.py`. Ogni operazione crea un worker indipendente che esegue `src/experiment.py`; il browser può essere chiuso senza interromperlo.

`src/orchestrator.py` governa le fasi della migrazione. `src/live_backend.py` esegue gli accessi Docker, alle API TeraFlow e al laboratorio P4. `src/tfs_adapter.py` esporta, riconcilia e verifica lo stato; `src/snapshot.py` calcola il delta tra snapshot. `src/transport.py` gestisce copia TCP, avanzamento e checksum. `src/probes.py` interpreta le osservazioni del servizio. `src/analysis.py` produce i report dai risultati già salvati.

Ogni stack contiene Context, Device, Service, NBI e PathComp; PathComp è diviso in frontend e backend, quindi il workload utilizza sei immagini. CockroachDB, NATS e Kafka sono indipendenti per A e B e sono considerati preinstallati. I database dei due host non sono replicati tra loro: lo stato viene trasferito attraverso snapshot e restore applicativo.

Il proxy P4 gestisce l'autorità del controller: B può preparare uno stato standby senza assumere il controllo dell'hardware. La destinazione ottiene il ruolo attivo dopo le verifiche e l'ACK. Le patch locali Service/Device e il bundle effettivamente usato sono dichiarati in `deploy/patches/` e `artifacts/images-l2-patched-v2/`.

Un lock persistente permette un solo job sul laboratorio. Un job può contenere più prove; una prova è una singola migrazione. Gli identificativi `job-*` e `run-*` vanno quindi interpretati separatamente.

## 3. Selezione del satellite destinazione

La configurazione scientifica è in `config/scenario.json`. Il profilo nominale per host è 6 core, 12 GiB di RAM e 80 GiB di disco, con riserva del 20%. L'orizzonte di previsione è calcolato dalla calibrazione come `ceil(1,2 × stima del completamento più lento)`.

Gli eventi considerano avvicinamento all'eclissi e previsione di sovraccarico. La soglia risorse è 80%, con persistenza di 30 campioni; la condizione si azzera sotto 70% per 60 secondi. La rampa sintetica della sorgente va dal 55% all'85% su due orizzonti.

I candidati devono avere contatto diretto e risorse sufficienti; il ranking scarta i candidati senza nodi raggiungibili o con una delle risorse libere dopo il posizionamento inferiore alla riserva. Lo score è:

`100 × (0,35 × latenza + 0,30 × connettività + 0,20 × continuità + 0,15 × risorse)`

Le quantità nella formula sono utilità tra 0 e 1: latenza inversamente normalizzata tra candidati eleggibili dello stesso evento; connettività come frazione di nodi raggiungibili; continuità come tempo fino alla perdita del controllo diviso per l'orizzonte, limitato a 1; risorse come margine minimo di CPU/RAM/disco sopra la riserva, normalizzato. Se le latenze coincidono, l'utilità di latenza è 1 per tutti. A parità di score prevalgono distanza FSO minore e poi NORAD ID minore.

La selezione congela tre eventi reali del modello vicini ai percentili P10/P50/P90 del margine orbitale. I percentili sono calcolati sugli eventi qualificati, non sui campioni di ogni secondo. I tre eventi devono essere distinti; se gli eventi eleggibili sono meno di tre, il gate fallisce senza sostituire implicitamente la costellazione.

## 4. Sequenza delle migrazioni

Ogni prova prepara il laboratorio e raccoglie una baseline prima del trigger; dopo la migrazione continua l'osservazione per un massimo di ulteriori 30 secondi, entro la durata del replay e salvo interruzione.

### Cold

1. Prepara B in standby e completa l'allineamento continuo del contatto.
2. Quiesce A ed esporta lo snapshot iniziale dello stato.
3. Segna l'inizio del downtime e arresta il workload su A.
4. Trasferisce il bundle delle sei immagini e lo snapshot; verifica ricevute e checksum.
5. Avvia il workload su B e ripristina lo stato iniziale attraverso le API.
6. Verifica equivalenza dello stato applicativo e disponibilità dello stato P4 standby.
7. Registra ACK, esegue il cutover e registra il completamento.

Nel codice live il downtime cold inizia subito prima della chiamata di arresto di A, dopo lo snapshot. Il tempo totale inizia al trigger e include l'allineamento.

### Hot

1. Prepara B, allinea il contatto ed esporta lo snapshot iniziale mentre A resta attivo.
2. Trasferisce immagini e snapshot, avvia B e ripristina lo stato iniziale in standby.
3. Segna l'inizio del downtime e congela A.
4. Esporta nuovamente A e calcola un delta contenente aggiunte, modifiche e cancellazioni rispetto allo snapshot iniziale.
5. Trasferisce e applica il delta su B.
6. Verifica equivalenza API e stato P4 standby, registra ACK ed esegue cutover.

Il downtime hot comprende freeze, snapshot finale, delta, verifica e cutover; la pre-copy è fuori dal downtime ma dentro il tempo totale. Il confronto va effettuato sulle misure salvate, non assumendo un rapporto fisso tra i due protocolli.

### Errori e recupero

Il trasferimento usa un timeout di mancato avanzamento di 120 secondi; sono ammessi al massimo tre tentativi complessivi. Dopo una copia interrotta il payload riparte da zero. Ogni fase controlla interruzione e scadenza operativa.

In caso di errore l'ACK corrente viene revocato, B viene disattivato e si tenta di recuperare A se ancora entro la scadenza. Se il fencing della destinazione o il recupero della sorgente falliscono, i retry si fermano e resta `recovery_required`. Un ACK storico non certifica che il cutover finale sia riuscito.

## 5. Avvio e uso del frontend

Avviare Docker Desktop con engine Linux per le operazioni live. Preparazione degli stack, override delle patch e laboratorio P4 sono descritti in [teraflow-compose.md](teraflow-compose.md). Per aprire soltanto la console:

```powershell
cd teraflow-migration-sim
.\.venv\Scripts\python.exe tools/serve_gui.py
```

Aprire **http://127.0.0.1:18092/**. Il server ascolta il loopback; il frontend ottiene automaticamente la sessione e il token per inviare comandi. Non serve compilare un'app JavaScript. La vecchia dashboard 8081 e `/legacy` sono state rimosse.

| Area del frontend | Come usarla e cosa significa |
| --- | --- |
| Laboratorio | Leggere disponibilità di Mininet, API A/B, proxy P4, autorità e ACK corrente. API disponibile non significa servizio funzionante. |
| Operazione | Scegliere il comando e premere **Avvia job**. Per **Singola migrazione**, selezionare cold/hot, 100 Mbit/s, 1 Gbit/s o 10 Gbit/s, ed eventualmente un evento congelato. L'evento predefinito è diagnostico funzionale. |
| Job e storico | Scegliere un job per seguirne stato e timeline persistente. **Interrompi** agisce sul job che occupa il laboratorio; attendere fencing e recupero. |
| Topologia del servizio | Selezionare una prova; A è la sorgente, B la destinazione tratteggiata, i nodi distinguono luce/ombra. Il layout per piano non è una mappa geografica in scala. La linea blu mostra il percorso geometrico, non una conferma di forwarding. |
| Replay storico | Nelle prove concluse con geometria salvata, usare il cursore per esaminare l'istante orbitale. Il replay non riavvia né pausa una prova live. |
| Campagna principale | Le celle rappresentano 3 eventi × 2 modalità × 3 throughput = 18 casi. Cliccare una cella eseguita per leggerne il dettaglio. Una cella assente non indica successo. |
| Risultati misurati | Filtrare per modalità e tipo di prova; cliccare l'identificativo della prova per vedere tempi, baseline, sonde, byte e motivo di fallimento. Il grafico GUI mostra al massimo 12 prove filtrate con downtime disponibile. |
| Fasi, score e trasferimenti | Espandere il dettaglio JSON per evento, operazioni, ricevute di trasferimento e sonde. |
| Artefatti e report | Scaricare i file registrati, restringendo l'ambito alla prova selezionata e agli artefatti generali oppure mostrando tutto. |

Lo stato viene aggiornato ogni 5 secondi; **Aggiorna** forza una nuova lettura. La timeline usa SSE e si riconnette con il cursore dell'ultimo evento. Una prova selezionata e un job selezionato possono appartenere a esecuzioni differenti: controllare entrambi gli identificativi.

## 6. Workflow per produrre risultati e report

Per una prova esplorativa selezionare **Singola migrazione**, scegliere modalità e throughput e avviare il job. Le prove funzionali non occupano una cella della campagna principale.

Per il workflow sperimentale usare **Sequenza completa dei gate**, oppure eseguire le fasi nell'ordine seguente:

1. **Verifica ambiente e trasporto**: controlla stack, laboratorio e trasferimenti ai tre throughput configurati.
2. **Calibrazione**: richiede sei migrazioni funzionali riuscite, tre per modalità, da cui derivare dimensioni, tempi e risorse misurate.
3. **Selezione e congelamento eventi**: genera gli eventi, seleziona P10/P50/P90 e registra i checksum di configurazioni, codice e artefatti.
4. **Diagnostica dei guasti**: esegue dieci casi separati, cold/hot per perdita FSO, assenza di avanzamento, checksum errato, avvio destinazione e restore API.
5. **Campagna**: verifica gli artefatti congelati ed esegue i 18 casi, in ordine evento → cold/hot → throughput crescente.
6. **Diagnostica del ranking**: usa un evento con più candidati, se disponibile, altrimenti registra la mancata esecuzione motivata.
7. **Analisi di sensibilità**: varia parametri nel modello calibrato; produce risultati modellati separati dalle misure live.
8. **Genera report**: aggrega i metadata già salvati e produce HTML, JSON, CSV e figure disponibili.

La sequenza completa si ferma al primo gate non superato e genera un report parziale. Il comando di report può essere eseguito anche autonomamente: non completa le prove mancanti e non lancia una nuova simulazione. Dopo nuove prove va rigenerato.

Gli equivalenti CLI, dalla directory del progetto, sono:

```powershell
.\.venv\Scripts\python.exe tools/experiment.py run --method hot --rate-bps 1000000000 --wait
.\.venv\Scripts\python.exe tools/experiment.py complete --wait
.\.venv\Scripts\python.exe tools/experiment.py report --wait
```

Ogni comando restituisce un job; `--wait` segue il worker. Chiudere il browser o il server HTTP lascia il worker operativo. Il clock live non è pausabile. **Recupera job dopo crash** è riservato a un worker morto con lock persistente: non rimuovere il lock manualmente e non usarlo per sostituire l'interruzione di un worker vivo.

## 7. Struttura dei risultati

| Percorso | Contenuto |
| --- | --- |
| `results/jobs/job-*/job.json` | Comando, parametri, stato e informazioni del worker. |
| `results/jobs/job-*/result.json` | Risultato restituito dall'operazione, se disponibile. |
| `results/jobs/job-*/events.jsonl`, `worker.log` | Timeline progressiva e log del worker. JSONL contiene un oggetto JSON per riga. |
| `results/runs/run-*/inputs.json` | Evento, modalità, throughput, scenario, bundle, finalità e guasto eventualmente iniettato. |
| `results/runs/run-*/metadata.json` | Documento principale della prova: esito, ACK, tentativi, tempi, byte, operazioni, sonde, risorse e limiti. |
| `results/runs/run-*/summary.csv` | Riepilogo tabellare della singola prova. |
| `results/runs/run-*/operation/` | Eventi delle fasi, checkpoint della macchina a stati, snapshot, delta e metadata della migrazione. |
| `results/runs/run-*/geometry.jsonl`, `heartbeat.jsonl`, `authority.jsonl`, `operations.jsonl`, `resources.jsonl` | Osservazioni temporali per replay e analisi, quando disponibili. |
| `results/runs/run-*/classified-probes.jsonl` | Sonde correlate con geometria e raggiungibilità del controllo. |
| `results/lab/run-*/` | Log grezzi delle sonde ping/UDP. |
| `results/calibration.json`, `events.json`, `campaign.json`, `fault-campaign.json`, `sensitivity.json`, `workflow.json` | Risultati delle fasi, quando eseguite. |
| `config/campaign-manifest.json` | Provenienza e checksum congelati prima della campagna. |

Gli artefatti effettivamente presenti dipendono dalla fase raggiunta. I download GUI espongono solo percorsi registrati. Il bundle ricevuto duplicato viene rimosso dopo l'uso per contenere il disco; restano il bundle sorgente e le ricevute.

## 8. Struttura del report generato

Il generatore scrive in `results/report/`. Non produce automaticamente DOCX o PDF.

| File | Struttura e uso |
| --- | --- |
| `index.html` | Report leggibile: numero di prove principali registrate su 18, interpretazione, limiti, tabella dei run e grafici disponibili. Aprirlo localmente insieme alle figure nella stessa cartella. |
| `report.json` | `schema_version`, `created_utc`, elenco completo `runs`, `primary_count`, `expected_primary_count`, `primary_complete`, `unique_primary_cases`, interpretazione e limiti di misura. |
| `runs.csv` | Una riga per metadata di prova, incluse calibrazioni, diagnostiche e guasti; adatto a fogli di calcolo e analisi. |
| `controller-downtime.svg` | Downtime del controller per run con misura disponibile. |
| `service-recovery.svg`, `throughput.svg`, `retries.svg`, `disk-content.svg`, `contact-margin.svg` | Grafici prodotti se ci sono valori disponibili per la rispettiva metrica. |
| `phase-durations.svg` | Tempi misurati per operazione; alcune attività possono essere concorrenti, quindi non sommare indiscriminatamente tutte le barre come tempo totale. |

Le figure richiedono `matplotlib`. Se non è installato, il report resta disponibile e il JSON registra `plot_unavailable`. I dati mancanti non sono trasformati in zero.

Le colonne del CSV aggregato sono, nell'ordine: `run_id`, `purpose`, `method`, `configured_rate_bps`, `outcome`, `success`, `ack`, `total_operation_s`, `controller_downtime_s`, `image_throughput_bps`, `attempt`, `bytes_sent`, `bytes_received`, `restarted_payload_bytes`, `failure_reason`. Nel report HTML la tabella mostra un sottoinsieme: run, finalità, modalità, throughput configurato, esito e downtime controller.

`primary_complete` controlla che esistano esattamente 18 combinazioni distinte di evento/modalità/throughput e che i run principali non siano in esecuzione. Non significa che tutte le migrazioni siano riuscite, né certifica tutti i gate: verificare anche `outcome`, `success`, risultati dei gate e `workflow.json`.

Per condividere l'HTML scaricare anche gli SVG associati, conservando i nomi nella stessa cartella. È possibile stampare l'HTML dal browser in PDF; questa è una conversione manuale, non un formato prodotto dal generatore.

## 9. Come interpretare le metriche

- **Esito**: `success`, `experimental_failure`, `invalid_lab`, `interrupted` o `recovery_required`. Un job `completed` indica che il worker ha restituito un risultato; un gate può comunque riportare `complete: false`.
- **Tempo totale**: dal trigger al completamento della migrazione; comprende allineamento e pre-copy.
- **Downtime controller**: intervallo segnato dalla macchina a stati fino al completamento del cutover. È distinto dalla continuità del servizio dati.
- **Recupero servizio**: tempo dalla prima perdita fino alla conferma di recupero stabile, con dieci successi consecutivi. È attribuibile solo con baseline disponibile; se non misurabile resta nullo. Il campo GUI chiamato downtime servizio deriva da questa metrica e include l'attesa della conferma.
- **Throughput effettivo**: byte del payload immagine e durata osservati dal trasferimento; nelle prove principali un valore inferiore al 90% del configurato rende la prova `invalid_lab`.
- **Retry**: `attempt - 1`; i byte reinviati per ripartenza del payload sono distinti dalle ritrasmissioni TCP, che non sono disponibili come misura.
- **Margine di contatto**: finestra residua al trigger meno durata totale dell'operazione. Non va confuso con il margine orbitale usato per selezionare gli eventi.
- **Sonde classificate**: servizio disponibile, assenza di percorso geometrico, perdita con percorso disponibile oppure geometria sconosciuta. La raggiungibilità del controllo è un'informazione separata.

Il daemon Docker è condiviso: il caricamento immagini può riutilizzare layer locali e non prova un'importazione su un daemon indipendente. Il disco contabilizza il contenuto logico dei layer unici del workload e delle dipendenze, writable layer e volumi; esclude overhead di allocazione del filesystem.

La campagna ha una replica per combinazione: permette il confronto dei casi rappresentativi ma non una conclusione di significatività statistica. Per lo stato scientifico effettivo usare le evidenze salvate e [implementation-status.md](implementation-status.md), non la sola presenza di un grafico o il fatto che il codice della campagna esista.

## 10. Riferimenti al codice e verifica della rimozione

Questa descrizione è ricavata da `web/index.html`, `web/app.js`, `src/web.py`, `src/jobs.py`, `src/experiment.py`, `src/orchestrator.py`, `src/live_backend.py`, `src/preparation.py`, `src/score_model.py`, `src/event_sampling.py`, `src/probes.py`, `src/analysis.py`, `src/report_plots.py` e `config/scenario.json`.

Dopo la rimozione della vecchia applicazione, la suite host del nuovo progetto ha eseguito 58 test: 53 superati e 5 saltati perché richiedono i protobuf P4 del container Linux. Docker Desktop non era attivo durante questa verifica: non è stata effettuata una nuova migrazione live né la pulizia degli eventuali container della vecchia applicazione presenti nel motore.

### Aggiornamento della verifica live del 14 ottobre 2026

I dieci container, le quattro immagini e la rete della precedente applicazione sono stati successivamente rimossi dal motore. Il laboratorio TeraFlow/P4 e la console 18092 sono stati riavviati; il job interrotto è stato recuperato attraverso il motore.

Sono stati corretti il recupero della pipeline P4 dopo il riavvio di BMv2 e il timeout di importazione immagini Docker, ora limitato a 600 secondi e alla scadenza orbitale residua. La suite aggiornata esegue 64 test host (56 superati e 8 saltati); gli otto test P4 passano nel container.

La prova hot funzionale `run-c680093ed93447bcb7a5b6323c6dd7c8`, a 1 Gbit/s, è riuscita al primo tentativo con trasferimenti verificati, equivalenza API, ACK e cutover. Downtime controller: **20,94 s**; durata totale: **627,65 s**, inclusi **460,27 s** di importazione del bundle in Docker. Throughput utile immagini: **999,27 Mbit/s**. Dopo il cutover: **320 ping riusciti su 320**. Il controller attivo è SAT-B, il lock è libero e la console resta disponibile.

La baseline iniziale del servizio nella prova era indisponibile: il recupero del servizio resta non attribuibile alla migrazione. La verifica preliminare indipendente aveva dato 50/50 ping riusciti e traffico UDP ricevuto. Questa verifica dimostra il funzionamento della migrazione hot e del forwarding dopo il cutover; non completa la calibrazione o la campagna di 18 casi e non include una nuova prova cold.

Il report dei risultati è stato rigenerato in `results/report/index.html`. L'evidenza dei controlli finali è in `results/runtime-verification-2026-10-14.json`; i metadata dettagliati restano nella directory della prova.
