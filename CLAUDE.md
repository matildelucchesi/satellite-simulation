# Sviluppare il laboratorio TeraFlowSDN

## Regole del repository

- Leggi [AGENTS.md](AGENTS.md). Implementa modifiche solo con un livello di confidenza di almeno il 95%. Se un requisito resta ambiguo dopo aver letto codice, configurazione e test, chiedi chiarimenti.
- Graphify è disattivato. Usa ricerche e letture dirette con `rg` e `rg --files`. Non usare Graphify e non rigenerarne gli output.
- Parti da `git status --short` e dal diff dei file rilevanti. Il worktree può contenere modifiche in corso e risultati sperimentali tracciati. Preservali.
- Prima di modificare un comportamento, identifica il punto d'ingresso reale, i test che lo coprono e gli eventuali formati persistiti che deve continuare a leggere.

## Scopo e percorso attuale

Il laboratorio confronta due strategie di migrazione del controller ETSI TeraFlowSDN 7.0.0 fra satelliti LEO. La simulazione riproduce geometria, illuminazione, contatti FSO e risorse a partire da TLE e parametri fissati. Il laboratorio esegue realmente le chiamate API, i trasferimenti TCP e il forwarding Mininet/BMv2 con P4Runtime. I risultati misurano il laboratorio e dipendono dai suoi vincoli, incluso l'eventuale daemon Docker condiviso.

- **Hot** prepara immagini e stato iniziale sulla destinazione mentre la sorgente controlla ancora la rete. Dopo il freeze trasferisce e applica il delta, verifica e passa l'autorità.
- **Cold** salva lo stato, arresta la sorgente prima del trasferimento e ripristina sulla destinazione. La misura di indisponibilità del controller include il lavoro successivo all'arresto fino al passaggio.
- **Confronto guidato** è il percorso principale della console. L'utente sceglie il rate utile TCP fra 100 Mbit/s, 1 Gbit/s e 10 Gbit/s. Il motore sceglie satellite e istante iniziali e costruisce un piano condiviso. La sequenza è Hot → Ripristino → Cold, con obiettivo di tre migrazioni verificate per modalità. Il tempo orbitale resta fermo durante la preparazione.
- **Confronto FSO singolo**, avviato con `functional`, verifica Hot e Cold su un evento. `simulate` esegue una sessione continua singola. La campagna, le prove di guasto e la sensitivity hanno percorsi e criteri di accettazione propri.

Usa il [README principale](README.md) e la [guida al flusso guidato](teraflow-migration-sim/docs/guided-flow.md) per il comportamento attuale. La documentazione datata e il README applicativo contengono anche profili e procedure storiche. Per un valore operativo specifico controlla configurazione e codice. Per un esito controlla le evidenze del job corrispondente.

## Struttura e punti d'ingresso

Il codice applicativo è in `teraflow-migration-sim/`. Salvo indicazione diversa, i percorsi e i comandi nelle sezioni seguenti partono da quella cartella.

| Area | File da leggere e responsabilità |
| --- | --- |
| Avvio | `tools/experiment.py` espone la CLI e avvia il worker. `tools/serve_gui.py` avvia la console locale. `tools/stack.py` gestisce il progetto Compose. |
| Job e persistenza | `src/jobs.py` gestisce esclusione, lifecycle del worker, annullamento e recupero. `src/storage.py` e `src/checkpoints.py` supportano la persistenza. `src/experiment.py` coordina i workflow condivisi da CLI e GUI. |
| Preparazione | `src/preparation.py` gestisce verifiche e calibrazioni. `src/common_base.py` identifica e valida una base riutilizzabile. `src/prepared_source.py` prepara e adotta lo stato operativo per il piano scelto. `src/preparation_budget.py` definisce i limiti delle sottofasi. `src/fixture.py` costruisce e riconcilia lo scenario. |
| Pianificazione | `src/automatic_start.py`, `src/planner.py` e `src/continuous_comparison.py` implementano ricerca iniziale, ammissione e piano comune. `src/simulation.py` esegue la sessione con il clock di `src/clock.py`. |
| Modello | `src/orbit.py`, `src/constellation.py`, `src/events.py` ed `src/event_sampling.py` trattano orbite, contatti ed eventi. `src/resource_model.py`, `src/score_model.py` e `src/migration_model.py` stimano ammissibilità, ranking e tempi. |
| Migrazione live | `src/orchestrator.py` governa la macchina a stati. `src/live_backend.py` collega Compose, API, link e sonde. `src/tfs_adapter.py` implementa accesso e riconciliazione TeraFlow. `src/snapshot.py`, `src/transport.py` e `src/artifacts.py` trattano snapshot, delta, TCP e verifica degli input. |
| Autorità e servizio | `src/authority.py`, `src/handover.py` e `src/p4_proxy.py` gestiscono fencing, verifica e commit del passaggio. `src/emulator.py` e `src/link_control.py` applicano i collegamenti nel lab. `src/probes.py` e `src/measurements.py` gestiscono osservazioni e misure. |
| Risultati | `src/results.py`, `src/analysis.py`, `src/simulation_report.py` e i moduli di plotting producono riepiloghi e report a partire dalle evidenze. |
| Console | `src/web.py` serve file statici e API locali sotto `/api/v1/`. `web/app.js` integra interazioni, stato e rendering. `web/experiment-state.js` deriva lo stato del flusso. `web/orbit-view.js` gestisce la vista orbitale. HTML, CSS e font sono locali. |

