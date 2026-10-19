# Console e workflow sperimentale

## Confronto continuo Hot/Cold nella console

La console mostra un solo avvio: imposta la durata **per modalità** e premi «Avvia confronto Hot/Cold». Il sistema verifica i prerequisiti, ammette una sequenza comune, esegue Hot, ripristina il laboratorio ed esegue Cold sugli stessi eventi. Report e confronti vengono salvati automaticamente. Vedi la [guida dedicata](paired-continuous.md). Gli strumenti sperimentali precedenti restano disponibili tramite CLI.

## Confronto FSO singolo tramite CLI

Dalla directory del progetto, avviare il laboratorio con `.\.venv\Scripts\python.exe tools/stack.py up` e la console con `.\.venv\Scripts\python.exe tools/serve_gui.py`. Per il confronto FSO singolo usare `.\.venv\Scripts\python.exe tools/experiment.py functional --wait`.

Un solo job seleziona e conserva un evento FSO diagnostico lungo, poi esegue hot e cold a 1 Gbit/s dallo stesso secondo orbitale e dalla stessa fixture. Entrambe le prove trasferiscono il bundle completo via TCP. La ricostruzione iniziale separa le due esecuzioni; non serve completare la calibrazione per questa verifica funzionale.

La baseline ammette la prova solo con API sorgente, autorità P4 e dieci ping freschi consecutivi. Il successo richiede equivalenza dello stato API, ACK/cutover, autorità della destinazione e dieci ping freschi consecutivi dopo il cutover. UDP resta disponibile nei log senza bloccare il gate. La coppia si interrompe al primo esito non valido o non riuscito, conservando il motivo e gli eventuali requisiti di recupero.

Il riepilogo mostra downtime controller, tempo dalla prima perdita alla conferma stabile dei ping, durata totale della migrazione e tentativi. Le differenze sono cold meno hot. Nessuna perdita osservata e misura non disponibile sono etichette distinte; non si inventano zeri. Gli identificativi e le misure di entrambe le prove sono salvati in `results/comparisons/compare-*/metadata.json`, nel risultato del job e nel riepilogo aggiornato `results/functional-gate.json`. Selezionando un job di confronto concluso si vedono le sue misure, anche dopo confronti successivi.

La simulazione continua e gli altri strumenti restano nelle **Funzioni avanzate**; la matrice di campagna è richiudibile. Una sola coppia valida il funzionamento del flusso e non costituisce una campagna di ricerca conclusa.

> Aggiornamento 16 ottobre 2026: il percorso principale è **Confronto FSO hot/cold**, su un evento a 1 Gbit/s con verifica API e ping. Simulazione continua e campagne rimangono funzioni avanzate con validazione separata. Avvio e criteri di successo sono nella [guida operativa](operating-guide.md).

La console indipendente è disponibile su **http://127.0.0.1:18092/**. Da questa directory:

La console sulla porta 18092 è l'unico frontend del progetto. La precedente dashboard Docker sulla porta 8081, la route `/legacy` e il relativo proxy sono stati rimossi. Avviare la GUI dalla directory `teraflow-migration-sim`; il worker è gestito dal motore sul computer.

```powershell
python tools/serve_gui.py
```