## Ambiente e verifiche locali

Il percorso documentato usa Windows, PowerShell e Python 3.13. Per il live servono Docker Desktop con motore Linux, Docker Compose e i materiali congelati del laboratorio. Node.js serve per le suite JavaScript. Il frontend usa file statici e può essere avviato direttamente dal server Python.

Dalla radice del repository, su una postazione da preparare:

```powershell
Set-Location teraflow-migration-sim
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Dalla cartella applicativa, con ambiente già installato:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/test_experiment_state.cjs tests/test_orbit_motion.cjs
.\.venv\Scripts\python.exe tools/experiment.py --help
```

Per restringere la verifica Python usa ad esempio `-m unittest discover -s tests -p 'test_prepared_source.py' -v` dopo il percorso dell'interprete. Le dipendenze Python, fra cui SGP4, Astropy, NumPy, PyYAML e Matplotlib, sono fissate in `requirements.txt`. Alcuni test P4 richiedono i protobuf dell'ambiente Linux del lab e possono essere saltati sull'host. Distingui i risultati dei test locali dai preflight di laboratorio e dalle prove sperimentali.

Se la sandbox Windows restituisce `WinError 5` nelle directory temporanee dei test, punta `TMP` e `TEMP` a una cartella scrivibile del workspace. Da PowerShell, nella cartella applicativa:

```powershell
New-Item -ItemType Directory -Force ..\.test-tmp | Out-Null
$env:TMP = (Resolve-Path ..\.test-tmp).Path
$env:TEMP = $env:TMP
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

I test di trasporto e della console usano socket locali. Se compare `WinError 10013`, verifica che l'ambiente di test consenta connessioni TCP su loopback.

## Configurazione e laboratorio live

- `config/scenario.json` definisce profilo orbitale, modello delle risorse, FSO, scoring e sonde. Il profilo corrente `real-450-580-64` usa 64 satelliti reali in due gruppi da 28 e 36, replay da 86.400 s a passi da 1 s, range FSO di 1.700 km e allineamento di 60 s. Leggi anche `config/selected_constellation.json` e `data/starlink_2026-10-01.tle`.
- `config/fixture.json` definisce lo scenario di rete. `config/artifact_manifest.json` registra immagini, bundle e misure. `config/teraflow-source.json` identifica la sorgente TeraFlow e `config/lab-manifest.json` identifica materiali del lab. Il template del manifest serve alla compilazione dei dati, mentre la prova richiede i valori effettivi.
- Il progetto Compose `teraflow` usa `deploy/stack.yaml` e `deploy/lab.env`. La definizione Compose in radice include lo stesso stack. SAT-A e SAT-B hanno reti e persistenze separate. Il lab usa Mininet, BMv2 e un proxy P4Runtime. Le NBI locali rispondono sulle porte 18080 e 18081, la console sulla 18092.
- L'avvio usa immagini già disponibili. Una nuova copia Git può richiedere bundle locali in `artifacts/`, input di build in `.reference/`, immagini e file P4. Le varianti Service e Device con patch sono parte del laboratorio. Segui la [guida Compose](teraflow-migration-sim/docs/teraflow-compose.md) per riprodurre o ripristinare questi materiali e mantieni la corrispondenza con digest, checksum e percorsi registrati.

```powershell
docker version
docker compose version
docker compose --env-file deploy/lab.env -p teraflow -f deploy/stack.yaml config --quiet
docker compose --env-file deploy/lab.env -p teraflow -f deploy/stack.yaml config --images
.\.venv\Scripts\python.exe tools/stack.py up
.\.venv\Scripts\python.exe tools/stack.py status
.\.venv\Scripts\python.exe tools/serve_gui.py
```

Con laboratorio predisposto e libero, apri [la console locale](http://127.0.0.1:18092/) oppure esegui da un altro terminale `tools/experiment.py compare_continuous --rate-bps 1000000000 --wait` con l'interprete dell'ambiente. Il launcher `tools/start_gui.cmd` avvia il server della console. Un confronto può durare ore. Mantieni PC, sessione Windows e Docker attivi. Il worker sopravvive alla chiusura della scheda.

## Invarianti per le modifiche

### Preparazione e confronto

- CLI e GUI devono mantenere lo stesso contratto per il confronto automatico. La partenza e la durata risultano dal piano e dal numero di migrazioni obiettivo. `--duration-s` non imposta la durata di `compare_continuous`.
- Quando servono nuove misure, si prepara prima la rete completa, si verifica il servizio e si eseguono le prove funzionali necessarie e le calibrazioni Cold e Hot. Le calibrazioni precedenti richiedono compatibilità di implementazione, artefatti e baseline.
- La preparazione incrementale conserva i dispositivi compatibili, riconcilia scenario e servizio per il tick richiesto e verifica nuovamente API, autorità e ping. Connessioni dei dispositivi incompatibili richiedono ricostruzione. Controlla `test_calibration_network.py`, `test_prepared_source.py`, `test_common_base.py` e `test_preparation_progress.py`.
- La ricerca di partenza valuta l'intera sequenza e la disponibilità del percorso geometrico del servizio. Ha un budget separato, attualmente 600 s. Una ricerca parziale può restituire un piano già verificato. L'assenza di un piano trovato entro il budget è distinta da un esito negativo esaustivo. Hot e Cold devono usare lo stesso piano verificato e mantenere la sua identità nei risultati.

### Migrazione, verifica e recupero

- Preserva l'autorità esclusiva e la separazione fra stato P4 staged e scritture attive. Consenti ACK e cutover dopo verifica del trasferimento e dell'equivalenza API. I test devono coprire anche l'assenza di ACK quando copia, staging o verifica falliscono.
- Preserva deadline orbitali, timeout per assenza di progresso e budget delle sottofasi. In caso di perdita del link, il trasferimento ricomincia da zero. Un recupero che fallisce nel fencing della destinazione o nel ripristino della sorgente ferma i retry.
- I contatti chiusi sono emulati con perdita `tc netem` al 100% nelle due direzioni. Tenere attive le interfacce evita la regressione BMv2 osservata quando una porta viene abbassata amministrativamente.
- Per il servizio verifica una baseline fresca e una sequenza di almeno dieci ping freschi consecutivi per il ripristino. UDP è diagnostico. Registra separatamente durata dell'operazione, downtime del controller, perdita e ripristino del forwarding. Mantieni le misure assenti come tali e calcola Cold−Hot solo quando gli eventi e le metriche sono confrontabili.
- Il laboratorio accetta un solo job alla volta. Per interrompere usa la console oppure `tools/experiment.py stop --job-id job-IDENTIFICATIVO`. Per controllare usa `tools/experiment.py jobs`. Quando serve il recupero usa **Ripristina laboratorio** o il comando `tools/experiment.py recover` secondo la guida operativa. Conserva il lock finché la messa in sicurezza è verificata.
- Mantieni distinti heartbeat, ultimo progresso e limite della fase. Uno stato del worker `completed` descrive il lifecycle del processo. Verifica separatamente esito applicativo, esiti dei figli e completamento del recupero. Per modifiche web preserva sessione, controlli same-origin, replay SSE e registro dei download.

## Evidenze e debug

| Percorso relativo all'applicazione | Uso |
| --- | --- |
| `results/jobs/job-*/` | Stato, eventi e log del worker. Prima tappa per errori, annullamenti, recupero e lock. |
| `results/continuous-comparisons/pair-*/` | Identità e hash del piano condiviso, esito del confronto, CSV e report HTML. |
| `results/simulations/sim-*/` | Sessione continua per modalità e progressione orbitale. |
| `results/runs/run-*/` | Input e prove della singola migrazione, tentativi, baseline, autorità e verifica del servizio. |
| `results/comparisons/compare-*/` | Confronto funzionale FSO su un evento. |
| `results/calibration.json` e `results/calibration-progress.json` | Misure registrate e avanzamento della calibrazione. Leggili insieme all'identità degli input. |
| `results/guided-validation/` | Riepiloghi del verificatore del flusso guidato. |

Per verificare un confronto salvato usa `tools/validate_guided_flow.py --comparison pair-IDENTIFICATIVO` con l'interprete Python locale. L'opzione `--live` avvia invece un collaudo delle tre velocità in sequenza, si ferma al primo errore e occupa il laboratorio. Riserva le prove live ai casi che richiedono Docker e traffico reale, con il laboratorio libero. Alcune evidenze sono tracciate e altre risiedono solo sulla postazione che le ha prodotte. Verifica disponibilità e provenienza prima di riportare misure.

## Letture per area

- [Guida operativa e CLI](teraflow-migration-sim/docs/operating-guide.md) e [flusso guidato](teraflow-migration-sim/docs/guided-flow.md).
- [Deployment](teraflow-migration-sim/docs/teraflow-compose.md), [adapter di stato TeraFlow v7](teraflow-migration-sim/docs/tfs-v7-state-adapter.md) e [validazione del caricamento](teraflow-migration-sim/docs/scenario-loading-validation.md).
- [Selezione orbitale](teraflow-migration-sim/docs/orbital-selection.md), [simulatore continuo](teraflow-migration-sim/docs/continuous-simulator.md) e [confronto appaiato](teraflow-migration-sim/docs/paired-continuous.md).
- [Consolidamento di esiti e metriche](teraflow-migration-sim/docs/consolidated-results.md), [validazione guidata](teraflow-migration-sim/docs/guided-flow-validation.md) e [stato storico](teraflow-migration-sim/docs/implementation-status.md).

Prima di dichiarare completata una validazione, individua job, piano, input, condizioni e repliche verificabili. Il confronto FSO singolo, una misura di preparazione incrementale e la suite locale forniscono ciascuno evidenza per il proprio caso. Per lo stato della campagna o del confronto guidato usa il riepilogo della specifica esecuzione e i relativi risultati figli.