Se si usa l'ambiente locale del progetto, installare prima le dipendenze e avviare il laboratorio da questa directory:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt matplotlib
.\.venv\Scripts\python.exe tools/stack.py up
.\.venv\Scripts\python.exe tools/serve_gui.py
```

Questi comandi presuppongono le immagini già costruite e gli artefatti del laboratorio presenti. `matplotlib` abilita le figure del report; NumPy e Astropy appartengono alle dipendenze dichiarate del progetto. Se è rimasto un lock di un worker morto, eseguire `tools/experiment.py recover --wait` con lo stesso interprete prima di nuove prove. Il recupero di un job ormai oltre la scadenza orbitale termina con i controller fenced: la nuova prova ricostruisce il proprio scenario.

Docker Desktop mostra SAT-A, SAT-B e Mininet/P4 in un unico gruppo **teraflow**. `tools/stack.py status` mostra tutti i container; `tools/stack.py stop` li ferma insieme; `tools/stack.py down` rimuove i container e le reti ma conserva i volumi e i risultati. I comandi di gestione rifiutano modifiche mentre un job o un recupero occupa il lock. La console Python resta sul computer, sulla porta 18092.

Usa Python con le dipendenze di `requirements.txt` installate e Docker Desktop con engine Linux avviato. Il server ascolta soltanto il loopback. Le API `/api/v1` applicano same-origin, verifica Host e token di sessione per i comandi. Non pubblicare la porta sulla rete.

## Operazioni condivise tra CLI e GUI

```powershell
python tools/experiment.py environment
python tools/experiment.py run --method cold --rate-bps 1000000000
python tools/experiment.py run --method hot --rate-bps 1000000000
python tools/experiment.py calibrate
python tools/experiment.py select
python tools/experiment.py faults
python tools/experiment.py campaign
python tools/experiment.py diagnostic
python tools/experiment.py sensitivity
python tools/experiment.py report
```

`complete` esegue queste fasi in ordine, fermandosi al primo gate non superato e producendo un report parziale. La calibrazione richiede sei prove funzionali riuscite. La selezione non cambia costellazione o finestra quando mancano tre eventi selezionabili. `campaign` verifica i checksum congelati prima delle 18 prove, nell'ordine evento → cold/hot → throughput crescente. Un valore configurato non sostenuto dal trasporto produce `invalid_lab`.

Ogni comando avvia un worker indipendente e restituisce un identificativo `job-*`. Aggiungere `--wait` per seguire la CLI. Un lock persistente ammette un solo job sul laboratorio. Chiudere il browser o riavviare il server HTTP lascia il worker in esecuzione.

```powershell
python tools/experiment.py jobs
python tools/experiment.py stop --job-id job-IDENTIFICATIVO
python tools/experiment.py recover
```

L'interruzione richiede fencing e recupero. Attendere l'esito prima di avviare altre operazioni. `recover` è riservato al worker morto con lock ancora presente: revoca l'autorità, arresta B e verifica il recupero di A se ancora operativo. Non rimuovere manualmente il lock per aggirare un recupero necessario. Dopo scadenza di A resta registrata l'indisponibilità. Il clock live non è pausabile.

## Dove leggere i risultati

- `results/jobs/job-*/`: stato, risultato dell'operazione, eventi progressivi JSONL e log del worker.
- `results/runs/run-*/metadata.json`: esito della prova, ACK corrente, tentativi, tempi, byte, API, risorse e limiti di misura.
- Nella stessa directory: snapshot/delta, checkpoint, timeline, geometria, heartbeat, autorità, sonde classificate e riepilogo CSV.
- `results/lab/run-*/`: ping e UDP grezzi; `results/report/`: report HTML, JSON, CSV e figure SVG.
- `results/calibration.json`, `results/events.json`, `results/campaign.json`, `results/fault-campaign.json`, `results/sensitivity.json`: risultati delle rispettive fasi quando eseguite.
- `config/campaign-manifest.json`: checksum di configurazioni, codice, fixture, patch, immagini, tracciati orbitali e calibrazione congelati.

Nella GUI scegliere il job per la timeline SSE, e la prova per topologia, trasferimenti, sonde e download. La timeline viene riletta dal registro persistente e usa identificativi progressivi per la riconnessione. Le prove concluse consentono il replay della geometria salvata. Il percorso blu è geometrico: il forwarding reale è verificato dalle sonde indipendenti. Un controller irraggiungibile non implica necessariamente perdita del forwarding.

## Interpretazione

Gli esiti sono `success`, `experimental_failure`, `invalid_lab`, `interrupted` e `recovery_required`. Il completamento del job indica che il worker ha restituito un risultato: controllare anche `complete`/`success` nel risultato del gate. Una prova funzionale o di calibrazione non occupa una cella della campagna principale.

TCP, API, operazioni Docker, P4Runtime e sonde sono misurati live; orbite, FSO e carico sintetico sono modellati. L'importazione immagini usa un daemon Docker condiviso e può riutilizzare layer locali; non dimostra importazione su un daemon indipendente. L'inventario immagini modellato per host rimane separato. I byte reinviati nei retry non sono ritrasmissioni TCP: queste ultime restano esplicitamente non disponibili.

Il disco misura il contenuto logico dei layer unici di workload e dipendenze, più writable layer e volumi del progetto; esclude overhead di allocazione del filesystem. L'archivio temporaneo usato per questa contabilità non fa parte del payload: il trasferimento immagini resta esclusivamente il bundle unico delle sei immagini autorizzate.

Non attribuire downtime alla migrazione se la baseline del servizio era già indisponibile. Perdite con percorso geometrico disponibile, assenza di percorso e controllo irraggiungibile sono registrati separatamente. I grafici riassumono casi rappresentativi con una replica: non supportano inferenza statistica.

Le misure parziali e le interruzioni vengono conservate. Un report disponibile prima del completamento dei quattro gate è un report preliminare.
